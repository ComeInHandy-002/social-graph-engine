# 代码结构与规范

本文档描述 SocialGraph Pro 的全栈架构设计、目录结构、各层编码规范以及添加新功能的标准步骤。

---

## 1. 全栈架构图

```
┌─────────────────────────────────────────────────────────────────┐
│                        frontend_web/                            │
│  ┌─────────┐  ┌──────────┐  ┌──────────┐  ┌────────────────┐  │
│  │ app.js   │  │ api.js    │  │ state.js  │  │ graphEngine.js │  │
│  │ (控制器) │──│ (HTTP)   │  │ (Store)   │  │ (3D WebGL)     │  │
│  └────┬─────┘  └────┬─────┘  └──────────┘  └────────────────┘  │
│       │              │                                          │
│  ┌────┴─────┐  ┌─────┴────┐  ┌──────────┐  ┌──────────────┐   │
│  │ charts.js │  │ search.js│  │ranking.js│  │ timeline.js  │   │
│  │ (仪表板)  │  │ (搜索)   │  │ (排行)   │  │ (时间轴)     │   │
│  └──────────┘  └──────────┘  └──────────┘  └──────────────┘   │
└──────────────────────┬──────────────────────────────────────────┘
                       │ HTTP REST / WebSocket
┌──────────────────────┴──────────────────────────────────────────┐
│                     middleware_python/                           │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │                    server.py (应用工厂)                    │  │
│  │   create_app() → 注册中间件 → 注册路由 → 注册 WebSocket   │  │
│  └────────────────────────┬─────────────────────────────────┘  │
│                           │                                     │
│  ┌────────────┐  ┌───────┴───────┐  ┌──────────────────────┐  │
│  │ middleware/ │  │   routes/      │  │  websockets/         │  │
│  │ error       │  │   graph.py     │  │  analysis_ws.py      │  │
│  │ request_log │  │   health.py    │  └──────────────────────┘  │
│  │ rate_limit  │  │   export.py    │                            │
│  │ compression │  │   admin.py     │  ┌──────────────────────┐  │
│  └────────────┘  └───────┬───────┘  │  auth/                │  │
│                          │           │  router.py            │  │
│  ┌───────────────────────┴───────┐  │  service.py           │  │
│  │         services/             │  │  models.py            │  │
│  │  cpp_engine.py (进程池)       │  └──────────────────────┘  │
│  │  cache.py (Cache-Aside)      │                             │
│  │  neo4j_service.py (拓扑)     │  ┌──────────────────────┐  │
│  │  performance.py (日志)       │  │  db/                  │  │
│  └───────────────────────────────┘  │  redis.py (Lazy)     │  │
│                                     │  mysql.py (aiomysql)  │  │
│  ┌───────────────────────────────┐  │  mongodb.py (motor)  │  │
│  │  core/                        │  │  neo4j.py (Lazy)     │  │
│  │  config.py (Pydantic)         │  └──────────────────────┘  │
│  │  security.py (JWT/bcrypt)     │                            │
│  │  exceptions.py               │  ┌──────────────────────┐  │
│  │  dependencies.py (Depends)   │  │  models/              │  │
│  └───────────────────────────────┘  │  graph.py            │  │
│                                     │  health.py           │  │
│                                     │  common.py           │  │
│                                     └──────────────────────┘  │
└──────────────────────┬──────────────────────────────────────────┘
                       │ subprocess (JSON IPC)
┌──────────────────────┴──────────────────────────────────────────┐
│                       backend_cpp/                              │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  include/Graph.h                                         │  │
│  │  SocialLogger | SocialGraph | DataManager                │  │
│  │  IGraphAlgorithm ← IPathFindingAlgorithm                │  │
│  │                  ← IScoringAlgorithm                     │  │
│  │                  ← ICommunityAlgorithm                   │  │
│  │  10 个算法类声明                                          │  │
│  └──────────────────────────────────────────────────────────┘  │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  src/                                                     │  │
│  │  main.cpp (CLI 调度 + 算法注册)                           │  │
│  │  GraphCore.cpp (邻接表实现)                               │  │
│  │  AlgoBFS.cpp | AlgoDijkstra.cpp | AlgoDFS.cpp            │  │
│  │  AlgoPageRank.cpp | AlgoLPA.cpp                          │  │
│  │  AlgoBetweennessCentrality.cpp | AlgoKCore.cpp           │  │
│  │  AlgoClusteringCoeff.cpp | AlgoConnectedComponents.cpp   │  │
│  │  AlgoGraphStats.cpp                                       │  │
│  └──────────────────────────────────────────────────────────┘  │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  tests/ (Catch2, 10 个测试文件)                           │  │
│  └──────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

---

## 2. 完整目录树

```
socialgraph-pro/
│
├── .github/workflows/main.yml        # CI/CD: C++ 跨平台构建+测试 + Python pytest
├── CLAUDE.md                         # Claude Code 项目指南
├── README.md                         # 项目主页文档
├── docker-compose.yml                # 6 服务全栈编排 (MySQL/Mongo/Redis/Neo4j/FastAPI/Nginx)
├── .gitignore                        # 忽略构建产物、环境文件、IDE 配置
│
├── docs/
│   ├── screenshot_main.png           # 系统截图
│   ├── SETUP.md                      # 开发环境搭建指南
│   ├── ARCHITECTURE.md               # 本文档
│   └── ONBOARDING.md                 # 新成员入职指南
│
├── backend_cpp/                      # C++ 图计算引擎
│   ├── CMakeLists.txt                # CMake 构建 (引擎 + 静态库 + Catch2 测试)
│   ├── facebook_combined.txt         # 主数据集 (边列表格式)
│   ├── data.txt                      # 备用测试数据集
│   ├── include/
│   │   └── Graph.h                   # 所有类声明: 数据结构 + 日志 + 策略接口 + 10 个算法
│   ├── src/
│   │   ├── main.cpp                  # CLI 入口 + 算法调度器 (10 个命令分支)
│   │   ├── GraphCore.cpp             # SocialGraph 邻接表实现
│   │   ├── AlgoBFS.cpp               # BFS 最短路径
│   │   ├── AlgoDijkstra.cpp          # Dijkstra 带权最短路径
│   │   ├── AlgoDFS.cpp               # DFS 搜寻 + 回声室检测
│   │   ├── AlgoPageRank.cpp          # PageRank 中心性
│   │   ├── AlgoLPA.cpp               # Label Propagation 社区发现
│   │   ├── AlgoBetweennessCentrality.cpp  # Betweenness Centrality (Brandes)
│   │   ├── AlgoKCore.cpp             # K-Core 分解 (Batagelj-Zaversnik)
│   │   ├── AlgoClusteringCoeff.cpp   # 聚类系数
│   │   ├── AlgoConnectedComponents.cpp   # 连通分量
│   │   └── AlgoGraphStats.cpp        # 图级别聚合统计
│   └── tests/
│       ├── test_main.cpp             # Catch2 测试入口
│       ├── test_graph.h              # 测试辅助函数
│       ├── test_BFS.cpp              # BFS 单元测试
│       ├── test_PageRank.cpp         # PageRank 单元测试
│       ├── test_LPA.cpp              # LPA 单元测试
│       ├── test_Dijkstra.cpp         # Dijkstra 单元测试
│       ├── test_Betweenness.cpp      # Betweenness 单元测试
│       ├── test_ConnectedComponents.cpp  # Connected Components 单元测试
│       ├── test_KCore.cpp            # K-Core 单元测试
│       ├── test_ClusteringCoeff.cpp  # 聚类系数 单元测试
│       └── test_GraphStats.cpp       # 图统计 单元测试
│
├── middleware_python/                # FastAPI 微服务网关
│   ├── server.py                     # 应用工厂: create_app() + uvicorn 入口
│   ├── logging_config.py             # 结构化 JSON 日志配置
│   ├── requirements.txt              # Python 依赖清单
│   ├── benchmark.py                  # 自动化 Benchmark 压测 (10K/50K/100K)
│   ├── import_data.py                # Neo4j 批量导入脚本
│   ├── core/
│   │   ├── __init__.py
│   │   ├── config.py                 # Pydantic Settings 统一配置 (SGP_ 前缀)
│   │   ├── exceptions.py             # 自定义异常类 (AppException 等)
│   │   ├── security.py               # JWT 创建/验证 + bcrypt 密码哈希
│   │   └── dependencies.py           # FastAPI Depends 依赖注入 (认证/授权/限流)
│   ├── routes/
│   │   ├── __init__.py
│   │   ├── graph.py                  # 图计算 API: 拓扑 + 9 种算法 + 路径查询
│   │   ├── health.py                 # 健康检查: /health + K8s liveness/readiness
│   │   ├── export.py                 # 数据导出: CSV/JSON 流式响应
│   │   └── admin.py                  # 管理员: 配置热更新/缓存失效/指标查询
│   ├── services/
│   │   ├── __init__.py
│   │   ├── cpp_engine.py             # C++ 引擎进程池 (预派生 + 复用 + 超时回收)
│   │   ├── cache.py                  # Cache-Aside 模式 (Redis + 分布式锁)
│   │   ├── neo4j_service.py          # Neo4j 图拓扑查询 (回退到 C++ 引擎)
│   │   └── performance.py            # 性能监控日志
│   ├── models/
│   │   ├── __init__.py
│   │   ├── graph.py                  # Pydantic 请求/响应模型 (图计算)
│   │   ├── health.py                 # 健康检查响应模型
│   │   └── common.py                 # 通用分页/错误响应模型
│   ├── db/
│   │   ├── __init__.py
│   │   ├── redis.py                  # Redis Lazy-Connect (异步+同步)
│   │   ├── mysql.py                  # MySQL aiomysql 连接池
│   │   ├── mongodb.py                # MongoDB motor 客户端
│   │   └── neo4j.py                  # Neo4j 驱动 Lazy-Connect
│   ├── middleware/
│   │   ├── __init__.py
│   │   ├── error_handler.py          # 全局异常处理 + Request ID
│   │   ├── request_logger.py         # JSON 结构化请求日志
│   │   ├── rate_limiter.py           # 滑动窗口限流
│   │   └── compression.py            # GZip 响应压缩
│   ├── auth/
│   │   ├── __init__.py
│   │   ├── router.py                 # 认证路由: 注册/登录/刷新/登出/API Key
│   │   ├── service.py                # 认证业务逻辑
│   │   └── models.py                 # 认证请求/响应模型
│   ├── websockets/
│   │   ├── __init__.py
│   │   └── analysis_ws.py            # WebSocket 实时分析端点
│   └── tests/
│       ├── __init__.py
│       ├── conftest.py               # pytest fixtures
│       └── test_api.py               # API 集成测试
│
├── frontend_web/                     # WebGL 可视化前端
│   ├── index.html                    # HTML 骨架 + CDN 引用 + UI 面板
│   ├── css/
│   │   ├── reset.css                 # CSS 重置
│   │   ├── variables.css             # CSS 自定义属性 (主题)
│   │   ├── layout.css                # 布局样式
│   │   ├── components.css            # 组件样式
│   │   └── dark-theme.css            # 深色主题
│   └── js/
│       ├── app.js                    # AppController — 应用入口与编排器
│       ├── api.js                    # APIService — HTTP 客户端 (缓存/去重/重试)
│       ├── graphEngine.js            # Engine3D — 3D 力导向图引擎封装
│       ├── state.js                  # Store — 事件驱动集中式状态管理
│       ├── charts.js                 # ChartDashboard — Chart.js 统计仪表板
│       ├── search.js                 # SearchManager — 全局搜索
│       ├── ranking.js                # RankingManager — 排行榜多指标切换
│       ├── timeline.js               # TimelineManager — 时间轴"宇宙大爆炸"动画
│       ├── ui.js                     # UIManager — Toast/Modal/加载屏
│       ├── accessibility.js          # AccessibilityManager — 屏幕阅读器支持
│       ├── config.js                 # CONFIG — API 地址/色板常量
│       └── chart.umd.min.js          # Chart.js 本地拷贝
│
└── database/                         # 数据库初始化脚本
    ├── mysql/
    │   ├── 001_init_schema.sql       # MySQL 建表 (6 张表)
    │   ├── 001_init_schema_down.sql  # 回滚脚本
    │   ├── 002_seed_data.sql         # 种子数据
    │   ├── 003_query_performance.sql # 性能查询优化
    │   └── 004_dataflow_migration.sql # 数据流迁移
    ├── mongodb/
    │   └── schema_design.js          # MongoDB 集合设计
    └── redis/
        └── cache_strategy.md         # 缓存策略文档
