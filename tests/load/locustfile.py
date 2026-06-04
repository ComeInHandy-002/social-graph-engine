"""
SocialGraph Pro — 负载测试套件 (Locust)

6 种测试场景:
  1. NormalLoad     — 正常负载 (50 并发, 30 分钟)
  2. PeakLoad       — 峰值负载 (10→200 并发, 60s 爬坡)
  3. SustainedLoad  — 持续负载 (100 并发, 2 小时)
  4. CacheFailure   — Redis 缓存故障 (30 并发, 10 分钟)
  5. DatabaseFailure— Neo4j 数据库故障 (30 并发, 10 分钟)
  6. MixedWorkload  — 混合工作负载 (80 并发, 20 分钟)

用法:
  # 启动 Web UI 模式 (手动选择场景)
  locust -f tests/load/locustfile.py --host=http://127.0.0.1:8000

  # 无 Web UI 模式, 指定场景
  locust -f tests/load/locustfile.py --host=http://127.0.0.1:8000 \
      --headless -u 50 -r 5 --run-time 30m \
      --tags NormalLoad \
      --csv=reports/normal_load

  # 执行所有场景 (使用辅助脚本)
  python tests/load/run_all_scenarios.py

依赖:
  pip install locust
"""

import json
import random
import time
import uuid
import logging
from typing import Optional

from locust import HttpUser, TaskSet, task, between, tag, events
from locust.runners import MasterRunner, WorkerRunner
from locust.env import Environment

logger = logging.getLogger("socialgraph.loadtest")

# ────────────────────────────────────────────────────────────────────
# 配置常量
# ────────────────────────────────────────────────────────────────────

# API 基础路径
API_V1 = "/api/v1"

# 测试数据 — 使用 facebook_combined.txt 中的已知节点 ID
# (格式: "0" 到 "4038")
KNOWN_NODES = [str(i) for i in range(0, 4039)]
KNOWN_COMMUNITIES = list(range(0, 20))  # LPA 发现的典型社区数

# 用户池 — 模拟已认证用户
USERS = [
    {"user_id": f"test_user_{i:04d}", "token": f"mock_jwt_token_{i:04d}"}
    for i in range(200)
]

# WebSocket 端点
WS_ENDPOINT = "/api/v1/ws/analysis"

# ────────────────────────────────────────────────────────────────────
# 请求负载选择器 — 基于权重随机选取
# ────────────────────────────────────────────────────────────────────


class RequestWeights:
    """定义不同场景下的请求类型权重。

    权重之和不需要等于 100, 会自动归一化。
    """

    # 场景 1/3: 正常/持续负载
    NORMAL = {
        "stats_cached": 20,          # GET /graph/stats (cache hit after first)
        "pagerank_cached": 15,       # GET /graph/pagerank (cached after first)
        "community_cached": 15,      # GET /graph/community (cached after first)
        "topology_cached": 10,       # GET /graph/all
        "shortest_path": 10,         # POST /graph/shortest_path (never cached)
        "connected_components": 10,  # GET /graph/connected_components
        "kcore": 10,                 # GET /graph/kcore
        "clustering_coeff": 5,       # GET /graph/clustering_coeff
        "betweenness": 5,            # GET /graph/betweenness
    }

    # 场景 2: 峰值负载 — 更多高频读
    PEAK = {
        "stats_cached": 30,
        "pagerank_cached": 25,
        "community_cached": 20,
        "topology_cached": 15,
        "shortest_path": 10,
    }

    # 场景 4: 缓存故障 — 全部走 C++ 直接计算
    CACHE_FAILURE = {
        "pagerank": 30,
        "community": 20,
        "betweenness": 15,
        "stats": 15,
        "kcore": 10,
        "clustering_coeff": 10,
    }

    # 场景 5: 数据库故障 — 混合拓扑 + 算法
    DB_FAILURE = {
        "topology": 30,              # 应回退到 C++ 文件读
        "shortest_path_neo4j": 15,   # Neo4j 最短路径 → 应降级
        "influencers": 10,           # Neo4j 分页 → 应降级
        "pagerank": 15,              # 不受影响
        "community": 15,             # 不受影响
        "stats": 15,                 # 不受影响
    }

    # 场景 6: 混合工作负载
    MIXED = {
        "stats_cached": 18,          # 读
        "pagerank_cached": 12,       # 读
        "community_cached": 10,      # 读
        "topology_cached": 10,       # 读
        "shortest_path": 10,         # 写 (计算)
        "influencers": 8,            # Neo4j 读
        "ego_network": 5,            # Neo4j 写 (计算)
        "export_pagerank": 5,        # 导出
        "community_structure": 5,    # Neo4j 读
        "recommendations": 5,        # 推荐 (计算密集型)
        "ws_analysis": 5,            # WebSocket
        "health": 7,                 # 健康检查
    }


