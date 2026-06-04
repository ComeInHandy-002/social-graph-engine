"""
SocialGraph Pro — FastAPI 依赖注入系统

提供:
  认证依赖:
    - get_token: 从 Authorization Header 提取 Bearer token
    - get_current_user: JWT + API Key 双认证
    - get_optional_user: 可选认证（匿名 + 已认证均放行）
    - get_current_admin: 要求 admin 角色
    - get_current_analyst_or_admin: 要求 analyst 或以上角色
    - get_api_key_user: 从 X-API-Key Header 提取用户

  数据库依赖:
    - get_db_redis: 获取 Redis 异步客户端
    - get_db_mysql: 获取 MySQL 连接池
    - get_db_mongo: 获取 MongoDB 数据库
    - get_db_neo4j: 获取 Neo4j 驱动

  请求元数据:
    - get_client_ip: 提取客户端真实 IP
    - get_cursor_params: 解析游标分页参数

设计原则:
  - 每个依赖可独立单元测试
  - Depends() 链式组合实现可组合认证
  - 数据库依赖遵循 Lazy-Connect（优雅降级）
  - 统一 401/403 错误响应格式
"""
import logging
from typing import Optional

from fastapi import Depends, Header, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from core.security import decode_token, is_token_blacklisted
from core.exceptions import UnauthorizedError, ForbiddenError

logger = logging.getLogger("socialgraph.dependencies")

# FastAPI 安全方案
bearer_scheme = HTTPBearer(auto_error=False)


# ═══════════════════════════════════════════════════════════════════
# Token 提取
# ═══════════════════════════════════════════════════════════════════

async def get_token(
    authorization: str = Header(..., description="Bearer <access_token>"),
) -> str:
    """从 Authorization Header 提取 Bearer token。

    使用方式:
        @router.get("/me")
        async def me(token: str = Depends(get_token)):
            ...

    Raises:
        UnauthorizedError: Header 缺失或格式不正确
    """
    if not authorization.startswith("Bearer "):
        raise UnauthorizedError(
            "认证格式错误，请使用: Authorization: Bearer <token>"
        )
    token = authorization[7:]  # 去掉 "Bearer " 前缀
    if not token.strip():
        raise UnauthorizedError("Token 不能为空")
    return token


# ═══════════════════════════════════════════════════════════════════
# 用户认证
# ═══════════════════════════════════════════════════════════════════

async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
    request: Request = None,
) -> dict:
    """从 JWT Bearer token 或 X-API-Key 中提取当前用户信息。

    支持两种认证方式（任选其一）:
      1. Authorization: Bearer <access_token>
      2. X-API-Key: <api_key_raw>

    返回:
        {"user_id": "uuid", "role": "admin|analyst|viewer", "auth_method": "jwt|api_key"}

    Raises:
        UnauthorizedError: 未认证或认证失败 (401)
    """
    # 方式 0: 开发模式 — 自动注入 demo 用户
    from core.config import get_settings
    if get_settings().environment == "development":
        return {"user_id": "demo-user", "role": "admin", "auth_method": "dev_mode"}

    # 方式 1: JWT Bearer Token
    if credentials and credentials.credentials:
        return await _authenticate_jwt(credentials.credentials)

    # 方式 2: API Key
    if x_api_key:
        return await _authenticate_api_key(x_api_key)

    raise UnauthorizedError("缺少认证凭据，请提供 Bearer token 或 X-API-Key")


async def get_optional_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
) -> Optional[dict]:
    """可选认证: 已认证返回用户信息，未认证返回 None。

    适用于同时支持匿名和已认证用户的端点（如公开 API 统计）。
    匿名用户的限流更严格（10/min），已认证用户更宽松（60/min）。

    使用方式:
        @router.get("/stats")
        async def stats(user: Optional[dict] = Depends(get_optional_user)):
            if user:
                log_operation("view_stats", user["user_id"], "stats")
            ...
    """
    try:
        return await get_current_user(
            credentials=credentials,
            x_api_key=x_api_key,
            request=None,
        )
    except UnauthorizedError:
        return None


async def get_current_admin(
    current_user: dict = Depends(get_current_user),
) -> dict:
    """要求 admin 角色 (403 如果角色不符)。

    使用方式:
        @router.delete("/users/{id}")
        async def delete_user(id: str, admin: dict = Depends(get_current_admin)):
            ...
    """
    if current_user["role"] != "admin":
        raise ForbiddenError(
            "此操作需要管理员权限",
            detail={"required_role": "admin", "current_role": current_user["role"]},
        )
    return current_user


async def get_current_analyst_or_admin(
    current_user: dict = Depends(get_current_user),
) -> dict:
    """要求 analyst 或 admin 角色 (403 如果角色不符)。

    使用方式:
        @router.get("/pagerank")
        async def pagerank(user: dict = Depends(get_current_analyst_or_admin)):
            ...
    """
    if current_user["role"] not in ("admin", "analyst"):
        raise ForbiddenError(
            "此操作需要分析师或管理员权限",
            detail={"required_role": "analyst|admin", "current_role": current_user["role"]},
        )
    return current_user


async def get_api_key_user(
    x_api_key: str = Header(..., alias="X-API-Key"),
) -> dict:
    """从 X-API-Key Header 提取用户 (仅 API Key 方式)。

    与 get_current_user 不同，如果 Header 不存在或无效，直接 401。
    适用于仅接受 API Key 认证的端点。

    使用方式:
        @router.get("/api/v1/graph/snapshot")
        async def snapshot(user: dict = Depends(get_api_key_user)):
            ...
    """
    if not x_api_key or not x_api_key.strip():
        raise UnauthorizedError("缺少 X-API-Key Header")
    return await _authenticate_api_key(x_api_key)