```

---

## 3. C++ 编码规范

### 3.1 标准与基础设施

- **标准**: C++17 (`set(CMAKE_CXX_STANDARD 17)` in `CMakeLists.txt`)
- **构建系统**: CMake 3.14+
- **数据结构**: `SocialGraph` 类，手写 `std::unordered_map<std::string, std::vector<std::string>>` 邻接表，零第三方图库
- **日志系统**: `SocialLogger` 静态类，通过 `LOG_INFO()` / `LOG_ERROR()` 宏输出带时间戳的日志到 `std::cerr`
- **数据加载**: `DataManager::loadFromFile()` 从边列表格式文件加载（每行两个空格分隔的节点 ID）

### 3.2 策略模式 (Strategy Pattern)

所有算法通过抽象接口实现，定义在 `include/Graph.h`:

```cpp
// 基础接口 (所有算法的基类)
class IGraphAlgorithm { virtual ~IGraphAlgorithm() = default; };

// 寻路算法接口: 输入 start+target → 输出路径列表
class IPathFindingAlgorithm : public IGraphAlgorithm {
    virtual std::vector<std::string> execute(const SocialGraph&, const std::string& start, const std::string& target) = 0;
};

// 全网评分算法接口: 输入图 → 输出 node→score 映射
class IScoringAlgorithm : public IGraphAlgorithm {
    virtual std::unordered_map<std::string, double> execute(const SocialGraph&) = 0;
};

