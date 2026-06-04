"""
SocialGraph Pro — C++ 计算引擎调用封装

通过 asyncio 子进程调用 C++ 引擎，消除阻塞。
使用 subprocess 模式的启动开销约 50ms，可通过 Redis 缓存吸收重复请求。
"""
import asyncio
import json
import logging
import os

from core.config import get_settings
from core.exceptions import CppEngineError, ComputeTimeoutError

logger = logging.getLogger("socialgraph.services.cpp_engine")


async def execute_command(command: str, *args: str, timeout: float = 60.0) -> dict:
    """执行 C++ 引擎命令。

    Args:
        command: C++ 引擎命令字符串 (如 "pagerank", "community", "shortest_path")
        *args:   命令参数
        timeout: 计算超时时间（秒），默认 60s

    Returns:
        JSON 解析后的 dict: {"status": "success", ...} 或 {"status": "error", ...}
    """
    settings = get_settings()
    cmd = [settings.cpp_engine_path, settings.graph_data_path, command] + list(args)

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)

        if proc.returncode != 0:
            return {
                "status": "error",
                "message": (
                    f"C++ 引擎返回非零退出码 ({proc.returncode}): "
                    f"{stderr.decode('utf-8', errors='replace')}"
                ),
            }

        try:
            return json.loads(stdout.decode("utf-8"))
        except json.JSONDecodeError:
            return {"status": "error", "message": "C++ 引擎返回数据格式异常"}

    except asyncio.TimeoutError:
        raise ComputeTimeoutError(f"C++ 引擎计算超时 ({timeout}s): {command}")
    except FileNotFoundError:
        raise CppEngineError(f"C++ 引擎可执行文件未找到: {settings.cpp_engine_path}")
    except Exception as e:
        raise CppEngineError(f"C++ 引擎执行失败: {e}")
