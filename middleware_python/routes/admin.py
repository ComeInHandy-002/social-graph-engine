"""
SocialGraph Pro — 管理员专用路由

端点:
  GET    /api/v1/admin/config                — 查看系统配置
  PUT    /api/v1/admin/config/{key}          — 更新系统配置
  POST   /api/v1/admin/cache/invalidate      — 手动失效缓存
  GET    /api/v1/admin/metrics               — 获取性能指标摘要
  POST   /api/v1/admin/maintenance           — 切换维护模式
"""
import logging

from fastapi import APIRouter, Depends, Query

from core.config import get_settings
from core.dependencies import get_current_admin
from core.exceptions import BadRequestError, NotFoundError

logger = logging.getLogger("socialgraph.routes.admin")

router = APIRouter(prefix="/api/v1/admin", tags=["管理员"])

# 所有管理端点都需要 admin 角色
router_dependencies = [Depends(get_current_admin)]


@router.get("/config")
async def get_system_config(
    current_user: dict = Depends(get_current_admin),
):
    """获取所有系统配置项。"""
    from db.mysql import execute_query

    rows = await execute_query(
        "SELECT config_key, config_value, value_type, description, updated_at "
        "FROM system_config ORDER BY config_key"
    )

    return {
        "status": "success",
        "configs": [
            {
                "key": r["config_key"],
                "value": r["config_value"],
                "type": r["value_type"],
                "description": r["description"],
                "updated_at": r["updated_at"].isoformat() if r["updated_at"] else None,
            }
            for r in rows
        ],
    }


@router.put("/config/{config_key}")
async def update_system_config(
    config_key: str,
    value: str,
    current_user: dict = Depends(get_current_admin),
):
    """更新系统配置项（热更新，无需重启）。"""
    from db.mysql import execute_one, execute_write
    from datetime import datetime, timezone

    # 检查配置项是否存在
    existing = await execute_one(
        "SELECT id, value_type FROM system_config WHERE config_key = %s",
        (config_key,),
    )
    if not existing:
        raise NotFoundError(f"配置项不存在: {config_key}")

    # 类型转换校验（可选）
    if existing["value_type"] == "int":
        try:
            int(value)
        except ValueError:
            raise BadRequestError(f"配置项 {config_key} 需要整数类型，收到: {value}")
    elif existing["value_type"] == "bool":
        if value.lower() not in ("true", "false", "1", "0"):
            raise BadRequestError(f"配置项 {config_key} 需要布尔类型，收到: {value}")

    now = datetime.now(timezone.utc)
    rows = await execute_write(
        "UPDATE system_config SET config_value = %s, updated_by = %s, updated_at = %s "
        "WHERE config_key = %s",
        (value, current_user["user_id"], now, config_key),
    )

    logger.info("系统配置已更新: key=%s, value=%s, by=%s", config_key, value, current_user["user_id"])

    return {
        "status": "success",
        "message": f"配置 {config_key} 已更新为 {value}",
        "config_key": config_key,
        "config_value": value,
    }


@router.post("/cache/invalidate")
async def invalidate_cache(
    pattern: str = Query("social_graph:*", description="Redis 键匹配模式"),
    current_user: dict = Depends(get_current_admin),
):
    """手动失效缓存（按模式匹配）。

    示例:
      - pattern=social_graph:pagerank:*  → 仅失效 PageRank 缓存
      - pattern=social_graph:*           → 失效所有图数据缓存
      - pattern=blacklist:*              → 清理黑名单记录
      - pattern=rate_limit:*             → 重置所有限流计数器
    """
    from services.cache import invalidate_cache

    # 安全检查: 不允许删除所有 Redis 键
    if pattern == "*":
        raise BadRequestError("不允许清除所有 Redis 键，请指定具体模式 (如 social_graph:*)")

    count = await invalidate_cache(pattern)

    logger.warning("管理员手动失效缓存: pattern=%s, count=%d, by=%s",
                   pattern, count, current_user["user_id"])

    return {
        "status": "success",
        "message": f"已失效 {count} 条缓存记录",
        "pattern": pattern,
        "invalidated_count": count,
    }


