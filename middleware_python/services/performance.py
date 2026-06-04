"""
SocialGraph Pro — 性能指标收集服务

异步写入性能数据到 MongoDB (operation_logs + performance_metrics)，
不阻塞 API 响应返回。

增强 (v2.0):
  - request_id / correlation_id 分布式追踪
  - 批量写入缓冲 (合并 100ms 窗口)
  - 缓存命中记录到 cache_registry
  - 操作日志包含 session_id / endpoint / http_method

使用方式:
    from services.performance import log_operation, record_metric

    # 在路由 handler 最后调用:
    await log_operation("run_algorithm", user_id, resource="pagerank",
                        duration_ms=245, request_id="req_abc123")

    # 记录延迟指标:
    await record_metric("pagerank.p95_ms", 245.0, "ms", {"algorithm": "pagerank"})
"""
import asyncio
import hashlib
import logging
import time
from collections import deque
from datetime import datetime, timezone
from typing import Any, Deque, Dict, List, Optional

logger = logging.getLogger("socialgraph.services.performance")

# ── 批量写入缓冲 (合并操作日志写入) ──────────────────────────────────────────
_batch_buffer: Deque[Dict] = deque()
_batch_lock = asyncio.Lock()
_batch_flush_task: Optional[asyncio.Task] = None
BATCH_MAX_SIZE = 200       # 缓冲区最大容量 (超过后立即刷新)
BATCH_FLUSH_INTERVAL = 0.1  # 刷新间隔 (秒)


async def _flush_batch():
    """定时批量刷新日志缓冲区到 MongoDB。"""
    global _batch_flush_task
    while True:
        try:
            await asyncio.sleep(BATCH_FLUSH_INTERVAL)
            async with _batch_lock:
                if not _batch_buffer:
                    continue
                batch = list(_batch_buffer)
                _batch_buffer.clear()

            if batch:
                from db.mongodb import bulk_write_logs
                inserted = await bulk_write_logs(batch)
                if inserted < len(batch):
                    logger.debug("批量刷新: %d/%d 条写入成功", inserted, len(batch))
        except asyncio.CancelledError:
            # 关闭前最后刷新
            async with _batch_lock:
                if _batch_buffer:
                    from db.mongodb import bulk_write_logs
                    await bulk_write_logs(list(_batch_buffer))
                    _batch_buffer.clear()
            break
        except Exception:
            pass


def _ensure_batch_flush():
    """确保批量刷新后台任务已启动。"""
    global _batch_flush_task
    if _batch_flush_task is None or _batch_flush_task.done():
        _batch_flush_task = asyncio.ensure_future(_flush_batch())


# ═══════════════════════════════════════════════════════════════════════════════
# 公开 API
# ═══════════════════════════════════════════════════════════════════════════════

