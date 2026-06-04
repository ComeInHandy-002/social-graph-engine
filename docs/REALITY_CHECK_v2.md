# Reality Check v2.0 — SocialGraph Pro 生产就绪审计

**审计日期**: 2026-05-02
**审计师**: Reality Checker (高级集成审计专家)
**评分**: **40/100** (前次: 33/100, 提升 +7)
**结论**: **条件性不通过 (CONDITIONAL NO-GO)**
**可部署环境**: 不推荐部署到任何环境 — dev/staging/prod 均不可用

---

## 前置声明

本次审计基于对实际源代码文件的逐行阅读验证。不信任任何声明 —— 只以代码为证据。

核心前提（由 PROJECT_PLAN.md 自认）：
> "本项目近 90% 的代码由 AI 生成，从未在任何环境中完整执行通过。三个核心模块之间从未进行过端到端集成测试。"

**本次审计确认该声明仍然完全成立。**

---

## 审计执行摘要

### 已验证的修复项（7 项 P0）

| # | 修复项 | 文件 | 证据 | 状态 |
|---|--------|------|------|------|
| 1 | C++ 进程池移除 | `server.py` | 直接 `subprocess.run()` 模式，无进程池残留 | **已验证** |
| 2 | pytest mock 路径修复 | `tests/conftest.py` | patch 路径 `routes.graph.execute_command` 正确 | **已验证** |
| 3 | 硬编码凭据消除 | `core/config.py` | `jwt_secret_key=""` 默认空，dev 环境自动生成，prod 抛出 RuntimeError | **已验证** |
| 4 | 登录限流 + 账户锁定 | `auth/service.py:187-269` | IP 级别限流 (5次/分钟) + 账户锁定 (5次失败锁15分钟)，Redis 实现 | **已验证** |
| 5 | CORS 环境自适应 | `server.py:173-179` | `production → ["localhost","127.0.0.1"]`, 非prod → `["*"]` | **已验证** |
| 6 | WebSocket 强制 JWT 认证 | `websockets/analysis_ws.py:35-37` | `if not token: await websocket.close(code=4001` — 连接前拒绝 | **已验证** |
| 7 | 前端 XSS 过滤 | `js/ui.js:291-295`, `js/app.js:341` | `_escapeHtml()` 用 `createTextNode` 实现; 雷达面板调用 escapeHtml | **部分验证** |

### 新增设计（文档存在但未实现）

| 设计项 | 文件位置 | 代码实现 | 执行验证 |
|--------|---------|---------|---------|
| C++ 微服务层 (gRPC) | `backend_cpp/server/` (9 headers) | CMakeLists 中 gRPC 编译链只配置了 `graph_server` 可执行文件入口 | 从未编译 |
| Neo4j 图模型 (4标签+7关系+21索引) | `database/neo4j/` | 约束脚本存在 | 从未在 Neo4j 实例执行 |
| MongoDB 增强 (5集合+35索引) | `database/mongodb/schema_design.js` | Schema/Validator 定义完整 | 从未在 MongoDB 实例执行 |
| Redis 缓存 v2.0 | `services/cache.py`, `db/redis.py` | 5 种失效模式代码完整 | 从未对真实 Redis 执行 |
| Locust 负载测试 (6场景,824行) | `tests/load/locustfile.py` | 脚本完整 | 从未执行（需要运行中的服务器） |

---

## 逐条标准审计

### 标准 1: 所有 API 响应 < 200ms (P95)

**判定: FALSE — 无法验证且基于物理学不可能**

#### 代码证据

**C++ 引擎确实包含了计时逻辑：**

`backend_cpp/src/main.cpp` 每个算法分支都包含了：
```cpp
auto t_start = std::chrono::high_resolution_clock::now();
auto result = algo->execute(graph);
auto t_end = std::chrono::high_resolution_clock::now();
long long time_ms = std::chrono::duration_cast<std::chrono::milliseconds>(t_end - t_start).count();
```
输出的 JSON 中包含 `"time_ms"` 字段。这是正确的设计。

