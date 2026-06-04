"""
SocialGraph Pro — 图计算 REST API 路由 (增强版)

端点:
  GET    /api/v1/graph/all                   — 全网拓扑
  GET    /api/v1/graph/pagerank              — PageRank
  GET    /api/v1/graph/community             — LPA 社区发现
  GET    /api/v1/graph/betweenness           — Betweenness Centrality
  GET    /api/v1/graph/connected_components  — 连通分量
  GET    /api/v1/graph/kcore                 — K-Core 分解
  GET    /api/v1/graph/clustering_coeff      — 聚类系数
  GET    /api/v1/graph/stats                 — 图统计
  POST   /api/v1/graph/shortest_path         — 路径查询

  GET    /api/v1/graph/influencers           — Top 影响力用户 (Q3)
  POST   /api/v1/graph/ego_network           — Ego Network (Q2)
  POST   /api/v1/graph/shortest_path_neo4j   — Neo4j 最短路径 (Q5)
  GET    /api/v1/graph/community_structure   — 社区结构 (Q4)
  GET    /api/v1/graph/community_bridges     — 社区桥接节点 (Q7)
  POST   /api/v1/graph/community_density     — 社区密度分析 (Q8)
  GET    /api/v1/graph/stats_neo4j           — Neo4j 图统计 (Q9)

  POST   /api/v1/graph/recommendations       — 好友推荐 (Scenario A)
  POST   /api/v1/graph/collaborative         — 协同过滤 (Scenario B)
  POST   /api/v1/graph/knowledge-explore     — 知识图谱探索 (Scenario C)

  管理:
  POST   /api/v1/graph/sync_algorithms       — 同步 C++ 结果到 Neo4j
  POST   /api/v1/admin/schema/init           — 初始化 Neo4j Schema
  GET    /api/v1/admin/schema/verify         — 验证索引状态
"""
import logging

from fastapi import APIRouter, Depends, HTTPException

from core.config import get_settings
from core.dependencies import get_current_analyst_or_admin, get_current_admin
from models.graph import (
    PathRequest, PathResponse,
    GraphAllResponse, AlgorithmResultResponse,
    CommunityResponse, ConnectedComponentsResponse,
    GraphStatsResponse, GraphPaginatedResponse,
    FriendRecommendationRequest, FriendRecommendationResponse,
    CollaborativeFilteringRequest, CollaborativeFilteringResponse,
    KnowledgeGraphExploreRequest, KnowledgeGraphExploreResponse,
    EgoNetworkRequest, ShortestPathNeo4jRequest,
    CommunityDensityRequest, SchemaInitResponse,
)
from services.cache import cache_get_or_compute
from services.cpp_engine import execute_command
from services.performance import log_operation

logger = logging.getLogger("socialgraph.routes.graph")

router = APIRouter(prefix="/api/v1/graph", tags=["图计算"])


# ═══════════════════════════════════════════════════════════════════
# 拓扑查询
# ═══════════════════════════════════════════════════════════════════

@router.get("/all", response_model=GraphAllResponse)
async def get_all_graph():
    """获取全网拓扑数据（节点 + 关系）。

    优先从 Redis 缓存返回，缓存未命中时从 Neo4j（回退到 C++ 引擎）加载。
    """
    settings = get_settings()
    return await cache_get_or_compute(
        "social_graph:topology:v7",
        settings.cache_topology_ttl,
        _fetch_topology,
        use_lock=True,
    )


async def _fetch_topology() -> dict:
    """从 Neo4j（或 C++ 引擎）获取全网拓扑的底层函数。"""
    from services.neo4j_service import get_full_topology

    data = await get_full_topology()
    if data.get("status") != "success":
        return {"status": "error", "nodes": [], "links": []}
    return data


@router.get("/all/paginated", response_model=GraphPaginatedResponse)
async def get_graph_paginated(
    page: int = 1,
    page_size: int = 500,
):
    """分页获取全网拓扑 — 解决全量 4MB 一次性加载问题。

    参数:
      page:      页码 (1-based, 默认 1)
      page_size: 每页边数 (默认 500, 最大 2000)

    返回当前页的边及其关联节点, 前端可逐页加载。
    对于 88234 条边, 默认每页 500 条 = 177 页。

    前端用法:
      GET /api/v1/graph/all/paginated?page=1&page_size=500
      → 拿到 total_pages=177
      → 逐页或按需加载后续页
    """
    from services.neo4j_service import get_topology_paginated

    page_size = min(page_size, 2000)
    return await get_topology_paginated(page=page, page_size=page_size)


