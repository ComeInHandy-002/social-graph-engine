// js/app.js
import { APIService } from './api.js';
import { Engine3D } from './graphEngine.js';
import { ChartDashboard } from './charts.js';

class AppController {
    constructor() {
        this.engine = new Engine3D('graph');
        this.globalGraphData = null;
        this.algorithmResults = {};
        this.algorithmTiming = {};
        this.playInterval = null;
        this.isPlaying = false;
        this.chartDashboard = new ChartDashboard();
        this.rankingMetric = 'pagerank';

        this.createRadarPanel();
        this.engine.onNodeFocus = (focusId) => this.updateRadarPanel(focusId);
        this.bindEvents();
        this.injectClickInteractions();
        this.initSearch();
        this.initKeyboardShortcuts();
    }

    // ========== 通知系统 ==========
    toast(message, type = 'success') {
        const container = document.getElementById('toast-container');
        if (!container) return console.warn(message);
        const toast = document.createElement('div');
        toast.className = `cyber-toast ${type}`;
        const icon = type === 'success' ? '✅' : type === 'warning' ? '⚠️' : '🚨';
        toast.innerHTML = `<span>${icon}</span> <span>${message}</span>`;
        container.appendChild(toast);
        setTimeout(() => {
            toast.style.animation = 'fadeOutUp 0.3s forwards';
            setTimeout(() => toast.remove(), 300);
        }, 3000);
    }

    // ========== 雷达面板 ==========
    createRadarPanel() {
        const panel = document.createElement('div');
        panel.id = 'radar-panel';
        panel.className = 'cyber-radar-panel';
        document.body.appendChild(panel);
    }

    updateRadarPanel(focusId) {
        const panel = document.getElementById('radar-panel');
        if (!focusId) { panel.classList.remove('active'); return; }

        const neighborsSet = this.engine.neighbors.get(focusId);
        if (!neighborsSet || !this.globalGraphData) return;

        const neighbors = this.globalGraphData.nodes.filter(n => neighborsSet.has(n.id));
        neighbors.sort((a, b) => (b.prScore || 0) - (a.prScore || 0));

        let html = `
            <div class="radar-header">
                <h3>📡 目标探针: ID ${focusId}</h3>
                <p>扫描到 <b style="color:#ffd700; font-size:16px;">${neighbors.length}</b> 个直接关联人脉</p>
            </div>
            <div class="radar-list">`;

        neighbors.forEach(n => {
            const score = n.prScore ? (n.prScore * 100).toFixed(2) : '0.00';
            const bc = n.betweennessScore ? n.betweennessScore.toFixed(4) : '-';
            const kc = n.kcore !== undefined ? Math.round(n.kcore) : '-';
            const cc = n.clusteringCoeff !== undefined ? n.clusteringCoeff.toFixed(3) : '-';
            html += `
            <div class="radar-card">
                <div class="card-header" onclick="window.app.flyToNode('${n.id}')" title="点击视角飞抵该星系">
                    <div class="item-left">
                        <span class="color-dot" style="background:${n.color || '#fff'}; box-shadow: 0 0 8px ${n.color || '#fff'}"></span>
                        <span class="n-id">ID: ${n.id}</span>
                    </div>
                    <span class="n-score">PR: ${score}</span>
                </div>
                <div class="card-body">
                    <div class="stat-row"><span>所属阵营:</span> <span style="color:${n.color || '#fff'}; font-weight:bold;">${n.community || '未知'}</span></div>
                    <div class="stat-row"><span>直系人脉:</span> <span style="color:#00ccff; font-weight:bold;">${n.degree || 0} 人</span></div>
                    <div class="stat-row"><span>中介中心性:</span> <span style="color:#ffaa00;">${bc}</span></div>
                    <div class="stat-row"><span>K-Core:</span> <span style="color:#aa00ff;">${kc}</span></div>
                    <div class="stat-row"><span>聚类系数:</span> <span style="color:#00ffff;">${cc}</span></div>
                </div>
                <div class="card-actions">
                    <button class="btn-mini" onclick="window.app.handleNodeSelection('${n.id}')">🎯 锁定路由</button>
                    <button class="btn-mini btn-focus" onclick="window.app.triggerNodeFocus('${n.id}')">👁️ 深度探测</button>
                </div>
            </div>`;
        });
        html += `</div>`;
        panel.innerHTML = html;
        panel.classList.add('active');
    }