# ═══════════════════════════════════════════════════════════════════
# JWT / API Key 内部认证逻辑
# ═══════════════════════════════════════════════════════════════════

async def _authenticate_jwt(token: str) -> dict:
    """验证 JWT access token。"""
    try:
        payload = decode_token(token)
    except Exception as e:
        raise UnauthorizedError(f"Access token 无效或已过期: {e}")

    if payload.get("type") != "access":
        raise UnauthorizedError("Token 类型错误: 期望 access token")

    # 检查黑名单（登出）
    jti = payload.get("jti")
    if jti and await is_token_blacklisted(jti):
        raise UnauthorizedError("Token 已失效，请重新登录")

    return {
        "user_id": payload["sub"],
        "role": payload.get("role", "viewer"),
        "auth_method": "jwt",
        "jti": jti,
    }


async def _authenticate_api_key(api_key_raw: str) -> dict:
    """验证 API Key。

    步骤:
      1. 从 Redis 缓存查找 key_hash（热路径优化）
      2. 缓存未命中 → MySQL 查询
      3. 验证哈希 → 更新 last_used_at
    """
    from db.redis import get_redis_async
    from db.mysql import execute_one, execute_write
    import hashlib
    from datetime import datetime, timezone

    key_hash = hashlib.sha256(api_key_raw.encode()).hexdigest()

    # 先查 Redis 缓存
    r = await get_redis_async()
    if r:
        cached = await r.get(f"apikey:user:{key_hash}")
        if cached:
            user_id, role = cached.split(":", 1)
            return {"user_id": user_id, "role": role, "auth_method": "api_key"}

    # 缓存未命中 → MySQL
    row = await execute_one(
        """SELECT a.id, a.user_id, a.permissions, a.expires_at, a.revoked_at, u.role, u.deleted_at
           FROM api_keys a
           JOIN users u ON a.user_id = u.id
           WHERE a.key_hash = %s""",
        (key_hash,),
    )

    if not row:
        raise UnauthorizedError("API Key 无效")

    if row["revoked_at"]:
        raise UnauthorizedError("API Key 已被撤销")

    if row["expires_at"] and row["expires_at"] < datetime.now(timezone.utc):
        raise UnauthorizedError("API Key 已过期")

    if row["deleted_at"]:
        raise UnauthorizedError("该账户已注销")

    # 更新最后使用时间（异步，不阻塞响应）
    import asyncio
    now = datetime.now(timezone.utc)
    try:
        asyncio.ensure_future(
            execute_write(
                "UPDATE api_keys SET last_used_at = %s WHERE id = %s",
                (now, row["id"]),
            )
        )
    except Exception:
        pass

    # 缓存到 Redis (5 分钟)
    if r:
        await r.setex(
            f"apikey:user:{key_hash}",
            300,
            f"{row['user_id']}:{row['role']}",
        )

    return {
        "user_id": row["user_id"],
        "role": row["role"],
        "auth_method": "api_key",
    }


# ═══════════════════════════════════════════════════════════════════
# 数据库连接依赖（注入到路由 handler）
# ═══════════════════════════════════════════════════════════════════

async def get_db_redis():
    """获取 Redis 异步客户端 (FastAPI Depends)。

    使用方式:
        @router.get("/cache-status")
        async def cache_status(r: Redis = Depends(get_db_redis)):
            if r is None:
                return {"status": "degraded"}
            ...

    Returns:
        aioredis.Redis 或 None (Redis 不可用时)
    """
    from db.redis import get_redis_async
    return await get_redis_async()


async def get_db_mysql():
    """获取 MySQL 连接池 (FastAPI Depends)。

    使用方式:
        @router.get("/users")
        async def list_users(pool = Depends(get_db_mysql)):
            ...
    """
    from db.mysql import get_mysql_pool
    return await get_mysql_pool()


async def get_db_mongo():
    """获取 MongoDB 数据库实例 (FastAPI Depends)。

    使用方式:
        @router.get("/analytics")
        async def analytics(db: AsyncIOMotorDatabase = Depends(get_db_mongo)):
            ...
    """
    from db.mongodb import get_mongo_db
    return await get_mongo_db()


async def get_db_neo4j():
    """获取 Neo4j 异步驱动 (FastAPI Depends)。

    使用方式:
        @router.get("/topology")
        async def topology(driver = Depends(get_db_neo4j)):
            ...
    """
    from db.neo4j import get_neo4j_driver
    return await get_neo4j_driver()


# ═══════════════════════════════════════════════════════════════════
# 客户端 IP 提取
# ═══════════════════════════════════════════════════════════════════

async def get_client_ip(request: Request) -> str:
    """提取客户端真实 IP（支持代理转发）。

    检查顺序: X-Forwarded-For > X-Real-IP > request.client.host
    """
    x_forwarded = request.headers.get("X-Forwarded-For")
    if x_forwarded:
        # 取链中第一个 IP（最原始的客户端）
        return x_forwarded.split(",")[0].strip()

    x_real_ip = request.headers.get("X-Real-IP")
    if x_real_ip:
        return x_real_ip.strip()

    return request.client.host if request.client else "unknown"


# ═══════════════════════════════════════════════════════════════════
# 游标分页
# ═══════════════════════════════════════════════════════════════════

async def get_cursor_params(
    cursor: Optional[str] = None,
    limit: int = 20,
    direction: str = "next",
) -> dict:
    """解析游标分页参数。

    使用方式:
        @router.get("/items")
        async def list_items(pagination: dict = Depends(get_cursor_params)):
            cursor = pagination["cursor"]
            limit = pagination["limit"]
            ...
    """
    return {
        "cursor": cursor,
        "limit": max(1, min(limit, 100)),
        "direction": direction if direction in ("next", "prev") else "next",
    }
