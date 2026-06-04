"""
SocialGraph Pro — MongoDB 异步客户端 (Motor)

功能:
  - 异步客户端初始化 + 连接池配置
  - 数据库句柄获取: get_mongo_db() -> AsyncIOMotorDatabase
  - 集合访问辅助: get_collection(name) -> AsyncIOMotorCollection
  - Fire-and-forget 写入: write_concern=0, 不阻塞 API 响应
  - 读偏好配置: primaryPreferred (优先主节点，故障时读副本)
  - TTL 索引管理: ensure_ttl_index()
  - 批量写入: bulk_write_logs() — 合并日志写入
  - 缓存注册表: register_cache_entry() / get_cache_entry() / invalidate_cache_by_hash()
  - 索引全量管理: ensure_all_indexes() — 启动时创建全部索引
  - 集合创建: ensure_collections() — 启动时创建全部集合(含校验器)
  - 集合统计: get_collection_stats() — 存储统计导出
  - 健康检查: ping_latency_ms() — 详细延迟测量

配置键 (SGP_* 前缀):
  mongodb_uri, mongodb_database
  mongodb_min_pool_size (默认 10), mongodb_max_pool_size (默认 50)
  mongodb_connect_timeout_ms (默认 5000), mongodb_server_selection_timeout_ms (默认 5000)
"""
import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase, AsyncIOMotorCollection
from pymongo import ASCENDING, DESCENDING, IndexModel
from pymongo.errors import BulkWriteError, DuplicateKeyError
from pymongo.operations import InsertOne
from pymongo.write_concern import WriteConcern

from core.config import get_settings

logger = logging.getLogger("socialgraph.db.mongodb")

_mongo_client: Optional[AsyncIOMotorClient] = None  # type: ignore[assignment]
_mongo_db: Optional[AsyncIOMotorDatabase] = None    # type: ignore[assignment]
_mongo_failed: bool = False


async def get_mongo_db() -> Optional[AsyncIOMotorDatabase]:
    """获取 MongoDB 异步数据库实例 (Lazy-Connect, 全局单例)。

    Returns:
        AsyncIOMotorDatabase 或 None (连接失败时)
    """
    global _mongo_client, _mongo_db, _mongo_failed

    if _mongo_db is not None:
        return _mongo_db
    if _mongo_failed:
        return None

    settings = get_settings()
    try:
        _mongo_client = AsyncIOMotorClient(
            settings.mongodb_uri,
            maxPoolSize=settings.mongodb_max_pool_size,
            minPoolSize=settings.mongodb_min_pool_size,
            connectTimeoutMS=settings.mongodb_connect_timeout_ms,
            serverSelectionTimeoutMS=settings.mongodb_server_selection_timeout_ms,
            # 读偏好: 优先主节点，主节点不可用时读副本
            readPreference="primaryPreferred",
        )
        # 连接测试
        await _mongo_client.admin.command("ping")
        _mongo_db = _mongo_client[settings.mongodb_database]
        logger.info(
            "MongoDB 已连接: %s/%s (pool=%d-%d)",
            settings.mongodb_uri,
            settings.mongodb_database,
            settings.mongodb_min_pool_size,
            settings.mongodb_max_pool_size,
        )
        return _mongo_db
    except Exception as e:
        logger.warning("MongoDB 不可用 (%s): %s", settings.mongodb_uri, e)
        _mongo_failed = True
        _mongo_db = None
        return None


async def get_collection(name: str) -> Optional[AsyncIOMotorCollection]:
    """获取命名集合，自动创建（MongoDB 特性）。

    Args:
        name: 集合名称，如 "operation_logs", "performance_metrics"

    Returns:
        AsyncIOMotorCollection 或 None (MongoDB 不可用时)
    """
    db = await get_mongo_db()
    if db is None:
        return None
    return db[name]


# ═══════════════════════════════════════════════════════════════════════════════
# 写关注辅助
# ═══════════════════════════════════════════════════════════════════════════════

def _get_write_concern_for_collection(collection_name: str) -> int:
    """根据集合类型返回合适的 write concern。

    策略:
      - 日志/指标类: w=0 (fire-and-forget, 不等待确认)
      - 快照/缓存/图状态: w=1 (等待主节点确认)
      - 运维/手动写入: w="majority"

    Args:
        collection_name: 集合名称

    Returns:
        write concern 值 (0, 1, 或 "majority")
    """
    fire_and_forget_collections = {"operation_logs", "operation_stats_hourly",
                                    "performance_metrics", "performance_metrics_hourly"}
    w = 0 if collection_name in fire_and_forget_collections else 1
    return w


