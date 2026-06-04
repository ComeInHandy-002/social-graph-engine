"""
SocialGraph Pro — Redis Pub/Sub 实时消息服务
版本: 1.0.0

提供异步发布/订阅抽象层，支持:
  - 算法进度推送 (C++ 引擎 → WebSocket 客户端)
  - 缓存失效广播 (Admin API → 所有 FastAPI Worker)
  - 系统事件通知 (维护模式、健康状态)
  - 实时协作 (多用户协同操作)

设计原则:
  - 每个订阅者在后台独立运行 (asyncio.Task)
  - 连接断开自动重连 (指数退避)
  - 优雅关闭 (cancel + cleanup)
  - Fire-and-forget 发布（不阻塞调用方）

频道命名:
  sgp:pubsub:{category}:{qualifier}

标准频道:
  sgp:pubsub:algo-progress:{job_id}     — 算法进度
  sgp:pubsub:cache-invalid              — 缓存失效广播
  sgp:pubsub:system-events              — 系统事件
  sgp:pubsub:collab:{room_id}           — 协同操作
"""
import asyncio
import json
import logging
import time
from typing import Any, Callable, Coroutine, Optional

logger = logging.getLogger("socialgraph.services.pubsub")


# ═══════════════════════════════════════════════════════════════════
# 频道常量
# ═══════════════════════════════════════════════════════════════════

class Channels:
    """标准 Pub/Sub 频道名称常量。

    使用方式:
        await pubsub.publish(Channels.algo_progress("job_abc"), {...})
        await pubsub.publish(Channels.CACHE_INVALID, {...})
    """

    # 全局广播频道
    CACHE_INVALID = "sgp:pubsub:cache-invalid"
    SYSTEM_EVENTS = "sgp:pubsub:system-events"

    # 动态频道模板
    @staticmethod
    def algo_progress(job_id: str) -> str:
        """算法进度频道: 每个计算任务独立推送。"""
        return f"sgp:pubsub:algo-progress:{job_id}"

    @staticmethod
    def collab_room(room_id: str) -> str:
        """协同操作频道: 每个协作房间独立频道。"""
        return f"sgp:pubsub:collab:{room_id}"


# ═══════════════════════════════════════════════════════════════════
# 消息处理器类型
# ═══════════════════════════════════════════════════════════════════

MessageHandler = Callable[[str, dict], Coroutine[Any, Any, None]]
"""消息处理器签名: async def handler(channel: str, data: dict) -> None"""


# ═══════════════════════════════════════════════════════════════════
# Redis Pub/Sub 客户端
# ═══════════════════════════════════════════════════════════════════

