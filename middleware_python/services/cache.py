"""
SocialGraph Pro — 缓存服务 v2.0

实现 5 种缓存失效模式:
  1. 版本失效 (Version-Based): 数据版本号 INCR → 旧版本键自动过期
  2. 标签失效 (Tag-Based):   依赖标签映射多键 → 一键批量失效
  3. TTL 失效 (Time-Based):   每条键设置过期时间作为兜底
  4. 事件驱动 (Event-Driven): Pub/Sub 广播 → 所有 Worker 同步失效
  5. 手动失效 (Manual):       Admin API 按模式/域删除

Cache-Aside 模式:
  - 读: 先查 Redis → 命中返回 / 未命中计算并写入
  - 写: 先更新 → 再失效相关缓存
  - 防击穿: 分布式锁 SET NX EX + 轮询等待

v2.0 增强:
  - 压缩存储 (zlib, 自动阈值 > 64KB)
  - 缓存预热 (P0 启动时预热, P1 首次请求时预热)
  - TTL 随机偏移 (±10%) 防雪崩
  - 命中/未命中原子计数器
  - 标签依赖图 (Tag → Set of cache keys)
  - 数据版本号管理 (sgp:meta:data_version)
  - 旧键兼容读 (social_graph:* + sgp:* 双读)
"""

import asyncio
import json
import logging
import random
import time
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from core.config import get_settings

logger = logging.getLogger("socialgraph.services.cache")

# ── 域常量 ────────────────────────────────────────────────────
DOMAIN_GRAPH = "graph"
DOMAIN_AUTH = "auth"
DOMAIN_RATE = "rate"
DOMAIN_LOCK = "lock"
DOMAIN_SESSION = "session"

# 旧版键模式 → 新版键模式映射（向后兼容双读）
_LEGACY_PATTERNS = {
    "social_graph:": "sgp:graph:",
    "socialgraph:": "sgp:graph:",
    "blacklist:token:": "sgp:auth:blacklist:",
    "blacklist:": "sgp:auth:blacklist:",
    "rate_limit:": "sgp:rate:",
    "lock:compute:": "sgp:lock:compute:",
}


# ═══════════════════════════════════════════════════════════════════
# 辅助函数
# ═══════════════════════════════════════════════════════════════════

def _apply_ttl_jitter(base_ttl: int) -> int:
    """在 base TTL 上添加随机偏移（±jitter_percent%），防止缓存雪崩。

    Args:
        base_ttl: 基础 TTL（秒）

    Returns:
        添加 jitter 后的 TTL（秒）
    """
    settings = get_settings()
    jitter = int(base_ttl * settings.cache_ttl_jitter_percent)
    offset = random.randint(0, jitter)
    return base_ttl + offset


def _resolve_cache_key(cache_key: str) -> list[str]:
    """解析缓存键，返回 [原始键] 或 [新版键, 旧版键] 列表（用于双读）。

    如果已使用 sgp:* 前缀，直接返回单元素列表。
    如果使用旧版前缀，同时返回新版键（供优先尝试）。
    """
    for old_prefix, new_prefix in _LEGACY_PATTERNS.items():
        if cache_key.startswith(old_prefix):
            new_key = cache_key.replace(old_prefix, new_prefix, 1)
            return [new_key, cache_key]
    return [cache_key]


def _auto_detect_legacy_keys(cache_key: str) -> Optional[str]:
    """识别并转换旧版键名为新版。

    Returns:
        新版键名，若非旧版模式则返回 None。
    """
    for old_prefix, new_prefix in _LEGACY_PATTERNS.items():
        if cache_key.startswith(old_prefix):
            return cache_key.replace(old_prefix, new_prefix, 1)
    return None


# ═══════════════════════════════════════════════════════════════════
# 模式 1: 版本失效（主要策略）
# ═══════════════════════════════════════════════════════════════════