    // ========== 搜索系统 ==========
    initSearch() {
        const searchInput = document.getElementById('global-search');
        const resultsDiv = document.getElementById('search-results');
        let selectedIdx = -1;

        searchInput.addEventListener('input', () => {
            const query = searchInput.value.trim().toLowerCase();
            if (!query || !this.globalGraphData) {
                resultsDiv.style.display = 'none';
                return;
            }
            const matches = this.globalGraphData.nodes
                .filter(n => n.id.toLowerCase().includes(query))
                .slice(0, 20);
            if (matches.length === 0) {
                resultsDiv.style.display = 'none';
                return;
            }
            resultsDiv.innerHTML = matches.map((n, i) =>
                `<div class="search-result-item ${i === 0 ? 'active' : ''}" data-id="${n.id}">
                    <span class="sr-id">ID: ${n.id}</span>
                    <span class="sr-info">社群:${n.community || '-'} | 度:${n.degree || 0} | PR:${n.prScore ? (n.prScore * 100).toFixed(1) : 0}%</span>
                </div>`
            ).join('');
            resultsDiv.style.display = 'block';
            selectedIdx = 0;
        });

        searchInput.addEventListener('keydown', (e) => {
            const items = resultsDiv.querySelectorAll('.search-result-item');
            if (e.key === 'ArrowDown') {
                e.preventDefault();
                selectedIdx = Math.min(selectedIdx + 1, items.length - 1);
                items.forEach((el, i) => el.classList.toggle('active', i === selectedIdx));
            } else if (e.key === 'ArrowUp') {
                e.preventDefault();
                selectedIdx = Math.max(selectedIdx - 1, 0);
                items.forEach((el, i) => el.classList.toggle('active', i === selectedIdx));
            } else if (e.key === 'Enter' && items[selectedIdx]) {
                const id = items[selectedIdx].dataset.id;
                this.handleNodeSelection(id);
                this.flyToNode(id);
                resultsDiv.style.display = 'none';
                searchInput.value = '';
            } else if (e.key === 'Escape') {
                resultsDiv.style.display = 'none';
                searchInput.value = '';
            }
        });

        resultsDiv.addEventListener('click', (e) => {
            const item = e.target.closest('.search-result-item');
            if (item) {
                const id = item.dataset.id;
                this.handleNodeSelection(id);
                this.flyToNode(id);
                resultsDiv.style.display = 'none';
                searchInput.value = '';
            }
        });

        document.addEventListener('click', (e) => {
            if (!searchInput.contains(e.target) && !resultsDiv.contains(e.target)) {
                resultsDiv.style.display = 'none';
            }
        });
    }

    // ========== 键盘快捷键 ==========
    initKeyboardShortcuts() {
        document.addEventListener('keydown', (e) => {
            if (e.target.tagName === 'INPUT' || e.target.tagName === 'SELECT') return;
            switch (e.key.toLowerCase()) {
                case 'h':
                    this.showShortcutsModal();
                    break;
                case 'r':
                    this.resetAll();
                    break;
                case 'l':
                    this.handleLoadFullSystem();
                    break;
                case 'f':
                    document.getElementById('global-search').focus();
                    break;
                case 's':
                    this.toggleDashboard();
                    break;
                case ' ':
                    e.preventDefault();
                    this.togglePlayback();
                    break;
                case 'shift':
                    break;
            }
        });
    }

    showShortcutsModal() {
        const existing = document.getElementById('shortcuts-modal');
        if (existing) { existing.remove(); return; }
        const modal = document.createElement('div');
        modal.id = 'shortcuts-modal';
        modal.innerHTML = `
            <div class="shortcuts-overlay">
                <div class="shortcuts-card">
                    <h3>⌨️ 键盘快捷键</h3>
                    <table>
                        <tr><td><kbd>H</kbd></td><td>显示 / 隐藏此面板</td></tr>
                        <tr><td><kbd>R</kbd></td><td>重置视角与状态</td></tr>
                        <tr><td><kbd>L</kbd></td><td>载入核心数据集</td></tr>
                        <tr><td><kbd>F</kbd></td><td>聚焦搜索栏</td></tr>
                        <tr><td><kbd>S</kbd></td><td>切换数据洞察面板</td></tr>
                        <tr><td><kbd>Space</kbd></td><td>播放 / 暂停时间轴</td></tr>
                    </table>
                    <button id="btn-close-shortcuts" style="margin-top:12px;">关闭</button>
                </div>
            </div>`;
        document.body.appendChild(modal);
        modal.querySelector('#btn-close-shortcuts').addEventListener('click', () => modal.remove());
        modal.querySelector('.shortcuts-overlay').addEventListener('click', (e) => {
            if (e.target === e.currentTarget) modal.remove();
        });
    }

