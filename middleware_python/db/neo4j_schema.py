"""
SocialGraph Pro — Neo4j 图数据模型 & 索引策略

================================================================================
图数据模型
================================================================================

节点标签:
  :User — 社交网络用户 (核心实体)
    { id, pagerank, betweenness, kcore, clustering_coeff, degree,
      community_id, name, updated_at }

  :Community — 检测到的社区/聚类 (来自 LPA / Connected Components)
    { id, size, name, cohesion, top_influencer_id, algorithm }

  :Influencer — 高影响力用户 (派生标签, PageRank top 5% 或 betweenness top 5%)
    (继承 :User 的所有属性)

  :Item — 推荐物品 (Scenario B: 协同过滤)
    { id, type, name, category }
    type ∈ {"page", "product", "group"}

  :Attribute — 用户属性/兴趣点 (Scenario C: 知识图谱)
    { id, name, category }
    category ∈ {"interest", "demographic", "location"}

关系类型:
  [:KNOWS]          — 直接好友关系
    { weight, mutual, created_at }

  [:BELONGS_TO]     — User → Community 归属
    { joined_at }

  [:INFLUENCES]     — 高影响力 User → 邻居 (权重 = PageRank 差值)
    { weight }

  [:LIKES]          — User → Item 喜欢 (Scenario B)
    { score, created_at }

  [:VIEWED]         — User → Item 浏览 (Scenario B)
    { count, last_viewed_at }

  [:PURCHASED]      — User → Item 购买 (Scenario B)
    { purchased_at }

  [:HAS_ATTRIBUTE]  — User → Attribute (Scenario C)
    { weight, source }

  [:RELATED_TO]     — Attribute → Attribute 关联 (Scenario C)
    { weight }


================================================================================
索引策略
================================================================================

┌────────────────────────┬───────────────┬──────────────────────────┬──────────────────────────────────────┐
│ 索引名                   │ 类型           │ 服务的查询                 │ 无索引时的计划                        │
├────────────────────────┼───────────────┼──────────────────────────┼──────────────────────────────────────┤
│ user_id_index           │ B-tree RANGE  │ Q1,Q2,Q5,Q6,Q10          │ AllNodesScan → 4000+ 节点全扫描       │
│ user_pagerank_index     │ B-tree RANGE  │ Q3, Scenario A           │ LabelScan + 排序/过滤 无索引          │
│ user_betweenness_index  │ B-tree RANGE  │ Q7                        │ LabelScan + Filter                   │
│ user_kcore_index        │ B-tree RANGE  │ 统计查询                   │ LabelScan + Filter                   │
│ user_community_index    │ B-tree RANGE  │ Q4,Q8                     │ LabelScan + Filter (全扫描 User)     │
│ user_clustering_index   │ B-tree RANGE  │ Q9                        │ LabelScan + Filter                   │
│ user_degree_index       │ B-tree RANGE  │ 度过滤查询 (top N)         │ LabelScan + 排序                     │
│ community_id_index      │ B-tree RANGE  │ Q8, 社区查询               │ AllNodesScan (Community 数量少)      │
│ item_id_index           │ B-tree RANGE  │ Scenario B                │ AllNodesScan                         │
│ attribute_id_index      │ B-tree RANGE  │ Scenario C                │ AllNodesScan                         │
│ user_comm_pr (复合)      │ B-tree RANGE  │ Q3+Q4 联合, 社区排行       │ 两个独立索引查询合并                   │
│ user_name_ft            │ Full-text     │ 用户名搜索                  │ LabelScan + CONTAINS (极慢)          │
│ item_name_ft            │ Full-text     │ 物品名搜索                  │ LabelScan + CONTAINS                 │
└────────────────────────┴───────────────┴──────────────────────────┴──────────────────────────────────────┘

约束:
  - user_id_unique:    UNIQUE (u:User {id})    — 主键约束
  - community_id_unique: UNIQUE (c:Community {id}) — 主键约束
  - item_id_unique:    UNIQUE (i:Item {id})    — 主键约束
  - attribute_id_unique: UNIQUE (a:Attribute {id}) — 主键约束
"""
import logging
from typing import Any

