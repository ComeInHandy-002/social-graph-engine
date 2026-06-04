# 开发环境搭建指南

本文档指导新开发者从零开始搭建 SocialGraph Pro 的完整开发环境。

---

## 1. 系统要求

### 操作系统

| 系统 | 测试状态 |
|------|---------|
| Windows 11 | 完整测试 |
| Ubuntu 22.04+ | CI 矩阵覆盖 |
| macOS (Apple Silicon) | 未充分测试 |

### 编译器与运行时

| 组件 | 最低版本 | 推荐版本 | 说明 |
|------|---------|---------|------|
| CMake | 3.14 | 3.28+ | C++ 构建系统 |
| GCC | 9.0 | 13.0+ | Linux 编译器 |
| MSVC | 2019 (16.0) | 2022 (17.0) | Windows 编译器 (Visual Studio Build Tools) |
| Clang | 12.0 | 18.0+ | macOS / 跨平台编译器 |
| Python | 3.10 | 3.12 | API 网关 |
| pip | 23.0+ | 24.0+ | Python 包管理 |
| Docker | 20.10 | 26.0+ | 容器化部署 |
| Docker Compose | 2.0+ | 2.27+ | 多容器编排 |

### 可选依赖 (手动安装时按需)

| 组件 | 用途 |
|------|------|
| MySQL 8.0 | 用户账户、Session、系统配置 |
| MongoDB 7.0 | 分析快照、操作日志 |
| Redis 7.x | 缓存层 |
| Neo4j 5.x Community | 图拓扑持久化 |
| Node.js 18+ | 前端开发服务器 (替代 Python http.server) |

---

## 2. Docker 全栈安装 (推荐)

Docker 方式一键启动所有服务，适合快速体验和集成测试。

### 启动

```bash
git clone https://github.com/ComeInHandy/socialgraph-pro.git
cd socialgraph-pro
docker-compose up -d
```

### 服务与端口

| 服务 | 端口 | 说明 |
|------|------|------|
| web-frontend (Nginx) | `80` | 前端静态页面 |
| python-middleware (FastAPI) | `8000` | API 网关 |
| mysql | `3306` | 关系型数据库 |
| mongodb | `27017` | 文档数据库 |
| redis | `6379` | 缓存 |
| neo4j | `7474` (HTTP), `7687` (Bolt) | 图数据库 |

### 验证

```bash
# 检查所有容器状态
docker-compose ps

# 检查 API 健康
curl http://localhost:8000/api/v1/health

# 检查前端
curl -s -o /dev/null -w "%{http_code}" http://localhost/
# 应返回 200

# 检查 Neo4j
curl http://localhost:7474
```

### 停止

```bash
docker-compose down          # 停止并删除容器
docker-compose down -v       # 同时删除数据卷 (重置所有数据)
```

---

## 3. 手动安装 (按组件)

### 3.1 C++ 引擎

C++ 引擎是最核心的组件，Python 网关通过 `subprocess` 调用它。

```bash
cd backend_cpp

# 配置 (Release 模式，开启优化)
cmake -B build -DCMAKE_BUILD_TYPE=Release

# 编译
cmake --build build --config Release

# 验证 (CI 连通性测试)
./build/graph_engine run_test
# 输出: [INFO] CI/CD 云端构建连通性测试通过！引擎状态健康。

# 试运行一个小算法
./build/graph_engine facebook_combined.txt pagerank | head -c 200
# 应输出 JSON
```

**Windows 注意事项**：
- CMake 默认生成 MSVC 项目，确保安装了 Visual Studio Build Tools 或完整的 Visual Studio
- 编译产物路径在 `build/Release/graph_engine.exe`
- 可使用 `cmake -G "MinGW Makefiles"` 切换为 MinGW 编译

**macOS 注意事项**：
- 需要 `xcode-select --install` 安装命令行工具
- 可能需要 `brew install cmake`

### 3.2 Python API 网关

```bash
cd middleware_python

# 创建虚拟环境 (推荐)
python -m venv venv

# 激活虚拟环境
# Windows:
venv\Scripts\activate
# macOS/Linux:
source venv/bin/activate

# 安装依赖
pip install -r requirements.txt

# 验证安装
python -c "import fastapi; import aiomysql; import neo4j; print('OK')"

# 启动 (开发模式，支持热重载)
uvicorn server:app --reload --port 8000

# 验证
curl http://127.0.0.1:8000/api/v1/health/live
# 应返回 {"status": "alive"}
```

**依赖说明**：
- `fastapi` + `uvicorn[standard]` + `pydantic` -- Web 框架核心
- `aiomysql` -- MySQL 异步驱动
- `motor` -- MongoDB 异步驱动
- `redis[hiredis]` -- Redis 异步客户端
- `neo4j` -- Neo4j Python 驱动
- `python-jose[cryptography]` -- JWT 令牌处理
- `bcrypt` -- 密码哈希
- `pytest` + `httpx` -- 测试框架

