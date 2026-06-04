// js/app.js — 应用入口 & 编排器 (重构版)
//
// 职责:
//   - 初始化所有子模块
//   - 协调模块间的通信 (通过 store)
//   - 处理高级用户交互 (加载、路径查找、导出)
//   - 键盘快捷键路由
//
// 导入: 所有子模块
// 导出: AppController (挂载到 window.app)

import { APIService } from './api.js';
import { Engine3D } from './graphEngine.js';
import { ChartDashboard } from './charts.js';
import { store } from './state.js';
import { SearchManager } from './search.js';
import { RankingManager } from './ranking.js';
import { TimelineManager } from './timeline.js';
import { UIManager } from './ui.js';
import { AccessibilityManager } from './accessibility.js';

class AppController {
    constructor() {
        // ---- 核心子系统 ----
        this.engine = new Engine3D('graph');
        this.chartDashboard = new ChartDashboard();

        // ---- 功能模块 ----
        this.search = new SearchManager();
        this.ranking = new RankingManager();
        this.timeline = new TimelineManager();
        this.ui = new UIManager();
        this.a11y = new AccessibilityManager();

        // ---- 雷达面板 ----
        this._createRadarPanel();

        // ---- 连接引擎回调 ----
        this.engine.onNodeFocus = (focusId) => this._updateRadarPanel(focusId);

        // ---- 连接搜索回调 ----
        this.search.onSelectNode = (nodeId) => this._onSearchSelectNode(nodeId);

        // ---- 连接排行回调 ----
        this.ranking.onSelectItem = (nodeId) => this._onRankingSelectNode(nodeId);

        // ---- 连接时间轴引擎 ----
        this.timeline.setEngine(this.engine);

        // ---- 初始化所有模块 ----
        this._initAll();

        // ---- 键盘快捷键 ----
        this._initKeyboardShortcuts();

        // ---- 暴露到 window (兼容雷达面板 onclick) ----
        window.app = this;
    }

    // ============================================================
    // 初始化
    // ============================================================

    _initAll() {
        this.a11y.init();
        this.search.init();
        this.ranking.init();
        this.timeline.init();
        this._bindEvents();

        // 订阅状态变化 (调试 & 无障碍通知)
        store.on('graphLoaded', (loaded) => {
            if (loaded) {
                this.a11y.notifyGraphLoaded();
            }
        });
    }

    _createRadarPanel() {
        // 雷达面板在 HTML 中已定义, 这里确保 DOM 存在
        if (!document.getElementById('radar-panel')) {
            const panel = document.createElement('div');
            panel.id = 'radar-panel';
            panel.setAttribute('aria-label', '人脉雷达探测面板');
            document.body.appendChild(panel);
        }
    }

    // ============================================================
    // 事件绑定
    // ============================================================

    _bindEvents() {
        // 加载数据
        document.getElementById('btn-load').addEventListener('click', () => this.handleLoadFullSystem());

        // 路径查找
        document.getElementById('btn-path-bfs').addEventListener('click', () => this.handleShortestPath('bfs'));
        document.getElementById('btn-path-dijkstra').addEventListener('click', () => this.handleShortestPath('dijkstra'));
        document.getElementById('btn-dfs').addEventListener('click', () => {
            const start = document.getElementById('s').value.trim();
            if (!start) return this.ui.toast('请先点击锁定一个探测起点!', 'warning');
            this.handleShortestPath('dfs');
        });

        // 仪表板
        document.getElementById('btn-dashboard').addEventListener('click', () => this.toggleDashboard());
        document.getElementById('btn-close-dash').addEventListener('click', () => this.chartDashboard.hide());

        // 重置
        document.getElementById('btn-reset').addEventListener('click', () => this.resetAll());

        // 连线切换
        document.getElementById('btn-toggle-links').addEventListener('click', (e) => {
            const isShowing = this.engine.toggleLinks();
            const btn = e.target;
            btn.innerHTML = isShowing ? '显示全网连线' : '隐藏全网连线';
            btn.className = isShowing ? '' : 'btn-danger';
            btn.setAttribute('aria-label', isShowing ? '显示全网连线' : '隐藏全网连线');
            if (isShowing) {
                this.ui.toast('已开启全网连线，请注意设备性能负荷', 'warning');
            }
        });

        // 力场滑块
        document.getElementById('ctrl-repel').addEventListener('input', () => this._handleForceChange());
        document.getElementById('ctrl-link').addEventListener('input', () => this._handleForceChange());

        // 导出
        document.getElementById('btn-export-json').addEventListener('click', () => this.handleExport('json'));
        document.getElementById('btn-export-csv').addEventListener('click', () => this.handleExport('csv'));

        // 3D 画布交互
        this._injectCanvasInteractions();

        // 阻止默认右键菜单
        document.getElementById('graph').addEventListener('contextmenu', e => e.preventDefault());
    }

