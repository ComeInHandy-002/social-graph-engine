// js/graphEngine.js
import { CONFIG } from './config.js';

export class Engine3D {
    constructor(containerId) {
        this.graph = ForceGraph3D()(document.getElementById(containerId));
        this.highlightNodes = new Set();
        this.highlightLinks = new Set();
        this.showAllLinks = false;
        this.init();
    }

    init() {
        this.graph
            .backgroundColor('rgba(0,0,0,0)')
            .nodeResolution(4)
            .linkWidth(link => this.isLinkHighlighted(link) ? 2 : 0.1)
            .enableNodeDrag(false)
            .cooldownTicks(80)
            .onEngineStop(() => this.graph.zoomToFit(500))
            .nodeLabel(node => this.buildTooltip(node))
            .nodeVisibility(node => this.highlightNodes.size === 0 || this.highlightNodes.has(node.id))
            .linkVisibility(link => {
                if (this.highlightNodes.size > 0) return this.isLinkHighlighted(link);
                return this.showAllLinks;
            })
            .linkColor(link => this.highlightNodes.size > 0 ? CONFIG.HIGHLIGHT_COLOR : CONFIG.DIM_LINK_COLOR)
            .linkDirectionalParticles(link => (this.highlightNodes.size > 0 && this.isLinkHighlighted(link)) ? 4 : 0)
            .linkDirectionalParticleWidth(3)
            .linkDirectionalParticleColor(() => '#ffffff');
    }

    buildTooltip(node) {
        return `
            <div class="cyber-tooltip">
                <h4>用户档案: ID ${node.id}</h4>
                <p><span class="label">星系阵营</span> <span class="value">${node.community || '未知'} <span class="color-dot" style="background:${node.color || '#fff'};"></span></span></p>
                <p><span class="label">直系圈子</span> <span class="value" style="color:#00ccff;">${node.degree || 0} 人</span></p>
                <p><span class="label">全网权重</span> <span class="value" style="color:#ffaa00;">${node.prScore ? (node.prScore * 100).toFixed(4) : 0}%</span></p>
            </div>
        `;
    }

    isLinkHighlighted(link) {
        const id1 = `${link.source.id || link.source}-${link.target.id || link.target}`;
        const id2 = `${link.target.id || link.target}-${link.source.id || link.source}`;
        return this.highlightLinks.has(id1) || this.highlightLinks.has(id2);
    }

    loadData(data) {
        this.graph.graphData(data);
    }

    // 注入 PageRank 和 社区颜色
    updateNodeVisuals(prMap, communityMap, degreeMap) {
        let colorIdx = 0;
        const rootColors = {};
        
        this.graph.graphData().nodes.forEach(node => {
            node.degree = degreeMap[node.id] || 0;
            node.prScore = prMap[node.id] || 0;
            node.community = communityMap[node.id] || '未知';
            
            if (!rootColors[node.community]) {
                rootColors[node.community] = CONFIG.CYBER_PALETTE[colorIdx % CONFIG.CYBER_PALETTE.length];
                colorIdx++;
            }
            node.color = rootColors[node.community];
        });

        this.graph.nodeColor(n => n.color).nodeVal(n => n.prScore ? n.prScore * 800 : 1);
        this.refreshFilters();
    }

    renderPath(pathArr) {
        this.highlightNodes.clear();
        this.highlightLinks.clear();
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
        this.refreshFilters();
        this.graph.zoomToFit(1000);
    }

    refreshFilters() {
        this.graph
            .nodeVisibility(this.graph.nodeVisibility())
            .linkVisibility(this.graph.linkVisibility())
            .linkWidth(this.graph.linkWidth())
            .linkColor(this.graph.linkColor())
            .linkDirectionalParticles(this.graph.linkDirectionalParticles());
    }
}