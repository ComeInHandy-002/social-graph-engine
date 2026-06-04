# SocialGraph Pro — 测试与实验策略

> 版本: 1.0.0 | 最后更新: 2026-05-02 | 适用版本: SocialGraph Pro v3.0.0

---

## 目录

1. [A/B 测试策略 (UI/UX)](#1-ab-测试策略-uiux)
2. [性能基准测试策略](#2-性能基准测试策略)
3. [负载测试策略](#3-负载测试策略)
4. [可靠性测试策略](#4-可靠性测试策略)

---

## 1. A/B 测试策略 (UI/UX)

### 1.1 实验平台与基础设施

| 组件 | 方案 | 说明 |
|------|------|------|
| 分流引擎 | 前端 JavaScript 分流（Math.random 哈希到 cookie） | 无需服务端改动，客户端确定性分流 |
| 数据采集 | MongoDB `ab_experiments` + `ab_events` 集合 | 复用现有 MongoDB 日志基础设施 |
| 统计分析 | Python `scipy.stats` (ttest_ind / mannwhitneyu / chi2) | 离线 Jupyter Notebook 分析 |
| 实验配置 | `experiments_config.json` 前端静态配置 | 可通过 Admin API 动态更新 |

**分流算法:**

```
bucket = md5(user_id + experiment_id).first_hex_digit
variant = "A" if bucket < "8" else "B"   // 50/50 split
```

**前提条件:**
- 用户需登录（有 user_id），匿名用户不参与实验
- 同一用户在同一实验中始终分配到同一变体（一致性哈希）
- 每个实验开始前需要 7 天 A/A 测试期验证分流均匀性

---

### 1.2 测试 1: 图渲染模式 (Graph Rendering Mode)

#### 假设

> **H1**: LOD (Level of Detail) 渲染模式在节点数 > 2000 的图中，相比全细节渲染，可将平均 FPS 提升 30%，且用户对渲染质量的主观评分无显著下降（非劣效边际 < 0.5 分，满分 5 分）。

#### 实验设计

| 维度 | 变体 A (Control) | 变体 B (Treatment) |
|------|-----------------|-------------------|
| 渲染策略 | 全细节渲染：所有节点使用球体几何（32 segments） | LOD 渲染：距离 > 阈值 → 点精灵; 中距离 → 低面球体 (8 segments); 近距离 → 全细节 (32 segments) |
| 标签渲染 | 所有节点标签以 12px 渲染 | 仅近距离节点标签渲染; 远距离节点无标签 |
| 连线渲染 | 所有连线以 LINE_STRIP 渲染 | 远距离连线以半透明细线渲染; 近距离正常 |

#### 评价指标

| 指标 | 类型 | 测量方式 | 目标 |
|------|------|---------|------|
| **平均 FPS** | 主指标 | `requestAnimationFrame` 采样，每秒记录一次，取会话中位数 | +30% |
| 渲染帧时间 (ms) | 副指标 | `performance.now()` 在每帧开始/结束计时 | <16.67ms (60fps) |
| 主观质量评分 | 非劣效指标 | 用户完成操作后弹出 1-5 星评分 | 非劣效边际 < 0.5 |
| 节点识别准确率 | 副指标 | 任务测试：给用户看节点 ID，要求点击正确节点 | B 不低于 A 的 95% |
| 图形内存占用 (MB) | 安全指标 | `performance.memory.usedJSHeapSize` | B 不超过 A 的 120% |

#### 样本量与持续时间

**样本量计算 (平均 FPS):**
- 预期效应量 (Cohen's d): 0.30 (中等，基于 FPS 标准差通常约 10fps)
- 显著性水平 (alpha): 0.05 (双尾)
- 统计功效 (1 - beta): 0.80
- 所需样本量: **每组 176 人，共 352 人**

**非劣效检验补充要求:**
- 非劣效边际: 0.5 分 (5 分制)
- 所需样本量 (90% 功效): **每组 210 人，共 420 人**
- 取较大值: **每组 210 人，共 420 人**

**持续时间估算:**
- 日均活跃用户假设: 50 人/天
- 所需实验天数: 420 / 50 = **8.4 天**
- 加 20% 缓冲 (考虑工作日效应): **10 天**
- 加 7 天 A/A 测试: **总计 17 天**

#### 统计方法

1. **主指标 (平均 FPS)**: Welch 双样本 t 检验（不假设方差齐性），alpha = 0.05，双尾
2. **非劣效检验 (质量评分)**: 单尾非劣效 t 检验，H0: B_quality <= A_quality - 0.5
3. **节点识别准确率**: 比例差检验 (two-proportion z-test)
4. **多重比较校正**: Bonferroni 校正 (3 个核心指标 → alpha_per_comparison = 0.0167)

#### 成功判定标准

- FPS 提升 ≥ 25%（留有安全边际，不低于 30% 目标值太远）
- 主观评分非劣效检验通过 (p < 0.05)
- 节点识别准确率不显著低于 A (p > 0.0167 或差异 < 5%)
- 内存增长 ≤ 20%
- **以上条件全部满足才视为成功**

#### 回滚方案

1. 前端 `experiments_config.json` 中设置 `rendering_mode_experiment.active = false` → 所有用户回退到变体 A
2. 若发现内存泄漏或崩溃率上升 > 2%，立即自动回滚 (kill switch)
3. 回滚后保留已采集数据，不丢弃

---

### 1.3 测试 2: 搜索交互 (Search UX)

#### 假设

> **H2**: 实时防抖搜索（debounce 300ms）相比回车触发搜索，可将用户找到目标节点的平均时间减少 40%。

#### 实验设计

| 维度 | 变体 A (Control) | 变体 B (Treatment) |
|------|-----------------|-------------------|
| 触发方式 | 用户在搜索框输入关键词，按 Enter 键触发搜索 | 用户输入时自动搜索 (debounce 300ms)，同时保留 Enter 键行为 |
| 反馈模式 | 按 Enter 后显示搜索结果下拉列表 | 输入过程中实时更新下拉列表，匹配节点高亮 |
| 搜索范围 | 精确子串匹配 + 节点 ID 匹配 | 模糊匹配 (Levenshtein 距离 < 3) + ID 前缀匹配 + 社区标签匹配 |

#### 评价指标

| 指标 | 类型 | 测量方式 | 目标 |
|------|------|---------|------|
| **找到目标节点时间 (秒)** | 主指标 | 从聚焦搜索框到点击目标节点的时间 | -40% |
| 搜索放弃率 | 副指标 | 搜索框失焦或关闭且未点击任何结果 | -30% |
| 搜索准确率 (Top-1) | 副指标 | 用户点击的第一个结果即为目标 | > 90% |
| 键盘交互次数 | 副指标 | 完成任务所需按键次数 | 减少 |
| 搜索 API 调用次数 | 安全指标 | 每次搜索请求的 API 调用数 | B < A x 3 |

#### 样本量与持续时间

**样本量计算 (找到目标节点时间):**
- 预期效应量 (Cohen's d): 0.40 (中到大，UX 改进通常效应明显)
- alpha: 0.05, power: 0.80
- 所需样本量: **每组 100 人，共 200 人**

**持续时间:**
- 日均活跃: 50 人/天
- 所需天数: 200 / 50 = 4 天 → 加缓冲 **7 天** + **7 天 A/A** = **14 天**

#### 统计方法

1. **主指标 (找到时间)**: Mann-Whitney U 检验（时间数据通常右偏，非参数方法更稳健）
2. **搜索放弃率**: 卡方检验 (chi-square test of independence)
3. **搜索准确率**: Fisher 精确检验 (样本量适中时比卡方更准确)

#### 成功判定标准

- 找到目标节点时间中位数减少 ≥ 35%
- 搜索放弃率不显著增加 (p > 0.05)
- 搜索准确率 ≥ 85%
- API 调用数增加不超过 3 倍

#### 回滚方案

1. `search_experiment.active = false` → 所有用户恢复 Enter 触发模式
2. 若 API 调用量激增导致服务端限流，通过 `experiments_config.json` 即时关闭，同时将 debounce 从 300ms 改为 500ms 观察
3. 若防抖逻辑导致输入卡顿（主线程耗时 > 50ms），立即回滚

---

### 1.4 测试 3: 配色方案 (Color Scheme)

#### 假设

> **H3**: 基于 LPA 社区归属的节点配色相比统一配色，可将用户识别图簇群结构的准确率提升 25%，识别时间减少 20%。

#### 实验设计

| 维度 | 变体 A (Control) | 变体 B (Treatment) |
|------|-----------------|-------------------|
| 节点颜色 | 统一蓝色 (#4A90D9) | 按 LPA 社区标签自动分配颜色 (d3.schemeCategory10) |
| 图例 | 无图例 | 顶部显示社区颜色图例 (社区 ID + 颜色方块) |
| 高亮 | 统一放大高亮 | 同社区节点共同高亮，异社区节点淡化 |

#### 评价指标

| 指标 | 类型 | 测量方式 | 目标 |
|------|------|---------|------|
| **簇群识别准确率** | 主指标 | 用户标注出图中自然形成的簇群，与 LPA 结果对比 (IoU) | +25% |
| 识别任务完成时间 (秒) | 副指标 | 从展示图形到用户提交标注的时间 | -20% |
| 簇群数量判断准确率 | 副指标 | "图中有多少个密集簇群？" | ±1 误差 |
| 色觉障碍可访问性 | 安全指标 | 通过 Sim Daltonism 模拟 3 种色觉障碍的区分度 | ≥ 7 种颜色可区分 |
| 主观美观评分 | 探索指标 | 用户 1-5 评分 | 不显著低于 A |

#### 样本量与持续时间

**样本量计算 (识别准确率):**
- 预期效应量 (Cohen's h): 0.30（中效应）
- alpha: 0.05, power: 0.80, two-proportion z-test
- 所需样本量: **每组 175 人，共 350 人**

**持续时间:** 350 / 50 = 7 天 + 缓冲 + A/A = **约 16 天**

#### 统计方法

1. **识别准确率**: 双比例 z 检验 (two-proportion z-test)
2. **完成时间**: Mann-Whitney U 检验
3. **色觉无障碍**: 描述性统计（非推断性）

#### 成功判定标准

- 簇群识别准确率提升 ≥ 20%
- 识别时间减少 ≥ 15%
- 色觉障碍下至少 7 种颜色可区分
- 美观评分不低于 A 的 0.5 分

#### 回滚方案

1. `color_scheme_experiment.active = false` → 恢复统一配色
2. 色觉无障碍验证脚本集成到 CI，若新配色方案未通过则阻止上线

---

### 1.5 测试 4: 仪表板布局 (Dashboard Layout)

#### 假设

> **H4**: 顶部对齐的仪表板布局相比侧面板布局，可将用户滚动交互次数减少 50%，定位特定指标的时间减少 30%。

#### 实验设计

| 维度 | 变体 A (Control) | 变体 B (Treatment) |
|------|-----------------|-------------------|
| 布局模式 | 侧面板: 左侧固定 320px 指标面板 + 右侧图形区 | 顶部对齐: 上方 180px 指标行 (6 列网格) + 下方全宽图形区 |
| 指标展示 | 垂直堆叠卡片，需滚动查看 | 水平网格，单行可见 6 个指标卡片 |
| 交互方式 | 侧面板可折叠/展开 | 顶部面板可拖拽调整高度 |

#### 评价指标

| 指标 | 类型 | 测量方式 | 目标 |
|------|------|---------|------|
| **滚动交互次数** | 主指标 | `wheel` 事件计数，每次实验会话总滚动次数 | -50% |
| 定位指标时间 (秒) | 副指标 | "请找到当前图中平均聚类系数" 从任务展示到点击正确值的时间 | -30% |
| 图形可视区域占比 | 副指标 | 图形 canvas 面积 / 总视口面积 | 提升 |
| 用户偏好投票 | 副指标 | 会话结束 A/B 对比投票 | > 60% 偏好 B |
| 信息密度感知 | 探索指标 | 用户主观评分 "信息是否拥挤" 1-5 | 不显著更差 |

#### 样本量与持续时间

**样本量计算 (滚动次数):**
- 预期效应量 (Cohen's d): 0.45 (布局改变通常效应较大)
- alpha: 0.05, power: 0.80
- 所需样本量: **每组 80 人，共 160 人**

**持续时间:** 160 / 50 = 3.2 天 → **5 天** + **7 天 A/A** = **12 天**

#### 统计方法

1. **滚动次数**: 负二项回归 (计数数据，通常过离散)
2. **定位时间**: Mann-Whitney U 检验
3. **用户偏好**: 二项检验 vs 50% null

#### 成功判定标准

- 滚动次数中位数减少 ≥ 45%
- 定位指标时间减少 ≥ 25%
- 用户偏好 B > 55%
- 图形可视区域占比不减少

#### 回滚方案

1. `dashboard_layout_experiment.active = false` → 恢复侧面板布局
2. 布局切换使用 CSS class 切换，无需刷新页面

---

### 1.6 A/B 测试汇总表

| 测试 | 假设效应 | 每组样本 | 总样本 | 估计持续 | 主统计方法 | 风险等级 |
|------|---------|---------|--------|---------|-----------|---------|
| 渲染模式 | FPS +30% | 210 | 420 | 17 天 | Welch t-test + 非劣效 | 高 (核心渲染路径) |
| 搜索 UX | 查找时间 -40% | 100 | 200 | 14 天 | Mann-Whitney U | 中 (API 负载风险) |
| 配色方案 | 识别准确率 +25% | 175 | 350 | 16 天 | Two-proportion z-test | 低 (纯前端) |
| 仪表板布局 | 滚动 -50% | 80 | 160 | 12 天 | 负二项回归 | 低 (纯前端) |

**实验顺序建议:** 配色方案 + 仪表板布局 (低风险，可并行) → 搜索 UX → 渲染模式 (高风险)

**实验间互斥:** 同一用户最多同时参与 2 个实验 (前端控制)，防止交互效应污染结果。

---

## 2. 性能基准测试策略

### 2.1 C++ 引擎基准测试

#### 完整算法矩阵

| 算法 | 时间复杂度 | 数据集规模 | 指标 | 目标 | 工具 |
|------|-----------|-----------|------|------|------|
| PageRank | O((V+E) * iter) | 1K / 10K / 100K edges | 计算耗时、内存峰值 | <500ms @ 100K | benchmark.py |
| Betweenness (精确) | O(V*(V+E)) | 1K / 5K edges | 计算耗时 | <2s @ 1K | benchmark.py |
| Betweenness (采样) | O(K*(V+E)) | 10K / 50K / 100K edges | 耗时、采样精度误差 | <5s @ 10K, 误差 <5% | benchmark.py |
| BFS 最短路径 | O(V+E) | 1K / 10K / 100K nodes | 查询耗时 | <50ms @ 100K | benchmark.py |
| Dijkstra 最优路径 | O((V+E)logV) | 1K / 10K / 100K nodes | 查询耗时 | <100ms @ 100K | benchmark.py |
| DFS 回声室检测 | O(V+E) | 1K / 10K / 100K nodes | 遍历节点数、耗时 | <100ms @ 100K | benchmark.py |
| LPA 社区发现 | O(E * iter) | 1K / 10K / 100K edges | 计算耗时 | <300ms @ 100K | benchmark.py |
| Betweenness Centrality | O(V*(V+E)) | 1K / 10K edges | 计算耗时 (采样) | <5s @ 10K | benchmark.py |
| K-Core 分解 | O(V+E) | 1K / 10K / 100K edges | 计算耗时 | <200ms @ 100K | benchmark.py |
| 聚类系数 | O(V * deg^2) | 1K / 10K / 100K edges | 计算耗时 | <300ms @ 100K | benchmark.py |
| 连通分量 | O(V+E) | 1K / 10K / 100K edges | 计算耗时 | <100ms @ 100K | benchmark.py |
| GraphStats | O(V+E) | 1K / 10K / 100K edges | 计算耗时 | <50ms @ 100K | benchmark.py |
| **全量套件** | — | 88K edges (facebook) | 10 算法总耗时 | <30s | benchmark.py |

#### 基准测试协议

**每次基准测试执行流程:**

```
1. 预热 (Warmup):   执行算法 3 次, 不计入统计
2. 正式测试:        执行算法 10 次, 记录每次耗时和内存峰值
3. 统计汇总:        计算中位数、P95、标准差
4. 环境检查:        记录 CPU 型号、内存大小、OS 版本
5. 写入 MongoDB:    结果存入 benchmarks 集合, 含 git commit hash
```

**数据生成策略:**

| 规模 | 节点数 | 边数 | 生成方法 |
|------|--------|------|---------|
| 1K | ~200 | 1,000 | random graph (Erdos-Renyi, p=0.05) |
| 10K | ~2,000 | 10,000 | random graph (Erdos-Renyi, p=0.003) |
| 50K | ~10,000 | 50,000 | random graph (Erdos-Renyi, p=0.001) |
| 100K | ~20,000 | 100,000 | random graph (Erdos-Renyi, p=0.0005) |
| 真实数据集 | 4,039 | 88,234 | facebook_combined.txt |

**Pass/Fail 标准:**

- 任何算法耗时超过目标值 2 倍 → FAIL
- 任何算法在真实数据集上崩溃 → FAIL
- 内存峰值超过 2GB (100K 边) → WARN
- 全量套件总耗时 > 60s → WARN

---

### 2.2 API 网关基准测试

#### 端点性能目标

| 端点 | 缓存状态 | Target P50 | Target P95 | Target P99 | 并发上限 |
|------|---------|-----------|-----------|-----------|---------|
| `GET /api/v1/graph/pagerank` | 命中 | <10ms | <50ms | <100ms | 50 |
| `GET /api/v1/graph/pagerank` | 未命中 | <200ms | <500ms | <1000ms | 10 |
| `GET /api/v1/graph/community` | 命中 | <10ms | <50ms | <100ms | 50 |
| `GET /api/v1/graph/community` | 未命中 | <150ms | <400ms | <800ms | 10 |
| `GET /api/v1/graph/betweenness` | 未命中 | <2000ms | <5000ms | <8000ms | 5 |
| `GET /api/v1/graph/kcore` | 未命中 | <150ms | <400ms | <800ms | 10 |
| `GET /api/v1/graph/clustering_coeff` | 未命中 | <200ms | <500ms | <1000ms | 10 |
| `GET /api/v1/graph/connected_components` | 未命中 | <80ms | <200ms | <500ms | 10 |
| `GET /api/v1/graph/stats` | 命中 | <5ms | <20ms | <50ms | 100 |
| `GET /api/v1/graph/all` | 命中 | <10ms | <30ms | <80ms | 50 |
| `POST /api/v1/graph/shortest_path` | 不缓存 | <50ms | <200ms | <500ms | 20 |
| `POST /api/v1/graph/ego_network` | 不缓存 | <50ms | <200ms | <500ms | 20 |
| `GET /api/v1/graph/influencers` | 部分缓存 | <20ms | <100ms | <200ms | 50 |
| `GET /api/v1/graph/export/pagerank` | 命中 | <50ms | <200ms | <500ms | 10 |
| `WS /api/v1/ws/analysis` | 不适用 | <100ms (首消息) | — | — | 10 |
| `GET /api/v1/health` | 不缓存 | <5ms | <20ms | <50ms | 200 |

#### 基准测试工具链

| 工具 | 用途 | 配置 |
|------|------|------|
| `wrk` / `wrk2` | HTTP 吞吐量测试 | 固定 QPS 模式 |
| `Locust` | 场景化负载测试 | Python 脚本 (见 `tests/load/locustfile.py`) |
| `hey` | 快速单端点压测 | 并发 + 总请求数 |
| `k6` | CI 集成基准测试 | JSON 输出 → 阈值断言 |
| `mitmproxy` | API 响应时间分布分析 | 捕获 P50/P95/P99 |

#### CI 集成

在 `.github/workflows/main.yml` 中增加 benchmark job:

```yaml
benchmark:
  runs-on: ubuntu-latest
  steps:
    - uses: actions/checkout@v4
    - name: Setup Python
      uses: actions/setup-python@v5
      with:
        python-version: "3.11"
    - name: Build C++ Engine
      run: |
        cd backend_cpp
        cmake -B build -DCMAKE_BUILD_TYPE=Release
        cmake --build build --config Release
    - name: Run Benchmarks
      run: |
        cd middleware_python
        pip install -r requirements.txt
        python benchmark.py
    - name: Assert Performance
      run: |
        # 解析 benchmark 输出, 验证是否达标
        cd middleware_python
        python -c "
        import json
        with open('benchmark_results.json') as f:
            data = json.load(f)
        assert data['pagerank_100k']['time_ms'] < 500, 'PageRank @ 100K too slow'
        assert data['total_suite_time'] < 30, 'Full suite too slow'
        "
```

---

### 2.3 前端性能基准测试

#### Lighthouse 目标

| 指标 | 定义 | 目标 | 测量条件 |
|------|------|------|---------|
| **LCP** (Largest Contentful Paint) | 最大内容绘制时间 | <2.5s | 4G 网络模拟, Moto G4 |
| **FID** (First Input Delay) | 首次输入延迟 | <100ms | 同上 |
| **CLS** (Cumulative Layout Shift) | 累积布局偏移 | <0.1 | 同上 |
| **TTI** (Time to Interactive) | 可交互时间 | <3s | 同上 |
| **TBT** (Total Blocking Time) | 总阻塞时间 | <300ms | 同上 |
| **Speed Index** | 速度指数 | <3s | 同上 |

#### 3D 渲染性能

| 指标 | 测量方法 | 目标 |
|------|---------|------|
| **图加载 FPS** (4K 节点) | Chrome DevTools Performance 录制 | >30 fps (稳定后) |
| **交互帧率** (旋转/缩放) | `requestAnimationFrame` 帧时间 | >45 fps |
| **"Big Bang" 展开帧率** | 逐帧计时，前 100 帧 | >20 fps |
| **JS 堆内存** (4K 节点) | `performance.memory.usedJSHeapSize` | <500 MB |
| **GPU 内存** (4K 节点) | Chrome Task Manager | <1 GB |
| **首次渲染时间** (冷加载) | `performance.timing.domContentLoadedEventEnd` | <5s |

#### 测量协议

1. 使用 Puppeteer 脚本自动化打开页面
2. 加载 facebook_combined 数据集 (4039 节点, 88234 边)
3. 等待 "Big Bang" 展开动画完成
4. 录制 30 秒交互 (随机旋转/缩放/右键)
5. 提取 FPS、内存、帧时间分布
6. 重复 5 次取中位数

#### CI 阈值检查 (Lighthouse)

```javascript
// lighthouserc.js
module.exports = {
  ci: {
    collect: { url: ['http://localhost:8000/static/index.html'] },
    assert: {
      assertions: {
        'categories:performance': ['error', { minScore: 0.85 }],
        'largest-contentful-paint': ['error', { maxNumericValue: 2500 }],
        'first-input-delay': ['error', { maxNumericValue: 100 }],
        'cumulative-layout-shift': ['error', { maxNumericValue: 0.1 }],
        'interactive': ['error', { maxNumericValue: 3000 }],
      },
    },
  },
};
```

---

## 3. 负载测试策略

### 3.1 测试环境

| 维度 | 配置 |
|------|------|
| 应用服务器 | 1 台 (或 Docker Compose 本地) |
| CPU | ≥ 4 核 |
| 内存 | ≥ 8 GB |
| 网络 | 本地回环 (消除网络延迟变量) |
| C++ 引擎 | Release 构建 |
| Redis | 本地实例, maxmemory 256MB, allkeys-lru |
| Neo4j | 本地实例, 预加载 facebook_combined 数据 |
| MySQL | 本地实例 |
| MongoDB | 本地实例 |

### 3.2 负载场景

#### 场景 1: 正常负载 (Normal Load)

| 参数 | 值 |
|------|---|
| 并发用户 | 50 |
| 孵化速率 | 5 用户/秒 |
| 持续时间 | 30 分钟 |
| 操作分布 | 40% 缓存读 (stats), 30% 算法读 (pagerank, community), 20% 拓扑查询, 10% 路径查询 |
| 用户等待时间 | 1-3 秒 (think time) |

#### 场景 2: 峰值负载 (Peak Load / Spike)

| 参数 | 值 |
|------|---|
| 并发用户 | 10 → 200 |
| 爬坡模式 | 60 秒内线性从 10 升至 200 |
| 持续时间 | 10 分钟 (含 2 分钟稳态 + 6 分钟峰值 + 2 分钟下降) |
| 操作分布 | 同正常负载 |
| 用户等待时间 | 0.5-1 秒 |

#### 场景 3: 持续负载 (Sustained Load)

| 参数 | 值 |
|------|---|
| 并发用户 | 100 |
| 孵化速率 | 10 用户/秒 |
| 持续时间 | 2 小时 |
| 操作分布 | 同正常负载 |
| 监控重点 | 内存趋势、连接池泄漏、日志增长 |

#### 场景 4: 缓存故障 (Cache Failure)

| 参数 | 值 |
|------|---|
| 前置条件 | Redis 进程被 kill |
| 并发用户 | 30 |
| 持续时间 | 10 分钟 |
| 操作分布 | 90% 算法读 (all uncached), 10% 拓扑查询 |
| 验证点 | 所有请求回退到 C++ 引擎直接计算，无 5xx 错误 |

#### 场景 5: 数据库故障 (Database Failure)

| 参数 | 值 |
|------|---|
| 前置条件 | Neo4j 进程被 kill |
| 并发用户 | 30 |
| 持续时间 | 10 分钟 |
| 操作分布 | 50% 拓扑查询 (应回退), 50% 算法读 (不受影响) |
| 验证点 | `/api/v1/graph/all` 回退到 C++ 文件读取，其他端点正常 |

#### 场景 6: 混合工作负载 (Mixed Workload)

| 参数 | 值 |
|------|---|
| 并发用户 | 80 |
| 持续时间 | 20 分钟 |
| 操作分布 | 30% 缓存读, 20% 算法读, 10% 路径查询, 10% WebSocket 分析, 10% 导出, 10% Neo4j 查询, 10% 推荐 |

---

### 3.3 监控指标收集

| 指标类别 | 具体指标 | 采集方式 | 目标 |
|---------|---------|---------|------|
| **吞吐量** | RPS (每秒请求数) | Locust 统计模块 | > 500 (正常负载) |
| **延迟** | P50 / P95 / P99 响应时间 | Locust 统计模块 | 见 2.2 节目标表 |
| **错误** | 失败率 (按端点) | Locust 统计模块 | < 1% |
| **CPU** | 应用 + C++ 引擎 CPU% | `psutil` / OS 监控 | < 80% 稳态 |
| **内存** | RSS / 堆内存趋势 | `psutil.Process.memory_info()` | 无连续增长 |
| **Redis** | 命中率 / 连接数 / 内存 | `INFO stats` | 命中率 > 80% |
| **Neo4j** | 查询耗时 / 连接池 | Neo4j Metrics | 无连接超时 |
| **文件描述符** | 打开 fd 数 | `/proc/self/fd` (或 OS 等价) | < 1000 |

---

### 3.4 Pass/Fail 判定矩阵

| 场景 | 条件 | 阈值 | 违反时动作 |
|------|------|------|-----------|
| 正常负载 | 错误率 | < 1% | FAIL — 阻塞上线 |
| 正常负载 | P95 响应时间 | < 目标值 x 1.5 | WARN — 记录技术债务 |
| 峰值负载 | 错误率 | < 2% | FAIL |
| 峰值负载 | P95 响应时间 | < 目标值 x 2.0 | WARN |
| 持续负载 | 内存增长 (2 小时) | < 10% | FAIL (内存泄漏) |
| 持续负载 | 连接泄漏 (fd 增长) | < 5% | FAIL |
| 缓存故障 | 系统可用性 | 100% (无 5xx) | FAIL |
| 缓存故障 | P95 响应时间 | < 目标值 x 5.0 | WARN |
| 数据库故障 | 核心端点可用性 | 核心端点 100% | FAIL |
| 数据库故障 | 拓扑端点可见降级 | 回退到 C++ 模式 | 验证回退逻辑 |
| 所有场景 | 进程崩溃 | 0 次 | FAIL |
| 所有场景 | 未处理异常 | 0 次 | FAIL |

---

### 3.5 负载测试执行清单

- [ ] 确认所有依赖服务 (Redis, Neo4j, MySQL, MongoDB) 运行中
- [ ] 确认 C++ 引擎可执行文件路径正确
- [ ] 确认 facebook_combined.txt 数据文件路径正确
- [ ] 预热缓存 (执行一次所有算法 + 拓扑查询)
- [ ] 设置 Locust 无 Web UI 模式 (`--headless`)
- [ ] 按顺序执行: 场景 1 → 2 → 3 → 4 → 5 → 6
- [ ] 每个场景执行后冷却 2 分钟 (让系统恢复)
- [ ] 场景 4 前手动 kill Redis (`redis-cli shutdown`)
- [ ] 场景 5 前手动 kill Neo4j (`neo4j stop`)
- [ ] 场景 4/5 后重启被 kill 的服务
- [ ] 收集所有 Locust CSV 报告 + HTML 报告
- [ ] 收集系统监控数据 (CPU/内存趋势)
- [ ] 生成负载测试报告

---

## 4. 可靠性测试策略

### 4.1 混沌工程测试 (Chaos Engineering)

#### 测试 1: Redis 进程终止

| 维度 | 详情 |
|------|------|
| **故障注入** | 在系统处理 `/api/v1/graph/pagerank` 请求期间，`kill -9 <redis_pid>` |
| **预期行为** | 当前正在读取缓存的请求应收到空值或超时，随即回退到 C++ 引擎直接计算 |
| **验证点** | 1) 无 5xx 错误; 2) 响应时间在 5s 内恢复正常; 3) Redis 重启后自动重连并恢复缓存写入 |
| **恢复时间目标** | < 5 秒 (连接重试间隔 x 重试次数) |

#### 测试 2: Neo4j 进程终止

| 维度 | 详情 |
|------|------|
| **故障注入** | 在处理 `/api/v1/graph/all` 请求期间，`neo4j stop` |
| **预期行为** | Neo4j 查询失败 → `get_full_topology()` 捕获异常 → 回退到 C++ 引擎 `get_full_graph` 命令 |
| **验证点** | 1) 拓扑数据正常返回 (来自 C++ 引擎); 2) Neo4j 特有端点 (如 `/graph/influencers`) 返回 503; 3) Neo4j 重启后自动恢复 |
| **恢复时间目标** | < 10 秒 |

#### 测试 3: C++ 引擎进程终止

| 维度 | 详情 |
|------|------|
| **故障注入** | 在 `execute_command` 执行中 kill C++ 子进程 |
| **预期行为** | `asyncio.create_subprocess_exec` 引发异常 → `CppEngineError` → API 返回 `{"status": "error"}` → 下次请求正常 fork 新进程 |
| **验证点** | 1) API 返回结构化错误 (非服务器崩溃); 2) 下一次请求正常执行; 3) 无僵尸进程残留 |
| **恢复时间目标** | 立即 (下次请求自动重新 fork) |

