"""
SocialGraph Pro — 健康检查模型
"""
from typing import Optional

from pydantic import BaseModel, Field


class ComponentHealth(BaseModel):
    """单个组件的健康状态。"""
    status: str = Field("unknown", description="healthy / degraded / unavailable / unknown")
    latency_ms: Optional[float] = Field(None, description="连接延迟（毫秒）")
    message: Optional[str] = Field(None, description="额外信息")


class DeepHealthResponse(BaseModel):
    """深度健康检查响应，逐组件报告状态。"""
    status: str = Field("healthy", description="healthy / degraded / unhealthy")
    version: str
    uptime_seconds: float
    components: dict[str, ComponentHealth]
    timestamp: str