async def fire_and_forget(collection_name: str, document: dict) -> None:
    """Fire-and-forget 写入: write_concern=0, 不等待确认, 不阻塞 API 响应。

    适用场景:
      - 操作日志 (operation_logs)
      - 性能指标 (performance_metrics)
      - 审计日志

    Args:
        collection_name: 目标集合名
        document: 要写入的文档
    """
    db = await get_mongo_db()
    if db is None:
        return
    try:
        collection = db[collection_name].with_options(
            write_concern=WriteConcern(w=0)
        )
        await collection.insert_one(document)
    except Exception as e:
        logger.debug("Fire-and-forget 写入失败 (非关键): collection=%s, error=%s",
                     collection_name, e)


async def write_with_concern(collection_name: str, document: dict,
                              w: int = 1) -> bool:
    """指定 write concern 的写入操作。

    适用场景:
      - analysis_snapshots: w=1 (快照可重算, w:1 足够)
      - cache_registry: w=1 (缓存状态需即时反映)
      - graph_snapshots: w=1 (低频写入无性能压力)

    Args:
        collection_name: 目标集合名
        document: 要写入的文档
        w: write concern (1 = 主节点确认, "majority" = 多数节点)

    Returns:
        True 如果写入成功
    """
    db = await get_mongo_db()
    if db is None:
        return False
    try:
        collection = db[collection_name].with_options(
            write_concern=WriteConcern(w=w)
        )
        await collection.insert_one(document)
        return True
    except Exception as e:
        logger.warning("写入失败: collection=%s, w=%s, error=%s",
                       collection_name, w, e)
        return False


async def bulk_write_logs(documents: List[dict]) -> int:
    """批量写入操作日志 (unordered insert_many, 遇错继续)。

    适用场景:
      - 合并 100ms 窗口内的日志批量写入
      - 减少网络往返次数, 提升吞吐

    Args:
        documents: 要写入的文档列表 (1-1000 条)

    Returns:
        成功写入的文档数, -1 表示完全失败
    """
    if not documents:
        return 0

    db = await get_mongo_db()
    if db is None:
        return -1

    try:
        collection = db.operation_logs.with_options(
            write_concern=WriteConcern(w=0)
        )
        result = await collection.insert_many(documents, ordered=False)
        return len(result.inserted_ids)
    except BulkWriteError as bwe:
        # ordered=False 时，部分写入成功
        inserted = bwe.details.get("nInserted", 0)
        errors = bwe.details.get("writeErrors", [])
        logger.debug("批量写入部分失败: 成功=%d, 错误=%d", inserted, len(errors))
        return inserted
    except Exception as e:
        logger.warning("批量写入完全失败: %s", e)
        return -1


# ═══════════════════════════════════════════════════════════════════════════════
# 集合创建与索引管理
# ═══════════════════════════════════════════════════════════════════════════════

async def ensure_ttl_index(
    collection_name: str,
    field: str,
    expire_after_seconds: int,
) -> bool:
    """确保集合存在 TTL 索引（幂等：已存在则跳过）。

    TTL 索引会自动删除超过过期时间的文档，用于:
      - operation_logs: 保留 30 天 (2592000s)
      - analysis_snapshots: 保留 90 天 (7776000s)
      - performance_metrics: 保留 7 天 (604800s)
      - performance_metrics_hourly: 保留 90 天 (7776000s)
      - operation_stats_hourly: 保留 90 天 (7776000s)
      - cache_registry: 保留 30 天 (2592000s)

    Args:
        collection_name:   集合名称
        field:             时间字段名 (如 "created_at")
        expire_after_seconds: 文档存活秒数

    Returns:
        是否成功

    使用方式 (在 lifespan startup 中):
        await ensure_ttl_index("operation_logs", "created_at", 2592000)  # 30 天
    """
    db = await get_mongo_db()
    if db is None:
        return False
    try:
        collection = db[collection_name]
        # 列出已有索引并检查是否已存在
        existing = await collection.index_information()
        ttl_name = f"{field}_ttl"
        if ttl_name in existing:
            logger.debug("TTL 索引已存在: %s.%s", collection_name, ttl_name)
            return True

        await collection.create_index(
            [(field, ASCENDING)],
            name=ttl_name,
            expireAfterSeconds=expire_after_seconds,
            background=True,  # 后台创建，不阻塞
        )
        logger.info(
            "TTL 索引已创建: %s.%s (expireAfterSeconds=%d)",
            collection_name, ttl_name, expire_after_seconds,
        )
        return True
    except Exception as e:
        logger.warning("TTL 索引创建失败: %s.%s, error=%s", collection_name, field, e)
        return False


