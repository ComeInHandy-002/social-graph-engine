# SocialGraph Pro -- 测试证据文档 (Test Evidence)

> 文档版本: 1.0.0 | 审计日期: 2026-05-02 | 系统状态: **从未运行 (Pre-Execution Audit)**

---

## 重要声明 -- 诚实性声明

**本系统 (SocialGraph Pro v3.0.0) 从未被启动过。** 没有服务器运行过，没有浏览器渲染过，没有数据库被连接过。所有测试脚本、基准测试框架、安全检查清单均已准备就绪，但尚未有任何实际执行证据。

本文档中:
- 标记为 **"已验证 (代码审查)"** 的内容：通过阅读源代码确认其存在与正确性
- 标记为 **"待执行 -- 需要运行系统"** 的内容：脚本已就绪，但必须在实时环境中执行才能获得结果
- 标记为 **"缺失"** 的内容：相关测试能力未被实现

**不包含任何编造的性能数字或测试结果。**

---

## 目录

1. [系统测试文档 (Pre-Execution Audit)](#1-系统测试文档)
2. [性能基准测试报告 (Pre-Computation)](#2-性能基准测试报告)
3. [安全测试结果 (Pre-Audit State)](#3-安全测试结果)
4. [部署验证步骤](#4-部署验证步骤)

---

## 1. 系统测试文档

### 1.1 测试资产全景表

| 测试层 | 框架 | 文件数 | 测试用例数 | 状态 | 能立即运行? |
|--------|------|--------|-----------|------|------------|
| C++ 单元测试 | Catch2 v3.4.0 | 10 个 .cpp 文件 | 11 个 TEST_CASE (含多个 SECTION) | CMake 配置完成 | 需要先编译 C++ 项目 |
| Python API 测试 | pytest + FastAPI TestClient | 3 个 .py 文件 | 13 个测试方法, 4 个测试类 | Mock 目标已修复 (commit 9f9f772) | 需要 pip install pytest |
| 负载测试 | Locust | 2 个 .py 文件 | 6 种场景 (21 个 @task 方法) | 脚本已就绪 | 需要运行中的 API 服务 |
| 前端 E2E 测试 | -- | 0 | 0 | **未实现** | 否 |

### 1.2 C++ 单元测试 -- 详细审计

**框架**: Catch2 v3.4.0 (通过 CMake FetchContent 拉取)

**CMake 配置** (`backend_cpp/CMakeLists.txt` 第 130-159 行):
- `FetchContent_Declare(Catch2 GIT_TAG v3.4.0)`
- 可执行文件 `graph_tests` 链接 `graph_algo` 和 `Catch2::Catch2WithMain`
- 集成 `CTest`: `add_test(NAME GraphEngineTests COMMAND graph_tests)`

**测试文件清单**:

| 文件名 | 测试内容 | TEST_CASE 数 | SECTION 数 | 代码审查结果 |
|--------|---------|-------------|-----------|-------------|
| `test_main.cpp` | Catch2 入口 (Catch2WithMain 处理) | 0 | 0 | 仅包含头文件, 正确 |
| `test_BFS.cpp` | BFS 最短路径查找 | 1 | 3 | 测试 A->F(4跳), A->C(2跳), 不存在节点 |
| `test_PageRank.cpp` | PageRank 全网权重计算 | 1 | 0 (4 asserts) | 验证 PR 值和为 1.0, B>A, D>F |
| `test_LPA.cpp` | LPA 社区发现 | 1 | 0 (4 asserts) | 验证三角形社区划分正确性 |
| `test_Dijkstra.cpp` | Dijkstra 带权最短路径 | 1 | 0 (3 asserts) | 验证 A->F 路径, X->Y 空路径 |
| `test_Betweenness.cpp` | Betweenness Centrality | 1 | 0 (5 asserts) | 验证 B>D>F, 叶子节点=0 |
| `test_ConnectedComponents.cpp` | 连通分量 | 1 | 0 (4 asserts) | 单图 1 分量 vs 双图 2 分量 |
| `test_KCore.cpp` | K-Core 分解 | 1 | 0 (5 asserts) | A/F=1, B/C>=2 核心 |
| `test_ClusteringCoeff.cpp` | 聚类系数 | 1 | 0 (范围断言循环) | 验证系数 [0,1] 范围 + A/F=0 |
| `test_GraphStats.cpp` | 图统计 JSON | 1 | 0 (4 asserts) | 验证 JSON 包含 nodes/edges/density/components |

**共享测试图** (`backend_cpp/tests/test_graph.h`):
```
  A -- B -- C -- D -- E -- F
       |_________|
  关键属性: 节点 B-C-D 形成三角形，A 和 F 是叶子节点
  6 节点, 6 条边
```

**总计**: 10 个 TEST_CASE (每个 1 个), 3 个 SECTION, 约 30+ 个独立断言。

**状态**: 待执行 -- 需要先编译 C++ 项目
```bash
cd backend_cpp
cmake -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build --config Release
ctest --test-dir build --output-on-failure
```

### 1.3 Python API 测试 -- 详细审计

**框架**: pytest + FastAPI TestClient + unittest.mock

**测试文件** (`middleware_python/tests/test_api.py`):

**测试类与方法统计**:

| 测试类 | 测试方法数 | 测试内容 | 代码行 |
|--------|-----------|---------|--------|
| `TestShortestPath` | 3 | BFS/Dijkstra/DFS 路径查询 | 6-48 |
| `TestAlgorithmEndpoints` | 6 | PageRank/Community/Betweenness/KCore/Clustering/Stats | 51-112 |
| `TestHealthCheck` | 3 | 健康检查 / 存活探测 / 就绪探测 | 114-139 |
| `TestCORS` | 1 | CORS 预检头验证 | 141-148 |

**API 端点覆盖**:
- `POST /api/v1/graph/shortest_path` (bfs / dijkstra / dfs 三种算法)
- `GET /api/v1/graph/pagerank`
- `GET /api/v1/graph/community`
- `GET /api/v1/graph/betweenness`
- `GET /api/v1/graph/kcore`
- `GET /api/v1/graph/clustering_coeff`
- `GET /api/v1/graph/stats`
- `GET /api/v1/health`
- `GET /api/v1/health/live`
- `GET /api/v1/health/ready`
- `OPTIONS /api/v1/graph/pagerank` (CORS)

**未覆盖的端点** (存在于 routes/graph.py 但测试中未出现):
- `GET /api/v1/graph/all` -- 全网拓扑
- `GET /api/v1/graph/influencers` -- Top 影响者
- `POST /api/v1/graph/ego_network` -- Ego Network
- `POST /api/v1/graph/shortest_path_neo4j` -- Neo4j 最短路径
- `GET /api/v1/graph/community_structure` -- 社区结构
- `GET /api/v1/graph/community_bridges` -- 社区桥接
- `POST /api/v1/graph/community_density` -- 社区密度
- `GET /api/v1/graph/stats_neo4j` -- Neo4j 统计
- `POST /api/v1/graph/recommendations` -- 好友推荐
- `POST /api/v1/graph/collaborative` -- 协同过滤
- `POST /api/v1/graph/knowledge-explore` -- 知识图谱探索
- `POST /api/v1/graph/sync_algorithms` -- 算法同步
- `GET /api/v1/export/{data_type}` -- 数据导出
- 所有 `/api/v1/admin/*` 端点
- 所有 `/api/v1/auth/*` 端点

**Fixture 配置** (`middleware_python/tests/conftest.py`):

| Fixture | 用途 | 状态 |
|---------|------|------|
| `client` | FastAPI TestClient, 模拟所有数据库不可用 | 已验证 (代码审查) -- commit 9f9f772 修复了 mock 目标路径 |
| `mock_run_cpp_engine` | 模拟 C++ 引擎执行 (patch `routes.graph.execute_command`) | 已验证 (代码审查) |
| `mock_redis` | 模拟 Redis 不可用 (patch `db.redis.get_redis_async`) | 已验证 (代码审查) |
| `mock_neo4j` | 模拟 Neo4j 不可用 (patch `services.neo4j_service.get_full_topology`) | 已验证 (代码审查) |

**conftest 环境变量模拟**:
- REDIS_HOST=localhost, REDIS_PORT=6379
- NEO4J_URI=bolt://localhost:7687, NEO4J_USER=neo4j, NEO4J_PASSWORD=password123
- CPP_ENGINE_PATH=/fake/path/graph_engine
- GRAPH_DATA_PATH=/fake/path/data.txt
- MYSQL_DSN=mysql+asyncmy://fake:fake@localhost:3306/test
- MONGO_URI=mongodb://fake:fake@localhost:27017

**状态**: 待执行 -- 需要先安装 pytest
```bash
cd middleware_python
pip install pytest pytest-asyncio httpx
python -m pytest tests/ -v
```

### 1.4 负载测试 -- 详细审计

**框架**: Locust

**locustfile.py 场景总结**:

| 场景编号 | 场景名 | 标签 | 目标用户数 | 运行时间 | think time | 目的 |
|---------|--------|------|-----------|---------|-----------|------|
| 1 | NormalLoad | `NormalLoad` | 50 | 30 分钟 | 1-3s | 正常负载基准 |
| 2 | PeakLoad | `PeakLoad` | 10->200 | 10 分钟 | 0.5-1s | 峰值负载/爬坡 |
| 3 | SustainedLoad | `SustainedLoad` | 100 | 2 小时 | 1-3s | 持续负载/内存泄漏 |
| 4 | CacheFailure | `CacheFailure` | 30 | 10 分钟 | 0.5-1.5s | Redis 不可用回退 |
| 5 | DatabaseFailure | `DatabaseFailure` | 30 | 10 分钟 | 0.5-1.5s | Neo4j 不可用降级 |
| 6 | MixedWorkload | `MixedWorkload` | 80 | 20 分钟 | 0.5-2s | 混合读写全覆盖 |

**6 个 User 类**:
1. `NormalLoadUser` -- 正常负载, wait_time=1-3s, weight=10
2. `PeakLoadUser` -- 峰值负载, wait_time=0.5-1s, weight=10
3. `SustainedLoadUser` -- 持续负载, wait_time=1-3s, weight=10
4. `CacheFailureUser` -- 缓存故障, wait_time=0.5-1.5s, weight=10
5. `DatabaseFailureUser` -- 数据库故障, wait_time=0.5-1.5s, weight=10
6. `MixedWorkloadUser` -- 混合负载, wait_time=0.5-2s, weight=10

**性能断言** (`@events.test_stop`):
- 错误率 < 1%
- 总请求数 > 0 (服务未崩溃)
- 如果有 FAIL 项, 设置 `environment.process_exit_code = 1` 供 CI 判断

**WebSocket 测试** (仅 MixedWorkload 场景):
- 使用标准库 `websockets` 进行连接级测试
- 注意: `websockets` 库使用需要 `pip install websockets`, 且 Locust 原生不支持 WebSocket

**run_all_scenarios.py 编排器**:
- 6 场景顺序执行
- 启动前健康检查 `GET /api/v1/health`
- 场景 4/5 有前置/后置脚本 (启停 Redis/Neo4j)
- 场景间 60 秒冷却间隔
- 支持 `--fail-fast` 提前终止
- 支持 `--scenarios` 选择性执行
- 支持 `--skip-health-check` 跳过健康检查
- 输出到 `tests/load/reports/` 目录 (CSV + HTML)

**状态**: 待执行 -- 需要运行中的 API 服务
```bash
# 先启动服务: cd middleware_python && python server.py
# 再执行负载测试:
python tests/load/run_all_scenarios.py --host http://127.0.0.1:8000
# 或单个场景:
locust -f tests/load/locustfile.py --host=http://127.0.0.1:8000 --headless -u 50 -r 5 --run-time 30m --tags NormalLoad --csv=reports/normal_load
```

### 1.5 前端 E2E 测试 -- 审计结果

**状态: 未实现。**

在 `frontend_web/` 目录下未找到任何测试文件:
- 无 Jest 测试 (`*.test.js` / `*.test.jsx`)
- 无 Cypress 测试 (`*.spec.js` / `*.cy.js`)
- 无 Playwright 测试
- 无 `frontend_web/tests/` 目录

前端复用模块化 ES6 (`api.js`, `graphEngine.js`, `app.js`) 结构，但零测试覆盖。建议最低实现:
- `api.js` 的单元测试 (fetch mock)
- `graphEngine.js` 的数据变换测试
- 关键用户路径的 E2E 测试 (页面加载 -> 图渲染 -> 右键探测)

**状态**: 缺失 -- 建议未来添加

### 1.6 测试覆盖率差距分析

```
已覆盖:
  C++ 单元测试:  10/10 算法 (完备)
  Python API:    11/31 端点 (35%)
  负载测试:      6 种场景 (6 种用户行为模式)
  前端:          0/全部 (0%)

待补充:
  [ ] Python: auth 端点测试 (注册/登录/刷新/登出)
  [ ] Python: admin 端点测试 (配置/指标/缓存)
  [ ] Python: export 端点测试
  [ ] Python: Neo4j 依赖端点测试 (influencers/ego_network/recommendations)
  [ ] Python: WebSocket 连接测试
  [ ] Python: 认证中间件集成测试 (401/403 场景)
  [ ] 前端: JavaScript 单元测试
  [ ] 前端: E2E 用户流程测试
  [ ] 集成: 端到端 (请求 -> C++ 引擎 -> 响应) 测试
```

---

## 2. 性能基准测试报告

### 2.1 基准测试基础设施

#### 基准测试脚本 (`middleware_python/benchmark.py`)

- **功能**: 自动生成随机图数据，调用 C++ 引擎执行算法，提取 `time_ms` 测量值
- **测试规模**: 10K / 50K / 100K 条边 (3 个等级)
- **测试算法**: PageRank, LPA Community Detection (2 个算法)
- **数据生成**: 随机节点对 (node count = edges/5)
- **引擎调用**: `subprocess.run` 捕获 stdout JSON, 读取 `time_ms` 字段
- **路径解析**: 优先 CPP_ENGINE_PATH 环境变量，回退自动探测多个路径

#### C++ 引擎内置计时 (`backend_cpp/src/main.cpp`)

所有 9 个算法命令均包含内置高精度计时:
```cpp
auto t_start = std::chrono::high_resolution_clock::now();
// ...算法执行...
auto t_end = std::chrono::high_resolution_clock::now();
long long time_ms = std::chrono::duration_cast<std::chrono::milliseconds>(t_end - t_start).count();
// 输出到 JSON: {"status":"success","time_ms":<value>, ...}
```

**带 time_ms 输出的命令**:
- `shortest_path` / `dijkstra_path`
- `echo_chamber` (DFS)
- `pagerank`
- `community` (LPA)
- `betweenness`
- `connected_components`
- `kcore`
- `clustering_coeff`
- `graph_stats`

#### 基准测试框架 -- 待执行模板

当前 `benchmark.py` 只测试 PageRank 和 LPA 两个算法。建议扩展为完整基准测试套件:

```python
# 建议的扩展算法列表
algorithms = [
    "pagerank",            # PageRank
    "community",           # LPA 社区发现
    "betweenness",         # Betweenness Centrality
    "connected_components",# 连通分量
    "kcore",              # K-Core 分解
    "clustering_coeff",   # 聚类系数
    "graph_stats",        # 图统计
]
```

### 2.2 基准测试结果模板 (待填充)

**所有结果标记为"待执行" -- 无编造数据。**

#### C++ 引擎基准测试 (通过 benchmark.py)

| 算法 | 10K 边 (ms) | 50K 边 (ms) | 100K 边 (ms) | 状态 |
|------|-----------|-----------|------------|------|
| PageRank | ___ms | ___ms | ___ms | 待执行 -- 需要编译并运行 benchmark.py |
| LPA Community | ___ms | ___ms | ___ms | 待执行 |
| Betweenness | ___ms | ___ms | ___ms | 待执行 (需要扩展 benchmark.py) |
| Connected Components | ___ms | ___ms | ___ms | 待执行 (需要扩展 benchmark.py) |
| K-Core | ___ms | ___ms | ___ms | 待执行 (需要扩展 benchmark.py) |
| Clustering Coefficient | ___ms | ___ms | ___ms | 待执行 (需要扩展 benchmark.py) |
| Graph Stats | ___ms | ___ms | ___ms | 待执行 (需要扩展 benchmark.py) |

#### C++ 引擎路径查询基准测试

| 算法 | 10K 边 (ms) | 50K 边 (ms) | 100K 边 (ms) | 状态 |
|------|-----------|-----------|------------|------|
| BFS (shortest_path) | ___ms | ___ms | ___ms | 待执行 |
| Dijkstra | ___ms | ___ms | ___ms | 待执行 |
| DFS (echo_chamber) | ___ms | ___ms | ___ms | 待执行 |

#### API 网关端到端延迟 (网络 + C++ 引擎)

| 端点 | P50 (ms) | P95 (ms) | P99 (ms) | 状态 |
|------|---------|---------|---------|------|
| GET /api/v1/graph/pagerank | ___ms | ___ms | ___ms | 待执行 -- 需要负载测试 |
| GET /api/v1/graph/community | ___ms | ___ms | ___ms | 待执行 |
| POST /api/v1/graph/shortest_path | ___ms | ___ms | ___ms | 待执行 |
| GET /api/v1/graph/betweenness | ___ms | ___ms | ___ms | 待执行 |
| GET /api/v1/graph/all | ___ms | ___ms | ___ms | 待执行 |

#### 负载测试吞吐量目标

| 场景 | 目标 RPS | 目标 P95 | 目标错误率 | 实际 RPS | 实际 P95 | 实际错误率 | 状态 |
|------|---------|---------|-----------|---------|---------|-----------|------|
| NormalLoad (50u) | >10 | <2000ms | <1% | ___ | ___ms | ___% | 待执行 |
| PeakLoad (200u) | >30 | <5000ms | <5% | ___ | ___ms | ___% | 待执行 |
| SustainedLoad (100u) | >20 | <3000ms | <1% | ___ | ___ms | ___% | 待执行 |
| CacheFailure (30u) | >5 | <5000ms | <10% | ___ | ___ms | ___% | 待执行 |
| DatabaseFailure (30u) | >5 | <5000ms | <20% | ___ | ___ms | ___% | 待执行 |
| MixedWorkload (80u) | >15 | <3000ms | <3% | ___ | ___ms | ___% | 待执行 |

#### 推荐前端基准测试

| 指标 | 节点数 < 500 | 节点数 500-2000 | 节点数 > 2000 | 状态 |
|------|------------|---------------|-------------|------|
| 首屏渲染 FPS | ___fps | ___fps | ___fps | 待执行 -- 前端未运行过 |
| 力导向稳定时间 | ___ms | ___ms | ___ms | 待执行 |
| 右键邻居探测延迟 | ___ms | ___ms | ___ms | 待执行 |
| 内存占用 | ___MB | ___MB | ___MB | 待执行 |

### 2.3 基准测试执行命令 (就绪)

```bash
# 1. 编译 C++ 引擎
cd backend_cpp
cmake -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build --config Release

# 2. 运行 Python 基准测试
cd middleware_python
python benchmark.py

# 3. 运行负载测试 (需要先启动服务)
python server.py &
python -m tests.load.run_all_scenarios --host http://127.0.0.1:8000

# 4. 手动单个算法基准测试
./backend_cpp/build/graph_engine facebook_combined.txt pagerank
# 输出: {"status":"success","time_ms":<实际值>,"data":[...]}
```

---

## 3. 安全测试结果

### 3.1 安全审计历史

**已知安全修复** (commit `9f9f772`, 2026-05-02):
```
fix: 修复 Reality Checker 识别的 7 个 P0 安全与稳定性阻塞项

1. 移除损坏的 C++ 进程池（main.cpp 无 --interactive 模式），统一使用已验证的 subprocess
2. 修复 pytest conftest.py mock 目标路径（旧 server.* -> 新 routes.* / db.*）
3. 消除所有硬编码凭据：JWT/MySQL/Neo4j/MongoDB 默认值清空，生产环境启动强制检查
4. 登录/注册从限流豁免列表移除，新增 IP 级限流 + 5 次失败锁定 15 分钟
5. CORS allow_origins 改为环境自适应（生产白名单 / 开发 *）
6. WebSocket 强制 JWT 认证，拒绝匿名连接
7. 前端 3 处 innerHTML XSS 添加 _escapeHtml 转义 + CSS 颜色值校验
```

变更涉及 8 个文件:
- `frontend_web/js/app.js` (+40/-0 行)
- `middleware_python/auth/service.py` (+126 行)
- `middleware_python/core/config.py` (+78 行)
- `middleware_python/middleware/rate_limiter.py` (+4/-0 行)
- `middleware_python/server.py` (+21 行)
- `middleware_python/services/cpp_engine.py` (-230 行, 移除损坏进程池)
- `middleware_python/tests/conftest.py` (+29 行)
- `middleware_python/websockets/analysis_ws.py` (+25 行)

### 3.2 漏洞严重性分类

| 严重性 | 数量 | 说明 | 状态 |
|--------|------|------|------|
| P0 (Critical) | 7 | 安全与稳定性阻塞项 | **已修复** (commit 9f9f772) |
| High | 0 (在 P0 修复中全覆盖) | -- | -- |
| Medium | 未知 | 未执行过完整安全审计 | 待执行 |
| Low | 未知 | 未执行过完整安全审计 | 待执行 |
| Info | 未知 | 未执行过完整安全审计 | 待执行 |

### 3.3 已实现的安全控制 (代码审查确认)

| 安全控制 | 实现位置 | 审查状态 |
|---------|---------|---------|
| JWT 访问令牌 + 刷新令牌 | `core/security.py:48-109` | 已验证 -- HS256 签名, 含 jti/jti 唯一标识 |
| bcrypt 密码哈希 (cost=12) | `core/security.py:29-41` | 已验证 |
| API Key 认证 (SHA-256 哈希) | `core/security.py:203-228` | 已验证 |
| Token 黑名单 (Redis) | `core/security.py:145-171` | 已验证 -- Redis 不可用时降级放行 |
| Token Family 吊销 | `core/security.py:174-196` | 已验证 -- 版本号递增机制 |
| 密码强度校验 | `core/security.py:234-254` | 已验证 -- 8字符/大小写/数字 |
| 开发环境自动生成密钥 | `core/config.py:205-207` | 已验证 |
| 生产环境强制密钥配置 | `core/config.py:232-238` | 已验证 -- 不配置则 RuntimeError |
| 不安全默认值检测 | `core/config.py:124-161` | 已验证 -- 检测 14 个弱密码模式 |
| CORS 环境自适应 | `server.py` | 已验证 -- 生产白名单, 开发通配符 |
| IP 级登录限流 + 锁定 | `middleware/rate_limiter.py` | 已验证 -- 5 次失败锁定 15 分钟 |
| WebSocket JWT 强制认证 | `websockets/analysis_ws.py` | 已验证 -- 拒绝匿名连接 |
| 前端 XSS 防护 | `frontend_web/js/app.js` | 已验证 -- _escapeHtml + CSS 校验 |

### 3.4 OWASP Top 10 (2021) 安全测试覆盖矩阵

| OWASP 类别 | 测试存在? | 自动化? | 代码中控制 | 审查状态 |
|-----------|----------|---------|----------|---------|
| A01: Broken Access Control | 部分 (角色装饰器在 `core/dependencies.py`) | 否 -- 无测试 | RBAC (admin/analyst/viewer) via JWT role claim | 需要集成测试 |
| A02: Cryptographic Failures | 否 | 否 | bcrypt, JWT HS256, API Key SHA-256 | 需要密钥管理审计 |
| A03: Injection | 否 | 否 | Neo4j 参数化查询 (代码中看), MySQL asyncmy 参数化 | 需要渗透测试 |
| A04: Insecure Design | 否 | 否 | 限流/键命名/降级策略 设计文档完整 | 需要威胁建模 |
| A05: Security Misconfiguration | 部分 (CORS 测试 1 个) | 是 (pytest) | 生产环境强制密钥检查, insecure 模式检测 | 基本覆盖 |
| A06: Vulnerable Components | 否 | 否 | -- | 需要 SCA/依赖扫描 |
| A07: Auth Failures | 部分 (仅测试健康检查) | 否 -- 无 auth 测试 | JWT/API Key/密码强度/登录锁定 | 需要 auth 测试 |
| A08: Software Integrity Failures | 否 | 否 | -- | 需要 CI/CD 完整性检查 |
| A09: Logging & Monitoring Failures | 否 | 否 | `X-Request-ID` trace header, 慢查询日志 | 需要日志审计 |
| A10: SSRF | 否 | 否 | -- | 需要 SSRF 测试 |
| API1: Broken Object Level Auth | 否 | 否 | -- | **关键缺失** -- 需要 BOLA 测试 |
| API2: Broken Authentication | 部分 | 否 | JWT 验证/黑名单/吊销 | 需要 token 操作测试 |
| API3: Excessive Data Exposure | 否 | 否 | Response model 定义了返回字段 | 需要数据泄露测试 |
| API4: Lack of Resources | 部分 | 是 (Locust 负载) | 限流配置 + 慢查询阈值 | 需要速率限制测试 |
| API5: Broken Function Level Auth | 部分 (角色装饰器) | 否 | RBAC decorators | 需要权限矩阵测试 |
| API8: Injection | 否 | 否 | -- | 需要 API 模糊测试 |
| API9: Improper Assets Mgmt | 否 | 否 | API 版本 `/api/v1/` | 需要文档 vs 实现审计 |
| API10: Unsafe Consumption | 否 | 否 | -- | 需要第三方 API 安全性审计 |

### 3.5 安全测试差距 -- 急需补充

1. **认证测试** (A07): 无 `POST /api/v1/auth/login`、`POST /api/v1/auth/register`、`POST /api/v1/auth/refresh`、`POST /api/v1/auth/logout` 的测试
2. **授权测试** (A01, API5): 无角色权限级联测试 (viewer 不能调 admin 端点)
3. **注入测试** (A03): 无 SQL 注入、NoSQL 注入、命令注入的负面测试用例
4. **速率限制测试** (API4): 无超出速率限制后获得 429 响应的验证
5. **前端安全测试**: 无 XSS 测试、无 CSRF 测试、无 CSP 头检查
6. **依赖安全扫描**: 无 SCA 工具集成 (无 dependabot/renovate/snyk)
7. **密钥扫描**: 无 git-secrets/truffleHog 预提交钩子

### 3.6 CORS 测试 (代码中唯一的安全测试)

`test_api.py` 第 141-148 行 -- TestCORS.test_cors_headers:
```python
def test_cors_headers(self, client):
    response = client.options("/api/v1/graph/pagerank", headers={
        "Origin": "http://localhost",
        "Access-Control-Request-Method": "GET"
    })
    assert response.status_code in [200, 405]
```

**审查意见**: 这是一个基本存在性检查，不是完整的安全测试。需要补充:
- 验证 Access-Control-Allow-Origin 响应头
- 验证非白名单 Origin 被拒绝
- 验证 Access-Control-Allow-Methods 受限

---

## 4. 部署验证步骤

### 4.1 部署前检查清单 (Pre-Flight)

#### 环境变量检查

| 环境变量 | 用途 | 必须? | 默认值安全性 | 状态 |
|---------|------|-------|------------|------|
| `SGP_JWT_SECRET_KEY` | JWT 签名密钥 | **是 (生产)** | 开发环境自动生成 `dev_` 前缀 | 需要设置 >= 32 字符随机值 |
| `SGP_NEO4J_PASSWORD` | Neo4j 数据库密码 | **是 (生产)** | 空值被拒绝 | 需要设置 |
| `SGP_MYSQL_PASSWORD` | MySQL 数据库密码 | **是 (生产)** | 空值被拒绝 | 需要设置 |
| `SGP_MONGODB_URI` | MongoDB 连接字符串 | **是 (生产)** | 空值被拒绝 | 需要设置 |
| `SGP_REDIS_PASSWORD` | Redis 认证密码 | 建议 | 空 = 无密码 | 建议设置 |
| `SGP_ENVIRONMENT` | 环境标识 | 是 | `development` | 生产设为 `production` |
| `SGP_DEBUG` | 调试模式 | 是 | `false` | 生产必须为 `false` |
| `SGP_LOG_LEVEL` | 日志级别 | 否 | `INFO` | 生产用 `INFO` 或 `WARNING` |
| `CPP_ENGINE_PATH` | C++ 引擎可执行文件路径 | 否 | 自动探测 | 确保路径正确 |
| `GRAPH_DATA_PATH` | 图数据文件路径 | 否 | 自动探测 | 确保路径正确 |

#### 数据库准备

- [ ] Neo4j 已安装并运行 (bolt:// 端口可达)
- [ ] Neo4j 中已导入图数据 (或 C++ 文件模式可用)
- [ ] MySQL 已安装并运行 (端口 3306 可达)
- [ ] MySQL 数据库 `socialgraph` 已创建
- [ ] MySQL 用户 `socialgraph` 已创建并授予权限
- [ ] MySQL 表已创建 (或 `/api/v1/admin/schema/init` 自动创建)
- [ ] MongoDB 已安装并运行
- [ ] MongoDB 用户已创建
- [ ] MongoDB 集合索引已创建 (按 `db/mongodb.py` 中的 35 个索引定义)
- [ ] Redis 已安装并运行 (端口 6379 可达)
- [ ] Redis 认证已配置 (requirepass)

#### 应用配置

- [ ] `.env` 文件已创建且包含所有必要配置
- [ ] `.env` 文件已排除在版本控制之外 (`.gitignore` 中已确认)
- [ ] C++ 引擎已编译 (Release 模式)
- [ ] C++ 引擎路径在 `CPP_ENGINE_PATH` 或自动探测范围内
- [ ] `facebook_combined.txt` 数据文件存在于 `GRAPH_DATA_PATH` 或自动探测范围内
- [ ] CORS origins 已配置为生产环境域名 (非 `*`)
- [ ] SSL/TLS 证书已安装并配置

#### 运行时准备

- [ ] Python 3.10+ 已安装
- [ ] 所有 Python 依赖已安装 (`pip install -r requirements.txt` 或等价)
- [ ] Docker 镜像已构建 (如果使用 Docker 部署)
- [ ] Docker 镜像已推送到注册表
- [ ] 监控系统 (Prometheus/Grafana) 已配置 (可选)
- [ ] 日志聚合系统已配置 (可选)
- [ ] 备份策略已制定并测试 (数据库 + 配置文件)

#### 预提交检查

- [ ] 所有 C++ 单元测试通过 (`ctest --test-dir build`)
- [ ] 所有 Python 测试通过 (`pytest tests/ -v`)
- [ ] 没有硬编码的秘密 (运行 `git secrets --scan`)
- [ ] 没有已知的高危依赖漏洞 (运行 `pip-audit` 或 `safety check`)
- [ ] C++ 编译无警告 (GCC `-Wall -Wextra` 或 MSVC `/W4`)
- [ ] Python linting 通过 (无严重问题)

### 4.2 部署后验证 (Post-Deployment)

#### 冒烟测试 (Smoke Test)

##### 自动化冒烟测试脚本 (`scripts/smoke_test.sh`)

```bash
#!/bin/bash
# SocialGraph Pro -- 部署冒烟测试脚本
# 用法: bash scripts/smoke_test.sh [http://127.0.0.1:8000]

BASE_URL="${1:-http://127.0.0.1:8000}"
PASS=0
FAIL=0
TOTAL=0

check() {
    local desc="$1"
    local method="$2"
    local url="$3"
    local expected_code="$4"
    local data="${5:-}"

    TOTAL=$((TOTAL + 1))
    local code
    if [ -z "$data" ]; then
        code=$(curl -s -o /dev/null -w "%{http_code}" -X "$method" "$BASE_URL$url" --max-time 10)
    else
        code=$(curl -s -o /dev/null -w "%{http_code}" -X "$method" "$BASE_URL$url" \
            -H "Content-Type: application/json" -d "$data" --max-time 10)
    fi

    if [ "$code" = "$expected_code" ]; then
        echo "  [PASS] $desc (got $code)"
        PASS=$((PASS + 1))
    else
        echo "  [FAIL] $desc (expected $expected_code, got $code)"
        FAIL=$((FAIL + 1))
    fi
}

echo "============================================"
echo "SocialGraph Pro -- 部署冒烟测试"
echo "目标: $BASE_URL"
echo "============================================"

# ── 健康检查 ────────────────────────────
echo ""
echo "[1] 健康检查端点"
check "Health main"         "GET" "/api/v1/health"           "200"
check "Health liveness"     "GET" "/api/v1/health/live"      "200"
check "Health readiness"    "GET" "/api/v1/health/ready"     "200"

# ── 图 API (公开) ──────────────────────
echo ""
echo "[2] 图 API -- 公开端点"
check "Stats"               "GET" "/api/v1/graph/stats"      "200"
check "Topology (all)"      "GET" "/api/v1/graph/all"        "200"

# ── 图 API (算法) ──────────────────────
echo ""
echo "[3] 图 API -- 算法端点"
check "PageRank"            "GET" "/api/v1/graph/pagerank"   "200"
check "Community (LPA)"    "GET" "/api/v1/graph/community"  "200"
check "Betweenness"         "GET" "/api/v1/graph/betweenness" "200"
check "Connected Components" "GET" "/api/v1/graph/connected_components" "200"
check "K-Core"              "GET" "/api/v1/graph/kcore"      "200"
check "Clustering Coeff"    "GET" "/api/v1/graph/clustering_coeff" "200"

# ── 路径查询 ──────────────────────────
echo ""
echo "[4] 路径查询"
check "Shortest Path"       "POST" "/api/v1/graph/shortest_path" "200" \
    '{"start_node":"1","target_node":"3","algorithm":"bfs"}'

# ── Neo4j 依赖端点 ────────────────────
echo ""
echo "[5] Neo4j 依赖端点"
check "Influencers"         "GET" "/api/v1/graph/influencers?limit=5" "200"

# ── 数据导出 ──────────────────────────
echo ""
echo "[6] 数据导出"
check "Export PageRank CSV" "GET" "/api/v1/export/pagerank?format=csv" "200"

# ── 结果汇总 ──────────────────────────
echo ""
echo "============================================"
echo "测试结果汇总"
echo "============================================"
echo "  通过: $PASS / $TOTAL"
echo "  失败: $FAIL / $TOTAL"
echo ""

if [ $FAIL -gt 0 ]; then
    echo ">>> 部署验证失败! 请检查上述 FAIL 项。"
    exit 1
else
    echo ">>> 部署验证通过! 所有关键端点响应正常。"
    exit 0
fi
```

#### 前端冒烟检查 (手动 -- 需要浏览器)

- [ ] `http://<host>:8000/` 前端页面加载成功 (无控制台错误)
- [ ] 3D 力导向图渲染正确 (节点 + 连线可见)
- [ ] 图可以拖拽旋转/缩放 (力导向交互正常)
- [ ] 右键节点显示邻居列表 (邻居探测功能)
- [ ] 统计面板数据非空 (如果仪表板已实现)
- [ ] WebSocket 连接状态为已连接 (如果启用)
- [ ] CORS 预检通过 (浏览器 Network 标签无红色 CORS 错误)
- [ ] 检查浏览器 Console 无 JavaScript 异常
- [ ] 检查 Network 标签中 API 请求均返回 200
- [ ] 测试移动端响应式布局 (如果支持)

#### 后端健康检查

- [ ] `GET /api/v1/health` 返回所有组件状态
  - [ ] `cpp_engine` 状态为 `healthy`
  - [ ] `redis` 状态为 `healthy` 或 `degraded`
  - [ ] `neo4j` 状态为 `healthy` 或 `degraded`
  - [ ] `mysql` 状态为 `healthy` 或 `degraded`
  - [ ] `mongodb` 状态为 `healthy` 或 `degraded`
- [ ] `GET /api/v1/health/live` 返回 `{"status":"alive"}`
- [ ] `GET /api/v1/health/ready` 返回 `{"status":"ready"}`

#### 性能验证

- [ ] 首次 `GET /api/v1/graph/pagerank` 响应时间 < 10 秒 (冷启动)
- [ ] 第二次 `GET /api/v1/graph/pagerank` 响应时间 < 2 秒 (Redis 缓存命中)
- [ ] `GET /api/v1/graph/stats` 响应时间 < 2 秒
- [ ] Redis 缓存命中率 > 0% (验证缓存生效)

#### 安全验证

- [ ] JWT 密钥非默认值 (`grep SGP_JWT_SECRET_KEY .env` 非空非弱密码)
- [ ] 生产环境 `SGP_ENVIRONMENT=production`
- [ ] 生产环境 `SGP_DEBUG=false`
- [ ] CORS 配置为生产域名 (非 `*`)
- [ ] Redis 已配置认证 (如适用)
- [ ] 数据库密码非默认值
- [ ] HTTPS 已启用 (TLS 1.2+)

### 4.3 回滚计划

如果部署后冒烟测试失败:

1. **记录失败端点**: 哪些端点返回非 200 响应?
2. **检查日志**: `server.py` 的输出 + C++ 引擎的 stderr 输出
3. **检查环境变量**: 确认所有 `SGP_*` 变量已正确设置
4. **检查数据库连通性**: 逐一验证 Neo4j / MySQL / MongoDB / Redis
5. **检查 C++ 引擎**: 手动执行 `graph_engine facebook_combined.txt pagerank` 验证 JSON 输出
6. **回滚**: 如果无法快速修复, 回滚到上一个已知良好的部署版本
7. **记录**: 记录失败原因和修复方案供后续参考

---

## 附录 A: 文档变更记录

| 版本 | 日期 | 变更 | 作者 |
|------|------|------|------|
| 1.0.0 | 2026-05-02 | 初始创建, Pre-Execution 审计 | Evidence Collector (EvidenceQA) |

## 附录 B: 审查方法论

本文档通过以下方法生成:

1. **源代码审查**: 读取 C++ `CMakeLists.txt`, 10 个 `test_*.cpp` 文件, `test_graph.h` 头文件
2. **源代码审查**: 读取 Python `test_api.py`, `conftest.py`, `benchmark.py`
3. **源代码审查**: 读取 Locust `locustfile.py`, `run_all_scenarios.py`
4. **源代码审查**: 读取 `main.cpp` (内置计时), `core/security.py` (认证模块), `core/config.py` (配置)
5. **Git 历史审查**: 审查 commit `9f9f772` (7 个 P0 安全修复)
6. **文件存在性检查**: 确认前端目录无测试文件

**明确未做**:
- 没有运行任何编译或测试
- 没有执行任何性能基准测试
- 没有进行渗透测试或安全扫描
- 没有启动服务器或连接数据库
- 没有在浏览器中渲染前端

所有"待执行"标记表示相应的测试脚本已准备就绪，但尚未在实时环境中运行过。
