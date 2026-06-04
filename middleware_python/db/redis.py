"""
SocialGraph Pro — Redis 客户端管理 (异步 + 同步)
版本: 2.0.0

Lazy-Connect 模式:
  - 首次调用时连接，后续复用全局单例
  - 连接失败时返回 None，调用方需处理降级
  - False 哨兵值表示"已尝试但连接失败"

v2.0 增强:
  - pipeline_get_multi / pipeline_delete_multi   批量读写
  - set_compressed / get_compressed             zlib 压缩 (>64KB)
  - get_pool_stats / get_cache_stats            连接池 + 命中率监控
  - track_cache_hit/track_cache_miss            原子计数器
  - scan_keys_by_domain                         SCAN 按域扫描
  - migrate_old_keys                            旧键迁移工具
  - redis_key 命名空间升级 sgp (SocialGraph Pro)
  - TCP keepalive + 定期健康检查
  - track_slow_query                            慢查询日志
"""
import logging
import time
import zlib
from contextlib import asynccontextmanager
from typing import Any, Optional

import redis.asyncio as aioredis
import redis as sync_redis

from core.config import get_settings

logger = logging.getLogger("socialgraph.db.redis")

# 全局缓存
_redis_async: Optional[aioredis.Redis] = None  # type: ignore
_redis_async_failed: bool = False

_redis_sync: Optional[sync_redis.Redis] = None  # type: ignore
_redis_sync_failed: bool = False

# ── 旧版命名空间映射（文档用途，实际迁移逻辑见 services/cache.py _LEGACY_PATTERNS）


async def get_redis_async() -> Optional[aioredis.Redis]:
    """获取 Redis 异步客户端 (推荐用于 FastAPI 路由)。

    Returns:
        aioredis.Redis 或 None (连接失败时)
    """
    global _redis_async, _redis_async_failed

    if _redis_async is not None:
        return _redis_async
    if _redis_async_failed:
        return None

    settings = get_settings()
    try:
        _redis_async = aioredis.Redis(
            host=settings.redis_host,
            port=settings.redis_port,
            db=settings.redis_db,
            password=settings.redis_password or None,
            max_connections=settings.redis_pool_max_connections,
            socket_timeout=settings.redis_socket_timeout,
            socket_connect_timeout=settings.redis_socket_connect_timeout,
            socket_keepalive=settings.redis_socket_keepalive,
            health_check_interval=settings.redis_health_check_interval,
            decode_responses=True,
            retry_on_timeout=True,
        )
        await _redis_async.ping()
        logger.info(
            "Redis 异步客户端已连接: %s:%s (pool=%d, keepalive=%s, hc_interval=%ds)",
            settings.redis_host,
            settings.redis_port,
            settings.redis_pool_max_connections,
            settings.redis_socket_keepalive,
            settings.redis_health_check_interval,
        )
        return _redis_async
    except RecursionError:
        # redis-py < 5.0.2 已知 bug: health_check_interval + retry_on_timeout 导致无限递归
        # 参考: https://github.com/redis/redis-py/issues/3745
        logger.warning(
            "Redis 连接初始化遇到 RecursionError (可能是 redis-py < 5.0.2 的已知 bug)。"
            "请升级: pip install redis>=5.0.2 或将 redis_health_check_interval 设为 0。"
        )
        _redis_async_failed = True
        _redis_async = None
        return None
    except Exception as e:
        logger.warning("Redis 不可用 (%s:%s): %s", settings.redis_host, settings.redis_port, e)
        _redis_async_failed = True
        _redis_async = None
        return None


def get_redis_sync() -> Optional[sync_redis.Redis]:
    """获取 Redis 同步客户端 (用于同步上下文如子进程、测试)。

    Returns:
        redis.Redis 或 None (连接失败时)
    """
    global _redis_sync, _redis_sync_failed

    if _redis_sync is not None:
        return _redis_sync
    if _redis_sync_failed:
        return None

    settings = get_settings()
    try:
        _redis_sync = sync_redis.Redis(
            host=settings.redis_host,
            port=settings.redis_port,
            db=settings.redis_db,
            password=settings.redis_password or None,
            max_connections=settings.redis_pool_max_connections,
            socket_timeout=settings.redis_socket_timeout,
            socket_connect_timeout=settings.redis_socket_connect_timeout,
            socket_keepalive=settings.redis_socket_keepalive,
            health_check_interval=settings.redis_health_check_interval,
            decode_responses=True,
            retry_on_timeout=True,
        )
        _redis_sync.ping()
        logger.info(
            "Redis 同步客户端已连接: %s:%s",
            settings.redis_host,
            settings.redis_port,
        )
        return _redis_sync
    except Exception as e:
        logger.warning("Redis 同步客户端不可用: %s", e)
        _redis_sync_failed = True
        _redis_sync = None
        return None


