"""
SocialGraph Pro — 统一异常层次结构

设计原则:
  1. 所有自定义异常继承自 AppException 基类
  2. 每个异常自带 HTTP 状态码和错误码 (ERROR_CODE)
  3. 错误码命名遵循 UPPER_SNAKE_CASE，含义自解释
  4. 中间件 error_handler.py 自动捕获并转换为统一 JSON 响应

使用方式:
    from core.exceptions import NotFoundError, UnauthorizedError
    raise NotFoundError("用户不存在", detail={"user_id": "xxx"})
"""

from typing import Any, Optional


class AppException(Exception):
    """应用异常基类。

    所有业务异常必须继承此类。中间件依赖 status_code 和 error_code
    来生成统一格式的错误响应。

    Attributes:
        status_code:  HTTP 状态码
        error_code:   机器可读错误码 (如 "RESOURCE_NOT_FOUND")
        message:      人类可读错误消息
        detail:       附加上下文信息 (dict, 可选)
    """

    status_code: int = 500
    error_code: str = "INTERNAL_ERROR"

    def __init__(
        self,
        message: str = "服务器内部错误",
        detail: Optional[dict[str, Any]] = None,
    ) -> None:
        self.message = message
        self.detail = detail or {}
        super().__init__(message)


# ═══════════════════════════════════════════════════════════════════
# HTTP 4xx — 客户端错误
# ═══════════════════════════════════════════════════════════════════

class BadRequestError(AppException):
    status_code = 400
    error_code = "BAD_REQUEST"

    def __init__(self, message: str = "请求参数无效", detail: Optional[dict] = None):
        super().__init__(message, detail)


class ValidationError(AppException):
    """Pydantic 校验失败（被 error_handler 捕获后统一格式化）。"""
    status_code = 422
    error_code = "VALIDATION_ERROR"

    def __init__(self, message: str = "数据校验失败", detail: Optional[dict] = None):
        super().__init__(message, detail)


class UnauthorizedError(AppException):
    """未认证：缺少或无效的 JWT token / API Key。"""
    status_code = 401
    error_code = "UNAUTHORIZED"

    def __init__(self, message: str = "未认证，请先登录", detail: Optional[dict] = None):
        super().__init__(message, detail)


class ForbiddenError(AppException):
    """已认证但权限不足。"""
    status_code = 403
    error_code = "FORBIDDEN"

    def __init__(self, message: str = "权限不足", detail: Optional[dict] = None):
        super().__init__(message, detail)


class NotFoundError(AppException):
    """资源不存在（用户、快照、分析记录等）。"""
    status_code = 404
    error_code = "RESOURCE_NOT_FOUND"

    def __init__(self, message: str = "资源不存在", detail: Optional[dict] = None):
        super().__init__(message, detail)


class ConflictError(AppException):
    """资源冲突（如邮箱已注册）。"""
    status_code = 409
    error_code = "RESOURCE_CONFLICT"

    def __init__(self, message: str = "资源冲突", detail: Optional[dict] = None):
        super().__init__(message, detail)


class RateLimitError(AppException):
    """请求频率超过限制。"""
    status_code = 429
    error_code = "RATE_LIMIT_EXCEEDED"

    def __init__(self, message: str = "请求过于频繁，请稍后再试", detail: Optional[dict] = None):
        super().__init__(message, detail)


# ═══════════════════════════════════════════════════════════════════
# HTTP 5xx — 服务端错误
# ═══════════════════════════════════════════════════════════════════

class CppEngineError(AppException):
    """C++ 图计算引擎异常（崩溃/超时/输出格式异常）。"""
    status_code = 502
    error_code = "CPP_ENGINE_ERROR"

    def __init__(self, message: str = "C++ 计算引擎异常", detail: Optional[dict] = None):
        super().__init__(message, detail)


class DatabaseUnavailableError(AppException):
    """数据库不可用（连接池耗尽/网络不通/未初始化）。"""
    status_code = 503
    error_code = "DATABASE_UNAVAILABLE"

    def __init__(self, message: str = "数据库服务不可用", detail: Optional[dict] = None):
        super().__init__(message, detail)


class ServiceUnavailableError(AppException):
    """通用服务不可用（维护模式、降级等）。"""
    status_code = 503
    error_code = "SERVICE_UNAVAILABLE"

    def __init__(self, message: str = "服务不可用", detail: Optional[dict] = None):
        super().__init__(message, detail)


class ExternalServiceError(AppException):
    """外部服务调用失败（Redis、Neo4j、MongoDB 操作失败）。"""
    status_code = 502
    error_code = "EXTERNAL_SERVICE_ERROR"

    def __init__(self, message: str = "外部服务调用失败", detail: Optional[dict] = None):
        super().__init__(message, detail)


class ComputeTimeoutError(AppException):
    """C++ 引擎执行超时。"""
    status_code = 504
    error_code = "COMPUTE_TIMEOUT"

    def __init__(self, message: str = "计算超时", detail: Optional[dict] = None):
        super().__init__(message, detail)
