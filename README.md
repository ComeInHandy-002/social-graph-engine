# 社交网络关系分析工具

一个工程级的社交网络关系分析工具，基于C++后端、Python中间件和Web前端的全栈架构实现。

## 项目结构

```
.
├── backend_cpp/          # C++后端实现
│   ├── CMakeLists.txt    # CMake配置文件
│   ├── include/          # 头文件目录
│   │   └── Graph.h      # 图数据结构和算法接口
│   └── src/             # 源代码目录
│       ├── main.cpp     # 主程序入口
│       └── BFS.cpp      # 广度优先搜索算法实现
├── middleware_python/   # Python中间件
│   ├── app.py           # Flask应用主程序
│   ├── requirements.txt # Python依赖包列表
│   └── utils/           # 工具模块
│       └── cpp_runner.py # C++程序运行器
├── frontend_web/        # Web前端
│   ├── index.html       # 主页面
│   └── js/              # JavaScript代码
│       └── main.js      # 前端逻辑
└── docker-compose.yml   # Docker编排配置
```

## 架构说明

### 1. C++后端 (backend_cpp)
- **技术栈**: C++17, CMake
- **核心功能**: 
  - 图数据结构实现
  - 图算法核心计算
  - BFS、DFS、最短路径等算法
- **特点**: 高性能计算，适合大规模图数据处理

### 2. Python中间件 (middleware_python)
- **技术栈**: Flask, NetworkX, NumPy
- **核心功能**:
  - REST API服务
  - 请求路由和参数解析
  - C++后端程序管理
  - 数据格式转换
- **特点**: 灵活的业务逻辑处理，易于扩展

### 3. Web前端 (frontend_web)
- **技术栈**: HTML5, JavaScript, D3.js, Vis.js
- **核心功能**:
  - 图形化界面展示
  - 交互式操作
  - 实时结果可视化
- **特点**: 直观的用户交互，丰富的可视化效果

## 快速开始

### 使用Docker (推荐)

```bash
# 克隆项目
git clone <repository-url>
cd social-network-analysis

# 启动所有服务
docker-compose up -d

# 查看日志
docker-compose logs -f
```

### 手动启动

#### 1. 启动C++后端
```bash
cd backend_cpp
mkdir build && cd build
cmake ..
make
./SocialNetworkAnalysis
```

#### 2. 启动Python中间件
```bash
cd middleware_python
pip install -r requirements.txt
python app.py
```

#### 3. 启动Web前端
```bash
cd frontend_web
python -m http.server 8000
# 或使用nginx等Web服务器
```

## API接口

### 图分析接口
```
POST /api/analyze
```

请求参数:
```json
{
    "graph": {},
    "algorithm": "bfs|dfs|shortest_path",
    "parameters": {}
}
```

### 图加载接口
```
POST /api/load_graph
```

请求参数:
```json
{
    "file_path": "path/to/graph/file"
}
```

### 健康检查接口
```
GET /api/health
```

## 核心算法

### 广度优先搜索 (BFS)
- 时间复杂度: O(V + E)
- 空间复杂度: O(V)
- 功能: 查找最短路径，连通分量检测

### 深度优先搜索 (DFS)
- 时间复杂度: O(V + E)
- 空间复杂度: O(V)
- 功能: 拓扑排序，环检测

### 最短路径
- 实现算法: Dijkstra / BFS (无权图)
- 时间复杂度: O(V^2) / O(E + V)
- 功能: 查找两点间的最短路径

## 扩展功能

### 待实现功能
1. 社区发现算法
2. 图的可视化布局
3. 性能监控和日志记录
4. 用户认证和权限管理
5. 数据导入导出功能

### 性能优化
1. 并行计算支持
2. 缓存机制
3. 增量计算
4. 内存优化

## 开发说明

### 代码规范
- C++: 遵循Google C++风格指南
- Python: 遵循PEP 8规范
- JavaScript: 使用ES6+语法，模块化开发

### 测试策略
1. 单元测试：各算法核心功能
2. 集成测试：端到端API测试
3. 性能测试：大规模图数据处理

### 部署方案
1. Docker容器化部署
2. Kubernetes集群部署
3. 云服务部署（AWS/GCP/阿里云）

## 许可证

MIT License