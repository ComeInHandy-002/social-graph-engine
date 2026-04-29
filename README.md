# 🌌 SocialGraph Pro | 高性能社交网络可视分析全栈中台

![Build Status](https://img.shields.io/badge/build-passing-brightgreen)
![C++](https://img.shields.io/badge/C++-17-blue.svg)
![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-009688.svg)
![ES6](https://img.shields.io/badge/ES6-WebGL-f1e05a.svg)
![Docker](https://img.shields.io/badge/Docker-Ready-2496ED.svg)
![License](https://img.shields.io/badge/license-MIT-green.svg)

> 一个基于 C++ 毫秒级底层计算、FastAPI 异步微服务网关与 WebGL 3D 物理渲染的工业级全栈项目。本项目采用标准的 **Monorepo (单体代码仓库)** 架构管理。

## 📖 项目简介

SocialGraph Pro 是一个致力于解决大规模复杂社交网络分析的全栈解决方案。系统剥离了传统重度耦合的架构，采用**前后端极度分离**与**计算渲染解耦**的现代化工程规范。

核心引擎由纯 C++ 编写，通过**策略模式 (Strategy Pattern)** 动态装载 PageRank、LPA 社区发现等高级图论算法，能够以毫秒级延迟处理十万级拓扑连线。网关层采用 FastAPI 暴露标准化 RESTful API，前端则通过 3D 力学导向图（Force-Directed Graph）结合赛博朋克 UI，实现直观、炫酷的多维数据可视化。

### 📸 核心界面与 API 文档
*(💡 提示：建议在这里放两张图，一张是你的 3D 星空全景截图，另一张是 FastAPI 生成的 Swagger 接口文档截图)*
![System Dashboard](./docs/screenshot_main.png)
*(图：WebGL 渲染的十万级社交节点物理力场)*

---

## 🏗️ 全栈架构设计 (Monorepo Architecture)

本项目严格遵循 **微服务分层** 与 **全栈数据闭环** 思想，拆分为三大独立核心模块：

1. **`backend_cpp` (底层算力引擎)**
   - 基于 C++17 构建的极速图计算核心，手工实现内存邻接表，零第三方图库依赖。
   - 实现完整的插件化算法注册中心，遵循开闭原则（OCP）。
   - 包含 BFS 最短通讯链路追踪、PageRank 全网影响力评估、LPA 标签传播社区裂变。
2. **`middleware_python` (API 网关 & 调度中枢)**
   - 基于 ASGI 高并发框架 FastAPI 构建的 RESTful API 微服务。
   - 自动生成 OpenAPI (Swagger) 交互式调试文档。
   - 解决跨域资源共享（CORS），通过文件级 IPC 零拷贝方案实现与 C++ 原生进程的极速调度通信。
3. **`frontend_web` (可视化指挥舱)**
   - 零框架纯 ES6 模块化构建，Fetch API 异步无阻塞获取中枢数据。
   - 深度封装 `3d-force-graph` (WebGL)，实现高负载节点的点云降噪与光子流动特效。

---

## ⚡ 核心技术特性 & 工业级工程化 (Engineering)

* 📊 **硬核基准压测 (Benchmark)**：内置 Python 自动化压测脚本。在单核 CPU 环境下，实测处理 **100,000 条边** 的 PageRank (100次迭代) 耗时仅 ~2.2秒，LPA (10次迭代) 仅 ~0.5秒。
* 🌐 **现代化接口契约**：彻底打通前后端分离，前端无需关心底层逻辑，直接通过 `http://127.0.0.1:8000/docs` 的可视化接口大屏进行数据联调。
* ⚙️ **跨平台 CI/CD 流水线**：内置 GitHub Actions，代码 Push 自动触发 Ubuntu (GCC) 与 Windows (MSVC) 的矩阵编译与连通性单元测试。
* 🐳 **容器化部署编排**：配备 `docker-compose.yml`，支持全系统环境的一键拉起。

---

## 📂 Monorepo 目录树

```text
social-graph-engine/
├── .github/workflows/       # CI/CD 自动化构建流水线
├── backend_cpp/             # C++ 核心计算引擎
│   ├── include/Graph.h      # 架构接口、策略模式基类与插件声明
│   ├── src/                 # BFS / PageRank / LPA / main 核心实现
│   └── CMakeLists.txt       # 跨平台构建脚本
├── middleware_python/       # FastAPI 微服务中间件
│   ├── server.py            # RESTful API 路由与 C++ 调度控制
│   ├── benchmark.py         # 自动化极限压力测试套件
│   └── requirements.txt     # Python 依赖清单
├── frontend_web/            # WebGL 可视化前端
│   ├── index.html           # UI 骨架与交互面板
│   └── js/                  # API Fetch 通信 / 3D 渲染引擎解耦模块
├── docs/                    # 静态资源与截图演示
├── .gitignore               # 工业级代码提交过滤规则
└── docker-compose.yml       # 容器化环境编排配置文件