async def reset_redis_connection():
    """强制重置 Redis 连接（用于连接池耗尽后恢复）。"""
    global _redis_async, _redis_async_failed, _redis_sync, _redis_sync_failed

    if _redis_async:
        try:
            await _redis_async.aclose()
        except Exception:
            pass
    _redis_async = None
    _redis_async_failed = False

    if _redis_sync:
        try:
            _redis_sync.close()
        except Exception:
            pass
    _redis_sync = None
    _redis_sync_failed = False

    logger.info("Redis 连接已重置")


async def check_redis_health() -> tuple[bool, Optional[str], float]:
    """Redis 连接健康检查。

    Returns:
        (is_healthy, error_message, latency_ms)
    """
    start = time.time()
    try:
        r = await get_redis_async()
        if r is None:
            return False, "客户端未初始化", 0
        await r.ping()
        latency = (time.time() - start) * 1000
        return True, None, round(latency, 2)
    except Exception as e:
        return False, str(e), 0


# ═══════════════════════════════════════════════════════════════════
# 键命名
# ═══════════════════════════════════════════════════════════════════

def redis_key(*parts: str, namespace: str = "sgp") -> str:
    """构建带命名空间前缀的 Redis 键。

    统一键命名规范，避免键冲突和拼写错误。

    v2.0: 默认命名空间升级为 "sgp" (SocialGraph Pro)

    使用方式:
        redis_key("graph", "topology", "v7")        # → "sgp:graph:topology:v7"
        redis_key("auth", "session", user_id)        # → "sgp:auth:session:abc123"
        redis_key("lock", "compute", "pagerank")     # → "sgp:lock:compute:pagerank"

        # 兼容旧命名空间:
        redis_key("topology", "v7", namespace="social_graph")  # → "social_graph:topology:v7"

    Args:
        *parts:     键的各部分，以冒号连接
        namespace:  顶层命名空间，默认 "sgp"

    Returns:
        完整的 Redis 键字符串
    """
    return f"{namespace}:" + ":".join(str(p) for p in parts)


def legacy_key(*parts: str) -> str:
    """构建旧版兼容键名（social_graph:* 前缀）。

    用于过渡期的双读/双写策略。
    新代码应使用 redis_key()。

    使用方式:
        legacy_key("topology", "v7")  # → "social_graph:topology:v7"
    """
    return f"social_graph:" + ":".join(str(p) for p in parts)


# ═══════════════════════════════════════════════════════════════════
# 批量操作 (Pipeline)
# ═══════════════════════════════════════════════════════════════════

async def pipeline_setex_multi(mapping: dict[str, tuple[str, int]]) -> bool:
    """使用 Pipeline 批量 SETEX 操作（原子性保证）。

    用于批量缓存刷新场景，比逐个 SETEX 快 5-10 倍。

    Args:
        mapping: {key: (value, ttl_seconds), ...}

    Returns:
        是否全部成功

    使用方式:
        await pipeline_setex_multi({
            "sgp:graph:pagerank:v3": (json.dumps(data), 86400),
            "sgp:graph:stats:v1": (json.dumps(stats), 600),
        })
    """
    r = await get_redis_async()
    if r is None:
        return False
    try:
        pipe = r.pipeline()
        for key, (value, ttl) in mapping.items():
            pipe.setex(key, ttl, value)
        await pipe.execute()
        return True
    except Exception as e:
        logger.warning("Pipeline SETEX 批量操作失败: %s", e)
        return False


