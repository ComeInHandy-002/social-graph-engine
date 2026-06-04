"""
SocialGraph Pro — 深度健康检查路由

端点:
  GET /api/v1/health — 深度健康检查
  GET /api/v1/health/live — Kubernetes liveness probe (仅检查进程存活)
  GET /api/v1/health/ready — Kubernetes readiness probe (检查所有依赖)
"""
import logging
import os
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Request

from models.health import DeepHealthResponse, ComponentHealth
from core.config import get_settings

logger = logging.getLogger("socialgraph.routes.health")

router = APIRouter(prefix="/api/v1/health", tags=["健康检查"])

# 应用启动时间（用于 uptime 计算）
_app_start_time = time.time()


@router.get("", response_model=DeepHealthResponse)
async def health_check(request: Request):
    """深度健康检查 — 验证所有依赖组件的连接状态。

    检测顺序（并行执行以缩短响应时间）:
      1. C++ 引擎可执行文件存在性
      2. Redis 连接 + PING
      3. Neo4j 连接 + Cypher RETURN 1
      4. MySQL 连接池
      5. MongoDB PING

    响应包含每个组件的独立状态和延迟。
    """
    import asyncio

    settings = get_settings()
    request_id = getattr(request.state, "request_id", "unknown")

    # 并行检查所有组件
    results = await asyncio.gather(
        _check_cpp_engine(settings),
        _check_redis(),
        _check_neo4j(),
        _check_mysql(),
        _check_mongodb(),
        return_exceptions=True,
    )

    component_names = ["cpp_engine", "redis", "neo4j", "mysql", "mongodb"]
    components = {}
    all_healthy = True

    for name, result in zip(component_names, results):
        if isinstance(result, Exception):
            components[name] = ComponentHealth(
                status="unavailable",
                message=str(result),
            )
            all_healthy = False
        else:
            components[name] = result
            if result.status != "healthy":
                all_healthy = False

    # 汇总状态
    all_healthy = all(
        c.status == "healthy"
        for c in components.values()
    )

    return DeepHealthResponse(
        status="healthy" if all_healthy else "degraded",
        version=settings.app_version,
        uptime_seconds=round(time.time() - _app_start_time, 1),
        components=components,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


@router.get("/live")
async def liveness_probe():
    """Kubernetes Liveness Probe: 仅检查进程是否存活。

    极简响应，不做任何外部依赖检查。
    """
    return {"status": "alive"}


@router.get("/ready")
async def readiness_probe():
    """Kubernetes Readiness Probe: 检查核心依赖是否就绪。

    核心依赖: C++ 引擎 + Redis
    非核心: MySQL, MongoDB, Neo4j（可降级）
    """
    import asyncio

    settings = get_settings()

    critical_tasks = [
        _check_cpp_engine(settings),
        _check_redis(),
    ]

    results = await asyncio.gather(*critical_tasks, return_exceptions=True)

    all_ready = all(
        not isinstance(r, Exception) and r.status == "healthy"
        for r in results
    )

    if all_ready:
        return {"status": "ready"}
    else:
        return {"status": "not_ready"}


# ═══════════════════════════════════════════════════════════════════
# 组件检查函数
# ═══════════════════════════════════════════════════════════════════

async def _check_cpp_engine(settings) -> ComponentHealth:
    """检查 C++ 引擎可执行文件是否存在且可执行。"""
    start = time.time()
    path = settings.cpp_engine_path

    if not path or not os.path.exists(path):
        return ComponentHealth(
            status="unavailable",
            message=f"引擎文件不存在: {path}",
        )

    if not os.access(path, os.X_OK):
        return ComponentHealth(
            status="unavailable",
            message=f"引擎文件不可执行: {path}",
        )

    latency = (time.time() - start) * 1000
    return ComponentHealth(status="healthy", latency_ms=round(latency, 2))


async def _check_redis() -> ComponentHealth:
    """检查 Redis 连接。"""
    start = time.time()
    from db.redis import get_redis_async

    try:
        r = await get_redis_async()
        if r is None:
            return ComponentHealth(status="unavailable", message="Redis 客户端未初始化")
        await r.ping()
        latency = (time.time() - start) * 1000
        return ComponentHealth(status="healthy", latency_ms=round(latency, 2))
    except Exception as e:
        return ComponentHealth(status="unavailable", message=str(e))


async def _check_neo4j() -> ComponentHealth:
    """检查 Neo4j 连接。"""
    start = time.time()
    from db.neo4j import get_neo4j_driver

    try:
        driver = await get_neo4j_driver()
        if driver is None:
            return ComponentHealth(status="unavailable", message="Neo4j 驱动未初始化")
        async with driver.session() as session:
            await session.run("RETURN 1")
        latency = (time.time() - start) * 1000
        return ComponentHealth(status="healthy", latency_ms=round(latency, 2))
    except Exception as e:
        return ComponentHealth(status="unavailable", message=str(e))


async def _check_mysql() -> ComponentHealth:
    """检查 MySQL 连接。"""
    start = time.time()
    from db.mysql import get_mysql_pool

    try:
        pool = await get_mysql_pool()
        if pool is None:
            return ComponentHealth(status="unavailable", message="MySQL 连接池未初始化")
        async with pool.acquire() as conn:
            cursor = await conn.cursor()
            await cursor.execute("SELECT 1")
            await cursor.fetchone()
        latency = (time.time() - start) * 1000
        return ComponentHealth(status="healthy", latency_ms=round(latency, 2))
    except Exception as e:
        return ComponentHealth(status="unavailable", message=str(e))


async def _check_mongodb() -> ComponentHealth:
    """检查 MongoDB 连接。"""
    start = time.time()
    from db.mongodb import get_mongo_db

    try:
        db = await get_mongo_db()
        if db is None:
            return ComponentHealth(status="unavailable", message="MongoDB 客户端未初始化")
        await db.command("ping")
        latency = (time.time() - start) * 1000
        return ComponentHealth(status="healthy", latency_ms=round(latency, 2))
    except Exception as e:
        return ComponentHealth(status="unavailable", message=str(e))
