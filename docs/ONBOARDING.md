# SocialGraph Pro 新成员入职指南

欢迎加入 SocialGraph Pro 团队！本文档将带你一步步了解这个全栈社交网络分析平台。阅读完毕后，你将能够独立贡献代码。

---

## 如果你只读 3 个文件

为了最快速度理解系统的核心运作方式，请按顺序阅读这 3 个文件：

| 顺序 | 文件 | 阅读目标 |
|------|------|---------|
| 1 | `backend_cpp/include/Graph.h` | 理解所有数据结构和算法接口定义，这是整个系统的"契约" |
| 2 | `middleware_python/server.py` | 理解应用如何组装：中间件栈 → 路由注册 → WebSocket 端点 |
| 3 | `frontend_web/js/app.js` | 理解前端如何编排加载流程：8 个 API 调用 → 算法结果合并 → 3D 渲染 |

读完这三份文件后，你对 "一个请求从浏览器到 C++ 引擎再回到浏览器" 的完整路径就有了清晰的认知。

---

## 请求生命周期

以下追踪一个完整的 **PageRank 计算请求** 从浏览器发起到响应返回的全过程：

```
[1] 用户点击 "载入核心数据集" 按钮
    │  frontend_web/js/app.js:95
    │  document.getElementById('btn-load').addEventListener('click', ...)

[2] AppController.handleLoadFullSystem() 被调用
    │  app.js:400
    │  遍历 8 个步骤：拓扑、PageRank、LPA、Betweenness、KCore、聚类、统计、连通分量

[3] 对每个步骤，调用 APIService 对应方法
    │  api.js:233
    │  APIService.getPageRank() → this.request('/pagerank')

[4] APIService.request() 发起 HTTP GET
    │  api.js:136
    │  fetch('http://127.0.0.1:8000/api/v1/graph/pagerank')
    │  检查内存缓存 → 未命中 → 发起网络请求 → 请求去重检查

[5] FastAPI 接收请求，通过中间件栈
    │  server.py:143-165
    │  CORSMiddleware → GZip → RateLimit → RequestLog → ErrorHandler → 路由

[6] 路由分发到 routes/graph.py 的 get_pagerank()
    │  routes/graph.py:69
    │  @router.get("/pagerank")
    │  验证当前用户角色 (analyst 或以上)

[7] Cache-Aside: 先查 Redis
    │  services/cache.py:56
    │  cache_get_or_compute("social_graph:pagerank:v3", ...)
    │  Redis GET → 命中? 直接返回 JSON / 未命中? 继续

[8] 调用 C++ 引擎
    │  services/cpp_engine.py:117
    │  execute_command("pagerank")
    │  从进程池获取空闲子进程 → 写入 JSON: {"command":"pagerank","args":[]}
    │  → 等待子进程 stdout 返回 JSON

[9] C++ 引擎执行
    │  backend_cpp/src/main.cpp:106-127
    │  command == "pagerank" → new PageRankAlgorithm()
    │  → algo->execute(graph) → 迭代计算 → 输出 JSON 到 stdout

[10] JSON 回传路径
     │  C++ stdout → cpp_engine.py 读取并解析 → cache.py 写入 Redis
     │  → routes/graph.py 返回响应 → FastAPI 序列化 → HTTP Response

[11] 前端接收响应
     │  api.js:172  → 存入内存缓存 → 返回 JSON 给 app.js

[12] 结果注入 3D 图
     │  app.js:453-477
     │  构建 prMap/commMap/bcMap/kcoreMap/ccMap → engine.prepareBigBang(...)
     │  → engine.renderToTimeStep(1) → WebGL 渲染
```

**关键时间节点**（以 PageRank 为例）：
- 前端缓存命中：< 1ms
- Redis 缓存命中：~5ms
- C++ 引擎计算：~978ms (88,234 边的 Facebook 数据集)
- 3D 渲染首帧：~300ms

---

## 4 个关键数据流

### 数据流 1：PageRank 计算

```
浏览器                     FastAPI                     Redis              C++ 引擎
  │                          │                          │                   │
  │──GET /api/v1/graph/──────│                          │                   │
  │       pagerank           │                          │                   │
  │                          │──GET social_graph:───────│                   │
  │                          │   pagerank:v3            │                   │
  │                          │<──── (miss) ─────────────│                   │
  │                          │                          │                   │
  │                          │──execute_command("pagerank")──────────────────│
  │                          │                          │   subprocess      │
  │                          │                          │   (JSON IPC)      │
  │                          │<───── {status:"success", data:[...]} ─────────│
  │                          │                          │                   │
  │                          │──SETEX social_graph:─────│                   │
  │                          │   pagerank:v3, 86400 ────│                   │
  │<──── JSON Response ──────│                          │                   │
  │                          │                          │                   │
  │  app.js 合并 prMap       │                          │                   │
  │  → 3D 节点着色           │                          │                   │
```