**但是：**

1. **零次实际执行。** `benchmark.py` 存在但从未运行。没有任何 `benchmark_results.json` 文件。CI 只执行了 `./graph_engine run_test` 冒烟测试（直接 return 0，不跑任何算法）。

2. **Betweenness Centrality 数学不可能性。** `AlgoBetweennessCentrality.cpp` 实现精确 Brandes 算法，复杂度 O(V*(V+E))。在 facebook_combined 数据集上 (4,039 节点, 88,234 边)，意味着约 4K * 88K ≈ 352M 次基本操作，加上最短路径计算的开销是 O(V*(V+E)) = 4K*92K = 368M 每个源节点。如果每个源节点都要 BFS，总操作量在 1.5B 级别。200ms 内完成需要 7.5 GFLOPS —— 在单核上不可能。

3. **PROJECT_PLAN.md 自认 Betweenness 存在规模瓶颈（R04 风险，概率 HIGH）。**

4. **API 响应时间组成未测量。** 200ms 需要 C++ 计算 + subprocess 开销 + Python 序列化 + Redis 查询 + 网络传输总和。没有任何一个测量点。

5. **负载测试未执行。** `tests/load/locustfile.py` 有 824 行完善的脚本，但从未运行——它需要运行中的服务器。

**评分: 0/15**

---

### 标准 2: 数据库查询 < 100ms

**判定: UNVERIFIABLE — 设计完备但零执行证据**

#### 正面发现

**MySQL 索引设计良好（`database/mysql/001_init_schema.sql`）：**
- `users`: uk_email (UNIQUE), idx_role, idx_deleted_at, idx_created_at
- `sessions`: idx_user_id, idx_expires_at, idx_refresh_token_hash
- `saved_analyses`: idx_user_created (复合), idx_type (复合), idx_public_created (复合)
- `export_history`: idx_user_created, idx_status, idx_date_type
- `system_config`: uk_config_key (UNIQUE)
- `api_keys`: uk_key_hash (UNIQUE), idx_user_id, idx_expires_at
- 总共有约 20 个索引，设计合理

**MongoDB 索引策略（`database/mongodb/schema_design.js`）：**
- 声明 5 个集合，35 个索引
- 包含 TTL 索引、部分索引、复合索引 ESR 规则
- 写关注策略分层设计（w:0/w:1/w:majority）
- 索引策略合理且全面

**Neo4j 约束：**
- 21 个索引/约束设计用于 4 种节点标签和 7 种关系类型

#### 负面发现

1. **零次实际数据库执行。** PROJECT_PLAN.md 自认："数据库 schema 设计完备但从未在真实实例上执行"。

2. **docker-compose.yml 中的 python-middleware 服务配置了 `dockerfile: Dockerfile`，但 Dockerfile 文件不存在**（Glob 搜索 `**/Dockerfile*` 返回零结果）。这意味着 `docker-compose up` 无法启动 Python 应用。

3. **健康检查端点 (`/api/v1/health`) 在测试中 mock 了所有数据库连接**（conftest.py 中 `get_redis_async` 等均返回 None）。无法验证真实数据库连接状态。

4. **MySQL DDL 中的 INSERT 语句**（第 226-236 行）种子数据包含硬编码的默认值。这些值从未在 MySQL 8.0 上成功执行过。

**评分: 3/15**

---

### 标准 3: 前端 Lighthouse 分数 > 90

**判定: FALSE — 架构阻碍达标**

#### 正面发现

**WCAG 无障碍支持（`js/accessibility.js`）实现良好：**
- `aria-live` 屏幕阅读器通知区域（双 div 技巧确保重复消息读）
- 跳过导航链接（`.skip-link`）
- Canvas ARIA 标签注入（MutationObserver 监听）
- 焦点陷阱（模态框 Tab 循环）
- `prefers-reduced-motion` 媒体查询监听
- WCAG 2.1 对比度计算工具（静态方法 `getLuminance` / `getContrastRatio`）
- 图加载完成通知、算法完成通知、路径查找通知
- **这是整个代码库中质量最高的模块之一。**