def log_operation(
    action: str,
    user_id: str,
    resource: str = "",
    details: Optional[dict] = None,
    duration_ms: int = 0,
    status: str = "success",
    error_code: str = "",
    error_message: str = "",
    ip_address: str = "",
    user_agent: str = "",
    request_id: str = "",
    correlation_id: str = "",
    session_id: str = "",
    endpoint: str = "",
    http_method: str = "",
    engine_version: str = "",
    cache_hit: bool = False,
):
    """异步记录用户操作到 MongoDB operation_logs。

    优先使用批量写入缓冲区 (合并 100ms 窗口), MongoDB 不可用时退化为 fire-and-forget。

    Args:
        action:         操作类型 (run_algorithm, export_data, login, ...)
        user_id:        用户 ID (anonymous 表示未登录)
        resource:       目标资源 (算法名/端点路径)
        details:        操作详情 (algorithm, parameters, export_format, ...)
        duration_ms:    执行耗时 (ms)
        status:         执行结果 (success/failure/rate_limited/unauthorized/timeout)
        error_code:     错误码 (如 CPP_ENGINE_TIMEOUT)
        error_message:  错误消息
        ip_address:     请求来源 IP
        user_agent:     User-Agent 头
        request_id:     HTTP X-Request-ID (分布式追踪)
        correlation_id: 跨服务调用链 ID
        session_id:     用户会话 ID
        endpoint:       API 端点路径
        http_method:    HTTP 方法 (GET/POST/...)
        engine_version: C++ 引擎版本
        cache_hit:      是否命中 Redis 缓存
    """
    now = datetime.now(timezone.utc)

    doc = {
        "user_id": user_id,
        "request_id": request_id,
        "correlation_id": correlation_id,
        "session_id": session_id,
        "action": action,
        "resource": resource,
        "endpoint": endpoint,
        "http_method": http_method,
        "details": details or {},
        "duration_ms": duration_ms,
        "status": status,
        "error_code": error_code,
        "error_message": error_message,
        "ip_address": ip_address,
        "user_agent": (user_agent or "")[:256],  # 截断防止过大
        "created_at": now,
    }

    # 缓存命中标记附属到 details 中
    if cache_hit:
        doc["details"]["cache_hit"] = True

    # 错误堆栈 hash (用于聚合同类错误)
    if error_code:
        doc["stack_trace_hash"] = hashlib.sha256(
            (error_code + (error_message or "")).encode()
        ).hexdigest()[:8]

    # 引擎版本
    if engine_version:
        v = engine_version
        doc["metadata"] = {
            "app_version": _get_app_version(),
            "environment": _get_environment(),
            "engine_version": v,
        }

    # 批量缓冲模式
    try:
        _ensure_batch_flush()
        asyncio.get_event_loop()
        _batch_buffer.append(doc)
        if len(_batch_buffer) >= BATCH_MAX_SIZE:
            # 超出阈值不立即同步刷新 — fires another flush shortly
            pass
    except RuntimeError:
        # 无事件循环时退化为 fire-and-forget
        asyncio.ensure_future(_write_operation_legacy(doc))


async def _write_operation_legacy(doc: dict):
    """传统单条写入（降级路径）。"""
    try:
        from db.mongodb import get_mongo_db
        db = await get_mongo_db()
        if db is None:
            return
        await db.operation_logs.insert_one(doc)
    except Exception as e:
        logger.debug("操作日志写入失败 (非关键): %s", e)


def record_metric(
    metric: str,
    value: float,
    unit: str = "ms",
    tags: Optional[dict] = None,
):
    """异步记录性能指标到 MongoDB performance_metrics。

    使用 fire-and-forget 模式。

    Args:
        metric: 指标名 (pagerank.p50_ms, api.latency.avg_ms, cache.hit_rate)
        value:  指标数值
        unit:   单位 (ms/percent/bytes/count/ops_per_sec/MB)
        tags:   标签维度 (algorithm/engine/host/graph_size/data_file)
    """
    asyncio.ensure_future(_write_metric(metric, value, unit, tags))


async def _write_metric(metric: str, value: float, unit: str, tags: Optional[dict]):
    """后台任务: 写入性能指标到 MongoDB。"""
    try:
        from db.mongodb import get_mongo_db
        db = await get_mongo_db()
        if db is None:
            return

        doc = {
            "metric": metric,
            "value": value,
            "unit": unit,
            "tags": tags or {},
            "timestamp": datetime.now(timezone.utc),
        }
        await db.performance_metrics.insert_one(doc)

    except Exception as e:
        logger.debug("性能指标写入失败 (非关键): %s", e)


# ═══════════════════════════════════════════════════════════════════════════════
# 缓存集成
# ═══════════════════════════════════════════════════════════════════════════════

def record_cache_hit(
    cache_key: str,
    algorithm: str,
    user_id: str = "",
):
    """记录 Redis 缓存命中。

    同时更新:
      1. operation_logs (用户操作审计)
      2. cache_registry (access_count +1, 缓存热度统计)

    Args:
        cache_key: Redis 缓存键
        algorithm: 算法类型
        user_id:   用户 ID
    """
    # 记录操作日志
    log_operation(
        action="run_algorithm",
        user_id=user_id or "anonymous",
        resource=algorithm,
        duration_ms=0,  # 缓存命中无执行时间
        cache_hit=True,
    )

    # 更新 cache_registry
    asyncio.ensure_future(_update_cache_access(cache_key))