async def get_data_version(domain: str = DOMAIN_GRAPH) -> int:
    """获取指定域的数据版本号。

    数据版本号用于所有缓存键的版本标记。
    当底层数据变更时，版本号 INCR，旧版本缓存自动 TTL 过期。

    Args:
        domain: 数据域 ("graph", "auth", etc.)

    Returns:
        当前数据版本号（整数，从 1 开始）

    使用方式:
        ver = await get_data_version("graph")
        cache_key = f"sgp:graph:pagerank:v{ver}"
    """
    from db.redis import get_redis_async, redis_key

    r = await get_redis_async()
    if r is None:
        return 1  # Redis 不可用时的默认版本

    version_key = redis_key("meta", "data_version", domain)
    try:
        version = await r.get(version_key)
        if version is None:
            await r.set(version_key, "1")
            return 1
        return int(version)
    except Exception as e:
        logger.warning("获取数据版本号异常: %s", e)
        return 1


async def bump_data_version(domain: str = DOMAIN_GRAPH) -> int:
    """递增指定域的数据版本号（数据变更时调用）。

    旧版本缓存不会被立即删除，而是通过 TTL 自然过期。
    版本号存储在 sgp:meta:data_version:{domain}。

    Args:
        domain: 数据域

    Returns:
        新版本号

    使用方式:
        new_ver = await bump_data_version("graph")
        # 之后新请求会自动使用 v{new_ver} 的缓存键
    """
    from db.redis import get_redis_async, redis_key

    r = await get_redis_async()
    if r is None:
        return 1

    version_key = redis_key("meta", "data_version", domain)
    try:
        new_ver = await r.incr(version_key)
        logger.info("数据版本已更新: domain=%s, version=%d", domain, new_ver)

        # 发布版本变更事件（通知其他 Worker）
        try:
            from services.pubsub import publish_cache_invalid
            await publish_cache_invalid(domain, reason="version_bump")
        except ImportError:
            pass

        return new_ver
    except Exception as e:
        logger.warning("递增数据版本号异常: %s", e)
        return 1


async def invalidate_by_version_bump(domain: str = DOMAIN_GRAPH) -> dict:
    """通过递增版本号来失效指定域的所有缓存。

    策略: 不删除任何键，仅递增版本号。
          旧版本键自然过期（TTL），新请求使用新版本键。

    Args:
        domain: 数据域

    Returns:
        {"old_version": N, "new_version": N+1, "domain": "graph"}

    Notes:
        - 优势: 零删除操作，无阻塞
        - 劣势: 旧版本缓存占用内存直到 TTL 过期
        - 适用: 内存充裕且 TTL 较短（< 1h）的场景
    """
    old_ver = await get_data_version(domain)
    new_ver = await bump_data_version(domain)
    return {"old_version": old_ver, "new_version": new_ver, "domain": domain}


# ═══════════════════════════════════════════════════════════════════
# 模式 2: 标签失效（Tag-Based Invalidation）
# ═══════════════════════════════════════════════════════════════════

async def cache_tag_dependency(tag: str, cache_key: str) -> bool:
    """将缓存键注册到标签依赖集。

    当标签失效时，所有关联的缓存键可一键删除。

    Args:
        tag:       标签（如 "pagerank", "user:abc123"）
        cache_key: 关联的缓存键

    Returns:
        是否注册成功

    使用方式:
        await cache_tag_dependency("pagerank", "sgp:graph:pagerank:v3")
        await cache_tag_dependency("user_42", "sgp:graph:ego_network:42")
    """
    from db.redis import get_redis_async, redis_key

    r = await get_redis_async()
    if r is None:
        return False

    tag_key = redis_key("tag", tag)
    try:
        await r.sadd(tag_key, cache_key)
        await r.expire(tag_key, 604800)  # 标签集 TTL = 7 天
        return True
    except Exception as e:
        logger.warning("标签依赖注册失败 (tag=%s, key=%s): %s", tag, cache_key, e)
        return False


async def cache_tag_dependencies(tag: str, cache_keys: list[str]) -> bool:
    """批量注册缓存键到标签依赖集（Pipeline 优化）。

    Args:
        tag:        标签
        cache_keys: 关联的缓存键列表

    Returns:
        是否全部注册成功
    """
    from db.redis import get_redis_async, redis_key

    if not cache_keys:
        return True

    r = await get_redis_async()
    if r is None:
        return False

    tag_key = redis_key("tag", tag)
    try:
        pipe = r.pipeline()
        pipe.sadd(tag_key, *cache_keys)
        pipe.expire(tag_key, 604800)
        await pipe.execute()
        logger.debug("标签依赖注册: tag=%s, keys=%d", tag, len(cache_keys))
        return True
    except Exception as e:
        logger.warning("批量标签依赖注册失败 (tag=%s): %s", tag, e)
        return False


