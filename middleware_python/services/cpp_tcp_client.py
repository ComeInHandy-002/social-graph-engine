"""
SocialGraph Pro — C++ 引擎 TCP 客户端

替代 subprocess 模式的持久连接方案:
  - C++ 引擎以 TCP Server 模式运行 (backend_cpp/server/tcp_server.h)
  - Python 通过 TCP 长连接发送 JSON 命令, 接收 JSON 结果
  - 连接池复用, 避免每次请求都启动新进程 (subprocess 开销 ~50ms/次)

启动 C++ TCP Server:
  cd backend_cpp
  ./cmake-build-debug/graph_engine.exe facebook_combined.txt serve --port 9555

架构对比:
  旧: Python → subprocess.run(engine) → stdout JSON → 解析返回  (每次启动进程)
  新: Python → TCP connect → send JSON → recv JSON → 解析返回  (长连接复用)
"""
import asyncio
import json
import logging
import time
from typing import Optional

from core.config import get_settings
from core.exceptions import CppEngineError, ComputeTimeoutError

logger = logging.getLogger("socialgraph.services.cpp_tcp_client")

# 连接池: 最多保留 4 个连接
_MAX_POOL_SIZE = 4
_pool: list["_TcpConnection"] = []
_pool_lock = asyncio.Lock()


class _TcpConnection:
    """单个 TCP 连接封装。"""

    def __init__(self, host: str, port: int):
        self.host = host
        self.port = port
        self.reader: Optional[asyncio.StreamReader] = None
        self.writer: Optional[asyncio.StreamWriter] = None
        self.in_use = False
        self.last_used = 0.0

    async def connect(self):
        self.reader, self.writer = await asyncio.wait_for(
            asyncio.open_connection(self.host, self.port),
            timeout=5.0,
        )
        self.last_used = time.time()

    async def send_command(self, command: str, *args: str, timeout: float = 60.0) -> dict:
        """发送 JSON 命令, 接收 JSON 响应。"""
        request = json.dumps({
            "command": command,
            "args": list(args),
        }) + "\n"

        self.writer.write(request.encode())
        await self.writer.drain()

        try:
            line = await asyncio.wait_for(
                self.reader.readline(),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            raise ComputeTimeoutError(f"C++ 引擎 TCP 超时 ({timeout}s): {command}")

        if not line:
            raise CppEngineError("C++ 引擎 TCP 连接已关闭")

        try:
            return json.loads(line.decode())
        except json.JSONDecodeError:
            return {"status": "error", "message": f"TCP 响应 JSON 解析失败: {line[:200]}"}

    async def close(self):
        if self.writer:
            self.writer.close()
            try:
                await self.writer.wait_closed()
            except Exception:
                pass

    def is_healthy(self) -> bool:
        return self.reader is not None and not self.reader.at_eof()


async def _get_connection() -> Optional[_TcpConnection]:
    """从连接池获取一个可用连接 (或创建新连接)。"""
    settings = get_settings()
    host = settings.cpp_engine_tcp_host
    port = settings.cpp_engine_tcp_port

    async with _pool_lock:
        # 先找空闲连接
        for conn in _pool:
            if not conn.in_use and conn.is_healthy():
                conn.in_use = True
                return conn

        # 创建新连接
        if len(_pool) < _MAX_POOL_SIZE:
            conn = _TcpConnection(host, port)
            try:
                await conn.connect()
                conn.in_use = True
                _pool.append(conn)
                logger.info("TCP 连接已建立: %s:%d (池大小: %d)", host, port, len(_pool))
                return conn
            except Exception as e:
                logger.warning("TCP 连接失败: %s:%d, %s", host, port, e)
                return None

        # 连接池满, 等一个空闲的
        for conn in _pool:
            if conn.is_healthy():
                conn.in_use = True
                return conn

        return None


async def _release_connection(conn: _TcpConnection):
    """归还连接到连接池。"""
    conn.in_use = False
    conn.last_used = time.time()


async def execute_command_tcp(command: str, *args: str, timeout: float = 60.0) -> dict:
    """通过 TCP 长连接执行 C++ 引擎命令。

    相比 subprocess 模式:
      - 首次连接: ~5ms (TCP handshake)
      - 后续请求: <1ms (连接复用)
      - subprocess 每次: ~50ms (进程启动)

    Args:
        command: C++ 引擎命令 (如 "pagerank", "community", "shortest_path")
        *args:   命令参数
        timeout: 超时秒数

    Returns:
        JSON 解析后的 dict
    """
    conn = await _get_connection()

    if conn is None:
        # TCP 不可用, 回退到 subprocess 模式
        logger.info("TCP 连接不可用, 回退到 subprocess 模式")
        from services.cpp_engine import execute_command as execute_subprocess
        return await execute_subprocess(command, *args, timeout=timeout)

    try:
        result = await conn.send_command(command, *args, timeout=timeout)
        return result
    except Exception as e:
        # 连接可能断开, 标记为不健康, 下次重新连接
        logger.warning("TCP 命令执行失败: %s, 错误: %s", command, e)
        await conn.close()
        async with _pool_lock:
            if conn in _pool:
                _pool.remove(conn)
        # 回退
        from services.cpp_engine import execute_command as execute_subprocess
        return await execute_subprocess(command, *args, timeout=timeout)
    finally:
        await _release_connection(conn)


async def health_check_tcp() -> dict:
    """检查 TCP 连接健康状态。"""
    try:
        result = await execute_command_tcp("run_test", timeout=5.0)
        return {"status": "healthy", "mode": "tcp", "result": result}
    except Exception as e:
        return {"status": "unavailable", "mode": "tcp", "message": str(e)}


async def shutdown_tcp_pool():
    """关闭所有 TCP 连接 (应用关闭时调用)。"""
    async with _pool_lock:
        for conn in _pool:
            await conn.close()
        _pool.clear()
        logger.info("TCP 连接池已关闭")