async def pipeline_get_multi(keys: list[str]) -> list[Optional[str]]:
    """使用 Pipeline 批量 GET 操作。

    比逐个 GET 快 5-10 倍，适合批量读取场景。

    Args:
        keys: Redis 键列表

    Returns:
        与 keys 顺序对应的值列表 (缓存未命中为 None)

    使用方式:
        values = await pipeline_get_multi([
            "sgp:graph:pagerank:v3",
            "sgp:graph:community:v3",
            "sgp:graph:stats:v1",
        ])
    """
    r = await get_redis_async()
    if r is None:
        return [None] * len(keys)
    try:
        pipe = r.pipeline()
        for key in keys:
            pipe.get(key)
        results = await pipe.execute()
        return results
    except Exception as e:
        logger.warning("Pipeline GET 批量操作失败: %s", e)
        return [None] * len(keys)


async def pipeline_delete_multi(keys: list[str]) -> int:
    """使用 Pipeline 批量 DELETE 操作。

    Args:
        keys: 待删除的 Redis 键列表

    Returns:
        实际删除的键数量

    使用方式:
        deleted = await pipeline_delete_multi([
            "sgp:graph:pagerank:v2",
            "sgp:graph:community:v2",
        ])
    """
    if not keys:
        return 0
    r = await get_redis_async()
    if r is None:
        return 0
    try:
        pipe = r.pipeline()
        for key in keys:
            pipe.delete(key)
        results = await pipe.execute()
        return sum(int(r) for r in results)
    except Exception as e:
        logger.warning("Pipeline DELETE 批量操作失败: %s", e)
        return 0


# ═══════════════════════════════════════════════════════════════════
# 压缩存储 (zlib, 适用于 > 64KB 的值)
# ═══════════════════════════════════════════════════════════════════

_COMPRESS_PREFIX = b"ZLIB:"
_COMPRESS_LEVEL = 6  # zlib 压缩级别 (1-9, 6 是平衡选择)


async def set_compressed(
    key: str,
    value: str,
    ttl: int,
    threshold: int = 65536,
) -> bool:
    """带 zlib 压缩的 SETEX。

    当 value 的字节长度超过 threshold 时自动压缩。
    压缩后的值以 "ZLIB:" 前缀标记，供 get_compressed 识别。

    Args:
        key:       Redis 键
        value:     原始字符串值
        ttl:       过期时间（秒）
        threshold: 压缩阈值（字节），默认 65536 (64KB)

    Returns:
        是否写入成功

    使用方式:
        await set_compressed("sgp:graph:topology:v7", json_str, 3600)
    """
    r = await get_redis_async()
    if r is None:
        return False

    raw_bytes = value.encode("utf-8")

    if len(raw_bytes) > threshold:
        compressed = zlib.compress(raw_bytes, _COMPRESS_LEVEL)
        stored = _COMPRESS_PREFIX + compressed
        ratio = len(compressed) / len(raw_bytes) * 100
        logger.debug(
            "压缩缓存: key=%s, raw=%dB, compressed=%dB (%.1f%%)",
            key, len(raw_bytes), len(compressed), ratio,
        )
    else:
        stored = raw_bytes

    try:
        async with track_slow_query(f"set_compressed:{key}"):
            await r.set(key, stored, ex=ttl)
        return True
    except Exception as e:
        logger.warning("压缩写入异常 (%s): %s", key, e)
        return False


async def get_compressed(key: str) -> Optional[str]:
    """读取并自动解压由 set_compressed 写入的值。

    自动检测 "ZLIB:" 前缀，有则解压，无则直接返回。

    Args:
        key: Redis 键

    Returns:
        解压后的原始字符串，或 None（键不存在/读取失败）

    使用方式:
        value = await get_compressed("sgp:graph:topology:v7")
    """
    r = await get_redis_async()
    if r is None:
        return None

    try:
        async with track_slow_query(f"get_compressed:{key}"):
            stored = await r.get(key)
        if stored is None:
            return None

        if isinstance(stored, bytes):
            if stored.startswith(_COMPRESS_PREFIX):
                decompressed = zlib.decompress(stored[len(_COMPRESS_PREFIX):])
                return decompressed.decode("utf-8")
            return stored.decode("utf-8")
        return stored
    except Exception as e:
        logger.warning("压缩读取异常 (%s): %s", key, e)
        return None


# ═══════════════════════════════════════════════════════════════════
# 缓存命中率统计 (应用层原子计数器)
# ═══════════════════════════════════════════════════════════════════

async def track_cache_hit(key_or_domain: str = "global"):
    """记录一次缓存命中（原子 INCR）。

    Args:
        key_or_domain: 缓存域标签或全键。建议传域值，如 "graph"、"auth"。
    """
    r = await get_redis_async()
    if r is None:
        return
    try:
        await r.incr(redis_key("metrics", "cache", "hits", key_or_domain))
    except Exception:
        pass