async def invalidate_by_tag(tag: str) -> int:
    """根据标签失效所有关联的缓存键。

    流程:
      1. SMEMBERS sgp:tag:{tag} → 获取所有关联键
      2. DELETE 所有关联键
      3. DELETE sgp:tag:{tag}

    Args:
        tag: 标签（如 "pagerank", "topology", "user_42"）

    Returns:
        失效的缓存键数量

    使用方式:
        count = await invalidate_by_tag("pagerank")
        # → 删除所有 pageRank 算法的缓存版本
    """
    from db.redis import get_redis_async, redis_key

    r = await get_redis_async()
    if r is None:
        return 0

    tag_key = redis_key("tag", tag)
    try:
        # 获取标签下的所有关联键
        members = await r.smembers(tag_key)
        keys = list(members) if members else []

        if keys:
            # 删除关联的缓存键
            await r.delete(*keys)
            # 删除标签集本身
            await r.delete(tag_key)
            logger.info("标签失效: tag=%s, keys_deleted=%d", tag, len(keys))
        return len(keys)

    except Exception as e:
        logger.warning("标签失效异常 (tag=%s): %s", tag, e)
        return 0


# ═══════════════════════════════════════════════════════════════════
# 模式 3: TTL 失效（兜底策略）
# ═══════════════════════════════════════════════════════════════════

# TTL 策略在每条键的 EXPIRE 中实现（见 cache_get_or_compute）。
# 此文件定义 TTL 常量，供各模块引用。

# TTL 层级定义
TTL_TIERS = {
    "hot":        {"min": 30,   "max": 600},    # 实时统计、限流窗口、分布式锁
    "warm":       {"min": 1800, "max": 7200},    # 拓扑数据、会话列表
    "stable":     {"min": 43200, "max": 172800}, # 算法结果（静态图）
    "persistent": {"min": 604800, "max": 2592000}, # 用户偏好、动态配置
}

# 具体 TTL 推荐值（秒）
TTL_DEFAULTS = {
    "topology": 3600,                # 全网拓扑: 1 小时
    "algorithm": 86400,              # 算法结果: 24 小时
    "stats": 600,                    # 图统计: 10 分钟
    "path_query": 0,                 # 路径查询: 不缓存（组合爆炸）
    "session_list": 3600,            # 用户会话列表: 1 小时
    "token_blacklist": 900,          # Token 黑名单: 15 分钟
    "rate_limit_window": 120,        # 限流窗口: 2 分钟
    "lock_compute": 30,              # 分布式锁: 30 秒
    "api_key_cache": 3600,           # API Key 验证缓存: 1 小时
    "user_preferences": 604800,      # 用户偏好: 7 天
    "dynamic_config": 604800,        # 动态配置: 7 天
}


def get_ttl(entity_type: str, with_jitter: bool = True) -> int:
    """获取推荐的缓存 TTL（可选 jitter）。

    Args:
        entity_type: 实体类型名称（如 "algorithm", "topology"）
        with_jitter: 是否添加随机偏移

    Returns:
        TTL 秒数
    """
    settings = get_settings()

    # 实体类型 → 配置项的映射
    config_map = {
        "topology": settings.cache_topology_ttl,
        "algorithm": settings.cache_algorithm_ttl,
        "stats": settings.cache_stats_ttl,
    }

    base_ttl = config_map.get(entity_type, settings.cache_default_ttl)
    if entity_type in TTL_DEFAULTS and base_ttl == settings.cache_default_ttl:
        base_ttl = TTL_DEFAULTS.get(entity_type, settings.cache_default_ttl)

    if with_jitter:
        return _apply_ttl_jitter(base_ttl)
    return base_ttl


# ═══════════════════════════════════════════════════════════════════
# 模式 4: 事件驱动失效（Pub/Sub 广播）
# ═══════════════════════════════════════════════════════════════════