# ═══════════════════════════════════════════════════════════════════
# 算法端点 (GET — 无参数)
# ═══════════════════════════════════════════════════════════════════

@router.get("/pagerank", response_model=AlgorithmResultResponse)
async def get_pagerank(
    current_user: dict = Depends(get_current_analyst_or_admin),
):
    """PageRank 中心性分析。

    需要 analyst 或以上角色。
    """
    settings = get_settings()
    result = await cache_get_or_compute(
        "social_graph:pagerank:v3",
        settings.cache_algorithm_ttl,
        execute_command, "pagerank",
    )
    log_operation("run_algorithm", current_user["user_id"], "pagerank")
    return result


@router.get("/community", response_model=CommunityResponse)
async def get_community(
    current_user: dict = Depends(get_current_analyst_or_admin),
):
    """LPA (Label Propagation) 社区发现。

    需要 analyst 或以上角色。
    """
    settings = get_settings()
    result = await cache_get_or_compute(
        "social_graph:community:v3",
        settings.cache_algorithm_ttl,
        execute_command, "community",
    )
    log_operation("run_algorithm", current_user["user_id"], "community")
    return result


@router.get("/betweenness", response_model=AlgorithmResultResponse)
async def get_betweenness(
    current_user: dict = Depends(get_current_analyst_or_admin),
):
    """介数中心性 (Betweenness Centrality)。

    需要 analyst 或以上角色。
    """
    settings = get_settings()
    result = await cache_get_or_compute(
        "social_graph:betweenness:v1",
        settings.cache_algorithm_ttl,
        execute_command, "betweenness",
    )
    log_operation("run_algorithm", current_user["user_id"], "betweenness")
    return result


@router.get("/connected_components", response_model=ConnectedComponentsResponse)
async def get_connected_components(
    current_user: dict = Depends(get_current_analyst_or_admin),
):
    """连通分量分析。

    需要 analyst 或以上角色。
    """
    settings = get_settings()
    result = await cache_get_or_compute(
        "social_graph:connected_components:v1",
        settings.cache_algorithm_ttl,
        execute_command, "connected_components",
    )
    log_operation("run_algorithm", current_user["user_id"], "connected_components")
    return result


@router.get("/kcore", response_model=AlgorithmResultResponse)
async def get_kcore(
    current_user: dict = Depends(get_current_analyst_or_admin),
):
    """K-Core 图分解。

    需要 analyst 或以上角色。
    """
    settings = get_settings()
    result = await cache_get_or_compute(
        "social_graph:kcore:v1",
        settings.cache_algorithm_ttl,
        execute_command, "kcore",
    )
    log_operation("run_algorithm", current_user["user_id"], "kcore")
    return result


@router.get("/clustering_coeff", response_model=AlgorithmResultResponse)
async def get_clustering_coeff(
    current_user: dict = Depends(get_current_analyst_or_admin),
):
    """聚类系数分析。

    需要 analyst 或以上角色。
    """
    settings = get_settings()
    result = await cache_get_or_compute(
        "social_graph:clustering:v1",
        settings.cache_algorithm_ttl,
        execute_command, "clustering_coeff",
    )
    log_operation("run_algorithm", current_user["user_id"], "clustering_coeff")
    return result


@router.get("/stats", response_model=GraphStatsResponse)
async def get_graph_stats():
    """获取图统计信息（节点数、边数、密度、平均度等）。

    公开端点，不需要认证（但有速率限制）。
    """
    settings = get_settings()
    return await cache_get_or_compute(
        "social_graph:stats:v1",
        settings.cache_stats_ttl,
        execute_command, "graph_stats",
    )


# ═══════════════════════════════════════════════════════════════════
# 路径查询 (POST — 有参数)
# ═══════════════════════════════════════════════════════════════════

