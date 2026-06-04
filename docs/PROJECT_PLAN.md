# SocialGraph Pro -- 项目管理计划

**项目名称**: SocialGraph Pro
**项目代号**: SGP
**文档版本**: 1.0
**最后更新**: 2026-05-02
**项目状态**: 架构设计完成，进入工程化冲刺阶段
**Reality Checker 评分**: 33/100 (首次审计, 基准线)

---

## 目录

1. [项目现状总结](#1-项目现状总结)
2. [Sprint 分解计划 (10 周)](#2-sprint-分解计划)
3. [任务分解与依赖矩阵](#3-任务分解与依赖矩阵)
4. [风险登记册](#4-风险登记册)
5. [团队协作清单与里程碑追踪](#5-团队协作清单与里程碑追踪)

---

## 1. 项目现状总结

### 1.1 已完成工作

| 阶段 | 内容 | 产出 |
|------|------|------|
| 架构设计 | 全栈三层分离设计 | CLAUDE.md, ARCHITECTURE.md |
| C++ 引擎 | 10 个图算法 + 策略模式 | backend_cpp/ (源码 + CMake) |
| C++ 微服务层 | TCP/gRPC/Redis/MySQL 驱动设计 | 9 个 header 文件 |
| Python 网关 | FastAPI 应用工厂 + 模块化架构 | ~47 个 .py 文件 |
| 前端 SPA | WebGL 3D 可视化 + 仪表板 | 15 个前端文件 |
| 数据库设计 | MySQL 6 表 + MongoDB 5 集合 + Neo4j 图模型 + Redis 缓存 v2 | database/ 目录 |
| P0 安全修复 | 进程池移除 / mock 路径 / 硬编码凭据 / 登录限流 / CORS / WebSocket 认证 / XSS 过滤 | 7 项已修复 |
| CI/CD | GitHub Actions 跨平台 CMake + 冒烟测试 | .github/workflows/ |
| 文档 | SETUP / ARCHITECTURE / ONBOARDING | docs/ |

### 1.2 已知问题概览

| 优先级 | 数量 | 关键项 |
|--------|------|--------|
| P0 (已修复) | 7 | 进程池移除、mock 路径、硬编码凭据、登录限流、CORS、WebSocket 认证、XSS |
| P1 (待处理) | 5 | Dockerfile 缺失、C++ JSON 输出脆弱、安全头 (CSP/HSTS)、API Key 权限未强制、DB 自动重连 |
| P2 (待处理) | 4 | Betweenness Centrality 规模限制、CDN SRI、E2E 测试缺失、Prometheus 指标 |
| 未知风险 | 15+ | AI 生成代码未执行验证、依赖版本冲突、跨平台兼容性等 |

### 1.3 核心风险陈述

**关键事实**: 本项目近 90% 的代码由 AI 生成，从未在任何环境中完整执行通过。三个核心模块 (C++/Python/前端) 之间从未进行过端到端集成测试。数据库 schema 设计完备但从未在真实实例上执行。Redis 缓存策略 v2.0 有 5 种失效模式但写回代码尚未实现。

**评估**: 从"好看的设计文档"到"可运行的软件"，预计需要 8-10 周的工程化冲刺。

---

## 2. Sprint 分解计划

### 总体时间线

```
Week 1     Week 2     Week 3     Week 4     Week 5     Week 6     Week 7     Week 8     Week 9     Week 10
├Sprint 0──┤├Sprint 1─┤├Sprint 2─┤├Sprint 3─┤├Sprint 4─┤├Sprint 5─┤├Sprint 6─┤├Sprint 7─┤├Sprint 8─┤
 基础稳定     C++ 加固    Python加固   数据库集成   前端现代化    安全加固     性能优化     测试QA     生产就绪
     │           │           │           │           │           │           │           │           │
  [M1]──────────[M2]──────────────────────[M3]──────────────────────[M4]──────────────────────[M5]
 第2周         第4周                     第7周                     第9周                    第10周
 代码可运行    核心稳定                   功能完整                   安全审计通过              生产就绪
```

### Sprint 0: 基础稳定化 (第 1-2 周)

**Sprint 目标**: 使三个核心模块能在本地环境独立启动且不报错，为后续所有 Sprint 建立可验证的基线。

**背景**: 当前代码库是 AI 生成的静态文件集合，从未实际编译/运行/集成过。Sprint 0 的核心任务是把"设计图"变成"能跑的代码"。

#### 用户故事 / 任务

| # | 用户故事 | 故事点 | 角色 |
|---|---------|--------|------|
| S0-1 | 作为开发者，我需要在本地 `cmake --build` 无错误通过 | 5 | C++ 工程师 |
| S0-2 | 作为开发者，我需要 `pip install -r requirements.txt` 完整安装所有依赖 | 3 | Python 后端 |
| S0-3 | 作为开发者，我需要 `uvicorn server:app` 能启动且所有路由注册成功 | 8 | Python 后端 |
| S0-4 | 作为开发者，我需要前端 `index.html` 在浏览器中无 JS 错误加载 | 5 | 前端工程师 |
| S0-5 | 作为开发者，我需要运行 `docker-compose up` 启动所有依赖服务 | 8 | DevOps |
| S0-6 | 作为 QA，我需要 13 个 pytest 测试用例全部通过 | 5 | QA |
| S0-7 | 作为 Tech Lead，我需要制定编码规范和分支策略 | 2 | Tech Lead |
| S0-8 | 作为 DevOps，我需要修复 GitHub Actions CI 流水线 | 5 | DevOps |

**依赖**: 无 (这是第一个 Sprint)
**接收标准**:
- `cmake -B build -DCMAKE_BUILD_TYPE=Release && cmake --build build` 零错误
- `uvicorn server:app --host 0.0.0.0 --port 8000` 成功启动, `/docs` 可访问
- 前端 `index.html` 在浏览器中渲染无 console error
- `docker-compose up` 启动 4 个外部服务 (MySQL/MongoDB/Redis/Neo4j)
- CI 流水线在 push 时自动触发并通过
- 13 个 pytest 测试 100% 通过

**工作量**: 36 故事点 | 风险缓冲: 10 点 | 团队速率: 23 点/周

---

### Sprint 1: C++ 核心引擎加固 (第 3 周)

**Sprint 目标**: 确保所有 10 个图算法输出合法 JSON, 修复 C++ JSON 输出脆弱性 (P1), 通过 Catch2 单元测试。

#### 用户故事 / 任务

| # | 用户故事 | 故事点 | 角色 |
|---|---------|--------|------|
| S1-1 | 作为后端服务，我需要 C++ 引擎 stdout 输出严格合法 JSON (不可掺杂日志) | 8 | C++ 工程师 |
| S1-2 | 作为算法用户，我需要 10 个算法对已知测试数据产生正确结果 | 13 | C++ 工程师 |
| S1-3 | 作为 QA，我需要 Catch2 测试覆盖所有算法核心逻辑 | 8 | QA (+ C++ 工程师) |
| S1-4 | 作为 DevOps，我需要 C++ 引擎编译产物纳入 CI artifacts | 3 | DevOps |
| S1-5 | 作为 Python 网关，我需要 `subprocess.run()` 调用 C++ 引擎端到端通 | 5 | Python 后端 |
| S1-6 | 作为开发者，我需要 C++ JSON 输出包含 schema 版本号 | 3 | C++ 工程师 |

**依赖**: Sprint 0 完成 (C++ 能编译)
**接收标准**:
- `build/graph_engine facebook_combined.txt get_full_graph` 输出 100% 合法 JSON
- 所有 10 个算法对标准数据集输出可验证的结果
- Catch2 测试覆盖率 > 80%
- `python -c "from services.cpp_engine import run_engine; print(run_engine('get_full_graph'))"` 成功返回

**工作量**: 40 故事点 | 风险缓冲: 8 点

---

### Sprint 2: API 网关加固 (第 4 周)

**Sprint 目标**: 所有 FastAPI 路由端到端可用, 修复异常处理链, 实现数据库自动重连 (P1), 编写 API 契约测试。

#### 用户故事 / 任务

| # | 用户故事 | 故事点 | 角色 |
|---|---------|--------|------|
| S2-1 | 作为 API 消费者，我需要 `/api/v1/graph/shortest_path` 返回正确路径 | 5 | Python 后端 |
| S2-2 | 作为 API 消费者，我需要 `/api/v1/graph/pagerank` 返回正确排序 | 5 | Python 后端 |
| S2-3 | 作为 API 消费者，我需要 `/api/v1/graph/community` 返回正确社区划分 | 5 | Python 后端 |
| S2-4 | 作为运维，我需要数据库连接断开后自动重连 (P1) | 8 | Python 后端 |
| S2-5 | 作为 API 消费者，我需要标准化的错误响应格式 | 5 | Python 后端 |
| S2-6 | 作为 QA，我需要 API 契约测试覆盖所有公开端点 | 8 | QA |
| S2-7 | 作为 API 消费者，我需要 `/api/v1/health` 返回真实健康状态 | 3 | Python 后端 |
| S2-8 | 作为开发者，我需要 API 速率限制无误杀正常请求 | 3 | Python 后端 |

**依赖**: Sprint 1 (C++ JSON 产出合法)
**接收标准**:
- 所有 8 个图算法端点返回正确 JSON 结果
- 数据库自动重连在 5 秒内恢复
- 错误响应格式统一 (code + message + details)
- 健康检查端点返回所有依赖的真实状态

**工作量**: 42 故事点 | 风险缓冲: 8 点

---

### Sprint 3: 数据库集成 (第 5 周)

**Sprint 目标**: MySQL/MongoDB/Neo4j 全部连接到真实实例, Schema 在真实环境执行验证, Redis 缓存策略代码实现。

#### 用户故事 / 任务

| # | 用户故事 | 故事点 | 角色 |
|---|---------|--------|------|
| S3-1 | 作为运维，我需要 MySQL 6 表 DDL 在 MySQL 8.x 上成功执行 | 5 | DevOps |
| S3-2 | 作为运维，我需要 MongoDB 5 集合 + 35 索引成功创建 | 5 | DevOps |
| S3-3 | 作为运维，我需要 Neo4j 图 schema + 21 索引成功创建 | 5 | DevOps |
| S3-4 | 作为开发者，我需要 Redis 缓存策略 v2.0 的 sgp 命名空间代码实现 | 8 | Python 后端 |
| S3-5 | 作为开发者，我需要 Redis Pub/Sub 缓存失效广播实现 | 5 | Python 后端 |
| S3-6 | 作为开发者，我需要数据库连接池配置调优并通过压测 | 5 | Python 后端 |
| S3-7 | 作为 QA，我需要验证数据导入/导出功能完整性 | 5 | QA |
| S3-8 | 作为后端服务，我需要 lazy-connect 模式在所有 DB 驱动上正常工作 | 3 | Python 后端 |

**依赖**: Sprint 0 (docker-compose 可运行)
**接收标准**:
- 所有 DDL/Schema 语句在真实数据库实例上零错误执行
- Redis `sgp:graph:*` 命名空间下可观测缓存键
- `docker-compose exec` 连接每个数据库成功
- Pub/Sub 消息可被多实例消费

**工作量**: 41 故事点 | 风险缓冲: 8 点

---

### Sprint 4: 前端现代化 (第 6 周)

**Sprint 目标**: XSS 修复落地, WCAG 2.1 AA 合规, 响应式 4 断点可用, 前端状态管理健壮化。

#### 用户故事 / 任务

| # | 用户故事 | 故事点 | 角色 |
|---|---------|--------|------|
| S4-1 | 作为安全工程师，我需要 XSS 过滤覆盖所有用户输入点 | 5 | 前端工程师 |
| S4-2 | 作为用户，我需要 4 个断点 (320/768/1024/1440) 下界面可用 | 8 | 前端工程师 |
| S4-3 | 作为视障用户，我需要键盘导航 + 屏幕阅读器支持 | 8 | 前端工程师 |
| S4-4 | 作为开发者，我需要 state.js 状态管理支持 undo/redo | 5 | 前端工程师 |
| S4-5 | 作为用户，我需要图表面板在各浏览器渲染一致 | 5 | 前端工程师 |
| S4-6 | 作为运维，我需要 `config.js` 支持环境变量注入 | 3 | 前端工程师 |
| S4-7 | 作为 QA，我需要前端自动化测试覆盖核心用户流程 | 8 | QA (+ 前端) |
| S4-8 | 作为用户，我需要右键菜单在触屏设备上有替代操作 | 3 | 前端工程师 |

**依赖**: Sprint 2 (API 端点可用供前端对接)
**接收标准**:
- XSS 测试向量全部被过滤
- Lighthouse Accessibility 评分 > 90
- 4 个断点下无布局错位或功能缺失
- state.js 的状态快照/恢复功能正常

**工作量**: 45 故事点 | 风险缓冲: 9 点

---

### Sprint 5: 安全加固 (第 7 周)

**Sprint 目标**: 关闭所有 P1 安全问题, 实现 CSP/HSTS/CSRF 安全头, API Key 权限强制执行, 审计日志落库。

#### 用户故事 / 任务

| # | 用户故事 | 故事点 | 角色 |
|---|---------|--------|------|
| S5-1 | 作为安全工程师，我需要 CSP 头阻止内联脚本和未授权资源 | 5 | DevOps (+ Python 后端) |
| S5-2 | 作为安全工程师，我需要 HSTS 头强制 HTTPS | 2 | DevOps |
| S5-3 | 作为安全工程师，我需要 CSRF token 机制保护状态变更端点 | 5 | Python 后端 |
| S5-4 | 作为管理员，我需要 API Key 权限 (role-based) 在每次请求时校验 | 8 | Python 后端 |
| S5-5 | 作为审计员，我需要所有管理操作记录到 MongoDB audit_log | 5 | Python 后端 |
| S5-6 | 作为安全工程师，我需要安全头扫描得分 > 85 | 3 | DevOps (+ QA) |
| S5-7 | 作为用户，我需要 JWT token family 机制支持 refresh token rotation | 8 | Python 后端 |
| S5-8 | 作为管理员，我需要敏感配置不出现在前端 bundle 中 | 3 | DevOps |

**依赖**: Sprint 2 (API 路由已稳定), Sprint 3 (MongoDB 可写入审计日志)
**接收标准**:
- Mozilla Observatory 评分 > 85
- API Key 的 viewer 角色无法调用算法端点
- JWT access token 过期后用 refresh token 可无感续期
- 审计日志包含: 操作者/时间/IP/动作/结果

**工作量**: 39 故事点 | 风险缓冲: 8 点

---

### Sprint 6: 性能优化 (第 8 周)

**Sprint 目标**: 进程池优化, 多级缓存策略落地, CDN 部署, Prometheus 指标导出, Betweenness Centrality 规模提升。

#### 用户故事 / 任务

| # | 用户故事 | 故事点 | 角色 |
|---|---------|--------|------|
| S6-1 | 作为运维，我需要 10K 边 PageRank 计算 < 2 秒 | 5 | C++ 工程师 |
| S6-2 | 作为运维，我需要 Betweenness Centrality 支持 > 50K 边的图 | 8 | C++ 工程师 |
| S6-3 | 作为运维，我需要 Redis Cache-Aside 模式对所有算法端点生效 | 5 | Python 后端 |
| S6-4 | 作为运维，我需要 `/metrics` 端点暴露 Prometheus 格式指标 | 8 | DevOps |
| S6-5 | 作为运维，我需要静态资源部署到 CDN | 5 | DevOps |
| S6-6 | 作为用户，我需要 WebGL 大数据量 (>5K 节点) 时帧率 > 30fps | 8 | 前端工程师 |
| S6-7 | 作为安全工程师，我需要 CDN 资源带 SRI hash | 3 | DevOps |
| S6-8 | 作为运维，我需要在 100 并发下 API 响应 P95 < 500ms | 8 | Python 后端 (+ DevOps) |

**依赖**: Sprint 3 (缓存基础设施可用), Sprint 5 (安全策略不破坏性能)
**接收标准**:
- Benchmark suite 3 种规模通过 (10K/50K/100K)
- Redis 命中率 > 70%
- Prometheus 导出 4 大黄金指标 (延迟/流量/错误/饱和度)
- WebGL 5K 节点场景稳定 30fps

**工作量**: 50 故事点 | 风险缓冲: 10 点

---

### Sprint 7: 测试与质量保证 (第 9 周)

**Sprint 目标**: 端到端测试覆盖核心流程, 性能测试基准建立, 32 个测试类型全覆盖, 负载测试通过。

#### 用户故事 / 任务

| # | 用户故事 | 故事点 | 角色 |
|---|---------|--------|------|
| S7-1 | 作为 QA，我需要 pytest 测试覆盖所有 API 端点 (目标 > 85%) | 13 | QA |
| S7-2 | 作为 QA，我需要 Catch2 测试覆盖所有 C++ 算法 (目标 > 90%) | 8 | QA (+ C++ 工程师) |
| S7-3 | 作为 QA，我需要 Playwright E2E 测试覆盖 5 个核心用户旅程 | 13 | QA (+ 前端) |
| S7-4 | 作为 QA，我需要 LoadRunner/Locust 负载测试脚本 | 8 | QA (+ DevOps) |
| S7-5 | 作为 QA，我需要安全渗透测试检查清单 | 5 | QA (+ 安全工程师) |
| S7-6 | 作为 QA，我需要兼容性矩阵测试 (Chrome/Firefox/Safari/Edge) | 5 | QA |
| S7-7 | 作为开发者，我需要所有测试在 CI 中自动运行 | 5 | DevOps |
| S7-8 | 作为 Tech Lead，我需要测试报告仪表板 | 3 | Tech Lead |

**依赖**: Sprint 1-6 所有功能开发完成
**接收标准**:
- pytest 覆盖率 > 85%
- Catch2 覆盖率 > 90%
- 5 个 E2E 用户旅程全部通过
- 100 并发负载测试 P95 < 500ms
- 安全检查清单 0 个 Critical/High 未解决项

**工作量**: 60 故事点 | 风险缓冲: 12 点

---

### Sprint 8: 生产就绪 (第 10 周)

**Sprint 目标**: Docker 生产镜像, CI/CD 完整流水线, 监控告警配置, 文档完善, Reality Checker 重新审计 > 80 分。

#### 用户故事 / 任务

| # | 用户故事 | 故事点 | 角色 |
|---|---------|--------|------|
| S8-1 | 作为 DevOps，我需要多阶段 Dockerfile (C++ build + Python runtime + Nginx) | 8 | DevOps |
| S8-2 | 作为 DevOps，我需要 `docker-compose.prod.yml` 生产部署配置 | 5 | DevOps |
| S8-3 | 作为 DevOps，我需要 CI/CD 包含测试 → 构建 → 部署完整流水线 | 8 | DevOps |
| S8-4 | 作为运维，我需要 Prometheus + Grafana 告警规则配置 | 5 | DevOps |
| S8-5 | 作为运维，我需要日志聚合方案 (ELK 或 Loki) | 5 | DevOps |
| S8-6 | 作为开发者，我需要 API 文档完整且包含示例 | 5 | Python 后端 |
| S8-7 | 作为新成员，我需要 ONBOARDING.md 能在 30 分钟内完成环境搭建 | 3 | Tech Lead |
| S8-8 | 作为利益相关者，我需要 Reality Checker 重新审计得分 > 80/100 | 8 | 全员 |

**依赖**: Sprint 7 (所有测试通过)
**接收标准**:
- `docker build` 生成 < 500MB 的生产镜像
- 完整 CI/CD: push → test → build → deploy
- Grafana 仪表板展示 4 大黄金指标
- Reality Checker 评分 > 80/100
- 新人 30 分钟内可启动完整开发环境

**工作量**: 47 故事点 | 风险缓冲: 9 点

---

### Sprint 故事点汇总

| Sprint | 名称 | 故事点 | 缓冲 | 总计 |
|--------|------|--------|------|------|
| S0 | 基础稳定化 | 36 | 10 | 46 |
| S1 | C++ 核心加固 | 40 | 8 | 48 |
| S2 | API 网关加固 | 42 | 8 | 50 |
| S3 | 数据库集成 | 41 | 8 | 49 |
| S4 | 前端现代化 | 45 | 9 | 54 |
| S5 | 安全加固 | 39 | 8 | 47 |
| S6 | 性能优化 | 50 | 10 | 60 |
| S7 | 测试与 QA | 60 | 12 | 72 |
| S8 | 生产就绪 | 47 | 9 | 56 |
| **合计** | | **400** | **82** | **482** |

---

## 3. 任务分解与依赖矩阵

### 3.1 Sprint 0: 基础稳定化 (第 1-2 周)

| ID | 任务 | 故事点 | 依赖 | 负责人 | 接收标准 |
|----|------|--------|------|--------|---------|
| S0-01 | 修复 C++ CMakeLists.txt 中的源文件路径与缺失引用 | 5 | -- | C++ 工程师 | `cmake --build build` 无错误, 生成可执行文件 |
| S0-02 | 生成 `requirements.txt` 并冻结依赖版本 | 3 | -- | Python 后端 | `pip install -r requirements.txt` 全部成功 |
| S0-03 | 修复 Python 模块导入错误与循环引用 | 5 | S0-02 | Python 后端 | `python -c "import server"` 无 import error |
| S0-04 | 验证 FastAPI 应用工厂启动 + OpenAPI docs 可访问 | 3 | S0-03 | Python 后端 | `http://127.0.0.1:8000/docs` 列出所有路由 |
| S0-05 | 修复前端 JS 模块导入与全局变量未定义错误 | 5 | -- | 前端工程师 | 浏览器 console 零 error |
| S0-06 | 创建 `docker-compose.yml` 服务定义文件 (P1: Dockerfile 缺失) | 5 | -- | DevOps | `docker-compose up -d mysql mongo redis neo4j` 成功 |
| S0-07 | 修复 `conftest.py` 中的 mock 路径 | 3 | S0-03 | Python 后端 | pytest 导入阶段不报错 |
| S0-08 | 使 13 个 pytest 测试全部通过 | 2 | S0-07 | QA | `pytest --tb=short` 13 passed |
| S0-09 | 修复 GitHub Actions workflow 语法与平台兼容 | 5 | S0-01 | DevOps | push 触发 CI, 矩阵构建通过 |
| S0-10 | 编写 `.editorconfig` + `pyproject.toml` 统一代码风格 | 2 | -- | Tech Lead | CI 中 linter 检查通过 |
| S0-11 | 更新 CLAUDE.md 反映真实可运行的构建命令 | 1 | S0-01, S0-03 | Tech Lead | 按 CLAUDE.md 指令从零搭建成功 |

### 3.2 Sprint 1: C++ 核心引擎加固 (第 3 周)

| ID | 任务 | 故事点 | 依赖 | 负责人 | 接收标准 |
|----|------|--------|------|--------|---------|
| S1-01 | 所有 `std::cout` 输出统一用 JSON 库 (nlohmann/json) | 5 | S0-01 | C++ 工程师 | 100% 的 stdout 内容可被 `jq .` 解析 |
| S1-02 | 所有调试日志用 `std::cerr` 输出, 加时间戳和日志级别 | 3 | S1-01 | C++ 工程师 | stdout 中无任何日志文本 |
| S1-03 | 为每个算法编写结果验证脚本 (金标准测试) | 8 | S1-01 | C++ 工程师 + QA | 10 个算法输出与已知正确结果完全一致 |
| S1-04 | 编写 Catch2 测试用例覆盖算法核心逻辑 | 8 | S1-01 | C++ 工程师 | 测试覆盖率 > 80% |
| S1-05 | `facebook_combined.txt` 数据集格式验证和清洗 | 2 | -- | QA | 所有行格式: `int int` (空格分隔) |
| S1-06 | 添加 `--version` 和 `--help` CLI 参数 | 2 | -- | C++ 工程师 | `./graph_engine --version` 输出版本号 |
| S1-07 | CI 构建产物上传为 release artifacts | 3 | S0-09 | DevOps | GitHub Release 页面可见二进制文件 |
| S1-08 | Python 通过 subprocess 调用 C++ 引擎端到端测试 | 5 | S1-01, S0-03 | Python 后端 | `services/cpp_engine.py` 的 `run_engine()` 正确返回 dict |
| S1-09 | JSON 输出添加 `schema_version` 字段 (向前兼容) | 3 | S1-01 | C++ 工程师 | 每个算法输出包含版本号 |

### 3.3 Sprint 2: API 网关加固 (第 4 周)

| ID | 任务 | 故事点 | 依赖 | 负责人 | 接收标准 |
|----|------|--------|------|--------|---------|
| S2-01 | `/api/v1/graph/shortest_path` end-to-end 联调 | 5 | S1-08 | Python 后端 | curl 返回正确最短路径 |
| S2-02 | `/api/v1/graph/pagerank` end-to-end 联调 | 5 | S1-08 | Python 后端 | curl 返回排序后的节点分数 |
| S2-03 | `/api/v1/graph/community` end-to-end 联调 | 5 | S1-08 | Python 后端 | curl 返回社区划分结果 |
| S2-04 | `/api/v1/graph/stats` + 其余算法端点联调 | 5 | S1-08 | Python 后端 | 8 个算法端点全部可用 |
| S2-05 | 数据库连接池实现自动重连与健康检查 (P1) | 5 | S0-06 | Python 后端 | 手动 kill 连接后 5s 内恢复 |
| S2-06 | 标准化错误响应模型 (RFC 7807 Problem Details) | 3 | -- | Python 后端 | 所有错误响应格式统一 |
| S2-07 | 异常处理链覆盖所有中间件和路由层 | 3 | S2-06 | Python 后端 | 未捕获异常返回 500 而非 hang |
| S2-08 | `/api/v1/health` 实现真实健康检查 (检查 DB + C++ 引擎) | 3 | S2-05 | Python 后端 | 返回各依赖组件的实际状态 |
| S2-09 | 速率限制器调优 (避免误杀正常请求) | 3 | -- | Python 后端 | 10 req/s 以内不触发限流 |
| S2-10 | 编写 API 契约测试 (pytest + httpx) | 5 | S2-01~S2-04 | QA | 所有公开端点有契约测试 |

### 3.4 Sprint 3: 数据库集成 (第 5 周)

| ID | 任务 | 故事点 | 依赖 | 负责人 | 接收标准 |
|----|------|--------|------|--------|---------|
| S3-01 | MySQL DDL 在真实实例上执行验证 (包含迁移工具) | 5 | S0-06 | DevOps | 6 张表成功创建, 索引确认 |
| S3-02 | MongoDB Schema + 35 索引在真实实例上创建验证 | 5 | S0-06 | DevOps | `db.collection.getIndexes()` 确认 35 个索引 |
| S3-03 | Neo4j 约束 + 21 索引在真实实例上创建验证 | 5 | S0-06 | DevOps | `SHOW CONSTRAINTS` + `SHOW INDEXES` 确认 |
| S3-04 | 实现 Redis sgp 命名空间键管理 | 3 | S0-06 | Python 后端 | `sgp:graph:*` 键可被 `SCAN` 发现 |
| S3-05 | 实现 Cache-Aside 模式 (读缓存 → 未命中 → 计算 → 写缓存) | 5 | S3-04 | Python 后端 | 两次相同请求, 第二次命中 Redis |
| S3-06 | 实现 Pub/Sub 缓存失效广播 | 3 | S3-04 | Python 后端 | 一条消息触发所有实例缓存失效 |
| S3-07 | 数据库连接池配置调优 (size/timeout/idle) | 3 | S3-01~S3-03 | Python 后端 | 100 并发无连接超时 |
| S3-08 | 数据导入脚本 (CSV/JSON → MySQL + Neo4j + MongoDB) | 3 | S3-01, S3-03 | DevOps | `python import_data.py` 成功导入 |
| S3-09 | 验证 lazy-connect 模式: 数据库不可用时优雅降级 | 3 | S3-01~S3-03 | Python 后端 | 停掉 MySQL 后 API 仍可返回 503 而非 crash |
| S3-10 | 初始化种子数据 (`002_seed_data.sql`) 执行验证 | 2 | S3-01 | QA | RBAC 角色和默认用户创建成功 |

### 3.5 Sprint 4: 前端现代化 (第 6 周)

| ID | 任务 | 故事点 | 依赖 | 负责人 | 接收标准 |
|----|------|--------|------|--------|---------|
| S4-01 | DOMPurify 集成 + 所有用户输入点 XSS 过滤 | 5 | S0-05 | 前端工程师 | XSS 测试向量无弹窗 |
| S4-02 | CSS 响应式断点 320/768/1024/1440 适配修缮 | 8 | S0-05 | 前端工程师 | 4 个分辨率截图无布局错位 |
| S4-03 | 键盘导航 (Tab/Enter/Escape/Arrow) + ARIA 属性 | 5 | S0-05 | 前端工程师 | 键盘可完成所有核心操作 |
| S4-04 | 屏幕阅读器标签 (aria-label/role/live-region) | 3 | S4-03 | 前端工程师 | NVDA/VoiceOver 朗读正确 |
| S4-05 | state.js 增强: 实现快照/恢复/undo (最多 50 步) | 5 | S0-05 | 前端工程师 | Ctrl+Z 回退上一次操作 |
| S4-06 | 跨浏览器一致性测试 (Chrome/Firefox/Safari/Edge) | 5 | S4-02 | QA | 4 浏览器截图无显著差异 |
| S4-07 | `config.js` 支持构建时注入: API_BASE_URL, WS_URL 等 | 3 | S0-05 | 前端工程师 | 修改 config.js 无需重编译 |
| S4-08 | 触屏设备替代操作 (长按替代右键) | 3 | S0-05 | 前端工程师 | iPad 上长按节点显示上下文菜单 |
| S4-09 | 前端单元测试 (使用 Vitest 或 Jest 测试核心模块) | 8 | S0-05 | QA | api.js / state.js / graphEngine.js 测试覆盖 > 70% |

### 3.6 Sprint 5: 安全加固 (第 7 周)

| ID | 任务 | 故事点 | 依赖 | 负责人 | 接收标准 |
|----|------|--------|------|--------|---------|
| S5-01 | Content-Security-Policy 头配置 (限制 script-src/style-src) | 5 | S4-01, S4-02 | DevOps + 前端 | CSP 不破坏现有功能 |
| S5-02 | Strict-Transport-Security + X-Content-Type-Options + X-Frame-Options | 2 | -- | DevOps | Mozilla Observatory 基础分 > 60 |
| S5-03 | CSRF token (双重提交 Cookie 模式) 保护 POST/PUT/DELETE | 5 | S2-01~S2-04 | Python 后端 | 无 token 的 POST 返回 403 |
| S5-04 | API Key 权限校验中间件 (role + endpoint 白名单) | 8 | S2-01~S2-04 | Python 后端 | viewer API Key 无法调用算法端点 |
| S5-05 | MongoDB audit_log 记录所有管理操作 | 5 | S3-02 | Python 后端 | 每次管理员操作产生一条审计记录 |
| S5-06 | JWT token family 实现 (refresh token rotation + 旧 token 失效) | 5 | -- | Python 后端 | 使用过的 refresh token 立即失效 |
| S5-07 | 敏感配置清理 (数据库密码/密钥不暴露在前端) | 3 | S4-07 | DevOps | 前端 bundle 中无数据库凭据 |
| S5-08 | 依赖安全扫描 (pip-audit / npm audit / trivy) | 3 | -- | DevOps | 0 个 Critical/High 漏洞 |
| S5-09 | 安全头综合扫描: Mozilla Observatory 评分 > 85 | 3 | S5-01, S5-02 | QA | Observatory 评分 A 或 A+ |

### 3.7 Sprint 6: 性能优化 (第 8 周)

| ID | 任务 | 故事点 | 依赖 | 负责人 | 接收标准 |
|----|------|--------|------|--------|---------|
| S6-01 | C++ PageRank 优化 (稀疏矩阵 CSR 表示) | 5 | S1-03 | C++ 工程师 | 10K 边 < 2 秒 |
| S6-02 | Betweenness Centrality 优化: Brandes 算法 + 采样近似 | 8 | S1-03 | C++ 工程师 | 50K 边 < 30 秒 (从 100K 边不可执行) |
| S6-03 | Redis Cache-Aside 对所有 8 个算法端点生效 | 5 | S3-05 | Python 后端 | 命中率 > 70% (benchmark 100 次请求) |
| S6-04 | Prometheus 指标端点 (请求计数/延迟直方图/错误率/并发数) | 8 | S2-01~S2-04 | DevOps | `/metrics` 返回 Prometheus 格式数据 |
| S6-05 | 静态资源 CDN 部署 (CSS/JS/字体) | 5 | S4-02 | DevOps | 静态资源从 CDN 加载, 首屏 < 2s |
| S6-06 | WebGL 性能优化 (节点合并/LOD/instance rendering) | 8 | S4-02 | 前端工程师 | 5K 节点稳定 > 30fps |
| S6-07 | CDN 资源 SRI 哈希校验 | 3 | S6-05 | DevOps | script/link 标签含 integrity 属性 |
| S6-08 | 100 并发负载测试 + 性能调优 | 8 | S6-01~S6-04 | Python 后端 + DevOps | P95 延迟 < 500ms, 0 错误 |

### 3.8 Sprint 7: 测试与质量保证 (第 9 周)

| ID | 任务 | 故事点 | 依赖 | 负责人 | 接收标准 |
|----|------|--------|------|--------|---------|
| S7-01 | pytest API 测试扩充至覆盖率 > 85% | 13 | S2-10 | QA | `pytest --cov=. --cov-report=term` 显示 > 85% |
| S7-02 | Catch2 测试扩充至覆盖率 > 90% | 8 | S1-04 | C++ 工程师 + QA | gcov/lcov 报告 > 90% |
| S7-03 | Playwright E2E: 登录 → 加载图 → 运行 PageRank → 查看排行 → 导出 | 13 | S4-02, S5-01~S5-04 | QA | 5 条 E2E 测试全部通过 |
| S7-04 | Locust 负载测试脚本 (模拟真实用户行为) | 8 | S6-08 | QA + DevOps | 测试报告包含 P50/P95/P99 延迟 |
| S7-05 | OWASP Top 10 安全检查清单执行 | 5 | S5-01~S5-09 | QA + 安全工程师 | 0 个 Critical/High 项未解决 |
| S7-06 | 浏览器兼容性矩阵 (Chrome 120+/Firefox 120+/Safari 17+/Edge 120+) | 5 | S4-06 | QA | 每个浏览器 5 条 E2E 通过 |
| S7-07 | 所有测试集成到 CI 中自动运行 | 5 | S7-01~S7-03 | DevOps | PR 页面可见测试结果 |
| S7-08 | 测试报告仪表板 (Allure 或类似) | 3 | S7-01~S7-03 | Tech Lead | HTML 报告可被非技术人员浏览 |

### 3.9 Sprint 8: 生产就绪 (第 10 周)

| ID | 任务 | 故事点 | 依赖 | 负责人 | 接收标准 |
|----|------|--------|------|--------|---------|
| S8-01 | 多阶段 Dockerfile: Stage 1 编译 C++, Stage 2 Python 运行时, Stage 3 Nginx | 8 | S0-01, S0-03 | DevOps | `docker build` 镜像 < 500MB |
| S8-02 | `docker-compose.prod.yml` 含健康检查/资源限制/重启策略 | 5 | S8-01 | DevOps | `docker-compose -f docker-compose.prod.yml up` 全部 healthy |
| S8-03 | CI/CD: push → lint → test → build image → push registry → deploy | 8 | S7-07 | DevOps | 整个流水线 < 15 分钟 |
| S8-04 | Prometheus 告警规则 (PagerDuty/钉钉 webhook) | 5 | S6-04 | DevOps | 错误率 > 5% 触发告警 |
| S8-05 | 日志聚合: 结构化 JSON 日志 + Loki/Promtail | 5 | S5-05 | DevOps | Grafana 可搜索所有服务日志 |
| S8-06 | API 文档完善: 每个端点含 curl 示例和响应示例 | 5 | S2-01~S2-04 | Python 后端 | OpenAPI docs 中每个端点有 example |
| S8-07 | ONBOARDING.md 验证: 新成员 30 分钟内启动全栈 | 3 | S0-11 | Tech Lead | 按文档操作计时 < 30 分钟 |
| S8-08 | Reality Checker 重新审计 | 8 | S0-S7 全部 | 全员 | 得分 > 80/100 (从 33 提升至 80+) |

---

### 3.10 关键路径 (Critical Path)

以下是决定项目最早完成时间的关键任务链:

```
S0-01 (C++ 编译)
  → S1-01 (JSON 输出) → S1-08 (Python 调用 C++)
    → S2-01 (API 联调) → S2-10 (契约测试)
      → S6-03 (Cache-Aside) → S6-08 (负载测试)
        → S7-04 (Locust 脚本) → S7-07 (CI 集成)
          → S8-03 (完整 CI/CD) → S8-08 (Reality Checker)

备用路径 (并行):
S0-05 (前端启动) → S4-02 (响应式) → S6-06 (WebGL 性能)
S0-06 (Docker) → S3-01~S3-03 (DB Schema) → S4-?? (前端对接数据)

安全路径 (并行):
S2-01~S2-04 (API) → S5-04 (API Key) → S5-01~S5-09 (安全头) → S7-05 (安全审计)
```

**关键路径总耗时**: 10 周
**风险缓冲安排**: 每周预留 20% 缓冲 (故事点计算已包含)

---

## 4. 风险登记册

### 风险评分标准

| 维度 | 低 (1) | 中 (2) | 高 (3) |
|------|--------|--------|--------|
| 概率 | < 20% | 20-60% | > 60% |
| 影响 | 单 Sprint 延迟 < 1 天 | 单 Sprint 延迟 2-4 天 | 整个项目延迟 > 1 周 |
| 得分 | 1-2 低风险 | 3-4 中风险 | 6-9 高风险 |

### 技术风险

| ID | 风险描述 | 概率 | 影响 | 得分 | 缓解措施 | 触发条件 | 负责人 |
|----|---------|------|------|------|---------|---------|--------|
| R01 | **AI 代码隐藏缺陷**: 大量 AI 生成的代码未执行过, 存在未发现的逻辑错误、边界条件 bug 或死代码 | 高 (3) | 高 (3) | **9** | 每个 Sprint 预留 20% 缓冲时间; Sprint 0 全部代码走读; 每个模块先跑通再优化; 强制 Code Review | Sprint 0 期间发现 > 10 个 bug | Tech Lead |
| R02 | **C++ JSON 输出格式错误**: stdout 混入日志导致 Python 端 JSON 解析失败 | 中 (2) | 高 (3) | **6** | 强制 stdout/stderr 分离; Python 端增加 JSON 解析容错 (跳过非 JSON 行); 添加 schema_version 字段; 集成测试覆盖 | Python 调用 C++ 返回非 JSON 文本 | C++ 工程师 |
| R03 | **C++ 算法结果正确性**: 手写算法可能存在逻辑错误导致结果偏差 | 中 (2) | 高 (3) | **6** | 每个算法编写金标准验证 (已知输入→已知输出); 与 NetworkX 结果交叉验证; Catch2 参数化测试 | 任一算法与金标准偏差 > 1% | C++ 工程师 |
| R04 | **Betweenness Centrality 规模瓶颈**: 50K+ 边无法在可接受时间内完成 | 高 (3) | 中 (2) | **6** | 提前实现采样近似算法; 设置计算超时 (30s); 前端显示近似结果标识 | Benchmark 50K 边 > 30 秒 | C++ 工程师 |
| R05 | **Python 依赖版本冲突**: pip install 时因依赖版本不兼容导致安装失败 | 中 (2) | 中 (2) | **4** | 使用 pip-tools + requirements.in, 生成精确版本的 requirements.txt; CI 中用缓存加速 pip | `pip install` 报冲突错误 | Python 后端 |
| R06 | **Docker 跨平台兼容性**: Windows/Mac/Linux 上 Docker 行为不一致 (路径/换行/权限) | 中 (2) | 中 (2) | **4** | 使用相对路径 + .dockerignore; 避免 `chmod`; 在 CI 中矩阵测试 3 平台 | 非 Linux 上 docker-compose 失败 | DevOps |
| R07 | **WebGL 大数据量渲染性能**: 5K+ 节点时浏览器掉帧严重甚至崩溃 | 中 (2) | 中 (2) | **4** | 实现 LOD/节点合并/视锥剔除; 限制默认渲染节点数, 提供"加载更多"选项 | 3K 节点时帧率 < 15fps | 前端工程师 |
| R08 | **Neo4j 查询性能**: 图拓扑查询在大数据集上过慢 | 低 (1) | 中 (2) | **2** | 预计算常用查询结果到 Redis; 添加查询超时; Neo4j query profiling | 全图查询 > 5 秒 | Python 后端 |

### 人员风险

| ID | 风险描述 | 概率 | 影响 | 得分 | 缓解措施 | 触发条件 | 负责人 |
|----|---------|------|------|------|---------|---------|--------|
| R09 | **知识单点依赖**: 每个模块只有 1 人深入理解, 关键人员请假导致阻塞 | 中 (2) | 高 (3) | **6** | 每日站会交叉分享; 每个模块至少有第二负责人; 完善文档和代码注释; Sprint 轮岗 | 关键人员请假 > 3 天 | Tech Lead |
| R10 | **AI 辅助工具限制**: 开发者过度依赖 AI 而非理解代码, 导致修改时引入新问题 | 中 (2) | 中 (2) | **4** | Code Review 严格要求理解逻辑; 每个 PR 需附变更原理说明; 关键模块需手写测试 | PR 描述缺乏业务逻辑说明 | Tech Lead |

### 进度风险

| ID | 风险描述 | 概率 | 影响 | 得分 | 缓解措施 | 触发条件 | 负责人 |
|----|---------|------|------|------|---------|---------|--------|
| R11 | **测试工作量低估**: Sprint 7 (测试 QA) 60 点估时可能不足, 测试编写比预期耗时 | 中 (2) | 高 (3) | **6** | 从 Sprint 0 开始逐步编写测试 (而非全部堆到 Sprint 7); 每个 Sprint 要求对应模块测试覆盖率增长 | Sprint 7 前两天进展 < 20% | Tech Lead + QA |
| R12 | **安全修复连环影响**: 安全加固 (CSP/CSRF) 可能破坏现有功能, 导致大量返工 | 中 (2) | 中 (2) | **4** | 安全变更先上 staging; 每个安全变更配回滚方案; E2E 测试覆盖核心流程 | 安全变更后 E2E 测试失败 | 安全工程师 |
| R13 | **范围蔓延 (Scope Creep)**: 开发过程中"再加一个小功能"持续累积 | 中 (2) | 中 (2) | **4** | Sprint 计划锁死后不接受新需求; 新需求入 backlog, 下个版本评估; Tech Lead 做需求守门人 | Sprint 中期新增 > 2 个需求 | Tech Lead |

### 外部依赖风险

| ID | 风险描述 | 概率 | 影响 | 得分 | 缓解措施 | 触发条件 | 负责人 |
|----|---------|------|------|------|---------|---------|--------|
| R14 | **第三方服务不可用**: Neo4j/Redis 等依赖服务版本更新导致 API 不兼容 | 低 (1) | 中 (2) | **2** | docker-compose 固定版本号; lazy-connect 优雅降级; 核心功能不依赖任何外部服务 | 服务版本号 major 升级 | DevOps |
| R15 | **CDN 引入问题**: CDN 加载的 `3d-force-graph` 等脚本版本变更或 CDN 不可用 | 低 (1) | 中 (2) | **2** | SRI 哈希锁定版本; 提供本地 fallback; 监控 script 加载错误 | CDN 脚本加载超时 > 5s | 前端工程师 |

### 安全风险

| ID | 风险描述 | 概率 | 影响 | 得分 | 缓解措施 | 触发条件 | 负责人 |
|----|---------|------|------|------|---------|---------|--------|
| R16 | **凭据泄露**: 硬编码凭据、.env 文件误提交、日志中打印敏感信息 | 中 (2) | 高 (3) | **6** | `.gitignore` 包含所有敏感文件; pre-commit hook 扫描硬编码凭据; CI 中运行 git-secrets | 代码中发现明文密码 | 安全工程师 |
| R17 | **API 未授权访问**: API Key 权限校验未覆盖所有端点, 低权限用户可执行敏感操作 | 中 (2) | 高 (3) | **6** | 每个端点单元测试验证权限矩阵; 安全审计工具自动化扫描; 默认拒绝策略 | viewer 角色成功调用管理端点 | 安全工程师 |
| R18 | **依赖供应链攻击**: 第三方 pip/npm 包被投毒或包含已知漏洞 | 低 (1) | 高 (3) | **3** | 锁定依赖版本; CI 中运行 pip-audit/npm audit/trivy; 定期更新依赖; 最小化依赖数量 | 安全扫描发现 Critical 漏洞 | DevOps |

### 风险热力图

```
影响 ↑
高(3) │ R17  R09  R01
      │ R16  R02  R03
      │
中(2) │ R07  R12  R04  R11
      │ R06  R05  R10  R13
      │ R14  R15
低(1) │ R18
      │
      └──────────────────────→ 概率
        低(1)    中(2)    高(3)
```

**TOP 5 高风险项 (得分 >= 6)**:
1. **R01**: AI 代码隐藏缺陷 (9) -- 最高优先级缓解
2. **R02**: C++ JSON 格式错误 (6)
3. **R03**: C++ 算法正确性 (6)
4. **R04**: Betweenness Centrality 规模 (6)
5. **R09**: 知识单点依赖 (6)

---

## 5. 团队协作清单与里程碑追踪

### 5.1 每日站会格式

**时间**: 每天 09:15, 严格 15 分钟
**参与人**: C++ 工程师 / Python 后端 / 前端工程师 / DevOps / QA / Tech Lead
**格式**: 每人回答 3 个问题:

1. **昨天完成了什么** (对应的任务 ID, 如 S2-03)
2. **今天计划做什么** (任务 ID + 预计完成度)
3. **遇到什么阻碍** (阻塞项 + 需要的帮助)

**站会后**: 阻塞项负责人留下, 快速排障 (不超过 10 分钟)
**工具**: Slack 或钉钉群 + 共享看板 (GitHub Projects / Linear / Notion)

### 5.2 每周利益相关者更新模板

```markdown
## SocialGraph Pro — 第 {N} 周进度报告

### 总体状态
- Sprint: {Sprint #} "{Sprint 名称}"
- 进度: {已完成点数} / {总点数} ({百分比}%)
- 状态: 🟢 正常 / 🟡 有风险 / 🔴 阻塞

### 本周完成
- [任务ID] 任务描述 ✓
- [任务ID] 任务描述 ✓

### 下周计划
- [任务ID] 任务描述
- [任务ID] 任务描述

### 风险与问题
| 风险 ID | 描述 | 状态 | 缓解措施 |
|---------|------|------|---------|
| R0X | ... | 🟡 监控中 | ... |

### 需要决策的事项
1. {需要利益相关者决策的具体问题}
2. ...

### 燃尽图
{图表: 计划线 vs 实际线}

### 下个里程碑
{M2: 核心稳定 — 目标第 4 周, 当前预计第 X 周}
```

### 5.3 代码审查检查清单

**每个 PR 必须检查的项目**:

#### 通用检查项
- [ ] 代码能编译/运行 (CI 绿灯)
- [ ] 所有测试通过 (新增 + 回归)
- [ ] 无硬编码凭据/密钥/IP 地址
- [ ] 无 `console.log` / `print` 调试日志残留
- [ ] 错误处理完善 (不吞异常、不暴露内部信息)

#### C++ 专项
- [ ] 内存管理正确 (无悬空指针/内存泄漏/use-after-free)
- [ ] `stdout` 仅输出 JSON, 日志全部走 `stderr`
- [ ] 新算法有对应的 Catch2 测试和性能基准

#### Python 专项
- [ ] 类型注解完整 (mypy 检查通过)
- [ ] 新端点有 OpenAPI 文档 (description + response model)
- [ ] 异步操作使用 `async/await`, 无阻塞调用
- [ ] 数据库操作有连接检查和重试逻辑
- [ ] 用户输入已做 Pydantic 校验

#### 前端专项
- [ ] 无 XSS 风险 (用户输入经 DOMPurify 处理)
- [ ] 响应式 4 断点测试通过
- [ ] 键盘可访问 (Tab 顺序合理)
- [ ] 无性能退化 (Lighthouse 评分不降低)

#### 安全专项
- [ ] 权限校验覆盖 (API Key / JWT scope 检查)
- [ ] 敏感操作有审计日志
- [ ] 速率限制对该端点有效

### 5.4 部署检查清单 (Pre-flight Verification)

**每次部署到 staging 或 production 前必须验证**:

```
[ ] 所有 CI 测试通过 (单元 + 集成 + E2E)
[ ] 安全扫描无 Critical/High 漏洞
[ ] 性能基准测试未退化 (页面加载 + API 延迟 + 算法耗时)
[ ] Docker 镜像构建成功且大小 < 500MB
[ ] docker-compose up 所有服务健康检查通过
[ ] 数据库迁移脚本已验证 (向前兼容)
[ ] 回滚方案已测试 (可回退到上一版本)
[ ] 监控仪表板正常展示
[ ] 告警规则已配置且测试通知可达
[ ] 发布说明 (Release Notes) 已准备
```

### 5.5 Sprint 回顾格式

**时间**: 每个 Sprint 最后一个工作日下午 (1.5 小时)
**参与人**: 全团队
**流程**:

#### 第一部分: 数据回顾 (20 分钟)
- 燃尽图: 计划 vs 实际
- 完成率: 承诺故事点 vs 实际完成
- 质量指标: bug 数量 / 回归率 / 测试覆盖率
- 团队速率趋势图

#### 第二部分: 做得好的 (15 分钟)
每人至少 1 条:
- 什么流程/工具/实践提升了效率
- 什么协作方式值得保持

#### 第三部分: 需要改进的 (20 分钟)
每人至少 1 条:
- 什么阻碍了进度
- 什么流程可以优化

#### 第四部分: 行动计划 (20 分钟)
- 投票选出 TOP 3 改进项
- 为每个改进项指定负责人和截止日期
- 下个 Sprint 追踪改进效果

#### 第五部分: 下个 Sprint 展望 (15 分钟)
- 确认 Sprint 计划
- 确认依赖已解除
- 团队能力/休假调整

### 5.6 里程碑追踪

| 里程碑 | 目标周 | 门禁标准 | Go/No-Go 决策人 | 通过条件 |
|--------|--------|---------|----------------|---------|
| **M1: 代码可运行** | 第 2 周 | 1. `cmake --build` 零错误<br>2. `uvicorn server:app` 启动成功<br>3. 前端页面无 console error<br>4. 13 个 pytest 全部通过<br>5. `docker-compose up` 全部服务 healthy | Tech Lead | 5/5 项通过 |
| **M2: 核心稳定** | 第 4 周 | 1. 10 个 C++ 算法输出合法 JSON<br>2. 8 个 API 端点端到端可用<br>3. Catch2 覆盖率 > 80%<br>4. 所有算法结果与金标准一致 | Tech Lead + QA | 4/4 项通过 |
| **M3: 功能完整** | 第 7 周 | 1. 所有 API 端点 + UI 面板可用<br>2. MySQL/MongoDB/Neo4j 在真实实例运行<br>3. 前端 4 断点 + WCAG 2.1 AA 合规<br>4. 安全头扫描得分 > 85<br>5. E2E 测试通过 | 产品负责人 | 5/5 项通过 |
| **M4: 安全审计通过** | 第 9 周 | 1. OWASP Top 10 0 个 Critical/High<br>2. 依赖扫描 0 个 Critical 漏洞<br>3. API Key 权限矩阵全覆盖<br>4. 审计日志完整<br>5. 渗透测试无严重发现 | 安全工程师 | 5/5 项通过 |
| **M5: 生产就绪** | 第 10 周 | 1. Reality Checker 评分 > 80<br>2. 100 并发 P95 < 500ms<br>3. CI/CD 完整流水线可用<br>4. 生产 Docker 镜像 < 500MB<br>5. 监控 + 告警 + 日志聚合就绪<br>6. 所有文档完整且经验证 | 全体利益相关者 | 6/6 项通过 |

### 5.7 Go/No-Go 决策流程

```
每个里程碑评估:
  1. QA 提供客观数据 (测试结果/覆盖率/性能报告)
  2. Tech Lead 评估技术债务和架构风险
  3. 决策人基于门禁标准做出判断

Go:
  - 继续进入下一 Sprint
  - 风险项进入跟踪列表

No-Go:
  - 暂停新功能开发
  - 识别未通过的根本原因
  - 制定补救 Sprint (最多 1 周)
  - 补充 Sprint 完成后重新评估
  - 如连续 2 次 No-Go, 上报利益相关者重新评估项目时间线
```

### 5.8 沟通渠道

| 场景 | 渠道 | 频率 | 参与人 |
|------|------|------|--------|
| 每日站会 | 钉钉视频 / Slack huddle | 每天 09:15 | 全团队 |
| Sprint 计划 | 会议室 + 共享屏幕 | 每 2 周 (Sprint 第一天) | 全团队 |
| Sprint 回顾 | 会议室 | 每 2 周 (Sprint 最后一天) | 全团队 |
| 利益相关者更新 | 邮件 + 文档分享 | 每周五 17:00 | 利益相关者 |
| 技术方案评审 | 会议室 + 架构文档 | 按需 | Tech Lead + 相关工程师 |
| 紧急问题 | 钉钉紧急群 / PagerDuty | 随时 | On-call + Tech Lead |

### 5.9 团队角色定义

| 角色 | 成员 | 职责范围 |
|------|------|---------|
| **Tech Lead** | (指派) | 架构决策、代码审查最终批准、技术债务管理、跨模块协调 |
| **C++ 工程师** | (指派) | `backend_cpp/` 所有代码, 算法正确性, JSON 输出规范 |
| **Python 后端** | (指派) | `middleware_python/` 所有代码, API 设计, 数据库驱动 |
| **前端工程师** | (指派) | `frontend_web/` 所有代码, UI/UX, 可访问性, 性能 |
| **DevOps** | (指派) | Docker, CI/CD, 监控, 部署, 基础设施 |
| **QA** | (指派) | 测试策略, 手工测试, 自动化测试, 性能测试, 安全测试 |
| **安全工程师** | (指派或兼任) | 安全审计, 渗透测试, 安全头配置, 凭据管理 |
| **产品负责人** | (指派) | 需求优先级, 用户故事确认, Milestone Go/No-Go 决策 |

---

## 附录 A: 成功指标

| 指标 | 当前基线 | 目标 (第 10 周) |
|------|---------|----------------|
| Reality Checker 评分 | 33/100 | > 80/100 |
| C++ 编译 | 未验证 | 零错误 |
| FastAPI 启动 | 未验证 | 零错误 |
| pytest 通过率 | 未验证 | 100% (> 200 测试) |
| Catch2 覆盖率 | 0% | > 90% |
| API P95 延迟 (100 并发) | 未测试 | < 500ms |
| PageRank 10K 边 | 未测试 | < 2s |
| 安全头评分 | 未测试 | Mozilla Observatory > 85 |
| WCAG 可访问性 | 未测试 | Lighthouse > 90 |
| Docker 镜像大小 | 无 | < 500MB |

## 附录 B: 文档索引

- [项目设置指南](SETUP.md)
- [架构设计文档](ARCHITECTURE.md)
- [新人入职指南](ONBOARDING.md)
- [项目 README](../README.md)
- [Redis 缓存策略](../database/redis/cache_strategy.md)
- [MySQL Schema](../database/mysql/001_init_schema.sql)
- [MongoDB Schema](../database/mongodb/schema_design.js)

---

*本文档由 Project Shepherd 生成, 版本 1.0。所有时间线均为预估, 实际进度受风险因素影响。每 2 周更新一次。*