async def track_cache_miss(key_or_domain: str = "global"):
    """记录一次缓存未命中（原子 INCR）。

    Args:
        key_or_domain: 缓存域标签，如 "graph"、"auth"。
    """
    r = await get_redis_async()
    if r is None:
        return
    try:
        await r.incr(redis_key("metrics", "cache", "misses", key_or_domain))
    except Exception:
        pass


async def get_cache_stats() -> dict:
    """获取应用层缓存统计（命中率 + 各域细分）。

    返回:
        {
            "global": {"hits": 1500, "misses": 300, "hit_rate": 83.3},
            "domains": {
                "graph": {"hits": 800, "misses": 200, "hit_rate": 80.0},
                "auth": {"hits": 500, "misses": 50, "hit_rate": 90.9},
            },
        }
    """
    r = await get_redis_async()
    if r is None:
        return {"global": {"hits": 0, "misses": 0, "hit_rate": 0}, "domains": {}}

    domains = ["global", "graph", "auth", "rate", "session", "lock"]
    result = {"domains": {}}
    total_hits = 0
    total_misses = 0

    try:
        for domain in domains:
            hits_key = redis_key("metrics", "cache", "hits", domain)
            misses_key = redis_key("metrics", "cache", "misses", domain)
            hits, misses = await asyncio_gather_with_default(
                r.get(hits_key), r.get(misses_key), default="0"
            )
            hits = int(hits or 0)
            misses = int(misses or 0)
            hit_rate = round(hits / (hits + misses) * 100, 1) if (hits + misses) > 0 else 0

            if domain == "global":
                result["global"] = {"hits": hits, "misses": misses, "hit_rate": hit_rate}
            else:
                result["domains"][domain] = {"hits": hits, "misses": misses, "hit_rate": hit_rate}
                total_hits += hits
                total_misses += misses

        # 如果 global 计数器未被显式使用，用各域汇总
        if result["global"]["hits"] == 0 and total_hits > 0:
            total = total_hits + total_misses
            hr = round(total_hits / total * 100, 1) if total > 0 else 0
            result["global"] = {"hits": total_hits, "misses": total_misses, "hit_rate": hr}

        return result
    except Exception as e:
        logger.warning("获取缓存统计异常: %s", e)
        return {"global": {"hits": 0, "misses": 0, "hit_rate": 0}, "domains": {}}


async def reset_cache_stats():
    """重置所有缓存命中率计数器。"""
    r = await get_redis_async()
    if r is None:
        return
    try:
        keys = []
        cursor = 0
        pattern = redis_key("metrics", "cache", "*")
        while True:
            cursor, batch = await r.scan(cursor, match=pattern, count=100)
            keys.extend(batch)
            if cursor == 0:
                break
        if keys:
            await r.delete(*keys)
        logger.info("缓存统计计数器已重置 (%d keys)", len(keys))
    except Exception as e:
        logger.warning("重置缓存统计异常: %s", e)


# 辅助: asyncio.gather 带默认值
async def asyncio_gather_with_default(*coros, default=None):
    """类似 asyncio.gather，但异常时返回默认值而非抛出。"""
    import asyncio
    results = await asyncio.gather(*coros, return_exceptions=True)
    return [default if isinstance(r, Exception) else r for r in results]


# ═══════════════════════════════════════════════════════════════════
# 连接池监控
# ═══════════════════════════════════════════════════════════════════