#### 测试 4: 网络延迟注入

| 维度 | 详情 |
|------|------|
| **故障注入** | 使用 `tc` (Linux) 或 `WinDivert` (Windows) 在 Redis/Neo4j 连接上注入 500ms 延迟 |
| **预期行为** | 延迟超过设定的超时阈值 → 连接超时 → 触发重试或回退逻辑 |
| **验证点** | 1) 无请求永悬; 2) 超时后的请求在合理时间内返回; 3) 延迟撤销后恢复正常 |
| **恢复时间目标** | 延迟撤销后 < 5 秒 |

#### 测试 5: 磁盘空间耗尽

| 维度 | 详情 |
|------|------|
| **故障注入** | 在日志目录所在盘创建大文件填满磁盘 (或使用 `fallocate`) |
| **预期行为** | 日志写入失败但应用不崩溃, 日志记录降级 (写入 stderr 或丢弃) |
| **验证点** | 1) 应用继续处理请求; 2) 日志模块正确处理 `ENOSPC`; 3) 磁盘释放后日志恢复 |
| **恢复时间目标** | 磁盘释放后 < 10 秒 |

---

### 4.2 故障注入矩阵

| 组件 | 故障模式 | 注入方式 | 预期行为 | 恢复时间 | 严重级别 |
|------|---------|---------|---------|---------|---------|
| **Redis** | 进程 kill | `kill -9` / `redis-cli shutdown` | 缓存全部 miss → 直接计算, 无错误 | < 5s (自动重连) | 中 |
| **Redis** | 连接拒绝 | `iptables -A INPUT -p tcp --dport 6379 -j DROP` | 同上, lazy-connect 返回 None | 即时 | 中 |
| **Redis** | 慢响应 (5s) | `redis-cli DEBUG SLEEP 5` (或代理延迟) | 请求超时后回退计算 | 超时后 < 1s | 中 |
| **Neo4j** | 进程 kill | `neo4j stop` / `kill -9` | 拓扑回退 C++ 文件读, Neo4j 特定端点 503 | < 10s | 高 |
| **Neo4j** | 连接池耗尽 | 模拟 10 并发长查询占满连接池 | 新请求等待/超时/优雅降级 | 长查询结束后立即 | 高 |
| **C++ Engine** | 进程 kill | `kill -9 <cpp_subprocess_pid>` | 错误响应, 下次请求重新 fork | 立即 | 低 |
| **C++ Engine** | 计算超时 | 构造超大数据集使 Betweenness 超时 | `ComputeTimeoutError` → 503 | 超时后立即 | 中 |
| **C++ Engine** | 可执行文件缺失 | `mv graph_engine graph_engine.bak` | `CppEngineError` → 503 | 恢复文件后即时 | 高 |
| **MySQL** | 连接断开 | `kill <mysql_connection_id>` | 连接池自动重连 | < 5s | 低 |
| **MongoDB** | 连接断开 | `kill -9 <mongod_pid>` | fire-and-forget 静默丢弃, 重连后恢复 | 重连后 < 5s | 低 |
| **MongoDB** | 写入超时 | 磁盘 I/O 压力 (fio) | 操作日志丢弃, 不影响请求处理 | 即时 | 低 |
| **磁盘** | 日志目录满 | `fallocate -l 10G dummy.dat` | 日志写入降级, 请求正常处理 | 清理后 < 10s | 高 |