    // ========== 飞行导航 ==========
    flyToNode(nodeId) {
        if (!this.globalGraphData) return;
        const targetNode = this.globalGraphData.nodes.find(n => n.id === nodeId || n.id === String(nodeId));
        if (targetNode && targetNode.x !== undefined) {
            const dist = Math.sqrt(targetNode.x ** 2 + targetNode.y ** 2 + targetNode.z ** 2);
            const safeDist = dist === 0 ? 1 : dist;
            const distRatio = 1 + 150 / safeDist;
            this.engine.graph.cameraPosition(
                { x: targetNode.x * distRatio, y: targetNode.y * distRatio, z: targetNode.z * distRatio },
                targetNode, 1000
            );
            this.toast(`视角已飞抵目标: ID ${nodeId}`);
        }
    }

    triggerNodeFocus(nodeId) {
        if (!this.globalGraphData) return;
        const targetNode = this.globalGraphData.nodes.find(n => n.id === nodeId || n.id === String(nodeId));
        if (targetNode) {
            this.engine.focusNode = nodeId;
            this.engine.refreshFilters();
            this.updateRadarPanel(nodeId);
            this.flyToNode(nodeId);
        }
    }

    handleNodeSelection(nodeId) {
        const sInput = document.getElementById('s');
        const tInput = document.getElementById('t');
        if (!sInput.value) {
            sInput.value = nodeId;
            this.toast(`已锁定起点: ID ${nodeId}`);
        } else if (sInput.value && !tInput.value && sInput.value !== nodeId) {
            tInput.value = nodeId;
            this.toast(`已锁定终点: ID ${nodeId}`);
        } else {
            sInput.value = nodeId;
            tInput.value = '';
            this.toast(`已重置并锁定新起点: ID ${nodeId}`);
        }
        this.engine.setSelectedNodes(sInput.value, tInput.value);
    }

    resetAll() {
        document.getElementById('s').value = '';
        document.getElementById('t').value = '';
        document.getElementById('path-hud').style.display = 'none';
        this.engine.reset();
        this.toast('系统视角与状态已重置');
    }

    // ========== 仪表板 ==========
    toggleDashboard() {
        if (this.chartDashboard.visible) {
            this.chartDashboard.hide();
            this.toast('数据洞察面板已关闭');
        } else {
            if (!this.globalGraphData) {
                this.toast('请先载入核心数据集', 'warning');
                return;
            }
            this.chartDashboard.init(document.getElementById('stats-dashboard'));
            this.populateCharts();
            this.chartDashboard.show();
            this.toast('数据洞察面板已打开');
        }
    }

    populateCharts() {
        if (!this.globalGraphData) return;

        try {
            const degreeMap = {};
            this.globalGraphData.nodes.forEach(n => { degreeMap[n.id] = n.degree || 0; });
            this.chartDashboard.updateDegreeDistribution(degreeMap);
        } catch (e) { console.warn('度数图表更新失败', e); }

        try {
            const commMap = {};
            this.globalGraphData.nodes.forEach(n => { commMap[n.id] = n.community || '未知'; });
            this.chartDashboard.updateCommunityDistribution(commMap);
        } catch (e) { console.warn('社区图表更新失败', e); }

        try {
            if (Array.isArray(this.algorithmResults.pagerank?.data)) {
                this.chartDashboard.updatePageRankBars(this.algorithmResults.pagerank.data);
            }
        } catch (e) { console.warn('PageRank图表更新失败', e); }

        try {
            if (this.algorithmTiming && Object.keys(this.algorithmTiming).length > 0) {
                this.chartDashboard.updateTimingComparison(this.algorithmTiming);
            }
        } catch (e) { console.warn('耗时图表更新失败', e); }

        try {
            if (this.algorithmResults.stats) {
                const s = this.algorithmResults.stats;
                const el = document.getElementById('global-stats');
                if (el) el.innerHTML =
                    `节点: <b style="color:#00ff88">${s.nodes || 0}</b> | ` +
                    `边: <b style="color:#00ff88">${s.edges || 0}</b> | ` +
                    `密度: <b style="color:#0088ff">${(s.density || 0).toFixed(6)}</b> | ` +
                    `平均度: <b style="color:#ffaa00">${(s.avg_degree || 0).toFixed(1)}</b> | ` +
                    `最大度: <b style="color:#ff0055">${s.max_degree || 0}</b> | ` +
                    `直径: <b style="color:#aa00ff">${s.diameter_approx || 0}</b> | ` +
                    `分量: <b style="color:#00ffff">${s.components || 0}</b>`;
            }
        } catch (e) { console.warn('全局统计更新失败', e); }
    }