// 社区聚类算法接口: 输入图 → 输出 node→community_label 映射
class ICommunityAlgorithm : public IGraphAlgorithm {
    virtual std::unordered_map<std::string, std::string> execute(const SocialGraph&) = 0;
};
```

### 3.3 算法注册机制

在 `src/main.cpp` 中通过 if-else 分支按 CLI 命令字符串分发：

```cpp
if (command == "shortest_path" || command == "dijkstra_path") {
    IPathFindingAlgorithm* algo = (command == "dijkstra_path")
        ? new DijkstraAlgorithm() : new BFSAlgorithm();
    auto path = algo->execute(graph, start, target);
    delete algo;
}
```

### 3.4 JSON 输出规范 (IPC 协议)

**关键规则**: `std::cout` 仅用于 JSON 输出，所有日志/调试信息必须通过 `std::cerr` 输出。

C++ 引擎输出的所有 JSON 均遵循统一格式：
```json
{
  "status": "success",
  "time_ms": 126,
  "data": [...]
}
```

错误时：
```json
{
  "status": "error",
  "message": "数据加载失败"
}
```

### 3.5 添加新算法 (标准步骤)

假设你要添加一个 "Triangle Count" 算法：

1. **在 `include/Graph.h` 声明算法类**：
   ```cpp
   class TriangleCountAlgorithm : public IScoringAlgorithm {
   public:
       std::unordered_map<std::string, double> execute(const SocialGraph& graph) override;
   };
   ```

2. **在 `src/` 创建实现文件** `AlgoTriangleCount.cpp`：
   ```cpp
   #include "../include/Graph.h"
   std::unordered_map<std::string, double> TriangleCountAlgorithm::execute(const SocialGraph& graph) {
       std::unordered_map<std::string, double> result;
       // ... 算法实现 ...
       return result;
   }
   ```

3. **在 `CMakeLists.txt` 的 `ALGO_SOURCES` 中添加** `src/AlgoTriangleCount.cpp`

4. **在 `src/main.cpp` 添加 CLI 分支**：
   ```cpp
   else if (command == "triangle_count") {
       IScoringAlgorithm* algo = new TriangleCountAlgorithm();
       auto result = algo->execute(graph);
       // 输出 JSON ...
       delete algo;
   }
   ```

5. **在 `middleware_python/routes/graph.py` 添加新端点**（见 Python 规范）

6. **在 `tests/` 添加 Catch2 测试** `test_TriangleCount.cpp`

---

## 4. Python 编码规范

### 4.1 模块结构

```
middleware_python/
├── server.py          # 应用工厂 (create_app)
├── core/              # 配置、安全、异常、依赖注入
├── routes/            # API 路由 (每个文件一组相关端点)
├── services/          # 业务逻辑 (引擎调用、缓存、数据库查询)
├── models/            # Pydantic 请求/响应模式
├── db/                # 数据库客户端 (Lazy-Connect)
├── middleware/         # FastAPI/Starlette 中间件
├── auth/              # 认证授权模块
└── websockets/        # WebSocket 端点
```

### 4.2 Lazy-Connect 模式

所有数据库连接采用 "延迟连接" 模式。首次调用时建立连接，后续复用全局单例。连接失败返回 `None`，调用方负责降级处理。

文件 `db/redis.py` 是典型示例：
```python
_redis_async = None       # 全局单例缓存
_redis_async_failed = False  # 哨兵: 已尝试但连接失败