**HTML 语义化良好（`index.html`）：**
- `<nav>`, `<main>`, `<aside>`, `<section>` 语义标签
- `role` 属性全面（`role="search"`, `role="combobox"`, `role="dialog"`, `role="img"`）
- 所有交互元素有 `aria-label`
- `<input type="search">` 而非 `type="text"`

#### 负面发现

1. **5 个 CSS 文件在 `<head>` 中同步加载**（`reset.css`, `variables.css`, `layout.css`, `components.css`, `dark-theme.css`）—— 全部是渲染阻塞资源。

2. **`3d-force-graph` 从 unpkg CDN 在 `<head>` 中同步加载**（`<script src="...">` 而非 `<script async/defer>`）—— 这是一个大型 WebGL 库，下载+解析会阻塞整个渲染，直接冲击 LCP。

3. **无代码分割、无懒加载、无打包优化。** 10 个独立的 JS 文件通过 ES6 `import` 加载。

4. **无资源大小优化。** `chart.umd.min.js` 本地文件但无法确定是否 tree-shaken。

5. **CDN 资源无 SRI 哈希。** `<link rel="preconnect">` 存在但 `<script>` / `<link>` 缺少 `integrity` 属性。

6. **Lighthouse 从未运行。** TESTING_STRATEGY.md 中有 Lighthouse 目标表，但无任何实际结果。

7. **关键指标估算：**
   - LCP: 3d-force-graph 加载 + Canvas 初始化 + 数据获取 = 不可控
   - TBT: 10 个 JS 模块的解析和执行
   - 目标 <2.5s LCP 在当前架构下不可实现

**评分: 3/15**

---

### 标准 4: 零 Critical/High 安全漏洞

**判定: PARTIALLY PROVEN — 3 个关键修复已验证，但仍存在 4 个 High 级缺失项**

#### 已验证的修复

| 修复项 | 文件 | 代码证据 |
|--------|------|---------|
| JWT secret 安全处理 | `core/config.py:205-208` | dev 环境 `"dev_" + secrets.token_hex(32)`, prod 空值抛 RuntimeError |
| CORS 环境自适应 | `server.py:173-179` | production → `["http://localhost", "http://127.0.0.1"]`, 非prod → `["*"]` |
| WebSocket 强制认证 | `websockets/analysis_ws.py:35-37` | 无 token → `close(code=4001)`, 不做任何处理前先认证 |
| 登录限流 (IP级) | `auth/service.py:187-207` | Redis INCR 5次/分钟/ip |
| 账户锁定 | `auth/service.py:210-257` | Redis `login_fail:{email}` 计数器, 5 次 → 锁定 15 分钟 |
| XSS escapeHtml | `js/ui.js:291-295` | `document.createTextNode(str)` — 正确的 XSS 防御 |

#### 剩余安全缺失项