logger = logging.getLogger("socialgraph.db.neo4j_schema")


# ═══════════════════════════════════════════════════════════════════
# 索引定义清单
# ═══════════════════════════════════════════════════════════════════

INDEX_DEFINITIONS: list[dict[str, Any]] = [
    # ── 用户节点索引 ──
    {
        "name": "user_id_index",
        "cypher": "CREATE INDEX user_id_index IF NOT EXISTS FOR (u:User) ON (u.id)",
        "type": "B-tree (RANGE)",
        "serves": "Q1, Q2, Q5, Q6, Q10",
        "without_index": "AllNodesScan → 遍历所有节点查找指定用户",
        "cardinality": "~4000 (唯一值)",
        "selectivity": "高 (等值查找 → NodeByIdSeek)",
    },
    {
        "name": "user_pagerank_index",
        "cypher": "CREATE INDEX user_pagerank_index IF NOT EXISTS FOR (u:User) ON (u.pagerank)",
        "type": "B-tree (RANGE)",
        "serves": "Q3 (Top Influencers), Scenario A",
        "without_index": "LabelScan + Sort → 全表排序",
        "cardinality": "~4000 (高基数, 浮点连续值)",
        "selectivity": "中 (范围扫描 + ORDER BY 利用索引排序)",
    },
    {
        "name": "user_betweenness_index",
        "cypher": "CREATE INDEX user_betweenness_index IF NOT EXISTS FOR (u:User) ON (u.betweenness)",
        "type": "B-tree (RANGE)",
        "serves": "Q7 (Community Bridge Detection)",
        "without_index": "LabelScan + Filter → 全表过滤",
        "cardinality": "~4000",
        "selectivity": "中",
    },
    {
        "name": "user_kcore_index",
        "cypher": "CREATE INDEX user_kcore_index IF NOT EXISTS FOR (u:User) ON (u.kcore)",
        "type": "B-tree (RANGE)",
        "serves": "Coreness 过滤查询, Graph Stats",
        "without_index": "LabelScan + Filter",
        "cardinality": "~50 (k-core 值范围有限)",
        "selectivity": "低基数但可加速范围查询",
    },
    {
        "name": "user_community_index",
        "cypher": "CREATE INDEX user_community_index IF NOT EXISTS FOR (u:User) ON (u.community_id)",
        "type": "B-tree (RANGE)",
        "serves": "Q4 (Community Structure), Q8 (Density Analysis)",
        "without_index": "LabelScan + Filter (社区查询需扫描所有 User)",
        "cardinality": "~50-200 (社区数量, 取决于数据)",
        "selectivity": "中-低 (每个社区含多用户)",
    },
    {
        "name": "user_clustering_index",
        "cypher": "CREATE INDEX user_clustering_index IF NOT EXISTS FOR (u:User) ON (u.clustering_coeff)",
        "type": "B-tree (RANGE)",
        "serves": "Q9 (Graph-wide Statistics)",
        "without_index": "LabelScan + Filter",
        "cardinality": "~4000",
        "selectivity": "中",
    },
    {
        "name": "user_degree_index",
        "cypher": "CREATE INDEX user_degree_index IF NOT EXISTS FOR (u:User) ON (u.degree)",
        "type": "B-tree (RANGE)",
        "serves": "度过滤查询 (高连接度用户, 孤立节点检测)",
        "without_index": "LabelScan + Sort",
        "cardinality": "~400-1000 (度值分布)",
        "selectivity": "中",
    },
    # ── 社区节点索引 ──
    {
        "name": "community_id_index",
        "cypher": "CREATE INDEX community_id_index IF NOT EXISTS FOR (c:Community) ON (c.id)",
        "type": "B-tree (RANGE)",
        "serves": "Q8, 社区详情查询",
        "without_index": "AllNodesScan (Community 节点少时可接受)",
        "cardinality": "~50-200",
        "selectivity": "高 (等值查找 → NodeByIdSeek)",
    },
    # ── 物品节点索引 (Scenario B) ──
    {
        "name": "item_id_index",
        "cypher": "CREATE INDEX item_id_index IF NOT EXISTS FOR (i:Item) ON (i.id)",
        "type": "B-tree (RANGE)",
        "serves": "Scenario B 协同过滤",
        "without_index": "AllNodesScan",
        "cardinality": "取决于数据规模",
        "selectivity": "高",
    },
    {
        "name": "item_type_index",
        "cypher": "CREATE INDEX item_type_index IF NOT EXISTS FOR (i:Item) ON (i.type)",
        "type": "B-tree (RANGE)",
        "serves": "物品类型过滤",
        "without_index": "LabelScan + Filter",
        "cardinality": "3-10 (类型数有限)",
        "selectivity": "低",
    },
    # ── 属性节点索引 (Scenario C) ──
    {
        "name": "attribute_id_index",
        "cypher": "CREATE INDEX attribute_id_index IF NOT EXISTS FOR (a:Attribute) ON (a.id)",
        "type": "B-tree (RANGE)",
        "serves": "Scenario C 知识图谱探索",
        "without_index": "AllNodesScan",
        "cardinality": "取决于属性数量",
        "selectivity": "高",
    },
    {
        "name": "attribute_category_index",
        "cypher": "CREATE INDEX attribute_category_index IF NOT EXISTS FOR (a:Attribute) ON (a.category)",
        "type": "B-tree (RANGE)",
        "serves": "属性分类过滤",
        "without_index": "LabelScan + Filter",
        "cardinality": "3 (interest/demographic/location)",
        "selectivity": "低",
    },
]

