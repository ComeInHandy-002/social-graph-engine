"""
SocialGraph Pro — 结构化请求日志中间件

功能:
  1. 自动记录每个 HTTP 请求的方法、路径、状态码、耗时
  2. 日志以 JSON 格式输出，便于日志聚合系统（ELK/Loki）解析
  3. 传播 request_id 到所有日志条目
  4. 慢请求告警（超过阈值时记录 WARNING）

日志格式:
  {
    "timestamp": "2024-01-15T10:30:00.123Z",
    "level": "INFO",
    "request_id": "req_abc123",
    "method": "GET",
    "path": "/api/v1/graph/pagerank",
    "status_code": 200,
    "duration_ms": 245.3,
    "client_ip": "192.168.1.1",
    "user_agent": "Mozilla/5.0 ...",
    "event": "request.completed"
  }
"""
import json
import logging
import time
from datetime import datetime, timezone

from starlette.middleware.base import BaseHTTPMiddleware
from core.config import get_settings

logger = logging.getLogger("socialgraph.middleware.request")


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """ASGI 中间件: 记录每个 HTTP 请求的结构化日志。"""

    async def dispatch(self, request, call_next):
        start_time = time.time()
        request_id = getattr(request.state, "request_id", "unknown")

        # 记录请求开始
        _log_request_start(request_id, request)

        try:
            response = await call_next(request)
        except Exception:
            # 异常由 ErrorHandlerMiddleware 处理，这里仅记录耗时
            elapsed_ms = (time.time() - start_time) * 1000
            _log_request_failed(request_id, request, elapsed_ms)
            raise

        elapsed_ms = (time.time() - start_time) * 1000

        # 慢请求告警
        settings = get_settings()
        if elapsed_ms > settings.slow_query_threshold_ms:
            logger.warning(
                _format_log_entry(
                    request_id, request, response.status_code, elapsed_ms,
                    event="request.slow",
                )
            )
        else:
            logger.info(
                _format_log_entry(
                    request_id, request, response.status_code, elapsed_ms,
                    event="request.completed",
                )
            )

        return response


def _log_request_start(request_id: str, request):
    """记录请求开始（DEBUG 级别，生产环境通常关闭）。"""
    logger.debug(
        json.dumps({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
            "query_string": str(request.url.query),
            "client_ip": request.client.host if request.client else "unknown",
            "user_agent": request.headers.get("user-agent", ""),
            "event": "request.started",
        }, ensure_ascii=False)
    )


def _format_log_entry(request_id, request, status_code: int, duration_ms: float, event: str) -> str:
    """构造结构化日志条目。"""
    return json.dumps({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "request_id": request_id,
        "method": request.method,
        "path": request.url.path,
        "status_code": status_code,
        "duration_ms": round(duration_ms, 2),
        "client_ip": request.client.host if request.client else "unknown",
        "user_agent": request.headers.get("user-agent", ""),
        "event": event,
    }, ensure_ascii=False)


def _log_request_failed(request_id: str, request, elapsed_ms: float):
    """记录失败的请求（异常被抛出）。"""
    logger.error(
        json.dumps({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
            "duration_ms": round(elapsed_ms, 2),
            "client_ip": request.client.host if request.client else "unknown",
            "event": "request.failed",
        }, ensure_ascii=False)
    )