@router.get("/metrics")
async def get_metrics_summary(
    current_user: dict = Depends(get_current_admin),
):
    """获取性能指标摘要（最近 1 小时）。

    返回:
      - cache_hit_rate: 缓存命中率
      - top_algorithms: 最常用算法 Top 10
      - avg_latency: 各算法平均延迟
    """
    from db.mongodb import get_mongo_db

    db = await get_mongo_db()
    if db is None:
        return {"status": "degraded", "message": "MongoDB 不可用，无法获取指标"}

    from datetime import datetime, timezone, timedelta

    one_hour_ago = datetime.now(timezone.utc) - timedelta(hours=1)

    # 算法运行次数
    algo_stats = await db.analysis_snapshots.aggregate([
        {"$match": {"created_at": {"$gte": one_hour_ago}}},
        {"$group": {
            "_id": "$algorithm",
            "count": {"$sum": 1},
            "avg_time_ms": {"$avg": "$execution_time_ms"},
        }},
        {"$sort": {"count": -1}},
        {"$limit": 10},
    ]).to_list(10)

    # 操作统计
    op_stats = await db.operation_logs.aggregate([
        {"$match": {"created_at": {"$gte": one_hour_ago}}},
        {"$group": {"_id": "$action", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
    ]).to_list(20)

    # 缓存命中率
    cache_stats = await db.operation_logs.aggregate([
        {"$match": {
            "action": "run_algorithm",
            "created_at": {"$gte": one_hour_ago},
        }},
        {"$group": {
            "_id": None,
            "total": {"$sum": 1},
            "hits": {"$sum": {"$cond": [{"$eq": ["$details.cache_hit", True]}, 1, 0]}},
        }},
    ]).to_list(1)

    hit_rate = 0
    if cache_stats:
        total = cache_stats[0].get("total", 0)
        hits = cache_stats[0].get("hits", 0)
        hit_rate = round(hits / total * 100, 1) if total > 0 else 0

    return {
        "status": "success",
        "period": "1 hour",
        "cache_hit_rate": hit_rate,
        "top_algorithms": [
            {"algorithm": s["_id"], "count": s["count"], "avg_time_ms": round(s.get("avg_time_ms", 0), 1)}
            for s in algo_stats
        ],
        "operations": [
            {"action": s["_id"], "count": s["count"]}
            for s in op_stats
        ],
    }


@router.post("/maintenance")
async def toggle_maintenance(
    enable: bool = Query(..., description="true=开启维护模式, false=关闭"),
    current_user: dict = Depends(get_current_admin),
):
    """切换维护模式。

    维护模式下，只有 admin 用户可以访问系统。
    """
    from db.mysql import execute_write
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    await execute_write(
        "UPDATE system_config SET config_value = %s, updated_by = %s, updated_at = %s "
        "WHERE config_key = 'maintenance.mode'",
        ("true" if enable else "false", current_user["user_id"], now),
    )

    logger.warning("维护模式 %s by %s", "开启" if enable else "关闭", current_user["user_id"])

    return {
        "status": "success",
        "maintenance_mode": enable,
        "message": "维护模式已开启，仅管理员可访问" if enable else "维护模式已关闭，恢复正常访问",
    }


# ═══════════════════════════════════════════════════════════════════
# Neo4j Schema 管理
# ═══════════════════════════════════════════════════════════════════

@router.post("/schema/init")
async def initialize_neo4j_schema(
    current_user: dict = Depends(get_current_admin),
):
    """初始化 Neo4j 图数据模型的全部索引和约束。

    创建: 4 个唯一性约束 + 12 个 B-tree 索引 + 2 个复合索引
         + 2 个全文索引 + 1 个属性存在性约束。

    幂等操作: 所有语句使用 IF NOT EXISTS，可安全重复执行。
    需要 admin 角色。
    """
    from db.neo4j_schema import initialize_schema

    result = await initialize_schema()
    logger.info(
        "Neo4j Schema 初始化: status=%s, created=%d",
        result.get("status"),
        len(result.get("created", [])),
    )
    return result


@router.get("/schema/verify")
async def verify_neo4j_schema(
    current_user: dict = Depends(get_current_admin),
):
    """验证当前 Neo4j 数据库中的索引和约束状态。

    返回已创建的索引列表和约束列表，便于验证 Schema 是否符合预期。
    需要 admin 角色。
    """
    from db.neo4j_schema import verify_indexes

    result = await verify_indexes()
    return result


@router.post("/schema/explain")
async def explain_neo4j_query(
    query_name: str,
    current_user: dict = Depends(get_current_admin),
):
    """对指定查询执行 EXPLAIN，返回查询执行计划。

    Args:
        query_name: 查询名称 (Q1 ~ Q10)

    用于开发调试：验证索引是否被正确命中。
    需要 admin 角色。
    """
    from db.neo4j_schema import explain_query

    result = await explain_query(query_name.upper())
    return result
