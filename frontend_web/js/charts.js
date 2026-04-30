// js/charts.js
export class ChartDashboard {
    constructor() {
        this.charts = {};
        this.visible = false;
        this.initialized = false;
    }

    init(container) {
        if (this.initialized) return true;
        if (!window.Chart) { console.error("Chart.js 未加载！"); return false; }

        this.container = container;
        container.style.display = 'block';
        container.offsetHeight; // 强制回流

        this._makeChart('degree', 'chart-degree', 'bar', '度数分布');
        this._makeChart('community', 'chart-community', 'doughnut', '社区分布');
        this._makeChart('pagerank', 'chart-pagerank-bar', 'bar', '影响力 Top 20', true);
        this._makeChart('timing', 'chart-timing', 'bar', '算法性能对比');
        this.initialized = true;
        return true;
    }

    _makeChart(key, canvasId, type, title, horizontal = false) {
        const ctx = document.getElementById(canvasId);
        if (!ctx) return;

        // 销毁同 key 的旧图表
        if (this.charts[key]) { this.charts[key].destroy(); this.charts[key] = null; }

        const plugins = {
            legend: type === 'doughnut'
                ? { position: 'right', labels: { color: '#aaa', font: { size: 9 }, padding: 8 } }
                : { display: false },
            title: { display: true, text: title, color: '#00ff88', font: { size: 14 } }
        };

        const scales = (type === 'doughnut') ? {} : {
            x: { ticks: { color: '#888' }, grid: { color: 'rgba(255,255,255,0.05)' } },
            y: { ticks: { color: '#888' }, grid: { color: 'rgba(255,255,255,0.05)' } }
        };

        const options = {
            responsive: true,
            maintainAspectRatio: false,
            indexAxis: horizontal ? 'y' : 'x',
            plugins,
            scales
        };

        this.charts[key] = new window.Chart(ctx, {
            type,
            data: { labels: [], datasets: [{ data: [], backgroundColor: 'rgba(0,255,136,0.4)', borderColor: '#00ff88', borderWidth: 1 }] },
            options
        });
    }

    // ------ 数据更新 ------

    updateDegreeDistribution(degreeMap) {
        const c = this.charts.degree; if (!c) return;
        const buckets = [0, 5, 10, 20, 50, 100, 200, 500, 1000, 5000];
        const counts = new Array(buckets.length).fill(0);
        for (const deg of Object.values(degreeMap)) {
            for (let i = buckets.length - 1; i >= 0; i--) { if (deg >= buckets[i]) { counts[i]++; break; } }
        }
        const filtered = buckets.map((b, i) => ({ label: i < buckets.length - 1 ? `${b}-${buckets[i + 1] - 1}` : `≥${b}`, count: counts[i] })).filter(x => x.count > 0);
        c.data.labels = filtered.map(x => x.label);
        c.data.datasets[0].data = filtered.map(x => x.count);
        c.data.datasets[0].backgroundColor = 'rgba(0,255,136,0.4)';
        c.data.datasets[0].borderColor = '#00ff88';
        c.update();
    }

    updateCommunityDistribution(communityMap) {
        const c = this.charts.community; if (!c) return;
        const counts = {};
        for (const comm of Object.values(communityMap)) { counts[comm] = (counts[comm] || 0) + 1; }
        const sorted = Object.entries(counts).sort((a, b) => b[1] - a[1]).slice(0, 10);
        c.data.labels = sorted.map(([name, n]) => `${name}(${n})`);
        c.data.datasets[0].data = sorted.map(([, n]) => n);
        c.data.datasets[0].backgroundColor = ['#ff0055', '#00ff88', '#0088ff', '#ffaa00', '#aa00ff', '#00ffff', '#ffff00', '#ff00aa', '#ff5500', '#55ff00'];
        c.update();
    }

    updatePageRankBars(prData) {
        const c = this.charts.pagerank; if (!c || !Array.isArray(prData)) return;
        const sorted = [...prData].sort((a, b) => b.score - a.score).slice(0, 20);
        c.data.labels = sorted.map(x => `ID ${x.node}`);
        c.data.datasets[0].data = sorted.map(x => +(x.score * 100).toFixed(2));
        c.data.datasets[0].backgroundColor = 'rgba(0,136,255,0.5)';
        c.data.datasets[0].borderColor = '#0088ff';
        c.update();
    }

    updateTimingComparison(timingData) {
        const c = this.charts.timing; if (!c) return;
        const entries = Object.entries(timingData);
        c.data.labels = entries.map(([k]) => k);
        c.data.datasets[0].data = entries.map(([, v]) => v);
        c.data.datasets[0].backgroundColor = ['rgba(0,255,136,0.4)', 'rgba(0,136,255,0.4)', 'rgba(170,0,255,0.4)', 'rgba(255,170,0,0.4)', 'rgba(255,0,85,0.4)', 'rgba(0,255,255,0.4)', 'rgba(255,255,0,0.4)', 'rgba(255,0,255,0.4)'];
        c.update();
    }

    hide() { if (this.container) this.container.style.display = 'none'; this.visible = false; }
    show() { if (this.container) this.container.style.display = 'block'; this.visible = true; }
}