# ═══════════════════════════════════════════════════════════════════
# 复合索引
# ═══════════════════════════════════════════════════════════════════

COMPOSITE_INDEX_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "user_comm_pr",
        "cypher": (
            "CREATE COMPOSITE INDEX user_comm_pr IF NOT EXISTS "
            "FOR (u:User) ON (u.community_id, u.pagerank)"
        ),
        "type": "B-tree (RANGE) composite",
        "serves": "社区内 PageRank 排行, 每个社区的 Top-K 用户查询",
        "without_index": "两个独立索引 → IntersectionNodeByIndexScan",
        "columns": ["community_id", "pagerank"],
        "note": "复合索引键序: community_id (等值) 在前, pagerank (排序) 在后",
    },
]

# ═══════════════════════════════════════════════════════════════════
# 全文索引 (用于用户搜索)
# ═══════════════════════════════════════════════════════════════════

FULLTEXT_INDEX_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "user_name_ft",
        "cypher": (
            "CREATE FULLTEXT INDEX user_name_ft IF NOT EXISTS "
            "FOR (u:User) ON EACH [u.name]"
        ),
        "type": "Full-text (Lucene)",
        "serves": "用户名模糊搜索, 关键字检索",
        "without_index": "LabelScan + WHERE name CONTAINS — 全表扫描+无索引字符串匹配",
    },
    {
        "name": "item_name_ft",
        "cypher": (
            "CREATE FULLTEXT INDEX item_name_ft IF NOT EXISTS "
            "FOR (i:Item) ON EACH [i.name]"
        ),
        "type": "Full-text (Lucene)",
        "serves": "Scenario B 物品名搜索",
        "without_index": "LabelScan + CONTAINS",
    },
]

# ═══════════════════════════════════════════════════════════════════
# 唯一性约束 (同时自动创建索引)
# ═══════════════════════════════════════════════════════════════════