# ── 全量索引定义 (与 schema_design.js v2.0 同步) ──────────────────────────────

_ALL_INDEXES: Dict[str, List[Dict]] = {
    "analysis_snapshots": [
        {"keys": [("snapshot_id", ASCENDING)],
         "options": {"unique": True, "name": "idx_snapshot_id"}},
        {"keys": [("user_id", ASCENDING), ("created_at", DESCENDING)],
         "options": {"name": "idx_user_timeline"}},
        {"keys": [("algorithm", ASCENDING), ("created_at", DESCENDING)],
         "options": {"name": "idx_algorithm_time"}},
        {"keys": [("user_id", ASCENDING), ("algorithm", ASCENDING), ("created_at", DESCENDING)],
         "options": {"name": "idx_user_algo_time"}},
        {"keys": [("algorithm", ASCENDING), ("execution_time_ms", DESCENDING)],
         "options": {"name": "idx_algo_exec_time"}},
        {"keys": [("created_at", ASCENDING)],
         "options": {"expireAfterSeconds": 7776000, "name": "idx_ttl_90d"}},
        {"keys": [("algorithm", ASCENDING), ("execution_time_ms", DESCENDING), ("created_at", DESCENDING)],
         "options": {"partialFilterExpression": {"execution_time_ms": {"$gt": 1000}},
                     "name": "idx_slow_queries_partial"}},
        {"keys": [("algorithm", "text"), ("parameters.description", "text")],
         "options": {"name": "idx_text_search",
                     "weights": {"algorithm": 10, "parameters.description": 5}}},
        {"keys": [("result_metadata.$**", ASCENDING)],
         "options": {"name": "idx_metadata_wildcard"}},
        {"keys": [("request_id", ASCENDING)],
         "options": {"name": "idx_request_id"}},
    ],
    "operation_logs": [
        {"keys": [("user_id", ASCENDING), ("created_at", DESCENDING)],
         "options": {"name": "idx_user_ops"}},
        {"keys": [("action", ASCENDING), ("created_at", DESCENDING)],
         "options": {"name": "idx_action_time"}},
        {"keys": [("status", ASCENDING), ("created_at", DESCENDING)],
         "options": {"name": "idx_status_time"}},
        {"keys": [("resource", ASCENDING), ("created_at", DESCENDING)],
         "options": {"name": "idx_resource_time"}},
        {"keys": [("action", ASCENDING), ("status", ASCENDING), ("created_at", DESCENDING)],
         "options": {"name": "idx_action_status_time"}},
        {"keys": [("created_at", ASCENDING)],
         "options": {"expireAfterSeconds": 2592000, "name": "idx_ttl_30d"}},
        {"keys": [("request_id", ASCENDING)],
         "options": {"name": "idx_request_id"}},
        {"keys": [("correlation_id", ASCENDING)],
         "options": {"name": "idx_correlation_id"}},
        {"keys": [("created_at", DESCENDING)],
         "options": {"partialFilterExpression": {"status": {"$in": ["failure", "timeout", "rate_limited"]}},
                     "name": "idx_failures_recent_partial"}},
        {"keys": [("session_id", ASCENDING), ("created_at", DESCENDING)],
         "options": {"name": "idx_session_time"}},
    ],
    "operation_stats_hourly": [
        {"keys": [("hour", DESCENDING)],
         "options": {"unique": True, "name": "idx_hour_unique"}},
        {"keys": [("created_at", ASCENDING)],
         "options": {"expireAfterSeconds": 7776000, "name": "idx_ttl_90d"}},
    ],
    "performance_metrics": [
        {"keys": [("metric", ASCENDING), ("timestamp", DESCENDING)],
         "options": {"name": "idx_metric_ts"}},
        {"keys": [("metric", ASCENDING), ("tags.algorithm", ASCENDING), ("timestamp", DESCENDING)],
         "options": {"name": "idx_metric_algo_ts"}},
        {"keys": [("timestamp", ASCENDING)],
         "options": {"expireAfterSeconds": 604800, "name": "idx_ttl_7d"}},
    ],
    "performance_metrics_hourly": [
        {"keys": [("metric", ASCENDING), ("hour", DESCENDING)],
         "options": {"name": "idx_metric_hour"}},
        {"keys": [("created_at", ASCENDING)],
         "options": {"expireAfterSeconds": 7776000, "name": "idx_ttl_90d"}},
    ],
    "cache_registry": [
        {"keys": [("cache_key", ASCENDING)],
         "options": {"unique": True, "name": "idx_cache_key_unique"}},
        {"keys": [("algorithm", ASCENDING), ("status", ASCENDING), ("created_at", DESCENDING)],
         "options": {"name": "idx_algo_status_time"}},
        {"keys": [("graph_data_hash", ASCENDING)],
         "options": {"name": "idx_data_hash"}},
        {"keys": [("created_at", ASCENDING)],
         "options": {"expireAfterSeconds": 2592000, "name": "idx_ttl_30d"}},
        {"keys": [("status", ASCENDING), ("expires_at", ASCENDING)],
         "options": {"partialFilterExpression": {"status": "active"},
                     "name": "idx_active_expires_partial"}},
    ],
    "graph_snapshots": [
        {"keys": [("timestamp", DESCENDING)],
         "options": {"name": "idx_timestamp_desc"}},
        {"keys": [("timestamp", DESCENDING), ("node_count", ASCENDING),
                   ("edge_count", ASCENDING), ("density", ASCENDING)],
         "options": {"name": "idx_snapshot_trend_covering"}},
        {"keys": [("data_file_hash", ASCENDING), ("timestamp", DESCENDING)],
         "options": {"name": "idx_filehash_time"}},
    ],
}