async def get_redis_async():
    if _redis_async is not None:   # 已有连接 → 直接返回
        return _redis_async
    if _redis_async_failed:        # 已知失败 → 立即返回 None
        return None
    # 尝试连接 ...
```

同样的模式也用于 `db/mysql.py`, `db/mongodb.py`, `db/neo4j.py`。

### 4.3 Cache-Aside 模式

文件 `services/cache.py` 实现标准的 Cache-Aside 模式：

1. **读**: 先查 Redis → 命中则返回 / 未命中则计算并写入缓存
2. **分布式锁**: 防止缓存击穿（多请求同时触发同一计算），使用 Redis `SET NX EX`
3. **缓存键版本化**: 如 `social_graph:pagerank:v3`，通过版本号管理缓存失效

```python
result = await cache_get_or_compute(
    "social_graph:pagerank:v3",      # 缓存键
    settings.cache_algorithm_ttl,    # TTL
    execute_command, "pagerank",     # 计算函数 + 参数
)
```

### 4.4 C++ 引擎 IPC

文件 `services/cpp_engine.py` 管理 C++ 引擎通信：

- **进程池模式**: 预派生 4 个子进程（`cpp_engine_pool_size`），通过 stdin/stdout 管道持续通信
- **回退模式**: 若进程池不可用，自动回退到 `subprocess.run()` 每次启动新进程
- **超时保护**: 单次计算超时自动回收进程并创建新进程替代
- **管道协议**: 每行 JSON（`{"command":"pagerank","args":[]}` 输入 → `{"status":"success",...}` 输出）

### 4.5 中间件栈

中间件注册顺序决定执行顺序（后注册的先执行）：

```
请求 → ErrorHandlerMiddleware → RequestLoggingMiddleware
     → RateLimitMiddleware → GZipMiddleware
     → CORSMiddleware → 路由处理 → 响应