    // ========== 事件绑定 ==========
    bindEvents() {
        document.getElementById('btn-load').addEventListener('click', () => this.handleLoadFullSystem());
        document.getElementById('btn-path-bfs').addEventListener('click', () => this.handleShortestPath('bfs'));
        document.getElementById('btn-path-dijkstra').addEventListener('click', () => this.handleShortestPath('dijkstra'));
        document.getElementById('btn-dfs').addEventListener('click', () => {
            const start = document.getElementById('s').value.trim();
            if (!start) return this.toast('请先点击锁定一个探测起点！', 'warning');
            this.handleShortestPath('dfs');
        });
        document.getElementById('btn-dashboard').addEventListener('click', () => this.toggleDashboard());
        document.getElementById('btn-close-dash').addEventListener('click', () => this.chartDashboard.hide());
        document.getElementById('btn-reset').addEventListener('click', () => this.resetAll());
        document.getElementById('btn-toggle-links').addEventListener('click', (e) => {
            const isShowing = this.engine.toggleLinks();
            e.target.innerHTML = isShowing ? "⚠️ 显示全网连线" : "👁️ 隐藏全网连线";
            e.target.className = isShowing ? "" : "btn-danger";
            if (isShowing) this.toast("已开启全网连线，请注意设备性能负荷", "warning");
        });
        document.getElementById('ctrl-repel').addEventListener('input', () => this.handleForceChange());
        document.getElementById('ctrl-link').addEventListener('input', () => this.handleForceChange());
        document.getElementById('btn-play').addEventListener('click', () => this.togglePlayback());
        document.getElementById('timeline-slider').addEventListener('input', (e) => {
            if (this.isPlaying) this.togglePlayback();
            this.engine.renderToTimeStep(e.target.value);
        });
        document.getElementById('btn-export-json').addEventListener('click', () => this.handleExport('json'));
        document.getElementById('btn-export-csv').addEventListener('click', () => this.handleExport('csv'));
        document.getElementById('ranking-metric').addEventListener('change', (e) => {
            this.rankingMetric = e.target.value;
            this.refreshRankingList();
        });
    }

    injectClickInteractions() {
        document.getElementById('graph').addEventListener('contextmenu', e => e.preventDefault());
        this.engine.graph.onNodeClick(node => {
            this.handleNodeSelection(node.id);
            try {
                if (node.x !== undefined) {
                    const dist = Math.hypot(node.x, node.y, node.z);
                    const distRatio = 1 + 150 / Math.max(dist, 1);
                    this.engine.graph.cameraPosition(
                        { x: node.x * distRatio, y: node.y * distRatio, z: node.z * distRatio }, node, 1500
                    );
                }
            } catch (err) { /* ignore */ }
        });
        this.engine.graph.onBackgroundClick(() => this.resetAll());
    }

    handleForceChange() {
        const repel = document.getElementById('ctrl-repel').value;
        const link = document.getElementById('ctrl-link').value;
        document.getElementById('val-repel').innerText = repel;
        document.getElementById('val-link').innerText = link;
        this.engine.updateForces(repel, link);
    }

    // ========== 加载流程 ==========
    showLoading(text, progress) {
        document.getElementById('loading-screen').style.display = 'flex';
        document.getElementById('loading-text').innerText = text;
        const prog = document.getElementById('loading-progress');
        if (progress) {
            prog.style.display = 'block';
            prog.innerText = progress;
        }
    }
    hideLoading() { document.getElementById('loading-screen').style.display = 'none'; }