async def ensure_all_indexes() -> Dict[str, int]:
    """幂等创建所有集合的非 TTL 索引（已存在则跳过）。

    在应用启动时调用 (lifespan startup) 确保索引已就绪。
    使用 background=True 避免阻塞启动。

    与 schema_design.js 中的索引定义严格同步。

    Returns:
        {collection_name: created_count} 每个集合新建的索引数

    使用方式:
        from db.mongodb import ensure_all_indexes
        await ensure_all_indexes()
    """
    db = await get_mongo_db()
    if db is None:
        logger.warning("MongoDB 不可用，跳过索引创建")
        return {}

    results: Dict[str, int] = {}

    for coll_name, index_specs in _ALL_INDEXES.items():
        try:
            collection = db[coll_name]
            existing_indexes = await collection.index_information()
            existing_names = set(existing_indexes.keys())

            created = 0
            for spec in index_specs:
                idx_name = spec["options"].get("name", "")
                if idx_name in existing_names:
                    continue  # 索引已存在，跳过

                try:
                    await collection.create_index(
                        spec["keys"],
                        name=idx_name,
                        unique=spec["options"].get("unique", False),
                        background=spec["options"].get("background", True),
                        expireAfterSeconds=spec["options"].get("expireAfterSeconds"),
                        partialFilterExpression=spec["options"].get("partialFilterExpression"),
                        weights=spec["options"].get("weights"),
                    )
                    created += 1
                    logger.info("索引已创建: %s.%s", coll_name, idx_name)
                except Exception as idx_err:
                    logger.warning("索引创建失败: %s.%s — %s", coll_name, idx_name, idx_err)

            results[coll_name] = created
        except Exception as e:
            logger.warning("无法访问集合 %s: %s", coll_name, e)

    total = sum(results.values())
    if total > 0:
        logger.info("索引初始化完成: 新建 %d 个索引", total)
    else:
        logger.debug("索引初始化完成: 无新建索引 (全部已存在)")

    return results


# ═══════════════════════════════════════════════════════════════════════════════
# 缓存注册表 (cache_registry 集合)
# ═══════════════════════════════════════════════════════════════════════════════