async def get_pool_stats() -> dict:
    """获取 Redis 连接池状态 + INFO 关键指标。

    返回:
        {
            "connected_clients": 5,
            "blocked_clients": 0,
            "used_memory_human": "2.5M",
            "uptime_seconds": 3600,
            "instantaneous_ops_per_sec": 120,
            "evicted_keys": 0,
            "expired_keys": 42,
            "keyspace_hits": 15000,
            "keyspace_misses": 2000,
            "pool_estimated_connections": 3,
        }
    """
    r = await get_redis_async()
    if r is None:
        return {"error": "Redis 不可用"}

    try:
        info = await r.info("stats")
        clients = await r.info("clients")
        memory = await r.info("memory")
        server = await r.info("server")

        return {
            "connected_clients": int(clients.get("connected_clients", 0)),
            "blocked_clients": int(clients.get("blocked_clients", 0)),
            "used_memory_human": memory.get("used_memory_human", "N/A"),
            "used_memory_bytes": int(memory.get("used_memory", 0)),
            "uptime_seconds": int(server.get("uptime_in_seconds", 0)),
            "instantaneous_ops_per_sec": int(stats.get("instantaneous_ops_per_sec", 0)),
            "evicted_keys": int(stats.get("evicted_keys", 0)),
            "expired_keys": int(stats.get("expired_keys", 0)),
            "keyspace_hits": int(stats.get("keyspace_hits", 0)),
            "keyspace_misses": int(stats.get("keyspace_misses", 0)),
            "pool_max_connections": get_settings().redis_pool_max_connections,
        }
    except Exception as e:
        logger.warning("获取连接池状态异常: %s", e)
        return {"error": str(e)}


# ═══════════════════════════════════════════════════════════════════
# SCAN 工具
# ═══════════════════════════════════════════════════════════════════

async def scan_keys_by_domain(domain: str, namespace: str = "sgp") -> list[str]:
    """使用 SCAN 获取指定域下的所有键。

    Args:
        domain:    域标签 (如 "graph", "auth", "rate")
        namespace: 命名空间，默认 "sgp"

    Returns:
        匹配的键列表

    使用方式:
        keys = await scan_keys_by_domain("graph")  # → 所有 sgp:graph:* 键
    """
    r = await get_redis_async()
    if r is None:
        return []

    pattern = f"{namespace}:{domain}:*"
    keys = []
    cursor = 0
    try:
        while True:
            cursor, batch = await r.scan(cursor, match=pattern, count=100)
            keys.extend(batch)
            if cursor == 0:
                break
        return keys
    except Exception as e:
        logger.warning("SCAN 域查询异常 (domain=%s): %s", domain, e)
        return []


async def count_keys_by_domain(domain: str, namespace: str = "sgp") -> int:
    """统计指定域下的键数量（不走 KEYS，用 SCAN 安全计数）。

    使用方式:
        count = await count_keys_by_domain("graph")
    """
    r = await get_redis_async()
    if r is None:
        return 0

    pattern = f"{namespace}:{domain}:*"
    count = 0
    cursor = 0
    try:
        while True:
            cursor, batch = await r.scan(cursor, match=pattern, count=100)
            count += len(batch)
            if cursor == 0:
                break
        return count
    except Exception as e:
        logger.warning("SCAN 计数异常 (domain=%s): %s", domain, e)
        return 0


# ═══════════════════════════════════════════════════════════════════
# 键迁移工具（旧 social_graph:* → 新 sgp:graph:*）
# ═══════════════════════════════════════════════════════════════════

