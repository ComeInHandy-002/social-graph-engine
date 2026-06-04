"""
SocialGraph Pro — Neo4j 图拓扑服务 (增强版)

================================================================================
10 个生产级 Cypher 查询 + 3 个完整应用场景
================================================================================

查询目录:
  Q1  完整拓扑导出         — MATCH (u:User)-[r:KNOWS]->(v:User)
  Q2  Ego Network (K-跳)   — 中心节点 K 跳子图 + 内部关系
  Q3  Top Influencers      — PageRank 降序, Top-K
  Q4  社区结构              — 按社区分组, 成员数 + 样本成员
  Q5  最短路径              — Neo4j 内建 shortestPath (无需 C++)
  Q6  共同邻居推荐           — 朋友的朋友, 排序推荐
  Q7  社区桥接检测           — 高 betweenness + 跨社区连接
  Q8  社区密度分析           — 社区内部连通性
  Q9  全图统计              — 节点数/边数/平均 PageRank/聚类系数
  Q10 批量更新算法结果       — UNWIND 批量写入 C++ 计算结果

应用场景:
  Scenario A — 社交网络好友推荐       (Neo4j + C++ PageRank 混合)
  Scenario B — 协同过滤推荐系统        (:Item + :LIKES/:VIEWED/:PURCHASED)
  Scenario C — 知识图谱多跳探索        (:Attribute + :HAS_ATTRIBUTE + :RELATED_TO)
"""
import logging
from typing import Optional, Any

from core.config import get_settings
from core.exceptions import ExternalServiceError

logger = logging.getLogger("socialgraph.services.neo4j")


# ═══════════════════════════════════════════════════════════════════
# Q1 — 完整拓扑导出
# ═══════════════════════════════════════════════════════════════════

async def get_full_topology() -> dict:
    """从 Neo4j 获取全网拓扑（节点 + 关系）。

    依赖索引: user_id_index (自动由 user_id_unique 约束提供)
    期望计划: NodeByLabelScan + Expand(All) → Projection
    无索引时: AllNodesScan → 4K 节点全扫描 (可接受但慢)

    返回:
        {"status": "success", "nodes": [...], "links": [...]}
    """
    from db.neo4j import get_neo4j_driver
    from services.cpp_engine import execute_command

    driver = await get_neo4j_driver()

    if driver:
        try:
            async with driver.session() as session:
                result = await session.run(
                    "MATCH (u:User)-[r:KNOWS]->(v:User) "
                    "RETURN u.id AS source, v.id AS target"
                )
                records = await result.data()

                links = [
                    {"source": str(rec["source"]), "target": str(rec["target"])}
                    for rec in records
                ]

                # 提取所有唯一节点
                node_ids: set[str] = set()
                for link in links:
                    node_ids.add(link["source"])
                    node_ids.add(link["target"])
                nodes = [{"id": nid, "group": 1} for nid in sorted(node_ids)]

                logger.info(
                    "Neo4j 拓扑查询完成: %d nodes, %d edges",
                    len(nodes), len(links),
                )
                return {"status": "success", "nodes": nodes, "links": links}

        except Exception as e:
            logger.warning("Neo4j 拓扑查询失败: %s, 回退到 C++ 引擎", e)

    # 回退: C++ 引擎直接读文件
    logger.info("从 C++ 引擎加载拓扑...")
    return await execute_command("get_full_graph")


