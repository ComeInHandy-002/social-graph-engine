// js/graphEngine.js
import { CONFIG } from './config.js';

export class Engine3D {
    constructor(containerId) {
        this.containerId = containerId;
        this.graph = ForceGraph3D()(document.getElementById(containerId));
        this.highlightNodes = new Set();
        this.highlightLinks = new Set();
        this.showAllLinks = false;
        
        this.selectedStart = null; 
        this.selectedTarget = null;
        
        this.focusNode = null; 
        this.neighbors = new Map(); 

        this.fullData = null;
        this.currentFrame = 100; 

        this.onNodeFocus = null; 

        this.init();

        // 监听窗口缩放，自适应填充
        window.addEventListener('resize', () => {
            this.graph.width(window.innerWidth).height(window.innerHeight);
        });
    }

    init() {
        this.graph
            .backgroundColor('rgba(0,0,0,0)')
            // 🌟 华丽升级 1：节点精度从 8 提升到 16，星星变成完美的圆球，不再有棱角
            .nodeResolution(16) 
            // 🌟 核心需求：开启节点拖拽！你可以随意拉扯星网了
            .enableNodeDrag(true) 
            .cooldownTicks(100)
            .onEngineStop(() => this.graph.zoomToFit(500))
            .nodeLabel(node => this.buildTooltip(node))
            
            .onNodeRightClick(node => {
                this.focusNode = (this.focusNode === node.id) ? null : node.id;
                this.refreshFilters();
                
                if (this.onNodeFocus) this.onNodeFocus(this.focusNode, node);
                
                if (this.focusNode) {
                    const distRatio = 1 + 120 / Math.max(Math.hypot(node.x, node.y, node.z), 1);
                    this.graph.cameraPosition({ x: node.x * distRatio, y: node.y * distRatio, z: node.z * distRatio }, node, 1000);
                }
            })

            .nodeVisibility(node => {
                if (node.birthFrame > this.currentFrame) return false; 
                const isPathMode = this.highlightNodes.size > 0;
                const isFocusMode = this.focusNode !== null;
                if (!isPathMode && !isFocusMode) return true; 

                if (isPathMode && this.highlightNodes.has(node.id)) return true;
                if (isFocusMode && (node.id === this.focusNode || this.neighbors.get(this.focusNode)?.has(node.id))) return true;
                return false;
            })

            .linkVisibility(link => {
                if (link.birthFrame > this.currentFrame) return false; 
                const isPathMode = this.highlightNodes.size > 0;
                const isFocusMode = this.focusNode !== null;
                if (!isPathMode && !isFocusMode) return this.showAllLinks;

                if (isPathMode && this.isLinkHighlighted(link)) return true;
                if (isFocusMode) {
                    const s = link.source.id || link.source;
                    const t = link.target.id || link.target;
                    if (s === this.focusNode || t === this.focusNode) return true;
                }
                return false;
            })
            
            .nodeColor(node => {
                if (node.id === this.selectedStart) return '#00ccff'; 
                if (node.id === this.selectedTarget) return '#ff0055'; 
                
                const isFocusMode = this.focusNode !== null;
                if (isFocusMode) {
                    const isFocus = node.id === this.focusNode;
                    const isNeighbor = this.neighbors.get(this.focusNode)?.has(node.id);
                    if (isFocus || isNeighbor) return node.color; 
                    
                    if (this.highlightNodes.has(node.id)) return 'rgba(255,255,255,0.2)'; 
                    return 'rgba(255,255,255,0.03)';
                }
                return node.color;
            })

            .nodeVal(node => {
                // 维持之前的保底大小，防止看不见
                const baseSize = node.prScore ? Math.max(3, node.prScore * 15000) : 3;
                if (node.id === this.selectedStart || node.id === this.selectedTarget) return baseSize * 4 + 10;
                
                if (this.focusNode) {
                    if (node.id === this.focusNode) return baseSize * 3 + 5;
                    if (this.neighbors.get(this.focusNode)?.has(node.id)) return baseSize * 1.5;
                }
                return baseSize;
            })

            // 🌟 华丽升级 2：极具质感的深蓝科技连线
            .linkColor(link => {
                const isPathLink = this.highlightNodes.size > 0 && this.isLinkHighlighted(link);
                let isFocusLink = false;
                if (this.focusNode) {
                    const s = link.source.id || link.source;
                    const t = link.target.id || link.target;
                    isFocusLink = (s === this.focusNode || t === this.focusNode);
                }

                if (isPathLink) return '#00ff88'; 
                if (isFocusLink) return '#ffd700'; 
                return 'rgba(40, 100, 220, 0.18)'; // 幽蓝色连线，低调奢华
            })
            .linkWidth(link => {
                const isPathLink = this.highlightNodes.size > 0 && this.isLinkHighlighted(link);
                let isFocusLink = this.focusNode && ((link.source.id || link.source) === this.focusNode || (link.target.id || link.target) === this.focusNode);
                if (isPathLink) return 2.5; 
                if (isFocusLink) return 1.5; 
                return 0.3; 
            })
            // 🌟 华丽升级 3：青色数据流光子
            .linkDirectionalParticles(link => {
                const isPathLink = this.highlightNodes.size > 0 && this.isLinkHighlighted(link);
                let isFocusLink = this.focusNode && ((link.source.id || link.source) === this.focusNode || (link.target.id || link.target) === this.focusNode);
                if (isPathLink) return 5;  
                if (isFocusLink) return 3; 
                return 1.5; // 让全网有适度的流光效果
            })
            .linkDirectionalParticleWidth(link => {
                const isPathLink = this.highlightNodes.size > 0 && this.isLinkHighlighted(link);
                return isPathLink ? 4 : (this.focusNode ? 2 : 1.2); // 背景粒子稍微放大一点点
            })
            .linkDirectionalParticleColor(link => {
                const isPathLink = this.highlightNodes.size > 0 && this.isLinkHighlighted(link);
                return isPathLink ? '#ffffff' : 'rgba(0, 255, 255, 0.7)'; // 青色赛博光子
            })
            .d3VelocityDecay(0.18); // 让拖拽手感更粘滞、有分量感
    }

