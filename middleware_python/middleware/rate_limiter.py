"""
SocialGraph Pro — 混合限流中间件

算法: 滑动窗口 + 令牌桶 混合策略

  - 滑动窗口: 追踪过去 N 秒内的请求次数，超过阈值即拒绝
    适合 API 级别的简单限流 (如 "每用户每分钟 60 次")

  - 令牌桶: 以固定速率补充令牌，突发流量可消耗桶内令牌
    适合更精细的流量整形

  当前实现使用滑动窗口（Redis sorted set），未来可扩展令牌桶。

Redis 数据结构:
  键:  rate_limit:{client_type}:{client_id}:{window}
  值:  Sorted Set, score = 请求时间戳 (毫秒)
  操作: ZREMRANGEBYSCORE 清理过期记录 → ZADD 添加新记录 → ZCARD 计数

限流器仅在 Redis 可用时生效；Redis 不可用时放行所有请求。
"""
import logging
import time
from typing import Optional

from starlette.middleware.base import BaseHTTPMiddleware
from fastapi import Request

from core.config import get_settings
from core.exceptions import RateLimitError

logger = logging.getLogger("socialgraph.middleware.ratelimit")


class RateLimitMiddleware(BaseHTTPMiddleware):
    """基于 Redis 滑动窗口的限流中间件。

    请求分类:
      - anonymous:    未认证请求 (从 X-Request-ID 或 IP 标识)
      - authenticated: 已认证请求 (从 JWT user_id 标识)
      - api_key:       API Key 请求 (从 API Key user_id 标识)

    限流规则从 system_config 表读取，未配置时使用默认值。
    """

    def __init__(self, app, exempt_paths: Optional[list[str]] = None):
        super().__init__(app)
        self.exempt_paths = exempt_paths or [
            "/api/v1/health",
            "/api/v1/health/live",
            "/api/v1/health/ready",
        ]

    async def dispatch(self, request: Request, call_next):
        # 豁免路径
        if request.url.path in self.exempt_paths:
            return await call_next(request)

        # 识别客户端
        client_type, client_id = await _identify_client(request)

        # 检查限流
        settings = get_settings()
        max_requests = {
            "anonymous": settings.rate_limit_anonymous_per_minute,
            "authenticated": settings.rate_limit_authenticated_per_minute,
            "api_key": settings.rate_limit_api_key_per_minute,
        }.get(client_type, 10)

        allowed, current, reset_seconds = await _check_rate_limit(
            client_type, client_id, max_requests, window=60
        )

        if not allowed:
            logger.warning(
                "限流触发: client=%s:%s, limit=%d, current=%d",
                client_type, client_id, max_requests, current,
            )
            raise RateLimitError(
                f"请求过于频繁，每 60 秒最多 {max_requests} 次请求",
                detail={
                    "limit": max_requests,
                    "current": current,
                    "reset_seconds": reset_seconds,
                },
            )

        response = await call_next(request)

        # 在响应头中返回限流信息
        response.headers["X-RateLimit-Limit"] = str(max_requests)
        response.headers["X-RateLimit-Remaining"] = str(max_requests - current - 1)
        response.headers["X-RateLimit-Reset"] = str(reset_seconds)

        return response


async def _identify_client(request: Request) -> tuple[str, str]:
    """识别请求的客户端类型和 ID。

    Returns:
        (client_type, client_id)
        client_type: "anonymous" | "authenticated" | "api_key"
        client_id:   IP 地址 / user_id / api_key_hash
    """
    # 尝试从 Authorization header 中提取 JWT 用户信息
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token_str = auth_header[7:]
        from core.security import decode_token_no_verify
        payload = decode_token_no_verify(token_str)
        if payload and payload.get("sub"):
            return ("authenticated", payload["sub"])

    # 尝试 X-API-Key
    api_key = request.headers.get("X-API-Key")
    if api_key:
        import hashlib
        key_hash = hashlib.sha256(api_key.encode()).hexdigest()[:16]
        return ("api_key", key_hash)

    # 匿名: 使用 IP 或 Request-ID
    client_id = request.headers.get("X-Request-ID") or (
        request.client.host if request.client else "unknown"
    )
    return ("anonymous", client_id)


async def _check_rate_limit(
    client_type: str,
    client_id: str,
    max_requests: int,
    window: int = 60,
) -> tuple[bool, int, int]:
    """检查滑动窗口内的请求次数。

    Args:
        client_type:   客户端类型
        client_id:     客户端标识
        max_requests:  窗口内允许的最大请求数
        window:        窗口大小（秒）

    Returns:
        (allowed, current_count, reset_seconds)
    """
    from db.redis import get_redis_async

    r = await get_redis_async()
    if r is None:
        return (True, 0, 0)  # Redis 不可用，放行

    key = f"rate_limit:{client_type}:{client_id}:{window}s"
    now_ms = int(time.time() * 1000)
    window_start_ms = now_ms - (window * 1000)

    try:
        # 使用 pipeline 确保原子性
        pipe = r.pipeline()
        # 1. 清理过期记录
        pipe.zremrangebyscore(key, 0, window_start_ms)
        # 2. 添加当前请求
        pipe.zadd(key, {str(now_ms): now_ms})
        # 3. 统计窗口内请求数
        pipe.zcard(key)
        # 4. 设置 key 过期时间
        pipe.expire(key, window + 10)
        _, _, count, _ = await pipe.execute()

        current = int(count)
        reset_seconds = window  # 简化：从窗口开始算

        return (current <= max_requests, current, reset_seconds)

    except Exception as e:
        logger.error("限流检查异常: %s", e)
        return (True, 0, 0)  # Redis 异常时放行（降级策略）