    async handleLoadFullSystem() {
        const steps = [
            ['拓扑数据', () => APIService.getFullGraph()],
            ['PageRank', () => APIService.getPageRank()],
            ['LPA 社区', () => APIService.getCommunity()],
            ['Betweenness', () => APIService.getBetweenness()],
            ['K-Core', () => APIService.getKCore()],
            ['聚类系数', () => APIService.getClusteringCoeff()],
            ['图统计', () => APIService.getGraphStats()],
            ['连通分量', () => APIService.getConnectedComponents()],
        ];

        for (let i = 0; i < steps.length; i++) {
            const [name, fn] = steps[i];
            this.showLoading(name, `${i + 1}/${steps.length} ${name}...`);
            try {
                const data = await fn();
                if (data.status === 'success') {
                    this.algorithmResults[name === '拓扑数据' ? 'topology' :
                        name === 'LPA 社区' ? 'community' :
                            name === '连通分量' ? 'connected_components' :
                                name === '聚类系数' ? 'clustering_coeff' :
                                    name === '图统计' ? 'stats' : name.toLowerCase()
                    ] = data;
                    if (data.time_ms) {
                        this.algorithmTiming[name] = data.time_ms;
                    }
                }
            } catch (e) {
                console.warn(`${name} 加载失败:`, e);
            }
        }

        // 处理拓扑数据
        const topoData = this.algorithmResults.topology;
        if (!topoData || topoData.status !== 'success') {
            this.showLoading('加载失败: 拓扑数据不可用', '');
            setTimeout(() => this.hideLoading(), 3000);
            return;
        }

        this.globalGraphData = topoData;

        // 构建辅助 maps
        const prMap = {};
        if (this.algorithmResults.pagerank?.data) {
            this.algorithmResults.pagerank.data.forEach(item => { prMap[item.node] = item.score; });
        }
        const commMap = {};
        if (this.algorithmResults.community?.data) {
            this.algorithmResults.community.data.forEach(item => { commMap[item.node] = item.community; });
        }
        const bcMap = {};
        if (this.algorithmResults.betweenness?.data) {
            this.algorithmResults.betweenness.data.forEach(item => { bcMap[item.node] = item.score; });
        }
        const kcMap = {};
        if (this.algorithmResults.kcore?.data) {
            this.algorithmResults.kcore.data.forEach(item => { kcMap[item.node] = item.coreness; });
        }
        const ccMap = {};
        if (this.algorithmResults.clustering_coeff?.data) {
            this.algorithmResults.clustering_coeff.data.forEach(item => { ccMap[item.node] = item.coefficient; });
        }

        const degreeMap = {};
        topoData.links.forEach(link => {
            const src = link.source.id || link.source;
            const tgt = link.target.id || link.target;
            degreeMap[src] = (degreeMap[src] || 0) + 1;
            degreeMap[tgt] = (degreeMap[tgt] || 0) + 1;
        });

        this.showLoading('注入 3D 引擎...', '渲染中...');
        setTimeout(() => {
            this.engine.prepareBigBang(topoData, prMap, commMap, degreeMap, bcMap, kcMap, ccMap);
            this.refreshRankingList();
            this.updateLegend(commMap);
            document.getElementById('legend-panel').style.display = 'block';
            document.getElementById('timeline-panel').style.display = 'block';
            this.hideLoading();
            this.engine.renderToTimeStep(1);
            this.toast(`数据装载完毕！${topoData.nodes.length} 节点, ${topoData.links.length} 条边已就绪`, 'success');
        }, 300);
    }

    // ========== 排行榜 ==========
    refreshRankingList() {
        const list = document.getElementById('rank-list');
        list.innerHTML = '';
        let items = [];

        switch (this.rankingMetric) {
            case 'pagerank':
                if (this.algorithmResults.pagerank?.data) {
                    items = this.algorithmResults.pagerank.data
                        .sort((a, b) => b.score - a.score)
                        .slice(0, 15)
                        .map(item => ({ id: item.node, val: (item.score * 100).toFixed(2), label: 'PR' }));
                }
                break;
            case 'betweenness':
                if (this.algorithmResults.betweenness?.data) {
                    items = this.algorithmResults.betweenness.data
                        .sort((a, b) => b.score - a.score)
                        .slice(0, 15)
                        .map(item => ({ id: item.node, val: item.score.toFixed(2), label: 'BC' }));
                }
                break;
            case 'kcore':
                if (this.algorithmResults.kcore?.data) {
                    items = this.algorithmResults.kcore.data
                        .sort((a, b) => b.coreness - a.coreness)
                        .slice(0, 15)
                        .map(item => ({ id: item.node, val: Math.round(item.coreness), label: 'KC' }));
                }
                break;
            case 'clustering':
                if (this.algorithmResults.clustering_coeff?.data) {
                    items = this.algorithmResults.clustering_coeff.data
                        .sort((a, b) => b.coefficient - a.coefficient)
                        .slice(0, 15)
                        .map(item => ({ id: item.node, val: item.coefficient.toFixed(3), label: 'CC' }));
                }
                break;
        }

        if (items.length === 0) {
            list.innerHTML = '<div style="color:#666; text-align:center; margin-top:10px; font-size:12px;">无数据</div>';
            return;
        }

        items.forEach((item, index) => {
            const div = document.createElement('div');
            div.className = 'rank-item';
            div.innerHTML = `<span class="rank-id">TOP ${index + 1} <b>ID: ${item.id}</b></span> <span class="score">${item.val}</span>`;
            div.addEventListener('click', () => {
                this.handleNodeSelection(item.id);
                this.flyToNode(item.id);
            });
            list.appendChild(div);
        });
    }

