# CLAUDE.md

## 用户偏好
- 我希望你始终使用**简体中文**与我对话。
- 不要使用英文回复，除非我明确要求。
- 技术术语可以保留英文原名，但解释需用中文。

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

SocialGraph Pro — full-stack social network visual analytics platform. Monorepo with three independent modules: a C++ graph compute engine, a Python API gateway, and a WebGL frontend.

## Build & Run

### C++ Engine (`backend_cpp/`)
```bash
cd backend_cpp
cmake -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build --config Release
# Run: ./build/graph_engine <data_file> <command> [args...]
# CI smoke test: ./build/graph_engine run_test
```

### Python API Gateway (`middleware_python/`)
```bash
pip install fastapi uvicorn redis neo4j
uvicorn server:app --host 0.0.0.0 --port 8000
# Interactive docs at http://127.0.0.1:8000/docs
```

### Benchmark Suite
```bash
cd middleware_python && python benchmark.py
```
Generates random graph data at 10K/50K/100K edge scales and benchmarks PageRank and LPA algorithms via the C++ engine.

### Docker
```bash
docker-compose up
```

### CI/CD
GitHub Actions (`.github/workflows/main.yml`) triggers cross-platform CMake build + smoke test on push to main/master — matrix: `ubuntu-latest` (GCC) and `windows-latest` (MSVC).

## Architecture

### Layered Separation
1. **`backend_cpp/`** — C++17 graph engine, zero third-party graph libs. Hand-rolled adjacency list with strategy-pattern algorithm registry. Outputs JSON to stdout for IPC.
2. **`middleware_python/`** — FastAPI ASGI gateway. Calls C++ engine via `subprocess.run()` for compute endpoints, queries Neo4j for raw topology (`/api/v1/graph/all`), caches results in Redis.
3. **`frontend_web/`** — Zero-framework ES6 modules (`api.js`, `graphEngine.js`, `app.js`). Uses `3d-force-graph` (WebGL) loaded via CDN `<script>` tag, not npm.

### C++ Design (Strategy Pattern)
All algorithms implement typed abstract interfaces defined in `include/Graph.h`:
- `IPathFindingAlgorithm` → BFS, Dijkstra, DFS (echo chamber detection)
- `IScoringAlgorithm` → PageRank
- `ICommunityAlgorithm` → LPA (Label Propagation)

`main.cpp` dispatches by CLI command string (`shortest_path`, `dijkstra_path`, `echo_chamber`, `pagerank`, `community`, `get_full_graph`). Graph data loads from edge-list format (two space-separated node IDs per line).

### Frontend Data Flow
`app.js` → `api.js` (fetch to FastAPI) → `graphEngine.js` (3d-force-graph wrapper). Key features: progressive time-step rendering ("Big Bang" expansion), neighbor detection on right-click, drag-enabled force layout with customizable repel/link tension sliders.

### Data Sources
- `backend_cpp/facebook_combined.txt` — primary edge-list dataset
- Neo4j stores imported graph for topology queries
- Redis caches API responses (3600s for topology, 86400s for computed results)

## Important Caveats

- **C++ output must be valid JSON on stdout** — all logging goes to stderr via `std::cerr` to keep stdout clean for IPC.
- **Neo4j + Redis 是可选依赖**：`server.py` 采用 lazy-connect 模式，若数据库不可用则回退到纯 C++ 引擎模式（PageRank、LPA、路径查询仍正常工作，仅拓扑全图接口依赖 Neo4j）。
- **路径解析优先级**：环境变量 > 相对路径自动探测。设置 `CPP_ENGINE_PATH` / `GRAPH_DATA_PATH` / `NEO4J_URI` / `REDIS_HOST` 可覆盖默认值。
