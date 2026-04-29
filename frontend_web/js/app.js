// js/app.js
import { APIService } from './api.js';
import { Engine3D } from './graphEngine.js';

class AppController {
    constructor() {
        this.engine = new Engine3D('graph');
        this.globalGraphData = null;
        this.playInterval = null; // 🌟 播放器定时器
        this.isPlaying = false;   // 🌟 播放状态
        this.createRadarPanel(); // 🌟 1. 动态生成雷达面板
        // 🌟 2. 接收 C++ 3D 引擎的右键聚焦信号，联动 UI！
        this.engine.onNodeFocus = (focusId) => this.updateRadarPanel(focusId);
        this.bindEvents();
        this.injectClickInteractions(); // 注入 3D 节点点击逻辑


    }

    // 🌟 全新企业级消息通知系统
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

    // 🌟 动态创建右侧雷达 UI
    createRadarPanel() {
        const panel = document.createElement('div');
        panel.id = 'radar-panel';
        panel.className = 'cyber-radar-panel';
        document.body.appendChild(panel);
    }

    // 🌟 核心：更新人脉探测数据
    updateRadarPanel(focusId) {
        const panel = document.getElementById('radar-panel');
        if (!focusId) {
            panel.classList.remove('active'); // 隐藏面板
            return;
        }

        const neighborsSet = this.engine.neighbors.get(focusId);
        if (!neighborsSet || !this.globalGraphData) return;

        // 提取兄弟节点，并按 PageRank 影响力降序排列！
        const neighbors = this.globalGraphData.nodes.filter(n => neighborsSet.has(n.id));
        neighbors.sort((a, b) => (b.prScore || 0) - (a.prScore || 0));

        let html = `
            <div class="radar-header">
                <h3>📡 目标探针: ID ${focusId}</h3>
                <p>扫描到 <b style="color:#ffd700; font-size:16px;">${neighbors.length}</b> 个直接关联人脉</p>
            </div>
            <div class="radar-list">
        `;

        // 生成高科技感的人员列表
        // 生成高科技感的人员情报卡片
        neighbors.forEach(n => {
            const score = n.prScore ? (n.prScore * 100).toFixed(2) : '0.00';
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
                        <div class="stat-row"><span>直系小弟:</span> <span style="color:#00ccff; font-weight:bold;">${n.degree || 0} 人</span></div>
                    </div>
                    
                    <div class="card-actions">
                        <button class="btn-mini" onclick="window.app.handleNodeSelection('${n.id}')" title="设为寻路起点/终点">🎯 锁定路由</button>
                        <button class="btn-mini btn-focus" onclick="window.app.triggerNodeFocus('${n.id}')" title="查看此人的人脉圈">👁️ 深度探测</button>
                    </div>
                </div>
            `;
        });
        html += `</div>`;
        panel.innerHTML = html;
        panel.classList.add('active'); // 弹出面板
    }
    bindEvents() {
        document.getElementById('btn-load').addEventListener('click', () => this.handleLoadFullSystem());
        // 删掉原来的 btn-path 绑定，换成这俩：
        document.getElementById('btn-path-bfs').addEventListener('click', () => this.handleShortestPath('bfs'));
        document.getElementById('btn-path-dijkstra').addEventListener('click', () => this.handleShortestPath('dijkstra'));

        document.getElementById('btn-dfs').addEventListener('click', () => {
            const start = document.getElementById('s').value.trim();
            if (!start) return this.toast('请先点击锁定一个探测起点！', 'warning');
            this.handleShortestPath('dfs'); // 复用现有的处理函数
        });

        // 彻底的重置逻辑
        document.getElementById('btn-reset').addEventListener('click', () => {
            document.getElementById('s').value = '';
            document.getElementById('t').value = '';
            document.getElementById('path-hud').style.display = 'none';
            this.engine.reset();
            this.toast('系统视角与状态已重置');
        });

        document.getElementById('btn-toggle-links').addEventListener('click', (e) => {
            const isShowing = this.engine.toggleLinks();
            e.target.innerHTML = isShowing ? "⚠️ 显示全网连线 (极度吃性能)" : "👁️ 隐藏全网连线 (极度流畅)";
            e.target.className = isShowing ? "" : "btn-danger";
            if (isShowing) this.toast("已开启全网连线，请注意设备性能负荷", "warning");
        });

        document.getElementById('ctrl-repel').addEventListener('input', () => this.handleForceChange());
        document.getElementById('ctrl-link').addEventListener('input', () => this.handleForceChange());

        // ... 原来的绑定不变 ...
        // 🌟 新增时间轴绑定
        document.getElementById('btn-play').addEventListener('click', () => this.togglePlayback());
        document.getElementById('timeline-slider').addEventListener('input', (e) => {
            if (this.isPlaying) this.togglePlayback(); // 手动拖拽时自动暂停
            this.engine.renderToTimeStep(e.target.value);
        });
    }

    // 🌟 播放器控制中枢
    togglePlayback() {
        if (!this.globalGraphData) return this.toast("请先载入核心数据集！", "warning");
        const btn = document.getElementById('btn-play');
        const slider = document.getElementById('timeline-slider');

        this.isPlaying = !this.isPlaying;

        if (this.isPlaying) {
            btn.innerText = '⏸️';
            // 如果已经放完了，重头开始
            if (parseInt(slider.value) >= 100) slider.value = 1;

            this.playInterval = setInterval(() => {
                let val = parseInt(slider.value);
                if (val >= 100) {
                    this.togglePlayback(); // 播放结束，自动暂停
                    this.toast("宇宙演化完成！", "success");
                } else {
                    val += 1; // 每次前进 1%
                    slider.value = val;
                    this.engine.renderToTimeStep(val);
                }
            }, 80); // 每 80 毫秒推进一帧（你可以调这个控制膨胀速度）
        } else {
            btn.innerText = '▶️';
            clearInterval(this.playInterval);
        }
    }
    // 🌟 新增 1：让镜头平滑飞向指定节点（不改变路由锁定状态）
    flyToNode(nodeId) {
        if (!this.globalGraphData) return;
        const targetNode = this.globalGraphData.nodes.find(n => n.id === nodeId || n.id === String(nodeId));
        if (targetNode && targetNode.x !== undefined) {
            const dist = Math.sqrt(targetNode.x * targetNode.x + targetNode.y * targetNode.y + targetNode.z * targetNode.z);
            const safeDist = dist === 0 ? 1 : dist;
            const distRatio = 1 + 150 / safeDist;
            this.engine.graph.cameraPosition({ x: targetNode.x * distRatio, y: targetNode.y * distRatio, z: targetNode.z * distRatio }, targetNode, 1000);
            this.toast(`视角已飞抵目标: ID ${nodeId}`);
        }
    }

    // 🌟 新增 2：在雷达面板中直接触发“深度探测”（无限下钻朋友的朋友）
    triggerNodeFocus(nodeId) {
        if (!this.globalGraphData) return;
        const targetNode = this.globalGraphData.nodes.find(n => n.id === nodeId || n.id === String(nodeId));
        if (targetNode) {
            // 模拟 3D 引擎里的右键点击逻辑
            this.engine.focusNode = nodeId;
            this.engine.refreshFilters();
            this.updateRadarPanel(nodeId); // 雷达面板自身更新为新目标！
            this.flyToNode(nodeId);
        }
    }

    // 🌟 统一处理节点选中的智能逻辑
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

        // 同步通知 3D 引擎改变节点颜色大小
        this.engine.setSelectedNodes(sInput.value, tInput.value);
    }

    injectClickInteractions() {
        // 🌟 阻止 WebGL 画布上的默认右键菜单弹出！
        document.getElementById('graph').addEventListener('contextmenu', e => e.preventDefault());

        // 左键点击节点：锁定起点/终点
        this.engine.graph.onNodeClick(node => {
            this.handleNodeSelection(node.id);
            try {
                if (node.x !== undefined && node.y !== undefined && node.z !== undefined) {
                    const dist = Math.sqrt(node.x * node.x + node.y * node.y + node.z * node.z);
                    const safeDist = dist === 0 ? 1 : dist;
                    const distRatio = 1 + 150 / safeDist;
                    this.engine.graph.cameraPosition({ x: node.x * distRatio, y: node.y * distRatio, z: node.z * distRatio }, node, 1500);
                }
            } catch (err) { }
        });

        // 点击宇宙背景：一键清空所有选中、孤立、路径状态！
        this.engine.graph.onBackgroundClick(() => {
            document.getElementById('s').value = '';
            document.getElementById('t').value = '';
            this.engine.setSelectedNodes(null, null);
            this.engine.focusNode = null;

            // 🌟 通知雷达面板关闭
            if (this.engine.onNodeFocus) this.engine.onNodeFocus(null);

            this.engine.refreshFilters();
            this.toast('已清空全图锁定状态');
        });
    }

    handleForceChange() {
        const repel = document.getElementById('ctrl-repel').value;
        const link = document.getElementById('ctrl-link').value;
        document.getElementById('val-repel').innerText = repel;
        document.getElementById('val-link').innerText = link;
        this.engine.updateForces(repel, link);
    }

    showLoading(text) {
        document.getElementById('loading-screen').style.display = 'flex';
        document.getElementById('loading-text').innerText = text;
    }
    hideLoading() { document.getElementById('loading-screen').style.display = 'none'; }

    async handleLoadFullSystem() {
        this.showLoading("1/4 正在获取星系拓扑...");
        try {
            const res = await APIService.getFullGraph();
            if (res.status !== 'success') throw new Error("拓扑数据加载失败");

            this.globalGraphData = res;

            this.showLoading("2/4 正在执行 PageRank 评估...");
            const prData = await APIService.getPageRank();
            // 🌟 核心修复：如果 PageRank 失败，跳过它，不要让整个 JS 崩掉
            const prMap = {};
            if (prData.status === 'success' && prData.data) {
                prData.data.forEach(item => prMap[item.node] = item.score);
            } else {
                console.warn("PageRank 权重获取失败，将使用默认权重");
            }

            this.showLoading("3/4 正在执行 LPA 社区裂变...");
            const commData = await APIService.getCommunity();
            const commMap = {};
            if (commData.status === 'success' && commData.data) {
                commData.data.forEach(item => commMap[item.node] = item.community);
            }

            this.showLoading("4/4 正在向 3D 引擎注入视觉情报...");
            const degreeMap = {};
            this.globalGraphData.links.forEach(link => {
                const src = link.source.id || link.source;
                const tgt = link.target.id || link.target;
                degreeMap[src] = (degreeMap[src] || 0) + 1;
                degreeMap[tgt] = (degreeMap[tgt] || 0) + 1;
            });

            setTimeout(() => {
                // 启动大爆炸准备
                this.engine.prepareBigBang(this.globalGraphData, prMap, commMap, degreeMap);
                if (prData.data) this.updateRankList(prData.data);

                document.getElementById('timeline-panel').style.display = 'block';
                this.hideLoading();
                this.engine.renderToTimeStep(1);
                this.toast("数据装载完毕，大爆炸引信已点燃！");
            }, 500);

        } catch (error) {
            console.error("加载链崩溃详情:", error);
            this.showLoading(`🚨 加载中断: ${error.message}`);
            setTimeout(() => this.hideLoading(), 5000);
        }
    }

    updateRankList(rankData) {
        const list = document.getElementById('rank-list');
        list.innerHTML = '';
        rankData.sort((a, b) => b.score - a.score).slice(0, 15).forEach((item, index) => {
            const div = document.createElement('div');
            div.className = 'rank-item';
            div.innerHTML = `<span class="rank-id">TOP ${index + 1} <b>ID: ${item.node}</b></span> <span class="score">${(item.score * 100).toFixed(2)}</span>`;

            // 排行榜点击，完美复用智能选中逻辑！
            div.addEventListener('click', () => {
                this.handleNodeSelection(item.node);
                const targetNode = this.engine.graph.graphData().nodes.find(n => n.id === item.node || n.id === String(item.node));
                if (targetNode && targetNode.x !== undefined) {
                    const dist = Math.sqrt(targetNode.x * targetNode.x + targetNode.y * targetNode.y + targetNode.z * targetNode.z);
                    const safeDist = dist === 0 ? 1 : dist;
                    const distRatio = 1 + 150 / safeDist;
                    this.engine.graph.cameraPosition({ x: targetNode.x * distRatio, y: targetNode.y * distRatio, z: targetNode.z * distRatio }, targetNode, 1500);
                }
            });
            list.appendChild(div);
        });
    }

    async handleShortestPath(algorithm) { // 🌟 接收算法类型
        const start = document.getElementById('s').value.trim();
        const target = document.getElementById('t').value.trim();
        if (!start || !target) return this.toast('请先在星空中点击选择起点和终点！', 'warning');

        // 根据算法决定按钮的动画
        const btnId = algorithm === 'dijkstra' ? 'btn-path-dijkstra' : 'btn-path-bfs';
        const btn = document.getElementById(btnId);
        const originalText = btn.innerText;
        btn.innerText = "⏳ 算力全开中...";

        try {
            // 🌟 传入 algorithm
            const data = await APIService.getShortestPath(start, target, algorithm);
            if (data.status === 'success') {
                this.engine.renderPath(data.path);
                this.showHUD(data.path);
                const typeName = algorithm === 'dijkstra' ? '高亲密链路' : '最少中转链路';
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
}

document.addEventListener('DOMContentLoaded', () => { window.app = new AppController(); });