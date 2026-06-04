"""
SocialGraph Pro — 认证专用 Pydantic 模型

字段校验规则:
  - 密码: 最少 8 字符，必须包含大小写字母和数字
  - 邮箱: 基本格式校验
  - display_name: 1-100 字符
"""
from typing import Optional

from pydantic import BaseModel, EmailStr, Field, field_validator

from core.security import validate_password_strength


# ═══════════════════════════════════════════════════════════════════
# 注册
# ═══════════════════════════════════════════════════════════════════

class RegisterRequest(BaseModel):
    """用户注册请求。"""
    email: str = Field(
        ...,
        min_length=5,
        max_length=255,
        pattern=r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$',
        description="登录邮箱",
    )
    password: str = Field(..., min_length=8, max_length=128, description="登录密码")
    display_name: str = Field(..., min_length=1, max_length=100, description="显示名称")

    @field_validator("password")
    @classmethod
    def password_must_be_strong(cls, v: str) -> str:
        is_valid, error = validate_password_strength(v)
        if not is_valid:
            raise ValueError(error)
        return v

    @field_validator("email")
    @classmethod
    def email_must_be_valid(cls, v: str) -> str:
        from core.security import validate_email
        if not validate_email(v):
            raise ValueError("邮箱格式无效")
        return v.lower().strip()


class RegisterResponse(BaseModel):
    """用户注册成功响应。"""
    user_id: str
    email: str
    display_name: str
    role: str = "viewer"
    message: str = "注册成功"


# ═══════════════════════════════════════════════════════════════════
# 登录
# ═══════════════════════════════════════════════════════════════════

class LoginRequest(BaseModel):
    """用户登录请求。"""
    email: str = Field(..., min_length=1, max_length=255)
    password: str = Field(..., min_length=1, max_length=128)
    device_info: Optional[str] = Field(None, max_length=500, description="设备信息 (User-Agent)")

    @field_validator("email")
    @classmethod
    def normalize_email(cls, v: str) -> str:
        return v.lower().strip()


class LoginResponse(BaseModel):
    """登录成功响应。"""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = 900  # 秒
    user: "UserInfo"


class UserInfo(BaseModel):
    """公开用户信息（返回给前端，不包含敏感字段）。"""
    id: str
    email: str
    display_name: str
    role: str
    avatar_url: Optional[str] = None


# ═══════════════════════════════════════════════════════════════════
# Token 刷新
# ═══════════════════════════════════════════════════════════════════

class RefreshRequest(BaseModel):
    """刷新 Access Token 请求。"""
    refresh_token: str = Field(..., min_length=1)


class RefreshResponse(BaseModel):
    """刷新成功响应。"""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


# ═══════════════════════════════════════════════════════════════════
# 登出
# ═══════════════════════════════════════════════════════════════════

class LogoutRequest(BaseModel):
    """登出请求（可选传 refresh_token 以精确撤销）。"""
    refresh_token: Optional[str] = None
    all_devices: bool = False  # True = 撤销所有设备


class LogoutResponse(BaseModel):
    message: str = "已成功登出"


# ═══════════════════════════════════════════════════════════════════
# API Key 管理
# ═══════════════════════════════════════════════════════════════════

class CreateApiKeyRequest(BaseModel):
    """创建 API Key 请求。"""
    name: str = Field(..., min_length=1, max_length=100, description="密钥名称标签")
    permissions: list[str] = Field(
        default_factory=lambda: ["read:graph"],
        description="权限列表: read:graph, run:pagerank, export:csv 等"
    )
    expires_in_days: Optional[int] = Field(None, ge=1, le=365, description="有效期（天）")


class CreateApiKeyResponse(BaseModel):
    """创建 API Key 成功响应 — 仅此一次显示原始密钥。"""
    api_key_raw: str = Field(..., description="原始 API Key，仅显示一次，请妥善保存")
    key_prefix: str
    key_id: str
    name: str
    message: str = "API Key 创建成功，原始密钥仅在本次响应中展示，请立即保存"


class ApiKeyInfo(BaseModel):
    """API Key 摘要信息（不含 secret）。"""
    key_id: str
    key_prefix: str
    name: str
    permissions: list[str]
    last_used_at: Optional[str] = None
    expires_at: Optional[str] = None
    created_at: str
    is_revoked: bool = False