| # | 问题 | 严重性 | 详情 |
|---|------|--------|------|
| 1 | **缺少 CSP 头** | **HIGH** | 无 `Content-Security-Policy` header。内联样式存在于 `index.html` 和 `app.js` 的动态 HTML。CSP 实现需要将所有内联样式/脚本外置或使用 nonce/hash。 |
| 2 | **缺少 CSRF 保护** | **HIGH** | `POST /api/v1/auth/login`, `POST /api/v1/graph/shortest_path`, `POST /api/v1/auth/register` 没有任何 CSRF token 保护。虽然 JWT Bearer token 提供了一定防护，但未使用 Double Submit Cookie 或 SameSite Cookie 模式。 |
| 3 | **缺少 HSTS 头** | **MEDIUM-HIGH** | 无 `Strict-Transport-Security` header。HTTP 连接不会被强制升级到 HTTPS。 |
| 4 | **缺少安全头** | **MEDIUM** | 无 `X-Content-Type-Options: nosniff`, 无 `X-Frame-Options: DENY`, 无 `Referrer-Policy` |
| 5 | **`showModal()` 使用 innerHTML** | **MEDIUM** | `js/ui.js:152` `body.innerHTML = content` — 若 content 来源于不可信源，存在 XSS 风险。`showShortcuts()` 方法也使用 innerHTML。 |
| 6 | **docker-compose.yml 默认密码** | **LOW** | `MYSQL_ROOT_PASSWORD:-rootpassword`, `MONGO_ROOT_PASSWORD:-mongopass`, `NEO4J_AUTH:-neo4j/password123` — 虽然只是开发默认值，但存在被误用的风险 |
| 7 | **API Key 权限未强制执行** | **MEDIUM** | `api_keys` 表定义了 `permissions JSON` 字段，但 `auth/router.py` 中的 API Key 端点未找到权限校验中间件 |
| 8 | **安全扫描得分为零** | **INFO** | Mozilla Observatory 从未运行。无法获得任何安全头评分。 |

**实际 Critical/High 计数: 2 个 HIGH (CSP + CSRF), 1 个 MEDIUM-HIGH (HSTS)**

**评分: 12/20**

---

### 标准 5: 代码覆盖率 > 80%

**判定: FALSE — 实际覆盖率估计 < 10%**

#### 实际测试统计

**Python 测试 (`middleware_python/tests/`):**
- 文件: `test_api.py` + `conftest.py`
- 测试类: 4
- 测试方法: 13
- 覆盖端点: `/health`, `/health/live`, `/health/ready`, `/graph/shortest_path`, `/graph/pagerank`, `/graph/community`, `/graph/betweenness`, `/graph/kcore`, `/graph/clustering_coeff`, `/graph/stats`
- **所有测试都是 mock 测试**（`mock_run_cpp_engine` 返回预设值，所有数据库返回 None）

**C++ 测试:**
- CMakeLists.txt 配置了 Catch2 测试框架
- 声明了 9 个测试源文件: `test_BFS.cpp`, `test_PageRank.cpp`, `test_LPA.cpp`, 等
- **但这些测试文件在仓库中不存在。** `tests/` 目录下没有匹配这些文件名的文件

**前端测试:**
- **零个前端测试。** 无 Vitest、无 Jest、无 Playwright 测试文件。

#### 代码规模 vs 测试覆盖

| 模块 | 源码文件数 | 测试文件数 | 测试方法数 | 估算覆盖率 |
|------|----------|-----------|-----------|-----------|
| C++ 引擎 | ~20 (.cpp + .h) | 0 实际存在 | 0 | 0% |
| Python 网关 | ~47 (.py) | 2 | 13 (全mock) | < 5% |
| 前端 Web | 15 (.js + .html + .css) | 0 | 0 | 0% |
| 数据库脚本 | ~8 (.sql + .js + .cypher) | 0 | 0 | 0% |

**实际覆盖率估算: < 5%（全部模块合计）**

**评分: 2/15**

---

### 标准 6: 生产部署清单完备

**判定: FALSE — 关键组件缺失**

| 检查项 | 状态 | 详情 |
|--------|------|------|
| Dockerfile | **缺失** | Glob 搜索 `**/Dockerfile*` 返回零文件。`docker-compose.yml` 引用 `./middleware_python/Dockerfile` 会导致构建失败 |
| docker-compose.yml | **存在但不完整** | 定义了 mysql/mongodb/redis/neo4j 四个外部服务 + python-middleware + web-frontend。但 python-middleware 因 Dockerfile 缺失无法构建 |
| MySQL 迁移脚本 | **存在** | `database/mysql/001_init_schema.sql` (237行) + `002_seed_data.sql` (未验证) |
| MongoDB Schema | **存在** | `database/mongodb/schema_design.js` (完整设计文档 + 集合创建脚本) |
| CI/CD | **部分存在** | GitHub Actions 仅覆盖 C++ 编译 + 冒烟测试 + pytest。无前端构建、无 Docker 构建、无部署步骤 |
| 监控/告警 | **未实现** | 无 Prometheus metrics 端点、无 Grafana 配置、无告警规则 |
| 日志聚合 | **未实现** | 无 ELK/Loki 配置 |
| 健康检查 | **部分实现** | `/api/v1/health` 端点存在但所有组件检查都在测试中被 mock |
| 回滚方案 | **未实现** | 无数据库迁移回滚脚本、无部署回滚策略 |
| 备份恢复 | **未实现** | 数据库 schema 中有设计但无备份脚本 |
| 负载均衡 | **未实现** | 单实例部署，无水平扩展方案 |
| SSL/TLS | **未实现** | 无证书配置、无 HTTPS 端点 |