    _injectCanvasInteractions() {
        this.engine.graph.onNodeClick(node => {
            this._onCanvasNodeClick(node);
        });

        this.engine.graph.onBackgroundClick(() => {
            document.getElementById('s').value = '';
            document.getElementById('t').value = '';
            document.getElementById('path-hud').style.display = 'none';
            this.engine.reset();
        });
    }

    // ============================================================
    // 键盘快捷键 (WCAG: 不影响输入框)
    // ============================================================

    _initKeyboardShortcuts() {
        document.addEventListener('keydown', (e) => {
            // 输入框中不触发快捷键 (除了 Escape)
            const tag = e.target.tagName;
            if ((tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') && e.key !== 'Escape') {
                return;
            }

            switch (e.key) {
                case 'h':
                case 'H':
                    this.ui.showShortcuts();
                    break;
                case 'r':
                case 'R':
                    this.resetAll();
                    break;
                case 'l':
                case 'L':
                    this.handleLoadFullSystem();
                    break;
                case 'f':
                case 'F':
                    this.search.focus();
                    break;
                case 's':
                case 'S':
                    this.toggleDashboard();
                    break;
                case ' ':
                    e.preventDefault();
                    this.timeline.togglePlayback();
                    break;
                case 'Escape':
                    this._handleEscape();
                    break;
                default:
                    break;
            }
        });
    }

    _handleEscape() {
        // 关闭仪表板
        if (this.chartDashboard.visible) {
            this.chartDashboard.hide();
            return;
        }
        // 关闭模态框
        this.ui.closeModal();
        // 重置
        this.resetAll();
    }

    // ============================================================
    // 节点交互
    // ============================================================

    _onCanvasNodeClick(node) {
        this._handleNodeSelection(node.id);

        // 飞行到节点
        if (node.x !== undefined) {
            try {
                const dist = Math.hypot(node.x, node.y, node.z);
                const distRatio = 1 + 150 / Math.max(dist, 1);
                this.engine.graph.cameraPosition(
                    { x: node.x * distRatio, y: node.y * distRatio, z: node.z * distRatio },
                    node,
                    1500
                );
            } catch (err) { /* ignore */ }
        }
    }

    _onSearchSelectNode(nodeId) {
        this._handleNodeSelection(nodeId);
        this._flyToNode(nodeId);
    }

    _onRankingSelectNode(nodeId) {
        this._handleNodeSelection(nodeId);
        this._flyToNode(nodeId);
    }

    _handleNodeSelection(nodeId) {
        const sInput = document.getElementById('s');
        const tInput = document.getElementById('t');

        if (!sInput.value) {
            sInput.value = nodeId;
            this.ui.toast(`已锁定起点: ID ${nodeId}`);
        } else if (!tInput.value && sInput.value !== String(nodeId)) {
            tInput.value = nodeId;
            this.ui.toast(`已锁定终点: ID ${nodeId}`);
        } else {
            sInput.value = nodeId;
            tInput.value = '';
            this.ui.toast(`已重置起点: ID ${nodeId}`);
        }
        this.engine.setSelectedNodes(sInput.value, tInput.value);
    }

    _flyToNode(nodeId) {
        const graphData = store.get('globalGraphData');
        if (!graphData) return;

        const targetNode = graphData.nodes.find(
            n => n.id === nodeId || n.id === String(nodeId)
        );

        if (targetNode && targetNode.x !== undefined) {
            const dist = Math.hypot(targetNode.x, targetNode.y, targetNode.z);
            const safeDist = dist === 0 ? 1 : dist;
            const distRatio = 1 + 150 / safeDist;
            this.engine.graph.cameraPosition(
                {
                    x: targetNode.x * distRatio,
                    y: targetNode.y * distRatio,
                    z: targetNode.z * distRatio
                },
                targetNode,
                1000
            );
            this.ui.toast(`视角飞抵: ID ${nodeId}`);
            this.a11y.announce(`已飞抵节点 ${nodeId}`);
        }
    }

    /** 公开方法: 飞行到节点 (供雷达面板 onclick 调用) */
    flyToNode(nodeId) {
        this._flyToNode(nodeId);
    }

    /** 公开方法: 触发节点聚焦 */
    triggerNodeFocus(nodeId) {
        const graphData = store.get('globalGraphData');
        if (!graphData) return;

        const targetNode = graphData.nodes.find(
            n => n.id === nodeId || n.id === String(nodeId)
        );

        if (targetNode) {
            this.engine.focusNode = nodeId;
            this.engine.refreshFilters();
            this._updateRadarPanel(nodeId);
            this._flyToNode(nodeId);
            store.set('focusNode', nodeId);
        }
    }

    // ============================================================
    // 雷达面板
    // ============================================================

    _updateRadarPanel(focusId) {
        const panel = document.getElementById('radar-panel');
        if (!panel) return;

        if (!focusId) {
            panel.classList.remove('active');
            panel.setAttribute('aria-hidden', 'true');
            return;
        }

        const neighborsSet = this.engine.neighbors.get(focusId);
        const graphData = store.get('globalGraphData');
        if (!neighborsSet || !graphData) return;

        const neighbors = graphData.nodes
            .filter(n => neighborsSet.has(n.id))
            .sort((a, b) => (b.prScore || 0) - (a.prScore || 0));

        const count = neighbors.length;
        store.set('neighbors', neighbors.map(n => n.id));

        let html = `
            <div class="radar-header">
                <button onclick="window.app._closeRadarPanel()" style="float:right;background:none;border:none;color:#888;font-size:18px;cursor:pointer;padding:0 4px;" title="关闭面板" aria-label="关闭目标探针面板">✕</button>
                <h3>目标探针: ID ${focusId}</h3>
                <p>扫描到 <b style="color:#ffd700;font-size:16px;">${count}</b> 个直接人脉</p>
            </div>
            <div class="radar-list">`;

        const esc = (s) => this.ui._escapeHtml(String(s));
        const validColor = (c) => /^#[0-9a-fA-F]{3,8}$|^[a-z]+$/.test(c) ? c : '#fff';

        neighbors.forEach(n => {
            const score = n.prScore ? (n.prScore * 100).toFixed(2) : '0.00';
            const bc = n.betweennessScore ? n.betweennessScore.toFixed(4) : '-';
            const kc = n.kcore !== undefined ? Math.round(n.kcore) : '-';
            const cc = n.clusteringCoeff !== undefined ? n.clusteringCoeff.toFixed(3) : '-';
            const safeId = esc(n.id);
            const safeColor = validColor(n.color);
            const safeCommunity = esc(n.community || '未知');
            html += `
            <div class="radar-card">
                <div class="card-header" onclick="window.app.flyToNode('${safeId}')"
                     role="button" tabindex="0"
                     aria-label="查看节点 ${safeId}, PR 得分 ${score}"
                     onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();window.app.flyToNode('${safeId}')}">
                    <div class="item-left">
                        <span class="color-dot" style="background:${safeColor};box-shadow:0 0 8px ${safeColor}" aria-hidden="true"></span>
                        <span class="n-id">ID: ${safeId}</span>
                    </div>
                    <span class="n-score">PR: ${score}</span>
                </div>
                <div class="card-body">
                    <div class="stat-row"><span>阵营</span> <span style="color:${safeColor};font-weight:bold;">${safeCommunity}</span></div>
                    <div class="stat-row"><span>人脉</span> <span style="color:#00ccff;font-weight:bold;">${n.degree || 0} 人</span></div>
                    <div class="stat-row"><span>中介</span> <span style="color:#ffaa00;">${bc}</span></div>
                    <div class="stat-row"><span>核心</span> <span style="color:#aa00ff;">${kc}</span></div>
                    <div class="stat-row"><span>聚类</span> <span style="color:#00ffff;">${cc}</span></div>
                </div>
                <div class="card-actions">
                    <button class="btn-mini" onclick="window.app._handleNodeSelection('${safeId}')"
                            aria-label="锁定节点 ${safeId} 为路由目标">锁定路由</button>
                    <button class="btn-mini btn-focus" onclick="window.app.triggerNodeFocus('${safeId}')"
                            aria-label="深度探测节点 ${safeId} 的人脉圈">深度探测</button>
                </div>
            </div>`;
        });
        html += `</div>`;

        panel.innerHTML = html;
        panel.classList.add('active');
        panel.setAttribute('aria-hidden', 'false');

        this.a11y.announce(`已聚焦节点 ${focusId}，扫描到 ${count} 个人脉`);
    }

    // ============================================================
    // 力场控制
    // ============================================================

    _handleForceChange() {
        const repel = document.getElementById('ctrl-repel').value;
        const link = document.getElementById('ctrl-link').value;
        document.getElementById('val-repel').innerText = repel;
        document.getElementById('val-link').innerText = link;
        store.set('forceRepel', Number(repel));
        store.set('forceLink', Number(link));
        this.engine.updateForces(repel, link);
    }

    // ============================================================
    // 加载流程
    // ============================================================

    async handleLoadFullSystem() {
        const steps = [
            ['拓扑数据',     () => APIService.getFullGraph()],
            ['PageRank',     () => APIService.getPageRank()],
            ['LPA 社区',     () => APIService.getCommunity()],
            ['Betweenness',  () => APIService.getBetweenness()],
            ['K-Core',       () => APIService.getKCore()],
            ['聚类系数',     () => APIService.getClusteringCoeff()],
            ['图统计',       () => APIService.getGraphStats()],
            ['连通分量',     () => APIService.getConnectedComponents()],
        ];

        let algorithmResults = {};
        let algorithmTiming = {};

        for (let i = 0; i < steps.length; i++) {
            const [name, fn] = steps[i];
            this.ui.showLoading(name, `${i + 1}/${steps.length} ${name}...`);

            try {
                const data = await fn();
                if (data && data.status === 'success') {
                    // 将算法结果映射到内部 key
                    const keyMap = {
                        '拓扑数据':  'topology',
                        'PageRank':  'pagerank',
                        'LPA 社区':  'community',
                        'Betweenness': 'betweenness',
                        'K-Core':    'kcore',
                        '聚类系数':  'clustering_coeff',
                        '图统计':    'stats',
                        '连通分量':  'connected_components',
                    };
                    algorithmResults[keyMap[name] || name.toLowerCase()] = data;
                    if (data.time_ms) {
                        algorithmTiming[name] = data.time_ms;
                    }
                }
            } catch (e) {
                console.warn(`[App] ${name} 加载失败:`, e.message);
                this.a11y.announce(`${name} 加载失败`, 'polite');
            }
        }

        // 检查拓扑数据
        const topoData = algorithmResults.topology;
        if (!topoData || topoData.status !== 'success') {
            this.ui.showLoading('加载失败: 拓扑数据不可用', '');
            setTimeout(() => this.ui.hideLoading(), 3000);
            this.a11y.announce('拓扑数据加载失败', 'assertive');
            return;
        }

        // 构建辅助 maps
        const prMap = {};
        if (algorithmResults.pagerank?.data) {
            algorithmResults.pagerank.data.forEach(item => { prMap[item.node] = item.score; });
        }

        const commMap = {};
        if (algorithmResults.community?.data) {
            algorithmResults.community.data.forEach(item => { commMap[item.node] = item.community; });
        }

        const bcMap = {};
        if (algorithmResults.betweenness?.data) {
            algorithmResults.betweenness.data.forEach(item => { bcMap[item.node] = item.score; });
        }

        const kcMap = {};
        if (algorithmResults.kcore?.data) {
            algorithmResults.kcore.data.forEach(item => { kcMap[item.node] = item.coreness; });
        }

        const ccMap = {};
        if (algorithmResults.clustering_coeff?.data) {
            algorithmResults.clustering_coeff.data.forEach(item => { ccMap[item.node] = item.coefficient; });
        }

        // 计算度数
        const degreeMap = {};
        topoData.links.forEach(link => {
            const src = link.source.id || link.source;
            const tgt = link.target.id || link.target;
            degreeMap[src] = (degreeMap[src] || 0) + 1;
            degreeMap[tgt] = (degreeMap[tgt] || 0) + 1;
        });

        // 着色方案 (社区→颜色)
        const PALETTE = ['#ff0055','#00ff88','#0088ff','#ffaa00','#aa00ff','#00ffff','#ffff00',
                          '#ff5500','#55ff00','#ff00aa','#ffcc00','#00ffcc'];
        const communityColors = {};
        for (const nid of Object.keys(commMap)) {
            const cid = commMap[nid];
            if (!communityColors[cid]) communityColors[cid] = PALETTE[Object.keys(communityColors).length % PALETTE.length];
        }

        // 富化节点: 将算法结果注入到每个节点对象上
        const enrichedNodes = topoData.nodes.map(n => ({
            ...n,
            prScore: prMap[n.id],
            betweennessScore: bcMap[n.id],
            kcore: kcMap[n.id],
            clusteringCoeff: ccMap[n.id],
            community: commMap[n.id] || '未知',
            degree: degreeMap[n.id] || 0,
            color: communityColors[commMap[n.id]] || '#ffffff',
        }));
        const enrichedTopoData = { ...topoData, nodes: enrichedNodes };

        // 更新 store
        store.batch({
            globalGraphData: enrichedTopoData,
            graphLoaded: true,
            algorithmResults: algorithmResults,
            algorithmTiming: algorithmTiming,
        });

        // 注入引擎并渲染
        this.ui.showLoading('注入 3D 引擎...', '渲染中...');
        setTimeout(() => {
            if (this.engine._disposed) return;

            this.engine.prepareBigBang(enrichedTopoData, prMap, commMap, degreeMap, bcMap, kcMap, ccMap);

            // 刷新排行榜 & 图例
            this.ranking.refresh();
            this._updateLegend(commMap);

            document.getElementById('legend-panel').style.display = 'block';
            store.set('timelineVisible', true);

            this.ui.hideLoading();
            this.engine.renderToTimeStep(1);

            const msg = `数据装载完毕! ${topoData.nodes.length} 节点, ${topoData.links.length} 条边`;
            this.ui.toast(msg, 'success');
            this.a11y.announce(msg);
        }, 300);
    }

    // ============================================================
    // 图例
    // ============================================================

    _updateLegend(commMap) {
        const colorCount = {};
        const graphData = store.get('globalGraphData');

        for (const [node, comm] of Object.entries(commMap)) {
            const targetNode = graphData?.nodes.find(n => n.id === node);
            const color = targetNode?.color || '#fff';
            if (!colorCount[color]) {
                colorCount[color] = { comm, count: 0 };
            }
            colorCount[color].count++;
        }

        const legendList = document.getElementById('legend-list');
        if (!legendList) return;

        legendList.innerHTML = Object.entries(colorCount)
            .map(([color, info]) => {
                const safeColor = /^#[0-9a-fA-F]{3,8}$|^[a-z]+$/.test(color) ? color : '#fff';
                const safeLabel = this.ui._escapeHtml(`${info.comm} (${info.count})`);
                return `
                <div class="legend-item">
                    <span class="legend-dot" style="background:${safeColor};box-shadow:0 0 6px ${safeColor};" aria-hidden="true"></span>
                    <span class="legend-label">${safeLabel}</span>
                </div>`;
            })
            .join('');
    }

    // ============================================================
    // 仪表板
    // ============================================================

    toggleDashboard() {
        if (this.chartDashboard.visible) {
            this.chartDashboard.hide();
            this.ui.toast('数据洞察面板已关闭');
        } else {
            const graphData = store.get('globalGraphData');
            if (!graphData) {
                this.ui.toast('请先载入核心数据集', 'warning');
                return;
            }
            this.chartDashboard.init(document.getElementById('stats-dashboard'));
            this._populateCharts();
            this.chartDashboard.show();
            this.ui.toast('数据洞察面板已打开');
        }
    }

    _populateCharts() {
        const graphData = store.get('globalGraphData');
        const algorithmResults = store.get('algorithmResults');
        const algorithmTiming = store.get('algorithmTiming');

        if (!graphData) return;

        // 度数分布
        try {
            const degreeMap = {};
            graphData.nodes.forEach(n => { degreeMap[n.id] = n.degree || 0; });
            this.chartDashboard.updateDegreeDistribution(degreeMap);
        } catch (e) { console.warn('[Charts] 度数更新失败', e); }

        // 社区分布
        try {
            const commMap = {};
            graphData.nodes.forEach(n => { commMap[n.id] = n.community || '未知'; });
            this.chartDashboard.updateCommunityDistribution(commMap);
        } catch (e) { console.warn('[Charts] 社区更新失败', e); }

        // PageRank
        try {
            if (Array.isArray(algorithmResults.pagerank?.data)) {
                this.chartDashboard.updatePageRankBars(algorithmResults.pagerank.data);
            }
        } catch (e) { console.warn('[Charts] PR更新失败', e); }

        // 算法性能
        try {
            if (algorithmTiming && Object.keys(algorithmTiming).length > 0) {
                this.chartDashboard.updateTimingComparison(algorithmTiming);
            }
        } catch (e) { console.warn('[Charts] 耗时更新失败', e); }

        // 全局统计
        try {
            if (algorithmResults.stats) {
                const s = algorithmResults.stats;
                const el = document.getElementById('global-stats');
                if (el) {
                    el.innerHTML = [
                        `节点: <b style="color:#00ff88">${s.nodes || 0}</b>`,
                        `边: <b style="color:#00ff88">${s.edges || 0}</b>`,
                        `密度: <b style="color:#0088ff">${(s.density || 0).toFixed(6)}</b>`,
                        `平均度: <b style="color:#ffaa00">${(s.avg_degree || 0).toFixed(1)}</b>`,
                        `最大度: <b style="color:#ff0055">${s.max_degree || 0}</b>`,
                        `直径: <b style="color:#aa00ff">${s.diameter_approx || 0}</b>`,
                        `分量: <b style="color:#00ffff">${s.components || 0}</b>`,
                    ].join(' | ');
                }
            }
        } catch (e) { console.warn('[Charts] 全局统计更新失败', e); }
    }

    // ============================================================
    // 路径查找
    // ============================================================

    async handleShortestPath(algorithm) {
        const start = document.getElementById('s').value.trim();
        const target = document.getElementById('t').value.trim();

        if (!start || !target) {
            return this.ui.toast('请先在星空中点击选择起点和终点!', 'warning');
        }

        const btnId = algorithm === 'dijkstra' ? 'btn-path-dijkstra' : 'btn-path-bfs';
        const btn = document.getElementById(btnId);
        const originalText = btn.innerText;
        btn.innerHTML = '算力全开中...';
        btn.disabled = true;

        try {
            const data = await APIService.getShortestPath(start, target, algorithm);
            if (data.status === 'success') {
                this.engine.renderPath(data.path);
                this._showHUD(data.path);

                const typeName = algorithm === 'dijkstra' ? '高亲密链路' :
                                algorithm === 'dfs' ? '回声室闭环' : '最少中转链路';
                this.ui.toast(`${typeName} 提取成功! 途径 ${data.path.length - 1} 跳`);
                this.a11y.notifyPathFound(data.path.length - 1);
            } else {
                this.ui.toast(`追踪失败: ${data.message || '两人处于信息孤岛'}`, 'error');
                this.engine.reset();
            }
        } catch (err) {
            this.ui.toast('底层 C++ 引擎通信异常', 'error');
            this.a11y.announce('路径查询失败', 'assertive');
        } finally {
            btn.innerText = originalText;
            btn.disabled = false;
        }
    }

    _showHUD(pathArr) {
        const hud = document.getElementById('path-hud');
        if (!pathArr || pathArr.length === 0) {
            hud.style.display = 'none';
            return;
        }

        hud.style.display = 'flex';
        let html = `<span class="hud-title">链路提取完成</span>`;
        pathArr.forEach((p, i) => {
            html += `<span class="node-badge">ID: ${this.ui._escapeHtml(String(p))}</span>`;
            if (i < pathArr.length - 1) html += `<span aria-hidden="true">➔</span>`;
        });
        hud.innerHTML = html;
    }

    // ============================================================
    // 导出
    // ============================================================

    async handleExport(format) {
        const dataType = document.getElementById('export-datatype').value;
        try {
            await APIService.exportData(dataType, format);
            this.ui.toast(`${dataType}.${format} 导出成功!`);
            this.a11y.announce(`${dataType} 数据导出完成`);
        } catch (e) {
            this.ui.toast(`导出失败: ${e.message}`, 'error');
        }
    }

    // ============================================================
    _closeRadarPanel() {
        const radar = document.getElementById('radar-panel');
        if (radar) {
            radar.classList.remove('active');
            radar.setAttribute('aria-hidden', 'true');
        }
        if (this.engine?.graph) {
            this.engine.graph.nodeColor(n => n.color || '#ffffff');
        }
    }

    // 重置
    // ============================================================

    resetAll() {
        document.getElementById('s').value = '';
        document.getElementById('t').value = '';
        document.getElementById('path-hud').style.display = 'none';

        this.engine.reset();
        this.timeline.reset();

        // 关闭面板
        const radar = document.getElementById('radar-panel');
        if (radar) radar.classList.remove('active');

        store.batch({
            selectedNode: null,
            startNode: null,
            targetNode: null,
            focusNode: null,
            neighbors: [],
            isPlaying: false,
        });

        this.ui.toast('系统视角与状态已重置');
        this.a11y.announce('视角已重置');
    }

    /** 公开: 供雷达面板使用 */
    handleNodeSelection(nodeId) {
        this._handleNodeSelection(nodeId);
    }

    /** 公开: 重置 (兼容旧接口) */
    reset() { this.resetAll(); }
}


// ============================================================
// 应用启动
// ============================================================

document.addEventListener('DOMContentLoaded', () => {
    if (window.app) {
        console.warn('[App] app 已存在, 跳过重复初始化');
        return;
    }

    try {
        const app = new AppController();
        window.app = app;

        // 初始加载屏幕
        app.ui.showLoading('系统休眠中...', '');

        // 健康检查 (后台)
        APIService.checkHealth()
            .then(data => {
                if (data && data.status === 'ok') {
                    console.log('[App] 后端健康检查通过');
                }
            })
            .catch(() => {
                console.warn('[App] 后端不可达, 将使用离线模式');
            });
    } catch(e) {
        console.error('[App] 初始化失败:', e);
        const el = document.getElementById('loading-text');
        if (el) el.innerHTML = '<span style="color:#ff4444;">❌ 初始化失败: ' + e.message + '</span><br><span style="color:#888;font-size:14px;">请查看 F12 Console</span>';
        throw e;
    }
});