CONSTRAINT_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "user_id_unique",
        "cypher": "CREATE CONSTRAINT user_id_unique IF NOT EXISTS FOR (u:User) REQUIRE u.id IS UNIQUE",
        "type": "UNIQUE (等价于 B-tree 索引 + 唯一性校验)",
        "note": "约束自动创建 B-tree 索引, 无需额外的 user_id_index 如果约束已覆盖",
    },
    {
        "name": "community_id_unique",
        "cypher": "CREATE CONSTRAINT community_id_unique IF NOT EXISTS FOR (c:Community) REQUIRE c.id IS UNIQUE",
        "type": "UNIQUE",
    },
    {
        "name": "item_id_unique",
        "cypher": "CREATE CONSTRAINT item_id_unique IF NOT EXISTS FOR (i:Item) REQUIRE i.id IS UNIQUE",
        "type": "UNIQUE",
    },
    {
        "name": "attribute_id_unique",
        "cypher": "CREATE CONSTRAINT attribute_id_unique IF NOT EXISTS FOR (a:Attribute) REQUIRE a.id IS UNIQUE",
        "type": "UNIQUE",
    },
]

# ═══════════════════════════════════════════════════════════════════
# 属性存在性约束 (Neo4j 5.x+, 可选)
# ═══════════════════════════════════════════════════════════════════

PROPERTY_EXISTENCE_CONSTRAINTS: list[dict[str, Any]] = [
    {
        "name": "user_id_exists",
        "cypher": "CREATE CONSTRAINT user_id_exists IF NOT EXISTS FOR (u:User) REQUIRE u.id IS NOT NULL",
        "type": "NODE PROPERTY EXISTENCE",
        "note": "确保所有 User 节点必有 id 属性",
    },
]

# ═══════════════════════════════════════════════════════════════════
# 预定义图 —— 实际的 Cypher 查询将通过 PROFILE/EXPLAIN 验证
# ═══════════════════════════════════════════════════════════════════

# EXPLAIN 命令模板 (非破坏性, 查看查询计划)
EXPLAIN_TEMPLATES: dict[str, str] = {
    "Q1": "EXPLAIN MATCH (u:User)-[r:KNOWS]->(v:User) RETURN u.id AS source, v.id AS target",
    "Q2": "EXPLAIN MATCH (center:User {id: '1'})-[r:KNOWS*1..2]-(neighbor:User) RETURN DISTINCT neighbor.id",
    "Q3": "EXPLAIN MATCH (u:User) WHERE u.pagerank IS NOT NULL RETURN u.id ORDER BY u.pagerank DESC LIMIT 10",
    "Q4": "EXPLAIN MATCH (u:User) WHERE u.community_id IS NOT NULL WITH u.community_id AS cid, count(u) AS size, collect(u.id) AS members RETURN cid, size",
    "Q5": "EXPLAIN MATCH (start:User {id: '1'}), (end:User {id: '10'}), path = shortestPath((start)-[:KNOWS*]-(end)) RETURN length(path)",
    "Q6": "EXPLAIN MATCH (u:User {id: '1'})-[:KNOWS]-(friend)-[:KNOWS]-(candidate:User) WHERE NOT (u)-[:KNOWS]-(candidate) AND candidate.id <> '1' RETURN candidate.id, count(friend) AS common_friends",
    "Q7": "EXPLAIN MATCH (u:User) WHERE u.betweenness IS NOT NULL AND u.community_id IS NOT NULL MATCH (u)-[:KNOWS]-(neighbor:User) WHERE neighbor.community_id <> u.community_id RETURN DISTINCT u.id, u.betweenness, u.community_id",
    "Q8": "EXPLAIN MATCH (u:User {community_id: '42'}) MATCH (u)-[:KNOWS]-(v:User {community_id: '42'}) RETURN count(DISTINCT u) AS nodes, count(DISTINCT v) AS edges",
    "Q9": "EXPLAIN MATCH (u:User) OPTIONAL MATCH (u)-[:KNOWS]-(v:User) RETURN count(DISTINCT u) AS total_nodes, count(DISTINCT v) AS total_edges",
    "Q10": "EXPLAIN UNWIND $updates AS update MATCH (u:User {id: update.id}) SET u.pagerank = update.pagerank RETURN count(u)",
}


