"""
SocialGraph Pro — 通用 Pydantic 模型

统一响应格式、分页、错误响应等。
"""
from typing import Any, Generic, Optional, TypeVar

from pydantic import BaseModel, Field


# ═══════════════════════════════════════════════════════════════════
# 通用响应包装器
# ═══════════════════════════════════════════════════════════════════

T = TypeVar("T")


class APIResponse(BaseModel, Generic[T]):
    """统一 API 响应格式。

    所有成功响应均包装为此格式:
      {"status": "success", "data": {...}, "request_id": "req_xxx"}
    """
    status: str = "success"
    data: T
    request_id: Optional[str] = None


class ErrorDetail(BaseModel):
    """错误详情。"""
    status: str = "error"
    code: str = "INTERNAL_ERROR"
    message: str = ""
    request_id: Optional[str] = None
    detail: Optional[dict[str, Any]] = None


# ═══════════════════════════════════════════════════════════════════
# 游标分页
# ═══════════════════════════════════════════════════════════════════

class CursorPage(BaseModel, Generic[T]):
    """游标分页响应。

    比 OFFSET/LIMIT 更高效的原生分页方式:
      - 使用上一页最后一条记录的唯一字段作为游标
      - 避免大 offset 导致的性能退化
      - 保证在数据写入情况下的分页稳定性
    """
    items: list[T] = Field(default_factory=list)
    total: Optional[int] = None  # 可选总数（需额外 COUNT 查询）
    next_cursor: Optional[str] = None
    has_more: bool = False


class CursorParams(BaseModel):
    """游标分页请求参数。"""
    cursor: Optional[str] = Field(None, description="上一页最后一项的游标值")
    limit: int = Field(20, ge=1, le=100, description="每页数量")
    direction: str = Field("next", pattern="^(next|prev)$", description="分页方向")
