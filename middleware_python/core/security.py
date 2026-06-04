"""
SocialGraph Pro — 安全认证模块

提供:
  1. JWT 访问令牌 / 刷新令牌 的创建与验证
  2. bcrypt 密码哈希 (cost=12)
  3. API Key 的创建、验证、哈希存储
  4. Token 黑名单 (Redis) 用于登出

密钥管理:
  生产环境必须设置环境变量 SGP_JWT_SECRET_KEY，否则启动时发出警告。
"""
import hashlib
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
from jose import JWTError, jwt

from core.config import get_settings


# ═══════════════════════════════════════════════════════════════════
# 密码哈希
# ═══════════════════════════════════════════════════════════════════

def hash_password(password: str) -> str:
    """使用 bcrypt 对密码进行哈希，cost 由配置决定（默认 12）。"""
    settings = get_settings()
    salt = bcrypt.gensalt(rounds=settings.bcrypt_cost)
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """验证密码与 bcrypt 哈希是否匹配。"""
    return bcrypt.checkpw(
        plain_password.encode("utf-8"),
        hashed_password.encode("utf-8"),
    )


# ═══════════════════════════════════════════════════════════════════
# JWT 令牌
# ═══════════════════════════════════════════════════════════════════

def create_access_token(
    user_id: str,
    role: str = "viewer",
    expires_delta: Optional[timedelta] = None,
) -> str:
    """创建 JWT 访问令牌 (Access Token)。

    Args:
        user_id:  用户 UUID
        role:     用户角色 (admin / analyst / viewer)
        expires_delta: 自定义过期时间，默认使用配置值

    Returns:
        编码后的 JWT 字符串
    """
    settings = get_settings()
    now = datetime.now(timezone.utc)
    expire = now + (expires_delta or timedelta(minutes=settings.access_token_expire_minutes))

    payload = {
        "sub": user_id,
        "role": role,
        "type": "access",
        "iat": now,
        "exp": expire,
        "jti": secrets.token_hex(16),  # 令牌唯一 ID，用于黑名单
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def create_refresh_token(
    user_id: str,
    session_id: str,
    expires_delta: Optional[timedelta] = None,
) -> str:
    """创建 JWT 刷新令牌 (Refresh Token)。

    Refresh Token 有过期时间更长，用于静默续期 Access Token。
    同时用于 token family 机制：当 refresh token 被泄露时，
    可撤销整个 family。

    Args:
        user_id:    用户 UUID
        session_id: 会话 UUID (关联 MySQL sessions 表)
        expires_delta: 自定义过期时间，默认 30 天

    Returns:
        编码后的 JWT 字符串
    """
    settings = get_settings()
    now = datetime.now(timezone.utc)
    expire = now + (expires_delta or timedelta(days=settings.refresh_token_expire_days))

    payload = {
        "sub": user_id,
        "session_id": session_id,
        "type": "refresh",
        "iat": now,
        "exp": expire,
        "jti": secrets.token_hex(16),
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_token(token: str) -> dict:
    """解码并验证 JWT 令牌。

    Args:
        token: JWT 字符串 (access 或 refresh)

    Returns:
        解码后的 payload dict

    Raises:
        JWTError: 令牌无效 / 已过期 / 签名不匹配
    """
    settings = get_settings()
    return jwt.decode(
        token,
        settings.jwt_secret_key,
        algorithms=[settings.jwt_algorithm],
        options={"require": ["sub", "type", "exp"]},
    )


def decode_token_no_verify(token: str) -> Optional[dict]:
    """解码 JWT 令牌但不验证签名（用于提取过期时间等元数据，实现黑名单预检查）。"""
    try:
        return jwt.get_unverified_claims(token)
    except JWTError:
        return None


# ═══════════════════════════════════════════════════════════════════
# Token 黑名单 (Redis) — 用于登出
# ═══════════════════════════════════════════════════════════════════

async def is_token_blacklisted(jti: str) -> bool:
    """检查 token 是否在黑名单中（是否已被登出/撤销）。"""
    from db.redis import get_redis_async

    r = await get_redis_async()
    if r is None:
        return False  # Redis 不可用时，不阻止请求（降级策略）
    return await r.exists(f"blacklist:token:{jti}") > 0


async def blacklist_token(jti: str, ttl: int) -> bool:
    """将 token 加入黑名单。

    Args:
        jti: token 唯一 ID (JWT ID)
        ttl: 黑名单存活时间（秒），应等于 token 剩余有效期

    Returns:
        是否成功
    """
    from db.redis import get_redis_async

    r = await get_redis_async()
    if r is None:
        return False
    await r.setex(f"blacklist:token:{jti}", ttl, "1")
    return True


async def revoke_token_family(user_id: str) -> bool:
    """撤销某个用户的所有活跃 token（强制所有设备重新登录）。

    通过递增 token family 版本号实现，所有旧 token 验证时被拒绝。
    """
    from db.redis import get_redis_async

    r = await get_redis_async()
    if r is None:
        return False
    await r.incr(f"token_family_version:{user_id}")
    return True


async def get_token_family_version(user_id: str) -> int:
    """获取用户的 token family 版本号。"""
    from db.redis import get_redis_async

    r = await get_redis_async()
    if r is None:
        return 0
    version = await r.get(f"token_family_version:{user_id}")
    return int(version) if version else 0


# ═══════════════════════════════════════════════════════════════════
# API Key 认证
# ═══════════════════════════════════════════════════════════════════

def generate_api_key() -> tuple[str, str, str]:
    """生成 API Key 三元组。

    Returns:
        (raw_key, key_prefix, key_hash)
        - raw_key:   给用户一次显示的原始密钥 (如 "sk_a1b2c3d4e5f6...")
        - key_prefix: 前半部分用于 UI 展示 (如 "sk_a1b2c3d4")
        - key_hash:   SHA-256 哈希，存入数据库
    """
    settings = get_settings()
    random_part = secrets.token_hex(32)  # 64 字符随机
    raw_key = f"{settings.api_key_prefix}{random_part}"
    key_prefix = raw_key[:12]  # 前 12 字符用于 UI 识别
    key_hash = _hash_api_key(raw_key)
    return raw_key, key_prefix, key_hash


def verify_api_key(raw_key: str, stored_hash: str) -> bool:
    """验证 API Key 是否匹配存储的哈希值。"""
    return _hash_api_key(raw_key) == stored_hash


def _hash_api_key(raw_key: str) -> str:
    """使用 SHA-256 哈希 API Key（加盐可选，但 SHA-256 足够安全因为输入熵很高）。"""
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


# ═══════════════════════════════════════════════════════════════════
# 密码强度校验
# ═══════════════════════════════════════════════════════════════════

def validate_password_strength(password: str) -> tuple[bool, Optional[str]]:
    """校验密码强度。

    规则:
      - 最少 8 字符
      - 至少包含 1 个大写字母
      - 至少包含 1 个小写字母
      - 至少包含 1 个数字

    Returns:
        (is_valid, error_message)
    """
    if len(password) < 8:
        return False, "密码长度至少为 8 个字符"
    if not any(c.isupper() for c in password):
        return False, "密码必须包含至少一个大写字母"
    if not any(c.islower() for c in password):
        return False, "密码必须包含至少一个小写字母"
    if not any(c.isdigit() for c in password):
        return False, "密码必须包含至少一个数字"
    return True, None


# ═══════════════════════════════════════════════════════════════════
# 邮箱格式校验
# ═══════════════════════════════════════════════════════════════════

def validate_email(email: str) -> bool:
    """基本邮箱格式校验（不依赖正则，足够覆盖常见场景）。"""
    if "@" not in email:
        return False
    local, _, domain = email.partition("@")
    if not local or not domain:
        return False
    if "." not in domain:
        return False
    if len(email) > 254:
        return False
    return True
