// js/graphEngine.js — 3D 力导向图引擎封装 (性能优化版)
//
// 功能:
//   - 3d-force-graph WebGL 渲染包装
//   - Big Bang 渐进式节点诞生
//   - 路径高亮 (BFS/Dijkstra/DFS)
//   - 邻居探测 (雷达面板)
//   - 力场参数调节
//   - 性能优化: LOD、节流、事件清理
//
// 导入: CONFIG (config.js)
// 导出: Engine3D 类
//
// 连接: app.js 创建实例, timeline.js/search.js 通过 app.js 间接调用

import { CONFIG } from './config.js';

export class Engine3D {
    constructor(containerId) {
        this.containerId = containerId;
        this.container = document.getElementById(containerId);

        // 3d-force-graph 实例
        this.graph = null;

        // 状态
        this.highlightNodes = new Set();
        this.highlightLinks = new Set();
        this.showAllLinks = false;
        this.selectedStart = null;
        this.selectedTarget = null;
        this.focusNode = null;
        this.neighbors = new Map();

        // 数据
        this.fullData = null;
        this.currentFrame = 100;

        // 性能控制
        this._lodEnabled = true;
        this._throttleTimers = new Map();
        this._disposed = false;

        // 回调
        this.onNodeFocus = null;

        // 初始化
        this._initGraph();
        this._bindResize();
    }

    // ============================================================
    // 初始化
    // ============================================================

    _initGraph() {
        if (!this.container) {
            console.error('[Engine3D] 容器元素未找到:', this.containerId);
            return;
        }

        this.graph = ForceGraph3D()(this.container);

        this.graph
            .backgroundColor('rgba(0,0,0,0)')
            .nodeResolution(16)
            .enableNodeDrag(true)
            .cooldownTicks(100)
            .onEngineStop(() => this._onEngineStop())
            .onBackgroundClick(() => {
                if (window.app) window.app._closeRadarPanel();
            })
            .nodeLabel(node => this._buildTooltip(node))
            .onNodeRightClick(node => this._onRightClick(node))
            .nodeVisibility(node => this._nodeVisibility(node))
            .linkVisibility(link => this._linkVisibility(link))
            .nodeColor(node => this._nodeColor(node))
            .nodeVal(node => this._nodeVal(node))
            .linkColor(link => this._linkColor(link))
            .linkWidth(link => this._linkWidth(link))
            .linkDirectionalParticles(link => this._linkParticles(link))
            .linkDirectionalParticleWidth(link => this._linkParticleWidth(link))
            .linkDirectionalParticleColor(link => this._linkParticleColor(link))
            .d3VelocityDecay(0.18);
    }

    _onEngineStop() {
        if (this._disposed) return;
        this.graph.zoomToFit(500);
    }

    _bindResize() {
        // 节流窗口缩放事件
        let resizeTimer = null;
        window.addEventListener('resize', () => {
            if (this._disposed) return;
            clearTimeout(resizeTimer);
            resizeTimer = setTimeout(() => {
                if (this.graph && !this._disposed) {
                    this.graph.width(window.innerWidth).height(window.innerHeight);
                }
            }, 150); // 150ms 节流
        });
    }

    // ============================================================
    // 工具提示
    // ============================================================

    _buildTooltip(node) {
        const bc = node.betweennessScore ? node.betweennessScore.toFixed(4) : '-';
        const kc = node.kcore !== undefined ? Math.round(node.kcore) : '-';
        const cc = node.clusteringCoeff !== undefined ? node.clusteringCoeff.toFixed(3) : '-';
        const pr = node.prScore ? (node.prScore * 100).toFixed(4) : '0';

        return `
            <div class="cyber-tooltip">
                <h4>ID ${node.id}</h4>
                <p><span class="label">阵营</span> <span class="value">${node.community || '?'}</span></p>
                <p><span class="label">人脉</span> <span class="value" style="color:#00ccff;">${node.degree || 0} 人</span></p>
                <p><span class="label">权重 PR</span> <span class="value" style="color:#ffaa00;">${pr}%</span></p>
                <p><span class="label">中介 BC</span> <span class="value" style="color:#ffd700;">${bc}</span></p>
                <p><span class="label">核心 KC</span> <span class="value" style="color:#aa00ff;">${kc}</span></p>
                <p><span class="label">聚类 CC</span> <span class="value" style="color:#00ffff;">${cc}</span></p>
                <p style="text-align:center; margin-top:8px; color:#888; font-size:10px;">[左键]锁定 | [右键]人脉 | [拖拽]移动</p>
            </div>`;
    }

    // ============================================================
    // 交互事件
    // ============================================================

