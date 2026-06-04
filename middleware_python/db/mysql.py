"""
SocialGraph Pro — MySQL 异步连接池 (aiomysql)

功能:
  - 连接池管理 (Lazy-Connect 模式)
  - 便捷查询: execute_query / execute_one / execute_write / execute_insert
  - 事务上下文管理器: async with mysql_transaction()
  - 连接借出健康检查: pool_recycle 自动重连
  - 优雅降级: MySQL 不可用时返回安全默认值

配置键 (SGP_* 前缀):
  mysql_host, mysql_port, mysql_user, mysql_password, mysql_database
  mysql_pool_min_size (默认 5), mysql_pool_max_size (默认 20)
  mysql_pool_recycle (默认 3600s), mysql_connect_timeout (默认 5s)
"""
import logging
from contextlib import asynccontextmanager
from typing import Optional, Any, AsyncIterator

import aiomysql

from core.config import get_settings

logger = logging.getLogger("socialgraph.db.mysql")

_mysql_pool: Optional[aiomysql.Pool] = None  # type: ignore[assignment]
_mysql_failed: bool = False


async def get_mysql_pool() -> Optional[aiomysql.Pool]:
    """获取 MySQL 异步连接池 (Lazy-Connect, 全局单例)。

    Returns:
        aiomysql.Pool 或 None (连接失败时)
    """
    global _mysql_pool, _mysql_failed

    if _mysql_pool is not None:
        return _mysql_pool
    if _mysql_failed:
        return None

    settings = get_settings()
    try:
        _mysql_pool = await aiomysql.create_pool(
            host=settings.mysql_host,
            port=settings.mysql_port,
            user=settings.mysql_user,
            password=settings.mysql_password,
            db=settings.mysql_database,
            minsize=settings.mysql_pool_min_size,
            maxsize=settings.mysql_pool_max_size,
            pool_recycle=settings.mysql_pool_recycle,
            connect_timeout=settings.mysql_connect_timeout,
            autocommit=True,
        )
        logger.info(
            "MySQL 连接池已建立: %s:%s/%s (pool=%d-%d)",
            settings.mysql_host,
            settings.mysql_port,
            settings.mysql_database,
            settings.mysql_pool_min_size,
            settings.mysql_pool_max_size,
        )
        return _mysql_pool
    except Exception as e:
        logger.warning(
            "MySQL 不可用 (%s:%s): %s",
            settings.mysql_host,
            settings.mysql_port,
            e,
        )
        _mysql_failed = True
        _mysql_pool = None
        return None


async def check_mysql_health() -> tuple[bool, Optional[str], float]:
    """MySQL 连接健康检查。

    Returns:
        (is_healthy, error_message, latency_ms)
    """
    import time
    start = time.time()
    try:
        pool = await get_mysql_pool()
        if pool is None:
            return False, "连接池未初始化", 0
        async with pool.acquire() as conn:
            cursor = await conn.cursor()
            await cursor.execute("SELECT 1")
            await cursor.fetchone()
        latency = (time.time() - start) * 1000
        return True, None, round(latency, 2)
    except Exception as e:
        return False, str(e), 0


@asynccontextmanager
async def get_mysql_connection():
    """异步上下文管理器：自动获取和释放 MySQL 连接。

    使用方式:
        async with get_mysql_connection() as conn:
            cursor = await conn.cursor(aiomysql.DictCursor)
            await cursor.execute("SELECT ...")
            rows = await cursor.fetchall()

    Raises:
        RuntimeError: MySQL 连接池不可用
    """
    pool = await get_mysql_pool()
    if pool is None:
        raise RuntimeError("MySQL 连接池不可用")
    conn = await pool.acquire()
    try:
        yield conn
    finally:
        await pool.release(conn)


@asynccontextmanager
async def mysql_transaction() -> AsyncIterator[aiomysql.Connection]:
    """异步事务上下文管理器: 自动 COMMIT 或 ROLLBACK。

    使用方式:
        async with mysql_transaction() as conn:
            await conn.cursor().execute("INSERT INTO users ...")
            await conn.cursor().execute("UPDATE accounts ...")
            # 无异常时自动 COMMIT，异常时自动 ROLLBACK

    注意:
      - 事务期间 autocommit 临时关闭
      - 上下文退出后恢复 autocommit=True
      - 连接自动归还连接池
    """
    pool = await get_mysql_pool()
    if pool is None:
        raise RuntimeError("MySQL 连接池不可用")

    conn = await pool.acquire()
    await conn.begin()  # 显式开启事务（关闭 autocommit）
    try:
        yield conn
        await conn.commit()
        logger.debug("事务已提交")
    except Exception:
        await conn.rollback()
        logger.debug("事务已回滚")
        raise
    finally:
        await pool.release(conn)


async def execute_query(sql: str, params: tuple = ()) -> list[dict[str, Any]]:
    """执行 SELECT 查询并返回结果列表 (DictCursor 自动列名映射)。

    Args:
        sql:    SQL 查询语句 (使用 %s 占位符)
        params: 参数化查询参数

    Returns:
        字典列表，MySQL 不可用时返回空列表 []
    """
    pool = await get_mysql_pool()
    if pool is None:
        return []
    async with pool.acquire() as conn:
        cursor = await conn.cursor(aiomysql.DictCursor)
        await cursor.execute(sql, params)
        rows = await cursor.fetchall()
        return rows


async def execute_one(sql: str, params: tuple = ()) -> Optional[dict[str, Any]]:
    """执行 SELECT 查询并返回单行结果 (DictCursor)。

    Returns:
        字典或 None (无匹配行 或 MySQL 不可用时)
    """
    pool = await get_mysql_pool()
    if pool is None:
        return None
    async with pool.acquire() as conn:
        cursor = await conn.cursor(aiomysql.DictCursor)
        await cursor.execute(sql, params)
        row = await cursor.fetchone()
        return row


async def execute_write(sql: str, params: tuple = ()) -> int:
    """执行 INSERT/UPDATE/DELETE 并返回影响行数。

    Returns:
        受影响的行数，或 0（连接不可用时）
    """
    pool = await get_mysql_pool()
    if pool is None:
        return 0
    async with pool.acquire() as conn:
        cursor = await conn.cursor()
        await cursor.execute(sql, params)
        return cursor.rowcount


async def execute_insert(sql: str, params: tuple = ()) -> Optional[int]:
    """执行 INSERT 并返回自增 ID (lastrowid)。

    Returns:
        自增 ID 或 None（非自增表 或 连接不可用时）
    """
    pool = await get_mysql_pool()
    if pool is None:
        return None
    async with pool.acquire() as conn:
        cursor = await conn.cursor()
        await cursor.execute(sql, params)
        return cursor.lastrowid


async def close_mysql():
    """关闭 MySQL 连接池（应用关闭时调用）。"""
    global _mysql_pool, _mysql_failed

    if _mysql_pool:
        _mysql_pool.close()
        await _mysql_pool.wait_closed()
        _mysql_pool = None
        _mysql_failed = False

    logger.info("MySQL 连接池已关闭")