_global_pubsub = None


async def _ensure_pubsub_started():
    """确保全局 Pub/Sub 客户端已启动（懒初始化）。"""
    global _global_pubsub
    if _global_pubsub is not None:
        return _global_pubsub

    try:
        from services.pubsub import RedisPubSub
        _global_pubsub = RedisPubSub()
        await _global_pubsub.start()
        logger.debug("缓存服务 Pub/Sub 客户端已启动")
    except ImportError:
        logger.debug("Pub/Sub 模块不可用，跳过事件驱动失效")
        _global_pubsub = False
    return _global_pubsub


async def listen_for_cache_invalidation():
    """注册缓存失效事件监听器（在应用启动时调用一次）。

    监听 sgp:pubsub:cache-invalid 频道，自动执行本地缓存失效。
    这样当一个 Worker 的 Admin API 触发了缓存失效，
    所有其他 Worker 也会同步失效，保障多进程缓存一致性。

    使用方式 (server.py lifespan startup):
        asyncio.create_task(listen_for_cache_invalidation())
    """
    pubsub = await _ensure_pubsub_started()
    if not pubsub:
        return

    async def on_cache_invalid(channel: str, data: dict):
        domain = data.get("domain", "")
        keys = data.get("keys", [])
        reason = data.get("reason", "unknown")
        logger.info("收到缓存失效广播: domain=%s, keys=%d, reason=%s", domain, keys, reason)

        if keys:
            from db.redis import pipeline_delete_multi
            deleted = await pipeline_delete_multi(keys)
            logger.debug("广播通知失效: deleted=%d keys", deleted)
        elif domain:
            count = await invalidate_by_domain(domain, namespace="sgp")
            logger.info("广播通知域失效: domain=%s, keys=%d", domain, count)

    from services.pubsub import Channels
    await pubsub.subscribe(Channels.CACHE_INVALID, on_cache_invalid)


# ═══════════════════════════════════════════════════════════════════
# 模式 5: 手动/管理失效（Admin API）
# ═══════════════════════════════════════════════════════════════════

async def invalidate_cache(pattern: str, namespace: str = "sgp") -> int:
    """根据通配模式失效缓存（SCAN + DELETE）。

    安全限制: 不允许 pattern="*" 以防止误删所有键。

    Args:
        pattern:   Redis 键匹配模式 (如 "sgp:graph:*", "social_graph:*")
        namespace: 若 pattern 不包含冒号，自动展开为 "{namespace}:{pattern}:*"

    Returns:
        失效的键数量

    使用方式:
        await invalidate_cache("sgp:graph:pagerank:*")
        await invalidate_cache("graph", namespace="sgp")  # 展开为 "sgp:graph:*"
    """
    from db.redis import get_redis_async

    # 安全检查
    if pattern == "*" or pattern == "sgp:*" or pattern == "social_graph:*" and not _confirm_safe():
        logger.warning("安全拦截: 拒绝通配全量失效 pattern=%s", pattern)
        return 0

    # 自动展开域缩写
    if ":" not in pattern and "*" not in pattern:
        pattern = f"{namespace}:{pattern}:*"

    r = await get_redis_async()
    if r is None:
        return 0

    count = 0
    cursor = 0
    try:
        while True:
            cursor, keys = await r.scan(cursor, match=pattern, count=100)
            if keys:
                await r.delete(*keys)
                count += len(keys)
            if cursor == 0:
                break

        logger.info("缓存已失效: pattern=%s, count=%d", pattern, count)
        return count
    except Exception as e:
        logger.warning("缓存失效异常 (pattern=%s): %s", pattern, e)
        return count


async def invalidate_by_domain(domain: str, namespace: str = "sgp") -> int:
    """失效指定域下的所有缓存（如 "graph" 域）。

    直接调用 invalidate_cache 展开为 "{namespace}:{domain}:*"。

    Args:
        domain:    域标签 ("graph", "auth", "rate", "session", "lock")
        namespace: 命名空间

    Returns:
        失效的键数量
    """
    pattern = f"{namespace}:{domain}:*"
    return await invalidate_cache(pattern)