---

### 4.3 浸泡测试 (Soak Testing)

**测试配置:**

| 参数 | 值 |
|------|---|
| 持续时间 | 8 小时 |
| 并发用户 | 50 (中等负载) |
| 流量模式 | 模拟真实日间模式: 6h 正常 + 1h 峰值 (100 用户) + 1h 低谷 (10 用户) |
| 操作混合 | 正常负载分布 |

**监控清单 (每小时采样):**

| 指标 | 预期趋势 | 告警触发 |
|------|---------|---------|
| 内存 (RSS) | 稳定，波动 < 5% | 增长 > 10% |
| Redis 内存 | 稳定 (maxmemory 限制内) | 接近 maxmemory |
| 日志文件大小 | 线性增长，< 500MB/8h | > 1GB/8h |
| 数据库连接数 | 稳定，无泄漏 | 持续增长 |
| 文件描述符 | 稳定 | 持续增长 |
| 响应时间 P95 | 稳定 (无漂移) | 末期 > 初期 x 1.3 |
| 错误率 | < 1% | > 2% |
| GC 停顿 (Python) | < 50ms | > 200ms |

---

### 4.4 恢复测试 (Recovery Testing)

#### 测试 1: 单服务独立重启

| 步骤 | 操作 | 预期 |
|------|------|------|
| 1 | 系统正常运行，持续发送请求 | — |
| 2 | `systemctl restart redis` | Lazy-connect 自动重连，缓存短暂不可用期间回退计算 |
| 3 | 等待 5 秒 | Redis 缓存恢复正常 |
| 4 | `systemctl restart neo4j` | Neo4j 查询回退，重启后自动恢复 |
| 5 | 等待 10 秒 | Neo4j 查询恢复正常 |
| 6 | 验证 | 无请求永久失败 |