### 数据流 2：图拓扑查询 (Neo4j + 回退)

```
浏览器                 FastAPI              Redis            Neo4j          C++ 引擎
  │                      │                    │                │              │
  │──GET /all───────────│                    │                │              │
  │                      │──GET topology:v7──│                │              │
  │                      │<── (miss) ────────│                │              │
  │                      │                    │                │              │
  │                      │──Cypher MATCH (n)-[r]->(m) RETURN──│              │
  │                      │                    │   id(r)       │              │
  │                      │<── nodes + links ──────────────────│              │
  │                      │    (若 Neo4j 不可用)               │              │
  │                      │──subprocess: get_full_graph ──────────────────────│
  │                      │<── {nodes:[...], links:[...]} ────────────────────│
  │                      │                    │                │              │
  │                      │──SETEX topology:v7│                │              │
  │                      │    3600 ──────────│                │              │
  │<── JSON ─────────────│                    │                │              │
```

### 数据流 3：WebSocket 实时分析

```
浏览器                          FastAPI                         C++ 引擎
  │                              │                                │
  │──WS /api/v1/ws/analysis─────│                                │
  │   ?token=xxx                 │                                │
  │                              │──JWT 验证 (可选)               │
  │<── WS Accept ───────────────│                                │
  │                              │                                │
  │──{"command":"kcore"}────────│                                │
  │                              │──{"status":"running",...}──────│
  │<──{"status":"running"}──────│                                │
  │                              │──execute_command("kcore") ─────│
  │                              │<──{status:"success",...} ──────│
  │<──{"status":"completed"}────│                                │
  │                              │                                │
  │──{"command":"betweenness"}──│  (可重复发送多次命令)           │
  │   ...                       │                                │
```

### 数据流 4：数据导出

```
浏览器                     FastAPI               Redis / C++ 引擎
  │                          │                       │
  │──GET /export/pagerank───│                       │
  │   ?format=csv           │                       │
  │                          │──认证 (get_current_user)
  │                          │                       │
  │                          │──cache_get_or_compute──│ (优先缓存)
  │                          │<── data ──────────────│
  │                          │                       │
  │                          │──检查文件大小限制 (50MB)
  │                          │──记录导出审计 (MongoDB)
  │                          │──生成 CSV/JSON Stream
  │<── StreamingResponse ────│
  │   Content-Disposition:   │
  │   attachment;            │
  │   filename=pagerank.csv  │
```

---

## 术语表

| 术语 | 定义 | 所在文件 |
|------|------|---------|
| **宇宙大爆炸 (Big Bang)** | 渐进式节点渲染动画：节点按时间步从 1 到 100 逐步出现，模拟星系膨胀 | `frontend_web/js/timeline.js`, `graphEngine.js` |
| **雷达面板 (Radar Panel)** | 右侧滑出面板：展示当前聚焦节点的邻居列表，每个邻居卡片显示 PR 得分、阵营、人脉数等 | `frontend_web/js/app.js:313-380`, `index.html:172` |
| **回声室探测 (Echo Chamber)** | 使用 DFS 深度优先搜索探测某节点的社交闭环——如果一个人只与想法相同的人交流，就形成了回声室 | `backend_cpp/src/AlgoDFS.cpp`, `main.cpp:84-105` |
| **LPA** | Label Propagation Algorithm — 标签传播社区发现算法。每个节点将其社区标签更新为邻居中最常见的标签，迭代至收敛 | `backend_cpp/src/AlgoLPA.cpp` |
| **PageRank** | 基于随机游走的节点重要性评分算法。阻尼系数 d=0.85，默认 100 次迭代 | `backend_cpp/src/AlgoPageRank.cpp` |
| **Betweenness Centrality** | 介数中心性 (Brandes 算法)。度量节点出现在其他节点之间最短路径上的频率 — 节点越"中介"越重要 | `backend_cpp/src/AlgoBetweennessCentrality.cpp` |
| **K-Core** | K-Core 分解 (Batagelj-Zaversnik 算法)。递归剥离度数小于 K 的节点，剩余节点的 coreness = K | `backend_cpp/src/AlgoKCore.cpp` |
| **聚类系数 (Clustering Coefficient)** | 衡量节点的邻居之间相互连接的程度 — 越高意味着越紧密的"小团体" | `backend_cpp/src/AlgoClusteringCoeff.cpp` |
| **连通分量 (Connected Components)** | 将图分割为互不连通的子图，每个子图内节点可达，子图间无连接 | `backend_cpp/src/AlgoConnectedComponents.cpp` |
| **策略模式注册中心** | 在 `main.cpp` 中通过 if-else 分支根据 CLI 命令字符串动态实例化不同的算法插件 | `backend_cpp/src/main.cpp` |
| **Cache-Aside** | 缓存策略：读时先查缓存，未命中则计算后写入缓存；写时先更新数据源再失效缓存 | `middleware_python/services/cache.py` |
| **Lazy-Connect** | 数据库连接策略：首次调用时建立连接，后续复用；失败时返回 None 而不抛异常 | `middleware_python/db/redis.py`, `mysql.py`, `mongodb.py`, `neo4j.py` |
| **进程池 (Process Pool)** | 预派生 4 个 C++ 子进程，通过 stdin/stdout 管道复用以消除每次 `subprocess.run()` 的 50ms 启动开销 | `middleware_python/services/cpp_engine.py:38-88` |
| **RBAC** | 基于角色的访问控制：admin (全局管理) / analyst (可运行分析) / viewer (只读) | `database/mysql/001_init_schema.sql:28-33`, `core/dependencies.py` |

