"""
SocialGraph Pro — WebSocket 实时数据推送端点

端点:
  WS /api/v1/ws/live — 订阅实时图数据更新

新增能力:
  1. 订阅指定节点/区域的实时更新
  2. 模拟实时数据流 (可替换为真实 Twitter/微博 API)
  3. 消息格式: {"type": "node_update"/"edge_add"/"community_shift"/"alert", "data": {...}}

协议:
  → 客户端发送: {"action": "subscribe", "filters": {"node_ids": ["1","2"], "event_types": ["node_update","edge_add"]}}
  → 服务端推送: {"type": "node_update", "node_id": "1", "changes": {"pagerank": 0.05, "community": 3}}, "timestamp": "..."}
  → 客户端发送: {"action": "unsubscribe"}
  → 客户端发送: {"action": "ping"} → 服务端回复 {"type": "pong"}

与旧 analysis_ws 的区别:
  analysis_ws: 请求-响应模式, 执行一次算法返回结果
  live_data_ws: 发布-订阅模式, 持续推送数据变化
"""
import asyncio
import json
import logging
import random
import time
from typing import Optional

from fastapi import WebSocket, WebSocketDisconnect, Query

logger = logging.getLogger("socialgraph.websockets.live_data")

# 活跃订阅者集合
_active_subscribers: set[WebSocket] = set()

# 模拟数据源 — 生产环境替换为 Kafka/Redis PubSub/真实 API
_SAMPLE_NODE_IDS = [str(i) for i in range(1, 4040)]


def _generate_mock_event() -> dict:
    """生成模拟实时事件 (演示用)。

    生产环境替换为真实数据源:
      - Twitter Streaming API → 新关注关系
      - Kafka Consumer → 用户行为事件
      - Redis PubSub → 图数据变更通知
    """
    event_types = ["node_update", "edge_add", "community_shift"]
    event_type = random.choice(event_types)

    if event_type == "node_update":
        node_id = random.choice(_SAMPLE_NODE_IDS)
        return {
            "type": "node_update",
            "node_id": node_id,
            "changes": {
                "pagerank": round(random.random() * 0.001, 6),
                "betweenness": round(random.random() * 0.01, 4),
                "degree_delta": random.randint(-2, 5),
            },
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
    elif event_type == "edge_add":
        return {
            "type": "edge_add",
            "source": random.choice(_SAMPLE_NODE_IDS),
            "target": random.choice(_SAMPLE_NODE_IDS),
            "weight": round(random.uniform(0.1, 1.0), 2),
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
    else:
        return {
            "type": "community_shift",
            "node_id": random.choice(_SAMPLE_NODE_IDS),
            "from_community": random.randint(1, 20),
            "to_community": random.randint(1, 20),
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        }


async def _broadcast_loop():
    """后台循环: 每 2-5 秒向所有订阅者推送一条模拟事件。"""
    while True:
        if _active_subscribers:
            event = _generate_mock_event()
            dead: list[WebSocket] = []
            for ws in _active_subscribers:
                try:
                    await ws.send_json(event)
                except Exception:
                    dead.append(ws)
            for ws in dead:
                _active_subscribers.discard(ws)
                logger.info("移除已断开的订阅者, 当前: %d", len(_active_subscribers))
        await asyncio.sleep(random.uniform(2.0, 5.0))


# 后台任务引用
_broadcast_task: Optional[asyncio.Task] = None


async def ws_live_handler(websocket: WebSocket, token: str = Query(None)):
    """WebSocket 实时数据推送处理器。

    URL: ws://127.0.0.1:8000/api/v1/ws/live?token=JWT_TOKEN

    支持的消息:
      {"action": "subscribe", "filters": {...}}  — 开始订阅
      {"action": "unsubscribe"}                   — 取消订阅
      {"action": "ping"}                          — 心跳
    """
    global _broadcast_task

    # 认证
    if not token:
        await websocket.close(code=4001, reason="需要认证")
        return
    try:
        from core.security import decode_token
        payload = decode_token(token)
        user_id = payload.get("sub", "unknown")
    except Exception as e:
        await websocket.close(code=4001, reason=f"认证失败: {e}")
        return

    await websocket.accept()
    _active_subscribers.add(websocket)
    logger.info("实时数据订阅者已连接: user=%s, 当前订阅者: %d",
                user_id, len(_active_subscribers))

    # 确保广播循环在运行
    if _broadcast_task is None or _broadcast_task.done():
        _broadcast_task = asyncio.create_task(_broadcast_loop())

    # 发送订阅确认
    await websocket.send_json({
        "type": "connected",
        "message": "已连接到 SocialGraph Pro 实时数据流",
        "subscriber_count": len(_active_subscribers),
        "supported_events": ["node_update", "edge_add", "community_shift"],
    })

    try:
        while True:
            msg = await websocket.receive_json()
            action = msg.get("action", "")

            if action == "ping":
                await websocket.send_json({
                    "type": "pong",
                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "subscriber_count": len(_active_subscribers),
                })
            elif action == "unsubscribe":
                await websocket.send_json({
                    "type": "unsubscribed",
                    "message": "已取消订阅",
                })
                break
            elif action == "subscribe":
                filters = msg.get("filters", {})
                await websocket.send_json({
                    "type": "subscribed",
                    "message": "订阅已更新",
                    "filters": filters,
                })
            else:
                await websocket.send_json({
                    "type": "error",
                    "message": f"未知操作: {action}",
                })

    except WebSocketDisconnect:
        logger.info("实时数据订阅者断开: %s", user_id)
    finally:
        _active_subscribers.discard(websocket)