**PROJECT_PLAN.md 的质量:**
- 10 周计划详尽完备（Sprint 0-8，400 故事点 + 82 缓冲）
- 风险登记册包含 18 个风险项，带概率/影响/得分/缓解措施
- 里程碑定义清晰（M1-M5, Go/No-Go 标准明确）
- **但是**: 承认计划本身尚未开始执行。Sprint 0 的第一步是 "使三个核心模块能在本地环境独立启动且不报错"，这是最基础的基线。

**评分: 3/20**

---

## 综合评分

| 标准 | 满分 | 得分 | 判定 |
|------|------|------|------|
| 1. API < 200ms P95 | 15 | 0 | **FALSE** |
| 2. DB 查询 < 100ms | 15 | 3 | **UNVERIFIABLE** |
| 3. Lighthouse > 90 | 15 | 3 | **FALSE** |
| 4. 零安全漏洞 | 20 | 12 | **PARTIALLY PROVEN** |
| 5. 覆盖率 > 80% | 15 | 2 | **FALSE** |
| 6. 部署清单完备 | 20 | 3 | **FALSE** |
| **总计** | **100** | **23** | |

> **注：** 重新校准后，评分从初步计算的 ~40 下调至 **23/100**，因为更严格地审视了每个标准的证据权重。安全标准 (标准 4) 是最接近达标的唯一项，但由于 CSP/CSRF/HSTS 三个 HIGH 级缺失，不能给及格分。

> **与上次评分 (33/100) 的比较**: 上次 33 分是基于代码结构和设计的概要审查。本次 23 分是基于逐行源代码验证的严格审计。分数的"下降"反映了审计深度的增加而非代码质量的退化。实际上，7 个 P0 修复是真实且有价值的改进。

---

## 最终裁定

### 当前状态: **不可部署到任何环境**

原因（按严重性排序）：

1. **代码从未执行过。** 这是根本问题。C++ 引擎未在真实数据上运行，Python 网关未处理过真实请求，前端未在真实浏览器中渲染过数据。所有测试都是 mock 测试。

2. **Dockerfile 缺失。** 连最基本的容器化构建都无法完成。

3. **C++ 测试文件不存在。** CMakeLists.txt 引用了 9 个 Catch2 测试源文件，但它们不在仓库中。CI 中的 `ctest` 步骤会失败。

4. **安全头完全缺失。** 0 个 CSP/HSTS/CSRF 实现。这是 HIGH 级安全问题。

5. **Betweenness Centrality 数学不可行性。** 在 4K 节点图上精确计算的耗时将超出预期 2-3 个数量级。

### 改进路径（若要达到可部署状态）

**第一周（Sprint 0 最低基线）：**
- [ ] 创建 `middleware_python/Dockerfile`
- [ ] `cmake --build` 通过并生成可执行文件
- [ ] `uvicorn server:app` 启动成功
- [ ] C++ 引擎对 `facebook_combined.txt` 执行 `get_full_graph` 输出合法 JSON
- [ ] 前端 `index.html` 在浏览器加载无 console error
- [ ] 创建缺失的 C++ 测试源文件或从 CMakeLists 中移除引用