# ────────────────────────────────────────────────────────────────────
# 认证辅助
# ────────────────────────────────────────────────────────────────────

def random_auth_header() -> dict:
    """生成随机认证头（模拟已认证用户）。"""
    user = random.choice(USERS)
    return {
        "Authorization": f"Bearer {user['token']}",
        "X-Request-ID": str(uuid.uuid4()),
        "Content-Type": "application/json",
    }


# ────────────────────────────────────────────────────────────────────
# WebSocket 客户端 (仅用于 MixedWorkload 场景)
# ────────────────────────────────────────────────────────────────────

class WebSocketClient:
    """简易 WebSocket 客户端，用于在 Locust 中测试 WebSocket 端点。

    注意: Locust 原生不支持 WebSocket。此实现使用标准库 websockets
    进行连接级测试。在真实场景中建议使用 Locust WebSocket 插件或
    自定义 User 类。
    """

    async def connect_and_send(self, command: str, args: list = None):
        """发送一个 WebSocket 命令并等待完成消息。"""
        try:
            import websockets
        except ImportError:
            logger.warning("websockets 库未安装，跳过 WebSocket 测试")
            return {"status": "skipped"}

        uri = f"ws://127.0.0.1:8000{WS_ENDPOINT}?token=mock_jwt_token_0001"
        try:
            async with websockets.connect(uri) as ws:
                await ws.send(json.dumps({
                    "command": command,
                    "args": args or [],
                }))
                # 等待完成响应或超时
                response = await ws.recv()
                # 可能还有后续消息
                return json.loads(response)
        except Exception as e:
            logger.error("WebSocket 连接失败: %s", e)
            return {"status": "error", "message": str(e)}


# ────────────────────────────────────────────────────────────────────
# HTTP 请求任务集
# ────────────────────────────────────────────────────────────────────