### 3.3 前端

前端是纯静态文件，无需构建步骤。

```bash
cd frontend_web

# 方式一: Python HTTP 服务器
python -m http.server 3000

# 方式二: Node.js (需要先安装)
npx serve . -p 3000

# 方式三: 直接打开 (部分浏览器可能有跨域限制)
# 浏览器打开 index.html
```

**验证**：浏览器打开 `http://127.0.0.1:3000`，应看到 "社交引擎控制台" 侧边栏和 3D 星空背景。

**重要**：前端依赖两个外部库通过 CDN 加载：
- `3d-force-graph` (unpkg.com) -- 核心 3D 渲染库
- `Chart.js` (本地 `js/chart.umd.min.js`) -- 统计图表库

请确保网络可访问 CDN，或自行修改 `index.html` 中的 CDN 引用。

---

## 4. 环境变量

### 配置优先级

1. `.env` 文件中的 `SGP_` 前缀变量（推荐新项目使用）
2. 系统环境变量（无 `SGP_` 前缀，向后兼容）
3. `core/config.py` 中的硬编码默认值

### 完整变量列表

#### C++ 引擎

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `SGP_CPP_ENGINE_PATH` / `CPP_ENGINE_PATH` | 自动探测 | graph_engine 可执行文件路径 |
| `SGP_GRAPH_DATA_PATH` / `GRAPH_DATA_PATH` | 自动探测 | 边列表数据文件路径 |
| `SGP_CPP_ENGINE_POOL_SIZE` | `4` | C++ 进程池大小 |

#### JWT 认证

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `SGP_JWT_SECRET_KEY` / `JWT_SECRET_KEY` | `CHANGE_ME_IN_PRODUCTION...` | JWT 签名密钥 (生产环境必须修改) |
| `SGP_JWT_ALGORITHM` | `HS256` | JWT 签名算法 |
| `SGP_ACCESS_TOKEN_EXPIRE_MINUTES` | `15` | Access Token 过期时间 |
| `SGP_REFRESH_TOKEN_EXPIRE_DAYS` | `30` | Refresh Token 过期时间 |

#### Redis

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `SGP_REDIS_HOST` / `REDIS_HOST` | `127.0.0.1` | Redis 主机地址 |
| `SGP_REDIS_PORT` / `REDIS_PORT` | `6379` | Redis 端口 |
| `SGP_REDIS_DB` | `0` | Redis 数据库编号 |
| `SGP_REDIS_PASSWORD` | (空) | Redis 密码 |
| `SGP_REDIS_POOL_MAX_CONNECTIONS` | `20` | 连接池上限 |

#### MySQL

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `SGP_MYSQL_HOST` / `MYSQL_HOST` | `127.0.0.1` | MySQL 主机地址 |
| `SGP_MYSQL_PORT` / `MYSQL_PORT` | `3306` | MySQL 端口 |
| `SGP_MYSQL_USER` / `MYSQL_USER` | `socialgraph` | MySQL 用户名 |
| `SGP_MYSQL_PASSWORD` / `MYSQL_PASSWORD` | `sgpass123` | MySQL 密码 |
| `SGP_MYSQL_DATABASE` / `MYSQL_DATABASE` | `socialgraph` | MySQL 数据库名 |

#### MongoDB

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `SGP_MONGODB_URI` / `MONGODB_URI` | `mongodb://127.0.0.1:27017/` | MongoDB 连接 URI |
| `SGP_MONGODB_DATABASE` / `MONGODB_DATABASE` | `socialgraph_analytics` | MongoDB 数据库名 |

#### Neo4j

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `SGP_NEO4J_URI` / `NEO4J_URI` | `bolt://127.0.0.1:7687` | Neo4j Bolt 地址 |
| `SGP_NEO4J_USER` / `NEO4J_USER` | `neo4j` | Neo4j 用户名 |
| `SGP_NEO4J_PASSWORD` / `NEO4J_PASSWORD` | `password123` | Neo4j 密码 |

#### 应用

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `SGP_DEBUG` | `false` | 调试模式 (开启后 Swagger 在生产环境也可见) |
| `SGP_LOG_LEVEL` | `INFO` | 日志级别 (DEBUG/INFO/WARNING/ERROR/CRITICAL) |
| `SGP_ENVIRONMENT` | `development` | 运行环境 (development/staging/production) |
| `SGP_APP_VERSION` | `3.0.0` | 应用版本号 |

### `.env` 文件示例

```env
# .env 文件 (放在 middleware_python/ 目录下)
SGP_DEBUG=true
SGP_LOG_LEVEL=DEBUG
SGP_JWT_SECRET_KEY=your-256-bit-secret-key-here
SGP_REDIS_HOST=localhost
SGP_MYSQL_HOST=localhost
SGP_MONGODB_URI=mongodb://localhost:27017/
SGP_NEO4J_URI=bolt://localhost:7687
```

