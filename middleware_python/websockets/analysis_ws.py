"""
SocialGraph Pro — WebSocket 实时分析端点

端点:
  WS /api/v1/ws/analysis — 实时运行 C++ 引擎算法

协议:
  客户端 → 服务器: {"command": "pagerank", "args": []}
  服务器 → 客户端:
    {"status": "running", "message": "正在执行 pagerank..."}
    {"status": "completed", "data": {...}}
    {"status": "error", "message": "..."}

特性:
  - 支持认证 (可选: 在连接 URL 中传递 ?token=xxx)
  - 超时保护 (60s)
  - 优雅关闭
"""
import logging

from fastapi import WebSocket, WebSocketDisconnect, Query

from services.cpp_engine import execute_command

logger = logging.getLogger("socialgraph.websockets.analysis")


async def ws_analysis_handler(websocket: WebSocket, token: str = Query(None)):
    """WebSocket 实时分析处理器。

    Args:
        token: 可选的 JWT access token（用于认证）
    """
    # 强制 token 认证
    if not token:
        await websocket.close(code=4001, reason="WebSocket 需要认证 — 请在 URL 中提供 ?token=JWT_TOKEN")
        return

    try:
        from core.security import decode_token
        payload = decode_token(token)
        user_id = payload.get("sub", "unknown")
        logger.info("WebSocket 连接已认证: user=%s", user_id)
    except Exception as e:
        await websocket.close(code=4001, reason=f"认证失败: {str(e)}")
        return

    await websocket.accept()
    logger.info("WebSocket 客户端已连接: %s", user_id)

    try:
        while True:
            # 接收消息
            msg = await websocket.receive_json()
            command = msg.get("command", "")
            args = msg.get("args", [])

            if not command:
                await websocket.send_json({
                    "status": "error",
                    "message": "缺少 command 字段",
                })
                continue

            logger.info("WebSocket 请求: user=%s, command=%s, args=%s", user_id, command, args)

            # 发送运行中状态
            await websocket.send_json({
                "status": "running",
                "message": f"正在执行 {command}...",
                "command": command,
            })

            # 执行命令（带超时保护）
            try:
                data = await execute_command(command, *args, timeout=60.0)

                if data.get("status") == "success":
                    await websocket.send_json({
                        "status": "completed",
                        "data": data,
                        "command": command,
                    })
                else:
                    await websocket.send_json({
                        "status": "error",
                        "message": data.get("message", "未知错误"),
                        "command": command,
                        "detail": data,
                    })
            except Exception as e:
                logger.error("WebSocket 命令执行失败: command=%s, error=%s", command, e)
                await websocket.send_json({
                    "status": "error",
                    "message": str(e),
                    "command": command,
                })

    except WebSocketDisconnect:
        logger.info("WebSocket 客户端断开: %s", user_id)
    except Exception as e:
        logger.error("WebSocket 异常: %s", e)
        try:
            await websocket.send_json({
                "status": "error",
                "message": f"服务器内部错误: {str(e)}",
            })
        except Exception:
            pass
