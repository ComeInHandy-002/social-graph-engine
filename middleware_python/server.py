import os
import subprocess
import asyncio
import json
import logging
import csv
import io

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from models import (
    PathRequest, PathResponse, GraphAllResponse,
    AlgorithmResultResponse, CommunityResponse,
    GraphStatsResponse, ConnectedComponentsResponse,
    HealthResponse
)

# 结构化日志
logging.basicConfig(level=logging.INFO, format="[%(asctime)s] [%(levelname)s] %(message)s")
logger = logging.getLogger("socialgraph")

app = FastAPI(
    title="SocialGraph Pro | 社交网络分析引擎",
    version="2.0.0",
    description="高性能图计算 RESTful API，支持 Betweenness Centrality、PageRank、LPA、K-Core 等 10 种算法"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==========================================
# 基础设施连接 (lazy-init)
# ==========================================
redis_client = None
neo4j_driver = None


def get_redis():
    global redis_client
    if redis_client is None:
        host = os.environ.get("REDIS_HOST", "127.0.0.1")
        port = int(os.environ.get("REDIS_PORT", "6379"))
        try:
            import redis as _redis
            redis_client = _redis.Redis(host=host, port=port, decode_responses=True)
            redis_client.ping()
            logger.info("Redis 已连接: %s:%s", host, port)
        except Exception as e:
            logger.warning("Redis 不可用 (%s:%s): %s", host, port, e)
            redis_client = False
    return redis_client if redis_client is not False else None


def get_neo4j():
    global neo4j_driver
    if neo4j_driver is None:
        uri = os.environ.get("NEO4J_URI", "bolt://127.0.0.1:7687")
        user = os.environ.get("NEO4J_USER", "neo4j")
        password = os.environ.get("NEO4J_PASSWORD", "password123")
        try:
            from neo4j import GraphDatabase as _GraphDatabase
            neo4j_driver = _GraphDatabase.driver(uri, auth=(user, password))
            with neo4j_driver.session() as s:
                s.run("RETURN 1")
            logger.info("Neo4j 已连接: %s", uri)
        except Exception as e:
            logger.warning("Neo4j 不可用 (%s): %s", uri, e)
            neo4j_driver = False
    return neo4j_driver if neo4j_driver is not False else None


# ==========================================
# 路径解析
# ==========================================
def _resolve_path(env_key, *candidates):
    val = os.environ.get(env_key)
    if val and os.path.exists(val):
        return val
    base = os.path.dirname(os.path.abspath(__file__))
    for c in candidates:
        path = os.path.normpath(os.path.join(base, c))
        if os.path.exists(path):
            return path
    return os.path.normpath(os.path.join(base, candidates[0]))


CPP_ENGINE_PATH = _resolve_path(
    "CPP_ENGINE_PATH",
    "../backend_cpp/cmake-build-release/graph_engine.exe",
    "../backend_cpp/cmake-build-debug/graph_engine.exe",
    "../backend_cpp/build/graph_engine",
    "../backend_cpp/build/graph_engine.exe",
)

GRAPH_DATA_PATH = _resolve_path(
    "GRAPH_DATA_PATH",
    "../backend_cpp/facebook_combined.txt",
)


def run_cpp_engine(command, *args):
    cmd = [CPP_ENGINE_PATH, GRAPH_DATA_PATH, command] + list(args)
    logger.info("调用 C++ 引擎: %s", command)
    res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    if res.returncode != 0:
        return {"status": "error", "message": f"C++ 引擎崩溃: {res.stderr}"}
    try:
        return json.loads(res.stdout)
    except json.JSONDecodeError:
        return {"status": "error", "message": "C++ 引擎返回数据格式异常"}


async def run_cpp_engine_async(command, *args):
    cmd = [CPP_ENGINE_PATH, GRAPH_DATA_PATH, command] + list(args)
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        return {"status": "error", "message": f"C++ 引擎崩溃: {stderr.decode('utf-8', errors='replace')}"}
    try:
        return json.loads(stdout.decode("utf-8"))
    except json.JSONDecodeError:
        return {"status": "error", "message": "C++ 引擎返回数据格式异常"}


def _cache_get_or_compute(cache_key, ttl, compute_fn):
    r = get_redis()
    if r:
        cached = r.get(cache_key)
        if cached:
            return json.loads(cached)
    data = compute_fn()
    if r and data.get("status") == "success":
        r.setex(cache_key, ttl, json.dumps(data))
    return data


# ==========================================
# REST API 路由
# ==========================================

@app.get("/api/v1/graph/all", response_model=GraphAllResponse)
async def get_all_graph_data():
    cache_key = "social_graph:all_topology_v7"
    r = get_redis()
    if r:
        cached = r.get(cache_key)
        if cached:
            return json.loads(cached)

    # 优先尝试 Neo4j，不可用时回退到 C++ 引擎直接读文件
    driver = get_neo4j()
    if driver:
        logger.info("从 Neo4j 提取全网拓扑...")
        try:
            with driver.session() as session:
                result = session.run("MATCH (n)-[r:KNOWS]->(m) RETURN n.id AS source, m.id AS target")
                links = [{"source": str(record["source"]), "target": str(record["target"])} for record in result]
        except Exception:
            driver = None  # Neo4j 查询失败，回退

    if not driver:
        logger.info("Neo4j 不可用，从 C++ 引擎直接加载拓扑...")
        data = run_cpp_engine("get_full_graph")
        if data.get("status") == "success":
            if r:
                r.setex(cache_key, 3600, json.dumps(data))
            return data
        return {"status": "error", "nodes": [], "links": []}

    node_ids = set()
    for link in links:
        node_ids.add(link["source"])
        node_ids.add(link["target"])
    nodes = [{"id": nid, "group": 1} for nid in node_ids]
    data = {"status": "success", "nodes": nodes, "links": links}
    if r:
        r.setex(cache_key, 3600, json.dumps(data))
    return data


@app.get("/api/v1/graph/pagerank", response_model=AlgorithmResultResponse)
async def get_pagerank():
    return _cache_get_or_compute("social_graph:pagerank_v3", 86400, lambda: run_cpp_engine("pagerank"))


@app.get("/api/v1/graph/community", response_model=CommunityResponse)
async def get_community():
    return _cache_get_or_compute("social_graph:community_v3", 86400, lambda: run_cpp_engine("community"))


@app.get("/api/v1/graph/betweenness", response_model=AlgorithmResultResponse)
async def get_betweenness():
    return _cache_get_or_compute("social_graph:betweenness_v1", 86400,
                                  lambda: run_cpp_engine("betweenness"))


@app.get("/api/v1/graph/connected_components", response_model=ConnectedComponentsResponse)
async def get_connected_components():
    return _cache_get_or_compute("social_graph:connected_components_v1", 86400,
                                  lambda: run_cpp_engine("connected_components"))


@app.get("/api/v1/graph/kcore", response_model=AlgorithmResultResponse)
async def get_kcore():
    return _cache_get_or_compute("social_graph:kcore_v1", 86400, lambda: run_cpp_engine("kcore"))


@app.get("/api/v1/graph/clustering_coeff", response_model=AlgorithmResultResponse)
async def get_clustering_coeff():
    return _cache_get_or_compute("social_graph:clustering_v1", 86400,
                                  lambda: run_cpp_engine("clustering_coeff"))


@app.get("/api/v1/graph/stats", response_model=GraphStatsResponse)
async def get_graph_stats():
    return _cache_get_or_compute("social_graph:stats_v1", 600, lambda: run_cpp_engine("graph_stats"))


@app.post("/api/v1/graph/shortest_path", response_model=PathResponse)
async def get_shortest_path(req: PathRequest):
    if req.algorithm == "dfs":
        logger.info("DFS 回声室探测: start=%s", req.start_node)
        data = run_cpp_engine("echo_chamber", str(req.start_node))
    elif req.algorithm == "dijkstra":
        logger.info("Dijkstra 寻路: %s -> %s", req.start_node, req.target_node)
        data = run_cpp_engine("dijkstra_path", str(req.start_node), str(req.target_node))
    else:
        logger.info("BFS 寻路: %s -> %s", req.start_node, req.target_node)
        data = run_cpp_engine("shortest_path", str(req.start_node), str(req.target_node))

    if data.get("status") == "success" and "path" in data:
        data["path"] = [str(node) for node in data["path"]]
    return data


# ==========================================
# 数据导出
# ==========================================

@app.get("/api/v1/graph/export/{data_type}")
async def export_data(data_type: str, format: str = Query("csv")):
    cache_key = f"social_graph:{data_type}_v1"
    if data_type == "pagerank":
        cache_key = "social_graph:pagerank_v3"
    elif data_type == "community":
        cache_key = "social_graph:community_v3"

    r = get_redis()
    data = None
    if r:
        cached = r.get(cache_key)
        if cached:
            data = json.loads(cached)
    if not data:
        data = run_cpp_engine(data_type)

    if data.get("status") != "success":
        return {"status": "error", "message": "数据获取失败"}

    if format == "csv":
        output = io.StringIO()
        writer = csv.writer(output)
        items = data.get("data", [])
        if items:
            writer.writerow(items[0].keys())
            for item in items:
                writer.writerow(item.values())
        output.seek(0)
        return StreamingResponse(
            output,
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename={data_type}.csv"}
        )
    else:
        output = io.StringIO()
        json.dump(data, output, ensure_ascii=False, indent=2)
        output.seek(0)
        return StreamingResponse(
            output,
            media_type="application/json",
            headers={"Content-Disposition": f"attachment; filename={data_type}.json"}
        )


# ==========================================
# 健康检查
# ==========================================

@app.get("/api/v1/health", response_model=HealthResponse)
async def health_check():
    cpp_ok = os.path.exists(CPP_ENGINE_PATH)
    redis_ok = get_redis() is not None
    neo4j_ok = get_neo4j() is not None
    return {
        "status": "ok" if cpp_ok else "degraded",
        "cpp_engine_available": cpp_ok,
        "redis_available": redis_ok,
        "neo4j_available": neo4j_ok,
    }


# ==========================================
# WebSocket 实时分析
# ==========================================

@app.websocket("/api/v1/ws/analysis")
async def ws_analysis(websocket: WebSocket):
    await websocket.accept()
    logger.info("WebSocket 客户端已连接")
    try:
        msg = await websocket.receive_json()
        command = msg.get("command", "")
        args = msg.get("args", [])
        logger.info("WebSocket 请求: command=%s args=%s", command, args)

        await websocket.send_json({"status": "running", "message": f"正在执行 {command}..."})

        data = await run_cpp_engine_async(command, *args)

        if data.get("status") == "success":
            await websocket.send_json({"status": "completed", "data": data})
        else:
            await websocket.send_json({"status": "error", "message": data.get("message", "未知错误")})
    except WebSocketDisconnect:
        logger.info("WebSocket 客户端断开")
    except Exception as e:
        logger.error("WebSocket 异常: %s", e)
        try:
            await websocket.send_json({"status": "error", "message": str(e)})
        except Exception:
            pass