class RedisPubSub:
    """异步 Redis Pub/Sub 客户端。

    每个 FastAPI Worker 应创建一个全局单例。
    支持多频道订阅，每个频道独立后台任务。
    连接断开时自动重连。

    使用方式:
        pubsub = RedisPubSub()
        await pubsub.start()

        # 订阅
        await pubsub.subscribe("sgp:pubsub:cache-invalid", on_cache_invalid)

        # 发布
        await pubsub.publish("sgp:pubsub:cache-invalid", {"domain": "graph"})

        # 关闭
        await pubsub.stop()
    """

    def __init__(self):
        self._started = False
        self._running = False
        self._lock = asyncio.Lock()

        # {channel: {handler, task}}
        self._subscriptions: dict[str, dict] = {}

    # ── 生命周期 ──────────────────────────────────────────────────

    async def start(self):
        """启动 Pub/Sub 客户端（建立 Redis 连接并启动所有订阅任务）。

        幂等操作，重复调用无副作用。
        """
        async with self._lock:
            if self._started:
                return
            self._running = True
            self._started = True
            logger.info("RedisPubSub 客户端已启动")

    async def stop(self):
        """停止 Pub/Sub 客户端（取消所有订阅任务并清理资源）。

        幂等操作。
        """
        async with self._lock:
            if not self._started:
                return
            self._running = False
            self._started = False

            # 取消所有后台任务
            for channel, sub in list(self._subscriptions.items()):
                task = sub.get("task")
                if task and not task.done():
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass
                logger.debug("取消订阅: %s", channel)

            self._subscriptions.clear()
            logger.info("RedisPubSub 客户端已停止")

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.stop()

    # ── 发布 ──────────────────────────────────────────────────────

    async def publish(self, channel: str, message: dict) -> bool:
        """向指定频道发布消息（Fire-and-forget 模式）。

        Args:
            channel: 频道名称
            message: 消息字典（自动序列化为 JSON）

        Returns:
            是否发布成功（Redis 不可用时返回 False，不阻塞）

        使用方式:
            await pubsub.publish(Channels.CACHE_INVALID, {
                "domain": "graph",
                "keys": ["sgp:graph:pagerank:v3"],
                "reason": "data_updated",
                "timestamp": "2025-01-01T00:00:00Z",
            })
        """
        from db.redis import get_redis_async

        r = await get_redis_async()
        if r is None:
            logger.debug("Redis 不可用，跳过发布: channel=%s", channel)
            return False

        try:
            payload = json.dumps(message, default=str)
            count = await r.publish(channel, payload)
            logger.debug("已发布到 %s: clients=%d, msg_type=%s", channel, count, message.get("event", "unknown"))
            return True
        except Exception as e:
            logger.warning("发布消息失败 (channel=%s): %s", channel, e)
            return False

    # ── 订阅 ──────────────────────────────────────────────────────

    async def subscribe(self, channel: str, handler: MessageHandler) -> bool:
        """订阅指定频道。

        启动一个后台任务持续监听消息，连接断开时自动重连。

        Args:
            channel: 频道名称 (支持 Redis 通配符，如 "sgp:pubsub:*")
            handler: 消息处理器 async def(channel, data)

        Returns:
            是否订阅成功

        使用方式:
            async def on_cache_invalid(channel: str, data: dict):
                if data.get("domain") == "graph":
                    await invalidate_all_graph_cache()

            await pubsub.subscribe(Channels.CACHE_INVALID, on_cache_invalid)
        """
        async with self._lock:
            if channel in self._subscriptions:
                logger.debug("频道已订阅: %s", channel)
                return True

            if not self._running:
                logger.warning("PubSub 未启动，请先调用 start()")
                return False

            task = asyncio.create_task(
                self._listen_loop(channel, handler),
                name=f"pubsub-{channel}",
            )
            self._subscriptions[channel] = {"handler": handler, "task": task}
            logger.info("已订阅频道: %s", channel)
            return True

    async def unsubscribe(self, channel: str) -> bool:
        """取消订阅指定频道。

        Args:
            channel: 频道名称

        Returns:
            是否取消成功
        """
        async with self._lock:
            sub = self._subscriptions.pop(channel, None)
            if sub is None:
                return False

            task = sub.get("task")
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
            logger.info("已取消订阅: %s", channel)
            return True

    # ── 后台监听循环 ──────────────────────────────────────────────

    async def _listen_loop(self, channel: str, handler: MessageHandler):
        """后台监听循环：持续监听频道消息。

        特性:
          - 连接断开自动重连（指数退避 1s → 2s → 4s → ... 最大 60s）
          - 重连后成功立即重置退避计时
          - 监听期间 self._running=False 时退出循环
        """
        from db.redis import get_redis_async

        backoff = 1.0   # 当前重试间隔（秒）
        max_backoff = 60.0

        while self._running:
            pubsub = None
            try:
                r = await get_redis_async()
                if r is None:
                    logger.debug("PubSub 等待 Redis 可用 (channel=%s)...", channel)
                    await asyncio.sleep(backoff)
                    continue

                pubsub = r.pubsub()
                await pubsub.subscribe(channel)
                logger.debug("PubSub 监听循环已启动: channel=%s", channel)
                backoff = 1.0  # 连接成功后重置退避

                while self._running:
                    message = await pubsub.get_message(
                        ignore_subscribe_messages=True,
                        timeout=1.0,
                    )
                    if message is None:
                        continue

                    msg_type = message.get("type", "")
                    if msg_type not in ("message", "pmessage"):
                        continue

                    raw_data = message.get("data", "")
                    actual_channel = message.get("channel", channel)

                    try:
                        data = json.loads(raw_data) if isinstance(raw_data, (str, bytes)) else {}
                    except json.JSONDecodeError:
                        logger.warning("PubSub 消息 JSON 解析失败: channel=%s", actual_channel)
                        data = {"_raw": str(raw_data)}

                    try:
                        await handler(actual_channel, data)
                    except Exception as e:
                        logger.error(
                            "PubSub 消息处理器异常 (channel=%s): %s",
                            actual_channel, e, exc_info=True,
                        )

            except asyncio.CancelledError:
                logger.debug("PubSub 监听循环取消: channel=%s", channel)
                break
            except Exception as e:
                logger.warning(
                    "PubSub 监听异常 (channel=%s, 将在 %.1fs 后重连): %s",
                    channel, backoff, e,
                )
            finally:
                if pubsub:
                    try:
                        await pubsub.unsubscribe(channel)
                        await pubsub.aclose()
                    except Exception:
                        pass

            if not self._running:
                break
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, max_backoff)

        logger.debug("PubSub 监听循环已退出: channel=%s", channel)