    // ========== 图例 ==========
    updateLegend(commMap) {
        const colorCount = {};
        for (const [node, comm] of Object.entries(commMap)) {
            const targetNode = this.globalGraphData?.nodes.find(n => n.id === node);
            const color = targetNode?.color || '#fff';
            if (!colorCount[color]) colorCount[color] = { comm, count: 0 };
            colorCount[color].count++;
        }
        const legendList = document.getElementById('legend-list');
        legendList.innerHTML = Object.entries(colorCount).map(([color, info]) =>
            `<div class="legend-item">
                <span class="legend-dot" style="background:${color}; box-shadow: 0 0 6px ${color};"></span>
                <span class="legend-label">${info.comm} (${info.count})</span>
            </div>`
        ).join('');
    }

    // ========== 导出 ==========
    async handleExport(format) {
        const dataType = document.getElementById('export-datatype').value;
        try {
            await APIService.exportData(dataType, format);
            this.toast(`${dataType}.${format} 导出成功!`);
        } catch (e) {
            this.toast(`导出失败: ${e.message}`, 'error');
        }
    }

    // ========== 路径查找 ==========
    async handleShortestPath(algorithm) {
        const start = document.getElementById('s').value.trim();
        const target = document.getElementById('t').value.trim();
        if (!start || !target) return this.toast('请先在星空中点击选择起点和终点！', 'warning');

        const btnId = algorithm === 'dijkstra' ? 'btn-path-dijkstra' : 'btn-path-bfs';
        const btn = document.getElementById(btnId);
        const originalText = btn.innerText;
        btn.innerText = "⏳ 算力全开中...";

        try {
            const data = await APIService.getShortestPath(start, target, algorithm);
            if (data.status === 'success') {
                this.engine.renderPath(data.path);
                this.showHUD(data.path);
                const typeName = algorithm === 'dijkstra' ? '高亲密链路' : algorithm === 'dfs' ? '回声室闭环' : '最少中转链路';
                this.toast(`${typeName} 提取成功！途径 ${data.path.length - 1} 跳`);
            } else {
                this.toast(`追踪失败: ${data.message || '两人处于信息孤岛'}`, 'error');
                this.engine.reset();
            }
        } catch (err) {
            this.toast('底层 C++ 引擎通信异常', 'error');
        } finally {
            btn.innerText = originalText;
        }
    }

    showHUD(pathArr) {
        const hud = document.getElementById('path-hud');
        if (!pathArr || pathArr.length === 0) { hud.style.display = 'none'; return; }
        hud.style.display = 'flex';
        let html = `<span class="hud-title">链路提取完成</span>`;
        pathArr.forEach((p, i) => {
            html += `<span class="node-badge">ID: ${p}</span>`;
            if (i < pathArr.length - 1) html += `<span>➔</span>`;
        });
        hud.innerHTML = html;
    }

    // ========== 时间轴 ==========
    togglePlayback() {
        if (!this.globalGraphData) return this.toast("请先载入核心数据集！", "warning");
        const btn = document.getElementById('btn-play');
        const slider = document.getElementById('timeline-slider');

        this.isPlaying = !this.isPlaying;
        if (this.isPlaying) {
            btn.innerText = '⏸️';
            if (parseInt(slider.value) >= 100) slider.value = 1;
            this.playInterval = setInterval(() => {
                let val = parseInt(slider.value);
                if (val >= 100) {
                    this.togglePlayback();
                    this.toast("宇宙演化完成！", "success");
                } else {
                    val += 1;
                    slider.value = val;
                    this.engine.renderToTimeStep(val);
                }
            }, 80);
        } else {
            btn.innerText = '▶️';
            clearInterval(this.playInterval);
        }
    }
}

document.addEventListener('DOMContentLoaded', () => { window.app = new AppController(); });
