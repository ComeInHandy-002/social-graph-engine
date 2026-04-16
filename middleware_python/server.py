import subprocess
import json
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware

# 🌟 初始化工业级 FastAPI 实例
app = FastAPI(
    title="Social Graph Engine API",
    description="基于 C++ 底层驱动的高性能社交图谱分析引擎微服务网关",
    version="1.0.0"
)

# 允许前端跨域访问（极其重要，否则你的 WebGL 前端会报错）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ⚠️ 注意：填入你真实的绝对路径！
ENGINE_PATH = r"D:\claudecode_workspace\backend_cpp\cmake-build-debug\graph_engine.exe"
# 假定你的默认数据集在这里，请修改为你真实的 txt 路径！
DATA_PATH = r"D:\claudecode_workspace\backend_cpp\facebook_combined.txt"

# 定义前端传过来的数据格式（严格的类型校验）
class PathRequest(BaseModel):
    start_node: str
    target_node: str

# 核心调度函数：Python 只负责跑腿，脏活全给 C++
def run_engine(command: str, *args):
    cmd = [ENGINE_PATH, DATA_PATH, command] + list(args)
    try:
        # 调用 C++ 引擎
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return json.loads(result.stdout)
    except subprocess.CalledProcessError as e:
        raise HTTPException(status_code=500, detail=f"C++ 底层引擎崩溃: {e}")
    except json.JSONDecodeError:
        raise HTTPException(status_code=500, detail="底层引擎返回了非法的 JSON 格式数据")

# ==========================================
# 🌟 标准 RESTful 路由分发
# ==========================================

@app.get("/api/v1/graph/all", summary="获取全网基础拓扑数据")
def get_full_graph():
    return run_engine("get_full_graph")

@app.get("/api/v1/graph/pagerank", summary="执行全局 PageRank 影响力评估")
def get_pagerank():
    return run_engine("pagerank")

@app.get("/api/v1/graph/community", summary="执行 LPA 社区裂变分析")
def get_community():
    return run_engine("community")

@app.post("/api/v1/graph/shortest_path", summary="查询两点间的最短通信路径")
def get_shortest_path(req: PathRequest):
    return run_engine("shortest_path", req.start_node, req.target_node)