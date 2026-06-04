"""
SocialGraph Pro — 认证授权路由

端点:
  POST   /api/v1/auth/register      — 用户注册
  POST   /api/v1/auth/login         — 用户登录
  POST   /api/v1/auth/refresh       — 刷新 Access Token
  POST   /api/v1/auth/logout        — 用户登出
  POST   /api/v1/auth/api-keys      — 创建 API Key
  GET    /api/v1/auth/api-keys      — 列出 API Key
  DELETE /api/v1/auth/api-keys/{id} — 撤销 API Key
"""
import logging

from fastapi import APIRouter, Depends, status

from auth.models import (
    RegisterRequest, RegisterResponse,
    LoginRequest, LoginResponse,
    RefreshRequest, RefreshResponse,
    LogoutRequest, LogoutResponse,
    CreateApiKeyRequest, CreateApiKeyResponse, ApiKeyInfo,
)
from auth.service import (
    register_user,
    login_user,
    refresh_access_token,
    logout_user,
    create_user_api_key,
    list_user_api_keys,
    revoke_api_key,
)
from core.dependencies import get_current_user, get_client_ip

logger = logging.getLogger("socialgraph.routes.auth")

router = APIRouter(prefix="/api/v1/auth", tags=["认证与授权"])


@router.post("/register", response_model=RegisterResponse, status_code=status.HTTP_201_CREATED)
async def register(req: RegisterRequest):
    """注册新用户。

    密码要求:
      - 最少 8 个字符
      - 包含至少一个大写字母
      - 包含至少一个小写字母
      - 包含至少一个数字
    """
    result = await register_user(
        email=req.email,
        password=req.password,
        display_name=req.display_name,
    )
    return RegisterResponse(**result)


@router.post("/login", response_model=LoginResponse)
async def login(req: LoginRequest, ip: str = Depends(get_client_ip)):
    """用户登录，返回 access_token + refresh_token。

    Access Token 有效期 15 分钟，Refresh Token 有效期 30 天。
    支持多设备同时登录。
    """
    result = await login_user(
        email=req.email,
        password=req.password,
        device_info=req.device_info or "",
        ip_address=ip,
    )
    return LoginResponse(**result)


@router.post("/refresh", response_model=RefreshResponse)
async def refresh(req: RefreshRequest):
    """使用 Refresh Token 换取新的 Access Token 和 Refresh Token。

    安全机制: Refresh Token Rotation — 每次刷新都会撤销旧 token
    并签发新 token。如果旧 token 被重用，将触发全设备登出。
    """
    result = await refresh_access_token(req.refresh_token)
    return RefreshResponse(**result)


@router.post("/logout", response_model=LogoutResponse)
async def logout(
    req: LogoutRequest,
    current_user: dict = Depends(get_current_user),
):
    """登出当前用户。

    - 不传参数: 需要可选的 refresh_token 参数精确登出
    - refresh_token: 撤销指定设备会话
    - all_devices=true: 撤销所有设备，所有 refresh token 失效
    """
    await logout_user(
        user_id=current_user["user_id"],
        refresh_token=req.refresh_token,
        all_devices=req.all_devices,
    )
    return LogoutResponse()


@router.post("/api-keys", response_model=CreateApiKeyResponse, status_code=status.HTTP_201_CREATED)
async def create_api_key(
    req: CreateApiKeyRequest,
    current_user: dict = Depends(get_current_user),
):
    """创建 API Key 用于程序化访问。

    原始密钥仅在此次响应中返回，请立即安全保存。
    不存储原始密钥，仅存 SHA-256 哈希。
    """
    result = await create_user_api_key(
        user_id=current_user["user_id"],
        name=req.name,
        permissions=req.permissions,
        expires_in_days=req.expires_in_days,
    )
    return CreateApiKeyResponse(**result)


@router.get("/api-keys", response_model=list[ApiKeyInfo])
async def list_api_keys(current_user: dict = Depends(get_current_user)):
    """列出当前用户的所有 API Key（不含原始密钥）。"""
    keys = await list_user_api_keys(current_user["user_id"])
    return [ApiKeyInfo(**k) for k in keys]


@router.delete("/api-keys/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_api_key_endpoint(
    key_id: str,
    current_user: dict = Depends(get_current_user),
):
    """撤销指定的 API Key。"""
    await revoke_api_key(current_user["user_id"], key_id)