@router.post("/shortest_path", response_model=PathResponse)
async def get_shortest_path(
    req: PathRequest,
    current_user: dict = Depends(get_current_analyst_or_admin),
):
    """路径查询: BFS 最短路径 / Dijkstra 最优路径 / DFS 回声室探测。

    需要 analyst 或以上角色。
    """
    if req.algorithm == "dfs":
        logger.info("DFS 回声室探测: start=%s", req.start_node)
        data = await execute_command("echo_chamber", str(req.start_node))
        command = "echo_chamber"
    elif req.algorithm == "dijkstra":
        logger.info("Dijkstra 寻路: %s -> %s", req.start_node, req.target_node)
        data = await execute_command("dijkstra_path", str(req.start_node), str(req.target_node))
        command = "dijkstra_path"
    else:
        logger.info("BFS 寻路: %s -> %s", req.start_node, req.target_node)
        data = await execute_command("shortest_path", str(req.start_node), str(req.target_node))
        command = "shortest_path"

    # 统一 path 字段为字符串列表
    if data.get("status") == "success" and "path" in data:
        data["path"] = [str(node) for node in data["path"]]
        data["path_length"] = len(data["path"])

    log_operation("run_algorithm", current_user["user_id"], command)
    return data


# ═══════════════════════════════════════════════════════════════════
# Neo4j 原生查询端点 (Q2-Q9, 无需 C++ 引擎)
# ═══════════════════════════════════════════════════════════════════

@router.get("/influencers")
async def get_influencers(
    limit: int = 20,
    current_user: dict = Depends(get_current_analyst_or_admin),
):
    """获取 PageRank 最高的 Top-K 影响者 (Q3)。

    利用 Neo4j 内建索引排序，无需 C++ 引擎。
    需要 analyst 或以上角色。
    """
    from services.neo4j_service import get_top_influencers

    result = await get_top_influencers(limit=limit)
    log_operation("query_neo4j", current_user["user_id"], "top_influencers")
    return result


@router.post("/ego_network")
async def get_ego_network(
    req: EgoNetworkRequest,
    current_user: dict = Depends(get_current_analyst_or_admin),
):
    """获取指定节点的 K 跳邻居子图 (Q2)。

    需要 analyst 或以上角色。
    """
    from services.neo4j_service import get_node_neighbors

    result = await get_node_neighbors(
        node_id=req.node_id,
        depth=req.depth,
        include_internal_edges=True,
    )
    log_operation("query_neo4j", current_user["user_id"], f"ego_network_{req.depth}hop")
    return result


@router.post("/shortest_path_neo4j")
async def get_shortest_path_neo4j(
    req: ShortestPathNeo4jRequest,
    current_user: dict = Depends(get_current_analyst_or_admin),
):
    """使用 Neo4j 内建 shortestPath 计算最短路径 (Q5)。

    相比 C++ 引擎的优势: 无需子进程启动开销，利用图原生存储。
    需要 analyst 或以上角色。
    """
    from services.neo4j_service import get_shortest_path_neo4j

    result = await get_shortest_path_neo4j(
        from_node=req.from_node,
        to_node=req.to_node,
        max_depth=req.max_depth,
    )
    log_operation("query_neo4j", current_user["user_id"], "shortest_path_neo4j")
    return result


@router.get("/community_structure")
async def get_community_structure(
    min_size: int = 2,
    current_user: dict = Depends(get_current_analyst_or_admin),
):
    """获取社区结构概览 (Q4)。

    返回每个社区的成员数和样本成员。
    需要 analyst 或以上角色。
    """
    from services.neo4j_service import get_community_structure

    result = await get_community_structure(min_size=min_size)
    log_operation("query_neo4j", current_user["user_id"], "community_structure")
    return result


@router.get("/community_bridges")
async def get_community_bridges(
    limit: int = 20,
    current_user: dict = Depends(get_current_analyst_or_admin),
):
    """检测社区桥接节点 (Q7)。

    找出连接不同社区的高介数中心性节点。
    需要 analyst 或以上角色。
    """
    from services.neo4j_service import get_community_bridges

    result = await get_community_bridges(limit=limit)
    log_operation("query_neo4j", current_user["user_id"], "community_bridges")
    return result


@router.post("/community_density")
async def get_community_density(
    req: CommunityDensityRequest,
    current_user: dict = Depends(get_current_analyst_or_admin),
):
    """计算指定社区的内部密度 (Q8)。

    需要 analyst 或以上角色。
    """
    from services.neo4j_service import get_community_density

    result = await get_community_density(community_id=req.community_id)
    log_operation("query_neo4j", current_user["user_id"], f"density_{req.community_id}")
    return result


@router.get("/stats_neo4j")
async def get_graph_stats_neo4j(
    current_user: dict = Depends(get_current_analyst_or_admin),
):
    """从 Neo4j 直接查询全图统计信息 (Q9)。

    补充 C++ graph_stats 端点，提供更丰富的百分位数指标。
    需要 analyst 或以上角色。
    """
    from services.neo4j_service import get_graph_statistics_neo4j

    result = await get_graph_statistics_neo4j()
    log_operation("query_neo4j", current_user["user_id"], "stats_neo4j")
    return result