async def _update_cache_access(cache_key: str):
    """更新 cache_registry 中的访问计数。"""
    try:
        from db.mongodb import record_cache_access
        await record_cache_access(cache_key)
    except Exception:
        pass


def record_cache_miss(
    algorithm: str,
    cache_key: str,
    user_id: str = "",
    parameters_hash: str = "",
    graph_data_hash: str = "",
    result_size_bytes: int = 0,
    ttl_seconds: int = 86400,
):
    """记录缓存未命中，并在 cache_registry 中注册新缓存条目。

    Args:
        algorithm:         算法类型
        cache_key:         Redis 缓存键
        user_id:           用户 ID
        parameters_hash:   参数 hash
        graph_data_hash:   图数据 hash
        result_size_bytes: 结果大小
        ttl_seconds:       Redis TTL
    """
    # 注册缓存条目
    asyncio.ensure_future(_register_cache(
        cache_key, algorithm, ttl_seconds,
        parameters_hash, graph_data_hash, result_size_bytes,
    ))


async def _register_cache(
    cache_key: str,
    algorithm: str,
    ttl_seconds: int,
    parameters_hash: str,
    graph_data_hash: str,
    result_size_bytes: int,
):
    """后台任务: 向 cache_registry 注册缓存条目。"""
    try:
        from db.mongodb import register_cache_entry
        await register_cache_entry(
            cache_key=cache_key,
            algorithm=algorithm,
            ttl_seconds=ttl_seconds,
            parameters_hash=parameters_hash,
            graph_data_hash=graph_data_hash,
            result_size_bytes=result_size_bytes,
        )
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════════════════
# 助手函数
# ═══════════════════════════════════════════════════════════════════════════════

def _get_app_version() -> str:
    try:
        from core.config import get_settings
        return get_settings().app_version
    except Exception:
        return "unknown"


def _get_environment() -> str:
    try:
        from core.config import get_settings
        return get_settings().environment
    except Exception:
        return "unknown"


# ═══════════════════════════════════════════════════════════════════════════════
# 操作计时器 (Context Manager)
# ═══════════════════════════════════════════════════════════════════════════════

class OperationTimer:
    """异步上下文管理器: 计时操作并自动记录日志。

    使用方式:
        async with OperationTimer("run_algorithm", user_id,
                                  resource="pagerank",
                                  request_id=request_id) as timer:
            result = await some_computation()
            timer.set_status("success")
    """

    def __init__(self, action: str, user_id: str, resource: str = "",
                 request_id: str = "", correlation_id: str = "",
                 session_id: str = "", endpoint: str = "",
                 http_method: str = "",
                 ip_address: str = "", user_agent: str = ""):
        self.action = action
        self.user_id = user_id
        self.resource = resource
        self.request_id = request_id
        self.correlation_id = correlation_id
        self.session_id = session_id
        self.endpoint = endpoint
        self.http_method = http_method
        self.ip_address = ip_address
        self.user_agent = user_agent
        self.status = "success"
        self.error_code = ""
        self.error_message = ""
        self.start_time: float = 0
        self.elapsed_ms: int = 0

    async def __aenter__(self):
        self.start_time = time.time()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        self.elapsed_ms = int((time.time() - self.start_time) * 1000)

        if exc_type is not None:
            self.status = "failure"
            self.error_code = exc_type.__name__ if hasattr(exc_type, "__name__") else str(exc_type)
            self.error_message = str(exc_val) if exc_val else ""

        log_operation(
            action=self.action,
            user_id=self.user_id,
            resource=self.resource,
            duration_ms=self.elapsed_ms,
            status=self.status,
            error_code=self.error_code,
            error_message=self.error_message,
            ip_address=self.ip_address,
            user_agent=self.user_agent,
            request_id=self.request_id,
            correlation_id=self.correlation_id,
            session_id=self.session_id,
            endpoint=self.endpoint or f"/api/v1/graph/{self.resource}",
            http_method=self.http_method or "POST",
        )

    def set_status(self, status: str, error_code: str = "", error_message: str = ""):
        self.status = status
        self.error_code = error_code
        self.error_message = error_message