def _confirm_safe() -> bool:
    """确认是否允许全量失效操作（生产环境保护）。"""
    settings = get_settings()
    if settings.environment == "production":
        return False
    return True


# ── 针对特定算法的失效 ──────────────────────────────────────────

async def invalidate_algorithm_cache(algorithm: str, namespace: str = "sgp") -> int:
    """失效特定算法的所有版本缓存。

    Args:
        algorithm: 算法名称 ("pagerank", "community", "betweenness", ...)
        namespace: 命名空间

    Returns:
        失效的键数量
    """
    # 同时清理 sgp 和旧版键
    count = 0
    count += await invalidate_cache(f"{namespace}:graph:{algorithm}:*")
    count += await invalidate_cache(f"social_graph:{algorithm}:*")
    count += await invalidate_cache(f"socialgraph:{algorithm}:*")

    # 同时通过标签失效
    count += await invalidate_by_tag(algorithm)
    return count


async def invalidate_all_graph_cache() -> int:
    """失效所有图数据和算法结果缓存（数据导入后调用）。

    同时清理 sgp 和旧版键，以及所有算法标签。
    """
    count = 0

    # sgp 新版键
    count += await invalidate_cache("sgp:graph:topology:*")
    count += await invalidate_cache("sgp:graph:pagerank:*")
    count += await invalidate_cache("sgp:graph:community:*")
    count += await invalidate_cache("sgp:graph:betweenness:*")
    count += await invalidate_cache("sgp:graph:kcore:*")
    count += await invalidate_cache("sgp:graph:clustering:*")
    count += await invalidate_cache("sgp:graph:connected_components:*")
    count += await invalidate_cache("sgp:graph:stats:*")
    count += await invalidate_cache("sgp:graph:path:*")

    # 旧版兼容键
    for domain_alg in ["topology", "pagerank", "community", "betweenness",
                        "kcore", "clustering", "connected_components", "stats"]:
        count += await invalidate_cache(f"social_graph:{domain_alg}:*")
        count += await invalidate_cache(f"socialgraph:{domain_alg}:*")

    # 标签失效
    for tag in ["topology", "pagerank", "community", "betweenness",
                "kcore", "clustering", "connected_components", "stats"]:
        count += await invalidate_by_tag(tag)

    logger.info("全量图缓存已失效: total_keys=%d", count)

    # 递增数据版本号（确保新请求使用新键）
    await bump_data_version(DOMAIN_GRAPH)

    return count


# ═══════════════════════════════════════════════════════════════════
# 缓存预热
# ═══════════════════════════════════════════════════════════════════

async def warm_cache(keys: list[str], compute_fns: list[Callable]) -> int:
    """预热缓存（在启动时或手动触发时调用）。

    并行预热所有指定键，不阻塞启动。

    Args:
        keys:        缓存键列表
        compute_fns: 对应的计算函数列表（与 keys 顺序对应）

    Returns:
        成功预热的键数量

    使用方式:
        await warm_cache(
            keys=["sgp:graph:topology:v1", "sgp:graph:stats:v1"],
            compute_fns=[_fetch_topology, lambda: execute_command("graph_stats")],
        )
    """
    settings = get_settings()
    if not settings.cache_warm_on_startup:
        logger.debug("缓存预热已禁用 (cache_warm_on_startup=false)")
        return 0

    if len(keys) != len(compute_fns):
        logger.error("预热参数不匹配: keys=%d, fns=%d", len(keys), len(compute_fns))
        return 0

    logger.info("开始缓存预热: keys=%d", len(keys))

    async def warm_one(key: str, fn: Callable, ttl: int):
        try:
            # 检查是否已有缓存
            from db.redis import get_redis_async
            r = await get_redis_async()
            if r:
                exists = await r.exists(key)
                if exists:
                    logger.debug("预热跳过 (已有缓存): %s", key)
                    return True

            # 执行计算
            if asyncio.iscoroutinefunction(fn):
                data = await fn()
            else:
                data = fn()

            if isinstance(data, dict) and data.get("status") == "success":
                from db.redis import set_compressed
                await set_compressed(key, json.dumps(data), ttl)
                logger.info("预热完成: %s (TTL=%ds)", key, ttl)
                return True
            else:
                logger.warning("预热跳过 (数据异常): %s", key)
                return False
        except Exception as e:
            logger.warning("预热失败 (%s): %s", key, e)
            return False

    # P0 级预热（拓扑 + 统计）并行执行
    results = await asyncio.gather(*[
        warm_one(key, fn, get_ttl(entity_type))
        for key, fn, entity_type in [
            (keys[i], compute_fns[i],
             "topology" if "topology" in keys[i] else
             "stats" if "stats" in keys[i] else
             "algorithm" if any(a in keys[i] for a in
                 ["pagerank", "community", "betweenness", "kcore", "clustering",
                  "connected_components"])
             else "topology")
            for i in range(len(keys))
        ]
    ], return_exceptions=True)

    success = sum(1 for r in results if r is True)
    logger.info("缓存预热完成: success=%d/%d", success, len(keys))
    return success


