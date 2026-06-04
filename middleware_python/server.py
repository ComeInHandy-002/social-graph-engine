"""
SocialGraph Pro — FastAPI 应用工厂入口

模块化架构:
  server.py (应用工厂) → routes/ (API路由) → services/ (业务逻辑)
                                             → db/ (数据库连接)
  middleware/ (CORS/Compression/RateLimit/RequestLog/ErrorHandler) — 横切关注点
  auth/ (认证授权) — 独立模块
  websockets/ (WebSocket) — 实时分析

中间件执行流 (请求从外到内):
  CORS → Compression → RateLimit → RequestLogger → ErrorHandler → Route Handler

启动:
  uvicorn server:app --host 0.0.0.0 --port 8000
  或
  python server.py  (调用 main() 函数启动)
"""
import asyncio
import logging
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from core.config import get_settings
from core.exceptions import AppException
from logging_config import setup_logging

# ── 初始化日志 ────────────────────────────────────────────────────
settings = get_settings()
setup_logging(settings.log_level, settings.environment)
logger = logging.getLogger("socialgraph")


# ═══════════════════════════════════════════════════════════════════
# 应用生命周期管理
# ═══════════════════════════════════════════════════════════════════

@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用启动/关闭事件处理器。

    启动时:
      1. 初始化 C++ 引擎进程池
      2. 预连接数据库 (异步 lazy-connect)
    关闭时:
      1. 关闭 C++ 引擎进程池
      2. 关闭所有数据库连接
    """
    logger.info("=" * 60)
    logger.info("SocialGraph Pro v%s 启动中...", settings.app_version)
    logger.info("环境: %s | 日志级别: %s", settings.environment, settings.log_level)
    logger.info("=" * 60)

    # ── 启动: 预热连接池 ──
    try:
        # 预初始化 C++ 引擎进程池（非阻塞，失败不阻止启动）
        asyncio.ensure_future(_warmup_services())
    except Exception as e:
        logger.warning("服务预热失败 (非致命): %s", e)

    yield  # ← 应用运行中

    # ── 关闭: 清理资源 ──
    logger.info("正在关闭 SocialGraph Pro...")
    await _shutdown_services()
    logger.info("SocialGraph Pro 已关闭")


async def _warmup_services():
    """预热服务（异步，非阻塞启动）。"""
    from db.redis import get_redis_async
    from db.mysql import get_mysql_pool
    from db.mongodb import get_mongo_db, ensure_all_indexes
    from db.neo4j import get_neo4j_driver

    tasks = [
        get_redis_async(),
        get_mysql_pool(),
        get_mongo_db(),
        get_neo4j_driver(),
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            logger.debug("服务预热 %d 异常 (非致命): %s", i, result)

    # MongoDB 索引全量对齐 (幂等，已存在自动跳过)
    try:
        idx_results = await ensure_all_indexes()
        new_total = sum(idx_results.values())
        if new_total > 0:
            logger.info("MongoDB 索引同步完成: 创建了 %d 个新索引", new_total)
    except Exception as e:
        logger.debug("MongoDB 索引同步跳过 (非致命): %s", e)


async def _shutdown_services():
    """关闭所有服务连接。"""
    from db.redis import close_redis
    from db.mysql import close_mysql
    from db.mongodb import close_mongo
    from db.neo4j import close_neo4j

    tasks = [
        close_redis(),
        close_mysql(),
        close_mongo(),
        close_neo4j(),
    ]
    await asyncio.gather(*tasks, return_exceptions=True)


# ═══════════════════════════════════════════════════════════════════
# 应用工厂
# ═══════════════════════════════════════════════════════════════════

def create_app() -> FastAPI:
    """创建并配置 FastAPI 应用实例。

    组装顺序:
      1. 创建 FastAPI 实例 (含 lifespan)
      2. 注册中间件栈 (请求执行流从外到内):
         CORSMiddleware (最外层) → GZipMiddleware (压缩) →
         RateLimitMiddleware (限流) → RequestLoggingMiddleware (日志) →
         ErrorHandlerMiddleware (最内层, 捕获路由异常)
      3. 注册全局异常处理器 (Starlette HTTPException + RequestValidationError + 兜底)
      4. 注册 API 路由 (health, auth, graph, export, admin)
      5. 注册 WebSocket 端点 (/api/v1/ws/analysis)
    """
    # 1. 创建实例
    app = FastAPI(
        title="SocialGraph Pro | 社交网络分析引擎",
        version=settings.app_version,
        description=(
            "高性能图计算 RESTful API，支持 Betweenness Centrality、"
            "PageRank、LPA、K-Core 等 10 种图算法。"
        ),
        lifespan=lifespan,
        docs_url="/docs" if settings.debug or settings.environment != "production" else None,
        redoc_url="/redoc" if settings.debug or settings.environment != "production" else None,
    )

    # 2. 注册中间件
    #
    # Starlette 中间件栈行为: 先注册的先执行 (innermost), 后注册的后执行 (outermost)
    # 即: add_middleware(A); add_middleware(B) → B wraps A wraps route_handler
    #
    # 目标执行流:
    #   Request → CORS → Compression → RateLimit → RequestLogger → ErrorHandler → Route Handler
    #
    # 因此注册顺序应为（从内到外）: ErrorHandler → RequestLogger → RateLimit → Compression → CORS

    # 2a. 统一异常处理 — 最内层 (先捕获 route handler 异常, 配合全局 exception_handler 兜底)
    from middleware.error_handler import ErrorHandlerMiddleware, register_exception_handlers
    app.add_middleware(ErrorHandlerMiddleware)

    # 2b. 请求日志 — JSON 结构化日志 (记录每个请求的方法/路径/状态码/耗时)
    from middleware.request_logger import RequestLoggingMiddleware
    app.add_middleware(RequestLoggingMiddleware)

    # 2c. 限流 — 滑动窗口 (基于 Redis sorted set, 三层: anonymous/authenticated/api_key)
    from middleware.rate_limiter import RateLimitMiddleware
    app.add_middleware(RateLimitMiddleware)

    # 2d. GZip 压缩 — 响应体 > 1KB 自动压缩 (减少带宽, text/json/html 类型)
    from middleware.compression import create_compression_middleware
    app.add_middleware(create_compression_middleware())

    # 2e. CORS — 最外层 (环境自适应 origins, 最先处理 OPTIONS preflight 短路)
    if settings.environment == "production":
        cors_origins = [
            "http://localhost",
            "http://127.0.0.1",
        ]
    else:
        cors_origins = [
            "http://localhost:8080", "http://localhost:8081",
            "http://127.0.0.1:8080", "http://127.0.0.1:8081",
            "http://localhost:8000", "http://127.0.0.1:8000",
        ]

    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID", "X-API-Key"],
        allow_credentials=False,
        expose_headers=["X-Request-ID", "X-RateLimit-Limit", "X-RateLimit-Remaining", "X-RateLimit-Reset"],
    )

    # 3. 注册异常处理器
    register_exception_handlers(app)

    # 4. 注册 API 路由
    _register_routers(app)

    # 5. 注册 WebSocket 端点
    _register_websockets(app)

    return app


def _register_routers(app: FastAPI):
    """注册所有 API 路由模块。"""
    from routes.graph import router as graph_router
    from routes.export import router as export_router
    from routes.health import router as health_router
    from routes.admin import router as admin_router
    from auth.router import router as auth_router

    app.include_router(health_router)      # /api/v1/health
    app.include_router(auth_router)        # /api/v1/auth/*
    app.include_router(graph_router)       # /api/v1/graph/*
    app.include_router(export_router)      # /api/v1/graph/export/*
    app.include_router(admin_router)       # /api/v1/admin/*


def _register_websockets(app: FastAPI):
    """注册 WebSocket 端点。"""
    from websockets.analysis_ws import ws_analysis_handler
    from websockets.live_data_ws import ws_live_handler

    app.websocket("/api/v1/ws/analysis")(ws_analysis_handler)
    app.websocket("/api/v1/ws/live")(ws_live_handler)


# ═══════════════════════════════════════════════════════════════════
# 应用实例
# ═══════════════════════════════════════════════════════════════════

app = create_app()


# ═══════════════════════════════════════════════════════════════════
# 直接运行入口
# ═══════════════════════════════════════════════════════════════════

def main():
    """直接运行 python server.py 启动应用。"""
    import uvicorn
    import asyncio

    # Windows 需要选择不同的事件循环策略
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    uvicorn.run(
        "server:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.debug,
        log_level=settings.log_level.lower(),
        access_log=False,  # 由我们的 RequestLoggingMiddleware 处理
    )


if __name__ == "__main__":
    main()