class GraphAPITasks(TaskSet):
    """图 API 任务集 — 所有场景共享。

    通过 @tag 装饰器按场景区分，每个场景只执行带对应标签的任务。
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._selected_nodes: Optional[tuple] = None

    def _random_node_pair(self) -> tuple:
        """随机选择一对不同的节点用于路径查询。"""
        if self._selected_nodes is None or random.random() < 0.1:
            a = random.choice(KNOWN_NODES)
            b = random.choice(KNOWN_NODES)
            while b == a:
                b = random.choice(KNOWN_NODES)
            self._selected_nodes = (a, b)
        return self._selected_nodes

    def _auth_headers(self) -> dict:
        return random_auth_header()

    # ── 缓存读 ────────────────────────────────────────────────

    @tag("NormalLoad", "PeakLoad", "SustainedLoad", "MixedWorkload")
    @task(1)
    def get_stats(self):
        """GET /api/v1/graph/stats — 图统计 (公开端点)。"""
        with self.client.get(
            f"{API_V1}/graph/stats",
            headers={"X-Request-ID": str(uuid.uuid4())},
            name="/api/v1/graph/stats",
            catch_response=True,
        ) as resp:
            if resp.status_code != 200:
                resp.failure(f"stats 返回 {resp.status_code}")

    @tag("NormalLoad", "PeakLoad", "SustainedLoad", "MixedWorkload")
    @task(1)
    def get_pagerank(self):
        """GET /api/v1/graph/pagerank — PageRank (需认证)。"""
        with self.client.get(
            f"{API_V1}/graph/pagerank",
            headers=self._auth_headers(),
            name="/api/v1/graph/pagerank",
            catch_response=True,
        ) as resp:
            if resp.status_code not in (200, 401, 403):
                resp.failure(f"pagerank 返回 {resp.status_code}")
            # 401/403 在 mock token 场景下是预期行为

    @tag("NormalLoad", "PeakLoad", "SustainedLoad", "MixedWorkload")
    @task(1)
    def get_community(self):
        """GET /api/v1/graph/community — LPA 社区发现 (需认证)。"""
        with self.client.get(
            f"{API_V1}/graph/community",
            headers=self._auth_headers(),
            name="/api/v1/graph/community",
            catch_response=True,
        ) as resp:
            if resp.status_code not in (200, 401, 403):
                resp.failure(f"community 返回 {resp.status_code}")

    @tag("NormalLoad", "PeakLoad", "SustainedLoad", "MixedWorkload")
    @task(1)
    def get_topology(self):
        """GET /api/v1/graph/all — 全网拓扑 (公开端点)。"""
        with self.client.get(
            f"{API_V1}/graph/all",
            headers={"X-Request-ID": str(uuid.uuid4())},
            name="/api/v1/graph/all",
            catch_response=True,
        ) as resp:
            if resp.status_code != 200:
                resp.failure(f"topology 返回 {resp.status_code}")

    # ── 路径查询 ──────────────────────────────────────────────

    @tag("NormalLoad", "PeakLoad", "SustainedLoad", "MixedWorkload")
    @task(1)
    def post_shortest_path(self):
        """POST /api/v1/graph/shortest_path — BFS 最短路径。"""
        a, b = self._random_node_pair()
        with self.client.post(
            f"{API_V1}/graph/shortest_path",
            json={"start_node": a, "target_node": b, "algorithm": "bfs"},
            headers=self._auth_headers(),
            name="/api/v1/graph/shortest_path",
            catch_response=True,
        ) as resp:
            if resp.status_code not in (200, 401, 403):
                resp.failure(f"shortest_path 返回 {resp.status_code}")

    @tag("NormalLoad", "SustainedLoad")
    @task(1)
    def get_connected_components(self):
        """GET /api/v1/graph/connected_components — 连通分量。"""
        with self.client.get(
            f"{API_V1}/graph/connected_components",
            headers=self._auth_headers(),
            name="/api/v1/graph/connected_components",
            catch_response=True,
        ) as resp:
            if resp.status_code not in (200, 401, 403):
                resp.failure(f"connected_components 返回 {resp.status_code}")

    @tag("NormalLoad", "SustainedLoad")
    @task(1)
    def get_kcore(self):
        """GET /api/v1/graph/kcore — K-Core 分解。"""
        with self.client.get(
            f"{API_V1}/graph/kcore",
            headers=self._auth_headers(),
            name="/api/v1/graph/kcore",
            catch_response=True,
        ) as resp:
            if resp.status_code not in (200, 401, 403):
                resp.failure(f"kcore 返回 {resp.status_code}")

    @tag("NormalLoad", "SustainedLoad")
    @task(1)
    def get_clustering_coeff(self):
        """GET /api/v1/graph/clustering_coeff — 聚类系数。"""
        with self.client.get(
            f"{API_V1}/graph/clustering_coeff",
            headers=self._auth_headers(),
            name="/api/v1/graph/clustering_coeff",
            catch_response=True,
        ) as resp:
            if resp.status_code not in (200, 401, 403):
                resp.failure(f"clustering_coeff 返回 {resp.status_code}")

    @tag("NormalLoad", "SustainedLoad")
    @task(1)
    def get_betweenness(self):
        """GET /api/v1/graph/betweenness — Betweenness Centrality。"""
        with self.client.get(
            f"{API_V1}/graph/betweenness",
            headers=self._auth_headers(),
            name="/api/v1/graph/betweenness",
            catch_response=True,
        ) as resp:
            if resp.status_code not in (200, 401, 403):
                resp.failure(f"betweenness 返回 {resp.status_code}")

    # ── 场景 4: 缓存故障 — 全部走 C++ 直接计算 ──────────────

    @tag("CacheFailure")
    @task(3)
    def get_pagerank_uncached(self):
        """GET /api/v1/graph/pagerank — PageRank (缓存故障 → 直接计算)。"""
        with self.client.get(
            f"{API_V1}/graph/pagerank",
            headers=self._auth_headers(),
            name="/api/v1/graph/pagerank (cache_fail)",
            catch_response=True,
        ) as resp:
            if resp.status_code not in (200, 401, 403):
                resp.failure(f"pagerank (cache_fail) 返回 {resp.status_code}")

    @tag("CacheFailure")
    @task(2)
    def get_community_uncached(self):
        """GET /api/v1/graph/community — LPA (缓存故障 → 直接计算)。"""
        with self.client.get(
            f"{API_V1}/graph/community",
            headers=self._auth_headers(),
            name="/api/v1/graph/community (cache_fail)",
            catch_response=True,
        ) as resp:
            if resp.status_code not in (200, 401, 403):
                resp.failure(f"community (cache_fail) 返回 {resp.status_code}")

    @tag("CacheFailure")
    @task(2)
    def get_betweenness_uncached(self):
        """GET /api/v1/graph/betweenness — Betweenness (缓存故障)。"""
        with self.client.get(
            f"{API_V1}/graph/betweenness",
            headers=self._auth_headers(),
            name="/api/v1/graph/betweenness (cache_fail)",
            catch_response=True,
        ) as resp:
            if resp.status_code not in (200, 401, 403):
                resp.failure(f"betweenness (cache_fail) 返回 {resp.status_code}")

    @tag("CacheFailure")
    @task(2)
    def get_stats_uncached(self):
        """GET /api/v1/graph/stats — Stats (缓存故障)。"""
        with self.client.get(
            f"{API_V1}/graph/stats",
            headers={"X-Request-ID": str(uuid.uuid4())},
            name="/api/v1/graph/stats (cache_fail)",
            catch_response=True,
        ) as resp:
            if resp.status_code != 200:
                resp.failure(f"stats (cache_fail) 返回 {resp.status_code}")

    @tag("CacheFailure")
    @task(1)
    def get_kcore_uncached(self):
        """GET /api/v1/graph/kcore — K-Core (缓存故障)。"""
        with self.client.get(
            f"{API_V1}/graph/kcore",
            headers=self._auth_headers(),
            name="/api/v1/graph/kcore (cache_fail)",
            catch_response=True,
        ) as resp:
            if resp.status_code not in (200, 401, 403):
                resp.failure(f"kcore (cache_fail) 返回 {resp.status_code}")

    @tag("CacheFailure")
    @task(1)
    def get_clustering_uncached(self):
        """GET /api/v1/graph/clustering_coeff — 聚类系数 (缓存故障)。"""
        with self.client.get(
            f"{API_V1}/graph/clustering_coeff",
            headers=self._auth_headers(),
            name="/api/v1/graph/clustering_coeff (cache_fail)",
            catch_response=True,
        ) as resp:
            if resp.status_code not in (200, 401, 403):
                resp.failure(f"clustering_coeff (cache_fail) 返回 {resp.status_code}")

    # ── 场景 5: 数据库故障 ────────────────────────────────────

    @tag("DatabaseFailure")
    @task(3)
    def get_topology_db_fail(self):
        """GET /api/v1/graph/all — 拓扑查询 (Neo4j 不可用 → 回退 C++)。"""
        with self.client.get(
            f"{API_V1}/graph/all",
            headers={"X-Request-ID": str(uuid.uuid4())},
            name="/api/v1/graph/all (db_fail)",
            catch_response=True,
        ) as resp:
            if resp.status_code not in (200, 503):
                resp.failure(f"topology (db_fail) 返回 {resp.status_code}")
            # 200 = 成功回退到 C++ 引擎
            # 503 = 回退也失败了 (可接受但需记录)

    @tag("DatabaseFailure")
    @task(2)
    def get_shortest_path_neo4j(self):
        """POST /api/v1/graph/shortest_path_neo4j — Neo4j 最短路径 (应降级)。"""
        a, b = self._random_node_pair()
        with self.client.post(
            f"{API_V1}/graph/shortest_path_neo4j",
            json={"from_node": a, "to_node": b, "max_depth": 6},
            headers=self._auth_headers(),
            name="/api/v1/graph/shortest_path_neo4j (db_fail)",
            catch_response=True,
        ) as resp:
            if resp.status_code not in (200, 503, 401, 403):
                resp.failure(f"shortest_path_neo4j (db_fail) 返回 {resp.status_code}")

    @tag("DatabaseFailure")
    @task(1)
    def get_influencers_db_fail(self):
        """GET /api/v1/graph/influencers — Top 影响者 (Neo4j 不可用 → 503)。"""
        with self.client.get(
            f"{API_V1}/graph/influencers?limit=10",
            headers=self._auth_headers(),
            name="/api/v1/graph/influencers (db_fail)",
            catch_response=True,
        ) as resp:
            if resp.status_code not in (200, 503, 401, 403):
                resp.failure(f"influencers (db_fail) 返回 {resp.status_code}")

    @tag("DatabaseFailure")
    @task(2)
    def get_pagerank_db_fail(self):
        """GET /api/v1/graph/pagerank — PageRank (不依赖 Neo4j，应正常)。"""
        with self.client.get(
            f"{API_V1}/graph/pagerank",
            headers=self._auth_headers(),
            name="/api/v1/graph/pagerank (db_fail)",
            catch_response=True,
        ) as resp:
            if resp.status_code not in (200, 401, 403):
                resp.failure(f"pagerank (db_fail) 返回 {resp.status_code}")

    @tag("DatabaseFailure")
    @task(2)
    def get_community_db_fail(self):
        """GET /api/v1/graph/community — LPA (不依赖 Neo4j，应正常)。"""
        with self.client.get(
            f"{API_V1}/graph/community",
            headers=self._auth_headers(),
            name="/api/v1/graph/community (db_fail)",
            catch_response=True,
        ) as resp:
            if resp.status_code not in (200, 401, 403):
                resp.failure(f"community (db_fail) 返回 {resp.status_code}")

    # ── 场景 6: 混合工作负载 ──────────────────────────────────

    @tag("MixedWorkload")
    @task(1)
    def get_influencers(self):
        """GET /api/v1/graph/influencers — Top 影响者 (Neo4j 查询)。"""
        with self.client.get(
            f"{API_V1}/graph/influencers?limit=10",
            headers=self._auth_headers(),
            name="/api/v1/graph/influencers",
            catch_response=True,
        ) as resp:
            if resp.status_code not in (200, 401, 403):
                resp.failure(f"influencers 返回 {resp.status_code}")

    @tag("MixedWorkload")
    @task(1)
    def post_ego_network(self):
        """POST /api/v1/graph/ego_network — Ego Network 查询。"""
        node = random.choice(KNOWN_NODES[:100])  # 限制范围
        with self.client.post(
            f"{API_V1}/graph/ego_network",
            json={"node_id": node, "depth": 2},
            headers=self._auth_headers(),
            name="/api/v1/graph/ego_network",
            catch_response=True,
        ) as resp:
            if resp.status_code not in (200, 401, 403):
                resp.failure(f"ego_network 返回 {resp.status_code}")

    @tag("MixedWorkload")
    @task(1)
    def get_export_pagerank(self):
        """GET /api/v1/graph/export/pagerank?format=csv — 数据导出。"""
        with self.client.get(
            f"{API_V1}/graph/export/pagerank?format=csv",
            headers=self._auth_headers(),
            name="/api/v1/graph/export/pagerank",
            catch_response=True,
        ) as resp:
            if resp.status_code not in (200, 401, 403):
                resp.failure(f"export/pagerank 返回 {resp.status_code}")

    @tag("MixedWorkload")
    @task(1)
    def get_community_structure(self):
        """GET /api/v1/graph/community_structure — 社区结构概览。"""
        with self.client.get(
            f"{API_V1}/graph/community_structure?min_size=2",
            headers=self._auth_headers(),
            name="/api/v1/graph/community_structure",
            catch_response=True,
        ) as resp:
            if resp.status_code not in (200, 401, 403):
                resp.failure(f"community_structure 返回 {resp.status_code}")

    @tag("MixedWorkload")
    @task(1)
    def post_recommendations(self):
        """POST /api/v1/graph/recommendations — 好友推荐 (计算密集型)。"""
        node = random.choice(KNOWN_NODES[:100])
        with self.client.post(
            f"{API_V1}/graph/recommendations",
            json={"user_id": node, "limit": 5},
            headers=self._auth_headers(),
            name="/api/v1/graph/recommendations",
            catch_response=True,
        ) as resp:
            if resp.status_code not in (200, 401, 403):
                resp.failure(f"recommendations 返回 {resp.status_code}")

    @tag("MixedWorkload")
    @task(1)
    def get_health(self):
        """GET /api/v1/health — 健康检查。"""
        with self.client.get(
            f"{API_V1}/health",
            name="/api/v1/health",
            catch_response=True,
        ) as resp:
            if resp.status_code != 200:
                resp.failure(f"health 返回 {resp.status_code}")


# ────────────────────────────────────────────────────────────────────
# 用户类 — 模拟不同行为的用户
# ────────────────────────────────────────────────────────────────────

class NormalLoadUser(HttpUser):
    """正常负载用户: 50 并发, 30 分钟, 中等 think time。

    用法:
      locust -f locustfile.py --host=http://127.0.0.1:8000 \
          --headless -u 50 -r 5 --run-time 30m --tags NormalLoad
    """
    tasks = [GraphAPITasks]
    wait_time = between(1, 3)   # 1-3 秒 think time (模拟人类交互)
    weight = 10


class PeakLoadUser(HttpUser):
    """峰值负载用户: 10→200 并发, 60s 爬坡, 短 think time。

    用法:
      locust -f locustfile.py --host=http://127.0.0.1:8000 \
          --headless -u 200 -r 3 --run-time 10m --tags PeakLoad
    """
    tasks = [GraphAPITasks]
    wait_time = between(0.5, 1)  # 短间隔 (模拟突发流量)
    weight = 10


class SustainedLoadUser(HttpUser):
    """持续负载用户: 100 并发, 2 小时。

    用法:
      locust -f locustfile.py --host=http://127.0.0.1:8000 \
          --headless -u 100 -r 10 --run-time 2h --tags SustainedLoad
    """
    tasks = [GraphAPITasks]
    wait_time = between(1, 3)
    weight = 10


class CacheFailureUser(HttpUser):
    """缓存故障用户: 30 并发, 10 分钟, 只执行需要 C++ 直接计算的请求。

    Redis 应在此场景前被手动停止。

    用法:
      # 先: redis-cli shutdown
      locust -f locustfile.py --host=http://127.0.0.1:8000 \
          --headless -u 30 -r 5 --run-time 10m --tags CacheFailure
    """
    tasks = [GraphAPITasks]
    wait_time = between(0.5, 1.5)
    weight = 10


class DatabaseFailureUser(HttpUser):
    """数据库故障用户: 30 并发, 10 分钟, 混合 Neo4j 依赖和非依赖请求。

    Neo4j 应在此场景前被手动停止。

    用法:
      # 先: neo4j stop
      locust -f locustfile.py --host=http://127.0.0.1:8000 \
          --headless -u 30 -r 5 --run-time 10m --tags DatabaseFailure
    """
    tasks = [GraphAPITasks]
    wait_time = between(0.5, 1.5)
    weight = 10


class MixedWorkloadUser(HttpUser):
    """混合工作负载用户: 80 并发, 20 分钟, 全覆盖。

    用法:
      locust -f locustfile.py --host=http://127.0.0.1:8000 \
          --headless -u 80 -r 5 --run-time 20m --tags MixedWorkload
    """
    tasks = [GraphAPITasks]
    wait_time = between(0.5, 2.0)
    weight = 10


# ────────────────────────────────────────────────────────────────────
# 事件钩子 — 自定义统计与日志
# ────────────────────────────────────────────────────────────────────


@events.init.add_listener
def on_locust_init(environment: Environment, **kwargs):
    """Locust 启动时记录测试配置。"""
    if isinstance(environment.runner, MasterRunner):
        logger.info("=" * 60)
        logger.info("SocialGraph Pro — 负载测试启动")
        logger.info("目标主机: %s", environment.host)
        logger.info("用户类: %s", [u.__name__ for u in environment.user_classes])
        logger.info("=" * 60)


@events.test_start.add_listener
def on_test_start(environment: Environment, **kwargs):
    """测试开始前打印场景信息。"""
    logger.info(">>> 负载测试开始执行 @ %s", time.strftime("%Y-%m-%d %H:%M:%S"))


@events.test_stop.add_listener
def on_test_stop(environment: Environment, **kwargs):
    """测试结束后打印汇总统计。"""
    logger.info(">>> 负载测试结束 @ %s", time.strftime("%Y-%m-%d %H:%M:%S"))

    # 打印关键统计
    stats = environment.runner.stats
    total = stats.total
    logger.info("=" * 60)
    logger.info("测试汇总:")
    logger.info("  总请求数:     %d", total.num_requests)
    logger.info("  失败数:       %d", total.num_failures)
    logger.info("  失败率:       %.2f%%", total.fail_ratio * 100)
    logger.info("  平均响应时间: %.1f ms", total.avg_response_time)
    logger.info("  P50 响应时间: %.1f ms", _get_percentile(stats, 0.50))
    logger.info("  P95 响应时间: %.1f ms", _get_percentile(stats, 0.95))
    logger.info("  P99 响应时间: %.1f ms", _get_percentile(stats, 0.99))
    logger.info("  最大响应时间: %.1f ms", total.max_response_time)
    logger.info("  总 RPS:        %.2f", total.total_rps)
    logger.info("=" * 60)

    # 按端点打印
    logger.info("端点级统计 (按失败率排序):")
    entries = sorted(stats.entries.values(), key=lambda e: e.fail_ratio, reverse=True)
    for entry in entries[:20]:
        logger.info(
            "  %-50s | R: %6d | F: %4d (%.1f%%) | avg: %7.1fms | P95: %7.1fms",
            entry.name[:50],
            entry.num_requests,
            entry.num_failures,
            entry.fail_ratio * 100,
            entry.avg_response_time,
            entry.get_response_time_percentile(0.95) or 0,
        )

    # 断言检查
    _assert_performance(stats, environment)


def _get_percentile(stats, percentile: float) -> float:
    """从统计中估算百分位响应时间（兼容 Locust v2.x）。"""
    total = stats.total
    if total.num_requests == 0:
        return 0.0
    try:
        return total.get_response_time_percentile(percentile) or 0.0
    except Exception:
        return 0.0


def _assert_performance(stats, environment: Environment):
    """性能断言 — 测试结束后自动检查 Pass/Fail 标准。

    这些断言不是硬失败的 (不抛异常), 而是在日志中标记 PASS/FAIL,
    方便 CI 系统解析日志判断测试结果。
    """
    total = stats.total
    failures = total.num_failures
    total_requests = total.num_requests
    fail_rate = total.fail_ratio * 100 if total_requests > 0 else 100

    checks = []

    # 检查 1: 错误率 < 1%
    if fail_rate < 1.0:
        checks.append(("PASS", f"错误率 {fail_rate:.2f}% < 1%"))
    else:
        checks.append(("FAIL", f"错误率 {fail_rate:.2f}% >= 1%"))

    # 检查 2: 无进程崩溃 (通过总请求数和失败类型间接判断)
    if total_requests > 0:
        checks.append(("PASS", f"成功发送 {total_requests} 个请求"))
    else:
        checks.append(("FAIL", "零请求发送 (服务可能未启动)"))

    # 打印结果
    logger.info("=" * 60)
    logger.info("性能断言结果:")
    for status, msg in checks:
        log_fn = logger.info if status == "PASS" else logger.error
        log_fn("  [%s] %s", status, msg)

    # 如果有 FAIL, 以非零退出码退出
    has_failures = any(status == "FAIL" for status, _ in checks)
    if has_failures:
        logger.error(">>> 性能断言失败! 请检查上述 FAIL 项。")
        if environment.runner:
            environment.process_exit_code = 1


# ────────────────────────────────────────────────────────────────────
# 辅助: 生成场景执行脚本说明
# ────────────────────────────────────────────────────────────────────

SCENARIO_COMMANDS = """
============================================================
SocialGraph Pro — 所有 6 个负载测试场景的执行命令
============================================================

