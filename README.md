# 🌌 SocialGraph Pro | 高性能社交网络可视分析中枢

![Build Status](https://img.shields.io/badge/build-passing-brightgreen)
![C++](https://img.shields.io/badge/C++-17-blue.svg)
![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-009688.svg)
![ES6](https://img.shields.io/badge/ES6-WebGL-f1e05a.svg)
![License](https://img.shields.io/badge/license-MIT-green.svg)

> 一个基于 C++ 毫秒级图计算引擎、FastAPI 异步微服务网关与 WebGL 3D 物理渲染的工业级全栈项目。

## 📖 项目简介

SocialGraph Pro 是一个致力于解决大规模复杂社交网络分析的全栈解决方案。系统剥离了传统重度耦合的架构，采用**前后端极度分离**与**计算渲染解耦**的现代化工程规范。

核心引擎由纯 C++ 编写，通过策略模式动态装载 PageRank、LPA 社区发现等高级图论算法，能够以毫秒级延迟处理十万级拓扑连线。前端采用 3D 力学导向图（Force-Directed Graph）结合赛博朋克 UI，实现直观、炫酷的多维数据可视化。

### 📸 核心大屏展示
*(💡 提示：在这里放一张你前端网页最炫酷的 3D 星空全景截图)*
![System Dashboard](./docs/screenshot_main.png)

---

## 🏗️ 全栈架构设计 (Architecture)

本项目严格遵循 **MVC 与微服务分层** 思想，拆分为三大独立核心模块：

1. **`backend_cpp` (底层发动机)**
   - 基于 C++17 构建的极速图计算核心。
   - 实现完整的插件化算法注册中心（Strategy Pattern）。
   - 包含 BFS 最短通讯链路追踪、PageRank 全网影响力评估、LPA 标签传播社区裂变。
2. **`middleware_python` (大堂经理 & 网关)**
   - 基于 ASGI 高并发框架 FastAPI 构建的 RESTful API 中枢。
   - 负责跨域资源共享（CORS）与原生 C++ 进程的子进程调度通信。
3. **`frontend_web` (可视化指挥舱)**
   - 零框架纯 ES6 模块化构建，彻底摒弃面条代码。
   - 深度封装 `3d-force-graph` (WebGL)，通过独立渲染层实现千万级光子流动特效。

---

## ⚡ 核心技术特性 (Features)

* 🚀 **极致性能榨取**：C++ 核心在处理 `facebook_combined` 等真实海量数据集时，最短路径与社区发现算法均能压榨至毫秒级响应。
* 🌐 **异步非阻塞网关**：FastAPI 完全接管 I/O 密集型任务，无缝对接前后端数据契约。
* 🎨 **沉浸式 3D 交互**：支持动态调整星系斥力（Repel）与社交张力（Link Distance），内置节点高亮、降噪过滤与动态摄像机追踪。
* ⚙️ **工业级 CI/CD**：内置 GitHub Actions 跨平台流水线，提交代码自动触发 CMake 在 Ubuntu 与 Windows 双端的编译与单元测试。

---

## 📂 核心目录结构

```text
social-graph-engine/
├── backend_cpp/             # C++ 核心计算引擎
│   ├── include/Graph.h      # 核心数据结构与算法接口声明
│   ├── src/                 # BFS / PageRank / LPA 算法实现
│   └── CMakeLists.txt       # 跨平台构建脚本
├── middleware_python/       # FastAPI 微服务中间件
│   ├── server.py            # API 路由与 C++ 进程调度控制
│   └── requirements.txt     # Python 依赖清单
├── frontend_web/            # WebGL 可视化前端
│   ├── index.html           # UI 骨架与加载屏
│   ├── css/style.css        # 赛博朋克主题样式
│   └── js/                  # API通信 / 3D渲染引擎 / 业务调度 解耦模块
└── .github/workflows/       # CI/CD 自动化流水线配置