async def warm_p0_cache():
    """P0 级缓存预热（启动时执行，仅预热拓扑和统计）。

    应在 server.py lifespan startup 中调用。
    """
    from services.cpp_engine import execute_command

    ver = await get_data_version(DOMAIN_GRAPH)
    return await warm_cache(
        keys=[
            f"sgp:graph:topology:v{ver}",
            f"sgp:graph:stats:v{ver}",
        ],
        compute_fns=[
            _warm_topology,
            lambda: execute_command("graph_stats"),
        ],
    )


async def _warm_topology():
    """预热拓扑数据。"""
    from services.neo4j_service import get_full_topology
    return await get_full_topology()


# ═══════════════════════════════════════════════════════════════════
# Cache-Aside 核心（增强版）
# ═══════════════════════════════════════════════════════════════════

async def cache_get_or_compute(
    cache_key: str,
    ttl: int,
    compute_fn: Callable,
    *args,
    use_lock: bool = True,
    lock_timeout: int = 30,
    compress: Optional[bool] = None,
    tags: Optional[list[str]] = None,
    entity_type: str = "topology",
    **kwargs,
) -> dict:
    """Cache-Aside 模式: 缓存命中返回，未命中则计算并缓存。

    支持分布式锁防止缓存击穿:
      当多个并发请求同时发现缓存未命中时，只有第一个请求执行计算，
      其余请求轮询等待新结果。

    v2.0 增强:
      - 双读兼容（sgp:* 优先，回退到 social_graph:*）
      - 自动压缩（值 > 64KB 时 zlib 压缩）
      - 标签依赖注册（用于批量失效）
      - TTL jitter 防雪崩
      - 原子命中/未命中计数器

    Args:
        cache_key:    Redis 缓存键（推荐 sgp:* 格式，自动兼容旧版）
        ttl:          缓存 TTL（秒），自动添加 ±10% jitter
        compute_fn:   计算函数（async callable，返回 dict）
        *args:        传给 compute_fn 的位置参数
        use_lock:     是否使用分布式锁（防止击穿）
        lock_timeout: 分布式锁超时时间（秒）
        compress:     是否压缩（None=自动判断，True/False=强制）
        tags:         标签列表（用于标签失效模式）
        entity_type:  实体类型（用于 TTL 选择）
        **kwargs:     传给 compute_fn 的关键字参数

    Returns:
        计算结果的 dict
    """
    from db.redis import (
        get_redis_async,
        get_compressed,
        set_compressed,
        track_cache_hit,
        track_cache_miss,
        redis_key,
    )

    settings = get_settings()
    actual_ttl = _apply_ttl_jitter(ttl)
    compress_threshold = settings.cache_compression_threshold
    r = await get_redis_async()

    # ── 1. 尝试从缓存读取（双读: sgp:* 优先，旧版回退）───────
    keys_to_try = _resolve_cache_key(cache_key)

    if r:
        for try_key in keys_to_try:
            try:
                cached = await get_compressed(try_key)
                if cached:
                    logger.debug("缓存命中: %s", try_key)
                    if settings.cache_stats_enabled:
                        await track_cache_hit(entity_type)
                    return json.loads(cached)
            except Exception as e:
                logger.warning("缓存读取异常 (%s): %s", try_key, e)

    if settings.cache_stats_enabled:
        await track_cache_miss(entity_type)

    # ── 2. 缓存未命中 → 尝试获取分布式锁 ────────────────────
    lock_key = redis_key("lock", "compute", _safe_lock_name(cache_key))

    if r and use_lock:
        lock_acquired = await r.set(lock_key, "1", nx=True, ex=lock_timeout)
        if not lock_acquired:
            logger.debug("等待其他请求的计算结果: %s", cache_key)
            for _ in range(int(lock_timeout * 10)):
                await asyncio.sleep(0.1)
                for try_key in keys_to_try:
                    try:
                        new_cached = await get_compressed(try_key)
                        if new_cached:
                            logger.debug("获取到其他请求的计算结果: %s", try_key)
                            return json.loads(new_cached)
                    except Exception:
                        pass
            logger.warning("等待锁释放超时: %s, 强制重新计算", cache_key)

    # ── 3. 执行计算 ────────────────────────────────────────
    start = time.time()
    try:
        if asyncio.iscoroutinefunction(compute_fn):
            data = await compute_fn(*args, **kwargs)
        else:
            data = compute_fn(*args, **kwargs)
    except Exception as e:
        logger.error("计算失败 (%s): %s", cache_key, e, exc_info=True)
        if r and use_lock:
            await r.delete(lock_key)
        raise

    elapsed_ms = (time.time() - start) * 1000
    logger.info("计算完成: %s (%.1fms)", cache_key, elapsed_ms)

    # ── 4. 写入缓存 ────────────────────────────────────────
    if r and data.get("status") == "success":
        try:
            value_str = json.dumps(data)
            primary_key = keys_to_try[0]  # 优先写新版键
            await set_compressed(primary_key, value_str, actual_ttl, threshold=compress_threshold)

            # 注册标签依赖
            if tags:
                await cache_tag_dependencies(tags[0], [primary_key])
                for tag in tags[1:]:
                    await cache_tag_dependency(tag, primary_key)

        except Exception as e:
            logger.warning("缓存写入异常 (%s): %s", cache_key, e)

    # ── 5. 释放锁 ──────────────────────────────────────────
    if r and use_lock:
        await r.delete(lock_key)

    return data