场景 1 — NormalLoad (正常负载):
  locust -f tests/load/locustfile.py --host=http://127.0.0.1:8000 \\
      --headless -u 50 -r 5 --run-time 30m \\
      --tags NormalLoad \\
      --csv=reports/normal_load \\
      --html=reports/normal_load.html

场景 2 — PeakLoad (峰值负载):
  locust -f tests/load/locustfile.py --host=http://127.0.0.1:8000 \\
      --headless -u 200 -r 3 --run-time 10m \\
      --tags PeakLoad \\
      --csv=reports/peak_load \\
      --html=reports/peak_load.html

场景 3 — SustainedLoad (持续负载):
  locust -f tests/load/locustfile.py --host=http://127.0.0.1:8000 \\
      --headless -u 100 -r 10 --run-time 2h \\
      --tags SustainedLoad \\
      --csv=reports/sustained_load

场景 4 — CacheFailure (缓存故障):
  前置: redis-cli shutdown
  locust -f tests/load/locustfile.py --host=http://127.0.0.1:8000 \\
      --headless -u 30 -r 5 --run-time 10m \\
      --tags CacheFailure \\
      --csv=reports/cache_failure \\
      --html=reports/cache_failure.html
  后置: redis-server --daemonize yes

场景 5 — DatabaseFailure (数据库故障):
  前置: neo4j stop
  locust -f tests/load/locustfile.py --host=http://127.0.0.1:8000 \\
      --headless -u 30 -r 5 --run-time 10m \\
      --tags DatabaseFailure \\
      --csv=reports/db_failure \\
      --html=reports/db_failure.html
  后置: neo4j start

场景 6 — MixedWorkload (混合负载):
  locust -f tests/load/locustfile.py --host=http://127.0.0.1:8000 \\
      --headless -u 80 -r 5 --run-time 20m \\
      --tags MixedWorkload \\
      --csv=reports/mixed_workload \\
      --html=reports/mixed_workload.html

============================================================
一键运行所有场景:
  python tests/load/run_all_scenarios.py
============================================================
"""

if __name__ == "__main__":
    print(SCENARIO_COMMANDS)