```

### 4.6 添加新 API 端点 (标准步骤)

假设你要为 Triangle Count 添加端点：

1. **在 `models/graph.py` 添加响应模型**（若返回结构不同于现有模型）

2. **在 `routes/graph.py` 添加路由**：
   ```python
   @router.get("/triangle_count", response_model=AlgorithmResultResponse)
   async def get_triangle_count(
       current_user: dict = Depends(get_current_analyst_or_admin),
   ):
       settings = get_settings()
       result = await cache_get_or_compute(
           "social_graph:triangle_count:v1",
           settings.cache_algorithm_ttl,
           execute_command, "triangle_count",
       )
       log_operation("run_algorithm", current_user["user_id"], "triangle_count")
       return result
   ```

3. **在 `server.py` 的 `_register_routers()` 中确认路由已自动注册**（graph_router 已包含）

4. **在 `frontend_web/js/api.js` 添加前端调用方法**：
   ```javascript
   static async getTriangleCount() {
       return this.request('/triangle_count');
   }
   ```

5. **在 `frontend_web/js/app.js` 的加载流程中集成**（按要求）

---

## 5. 前端编码规范

### 5.1 模块架构

前端采用零框架 ES6 模块化架构，通过 `<script type="module">` 加载。8 个模块职责分明：

| 模块 | 类 | 职责 |
|------|----|------|
| `app.js` | `AppController` | 应用入口，编排所有模块，处理用户交互 |
| `api.js` | `APIService` | HTTP 请求封装（缓存/去重/重试/取消） |
| `graphEngine.js` | `Engine3D` | 3D 力导向图渲染（3d-force-graph 封装） |
| `state.js` | `Store` | 集中式事件驱动状态管理 |
| `charts.js` | `ChartDashboard` | Chart.js 统计仪表板 |
| `search.js` | `SearchManager` | 全局节点搜索 |
| `ranking.js` | `RankingManager` | 排行榜多指标切换 |
| `timeline.js` | `TimelineManager` | "宇宙大爆炸"渐进式渲染 |
| `ui.js` | `UIManager` | Toast 通知 / 加载屏幕 / 模态框 |
| `accessibility.js` | `AccessibilityManager` | 屏幕阅读器 / 键盘导航 |
| `config.js` | `CONFIG` | 配置常量（API 地址、色板） |

### 5.2 状态管理 (Store)

文件 `js/state.js` 实现发布/订阅模式的状态管理：

- **`store.get(key)`**: 获取当前值快照
- **`store.set(key, value)`**: 设置单个值，触发该 key 的监听器和全局监听器
- **`store.batch({key: val, ...})`**: 批量更新，仅触发一次全局通知
- **`store.on(key, callback)`**: 订阅特定 key 的变化，返回取消订阅函数
- **`store.onAny(callback)`**: 订阅所有状态变更

默认状态形状包含：图数据、算法结果、选中节点、搜索、排行榜、时间轴、UI 状态、WebSocket 状态、力场参数。

### 5.3 API 通信层

文件 `js/api.js` 的 `APIService` 提供：

- **内存缓存**: 可配置 TTL（拓扑 1 小时，算法结果 24 小时）
- **请求去重**: 相同请求不重复发出（`pendingRequests` Map）
- **自动重试**: 最多 2 次指数退避重试
- **AbortController**: 支持取消活跃请求

### 5.4 外部依赖

前端有两个外部库通过 CDN/本地加载：
- **`3d-force-graph`**: CDN (`unpkg.com`)，在 `index.html` 中以 `<script>` 标签加载
- **`Chart.js`**: 本地文件 (`js/chart.umd.min.js`)，在 `index.html` 中以 `<script>` 标签加载

这意味着不需要 npm install -- 直接打开 HTML 文件即可运行（需网络访问 CDN）。

### 5.5 添加新 UI 面板 (标准步骤)

1. **在 `index.html` 中添加面板的 HTML 结构**
2. **在 `css/components.css` 中添加面板样式**
3. **如需新的 JS 逻辑，创建新的 JS 模块**（如 `js/myPanel.js`）
4. **在 `app.js` 中导入并连接**：`import { MyPanel } from './myPanel.js';`
5. **绑定事件并集成到 AppController 生命周期**

---

## 6. 数据库架构

### MySQL (关系型)

6 张表定义在 `database/mysql/001_init_schema.sql`：

| 表名 | 用途 | 主键策略 |
|------|------|---------|
| `users` | 用户账户 | CHAR(36) UUID v4 |
| `sessions` | JWT Refresh Token 会话 | CHAR(36) UUID v4 |
| `saved_analyses` | 用户保存的分析配置 | CHAR(36) UUID v4 |
| `export_history` | 导出操作审计 | CHAR(36) UUID v4 |
| `system_config` | 运行时动态配置 | INT AUTO_INCREMENT |
| `api_keys` | API Key 管理 | CHAR(36) UUID v4 |

所有表使用 InnoDB 引擎，utf8mb4 字符集。UUID v4 作为主键防止枚举攻击并支持未来分库分表。

### MongoDB (文档型)

`database/mongodb/schema_design.js` 定义：
- `analysis_snapshots` -- 分析结果快照
- `operation_logs` -- 操作审计日志

### Redis (缓存)

缓存键策略定义在 `database/redis/cache_strategy.md` 和 `services/cache.py`：
- `social_graph:topology:v7` -- 拓扑结构
- `social_graph:{algorithm}:v{n}` -- 各算法结果
- `lock:compute:{cache_key}` -- 分布式锁
- `rate_limit:{client_id}:{window}` -- 限流计数

---

## 7. Git 规范

### 分支命名

| 前缀 | 用途 | 示例 |
|------|------|------|
| `feat/` | 新功能 | `feat/add-triangle-count` |
| `fix/` | Bug 修复 | `fix/cache-key-collision` |
| `refactor/` | 重构（无功能变更） | `refactor/extract-db-interface` |
| `docs/` | 文档更新 | `docs/api-reference` |
| `test/` | 测试补充 | `test/kcore-edge-cases` |
| `ci/` | CI/CD 变更 | `ci/add-docker-scan` |

### 提交信息格式

```
<type>: <简短描述>