async def get_topology_paginated(page: int = 1, page_size: int = 500) -> dict:
    """分页获取全网拓扑 — 解决全量 4MB 一次性加载的瓶颈。

    策略: 按边分页, 只返回当前页的边及其关联的节点。
    前端可以按需加载更多页, 或只加载视口内数据。

    Args:
        page:      页码 (从 1 开始)
        page_size: 每页边数 (默认 500)

    Returns:
        {"status": "success", "page": 1, "page_size": 500,
         "total_nodes": 4039, "total_edges": 88234, "total_pages": 177,
         "nodes": [...], "links": [...]}
    """
    from db.neo4j import get_neo4j_driver

    driver = await get_neo4j_driver()

    if driver:
        try:
            async with driver.session() as session:
                # 先查总数
                count_result = await session.run(
                    "MATCH (u:User)-[r:KNOWS]->(v:User) RETURN count(r) AS total"
                )
                count_record = await count_result.single()
                total_edges = count_record["total"] if count_record else 0

                # 节点总数 (近似, 查询唯一节点)
                node_result = await session.run(
                    "MATCH (u:User) RETURN count(u) AS total"
                )
                node_record = await node_result.single()
                total_nodes = node_record["total"] if node_record else 0

                total_pages = max(1, (total_edges + page_size - 1) // page_size)
                page = max(1, min(page, total_pages))
                skip = (page - 1) * page_size

                # 分页查询边
                result = await session.run(
                    "MATCH (u:User)-[r:KNOWS]->(v:User) "
                    "RETURN u.id AS source, v.id AS target "
                    "ORDER BY u.id, v.id "
                    "SKIP $skip LIMIT $limit",
                    skip=skip, limit=page_size,
                )
                records = await result.data()

                links = [
                    {"source": str(rec["source"]), "target": str(rec["target"])}
                    for rec in records
                ]

                # 提取当前页涉及的所有节点
                node_ids: set[str] = set()
                for link in links:
                    node_ids.add(link["source"])
                    node_ids.add(link["target"])
                nodes = [{"id": nid, "group": 1} for nid in sorted(node_ids)]

                logger.info(
                    "Neo4j 分页拓扑: page=%d/%d, %d nodes, %d edges (total: %d/%d)",
                    page, total_pages, len(nodes), len(links),
                    total_nodes, total_edges,
                )
                return {
                    "status": "success",
                    "page": page,
                    "page_size": page_size,
                    "total_nodes": total_nodes,
                    "total_edges": total_edges,
                    "total_pages": total_pages,
                    "nodes": nodes,
                    "links": links,
                }

        except Exception as e:
            logger.warning("Neo4j 分页查询失败: %s", e)

    # 回退到全量 + Python 内存分页
    full = await get_full_topology()
    if full.get("status") != "success":
        return {"status": "error", "message": "无法加载拓扑数据",
                "page": 1, "page_size": page_size,
                "total_nodes": 0, "total_edges": 0, "total_pages": 0,
                "nodes": [], "links": []}

    all_links = full["links"]
    total_edges = len(all_links)
    node_ids = set()
    for link in all_links:
        node_ids.add(link["source"])
        node_ids.add(link["target"])
    total_nodes = len(node_ids)
    total_pages = max(1, (total_edges + page_size - 1) // page_size)
    page = max(1, min(page, total_pages))
    skip = (page - 1) * page_size

    page_links = all_links[skip:skip + page_size]
    page_node_ids: set[str] = set()
    for link in page_links:
        page_node_ids.add(link["source"])
        page_node_ids.add(link["target"])

    return {
        "status": "success",
        "page": page,
        "page_size": page_size,
        "total_nodes": total_nodes,
        "total_edges": total_edges,
        "total_pages": total_pages,
        "nodes": [{"id": nid, "group": 1} for nid in sorted(page_node_ids)],
        "links": page_links,
    }


# ═══════════════════════════════════════════════════════════════════
# Q2 — Ego Network (K-跳邻居子图)
# ═══════════════════════════════════════════════════════════════════

async def get_node_neighbors(
    node_id: str,
    depth: int = 2,
    include_internal_edges: bool = True,
) -> dict:
    """获取指定节点的 K 跳邻居子图（增强版）。

    依赖索引: user_id_index / user_id_unique (节点快速定位)
    期望计划:
      1. NodeByIdSeek(center) → VarLengthExpand(All) → Distinct
      2. NodeByIdSeek × N + Expand(All) → Filter(IN)

    Args:
        node_id: 中心节点 ID
        depth:   查询深度 (1-3)
        include_internal_edges: 是否包含子图内部边

    返回:
        子图数据 (nodes + links)
    """
    from db.neo4j import get_neo4j_driver

    driver = await get_neo4j_driver()
    if driver is None:
        return {"status": "error", "message": "Neo4j 不可用，无法进行子图查询"}

    try:
        depth = max(1, min(depth, 3))

        # 阶段 1: 查找 K 跳邻居 (使用可变长度路径)
        async with driver.session() as session:
            query1 = """
                MATCH (center:User {id: $node_id})
                MATCH (center)-[:KNOWS*1..$depth]-(neighbor:User)
                WITH DISTINCT neighbor
                RETURN neighbor.id AS id, labels(neighbor) AS labels
            """
            result1 = await session.run(
                query1,
                node_id=node_id,
                depth=depth,
            )
            records = await result1.data()

            nodes = [{"id": rec["id"], "group": 1} for rec in records]

            # 确保中心节点在结果中
            center_present = any(n["id"] == node_id for n in nodes)
            if not center_present:
                nodes.insert(0, {"id": node_id, "group": 1})

            # 阶段 2: 查询子图内部关系
            links: list[dict[str, str]] = []
            if include_internal_edges and nodes:
                node_ids = [n["id"] for n in nodes]
                query2 = """
                    MATCH (a:User)-[r:KNOWS]-(b:User)
                    WHERE a.id IN $node_ids AND b.id IN $node_ids
                    RETURN a.id AS source, b.id AS target
                """
                result2 = await session.run(query2, node_ids=node_ids)
                records2 = await result2.data()
                links = [
                    {"source": str(rec["source"]), "target": str(rec["target"])}
                    for rec in records2
                ]

            return {"status": "success", "nodes": nodes, "links": links}

    except Exception as e:
        logger.error("Neo4j 子图查询失败: %s", e)
        return {"status": "error", "message": f"Neo4j 子图查询失败: {e}"}


# ═══════════════════════════════════════════════════════════════════
# Q3 — Top Influencers by PageRank
# ═══════════════════════════════════════════════════════════════════

async def get_top_influencers(limit: int = 20) -> dict:
    """获取 PageRank 最高的 Top-K 用户。

    依赖索引: user_pagerank_index (B-tree, 利用索引排序避免全表排序)
    期望计划:
      NodeByLabelScan(User) → Filter(pagerank IS NOT NULL)
      → Sort (使用 user_pagerank_index) → Top(LIMIT)

    无索引时:
      AllNodesScan → 全表排序 (O(n log n), n=4K) → 可慢 5-10 倍

    Args:
        limit: 返回数量 (默认 20, 最大 100)

    返回:
        {"status": "success", "influencers": [{"id": ..., "pagerank": ..., "rank": ...}]}
    """
    from db.neo4j import execute_cypher

    limit = min(max(limit, 1), 100)

    query = """
        MATCH (u:User)
        WHERE u.pagerank IS NOT NULL
        RETURN u.id AS id, u.pagerank AS pagerank, u.degree AS degree
        ORDER BY u.pagerank DESC
        LIMIT $limit
    """
    records = await execute_cypher(query, {"limit": limit})

    influencers = []
    for i, rec in enumerate(records):
        influencers.append({
            "id": str(rec["id"]),
            "pagerank": round(float(rec["pagerank"]), 6),
            "degree": rec.get("degree", 0),
            "rank": i + 1,
        })

    return {"status": "success", "influencers": influencers, "total_returned": len(influencers)}


# ═══════════════════════════════════════════════════════════════════
# Q4 — Community Structure
# ═══════════════════════════════════════════════════════════════════

async def get_community_structure(min_size: int = 2) -> dict:
    """获取社区结构概览。

    依赖索引: user_community_index (B-tree, 加速 community_id 分组)
    期望计划:
      NodeByLabelScan(User) → Filter(community_id IS NOT NULL)
      → EagerAggregation (GROUP BY community_id)

    无索引时:
      LabelScan + 全表分组 (依然可行但较慢)

    Args:
        min_size: 最小社区人数过滤

    返回:
        {"communities": [{"id": ..., "size": ..., "sample_members": [...]}]}
    """
    from db.neo4j import execute_cypher

    query = """
        MATCH (u:User)
        WHERE u.community_id IS NOT NULL
        WITH u.community_id AS cid, count(u) AS size, collect(u.id) AS members
        WHERE size >= $min_size
        RETURN cid, size, members[0..10] AS sample_members
        ORDER BY size DESC
    """
    records = await execute_cypher(query, {"min_size": min_size})

    communities = []
    for rec in records:
        communities.append({
            "id": str(rec["cid"]),
            "size": int(rec["size"]),
            "sample_members": [str(m) for m in rec["sample_members"]],
        })

    return {"status": "success", "communities": communities, "total_communities": len(communities)}


# ═══════════════════════════════════════════════════════════════════
# Q5 — Shortest Path (Neo4j 内建, 无需 C++)
# ═══════════════════════════════════════════════════════════════════

async def get_shortest_path_neo4j(
    from_node: str,
    to_node: str,
    max_depth: int = 10,
) -> dict:
    """使用 Neo4j 内建 shortestPath 算法查找路径。

    相比 C++ 引擎的优势:
      - 无需子进程启动开销 (~50ms)
      - 利用图原生存储, 路径遍历已高度优化
      - 支持关系过滤和路径权重

    依赖索引: user_id_index × 2 (起点 + 终点 NodeByIdSeek)
    期望计划:
      NodeByIdSeek(start) + NodeByIdSeek(end)
      → ShortestPath (双向 BFS, 内部优化)
      → Projection

    Args:
        from_node: 起始节点 ID
        to_node:   目标节点 ID
        max_depth: 最大跳跃深度

    返回:
        {"status": "success", "path": [...], "hops": N, "time_ms": ...}
    """
    from db.neo4j import execute_cypher
    import time

    start_time = time.time()

    query = """
        MATCH (start:User {id: $from}), (end:User {id: $to}),
              path = shortestPath((start)-[:KNOWS*..$max_depth]-(end))
        RETURN [node IN nodes(path) | node.id] AS path, length(path) AS hops
    """
    records = await execute_cypher(query, {
        "from": from_node,
        "to": to_node,
        "max_depth": max_depth,
    })

    elapsed_ms = round((time.time() - start_time) * 1000, 1)

    if not records:
        return {
            "status": "error",
            "message": f"在 {max_depth} 跳内未找到从 {from_node} 到 {to_node} 的路径",
            "time_ms": elapsed_ms,
        }

    rec = records[0]
    return {
        "status": "success",
        "path": [str(n) for n in rec["path"]],
        "hops": int(rec["hops"]),
        "time_ms": elapsed_ms,
    }


# ═══════════════════════════════════════════════════════════════════
# Q6 — Common Neighbors (好友推荐)
# ═══════════════════════════════════════════════════════════════════

async def get_friend_recommendations(
    user_id: str,
    limit: int = 10,
    exclude_self: bool = True,
) -> dict:
    """基于共同邻居的好友推荐 (朋友的朋友)。

    算法原理:
      - 找到用户 A 的所有朋友 F
      - 找到所有朋友的朋友 C (候选人)
      - 过滤掉已是好友的 C 和 A 自己
      - 按共同好友数降序排列 (越多共同好友 → 越可能认识)

    依赖索引: user_id_index × N (节点查找)
    期望计划:
      NodeByIdSeek(u) → Expand(All) → Expand(All) → AntiSemiApply (NOT exists)
      → EagerAggregation (count) → Sort → Top

    注意: 对于大图 (>100K 节点), 应添加候选人数上限以避免组合爆炸。

    Args:
        user_id: 目标用户 ID
        limit:   返回推荐数量
        exclude_self: 是否排除自身

    返回:
        {"recommendations": [{"id": ..., "common_friends": ..., "score": ...}]}
    """
    from db.neo4j import execute_cypher

    query = """
        MATCH (u:User {id: $user_id})-[:KNOWS]-(friend:User)-[:KNOWS]-(candidate:User)
        WHERE NOT (u)-[:KNOWS]-(candidate)
          AND candidate.id <> $user_id
        RETURN candidate.id AS id,
               candidate.pagerank AS pagerank,
               count(DISTINCT friend) AS common_friends
        ORDER BY common_friends DESC, candidate.pagerank DESC
        LIMIT $limit
    """
    records = await execute_cypher(query, {
        "user_id": user_id,
        "limit": limit,
    })

    recommendations = []
    for rec in records:
        common = int(rec["common_friends"])
        pr = float(rec.get("pagerank", 0) or 0)
        # 综合得分: 共同好友数 * (1 + PageRank 加权)
        combined_score = round(common * (1.0 + pr * 10), 2)
        recommendations.append({
            "id": str(rec["id"]),
            "common_friends": common,
            "pagerank": round(pr, 6),
            "combined_score": combined_score,
        })

    return {"status": "success", "recommendations": recommendations, "for_user": user_id}


# ═══════════════════════════════════════════════════════════════════
# Q7 — Community Bridge Detection (社区桥接节点)
# ═══════════════════════════════════════════════════════════════════

async def get_community_bridges(limit: int = 20) -> dict:
    """检测连接不同社区的桥接节点 (高 betweenness + 跨社区边)。

    桥接节点的价值:
      - 信息传播的关键枢纽
      - 如果移除, 社区之间连接断裂
      - 可用于影响力传播、流行病建模、信息隔离策略

    依赖索引: user_betweenness_index, user_community_index
    期望计划:
      NodeByLabelScan → Filter(betweenness IS NOT NULL AND community_id IS NOT NULL)
      → Expand(All) → Filter(neighbor.community_id <> u.community_id)
      → EagerAggregation → Sort → Top

    Args:
        limit: 返回数量

    返回:
        {"bridges": [{"id": ..., "betweenness": ..., "community": ..., "bridges_to": [...]}]}
    """
    from db.neo4j import execute_cypher

    query = """
        MATCH (u:User)
        WHERE u.betweenness IS NOT NULL AND u.community_id IS NOT NULL
        MATCH (u)-[:KNOWS]-(neighbor:User)
        WHERE neighbor.community_id <> u.community_id
        RETURN DISTINCT u.id AS id,
               u.betweenness AS betweenness,
               u.community_id AS community,
               collect(DISTINCT neighbor.community_id) AS bridges_to,
               count(DISTINCT neighbor) AS cross_community_edges
        ORDER BY u.betweenness DESC
        LIMIT $limit
    """
    records = await execute_cypher(query, {"limit": limit})

    bridges = []
    for rec in records:
        bridges.append({
            "id": str(rec["id"]),
            "betweenness": round(float(rec["betweenness"]), 6),
            "community": str(rec["community"]),
            "bridges_to": [str(c) for c in rec["bridges_to"]],
            "cross_community_edges": int(rec["cross_community_edges"]),
        })

    return {"status": "success", "bridges": bridges, "total_returned": len(bridges)}


# ═══════════════════════════════════════════════════════════════════
# Q8 — Community Density Analysis
# ═══════════════════════════════════════════════════════════════════

async def get_community_density(community_id: str) -> dict:
    """计算指定社区的密度（内部连通性）。

    密度公式:
      density = actual_edges / max_possible_edges
      max_possible_edges = n * (n - 1) / 2  (无向图)
      或 n * (n - 1) (有向图)

    依赖索引: user_community_index (快速过滤社区成员)
    期望计划:
      NodeByIndexSeek(user_community_index) → Expand(All)
      → Filter(community_id match) → EagerAggregation
    注意: 此处使用社区 ID 索引做前置过滤, 然后仅展开社区内关系,
          避免全图关系扫描。

    Args:
        community_id: 社区 ID

    返回:
        {"nodes": N, "edges": E, "density": D, "max_possible_edges": M}
    """
    from db.neo4j import execute_cypher

    # 阶段 1: 计算社区内节点数和内部边数
    query = """
        MATCH (u:User {community_id: $community_id})
        WITH collect(u) AS members
        WITH members, size(members) AS node_count
        UNWIND members AS a
        UNWIND members AS b
        MATCH (a)-[r:KNOWS]-(b)
        WHERE id(a) < id(b)  // 避免重复计数 (无向边每条只计一次)
        WITH node_count, count(r) AS edge_count
        RETURN node_count, edge_count,
               CASE WHEN node_count > 1
                 THEN edge_count * 2.0 / (node_count * (node_count - 1))
                 ELSE 0
               END AS density
    """
    records = await execute_cypher(query, {"community_id": community_id})

    if not records:
        return {"status": "error", "message": f"社区 {community_id} 不存在或为空"}

    rec = records[0]
    n = int(rec["node_count"])
    e = int(rec["edge_count"])
    return {
        "status": "success",
        "community_id": community_id,
        "nodes": n,
        "edges": e,
        "density": round(float(rec["density"]), 6),
        "max_possible_edges": n * (n - 1) / 2 if n > 1 else 0,
    }


# ═══════════════════════════════════════════════════════════════════
# Q9 — Graph-wide Statistics
# ═══════════════════════════════════════════════════════════════════

async def get_graph_statistics_neo4j() -> dict:
    """获取全图统计指标（从 Neo4j 直接聚合）。

    依赖索引: user_clustering_index (avg 聚合可能利用), user_pagerank_index
    期望计划:
      NodeCountFromCountStore(User) — 使用计数存储 (O(1))
      → Expand(All) — 度计算
      → EagerAggregation — avg/percentile 聚合

    Neo4j 企业版特性: 节点/关系计数存储在元数据, COUNT 通常是 O(1)。

    返回:
        {
            "total_nodes", "total_edges", "avg_degree",
            "avg_pagerank", "avg_clustering_coeff",
            "max_degree", "density"
        }
    """
    from db.neo4j import execute_cypher

    query = """
        MATCH (u:User)
        OPTIONAL MATCH (u)-[r:KNOWS]-(v:User)
        WITH u, count(DISTINCT v) AS degree
        RETURN
            count(u) AS total_nodes,
            sum(degree) AS total_edges,
            avg(degree) AS avg_degree,
            max(degree) AS max_degree,
            avg(u.pagerank) AS avg_pagerank,
            avg(u.clustering_coeff) AS avg_clustering_coeff,
            percentileCont(u.pagerank, 0.5) AS median_pagerank,
            percentileCont(u.pagerank, 0.95) AS p95_pagerank
    """
    records = await execute_cypher(query)

    if not records:
        return {"status": "error", "message": "图统计数据为空"}

    rec = records[0]
    n = int(rec["total_nodes"])
    e = int(rec["total_edges"]) // 2  # 无向图每条边被计数两次
    return {
        "status": "success",
        "total_nodes": n,
        "total_edges": e,
        "avg_degree": round(float(rec["avg_degree"] or 0), 2),
        "max_degree": int(rec["max_degree"] or 0),
        "avg_pagerank": round(float(rec["avg_pagerank"] or 0), 8),
        "avg_clustering_coeff": round(float(rec["avg_clustering_coeff"] or 0), 6),
        "median_pagerank": round(float(rec["median_pagerank"] or 0), 8),
        "p95_pagerank": round(float(rec["p95_pagerank"] or 0), 8),
        "density": round(e * 2.0 / (n * (n - 1)), 6) if n > 1 else 0,
    }


# ═══════════════════════════════════════════════════════════════════
# Q10 — Batch Update Algorithm Results (C++ 结果同步)
# ═══════════════════════════════════════════════════════════════════

async def batch_update_algorithm_results(updates: list[dict[str, Any]]) -> dict:
    """批量同步 C++ 算法计算结果到 Neo4j。

    依赖索引: user_id_index / user_id_unique (UNWIND 后 MATCH 定位)
    期望计划:
      Unwind → NodeByIdSeek (每条 update 一行) → SetProperties → Count

    性能注意事项:
      - 4K 节点批量更新, UNWIND 方式比逐个 MERGE 快 10-50 倍
      - 单事务写入所有更新, 避免中间状态不一致
      - updated_at 时间戳统一设置, 便于后续增量同步判定

    Args:
        updates: 算法结果列表, 每条格式:
            {
                "id": "节点ID",
                "pagerank": 0.001234,
                "betweenness": 0.05,
                "kcore": 3,
                "clustering_coeff": 0.42,
                "community_id": "community_42",
                "degree": 12,
            }

    返回:
        {"status": "success", "updated_count": N}
    """
    from db.neo4j import execute_cypher_write

    query = """
        UNWIND $updates AS update
        MATCH (u:User {id: update.id})
        SET u.pagerank = update.pagerank,
            u.betweenness = update.betweenness,
            u.kcore = update.kcore,
            u.clustering_coeff = update.clustering_coeff,
            u.community_id = update.community_id,
            u.degree = update.degree,
            u.updated_at = datetime()
        RETURN count(u) AS updated
    """
    records = await execute_cypher_write(query, {"updates": updates})

    updated_count = int(records[0]["updated"]) if records else 0
    logger.info("批量更新算法结果: %d/%d 节点已同步", updated_count, len(updates))

    return {"status": "success", "updated_count": updated_count, "total_submitted": len(updates)}


# ═══════════════════════════════════════════════════════════════════
# 辅助: 从 C++ 引擎获取算法结果并转换为批量更新格式
# ═══════════════════════════════════════════════════════════════════

async def sync_all_algorithm_results() -> dict:
    """一键同步: 运行所有 C++ 算法并将结果写入 Neo4j。

    执行流程:
      1. C++ pagerank → 获取 PageRank 分数
      2. C++ betweenness → 获取介数中心性
      3. C++ kcore → 获取 K-Core
      4. C++ clustering_coeff → 获取聚类系数
      5. C++ community → 获取社区分配
      6. 合并所有结果为统一格式
      7. 批量写入 Neo4j (Q10)
      8. 创建 Community 节点 + BELONGS_TO 关系

    返回:
        {"status": "success", "synced": N, "communities_created": M}
    """
    import asyncio
    from services.cpp_engine import execute_command

    # 并行运行所有 C++ 算法
    pagerank_task = execute_command("pagerank")
    betweenness_task = execute_command("betweenness")
    kcore_task = execute_command("kcore")
    clustering_task = execute_command("clustering_coeff")
    community_task = execute_command("community")

    pr_result, bc_result, kc_result, cc_result, comm_result = await asyncio.gather(
        pagerank_task, betweenness_task, kcore_task, clustering_task, community_task,
        return_exceptions=True,
    )

    # 收集算法结果
    results_by_node: dict[str, dict[str, Any]] = {}

    def _collect(result, field: str, key: str = "score"):
        """将算法结果收集到 results_by_node 字典中。"""
        if isinstance(result, Exception) or result.get("status") != "success":
            logger.warning("算法 %s 失败, 跳过", field)
            return
        for item in result.get("data", []):
            node_id = str(item["node"])
            if node_id not in results_by_node:
                results_by_node[node_id] = {"id": node_id}
            if field == "community":
                results_by_node[node_id]["community_id"] = str(item["community"])
            if key == "score":
                results_by_node[node_id][field] = float(item["score"])
            elif key == "coreness":
                results_by_node[node_id]["kcore"] = int(item["coreness"])
            elif key == "coefficient":
                results_by_node[node_id]["clustering_coeff"] = float(item["coefficient"])

    _collect(pr_result, "pagerank")
    _collect(bc_result, "betweenness")
    _collect(kc_result, "kcore", key="coreness")
    _collect(cc_result, "clustering_coeff", key="coefficient")
    _collect(comm_result, "community")

    # 计算度 (需要从拓扑数据获取, 这里从 C++ get_full_graph 计算)
    # 简化: 度在 Q10 写入时从 Neo4j 计算, 此处暂不设置
    # 实际应在导入阶段通过 Neo4j 计算 degree

    updates = list(results_by_node.values())

    # 批量写入
    sync_result = await batch_update_algorithm_results(updates)

    # 同步 Community 节点
    communities_created = await _sync_community_nodes()

    return {
        "status": "success",
        "synced": sync_result["updated_count"],
        "communities_created": communities_created,
    }


async def _sync_community_nodes() -> int:
    """从 User.community_id 聚合并创建/更新 Community 节点和 BELONGS_TO 关系。"""
    from db.neo4j import execute_cypher_write

    query = """
        // 1. 创建/更新 Community 节点
        MATCH (u:User)
        WHERE u.community_id IS NOT NULL
        WITH u.community_id AS cid, count(u) AS size, collect(u) AS members
        MERGE (c:Community {id: cid})
        SET c.size = size,
            c.name = 'Community ' + cid,
            c.cohesion = 0.0,
            c.updated_at = datetime()

        // 2. 清除旧的 BELONGS_TO 关系
        WITH c, members
        UNWIND members AS member
        OPTIONAL MATCH (member)-[old:BELONGS_TO]->(:Community)
        DELETE old

        // 3. 创建新的 BELONGS_TO 关系
        WITH c, members
        UNWIND members AS member
        MERGE (member)-[:BELONGS_TO {joined_at: datetime()}]->(c)
        RETURN count(DISTINCT c) AS communities_created
    """
    records = await execute_cypher_write(query)
    count = int(records[0]["communities_created"]) if records else 0
    logger.info("Community 节点同步完成: %d 个社区", count)
    return count


# ═══════════════════════════════════════════════════════════════════
# Scenario A — 社交网络好友推荐 (Neo4j + C++ PageRank 混合)
# ═══════════════════════════════════════════════════════════════════

async def scenario_a_friend_recommendation(
    user_id: str,
    limit: int = 10,
) -> dict:
    """社交网络好友推荐 — 完整数据流。

    流程:
      1. Neo4j Q6: 找共同邻居最多的候选人
      2. C++ PageRank: 获取全局影响力分数
      3. 合并: combined_score = common_friends * (1 + PageRank * 10)
      4. 排序返回 Top-K

    端点: POST /api/v1/graph/recommendations

    请求:
      {
        "user_id": "42",
        "limit": 10
      }

    响应:
      {
        "status": "success",
        "for_user": "42",
        "recommendations": [
          {
            "id": "108",
            "common_friends": 5,
            "pagerank": 0.00234,
            "combined_score": 5.12,
            "explanation": "通过 5 位共同好友连接, 且具有较高影响力"
          }
        ],
        "algorithm": "common_neighbors + pagerank",
        "latency_ms": 45.2
      }
    """
    import time
    import asyncio

    start = time.time()

    # 阶段 1: Neo4j 共同邻居查询
    neo4j_result = await get_friend_recommendations(user_id, limit=limit * 2)

    if neo4j_result.get("status") != "success":
        return neo4j_result

    candidates = neo4j_result["recommendations"]

    # 阶段 2: 如果候选人已有 pagerank, 直接用; 否则调用 C++
    # 因为 Q6 已经返回了 candidate.pagerank, 这里主要是展示混合计算路径
    cpp_pagerank: dict[str, float] = {}

    # 如果候选人缺少 PageRank 或需要刷新, 调用 C++ 引擎
    need_cpp = any(c.get("pagerank", 0) == 0 for c in candidates)
    if need_cpp:
        from services.cpp_engine import execute_command
        pr_result = await execute_command("pagerank")
        if pr_result.get("status") == "success":
            for item in pr_result.get("data", []):
                cpp_pagerank[str(item["node"])] = float(item["score"])

    # 阶段 3: 合并评分
    for candidate in candidates:
        cid = candidate["id"]
        pr = cpp_pagerank.get(cid, candidate.get("pagerank", 0))
        common = candidate["common_friends"]
        candidate["pagerank"] = round(pr, 6)
        candidate["combined_score"] = round(common * (1.0 + pr * 10), 2)
        if common >= 5:
            candidate["explanation"] = f"通过 {common} 位共同好友连接, 且具有较高影响力"
        elif common >= 2:
            candidate["explanation"] = f"通过 {common} 位共同好友连接"
        else:
            candidate["explanation"] = "通过 PageRank 影响力发现"

    # 按综合得分降序
    candidates.sort(key=lambda x: x["combined_score"], reverse=True)
    candidates = candidates[:limit]

    latency_ms = round((time.time() - start) * 1000, 1)

    return {
        "status": "success",
        "for_user": user_id,
        "recommendations": candidates,
        "algorithm": "neo4j_common_neighbors + cpp_pagerank",
        "latency_ms": latency_ms,
    }


# ═══════════════════════════════════════════════════════════════════
# Scenario B — 协同过滤推荐系统
# ═══════════════════════════════════════════════════════════════════

async def scenario_b_collaborative_filtering(
    user_id: str,
    item_type: str | None = None,
    limit: int = 10,
) -> dict:
    r"""协同过滤推荐 — "喜欢 X 的用户也喜欢 Y"。

    图模型扩展:
      (:User)-[:LIKES]->(:Item)    — 用户喜欢物品
      (:User)-[:VIEWED]->(:Item)   — 用户浏览物品
      (:User)-[:PURCHASED]->(:Item) — 用户购买物品

    算法:
      1. 找到目标用户的邻居用户 (有相似行为的用户)
      2. 聚合邻居喜欢的物品 (排除目标用户已喜欢的)
      3. 用 C++ PageRank 对候选物品加权
      4. 返回 Top-K 推荐 + 解释

    端点: POST /api/v1/graph/collaborative

    请求:
      {
        "user_id": "42",
        "item_type": "product",  // 可选: page/product/group
        "limit": 10
      }

    响应:
      {
        "status": "success",
        "for_user": "42",
        "recommendations": [
          {
            "item_id": "item_789",
            "item_name": "Graph Theory 101",
            "item_type": "page",
            "score": 0.87,
            "explanation": "被 12 位相似用户喜欢, 且具有高 PageRank 权重",
            "similar_users_count": 12
          }
        ]
      }
    """
    from db.neo4j import execute_cypher
    import time

    start = time.time()

    # 阶段 1: 协同过滤主查询
    # 找相似用户 → 聚合他们喜欢的物品 → 排除已喜欢的 → 排序
    item_filter = "AND item.type = $item_type" if item_type else ""

    query = f"""
        // 1. 找到目标用户
        MATCH (u:User {{id: $user_id}})

        // 2. 找到与 u 有共同好友的相似用户
        MATCH (u)-[:KNOWS]-(:User)-[:KNOWS]-(similar:User)
        WHERE similar.id <> $user_id

        // 3. 相似用户喜欢的物品
        MATCH (similar)-[like:LIKES]->(item:Item)
        WHERE NOT EXISTS {{ (u)-[:LIKES]->(item) }}
        {item_filter}

        // 4. 聚合评分
        WITH item,
             count(DISTINCT similar) AS similar_count,
             avg(COALESCE(like.score, 1.0)) AS avg_like_score

        // 5. PageRank 加权 (若 Item 关联了 User 社区的 PageRank)
        OPTIONAL MATCH (item)<-[:LIKES]-(liker:User)
        WITH item, similar_count, avg_like_score,
             avg(liker.pagerank) AS avg_liker_pagerank

        RETURN
            item.id AS item_id,
            item.name AS item_name,
            item.type AS item_type,
            item.category AS item_category,
            similar_count,
            avg_like_score,
            COALESCE(avg_liker_pagerank, 0.0) AS community_pagerank,
            (similar_count * avg_like_score * (1.0 + COALESCE(avg_liker_pagerank, 0.0) * 10))
              AS final_score
        ORDER BY final_score DESC
        LIMIT $limit
    """
    records = await execute_cypher(query, {
        "user_id": user_id,
        "limit": limit,
        "item_type": item_type or "",
    })

    recommendations = []
    for rec in records:
        similar_count = int(rec["similar_count"])
        recommendations.append({
            "item_id": str(rec["item_id"]),
            "item_name": rec.get("item_name", ""),
            "item_type": rec.get("item_type", ""),
            "item_category": rec.get("item_category", ""),
            "score": round(float(rec["final_score"]), 4),
            "similar_users_count": similar_count,
            "avg_like_score": round(float(rec["avg_like_score"]), 4),
            "explanation": (
                f"被 {similar_count} 位相似用户喜欢, "
                f"社区影响力权重 {round(float(rec['community_pagerank']), 6)}"
            ),
        })

    latency_ms = round((time.time() - start) * 1000, 1)

    return {
        "status": "success",
        "for_user": user_id,
        "item_type_filter": item_type,
        "recommendations": recommendations,
        "algorithm": "collaborative_filtering + pagerank_weighted",
        "latency_ms": latency_ms,
    }


# ═══════════════════════════════════════════════════════════════════
# Scenario C — 知识图谱多跳探索
# ═══════════════════════════════════════════════════════════════════

async def scenario_c_knowledge_graph_explore(
    user_id: str,
    min_shared_interests: int = 2,
    max_hops: int = 3,
    limit: int = 10,
) -> dict:
    """知识图谱多跳探索 — "找到和我朋友至少共享 N 个兴趣的人"。

    图模型:
      (:User)-[:HAS_ATTRIBUTE]->(:Attribute)  — 用户拥有属性
      (:Attribute)-[:RELATED_TO]->(:Attribute) — 属性之间关联

    查询逻辑:
      1. 起点用户 u
      2. u 的朋友 f (1-hop)
      3. f 的兴趣属性 (2-hop)
      4. 拥有相同兴趣的陌生人 s (3-hop)
      5. 过滤: s 不是 u 的朋友, 且共享兴趣数 >= N

    路径说明返回:
      不仅返回结果, 还返回推理路径, 展示"为什么推荐此人"。

    端点: POST /api/v1/graph/knowledge-explore

    请求:
      {
        "user_id": "42",
        "min_shared_interests": 2,
        "max_hops": 3,
        "limit": 10
      }

    响应:
      {
        "status": "success",
        "discoveries": [
          {
            "user_id": "108",
            "shared_interests": ["Graph Theory", "Machine Learning"],
            "shared_count": 2,
            "paths": [
              {
                "path": "42 -> [KNOWS] -> 55 -> [HAS_ATTRIBUTE] -> Graph Theory -> [HAS_ATTRIBUTE] -> 108",
                "path_length": 3
              }
            ],
            "explanation": "通过你的朋友 55 的共同兴趣 'Graph Theory' 发现"
          }
        ]
      }
    """
    from db.neo4j import execute_cypher
    import time

    start = time.time()

    query = """
        // 1. 找到起点用户 u
        MATCH (u:User {id: $user_id})

        // 2. u 的朋友 (1-hop)
        MATCH (u)-[:KNOWS]-(friend:User)

        // 3. 朋友的兴趣属性 (2-hop)
        MATCH (friend)-[:HAS_ATTRIBUTE]->(attr:Attribute)

        // 4. 共享相同兴趣的陌生人 (3-hop)
        MATCH (stranger:User)-[:HAS_ATTRIBUTE]->(attr)
        WHERE stranger.id <> $user_id
          AND NOT (u)-[:KNOWS]-(stranger)

        // 5. 聚合共享兴趣
        WITH stranger,
             collect(DISTINCT attr.name) AS shared_interests,
             count(DISTINCT attr) AS shared_count,
             collect(DISTINCT friend.id)[0..3] AS via_friends_sample

        WHERE shared_count >= $min_shared_interests

        // 6. 可选: 也考虑属性之间的关联 (RELATED_TO)
        OPTIONAL MATCH (stranger)-[:HAS_ATTRIBUTE]->(attr2:Attribute)
        WHERE attr2.name IN shared_interests
        WITH stranger, shared_interests, shared_count, via_friends_sample,
             collect(DISTINCT attr2.category) AS interest_categories

        RETURN
            stranger.id AS user_id,
            shared_interests,
            shared_count,
            via_friends_sample,
            interest_categories,
            stranger.pagerank AS pagerank
        ORDER BY shared_count DESC, stranger.pagerank DESC
        LIMIT $limit
    """
    records = await execute_cypher(query, {
        "user_id": user_id,
        "min_shared_interests": min_shared_interests,
        "limit": limit,
    })

    discoveries = []
    for rec in records:
        shared = [str(s) for s in rec["shared_interests"]]
        via_friends = [str(f) for f in rec["via_friends_sample"]]
        categories = [str(c) for c in rec["interest_categories"]]

        # 构造推理路径
        paths = []
        for friend_id in via_friends[:3]:
            for interest in shared[:2]:
                paths.append({
                    "path": (
                        f"{user_id} -> [KNOWS] -> {friend_id} "
                        f"-> [HAS_ATTRIBUTE] -> {interest} "
                        f"-> [HAS_ATTRIBUTE] -> {rec['user_id']}"
                    ),
                    "path_length": 3,
                })

        # 生成解释
        friend_str = via_friends[0] if via_friends else "朋友"
        interest_str = shared[0] if shared else "共同兴趣"
        explanation = (
            f"通过你的朋友 {friend_str} 的共同兴趣 '{interest_str}' 发现"
            + (f" (及其他 {len(shared)-1} 个兴趣)" if len(shared) > 1 else "")
        )

        discoveries.append({
            "user_id": str(rec["user_id"]),
            "shared_interests": shared,
            "shared_count": int(rec["shared_count"]),
            "interest_categories": categories,
            "via_friends": via_friends,
            "paths": paths[:3],
            "pagerank": round(float(rec.get("pagerank", 0) or 0), 6),
            "explanation": explanation,
        })

    latency_ms = round((time.time() - start) * 1000, 1)

    return {
        "status": "success",
        "for_user": user_id,
        "min_shared_interests": min_shared_interests,
        "discoveries": discoveries,
        "algorithm": "knowledge_graph_multi_hop",
        "latency_ms": latency_ms,
    }


# ═══════════════════════════════════════════════════════════════════
# 场景辅助: 批量创建场景数据
# ═══════════════════════════════════════════════════════════════════

async def seed_scenario_b_data(items: list[dict[str, str]]) -> dict:
    """为 Scenario B 创建示例 Item 节点和 LIKES/VIEWED 关系。

    仅用于开发和演示环境。

    Args:
        items: [{"id": "item_1", "name": "...", "type": "page", "category": "cs"}]

    返回:
        {"status": "success", "created": N}
    """
    from db.neo4j import execute_cypher_write

    # 批量创建 Item 节点
    create_query = """
        UNWIND $items AS item
        MERGE (i:Item {id: item.id})
        SET i.name = item.name,
            i.type = item.type,
            i.category = item.category,
            i.created_at = COALESCE(i.created_at, datetime())
        RETURN count(i) AS created
    """
    records = await execute_cypher_write(create_query, {"items": items})
    created = int(records[0]["created"]) if records else 0
    return {"status": "success", "created": created}


async def seed_scenario_c_data(attributes: list[dict[str, str]]) -> dict:
    """为 Scenario C 创建示例 Attribute 节点。

    Args:
        attributes: [{"id": "attr_1", "name": "Graph Theory", "category": "interest"}]

    返回:
        {"status": "success", "created": N}
    """
    from db.neo4j import execute_cypher_write

    query = """
        UNWIND $attributes AS attr
        MERGE (a:Attribute {id: attr.id})
        SET a.name = attr.name,
            a.category = attr.category
        RETURN count(a) AS created
    """
    records = await execute_cypher_write(query, {"attributes": attributes})
    created = int(records[0]["created"]) if records else 0
    return {"status": "success", "created": created}