async def register_cache_entry(
    cache_key: str,
    algorithm: str,
    ttl_seconds: int = 86400,
    parameters_hash: str = "",
    graph_data_hash: str = "",
    result_size_bytes: int = 0,
) -> bool:
    """注册一条缓存条目（幂等: 相同 cache_key 已存在则更新）。

    当 C++ 引擎计算完成后将结果写入 Redis 时调用，
    在 MongoDB 中记录缓存元数据以实现缓存感知查询。

    Args:
        cache_key: Redis 缓存键 (如 algo:pagerank:hash:abc123)
        algorithm: 算法类型
        ttl_seconds: Redis TTL (秒)
        parameters_hash: 算法参数 SHA256 前 16 字符
        graph_data_hash: 图数据文件 MD5
        result_size_bytes: 结果数据大小

    Returns:
        True 如果写入成功
    """
    db = await get_mongo_db()
    if db is None:
        return False

    now = datetime.now(timezone.utc)
    doc = {
        "cache_key": cache_key,
        "algorithm": algorithm,
        "parameters_hash": parameters_hash,
        "graph_data_hash": graph_data_hash,
        "result_size_bytes": result_size_bytes,
        "ttl_seconds": ttl_seconds,
        "access_count": 0,
        "last_accessed_at": None,
        "status": "active",
        "created_at": now,
        "expires_at": datetime.fromtimestamp(now.timestamp() + ttl_seconds, tz=timezone.utc),
    }

    try:
        collection = db.cache_registry
        await collection.update_one(
            {"cache_key": cache_key},
            {"$set": doc, "$setOnInsert": {"access_count": 0}},
            upsert=True,
        )
        logger.debug("缓存已注册: %s", cache_key)
        return True
    except Exception as e:
        logger.debug("缓存注册失败: %s, error=%s", cache_key, e)
        return False


async def record_cache_access(cache_key: str) -> bool:
    """记录缓存命中（access_count +1, 更新 last_accessed_at）。

    每次 Redis 缓存命中时调用，用于统计缓存使用频率。

    Args:
        cache_key: 缓存键

    Returns:
        True 更新成功
    """
    db = await get_mongo_db()
    if db is None:
        return False

    try:
        await db.cache_registry.update_one(
            {"cache_key": cache_key},
            {
                "$inc": {"access_count": 1},
                "$set": {"last_accessed_at": datetime.now(timezone.utc)},
            }
        )
        return True
    except Exception as e:
        logger.debug("缓存访问记录失败: %s, error=%s", cache_key, e)
        return False


async def get_cache_entry(cache_key: str) -> Optional[Dict]:
    """查询缓存注册表条目。

    Args:
        cache_key: 缓存键

    Returns:
        缓存条目文档或 None
    """
    db = await get_mongo_db()
    if db is None:
        return None

    try:
        return await db.cache_registry.find_one({"cache_key": cache_key})
    except Exception as e:
        logger.debug("缓存查询失败: %s, error=%s", cache_key, e)
        return None


async def invalidate_cache_by_data_hash(graph_data_hash: str) -> int:
    """根据图数据 hash 批量标记缓存为过期。

    当图数据文件更新时调用，标记所有基于旧数据的缓存为 stale。

    Args:
        graph_data_hash: 图数据文件 MD5

    Returns:
        标记为 stale 的条目数
    """
    db = await get_mongo_db()
    if db is None:
        return 0

    try:
        result = await db.cache_registry.update_many(
            {"graph_data_hash": graph_data_hash, "status": "active"},
            {"$set": {"status": "stale"}},
        )
        count = result.modified_count
        if count > 0:
            logger.info("缓存失效: data_hash=%s, 标记 %d 条目为 stale",
                        graph_data_hash, count)
        return count
    except Exception as e:
        logger.warning("缓存失效失败: %s", e)
        return 0


async def invalidate_cache_by_algorithm(algorithm: str) -> int:
    """按算法类型批量标记缓存为过期。

    Args:
        algorithm: 算法类型

    Returns:
        标记为 stale 的条目数
    """
    db = await get_mongo_db()
    if db is None:
        return 0

    try:
        result = await db.cache_registry.update_many(
            {"algorithm": algorithm, "status": "active"},
            {"$set": {"status": "stale"}},
        )
        return result.modified_count
    except Exception as e:
        logger.warning("缓存失效失败: %s", e)
        return 0


