"""
SocialGraph Pro — 图计算相关 Pydantic 模型

合并原 models.py 中的所有模型，增加新模型。
"""
from typing import Optional

from pydantic import BaseModel, Field


# ═══════════════════════════════════════════════════════════════════
# 拓扑图模型
# ═══════════════════════════════════════════════════════════════════

class NodeInfo(BaseModel):
    id: str
    group: int = 1
    label: Optional[str] = None
    size: Optional[float] = None


class LinkInfo(BaseModel):
    source: str
    target: str
    weight: float = 1.0


class GraphAllResponse(BaseModel):
    status: str
    nodes: list[NodeInfo] = []
    links: list[LinkInfo] = []


class GraphPaginatedResponse(BaseModel):
    """分页拓扑响应 — 解决全量 4MB 一次性加载问题。"""
    status: str
    page: int
    page_size: int
    total_nodes: int
    total_edges: int
    total_pages: int
    nodes: list[NodeInfo] = []
    links: list[LinkInfo] = []


# ═══════════════════════════════════════════════════════════════════
# 路径查询模型
# ═══════════════════════════════════════════════════════════════════

class PathRequest(BaseModel):
    start_node: str = Field(..., min_length=1, description="起始节点 ID")
    target_node: str = Field("", description="目标节点 ID")
    algorithm: str = Field("bfs", pattern="^(bfs|dijkstra|dfs)$",
                           description="路径算法: bfs / dijkstra / dfs")


class PathResponse(BaseModel):
    status: str
    time_ms: int = 0
    path: list[str] = []
    path_length: int = 0


# ═══════════════════════════════════════════════════════════════════
# 算法结果模型
# ═══════════════════════════════════════════════════════════════════

class ScoreItem(BaseModel):
    node: str
    score: float


class AlgorithmResultResponse(BaseModel):
    status: str
    time_ms: int = 0
    data: list[dict] = []


class CommunityItem(BaseModel):
    node: str
    community: str


class CommunityResponse(BaseModel):
    status: str
    time_ms: int = 0
    data: list[CommunityItem] = []


class ConnectedComponentsResponse(BaseModel):
    status: str
    time_ms: int = 0
    component_count: int = 0
    component_sizes: dict = {}
    data: list[dict] = []


# ═══════════════════════════════════════════════════════════════════
# 图统计模型
# ═══════════════════════════════════════════════════════════════════

class GraphStatsResponse(BaseModel):
    status: str
    time_ms: int = 0
    nodes: int = 0
    edges: int = 0
    density: float = 0.0
    avg_degree: float = 0.0
    max_degree: int = 0
    diameter_approx: int = 0
    components: int = 0


# ═══════════════════════════════════════════════════════════════════
# WebSocket 消息模型
# ═══════════════════════════════════════════════════════════════════

class WSRequest(BaseModel):
    command: str = Field(..., min_length=1)
    args: list[str] = []


class WSResponse(BaseModel):
    status: str  # running / completed / error
    message: str = ""
    data: Optional[dict] = None


# ═══════════════════════════════════════════════════════════════════
# Scenario A — 好友推荐
# ═══════════════════════════════════════════════════════════════════

class FriendRecommendationRequest(BaseModel):
    user_id: str = Field(..., min_length=1, description="目标用户 ID")
    limit: int = Field(10, ge=1, le=100, description="推荐数量上限")


class FriendRecommendationItem(BaseModel):
    id: str
    common_friends: int = 0
    pagerank: float = 0.0
    combined_score: float = 0.0
    explanation: str = ""


class FriendRecommendationResponse(BaseModel):
    status: str
    for_user: str
    recommendations: list[dict] = []
    algorithm: str = ""
    latency_ms: float = 0.0


# ═══════════════════════════════════════════════════════════════════
# Scenario B — 协同过滤
# ═══════════════════════════════════════════════════════════════════

class CollaborativeFilteringRequest(BaseModel):
    user_id: str = Field(..., min_length=1, description="目标用户 ID")
    item_type: Optional[str] = Field(None, description="物品类型过滤: page / product / group")
    limit: int = Field(10, ge=1, le=50, description="推荐数量上限")


class CollaborativeFilteringResponse(BaseModel):
    status: str
    for_user: str
    item_type_filter: Optional[str] = None
    recommendations: list[dict] = []
    algorithm: str = ""
    latency_ms: float = 0.0


# ═══════════════════════════════════════════════════════════════════
# Scenario C — 知识图谱探索
# ═══════════════════════════════════════════════════════════════════

class KnowledgeGraphExploreRequest(BaseModel):
    user_id: str = Field(..., min_length=1, description="起点用户 ID")
    min_shared_interests: int = Field(2, ge=1, le=10, description="最少共享兴趣数")
    max_hops: int = Field(3, ge=1, le=5, description="最大探索跳数")
    limit: int = Field(10, ge=1, le=50, description="返回结果数上限")


class KnowledgeGraphExploreResponse(BaseModel):
    status: str
    for_user: str
    min_shared_interests: int = 2
    discoveries: list[dict] = []
    algorithm: str = ""
    latency_ms: float = 0.0


# ═══════════════════════════════════════════════════════════════════
# 通用请求模型
# ═══════════════════════════════════════════════════════════════════

class EgoNetworkRequest(BaseModel):
    node_id: str = Field(..., min_length=1, description="中心节点 ID")
    depth: int = Field(2, ge=1, le=3, description="查询深度 (1-3)")


class ShortestPathNeo4jRequest(BaseModel):
    from_node: str = Field(..., min_length=1, description="起始节点 ID")
    to_node: str = Field(..., min_length=1, description="目标节点 ID")
    max_depth: int = Field(10, ge=1, le=20, description="最大搜索深度")


class CommunityDensityRequest(BaseModel):
    community_id: str = Field(..., min_length=1, description="社区 ID")


class BatchUpdateRequest(BaseModel):
    updates: list[dict] = Field(..., min_length=1, description="算法结果更新列表")


class SchemaInitResponse(BaseModel):
    status: str
    created: list[str] = []
    skipped: list[str] = []
    errors: list[str] = []