    _onRightClick(node) {
        if (this._disposed) return;
        this.focusNode = (this.focusNode === node.id) ? null : node.id;
        this.refreshFilters();

        if (this.onNodeFocus) {
            this.onNodeFocus(this.focusNode, node);
        }

        if (this.focusNode) {
            const dist = Math.hypot(node.x || 0, node.y || 0, node.z || 0);
            const distRatio = 1 + 120 / Math.max(dist, 1);
            this.graph.cameraPosition(
                { x: (node.x || 0) * distRatio, y: (node.y || 0) * distRatio, z: (node.z || 0) * distRatio },
                node,
                1000
            );
        }
    }

    // ============================================================
    // 可见性规则
    // ============================================================

    _nodeVisibility(node) {
        if (this._disposed) return false;
        // Big Bang: 未诞生的节点隐藏
        if (node.birthFrame > this.currentFrame) return false;

        const isPathMode = this.highlightNodes.size > 0;
        const isFocusMode = this.focusNode !== null;

        // 全景模式: 全部可见
        if (!isPathMode && !isFocusMode) return true;

        // 路径模式: 仅高亮节点可见
        if (isPathMode && this.highlightNodes.has(node.id)) return true;

        // 邻居探测模式: 焦点节点 + 其邻居可见
        if (isFocusMode) {
            if (node.id === this.focusNode) return true;
            if (this.neighbors.get(this.focusNode)?.has(node.id)) return true;
            return false;
        }

        return false;
    }

    _linkVisibility(link) {
        if (this._disposed) return false;
        if (link.birthFrame > this.currentFrame) return false;

        const isPathMode = this.highlightNodes.size > 0;
        const isFocusMode = this.focusNode !== null;

        if (!isPathMode && !isFocusMode) return this.showAllLinks;

        if (isPathMode && this._isLinkHighlighted(link)) return true;

        if (isFocusMode) {
            const s = link.source.id || link.source;
            const t = link.target.id || link.target;
            return s === this.focusNode || t === this.focusNode;
        }

        return false;
    }

    // ============================================================
    // 样式规则
    // ============================================================

    _nodeColor(node) {
        if (this._disposed) return '#fff';
        // 起点/终点高亮
        if (node.id === this.selectedStart) return '#00ccff';
        if (node.id === this.selectedTarget) return '#ff0055';

        const isFocusMode = this.focusNode !== null;
        if (isFocusMode) {
            const isFocus = node.id === this.focusNode;
            const isNeighbor = this.neighbors.get(this.focusNode)?.has(node.id);
            if (isFocus || isNeighbor) return node.color || '#fff';
            if (this.highlightNodes.has(node.id)) return 'rgba(255,255,255,0.2)';
            return 'rgba(255,255,255,0.03)';
        }
        return node.color || '#fff';
    }

    _nodeVal(node) {
        const baseSize = (node.prScore || 0) > 0
            ? Math.max(3, (node.prScore || 0) * 15000)
            : 3;

        if (node.id === this.selectedStart || node.id === this.selectedTarget) {
            return baseSize * 4 + 10;
        }

        if (this.focusNode) {
            if (node.id === this.focusNode) return baseSize * 3 + 5;
            if (this.neighbors.get(this.focusNode)?.has(node.id)) return baseSize * 1.5;
        }

        // LOD: 低缩放级别减小节点体积
        if (this._lodEnabled && this.graph && this.graph.cameraPosition) {
            try {
                const cam = this.graph.cameraPosition();
                const dist = Math.hypot(
                    (node.x || 0) - cam.x,
                    (node.y || 0) - cam.y,
                    (node.z || 0) - cam.z
                );
                if (dist > 2000) return baseSize * 0.5;
            } catch (e) { /* ignore camera errors */ }
        }

        return baseSize;
    }

    _linkColor(link) {
        const isPathLink = this.highlightNodes.size > 0 && this._isLinkHighlighted(link);
        if (isPathLink) return '#00ff88';

        let isFocusLink = false;
        if (this.focusNode) {
            const s = link.source.id || link.source;
            const t = link.target.id || link.target;
            isFocusLink = (s === this.focusNode || t === this.focusNode);
        }
        if (isFocusLink) return '#ffd700';

        return 'rgba(40, 100, 220, 0.18)';
    }

    _linkWidth(link) {
        if (this.highlightNodes.size > 0 && this._isLinkHighlighted(link)) return 2.5;
        if (this.focusNode) {
            const s = link.source.id || link.source;
            const t = link.target.id || link.target;
            if (s === this.focusNode || t === this.focusNode) return 1.5;
        }
        return 0.3;
    }