[可选的详细说明]
```

Type 选项：`feat`, `fix`, `refactor`, `docs`, `test`, `ci`, `build`, `chore`

### PR 流程

1. 创建功能分支并推送
2. 打开 PR 到 `main` 分支
3. CI 自动运行 C++ 编译 + 测试 + Python pytest
4. 至少 1 人 Code Review
5. 合并 (Squash & Merge)

---

## 8. 测试规范

### C++ 测试 (Catch2 v3.4)

- 测试框架：Catch2 (通过 CMake `FetchContent` 自动下载)
- 测试文件：`backend_cpp/tests/` 目录下 10 个文件
- 运行：`cd backend_cpp/build && ctest --output-on-failure -C Release`
- CI 在 Ubuntu 和 Windows 上各运行一次完整测试套件

### Python 测试 (pytest + httpx)

- 测试文件：`middleware_python/tests/`
- 运行：`cd middleware_python && pytest tests/ -v`
- 使用 `httpx.AsyncClient` 进行异步 API 测试
- CI 在 Ubuntu 上运行 pytest

### 前端测试

- 前端目前无自动化测试
- 手动验证清单：
  1. 页面加载无 JS 错误（控制台）
  2. "载入核心数据集" 按钮可用
  3. 3D 节点可见
  4. 路径查询 (BFS/Dijkstra/DFS) 返回正确结果
  5. 仪表板图表可正常渲染
  6. 快捷键 (H, R, L, F, S, Space, Escape) 正常响应
  7. 雷达面板右击探测功能正常
  8. 数据导出 (JSON/CSV) 下载文件内容正确