    setSelectedNodes(startId, targetId) {
        this.selectedStart = startId;
        this.selectedTarget = targetId;
        this.refreshFilters();
    }

    buildTooltip(node) {
        const bc = node.betweennessScore ? node.betweennessScore.toFixed(4) : '-';
        const kc = node.kcore !== undefined ? Math.round(node.kcore) : '-';
        const cc = node.clusteringCoeff !== undefined ? node.clusteringCoeff.toFixed(3) : '-';
        return `
            <div class="cyber-tooltip">
                <h4>用户档案: ID ${node.id}</h4>
                <p><span class="label">星系阵营</span> <span class="value">${node.community || '未知'} <span class="color-dot" style="background:${node.color || '#fff'};"></span></span></p>
                <p><span class="label">直系圈子</span> <span class="value" style="color:#00ccff;">${node.degree || 0} 人</span></p>
                <p><span class="label">全网权重 (PR)</span> <span class="value" style="color:#ffaa00;">${node.prScore ? (node.prScore * 100).toFixed(4) : 0}%</span></p>
                <p><span class="label">中介中心性 (BC)</span> <span class="value" style="color:#ffd700;">${bc}</span></p>
                <p><span class="label">核心度 (K-Core)</span> <span class="value" style="color:#aa00ff;">${kc}</span></p>
                <p><span class="label">聚类系数 (CC)</span> <span class="value" style="color:#00ffff;">${cc}</span></p>
                <p style="text-align:center; margin-top:8px; color:#888; font-size:10px;">[左键]锁定 | [右键]人脉 | [拖拽]移动</p>
            </div>
        `;
    }

    isLinkHighlighted(link) {
        const id1 = `${link.source.id || link.source}-${link.target.id || link.target}`;
        const id2 = `${link.target.id || link.target}-${link.source.id || link.source}`;
        return this.highlightLinks.has(id1) || this.highlightLinks.has(id2);
    }