    _linkParticles(link) {
        if (this.highlightNodes.size > 0 && this._isLinkHighlighted(link)) return 5;
        if (this.focusNode) {
            const s = link.source.id || link.source;
            const t = link.target.id || link.target;
            if (s === this.focusNode || t === this.focusNode) return 3;
        }
        return 1.5;
    }

    _linkParticleWidth(link) {
        return (this.highlightNodes.size > 0 && this._isLinkHighlighted(link)) ? 4 : 1.2;
    }

    _linkParticleColor(link) {
        return (this.highlightNodes.size > 0 && this._isLinkHighlighted(link))
            ? '#ffffff'
            : 'rgba(0, 255, 255, 0.7)';
    }

    // ============================================================
    // 公开方法
    // ============================================================

    /** 检查 link 是否在路径中 */
    _isLinkHighlighted(link) {
        const s = link.source.id || link.source;
        const t = link.target.id || link.target;
        return this.highlightLinks.has(`${s}-${t}`) || this.highlightLinks.has(`${t}-${s}`);
    }

    /** 设置选中节点 */
    setSelectedNodes(startId, targetId) {
        this.selectedStart = startId || null;
        this.selectedTarget = targetId || null;
        this.refreshFilters();
    }

    /**
     * 准备 Big Bang (注入数据并构建邻居映射)
     * 使用 requestIdleCallback 分片处理大数据
     */
    prepareBigBang(data, prMap, communityMap, degreeMap, bcMap = {}, kcMap = {}, ccMap = {}) {
        if (this._disposed) return;

        let colorIdx = 0;
        const rootColors = {};

        // 构建邻居映射
        this.neighbors.clear();
        data.nodes.forEach(n => this.neighbors.set(n.id, new Set()));
        data.links.forEach(link => {
            const s = link.source.id || link.source;
            const t = link.target.id || link.target;
            if (this.neighbors.has(s)) this.neighbors.get(s).add(t);
            if (this.neighbors.has(t)) this.neighbors.get(t).add(s);
        });

        // 按 ID 排序 (数值排序)
        data.nodes.sort((a, b) => (parseInt(a.id) || 0) - (parseInt(b.id) || 0));

        const totalNodes = data.nodes.length;
        const nodeBirthMap = new Map();

        // 分片处理大数据集
        const processChunk = (startIdx, chunkSize) => {
            if (this._disposed) return;

            const end = Math.min(startIdx + chunkSize, totalNodes);
            for (let i = startIdx; i < end; i++) {
                const node = data.nodes[i];
                node.degree = degreeMap[node.id] || 0;
                node.prScore = prMap[node.id] || 0;
                node.community = communityMap[node.id] || '未知';
                node.betweennessScore = bcMap[node.id] || 0;
                node.kcore = kcMap[node.id] || 0;
                node.clusteringCoeff = ccMap[node.id] || 0;

                if (!rootColors[node.community]) {
                    rootColors[node.community] = CONFIG.CYBER_PALETTE[colorIdx % CONFIG.CYBER_PALETTE.length];
                    colorIdx++;
                }
                node.color = rootColors[node.community];

                node.birthFrame = Math.max(1, Math.ceil(((i + 1) / totalNodes) * 100));
                nodeBirthMap.set(node.id, node.birthFrame);
            }

            if (end < totalNodes) {
                if (window.requestIdleCallback) {
                    requestIdleCallback(() => processChunk(end, chunkSize), { timeout: 50 });
                } else {
                    setTimeout(() => processChunk(end, chunkSize), 0);
                }
            } else {
                // 所有节点处理完毕，处理links
                this._finalizeBigBang(data, nodeBirthMap);
            }
        };

        processChunk(0, 500); // 每块 500 个节点
    }

    _finalizeBigBang(data, nodeBirthMap) {
        if (this._disposed) return;
        data.links.forEach(link => {
            const s = link.source.id || link.source;
            const t = link.target.id || link.target;
            link.birthFrame = Math.max(
                nodeBirthMap.get(s) || 100,
                nodeBirthMap.get(t) || 100
            );
        });

        this.fullData = data;
        this.currentFrame = 1;
        this.graph.graphData(data);
    }

    /** 渲染到指定时间步 (Big Bang) */
    renderToTimeStep(percentage) {
        if (!this.fullData || this._disposed) return;
        this.currentFrame = parseInt(percentage) || 1;

        // 触发渲染
        this.refreshFilters();

        // 更新状态面板 (异步以优化性能)
        if (window.requestIdleCallback) {
            requestIdleCallback(() => this._updateStats(), { timeout: 50 });
        } else {
            setTimeout(() => this._updateStats(), 0);
        }
    }

