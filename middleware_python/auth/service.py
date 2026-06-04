"""
SocialGraph Pro — 认证业务逻辑

负责:
  - 用户注册（含邮箱唯一性校验）
  - 用户登录（密码验证 + JWT 生成 + 会话持久化）
  - Token 刷新（轮换 refresh token 防重放）
  - 登出（单个会话 / 全部设备）
  - API Key CRUD
"""
import logging
import time
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional

from core.config import get_settings
from core.security import (
    hash_password,
    verify_password,
    create_access_token,
    create_refresh_token,
    decode_token,
    generate_api_key,
    blacklist_token,
)
from core.exceptions import (
    ConflictError,
    UnauthorizedError,
    NotFoundError,
    BadRequestError,
)

logger = logging.getLogger("socialgraph.auth")


# ═══════════════════════════════════════════════════════════════════
# 注册
# ═══════════════════════════════════════════════════════════════════

async def register_user(email: str, password: str, display_name: str) -> dict:
    """注册新用户。

    Steps:
      1. 检查邮箱是否已注册
      2. bcrypt 哈希密码
      3. INSERT 用户记录
      4. 返回用户信息

    Raises:
        ConflictError: 邮箱已存在
        DatabaseUnavailableError: MySQL 不可用
    """
    from db.mysql import execute_one, execute_insert

    # 检查邮箱唯一性
    existing = await execute_one(
        "SELECT id FROM users WHERE email = %s AND deleted_at IS NULL",
        (email,),
    )
    if existing:
        raise ConflictError(f"邮箱已注册: {email}", detail={"email": email})

    user_id = str(uuid.uuid4())
    password_hash = hash_password(password)
    now = datetime.now(timezone.utc)

    rows = await execute_insert(
        """INSERT INTO users (id, email, password_hash, display_name, role, email_verified_at, created_at, updated_at)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
        (user_id, email, password_hash, display_name, "viewer", None, now, now),
    )

    if not rows:
        from core.exceptions import DatabaseUnavailableError
        raise DatabaseUnavailableError("用户注册失败：数据库不可用")

    logger.info("新用户注册: email=%s, id=%s", email, user_id)

    return {
        "user_id": user_id,
        "email": email,
        "display_name": display_name,
        "role": "viewer",
    }


# ═══════════════════════════════════════════════════════════════════
# 登录
# ═══════════════════════════════════════════════════════════════════

async def login_user(email: str, password: str, device_info: str = "",
                     ip_address: str = "") -> dict:
    """用户登录。

    Steps:
      1. 检查账户是否被锁定
      2. 检查登录频率限制
      3. 查找用户（含软删除检查）
      4. bcrypt 验证密码
      5. 创建 access + refresh token
      6. 持久化会话 (MySQL: sessions 表)
      7. 更新 last_login_at + 清除失败计数
      8. 返回 token 对

    Raises:
        UnauthorizedError: 邮箱或密码不正确 / 账户已锁定 / 请求过于频繁
    """
    from db.mysql import execute_one, execute_write, execute_insert
    import hashlib

    # 0. 检查账户锁定
    locked_until = await _get_account_lock(email)
    if locked_until:
        remaining = int((locked_until - datetime.now(timezone.utc)).total_seconds())
        if remaining > 0:
            raise UnauthorizedError(
                f"账户已被临时锁定，请在 {int(remaining / 60) + 1} 分钟后重试"
            )

    # 0b. 检查登录频率限制 (IP 级别)
    ip_allowed, ip_msg = await _check_login_ip_rate_limit(ip_address)
    if not ip_allowed:
        raise UnauthorizedError(ip_msg)

    # 1. 查找用户
    user = await execute_one(
        "SELECT id, email, password_hash, display_name, role, avatar_url FROM users "
        "WHERE email = %s AND deleted_at IS NULL",
        (email,),
    )
    if not user:
        await _record_login_failure(email, ip_address)
        raise UnauthorizedError("邮箱或密码不正确")

    # 2. 验证密码
    if not verify_password(password, user["password_hash"]):
        await _record_login_failure(email, ip_address)
        raise UnauthorizedError("邮箱或密码不正确")

    # 3. 登录成功 → 清除失败计数
    await _clear_login_failures(email)

    # 创建会话
    session_id = str(uuid.uuid4())
    access_token = create_access_token(user["id"], user["role"])
    refresh_token = create_refresh_token(user["id"], session_id)

    # 存 refresh_token 哈希到 sessions 表
    refresh_hash = hashlib.sha256(refresh_token.encode()).hexdigest()
    now = datetime.now(timezone.utc)
    settings = get_settings()
    expires_at = now + timedelta(days=settings.refresh_token_expire_days)

    await execute_insert(
        """INSERT INTO sessions (id, user_id, refresh_token_hash, device_info, ip_address, expires_at, created_at)
           VALUES (%s, %s, %s, %s, %s, %s, %s)""",
        (session_id, user["id"], refresh_hash, device_info[:500] if device_info else None,
         ip_address, expires_at, now),
    )

    # 更新最后登录时间
    await execute_write(
        "UPDATE users SET last_login_at = %s WHERE id = %s",
        (now, user["id"]),
    )

    logger.info("用户登录成功: email=%s, session=%s", email, session_id)

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "expires_in": settings.access_token_expire_minutes * 60,
        "user": {
            "id": user["id"],
            "email": user["email"],
            "display_name": user["display_name"],
            "role": user["role"],
            "avatar_url": user.get("avatar_url"),
        },
    }


# ── 登录安全辅助函数 ────────────────────────────────────────

async def _check_login_ip_rate_limit(ip_address: str) -> tuple[bool, str]:
    """检查单个 IP 的登录频率限制 (严格: 5次/分钟)。"""
    if not ip_address:
        return (True, "")

    settings = get_settings()
    from db.redis import get_redis_async
    r = await get_redis_async()
    if r is None:
        return (True, "")  # Redis 不可用时放行

    key = f"login_ip:{ip_address}:60s"
    try:
        count = await r.incr(key)
        if count == 1:
            await r.expire(key, 60)
        if count > settings.login_max_attempts:
            return (False, "登录请求过于频繁，请稍后重试")
        return (True, "")
    except Exception:
        return (True, "")


async def _get_account_lock(email: str):
    """获取账户锁定到期时间。"""
    from db.redis import get_redis_async
    r = await get_redis_async()
    if r is None:
        return None
    try:
        val = await r.get(f"login_lock:{email}")
        if val:
            return datetime.fromtimestamp(float(val), tz=timezone.utc)
    except Exception:
        pass
    return None


async def _record_login_failure(email: str, ip_address: str):
    """记录登录失败，达到阈值后锁定账户。"""
    settings = get_settings()
    from db.redis import get_redis_async
    r = await get_redis_async()
    if r is None:
        return

    try:
        fail_key = f"login_fail:{email}"
        current = await r.incr(fail_key)
        await r.expire(fail_key, settings.login_lockout_minutes * 60 * 2)

        if current >= settings.login_max_attempts:
            lock_until = datetime.now(timezone.utc) + timedelta(
                minutes=settings.login_lockout_minutes
            )
            await r.setex(
                f"login_lock:{email}",
                settings.login_lockout_minutes * 60,
                str(lock_until.timestamp()),
            )
            logger.warning(
                "账户已锁定: email=%s, 失败次数=%d, 锁定至=%s",
                email, current, lock_until.isoformat(),
            )
        else:
            logger.warning(
                "登录失败: email=%s, ip=%s, 尝试=%d/%d",
                email, ip_address, current, settings.login_max_attempts,
            )
    except Exception:
        pass


async def _clear_login_failures(email: str):
    """登录成功后清除失败计数和锁定。"""
    from db.redis import get_redis_async
    r = await get_redis_async()
    if r is None:
        return
    try:
        await r.delete(f"login_fail:{email}", f"login_lock:{email}")
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════
# Token 刷新 (轮换)
# ═══════════════════════════════════════════════════════════════════

async def refresh_access_token(refresh_token_str: str) -> dict:
    """使用 refresh token 换取新的 access token + 新的 refresh token。

    安全机制 — Refresh Token Rotation:
      - 每次刷新都签发全新的 refresh token
      - 旧的 refresh token 立即失效（存入黑名单）
      - 如果发现已撤销的 refresh token 被重用（泄露检测）→
        撤销该用户全部会话

    Args:
        refresh_token_str: 原始的 refresh token

    Returns:
        新的 token 对

    Raises:
        UnauthorizedError: refresh token 无效 / 已过期 / 已被撤销
    """
    from db.mysql import execute_one, execute_write, execute_insert
    import hashlib

    # 解码并验证
    try:
        payload = decode_token(refresh_token_str)
    except Exception as e:
        raise UnauthorizedError(f"Refresh token 无效: {e}")

    if payload.get("type") != "refresh":
        raise UnauthorizedError("Token 类型错误: 期望 refresh token")

    user_id = payload["sub"]
    session_id = payload.get("session_id")
    jti = payload.get("jti")

    # 检查 token 是否在黑名单中 (重用检测)
    from core.security import is_token_blacklisted
    if await is_token_blacklisted(jti):
        # Token 已被撤销但仍被使用 → 泄露事件！
        # 撤销该用户所有会话
        from core.security import revoke_token_family
        await revoke_token_family(user_id)
        logger.critical("检测到 refresh token 重用! user_id=%s, 已撤销所有会话", user_id)
        raise UnauthorizedError("安全警报: 检测到异常活动，请重新登录")

    # 验证 session 存在且未撤销
    session = await execute_one(
        "SELECT id, user_id, refresh_token_hash, expires_at, revoked_at "
        "FROM sessions WHERE id = %s",
        (session_id,),
    )
    if not session or session["revoked_at"] is not None:
        raise UnauthorizedError("会话已失效，请重新登录")

    # 验证 refresh token hash 匹配
    expected_hash = hashlib.sha256(refresh_token_str.encode()).hexdigest()
    if session["refresh_token_hash"] != expected_hash:
        raise UnauthorizedError("Refresh token 不匹配")

    # 检查是否过期
    if session["expires_at"] and session["expires_at"] < datetime.now(timezone.utc):
        raise UnauthorizedError("Refresh token 已过期，请重新登录")

    # ── 轮换: 撤销旧 token，签发新 token ──
    now = datetime.now(timezone.utc)

    # 1. 将旧 refresh token 加入黑名单
    ttl = 86400  # 默认 24 小时
    await blacklist_token(jti, ttl)

    # 2. 获取用户角色
    user = await execute_one(
        "SELECT role FROM users WHERE id = %s AND deleted_at IS NULL",
        (user_id,),
    )
    if not user:
        raise UnauthorizedError("用户不存在")

    # 3. 创建新的会话和 token
    new_session_id = str(uuid.uuid4())
    new_access_token = create_access_token(user_id, user["role"])
    new_refresh_token = create_refresh_token(user_id, new_session_id)

    new_refresh_hash = hashlib.sha256(new_refresh_token.encode()).hexdigest()
    settings = get_settings()
    new_expires_at = now + timedelta(days=settings.refresh_token_expire_days)

    # 4. 持久化新 session (在同一事务中完成旧 session 作废 + 新 session 创建)
    #    这里使用两条语句，因为 aiomysql 事务支持需额外配置
    await execute_write(
        "UPDATE sessions SET revoked_at = %s WHERE id = %s",
        (now, session_id),
    )
    await execute_insert(
        """INSERT INTO sessions (id, user_id, refresh_token_hash, device_info, ip_address, expires_at, created_at)
           VALUES (%s, %s, %s, %s, %s, %s, %s)""",
        (new_session_id, user_id, new_refresh_hash,
         session.get("device_info"), session.get("ip_address"),
         new_expires_at, now),
    )

    logger.info("Token 刷新成功: user=%s, old_session=%s, new_session=%s",
                user_id, session_id, new_session_id)

    return {
        "access_token": new_access_token,
        "refresh_token": new_refresh_token,
        "token_type": "bearer",
        "expires_in": settings.access_token_expire_minutes * 60,
    }


# ═══════════════════════════════════════════════════════════════════
# 登出
# ═══════════════════════════════════════════════════════════════════

async def logout_user(user_id: str, refresh_token: Optional[str] = None,
                      all_devices: bool = False) -> None:
    """用户登出。

    Args:
        user_id:        用户 ID (来自 JWT token)
        refresh_token:  要撤销的具体 refresh token
        all_devices:    是否撤销所有设备
    """
    from db.mysql import execute_write
    import hashlib

    now = datetime.now(timezone.utc)

    if all_devices:
        # 撤销所有设备
        await execute_write(
            "UPDATE sessions SET revoked_at = %s WHERE user_id = %s AND revoked_at IS NULL",
            (now, user_id),
        )
        from core.security import revoke_token_family
        await revoke_token_family(user_id)
        logger.info("用户登出(全部设备): user_id=%s", user_id)
    elif refresh_token:
        # 撤销指定 refresh token 对应的会话
        refresh_hash = hashlib.sha256(refresh_token.encode()).hexdigest()
        await execute_write(
            "UPDATE sessions SET revoked_at = %s WHERE refresh_token_hash = %s AND user_id = %s",
            (now, refresh_hash, user_id),
        )
        # 将 token 加入黑名单
        try:
            payload = decode_token(refresh_token)
            await blacklist_token(payload["jti"], 86400)
        except Exception:
            pass
        logger.info("用户登出(单设备): user_id=%s", user_id)
    else:
        raise BadRequestError("请提供 refresh_token 或设置 all_devices=true")


# ═══════════════════════════════════════════════════════════════════
# API Key 管理
# ═══════════════════════════════════════════════════════════════════

async def create_user_api_key(user_id: str, name: str, permissions: list[str],
                              expires_in_days: Optional[int] = None) -> dict:
    """为用户创建 API Key。

    Returns:
        dict 包含 raw_key (仅此一次显示)
    """
    from db.mysql import execute_insert
    from core.security import generate_api_key

    raw_key, key_prefix, key_hash = generate_api_key()
    key_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    expires_at = None
    if expires_in_days:
        expires_at = now + timedelta(days=expires_in_days)

    import json
    await execute_insert(
        """INSERT INTO api_keys (id, user_id, key_hash, key_prefix, name, permissions, expires_at, created_at)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
        (key_id, user_id, key_hash, key_prefix, name, json.dumps(permissions), expires_at, now),
    )

    logger.info("API Key 已创建: user=%s, key_id=%s, name=%s", user_id, key_id, name)

    return {
        "api_key_raw": raw_key,
        "key_prefix": key_prefix,
        "key_id": key_id,
        "name": name,
    }


