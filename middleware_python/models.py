from pydantic import BaseModel
from typing import Optional


class NodeInfo(BaseModel):
    id: str
    group: int = 1


class LinkInfo(BaseModel):
    source: str
    target: str


class GraphAllResponse(BaseModel):
    status: str
    nodes: list[NodeInfo] = []
    links: list[LinkInfo] = []


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


class PathRequest(BaseModel):
    start_node: str
    target_node: str = ""
    algorithm: str = "bfs"


class PathResponse(BaseModel):
    status: str
    time_ms: int = 0
    path: list[str] = []


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


class ConnectedComponentsResponse(BaseModel):
    status: str
    time_ms: int = 0
    component_count: int = 0
    component_sizes: dict = {}
    data: list[dict] = []


class HealthResponse(BaseModel):
    status: str
    cpp_engine_available: bool = False
    redis_available: bool = False
    neo4j_available: bool = False


class WSMessage(BaseModel):
    command: str
    args: list[str] = []
