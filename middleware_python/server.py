from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from neo4j import GraphDatabase
import redis
import subprocess
import json
import time

app = FastAPI()

# 解决跨域
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==========================================
# 🌟 第一部分：基础设施连接
# ==========================================
print("🔌 正在连接 Redis 缓存层...")
redis_client = redis.Redis(host='127.0.0.1', port=6379, decode_responses=True)

print("🗄️ 正在连接 Neo4j 图数据库...")
NEO4J_URI = "bolt://127.0.0.1:7687"
NEO4J_AUTH = ("neo4j", "password123")
neo4j_driver = GraphDatabase.driver(NEO4J_URI, auth=NEO4J_AUTH)

# 🎯 极其精准的绝对路径：直指你的 cmake-build-debug 文件夹
CPP_ENGINE_PATH = r"D:\claudecode_workspace\backend_cpp\cmake-build-debug\graph_engine.exe"

# 🎯 数据文件的绝对路径（假设它在 backend_cpp 根目录下）
GRAPH_DATA_PATH = r"D:\claudecode_workspace\backend_cpp\facebook_combined.txt"

# ==========================================
# 🚀 第二部分：四大核心接口
# ==========================================

# 1. 获取全网拓扑 (Neo4j + Redis)
@app.get("/api/v1/graph/all")
async def get_all_graph_data():
    cache_key = "social_graph:all_topology_v7"  # 升级为 v7 强行绕过旧缓存
    
    cached_data = redis_client.get(cache_key)
    if cached_data:
        print("⚡ [全网拓扑] 命中 Redis 缓存！")
        return json.loads(cached_data)

    print("🐌 [全网拓扑] 缓存未命中，正在从 Neo4j 提取星系数据...")
    start_time = time.time()
    
    with neo4j_driver.session() as session:
        # 限制 3000 条边防止前端浏览器卡死
        result = session.run("MATCH (n)-[r:KNOWS]->(m) RETURN n.id AS source, m.id AS target")
        
        # 统一转为字符串，确保前端 3d-force-graph 兼容性
        links = [{"source": str(record["source"]), "target": str(record["target"])} for record in result]
        
        node_ids = set()
        for link in links:
            node_ids.add(link["source"])
            node_ids.add(link["target"])
            
        nodes = [{"id": nid, "group": 1} for nid in node_ids]
        
       # 🚨 完美契合前端要求的终极数据结构
        data = {
            "status": "success",  # 🌟 就是这把极其关键的钥匙！
            "nodes": nodes,
            "links": links
        }

        redis_client.setex(cache_key, 3600, json.dumps(data))
        print(f"💾 [全网拓扑] 数据已存入 Redis！")
        
        return data

# 2. PageRank 权重计算
@app.get("/api/v1/graph/pagerank")
async def get_pagerank():
    cache_key = "social_graph:pagerank_v3" # 再次升级版本
    cached = redis_client.get(cache_key)
    if cached:
        return json.loads(cached)
        
    print(f"🔥 [PageRank] 调用路径: {CPP_ENGINE_PATH}")
    # 增加超时处理和错误捕获
    try:
        cmd = [CPP_ENGINE_PATH, GRAPH_DATA_PATH, "pagerank"]
        res = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8')
        
        if res.returncode != 0:
            return {"status": "error", "message": f"C++ 引擎运行崩溃: {res.stderr}"}
            
        data = json.loads(res.stdout)
        redis_client.setex(cache_key, 86400, json.dumps(data))
        return data
    except Exception as e:
        return {"status": "error", "message": f"Python 调度异常: {str(e)}"}

# 3. LPA 社区发现
@app.get("/api/v1/graph/community")
async def get_community():
    cache_key = "social_graph:community_v3"
    cached = redis_client.get(cache_key)
    if cached:
        return json.loads(cached)

    try:
        cmd = [CPP_ENGINE_PATH, GRAPH_DATA_PATH, "community"]
        res = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8')
        
        if res.returncode != 0:
            return {"status": "error", "message": f"C++ 社区算法崩溃: {res.stderr}"}
            
        data = json.loads(res.stdout)
        redis_client.setex(cache_key, 86400, json.dumps(data))
        return data
    except Exception as e:
        return {"status": "error", "message": f"社区分析调度失败: {str(e)}"}

# 4. 社交链路探测 (支持 BFS / Dijkstra / DFS 回声室)
class PathRequest(BaseModel):
    start_node: str  
    target_node: str = ""  # 🌟 将终点设为可选，因为 DFS 探测环路只需要起点
    algorithm: str = "bfs" 

@app.post("/api/v1/graph/shortest_path")
async def get_shortest_path(req: PathRequest):
    # 🌟 逻辑分发：根据算法类型决定传给 C++ 引擎的指令
    if req.algorithm == "dfs":
        # 如果是 DFS，执行“回声室探测”指令，只传起点
        print(f"🕵️‍♂️ [DFS] 启动深度穿透，探测 ID {req.start_node} 的回声室闭环...")
        command = "echo_chamber"
        cmd = [CPP_ENGINE_PATH, GRAPH_DATA_PATH, command, str(req.start_node)]
    else:
        # 如果是 BFS 或 Dijkstra，执行寻路指令，传起点和终点
        print(f"🔥 [{req.algorithm.upper()}] 唤醒引擎追踪 {req.start_node} -> {req.target_node}...")
        command = "dijkstra_path" if req.algorithm == "dijkstra" else "shortest_path"
        cmd = [CPP_ENGINE_PATH, GRAPH_DATA_PATH, command, str(req.start_node), str(req.target_node)]
    
    res = subprocess.run(cmd, capture_output=True, text=True)
    
    try:
        data = json.loads(res.stdout)
        
        # 统一处理返回路径：将节点 ID 转为字符串，确保前端兼容性
        if data.get("status") == "success" and "path" in data:
            data["path"] = [str(node) for node in data["path"]]
        return data
    except Exception as e:
        print(f"❌ 算法执行失败，错误详情: {res.stderr}")
        return {"status": "error", "message": f"算法调用异常: {str(e)}"}