def _safe_lock_name(cache_key: str) -> str:
    """生成安全的锁名（去除特殊字符，限制长度）。"""
    safe = cache_key.replace(":", "_").replace("*", "star").replace("?", "q")
    if len(safe) > 80:
        import hashlib
        safe = safe[:40] + "_" + hashlib.md5(safe.encode()).hexdigest()[:8]
    return safe


# ═══════════════════════════════════════════════════════════════════
# Lua 脚本 — 原子化缓存获取或计算
# ═══════════════════════════════════════════════════════════════════

_LUA_GET_OR_LOCK = """
local cache_key = KEYS[1]
local lock_key = KEYS[2]
local lock_timeout = ARGV[1]

local cached = redis.call('GET', cache_key)
if cached then
    return {'HIT', cached}
end

local locked = redis.call('SET', lock_key, '1', 'NX', 'EX', lock_timeout)
if locked then
    return {'COMPUTE'}
else
    return {'WAIT'}
end
"""


async def atomic_get_or_lock(cache_key: str, lock_timeout: int = 30) -> tuple[str, Optional[str]]:
    """原子化操作: 检查缓存存在性或获取计算锁。

    使用 Lua 脚本在 Redis 服务端原子执行，消除竞态条件。

    Args:
        cache_key:    缓存键
        lock_timeout: 锁超时时间（秒）

    Returns:
        ("HIT", cached_value)  — 命中缓存
        ("COMPUTE", None)      — 未命中且获取到锁，调用方应执行计算
        ("WAIT", None)         — 未命中且锁被占用，调用方应等待

    使用方式:
        action, value = await atomic_get_or_lock("sgp:graph:pagerank:v3")
        if action == "HIT":
            return json.loads(value)
        elif action == "COMPUTE":
            result = await compute()
            await cache_set_and_unlock("sgp:graph:pagerank:v3", result, 86400)
            return result
        else:
            await asyncio.sleep(0.1)
            return await retry_get(key)
    """
    from db.redis import get_redis_async, redis_key

    r = await get_redis_async()
    if r is None:
        return ("COMPUTE", None)

    lock_key = redis_key("lock", "compute", _safe_lock_name(cache_key))

    try:
        result = await r.eval(
            _LUA_GET_OR_LOCK, 2,
            cache_key, lock_key, lock_timeout,
        )
        action, *rest = result
        return (action, rest[0] if rest else None)
    except Exception as e:
        logger.warning("Lua 脚本执行异常: %s", e)
        return ("COMPUTE", None)