# ═══════════════════════════════════════════════════════════════════
# Schema 初始化函数
# ═══════════════════════════════════════════════════════════════════

async def initialize_schema() -> dict[str, Any]:
    """创建/验证 Neo4j 图数据模型的全部索引和约束。

    幂等性: 所有语句使用 IF NOT EXISTS, 重复执行无副作用。

    执行顺序:
      1. 唯一性约束 (自动创建底层索引, 为后续索引做铺垫)
      2. B-tree 属性索引
      3. 复合索引
      4. 全文索引
      5. 属性存在性约束

    Returns:
        {"status": "success", "created": [...], "skipped": [...], "errors": [...]}
    """
    from db.neo4j import get_neo4j_driver

    driver = await get_neo4j_driver()
    if driver is None:
        return {"status": "error", "message": "Neo4j 驱动不可用"}

    results = {"created": [], "skipped": [], "errors": []}

    # 阶段 1: 唯一性约束
    for constraint in CONSTRAINT_DEFINITIONS:
        try:
            async with driver.session() as session:
                await session.run(constraint["cypher"])
            results["created"].append(f"constraint:{constraint['name']}")
            logger.info("约束已创建: %s", constraint["name"])
        except Exception as e:
            err_msg = str(e)
            if "already exists" in err_msg.lower() or "equivalent" in err_msg.lower():
                results["skipped"].append(f"constraint:{constraint['name']} (已存在)")
            else:
                results["errors"].append(f"constraint:{constraint['name']}: {err_msg}")
                logger.warning("约束创建失败: %s → %s", constraint["name"], err_msg)

    # 阶段 2: B-tree 单属性索引
    for index in INDEX_DEFINITIONS:
        try:
            async with driver.session() as session:
                await session.run(index["cypher"])
            results["created"].append(f"index:{index['name']}")
            logger.info("索引已创建: %s", index["name"])
        except Exception as e:
            err_msg = str(e)
            if "already exists" in err_msg.lower() or "equivalent" in err_msg.lower():
                results["skipped"].append(f"index:{index['name']} (已存在或约束覆盖)")
            else:
                results["errors"].append(f"index:{index['name']}: {err_msg}")
                logger.warning("索引创建失败: %s → %s", index["name"], err_msg)

    # 阶段 3: 复合索引
    for composite in COMPOSITE_INDEX_DEFINITIONS:
        try:
            async with driver.session() as session:
                await session.run(composite["cypher"])
            results["created"].append(f"composite:{composite['name']}")
            logger.info("复合索引已创建: %s (%s)", composite["name"], composite.get("columns"))
        except Exception as e:
            err_msg = str(e)
            if "already exists" in err_msg.lower():
                results["skipped"].append(f"composite:{composite['name']} (已存在)")
            else:
                results["errors"].append(f"composite:{composite['name']}: {err_msg}")
                logger.warning("复合索引创建失败: %s → %s", composite["name"], err_msg)

    # 阶段 4: 全文索引
    for ft_index in FULLTEXT_INDEX_DEFINITIONS:
        try:
            async with driver.session() as session:
                await session.run(ft_index["cypher"])
            results["created"].append(f"fulltext:{ft_index['name']}")
            logger.info("全文索引已创建: %s", ft_index["name"])
        except Exception as e:
            err_msg = str(e)
            if "already exists" in err_msg.lower():
                results["skipped"].append(f"fulltext:{ft_index['name']} (已存在)")
            else:
                results["errors"].append(f"fulltext:{ft_index['name']}: {err_msg}")
                logger.warning("全文索引创建失败: %s → %s", ft_index["name"], err_msg)

    # 阶段 5: 属性存在性约束
    for prop_constraint in PROPERTY_EXISTENCE_CONSTRAINTS:
        try:
            async with driver.session() as session:
                await session.run(prop_constraint["cypher"])
            results["created"].append(f"prop_constraint:{prop_constraint['name']}")
            logger.info("属性约束已创建: %s", prop_constraint["name"])
        except Exception as e:
            err_msg = str(e)
            if "already exists" in err_msg.lower():
                results["skipped"].append(f"prop_constraint:{prop_constraint['name']} (已存在)")
            else:
                results["errors"].append(f"prop_constraint:{prop_constraint['name']}: {err_msg}")
                logger.warning("属性约束创建失败: %s → %s", prop_constraint["name"], err_msg)

    status = "success"
    if results["errors"]:
        status = "partial" if results["created"] else "error"

    logger.info(
        "Schema 初始化完成: status=%s, created=%d, skipped=%d, errors=%d",
        status,
        len(results["created"]),
        len(results["skipped"]),
        len(results["errors"]),
    )
    return {"status": status, **results}


