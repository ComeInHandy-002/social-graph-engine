"""
SocialGraph Pro — 数据库连接池管理 (Lazy-Connect 模式)

遵循 server.py 既有的 lazy-init 约定:
  - 首次访问时才建立连接 (兼容数据库不可用的降级场景)
  - 全局单例缓存 driver/client
  - False 哨兵值表示"已尝试但连接失败"

使用方式:
    from database import get_mysql_pool, get_mongo_client

    async def some_endpoint():
        pool = await get_mysql_pool()
        if pool:
            async with pool.acquire() as conn:
                ...
        # 否则回退到无数据库模式
"""

import os
import logging

logger = logging.getLogger("socialgraph.database")

# ==========================================
# 全局缓存 (遵循 server.py 的 lazy-init 模式)
# ==========================================
_mysql_pool = None
_mongo_client = None


# ============================================================================
# MySQL 连接池 (aiomysql / SQLAlchemy async)
# ============================================================================

async def get_mysql_pool():
    """
    获取 MySQL 异步连接池。

    连接参数来自环境变量:
        MYSQL_HOST     (默认: 127.0.0.1)
        MYSQL_PORT     (默认: 3306)
        MYSQL_USER     (默认: socialgraph)
        MYSQL_PASSWORD (默认: sgpass123)
        MYSQL_DATABASE (默认: socialgraph)

    Returns:
        aiomysql.Pool 或 None (连接失败时)
    """
    global _mysql_pool
    if _mysql_pool is not None:
        return _mysql_pool if _mysql_pool is not False else None

    host = os.environ.get("MYSQL_HOST", "127.0.0.1")
    port = int(os.environ.get("MYSQL_PORT", "3306"))
    user = os.environ.get("MYSQL_USER", "socialgraph")
    password = os.environ.get("MYSQL_PASSWORD", "sgpass123")
    database = os.environ.get("MYSQL_DATABASE", "socialgraph")

    try:
        import aiomysql
        _mysql_pool = await aiomysql.create_pool(
            host=host,
            port=port,
            user=user,
            password=password,
            db=database,
            minsize=5,
            maxsize=20,
            pool_recycle=3600,       # 1小时回收, 防止 MySQL wait_timeout 断开
            connect_timeout=5,
            autocommit=True,
        )
        logger.info("MySQL 连接池已建立: %s:%s/%s (pool_size=5-20)", host, port, database)
        return _mysql_pool
    except Exception as e:
        logger.warning("MySQL 不可用 (%s:%s): %s", host, port, e)
        _mysql_pool = False
        return None


async def get_mysql_connection():
    """
    获取单个 MySQL 连接 (便捷方法)。

    用于简单的查询场景, 无需管理连接池。

    Returns:
        aiomysql.Connection 或 None
    """
    pool = await get_mysql_pool()
    if pool:
        return await pool.acquire()
    return None


# ============================================================================
# MongoDB 客户端 (PyMongo / Motor async)
# ============================================================================

async def get_mongo_client():
    """
    获取 MongoDB 异步客户端。

    连接参数来自环境变量:
        MONGODB_URI      (默认: mongodb://127.0.0.1:27017/)
        MONGODB_DATABASE (默认: socialgraph_analytics)

    Returns:
        motor.motor_asyncio.AsyncIOMotorDatabase 或 None
    """
    global _mongo_client
    if _mongo_client is not None:
        return _mongo_client if _mongo_client is not False else None

    uri = os.environ.get("MONGODB_URI", "mongodb://127.0.0.1:27017/")
    db_name = os.environ.get("MONGODB_DATABASE", "socialgraph_analytics")

    try:
        import motor.motor_asyncio
        client = motor.motor_asyncio.AsyncIOMotorClient(
            uri,
            maxPoolSize=50,
            minPoolSize=10,
            connectTimeoutMS=5000,
            serverSelectionTimeoutMS=5000,
        )
        # 连接测试
        await client.admin.command("ping")
        _mongo_client = client[db_name]
        logger.info("MongoDB 已连接: %s (pool=10-50)", uri)
        return _mongo_client
    except Exception as e:
        logger.warning("MongoDB 不可用 (%s): %s", uri, e)
        _mongo_client = False
        return None


# ============================================================================
# 数据库健康检查
# ============================================================================

async def check_all_databases():
    """
    检查所有数据库的连接状态。

    Returns:
        dict: {
            "mysql": "connected" | "unavailable",
            "mongodb": "connected" | "unavailable",
            "redis": "connected" | "unavailable",
            "neo4j": "connected" | "unavailable"
        }
    """
    status = {}

    # MySQL
    try:
        pool = await get_mysql_pool()
        status["mysql"] = "connected" if pool else "unavailable"
    except Exception:
        status["mysql"] = "unavailable"

    # MongoDB
    try:
        mongo = await get_mongo_client()
        status["mongodb"] = "connected" if mongo else "unavailable"
    except Exception:
        status["mongodb"] = "unavailable"

    # Redis (import server's get_redis — avoid circular import)
    try:
        from server import get_redis
        r = get_redis()
        status["redis"] = "connected" if r else "unavailable"
    except Exception:
        status["redis"] = "unavailable"

    # Neo4j
    try:
        from server import get_neo4j
        n = get_neo4j()
        status["neo4j"] = "connected" if n else "unavailable"
    except Exception:
        status["neo4j"] = "unavailable"

    return status