# ═══════════════════════════════════════════════════════════════════════════════
# 集合统计
# ═══════════════════════════════════════════════════════════════════════════════

async def get_collection_stats(collection_name: str) -> Optional[Dict]:
    """获取集合存储统计信息。

    使用 $collStats 聚合阶段获取精确的存储大小、文档数、平均对象大小。

    Args:
        collection_name: 集合名称

    Returns:
        统计信息字典 {size_mb, count, avg_obj_size_bytes, storage_size_mb,
                        total_index_size_mb, num_indexes}
        或 None (MongoDB 不可用/集合不存在)
    """
    db = await get_mongo_db()
    if db is None:
        return None

    try:
        collection = db[collection_name]
        # $collStats 返回 storageStats
        result = await collection.aggregate([
            {"$collStats": {"storageStats": {"scale": 1}}},
        ]).to_list(1)

        if not result:
            return None

        stats = result[0].get("storageStats", {})
        return {
            "collection": collection_name,
            "size_mb": round(stats.get("size", 0) / (1024 * 1024), 2),
            "count": stats.get("count", 0),
            "avg_obj_size_bytes": stats.get("avgObjSize", 0),
            "storage_size_mb": round(stats.get("storageSize", 0) / (1024 * 1024), 2),
            "total_index_size_mb": round(stats.get("totalIndexSize", 0) / (1024 * 1024), 2),
            "num_indexes": stats.get("nindexes", 0),
        }
    except Exception as e:
        logger.debug("集合统计获取失败: %s, error=%s", collection_name, e)
        return None


async def get_all_collection_stats() -> List[Dict]:
    """获取所有集合的存储统计 (用于运维仪表板)。

    Returns:
        统计信息列表，按 size_mb 降序排列
    """
    collections = [
        "analysis_snapshots", "operation_logs", "operation_stats_hourly",
        "performance_metrics", "performance_metrics_hourly",
        "cache_registry", "graph_snapshots",
    ]

    results = []
    for coll_name in collections:
        stats = await get_collection_stats(coll_name)
        if stats:
            results.append(stats)

    results.sort(key=lambda x: x["size_mb"], reverse=True)
    return results


# ═══════════════════════════════════════════════════════════════════════════════
# 健康检查
# ═══════════════════════════════════════════════════════════════════════════════

async def check_mongo_health() -> Tuple[bool, Optional[str], float]:
    """MongoDB 连接健康检查。

    Returns:
        (is_healthy, error_message, latency_ms)
    """
    start = time.time()
    try:
        db = await get_mongo_db()
        if db is None:
            return False, "客户端未初始化", 0
        await db.command("ping")
        latency = (time.time() - start) * 1000
        return True, None, round(latency, 2)
    except Exception as e:
        return False, str(e), 0


async def ping_latency_ms(samples: int = 3) -> Dict:
    """详细的 MongoDB 延迟探测 (多次采样)。

    Args:
        samples: 采样次数 (默认 3)

    Returns:
        {
            "min_ms": 最小延迟,
            "max_ms": 最大延迟,
            "avg_ms": 平均延迟,
            "samples": [每次采样的延迟],
            "healthy": 是否全部成功
        }
    """
    db = await get_mongo_db()
    if db is None:
        return {"min_ms": 0, "max_ms": 0, "avg_ms": 0, "samples": [], "healthy": False}

    latencies = []
    for _ in range(samples):
        try:
            start = time.time()
            await db.command("ping")
            latencies.append(round((time.time() - start) * 1000, 2))
        except Exception:
            latencies.append(-1)

    successful = [l for l in latencies if l >= 0]
    if not successful:
        return {"min_ms": 0, "max_ms": 0, "avg_ms": 0, "samples": latencies, "healthy": False}

    return {
        "min_ms": min(successful),
        "max_ms": max(successful),
        "avg_ms": round(sum(successful) / len(successful), 2),
        "samples": latencies,
        "healthy": len(successful) == samples,
    }


async def close_mongo():
    """关闭 MongoDB 客户端（应用关闭时调用）。"""
    global _mongo_client, _mongo_db, _mongo_failed

    if _mongo_client:
        try:
            _mongo_client.close()
        except Exception:
            pass
        _mongo_client = None
        _mongo_db = None
        _mongo_failed = False

    logger.info("MongoDB 连接已关闭")