async def migrate_old_keys(dry_run: bool = True) -> dict:
    """将旧版键名迁移到 sgp 命名空间。

    旧 → 新 映射:
      social_graph:*      → sgp:graph:*
      socialgraph:*       → sgp:graph:*
      blacklist:token:*   → sgp:auth:blacklist:*
      rate_limit:*        → sgp:rate:*
      lock:compute:*      → sgp:lock:compute:*

    Args:
        dry_run: True = 仅统计不迁移，False = 执行迁移（COPY 模式，保留旧键）

    Returns:
        {
            "dry_run": true,
            "migrated": 15,
            "skipped": 0,
            "errors": 0,
            "details": [
                {"old": "social_graph:topology:v7", "new": "sgp:graph:topology:v7", "migrated": true},
            ],
        }
    """
    r = await get_redis_async()
    if r is None:
        return {"dry_run": dry_run, "migrated": 0, "skipped": 0, "errors": 0, "details": [], "error": "Redis 不可用"}

    migration_maps = {
        "social_graph:*": ("sgp:graph:", lambda k: k.replace("social_graph:", "sgp:graph:", 1)),
        "socialgraph:*": ("sgp:graph:", lambda k: k.replace("socialgraph:", "sgp:graph:", 1)),
        "blacklist:token:*": ("sgp:auth:blacklist:", lambda k: k.replace("blacklist:token:", "sgp:auth:blacklist:", 1)),
        "blacklist:*": ("sgp:auth:blacklist:", lambda k: k.replace("blacklist:", "sgp:auth:blacklist:", 1)),
        "rate_limit:*": ("sgp:rate:", lambda k: k.replace("rate_limit:", "sgp:rate:", 1)),
        "lock:compute:*": ("sgp:lock:compute:", lambda k: k.replace("lock:compute:", "sgp:lock:compute:", 1)),
    }

    details = []
    migrated = 0
    skipped = 0
    errors = 0

    for old_pattern, (new_prefix, transform_fn) in migration_maps.items():
        cursor = 0
        while True:
            cursor, keys = await r.scan(cursor, match=old_pattern, count=50)
            for old_key in keys:
                new_key = transform_fn(old_key)

                # 检查目标键是否已存在
                target_exists = await r.exists(new_key)
                if target_exists:
                    details.append({"old": old_key, "new": new_key, "migrated": False, "reason": "目标键已存在"})
                    skipped += 1
                    continue

                if not dry_run:
                    try:
                        # 使用 COPY 命令 (Redis 6.2+) 复制值 + TTL
                        # 回退方案: DUMP → RESTORE
                        ttl = await r.ttl(old_key)
                        if ttl is not None and ttl >= 0:
                            serialized = await r.dump(old_key)
                            if serialized:
                                await r.restore(new_key, ttl * 1000 if ttl > 0 else 0, serialized, replace=True)
                            else:
                                # DUMP 失败（可能键已过期），跳过
                                errors += 1
                                details.append({"old": old_key, "new": new_key, "migrated": False, "reason": "DUMP 失败"})
                                continue
                        else:
                            # TTL = -1（永不过期）或 -2（不存在）
                            if ttl == -1:
                                serialized = await r.dump(old_key)
                                if serialized:
                                    await r.restore(new_key, 0, serialized, replace=True)
                            else:
                                skipped += 1
                                continue
                    except Exception as e:
                        errors += 1
                        details.append({"old": old_key, "new": new_key, "migrated": False, "reason": str(e)})
                        continue

                migrated += 1
                details.append({"old": old_key, "new": new_key, "migrated": True})

            if cursor == 0:
                break

    logger.info(
        "键迁移 %s: 已迁移=%d, 已跳过=%d, 错误=%d",
        "模拟" if dry_run else "执行",
        migrated, skipped, errors,
    )

    return {
        "dry_run": dry_run,
        "migrated": migrated,
        "skipped": skipped,
        "errors": errors,
        "details": details,
    }


# ═══════════════════════════════════════════════════════════════════
# 慢查询日志
# ═══════════════════════════════════════════════════════════════════

@asynccontextmanager
async def track_slow_query(label: str = "unknown"):
    """异步上下文管理器：记录慢 Redis 查询。

    使用方式:
        async with track_slow_query("get_cache:sgp:graph:topology"):
            value = await r.get(key)
    """
    settings = get_settings()
    threshold = settings.redis_slow_query_threshold_ms  # 毫秒
    start = time.time()
    try:
        yield
    finally:
        elapsed_ms = (time.time() - start) * 1000
        if elapsed_ms > threshold:
            logger.warning(
                "Redis 慢查询: label=%s, elapsed=%.1fms, threshold=%dms",
                label, elapsed_ms, threshold,
            )


# ═══════════════════════════════════════════════════════════════════
# Redis 服务器端 INFO 包装
# ═══════════════════════════════════════════════════════════════════

async def get_redis_info(section: str = "all") -> dict:
    """获取 Redis INFO 原始数据。

    Args:
        section: INFO 分区 ("server", "clients", "memory", "stats", "all")

    Returns:
        INFO 命令的解析结果
    """
    r = await get_redis_async()
    if r is None:
        return {}
    try:
        if section == "all":
            return await r.info()
        return await r.info(section)
    except Exception as e:
        logger.warning("获取 Redis INFO 异常: %s", e)
        return {}


# ═══════════════════════════════════════════════════════════════════
# 生命周期
# ═══════════════════════════════════════════════════════════════════

async def close_redis():
    """关闭所有 Redis 连接（应用关闭时调用）。"""
    global _redis_async, _redis_async_failed, _redis_sync, _redis_sync_failed

    if _redis_async:
        try:
            await _redis_async.aclose()
        except Exception:
            pass
        _redis_async = None
        _redis_async_failed = False

    if _redis_sync:
        try:
            _redis_sync.close()
        except Exception:
            pass
        _redis_sync = None
        _redis_sync_failed = False

    logger.info("Redis 连接已关闭")