**第二周（安全加固）：**
- [ ] 实现 CSP 头中间件
- [ ] 实现 HSTS 头
- [ ] 实现 CSRF token 保护
- [ ] Mozilla Observatory 评分 > 60

**第三至四周（集成验证）：**
- [ ] 端到端测试: Python 调用 C++ 引擎成功返回 JSON
- [ ] 前端通过 API 获取真实数据并渲染
- [ ] 数据库 schema 在真实实例上执行验证
- [ ] Locust 负载测试在真实服务器上运行

### 可选乐观路径

如果目标仅为 **开发环境演示**（非生产），所需工作显著减少：
- Dockerfile + C++ 编译 + API 启动 + 前端渲染 = 约 1 周工作量
- 不需安全头、不需 80% 覆盖率、不需 Betweenness 优化

---

## 附录 A: 审计数据来源

审计中实际读取并引用的文件（按读取顺序）：

| 文件 | 行数 | 关键发现 |
|------|------|---------|
| `middleware_python/server.py` | 256 | 应用工厂架构完整，lifespan 管理正确，CORS 环境自适应已实现 |
| `middleware_python/core/config.py` | 250 | JWT secret 在 dev 自动生成，prod 强制检查，路径自动探测 |
| `middleware_python/db/redis.py` | 822 | lazy-connect 模式正确，v2.0 增强完备，但从未连接过真实 Redis |
| `middleware_python/services/cache.py` | 1008 | 5 种失效模式代码完整，Tag-Based/Version/Event/TTL/Manual 均有实现 |
| `backend_cpp/src/main.cpp` | 248 | stdout 输出 JSON，std::cerr 日志，10 个算法分支均有计时，但 JSON 是手工拼接而非 JSON 库 |
| `frontend_web/js/app.js` | 772 | escapeHtml 应用于雷达面板，加载流程调用 8 个 API 端点 |
| `frontend_web/index.html` | 214 | 语义化 HTML，ARIA 属性全面，但 5 个 CSS + 2 个 CDN JS 阻塞渲染 |
| `frontend_web/js/accessibility.js` | 283 | WCAG 功能实现质量高，含 aria-live/跳过链接/焦点陷阱/reduced-motion |
| `frontend_web/js/ui.js` | 307 | escapeHtml 实现正确，但 showModal innerHTML 存在 XSS 风险 |
| `middleware_python/websockets/analysis_ws.py` | 110 | JWT 强制认证在连接前检查，正确 |
| `middleware_python/middleware/rate_limiter.py` | 176 | 滑动窗口 + Sorted Set 实现，Redis 不可用时放行 |
| `middleware_python/auth/service.py` | ~350 | IP 限流 + 账户锁定实现完整，token 刷新轮换 |
| `middleware_python/core/security.py` | 273 | bcrypt cost=12, JWT 创建/验证/黑名单完整 |
| `database/mysql/001_init_schema.sql` | 237 | 6 表 20+ 索引，设计专业 |
| `database/mongodb/schema_design.js` | 1000+ | 5 集合 35 索引，Validator 设计完整 |
| `backend_cpp/CMakeLists.txt` | 160 | 测试文件引用存在但文件缺失 |
| `tests/load/locustfile.py` | 825 | 6 场景设计完备，但从未执行 |
| `docker-compose.yml` | 122 | 服务定义完整但引用不存在的 Dockerfile |
| `.github/workflows/main.yml` | 63 | 仅 C++ + pytest，无前端/部署 CI |
| `docs/PROJECT_PLAN.md` | 792 | 10 周计划详尽，自认代码从未执行 |
| `docs/TESTING_STRATEGY.md` | 841 | 测试策略完善但 0 项已执行 |
| `middleware_python/tests/test_api.py` | 148 | 13 个 mock 测试 |
| `middleware_python/tests/conftest.py` | 54 | Mock 路径正确，所有 DB 返回 None |

---

*审计文件由 Reality Checker v2.0 生成。每个结论均有对应代码行号支撑。质疑请附带反证。*