# ═══════════════════════════════════════════════════════════════════
# 缓存空值防护（防穿透）
# ═══════════════════════════════════════════════════════════════════

_NULL_MARKER = "__CACHE_NULL__"
_NULL_TTL = 60  # 空值缓存 60 秒


async def cache_set_null(cache_key: str) -> bool:
    """缓存空值标记（防止缓存穿透：查询不存在的数据每次打中后端）。

    Args:
        cache_key: 缓存键

    Returns:
        是否写入成功

    使用方式:
        # 当查询到 node_id=99999999 不存在时:
        await cache_set_null("sgp:graph:node:99999999")
    """
    from db.redis import get_redis_async

    r = await get_redis_async()
    if r is None:
        return False
    try:
        await r.setex(cache_key, _NULL_TTL, _NULL_MARKER)
        return True
    except Exception as e:
        logger.warning("空值缓存写入异常 (%s): %s", cache_key, e)
        return False


async def cache_is_null(value: Optional[str]) -> bool:
    """检查缓存值是否为空值标记。

    Args:
        value: 从 Redis GET 获取的值

    Returns:
        True 表示该值为缓存穿透标记
    """
    return value == _NULL_MARKER


# ═══════════════════════════════════════════════════════════════════
# 缓存统计增强 — 键数量 + 内存估算
# ═══════════════════════════════════════════════════════════════════

async def get_cache_memory_estimate() -> dict:
    """估算各域的缓存内存占用。

    使用 MEMORY USAGE 命令采样估算（避免对每个键都执行 MEMORY USAGE）。

    Returns:
        {"graph": {"keys": 8, "estimated_bytes": 2097152}, ...}
    """
    from db.redis import get_redis_async, scan_keys_by_domain

    r = await get_redis_async()
    if r is None:
        return {}

    domains = ["graph", "auth", "rate", "session", "lock"]
    result = {}

    for domain in domains:
        keys = await scan_keys_by_domain(domain)
        if not keys:
            result[domain] = {"keys": 0, "estimated_bytes": 0}
            continue

        # 采样前 3 个键估算平均大小
        sample = keys[:3]
        total_sample = 0
        for key in sample:
            try:
                usage = await r.memory_usage(key)
                if usage:
                    total_sample += usage
            except Exception:
                pass

        avg_size = total_sample / len(sample) if sample else 0
        estimated = int(avg_size * len(keys))
        result[domain] = {"keys": len(keys), "estimated_bytes": estimated}

    return result


async def get_cache_summary() -> dict:
    """获取完整的缓存状态摘要。

    聚合: 命中率 + 内存估算 + 键数量 + 数据版本号。

    Returns:
        {
            "stats": {...},         # 命中率统计
            "memory": {...},        # 内存估算
            "versions": {...},      # 数据版本号
            "pool": {...},          # 连接池状态
        }
    """
    from db.redis import get_cache_stats, get_pool_stats

    stats_task = get_cache_stats()
    memory_task = get_cache_memory_estimate()
    pool_task = get_pool_stats()
    versions_task = get_data_version(DOMAIN_GRAPH)

    stats, memory, pool, version = await asyncio.gather(
        stats_task, memory_task, pool_task, versions_task,
        return_exceptions=True,
    )

    return {
        "stats": stats if not isinstance(stats, Exception) else {"error": str(stats)},
        "memory": memory if not isinstance(memory, Exception) else {"error": str(memory)},
        "pool": pool if not isinstance(pool, Exception) else {"error": str(pool)},
        "versions": {
            "graph": version if not isinstance(version, Exception) else 1,
        },
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