#### 测试 2: 全栈重启

| 步骤 | 操作 | 预期 |
|------|------|------|
| 1 | 系统正常运行 | — |
| 2 | `docker-compose down && docker-compose up -d` | 所有服务同时重启 |
| 3 | 启动健康检查轮询 | 所有健康检查端点 200 |
| 4 | 恢复时间目标 | **< 30 秒** |
| 5 | 验证数据一致性 | 缓存预热完成，数据可访问 |

#### 测试 3: 数据库恢复

| 步骤 | 操作 | 预期 |
|------|------|------|
| 1 | 关闭 MySQL | — |
| 2 | 尝试认证请求 | 认证失败 → 返回 503 (而非崩溃) |
| 3 | 启动 MySQL | — |
| 4 | 等待连接池恢复 | Lazy-connect 自动重连 |
| 5 | 验证 | 认证恢复正常，无需应用重启 |

---

### 4.5 优雅降级矩阵

| 依赖可用性组合 | Redis | Neo4j | MySQL | MongoDB | C++ Engine | 系统能力 |
|--------------|-------|-------|-------|---------|-----------|---------|
| 全部正常 | Yes | Yes | Yes | Yes | Yes | 全功能 |
| Redis 不可用 | No | Yes | Yes | Yes | Yes | 全功能 (缓存失效, 延迟增加) |
| Neo4j 不可用 | Yes | No | Yes | Yes | Yes | 核心算法正常, 拓扑/Neo4j 特定端点 503 |
| MySQL 不可用 | Yes | Yes | No | Yes | Yes | 图计算正常, 认证/配置管理不可用 |
| MongoDB 不可用 | Yes | Yes | Yes | No | Yes | 全功能 (日志/指标丢失) |
| C++ Engine 不可用 | Yes | Yes | Yes | Yes | No | **全部算法端点 503**, 仅健康检查 + Neo4j 纯查询可用 |
| Redis + Neo4j 不可用 | No | No | Yes | Yes | Yes | 仅核心算法 (全部来自 C++ 直接计算) |
| 全部数据库不可用 | No | No | No | No | Yes | 仅算法计算可用 (minimal viable) |
| C++ Engine + Neo4j 不可用 | Yes | No | Yes | Yes | No | **仅健康检查可用** (service degraded) |