---

## 5. IDE 配置

### Visual Studio Code (推荐)

安装以下扩展：

| 扩展 ID | 名称 | 用途 |
|------|------|------|
| `ms-vscode.cpptools` | C/C++ | C++ 语法高亮、IntelliSense、调试 |
| `ms-vscode.cmake-tools` | CMake Tools | CMake 项目配置与构建 |
| `ms-python.python` | Python | Python 支持 |
| `ms-python.vscode-pylance` | Pylance | Python 类型检查 |
| `dbaeumer.vscode-eslint` | ESLint | JavaScript 代码规范 |
| `editorconfig.editorconfig` | EditorConfig | 统一编辑器设置 |
| `redhat.vscode-yaml` | YAML | Docker Compose / CI 文件支持 |

### 推荐设置 (`.vscode/settings.json`)

```json
{
  "files.exclude": {
    "**/__pycache__": true,
    "**/*.pyc": true,
    "backend_cpp/build": true,
    "backend_cpp/cmake-build-debug": true,
    "backend_cpp/cmake-build-release": true
  },
  "python.linting.enabled": true,
  "editor.formatOnSave": true,
  "editor.tabSize": 4,
  "[python]": {
    "editor.tabSize": 4
  },
  "[javascript]": {
    "editor.tabSize": 2
  }
}
```

### CLion (JetBrains)

CLion 原生支持 CMake 项目。打开 `backend_cpp/` 目录即可自动检测 CMakeLists.txt。

---

## 6. 验证清单

完成搭建后，逐一执行以下命令确认所有组件正常工作：

### C++ 引擎

```bash
# 1. CI 测试
cd backend_cpp && ./build/graph_engine run_test
# 期望: 正常退出 (exit code 0)

# 2. 完整测试套件
cd build && ctest --output-on-failure -C Release
# 期望: All tests passed

# 3. 手动运行算法
./graph_engine ../facebook_combined.txt graph_stats
# 期望: stdout 输出 JSON，包含 nodes / edges / density 等字段
```

### Python 网关

```bash
# 4. 存活检查
curl http://127.0.0.1:8000/api/v1/health/live
# 期望: {"status": "alive"}

# 5. 深度健康检查 (需数据库)
curl http://127.0.0.1:8000/api/v1/health
# 期望: {"status": "healthy"|"degraded", "components": {...}}

# 6. Swagger 文档可访问
curl http://127.0.0.1:8000/docs
# 期望: HTTP 200

# 7. Python 测试
cd middleware_python && pytest tests/ -v
# 期望: All tests passed
```

### 前端

```bash
# 8. 静态文件可访问
curl http://127.0.0.1:3000/index.html | head -5
# 期望: HTML 内容

# 9. 前端 JS 模块无语法错误
# 浏览器打开 http://127.0.0.1:3000
# 打开开发者工具 Console → 应无红色错误
# 期望: 看到 "[App] 后端健康检查通过" 或 "[App] 后端不可达"
```

### Docker

```bash
# 10. 所有容器运行中
docker-compose ps
# 期望: 6/6 容器状态为 Up 且 healthy
```

---

## 7. 常见问题

### Q: `cmake` 命令找不到
**A**: 安装 CMake 并确保已加入 PATH。Windows 用户可使用 `winget install Kitware.CMake`。

### Q: C++ 编译报 `C++17` 相关错误
**A**: 升级编译器。GCC 9+, MSVC 2019+, Clang 12+ 均支持 C++17。

### Q: `pip install -r requirements.txt` 报错
**A**: 确保 Python 版本为 3.10+：`python --version`。某些包（如 `hiredis`）在 Windows 上可能需要预编译二进制或 Visual C++ Build Tools。

### Q: 前端加载后 3D 图不显示
**A**: 检查浏览器控制台是否有 CDN 加载错误。确保网络可访问 `unpkg.com`。中国大陆用户可能需要代理或替换 CDN 源（如 `cdn.bootcdn.net`）。

### Q: API 返回 "C++ 引擎不可用"
**A**: 确保 C++ 引擎已编译且路径正确。检查 `SGP_CPP_ENGINE_PATH` 或 `CPP_ENGINE_PATH` 环境变量。默认自动探测以下路径：
1. `../backend_cpp/cmake-build-release/graph_engine.exe`
2. `../backend_cpp/cmake-build-debug/graph_engine.exe`
3. `../backend_cpp/build/graph_engine`
4. `../backend_cpp/build/graph_engine.exe`

### Q: MySQL/MongoDB/Redis/Neo4j 连接失败
**A**: Python 网关采用 lazy-connect 模式，数据库不可用时会自动降级。核心算法 (PageRank/LPA/路径查询) 仍可正常工作，仅部分功能受影响。