    // 依然保留了极其稳定的邻居计算和时间轴控制
    prepareBigBang(data, prMap, communityMap, degreeMap, bcMap = {}, kcMap = {}, ccMap = {}) {
        let colorIdx = 0; const rootColors = {};
        this.neighbors.clear();
        data.nodes.forEach(n => this.neighbors.set(n.id, new Set()));
        data.links.forEach(link => {
            const s = link.source.id || link.source;
            const t = link.target.id || link.target;
            if(this.neighbors.has(s)) this.neighbors.get(s).add(t);
            if(this.neighbors.has(t)) this.neighbors.get(t).add(s);
        });

        data.nodes.sort((a, b) => parseInt(a.id) - parseInt(b.id));

        const totalNodes = data.nodes.length;
        const nodeBirthMap = new Map();

        data.nodes.forEach((node, idx) => {
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

            node.birthFrame = Math.max(1, Math.ceil((idx / totalNodes) * 100));
            nodeBirthMap.set(node.id, node.birthFrame);
        });

        data.links.forEach(link => {
            const s = link.source.id || link.source;
            const t = link.target.id || link.target;
            const sFrame = nodeBirthMap.get(s) || 100;
            const tFrame = nodeBirthMap.get(t) || 100;
            link.birthFrame = Math.max(sFrame, tFrame);
        });

        this.fullData = data;
        this.currentFrame = 1;
        this.graph.graphData(data);
    }

    renderToTimeStep(percentage) {
        if (!this.fullData) return;
        this.currentFrame = parseInt(percentage);

        let visibleNodeCount = 0;
        let visibleLinkCount = 0;
        this.fullData.nodes.forEach(n => { if(n.birthFrame <= this.currentFrame) visibleNodeCount++; });
        this.fullData.links.forEach(l => { if(l.birthFrame <= this.currentFrame) visibleLinkCount++; });
        
        document.getElementById('stat-nodes').innerText = visibleNodeCount;
        document.getElementById('stat-edges').innerText = visibleLinkCount;

        const baseRepel = document.getElementById('ctrl-repel').value || 30;
        let forceMultiplier = 1;
        if (this.currentFrame < 30) forceMultiplier = 1.5;
        else if (this.currentFrame < 70) forceMultiplier = 1.2;
        this.graph.d3Force('charge').strength(-baseRepel * forceMultiplier);

        this.refreshFilters();
    }

    renderPath(pathArr) {
        this.highlightNodes.clear(); this.highlightLinks.clear();
        pathArr.forEach(node => this.highlightNodes.add(node));
        for (let i = 0; i < pathArr.length - 1; i++) {
            this.highlightLinks.add(`${pathArr[i]}-${pathArr[i+1]}`);
            this.highlightLinks.add(`${pathArr[i+1]}-${pathArr[i]}`);
        }
        this.refreshFilters();
        this.focusOnPath(pathArr);
    }

    focusOnPath(pathArr) {
        const pathNodes = pathArr.map(id => this.graph.graphData().nodes.find(n => n.id === id)).filter(n => n);
        if(pathNodes.length === 0) return;
        let cx=0, cy=0, cz=0; 
        pathNodes.forEach(n => { cx+=n.x; cy+=n.y; cz+=n.z; });
        cx/=pathNodes.length; cy/=pathNodes.length; cz/=pathNodes.length;
        this.graph.cameraPosition({ x: cx, y: cy, z: cz + 150 + pathNodes.length*20 }, { x: cx, y: cy, z: cz }, 2500);
    }

    toggleLinks() {
        this.showAllLinks = !this.showAllLinks;
        this.refreshFilters();
        return this.showAllLinks;
    }

    updateForces(repel, linkDist) {
        this.graph.d3Force('charge').strength(-Number(repel)); 
        this.graph.d3Force('link').distance(Number(linkDist));
        this.graph.d3ReheatSimulation();
    }

    reset() {
        this.highlightNodes.clear();
        this.highlightLinks.clear();
        this.setSelectedNodes(null, null);
        this.focusNode = null; 
        this.graph.zoomToFit(1000);
        this.refreshFilters();
    }

    refreshFilters() {
        this.graph.nodeColor(this.graph.nodeColor()).nodeVal(this.graph.nodeVal())
            .nodeVisibility(this.graph.nodeVisibility()).linkVisibility(this.graph.linkVisibility())
            .linkWidth(this.graph.linkWidth()).linkColor(this.graph.linkColor())
            .linkDirectionalParticles(this.graph.linkDirectionalParticles());
    }
}