---

### 4.6 可靠性测试执行 SOP

```
1. 准备阶段
   - 确认测试环境独立 (非生产)
   - 备份所有数据库
   - 启动系统监控 (Prometheus + Grafana 或简单脚本)
   - 确认日志级别设为 DEBUG

2. 执行阶段 (按序)
   a. 正常运行 30 分钟基线采集
   b. 混沌测试 1-5 (每个测试间隔 5 分钟恢复)
   c. 浸泡测试 8 小时
   d. 恢复测试 1-3

3. 验证阶段
   - 收集所有日志
   - 统计错误率、恢复时间
   - 检查是否有内存泄漏 (ps 记录)
   - 检查是否有连接泄漏 (netstat/ss 记录)
   - 检查僵尸进程 (ps aux | grep defunct)

4. 报告阶段
   - 生成可靠性评分 (0-100)
   - 列出所有发现问题
   - 建议改进优先级
```

---

### 4.7 可靠性评分模型

| 维度 | 满分 | 评分依据 |
|------|------|---------|
| 故障恢复率 | 30 | 每有一个故障未自动恢复扣 10 分 |
| 恢复时间达标率 | 25 | 恢复时间超过目标 2 倍的场景数 |
| 零数据丢失 | 15 | 是否有数据因故障丢失 |
| 优雅降级 | 20 | 依赖全部不可用时是否仍可提供最小服务 |
| 监控可见性 | 10 | 故障发生时日志/指标是否提供了足够诊断信息 |

