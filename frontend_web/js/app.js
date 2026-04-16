// js/app.js
import { APIService } from './api.js';
import { Engine3D } from './graphEngine.js';

class AppController {
    constructor() {
        this.engine = new Engine3D('graph');
        this.globalGraphData = null;
        this.bindEvents();
    }

    bindEvents() {
        document.getElementById('btn-load').addEventListener('click', () => this.handleLoadFullSystem());
        document.getElementById('btn-path').addEventListener('click', () => this.handleShortestPath());
        document.getElementById('btn-reset').addEventListener('click', () => this.engine.reset());

        document.getElementById('btn-toggle-links').addEventListener('click', (e) => {
            const isShowing = this.engine.toggleLinks();
            e.target.innerHTML = isShowing ? "⚠️ 显示全网连线 (极度吃性能)" : "👁️ 隐藏全网连线 (极度流畅)";
            e.target.className = isShowing ? "" : "btn-danger";
        });

        // 力场滑块绑定
        document.getElementById('ctrl-repel').addEventListener('input', (e) => this.handleForceChange());
        document.getElementById('ctrl-link').addEventListener('input', (e) => this.handleForceChange());
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

    hideLoading() {
        document.getElementById('loading-screen').style.display = 'none';
    }

    async handleLoadFullSystem() {
        this.showLoading("1/4 正在向 FastAPI 调取底层拓扑...");
        try {
            const res = await APIService.getFullGraph();
            if (res.status === 'success') {
                this.globalGraphData = res;
                this.engine.loadData({ nodes: res.nodes, links: res.links });
                document.getElementById('stat-nodes').innerText = res.nodes.length;
                document.getElementById('stat-edges').innerText = res.links.length;

                this.showLoading("2/4 正在执行 PageRank 评估...");
                const prData = await APIService.getPageRank();

                this.showLoading("3/4 正在执行 LPA 社区裂变...");
                const commData = await APIService.getCommunity();
                
                // 🌟 超有仪式感的第 4 步！
                this.showLoading("4/4 正在向 3D 引擎注入视觉情报...");

                // 组装数据并注入引擎
                const prMap = {}; prData.data.forEach(item => prMap[item.node] = item.score);
                const commMap = {}; commData.data.forEach(item => commMap[item.node] = item.community);

                const degreeMap = {};
                this.globalGraphData.links.forEach(link => {
                    const src = link.source.id || link.source; const tgt = link.target.id || link.target;
                    degreeMap[src] = (degreeMap[src] || 0) + 1; degreeMap[tgt] = (degreeMap[tgt] || 0) + 1;
                });

                // 假装渲染需要时间，给个 500 毫秒的特效停顿，让装逼感拉满！
                setTimeout(() => {
                    this.engine.updateNodeVisuals(prMap, commMap, degreeMap);
                    this.updateRankList(prData.data);
                    this.hideLoading();
                }, 500);
            }
        } catch (error) {
            console.error(error);
            this.showLoading("🚨 致命错误：FastAPI 后端未启动或跨域拦截！");
            setTimeout(() => this.hideLoading(), 4000);
        }
    }

    updateRankList(rankData) {
        const list = document.getElementById('rank-list');
        list.innerHTML = '';
        rankData.sort((a, b) => b.score - a.score).slice(0, 15).forEach((item, index) => {
            const div = document.createElement('div');
            div.className = 'rank-item';
            div.innerHTML = `<span class="rank-id">TOP ${index + 1} <b>ID: ${item.node}</b></span> <span class="score">${(item.score * 100).toFixed(2)}</span>`;
            list.appendChild(div);
        });
    }

    async handleShortestPath() {
        const start = document.getElementById('s').value.trim();
        const target = document.getElementById('t').value.trim();
        if (!start || !target) return alert('请输入起点和终点ID！');

        const btn = document.getElementById('btn-path');
        btn.innerText = "⏳ 追踪中...";
        try {
            const data = await APIService.getShortestPath(start, target);
            if (data.status === 'success') {
                this.engine.renderPath(data.path);
                this.showHUD(data.path);
            } else {
                alert(`追踪失败: ${data.message || '未找到路径'}`);
                this.engine.reset();
            }
        } catch (err) {
            alert('通信异常，请检查 FastAPI 服务！');
        } finally {
            btn.innerText = "🎯 追踪最短通信链路";
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
} // <--- 注意，这里才是整个 AppController 类的真正闭合点！

// 网页加载完毕后启动总调度室
document.addEventListener('DOMContentLoaded', () => {
    window.app = new AppController();
});