---

## 常见易错点

### 1. C++ stdout vs stderr (最重要!)

**问题**: C++ 引擎的 `std::cout` 输出被 Python 网关解析为 JSON。如果在 `std::cout` 中输出任何调试信息，JSON 解析将失败。

**正确做法**: 所有日志/调试信息必须输出到 `std::cerr`。使用宏 `LOG_INFO()` 和 `LOG_ERROR()`（定义在 `include/Graph.h`），它们自动输出到 stderr。

```cpp
// 正确：日志到 stderr，数据到 stdout
LOG_INFO("装载 PageRank 分析插件...");
std::cout << "{\"status\":\"success\",...}" << std::endl;

// 错误：这会破坏 JSON 输出！
std::cout << "Starting PageRank..." << std::endl;  // ❌
```

### 2. Lazy-Connect 返回 None

**问题**: 数据库可能不可用，`get_redis_async()`, `get_mysql_pool()` 等函数可能返回 `None`。不检查返回值直接使用会抛出 `AttributeError`。

**正确做法**: 始终检查返回值并在数据库不可用时优雅降级。

```python
# 正确
r = await get_redis_async()
if r is None:
    return await compute_without_cache()  # 降级逻辑
data = await r.get(cache_key)

# 错误
r = await get_redis_async()
data = await r.get(cache_key)  # ❌ r 可能是 None
```

### 3. 缓存键版本号

**问题**: 缓存键包含版本号（如 `social_graph:pagerank:v3`）。修改算法实现后如果忘记更新版本号，用户可能一直看到旧缓存的结果。

**正确做法**: 每次修改算法逻辑或数据格式时，增量版本号。可以在 `services/cache.py` 和各路由文件中找到当前版本号。

```python
# 版本号出现在这里
result = await cache_get_or_compute(
    "social_graph:pagerank:v3",  # ← v3
    settings.cache_algorithm_ttl,
    execute_command, "pagerank",
)
```

### 4. CDN 依赖

**问题**: 前端通过 `<script src="https://unpkg.com/3d-force-graph">` 加载核心渲染库。如果网络无法访问 CDN，3D 图将完全不工作，但页面不会报明显错误（仅控制台有一个加载失败日志）。

**检查方法**: 打开浏览器开发者工具 → Network 面板 → 确认 `3d-force-graph` 加载成功（状态 200）。

### 5. C++ 引擎路径探测

**问题**: 如果 C++ 引擎没有在预期位置编译，Python 网关启动时找不到可执行文件。配置解析逻辑在 `core/config.py:146-170`，依次探测多个候选路径。

**解决方案**: 设置环境变量 `CPP_ENGINE_PATH` 或 `SGP_CPP_ENGINE_PATH` 指向正确的可执行文件路径。

### 6. Windows 异步事件循环

**问题**: Python 的 `asyncio` 在 Windows 上默认使用 `ProactorEventLoop`，可能导致某些异步操作行为异常。`server.py:219` 中专门为 Windows 设置了 `WindowsSelectorEventLoopPolicy`。

**注意事项**: 如果在 Windows 上编写新的异步脚本，请同样设置事件循环策略。

---

## 从哪里开始贡献