**总分 ≥ 80: 生产就绪 | 60-79: 有条件就绪 | < 60: 不可上线**

---

## 附录 A: 统计公式参考

### A.1 样本量计算 (双样本 t 检验)

```
n = 2 * (Z_{alpha/2} + Z_beta)^2 * (sigma / delta)^2

其中:
  Z_{alpha/2} = 1.96 (alpha=0.05 双尾)
  Z_beta      = 0.84 (power=0.80)
  sigma       = 合并标准差
  delta       = 最小可检测效应
```

### A.2 非劣效检验

```
H0: mu_B - mu_A <= -M  (B 劣于 A)
H1: mu_B - mu_A >  -M  (B 不劣于 A)

M = 非劣效边际
```

### A.3 Cohen's d 效应量

```
d = (mu_B - mu_A) / sigma_pooled

解释:
  d < 0.2: 可忽略
  0.2 <= d < 0.5: 小效应
  0.5 <= d < 0.8: 中效应
  d >= 0.8: 大效应
```

---

## 附录 B: 实验工具清单

| 工具 | 用途 | 安装 |
|------|------|------|
| **Locust** | HTTP/WS 负载测试 | `pip install locust` |
| **wrk2** | 固定速率 HTTP 压测 | `apt install wrk` 或源码编译 |
| **k6** | CI 集成负载测试 | `brew install k6` 或下载二进制 |
| **Lighthouse** | 前端性能审计 | Chrome DevTools 内置, 或 `npm i -g lighthouse` |
| **Puppeteer** | 自动化前端性能采集 | `npm i puppeteer` |
| **scipy** | 统计检验 | `pip install scipy` |
| **statsmodels** | 回归分析 | `pip install statsmodels` |
| **psutil** | 系统资源监控 | `pip install psutil` |
| **tc (traffic control)** | 网络延迟注入 | Linux 内置 |
| **Chaos Mesh / Litmus** | Kubernetes 混沌工程 | Helm install |

---

> **文档维护:** 每次重大架构变更或新算法上线后，需更新对应的性能基准目标和负载测试场景。
>
> **下次审查日期:** 2026-08-02