# ═══════════════════════════════════════════════════════════════════
# Scenario A — 好友推荐
# ═══════════════════════════════════════════════════════════════════

@router.post("/recommendations", response_model=FriendRecommendationResponse)
async def get_friend_recommendations(
    req: FriendRecommendationRequest,
    current_user: dict = Depends(get_current_analyst_or_admin),
):
    """社交网络好友推荐 (Scenario A)。

    混合算法: Neo4j 共同邻居 + C++ PageRank 加权。
    需要 analyst 或以上角色。

    请求: {"user_id": "42", "limit": 10}
    响应: 包含推荐用户列表, 含共同好友数 + PageRank + 综合得分 + 解释
    """
    from services.neo4j_service import scenario_a_friend_recommendation

    result = await scenario_a_friend_recommendation(
        user_id=req.user_id,
        limit=req.limit,
    )
    log_operation("recommendation", current_user["user_id"], "friend_recommendation")
    return result


# ═══════════════════════════════════════════════════════════════════
# Scenario B — 协同过滤
# ═══════════════════════════════════════════════════════════════════

@router.post("/collaborative", response_model=CollaborativeFilteringResponse)
async def get_collaborative_recommendations(
    req: CollaborativeFilteringRequest,
    current_user: dict = Depends(get_current_analyst_or_admin),
):
    """协同过滤推荐 (Scenario B)。

    图模型: (:User)-[:LIKES/:VIEWED/:PURCHASED]->(:Item)
    算法: "喜欢 X 的用户也喜欢 Y", 以 PageRank 加权。
    需要 analyst 或以上角色。

    请求: {"user_id": "42", "item_type": "page", "limit": 10}
    响应: 包含推荐物品列表, 含相似用户数 + 评分 + 解释
    """
    from services.neo4j_service import scenario_b_collaborative_filtering

    result = await scenario_b_collaborative_filtering(
        user_id=req.user_id,
        item_type=req.item_type,
        limit=req.limit,
    )
    log_operation("recommendation", current_user["user_id"], "collaborative")
    return result


# ═══════════════════════════════════════════════════════════════════
# Scenario C — 知识图谱探索
# ═══════════════════════════════════════════════════════════════════

@router.post("/knowledge-explore", response_model=KnowledgeGraphExploreResponse)
async def explore_knowledge_graph(
    req: KnowledgeGraphExploreRequest,
    current_user: dict = Depends(get_current_analyst_or_admin),
):
    """知识图谱多跳探索 (Scenario C)。

    图模型: (:User)-[:HAS_ATTRIBUTE]->(:Attribute)-[:RELATED_TO]-(:Attribute)
    查询: "找到和我朋友至少共享 N 个兴趣的人"
    需要 analyst 或以上角色。

    请求: {"user_id": "42", "min_shared_interests": 2, "max_hops": 3, "limit": 10}
    响应: 包含发现用户列表, 含共享兴趣 + 推理路径 + 解释
    """
    from services.neo4j_service import scenario_c_knowledge_graph_explore

    result = await scenario_c_knowledge_graph_explore(
        user_id=req.user_id,
        min_shared_interests=req.min_shared_interests,
        max_hops=req.max_hops,
        limit=req.limit,
    )
    log_operation("recommendation", current_user["user_id"], "knowledge_explore")
    return result


# ═══════════════════════════════════════════════════════════════════
# 管理端点 — Schema 初始化 & 算法同步
# ═══════════════════════════════════════════════════════════════════

@router.post("/sync_algorithms")
async def sync_algorithm_results(
    current_user: dict = Depends(get_current_admin),
):
    """一键同步 C++ 所有算法结果到 Neo4j (Q10)。

    执行: pagerank + betweenness + kcore + clustering_coeff + community
    然后批量写入 Neo4j，创建 Community 节点和 BELONGS_TO 关系。
    需要 admin 角色。
    """
    from services.neo4j_service import sync_all_algorithm_results

    result = await sync_all_algorithm_results()
    log_operation("admin_action", current_user["user_id"], "sync_algorithms")
    return result


# Schema 管理端点注册在 admin 路由上
# 在 routes/admin.py 中添加或在 init 中注册