### "我想添加一个新的图算法"

1. **阅读**: `backend_cpp/include/Graph.h` -- 了解策略接口 (`IPathFindingAlgorithm` / `IScoringAlgorithm` / `ICommunityAlgorithm`)
2. **参考**: `backend_cpp/src/AlgoPageRank.cpp` -- 了解 IScoringAlgorithm 实现模式
3. **修改**:
   - `backend_cpp/include/Graph.h` -- 添加算法类声明
   - `backend_cpp/src/Algo<New>.cpp` -- 创建算法实现文件
   - `backend_cpp/src/main.cpp` -- 添加 CLI 命令分支
   - `backend_cpp/CMakeLists.txt` -- 添加到 `ALGO_SOURCES`
4. **测试**: `backend_cpp/tests/test_<New>.cpp` -- 添加 Catch2 测试
5. **API 暴露**: `middleware_python/routes/graph.py` -- 添加新路由端点
6. **前端集成**: `frontend_web/js/api.js` -- 添加 API 方法；`frontend_web/js/app.js` -- 在加载流程中集成

### "我想添加一个新的 API 端点"

1. **阅读**: `middleware_python/routes/graph.py` -- 了解现有路由模式
2. **如需新数据模型**: `middleware_python/models/graph.py` -- 添加 Pydantic 模型
3. **修改**: 在对应路由文件中添加端点（选择正确的角色依赖）
4. **缓存**: 使用 `cache_get_or_compute()` 包装计算逻辑
5. **如需调用 C++ 引擎**: 使用 `execute_command(command, *args)`
6. **测试**: `middleware_python/tests/test_api.py` -- 添加 pytest 测试
7. **文档**: 新端点自动出现在 Swagger UI (`/docs`)

### "我想添加一个新的前端面板/功能"

1. **阅读**: `frontend_web/js/app.js` -- 了解 AppController 如何编排模块
2. **阅读**: `frontend_web/js/state.js` -- 了解 Store 状态管理
3. **修改**:
   - `frontend_web/index.html` -- 添加 UI 面板 HTML 结构
   - `frontend_web/css/components.css` -- 添加样式
   - `frontend_web/js/myFeature.js` -- 创建新模块（仿照现有模块格式）
   - `frontend_web/js/app.js` -- 导入并连接新模块
4. **如需新 API 调用**: `frontend_web/js/api.js` -- 添加方法
5. **如需新状态字段**: `frontend_web/js/state.js` -- 在 `DEFAULT_STATE` 中添加

### "我想添加一个新的数据库实体"

1. **阅读**: `database/mysql/001_init_schema.sql` -- 了解现有数据库设计
2. **MySQL 表**:
   - `database/mysql/001_init_schema.sql` -- 添加 CREATE TABLE 语句
   - `database/mysql/001_init_schema_down.sql` -- 添加回滚脚本
3. **Python 数据库访问**: 使用 `db/mysql.py` 提供的 `execute_query()`, `execute_write()`, `execute_insert()` 方法
4. **MongoDB 集合**: `database/mongodb/schema_design.js` -- 添加集合设计
5. **测试**: 确保 CI 中的 MySQL 初始化脚本能正常执行

---

## 开发工作流速查

### 日常开发循环

```bash
# 1. 修改 C++ 代码后
cd backend_cpp && cmake --build build --config Release && cd build && ctest -C Release

# 2. 修改 Python 代码后
# (uvicorn --reload 会自动重启, 无需手动操作)
# 运行测试:
cd middleware_python && pytest tests/ -v

# 3. 修改前端代码后
# 刷新浏览器即可, 无需构建步骤

# 4. 全栈验证
# 浏览器打开 http://127.0.0.1:3000 → 点击"载入核心数据集" → 等待加载完成
# → 测试路径查询 → 测试仪表板 → 测试导出
```

### 提交前检查清单

- [ ] C++: `ctest --output-on-failure -C Release` 全部通过
- [ ] Python: `pytest tests/ -v` 全部通过
- [ ] 前端: 手动验证核心功能正常
- [ ] 新代码遵循项目编码规范
- [ ] 缓存键版本号已更新（如果修改了算法逻辑）
- [ ] JSON 输出格式与前后端一致
- [ ] 没有 `std::cout` 调试输出残留（仅 `std::cerr`）

### 运行 Benchmark

```bash
cd middleware_python
python benchmark.py
```

此脚本生成 10K/50K/100K 随机边，对 PageRank 和 LPA 算法进行多次压测，输出平均耗时和吞吐量。用于验证性能优化效果。