    _updateStats() {
        let visibleNodeCount = 0;
        let visibleLinkCount = 0;
        if (this.fullData) {
            this.fullData.nodes.forEach(n => {
                if (n.birthFrame <= this.currentFrame) visibleNodeCount++;
            });
            this.fullData.links.forEach(l => {
                if (l.birthFrame <= this.currentFrame) visibleLinkCount++;
            });
        }

        document.getElementById('stat-nodes').innerText = visibleNodeCount;
        document.getElementById('stat-edges').innerText = visibleLinkCount;

        // 力场动态调节 (初期增强斥力)
        const baseRepel = document.getElementById('ctrl-repel')?.value || 30;
        let forceMultiplier = 1;
        if (this.currentFrame < 30) forceMultiplier = 1.5;
        else if (this.currentFrame < 70) forceMultiplier = 1.2;
        this.graph.d3Force('charge').strength(-baseRepel * forceMultiplier);
    }

    /** 渲染高亮路径 */
    renderPath(pathArr) {
        if (this._disposed) return;
        this.highlightNodes.clear();
        this.highlightLinks.clear();

        pathArr.forEach(node => this.highlightNodes.add(node));
        for (let i = 0; i < pathArr.length - 1; i++) {
            this.highlightLinks.add(`${pathArr[i]}-${pathArr[i + 1]}`);
            this.highlightLinks.add(`${pathArr[i + 1]}-${pathArr[i]}`);
        }

        this.refreshFilters();
        this._focusOnPath(pathArr);
    }

    _focusOnPath(pathArr) {
        if (this._disposed) return;
        const pathNodes = pathArr
            .map(id => this.graph.graphData().nodes.find(n => n.id === id))
            .filter(n => n);

        if (pathNodes.length === 0) return;

        let cx = 0, cy = 0, cz = 0;
        pathNodes.forEach(n => { cx += n.x; cy += n.y; cz += n.z; });
        cx /= pathNodes.length;
        cy /= pathNodes.length;
        cz /= pathNodes.length;

        this.graph.cameraPosition(
            { x: cx, y: cy, z: cz + 150 + pathNodes.length * 20 },
            { x: cx, y: cy, z: cz },
            2500
        );
    }

    /** 切换连线显示 */
    toggleLinks() {
        this.showAllLinks = !this.showAllLinks;
        this.refreshFilters();
        return this.showAllLinks;
    }

    /** 更新力场参数 */
    updateForces(repel, linkDist) {
        if (this._disposed) return;
        this.graph.d3Force('charge').strength(-Number(repel));
        this.graph.d3Force('link').distance(Number(linkDist));
        this.graph.d3ReheatSimulation();
    }

    /** 重置所有状态 */
    reset() {
        if (this._disposed) return;
        this.highlightNodes.clear();
        this.highlightLinks.clear();
        this.setSelectedNodes(null, null);
        this.focusNode = null;
        this.graph.zoomToFit(1000);
        this.refreshFilters();
    }

    /** 刷新渲染过滤器 (集中调用以优化性能) */
    refreshFilters() {
        if (this._disposed) return;
        // 使用 requestAnimationFrame 确保渲染同步
        if (this._rafId) cancelAnimationFrame(this._rafId);
        this._rafId = requestAnimationFrame(() => {
            if (this._disposed) return;
            this.graph
                .nodeColor(this.graph.nodeColor())
                .nodeVal(this.graph.nodeVal())
                .nodeVisibility(this.graph.nodeVisibility())
                .linkVisibility(this.graph.linkVisibility())
                .linkWidth(this.graph.linkWidth())
                .linkColor(this.graph.linkColor())
                .linkDirectionalParticles(this.graph.linkDirectionalParticles());
        });
    }

    // ============================================================
    // 性能控制
    // ============================================================

    /** 启用/禁用 LOD (远距离节点缩小) */
    setLOD(enabled) {
        this._lodEnabled = enabled;
    }

    /** 销毁引擎, 释放资源 */
    dispose() {
        this._disposed = true;

        // 清理 raf
        if (this._rafId) cancelAnimationFrame(this._rafId);

        // 清理计时器
        this._throttleTimers.forEach(t => clearTimeout(t));
        this._throttleTimers.clear();

        // 清理集合
        this.highlightNodes.clear();
        this.highlightLinks.clear();
        this.neighbors.clear();

        // 清理 3d-force-graph
        if (this.graph && this.graph._destructor) {
            this.graph._destructor();
        }

        this.fullData = null;
        this.graph = null;
    }
}