async def list_user_api_keys(user_id: str) -> list[dict]:
    """列出用户的所有 API Key（不包含密钥本身）。"""
    from db.mysql import execute_query
    rows = await execute_query(
        """SELECT id, key_prefix, name, permissions, last_used_at, expires_at, created_at, revoked_at
           FROM api_keys WHERE user_id = %s ORDER BY created_at DESC""",
        (user_id,),
    )
    import json
    return [
        {
            "key_id": r["id"],
            "key_prefix": r["key_prefix"],
            "name": r["name"],
            "permissions": json.loads(r["permissions"]) if isinstance(r["permissions"], str) else r["permissions"],
            "last_used_at": r["last_used_at"].isoformat() if r["last_used_at"] else None,
            "expires_at": r["expires_at"].isoformat() if r["expires_at"] else None,
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            "is_revoked": r["revoked_at"] is not None,
        }
        for r in rows
    ]


async def revoke_api_key(user_id: str, key_id: str) -> bool:
    """撤销 API Key。"""
    from db.mysql import execute_write
    now = datetime.now(timezone.utc)
    rows = await execute_write(
        "UPDATE api_keys SET revoked_at = %s WHERE id = %s AND user_id = %s AND revoked_at IS NULL",
        (now, key_id, user_id),
    )
    if rows == 0:
        raise NotFoundError(f"API Key 不存在或已撤销: {key_id}")
    logger.info("API Key 已撤销: user=%s, key_id=%s", user_id, key_id)
    return True