# ═══════════════════════════════════════════════════════════════════
# 便利函数 — 发布标准消息
# ═══════════════════════════════════════════════════════════════════

async def publish_cache_invalid(
    domain: str,
    keys: Optional[list[str]] = None,
    reason: str = "manual",
) -> bool:
    """发布缓存失效通知。

    Args:
        domain: 缓存域 (如 "graph", "auth", "all")
        keys:   具体失效的键列表（None 表示该域全部失效）
        reason: 失效原因 (data_updated, manual, version_bump)

    Returns:
        是否发布成功

    使用方式:
        await publish_cache_invalid("graph", reason="data_updated")
    """
    from datetime import datetime, timezone

    pubsub = RedisPubSub()
    return await pubsub.publish(Channels.CACHE_INVALID, {
        "event": "cache_invalid",
        "domain": domain,
        "keys": keys or [],
        "reason": reason,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })


async def publish_algo_progress(
    job_id: str,
    stage: str,
    percent: float = 0,
    algorithm: str = "",
    message: str = "",
) -> bool:
    """发布算法执行进度。

    Args:
        job_id:    计算任务唯一 ID
        stage:     当前阶段 (starting, computing, postprocessing, completed, error)
        percent:   进度百分比 (0-100)
        algorithm: 算法名称
        message:   附带信息

    Returns:
        是否发布成功

    使用方式:
        await publish_algo_progress("job_001", "computing", percent=50, algorithm="pagerank")
    """
    pubsub = RedisPubSub()
    return await pubsub.publish(Channels.algo_progress(job_id), {
        "event": "algo_progress",
        "job_id": job_id,
        "stage": stage,
        "percent": percent,
        "algorithm": algorithm,
        "message": message or f"正在执行 {algorithm} ({percent:.0f}%)",
    })


