"""
SocialGraph Pro — 全局异常处理器

功能:
  1. 捕获所有未处理的异常，返回统一 JSON 格式
  2. Request ID 生成与传播 (X-Request-ID header)
  3. 区分已知的 AppException 和未知的系统异常
  4. 生产环境下隐藏详细错误信息

响应格式:
  {
    "status": "error",
    "code": "ERROR_CODE",
    "message": "人类可读错误消息",
    "request_id": "req_abc123...",
    "detail": {}  // 可选
  }
"""
import logging
import traceback
import uuid

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from core.exceptions import AppException
from core.config import get_settings

logger = logging.getLogger("socialgraph.middleware.error")


class ErrorHandlerMiddleware(BaseHTTPMiddleware):
    """ASGI 中间件: 统一异常捕获。

    注入 request_id 到请求状态，并在响应头中返回。
    """

    async def dispatch(self, request: Request, call_next):
        # 生成或提取 request_id
        request_id = (
            request.headers.get("X-Request-ID")
            or request.headers.get("x-request-id")
            or f"req_{uuid.uuid4().hex[:12]}"
        )
        request.state.request_id = request_id

        try:
            response = await call_next(request)
            # 在响应头中返回 request_id
            response.headers["X-Request-ID"] = request_id
            return response

        except AppException as exc:
            # 已知的应用异常 → 有结构的错误响应
            return _build_error_response(exc, request_id)

        except Exception as exc:
            # 未知异常 → 500 + 隐藏内部细节（生产环境）
            return _build_unexpected_error(exc, request, request_id)


def _build_error_response(exc: AppException, request_id: str) -> JSONResponse:
    """构造已知异常的错误响应。"""
    logger.warning(
        "[%s] %s: %s (detail=%s)",
        request_id,
        exc.error_code,
        exc.message,
        exc.detail,
    )
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "status": "error",
            "code": exc.error_code,
            "message": exc.message,
            "request_id": request_id,
            "detail": exc.detail,
        },
    )


def _build_unexpected_error(exc: Exception, request: Request, request_id: str) -> JSONResponse:
    """构造未知异常的错误响应。"""
    logger.critical(
        "[%s] 未处理的内部错误: %s\nPath: %s %s\n%s",
        request_id,
        str(exc),
        request.method,
        request.url.path,
        traceback.format_exc(),
    )

    settings = get_settings()
    is_production = settings.environment == "production"

    message = "服务器内部错误" if is_production else str(exc)

    return JSONResponse(
        status_code=500,
        content={
            "status": "error",
            "code": "INTERNAL_ERROR",
            "message": message,
            "request_id": request_id,
        },
    )


# ═══════════════════════════════════════════════════════════════════
# FastAPI 异常处理器 (注册到 app)
# ═══════════════════════════════════════════════════════════════════

def register_exception_handlers(app):
    """将 FastAPI 原生异常处理器注册到 app 实例。"""

    from fastapi.exceptions import RequestValidationError
    from starlette.exceptions import HTTPException as StarletteHTTPException

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        request_id = getattr(request.state, "request_id", f"req_{uuid.uuid4().hex[:12]}")
        logger.warning("[%s] HTTP %d: %s", request_id, exc.status_code, exc.detail)
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "status": "error",
                "code": f"HTTP_{exc.status_code}",
                "message": str(exc.detail),
                "request_id": request_id,
            },
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        request_id = getattr(request.state, "request_id", f"req_{uuid.uuid4().hex[:12]}")
        errors = exc.errors()
        logger.warning("[%s] 请求校验失败: %s", request_id, errors)

        # 提取第一个错误作为主消息
        first_error = errors[0] if errors else {"msg": "请求参数无效"}
        field = ".".join(str(loc) for loc in first_error.get("loc", []) if loc != "body")

        return JSONResponse(
            status_code=422,
            content={
                "status": "error",
                "code": "VALIDATION_ERROR",
                "message": f"{field}: {first_error['msg']}" if field else first_error["msg"],
                "request_id": request_id,
                "detail": {"errors": errors},
            },
        )

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        """捕获所有未被上述处理器处理的异常（兜底）。"""
        request_id = getattr(request.state, "request_id", f"req_{uuid.uuid4().hex[:12]}")
        settings = get_settings()

        logger.critical(
            "[%s] 未捕获的全局异常: %s\nRoute: %s %s\n%s",
            request_id,
            str(exc),
            request.method,
            request.url.path,
            traceback.format_exc(),
        )

        message = "服务器内部错误" if settings.environment == "production" else str(exc)

        return JSONResponse(
            status_code=500,
            content={
                "status": "error",
                "code": "INTERNAL_ERROR",
                "message": message,
                "request_id": request_id,
            },
        )