async def verify_indexes() -> dict[str, Any]:
    """验证当前数据库中的索引/约束状态。

    Returns:
        {
            "indexes": [{"name": "...", "type": "...", "labelsOrTypes": [...], ...}],
            "constraints": [{"name": "...", "type": "...", ...}],
        }
    """
    from db.neo4j import get_neo4j_driver

    driver = await get_neo4j_driver()
    if driver is None:
        return {"status": "error", "message": "Neo4j 驱动不可用"}

    async with driver.session() as session:
        index_result = await session.run(
            "SHOW INDEXES WHERE type IN ('RANGE', 'TEXT', 'FULLTEXT') "
            "AND labelsOrTypes CONTAINS 'User' OR labelsOrTypes CONTAINS 'Community' "
            "OR labelsOrTypes CONTAINS 'Item' OR labelsOrTypes CONTAINS 'Attribute'"
        )
        indexes = await index_result.data()

        constraint_result = await session.run(
            "SHOW CONSTRAINTS WHERE labelsOrTypes CONTAINS 'User' "
            "OR labelsOrTypes CONTAINS 'Community' OR labelsOrTypes CONTAINS 'Item' "
            "OR labelsOrTypes CONTAINS 'Attribute'"
        )
        constraints = await constraint_result.data()

    return {
        "status": "success",
        "indexes": [dict(rec) for rec in indexes],
        "constraints": [dict(rec) for rec in constraints],
    }


async def explain_query(query_name: str) -> dict[str, Any]:
    """对命名查询执行 EXPLAIN，返回执行计划。

    使用 PROFILE 运行但不消耗数据 (通过 LIMIT 0 或空结果集)。
    仅用于开发/调试阶段验证索引命中情况。

    Args:
        query_name: Q1-Q10 之一

    Returns:
        {"query": "...", "plan": {...}}
    """
    from db.neo4j import get_neo4j_driver

    if query_name not in EXPLAIN_TEMPLATES:
        return {"status": "error", "message": f"未知查询: {query_name}, 可用: {list(EXPLAIN_TEMPLATES.keys())}"}

    driver = await get_neo4j_driver()
    if driver is None:
        return {"status": "error", "message": "Neo4j 驱动不可用"}

    cypher = EXPLAIN_TEMPLATES[query_name]
    try:
        async with driver.session() as session:
            result = await session.run(cypher)
            # 不调用 result.data() — EXPLAIN 不返回数据, 仅确认计划
            await result.consume()
            # 注意: Neo4j Python driver 的 ResultSummary 包含 plan 信息
            summary = await result.consume()
            plan = (
                str(summary.plan) if summary.plan else "计划信息不可用"
            )
        return {"status": "success", "query": cypher, "plan": plan, "name": query_name}
    except Exception as e:
        return {"status": "error", "query": cypher, "name": query_name, "message": str(e)}