async def publish_system_event(
    event_type: str,
    enabled: bool = False,
    message: str = "",
    extra: Optional[dict] = None,
) -> bool:
    """发布系统事件通知。

    Args:
        event_type: 事件类型 (maintenance_mode, health_degraded, config_changed)
        enabled:    状态值
        message:    描述信息
        extra:      额外数据

    Returns:
        是否发布成功

    使用方式:
        await publish_system_event("maintenance_mode", enabled=True, message="维护模式已开启")
    """
    from datetime import datetime, timezone

    payload = {
        "event": event_type,
        "enabled": enabled,
        "message": message,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if extra:
        payload.update(extra)

    pubsub = RedisPubSub()
    return await pubsub.publish(Channels.SYSTEM_EVENTS, payload)


async def publish_collab_action(
    room_id: str,
    user_id: str,
    action: str,
    payload: dict,
) -> bool:
    """发布协同操作事件。

    Args:
        room_id: 协作房间 ID
        user_id: 操作用户 ID
        action:  操作类型 (node_selected, node_moved, view_changed, comment_added)
        payload: 操作数据

    Returns:
        是否发布成功

    使用方式:
        await publish_collab_action("room_001", "user_42", "node_selected", {"node_id": "107"})
    """
    pubsub = RedisPubSub()
    return await pubsub.publish(Channels.collab_room(room_id), {
        "event": "collab_action",
        "room_id": room_id,
        "user": user_id,
        "action": action,
        "data": payload,
        "timestamp": int(time.time() * 1000),
    })


# ═══════════════════════════════════════════════════════════════════
# WebSocket 集成辅助 — 算法进度推送
# ═══════════════════════════════════════════════════════════════════

async def forward_algo_progress_to_websocket(
    websocket,  # fastapi.WebSocket
    job_id: str,
    cancel_event: asyncio.Event,
) -> None:
    """将算法进度消息从 Redis Pub/Sub 转发到 WebSocket 客户端。

    使用方式 (在 WebSocket handler 中):
        cancel = asyncio.Event()
        forward_task = asyncio.create_task(
            forward_algo_progress_to_websocket(websocket, job_id, cancel)
        )
        # ... 执行算法 ...
        cancel.set()
        await forward_task

    Args:
        websocket:    FastAPI WebSocket 连接
        job_id:       计算任务唯一 ID
        cancel_event: 取消信号 (算法完成时 set)
    """
    channel = Channels.algo_progress(job_id)
    send_lock = asyncio.Lock()

    async def on_progress(ch: str, data: dict):
        """线程安全: 使用锁确保 send_json 不交错。"""
        async with send_lock:
            try:
                await websocket.send_json({
                    "status": "progress",
                    "stage": data.get("stage", "unknown"),
                    "percent": data.get("percent", 0),
                    "algorithm": data.get("algorithm", ""),
                    "message": data.get("message", ""),
                })
            except Exception as e:
                logger.warning("WebSocket 进度推送失败: %s", e)

    pubsub = RedisPubSub()
    await pubsub.start()

    try:
        await pubsub.subscribe(channel, on_progress)

        # 阻塞直到收到取消信号
        await cancel_event.wait()
    finally:
        await pubsub.unsubscribe(channel)
        await pubsub.stop()


# ═══════════════════════════════════════════════════════════════════
# 系统事件处理器 — 内置监听器
# ═══════════════════════════════════════════════════════════════════

async def start_system_event_listener():
    """启动系统事件后台监听器。

    在应用启动时调用一次，持续运行直到应用关闭。
    处理:
      - maintenance_mode: 自动切换限流策略为严格模式
      - health_degraded:  健康检查报告降级状态

    使用方式 (在 server.py lifespan startup 中):
        system_listener_task = asyncio.create_task(start_system_event_listener())
        # ... 稍后在 shutdown 中取消 ...
    """
    pubsub = RedisPubSub()

    async def handle_system_event(channel: str, data: dict):
        event_type = data.get("event", "")
        logger.info("系统事件: type=%s, data=%s", event_type, data)

        if event_type == "maintenance_mode":
            enabled = data.get("enabled", False)
            if enabled:
                logger.warning("系统进入维护模式，建议启用严格限流")
                # 此处各 Worker 可自行实现策略切换逻辑
            else:
                logger.info("系统退出维护模式，恢复正常服务")

        elif event_type == "health_degraded":
            logger.warning("系统健康状态降级: %s", data.get("message", ""))

        elif event_type == "config_changed":
            logger.info("系统配置变更: %s", data.get("message", ""))

    await pubsub.start()
    await pubsub.subscribe(Channels.SYSTEM_EVENTS, handle_system_event)
    return pubsub  # 调用方负责在 shutdown 时调用 pubsub.stop()
