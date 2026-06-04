// js/charts.js — 统计仪表板 (增强版)
//
// 功能:
//   - Chart.js 图表封装 (度数分布、社区分布、PageRank、性能对比)
//   - 显示/隐藏控制
//   - 数据表格后备 (无障碍)
//   - 图表 ARIA 描述更新
//
// 导入: 无 (纯 DOM / Chart.js 全局)
// 导出: ChartDashboard 类
//
// 连接: app.js 在加载数据后调用 update*() 方法

export class ChartDashboard {
    constructor() {
        this.charts = {};          // 图表实例映射
        this.dataTables = {};      // 数据表格映射 (无障碍后备)
        this.visible = false;
        this.initialized = false;
        this.container = null;
    }

    /**
     * 初始化仪表板 (仅在第一次显示时调用)
     * @param {HTMLElement} container - 仪表板容器元素
     * @returns {boolean} 是否初始化成功
     */
    init(container) {
        if (this.initialized) return true;
        if (!window.Chart) {
            console.error('[ChartDashboard] Chart.js 未加载!');
            return false;
        }

        this.container = container;
        container.style.display = 'block';
        container.offsetHeight; // 强制回流, 确保 canvas 正确渲染

        // 创建 4 个图表
        this._makeChart('degree', 'chart-degree', 'bar', '度数分布', false);
        this._makeChart('community', 'chart-community', 'doughnut', '社区分布', false);
        this._makeChart('pagerank', 'chart-pagerank-bar', 'bar', '影响力 Top 20', true);
        this._makeChart('timing', 'chart-timing', 'bar', '算法性能对比', false);

        // 创建无障碍数据表格
        this._createDataTables();

        this.initialized = true;
        return true;
    }

    /**
     * 创建单个 Chart.js 图表
     * @param {string} key - 内部标识
     * @param {string} canvasId - Canvas 元素 ID
     * @param {string} type - Chart.js 类型
     * @param {string} title - 图表标题
     * @param {boolean} horizontal - 是否水平布局
     */
    _makeChart(key, canvasId, type, title, horizontal = false) {
        const ctx = document.getElementById(canvasId);
        if (!ctx) return;

        // 设置 canvas 的 ARIA 标签
        ctx.setAttribute('role', 'img');
        ctx.setAttribute('aria-label', `${title}图表`);

        // 销毁同 key 旧图表
        if (this.charts[key]) {
            this.charts[key].destroy();
            this.charts[key] = null;
        }

        const plugins = {
            legend: type === 'doughnut'
                ? {
                    position: 'right',
                    labels: {
                        color: '#aaa',
                        font: { size: 9 },
                        padding: 8,
                        generateLabels: (chart) => {
                        const data = chart.data;
                        return data.labels.map((label, i) => ({
                            text: label,
                            fillStyle: data.datasets[0].backgroundColor[i] || '#00ff88',
                            hidden: false,
                            index: i,
                            strokeStyle: '#fff',
                            lineWidth: 0
                        }));
                    }
                    }
                }
                : { display: false },
            title: {
                display: true,
                text: title,
                color: '#00ff88',
                font: { size: 14, family: "'Segoe UI', sans-serif" }
            }
        };

        const scales = (type === 'doughnut') ? {} : {
            x: {
                ticks: { color: '#888', font: { size: 10 } },
                grid: { color: 'rgba(255,255,255,0.05)' }
            },
            y: {
                ticks: { color: '#888', font: { size: 10 } },
                grid: { color: 'rgba(255,255,255,0.05)' }
            }
        };

        const options = {
            responsive: true,
            maintainAspectRatio: false,
            indexAxis: horizontal ? 'y' : 'x',
            animation: this._respectsReducedMotion() ? false : { duration: 800 },
            plugins,
            scales
        };

        this.charts[key] = new window.Chart(ctx, {
            type,
            data: {
                labels: ['等待数据...'],
                datasets: [{
                    data: [0],
                    backgroundColor: 'rgba(0,255,136,0.4)',
                    borderColor: '#00ff88',
                    borderWidth: 1
                }]
            },
            options
        });
    }

    // ============================================================
    // 无障碍数据表格 (屏幕阅读器后备)
    // ============================================================

    _createDataTables() {
        if (!this.container) return;
        const tableContainer = document.createElement('div');
        tableContainer.id = 'chart-data-tables';
        tableContainer.className = 'sr-only';
        tableContainer.setAttribute('aria-hidden', 'true');
        this.container.appendChild(tableContainer);
        this.dataTables.container = tableContainer;
    }

    /**
     * 更新无障碍数据表格
     * @param {string} chartKey - 图表 key
     * @param {string} caption - 表格标题
     * @param {Array<{label:string, value:*}>} rows - 数据行
     */
    _updateDataTable(chartKey, caption, rows) {
        if (!this.dataTables.container) return;

        let tableEl = this.dataTables[chartKey];
        if (!tableEl) {
            tableEl = document.createElement('table');
            const cap = document.createElement('caption');
            cap.textContent = caption;
            tableEl.appendChild(cap);
            this.dataTables.container.appendChild(tableEl);
            this.dataTables[chartKey] = tableEl;
        } else {
            tableEl.innerHTML = '';
            const cap = document.createElement('caption');
            cap.textContent = caption;
            tableEl.appendChild(cap);
        }

        const thead = document.createElement('thead');
        thead.innerHTML = '<tr><th scope="col">项目</th><th scope="col">数值</th></tr>';
        tableEl.appendChild(thead);

        const tbody = document.createElement('tbody');
        rows.forEach(row => {
            const tr = document.createElement('tr');
            tr.innerHTML = `<td>${row.label}</td><td>${row.value}</td>`;
            tbody.appendChild(tr);
        });
        tableEl.appendChild(tbody);
    }

    // ============================================================
    // 数据更新方法
    // ============================================================

    /** 更新度数分布图 */
    updateDegreeDistribution(degreeMap) {
        const c = this.charts.degree;
        if (!c) return;

        // 分桶统计
        const buckets = [0, 5, 10, 20, 50, 100, 200, 500, 1000, 5000];
        const counts = new Array(buckets.length).fill(0);

        for (const deg of Object.values(degreeMap)) {
            for (let i = buckets.length - 1; i >= 0; i--) {
                if (deg >= buckets[i]) { counts[i]++; break; }
            }
        }

        const filtered = buckets
            .map((b, i) => ({
                label: i < buckets.length - 1 ? `${b}-${buckets[i + 1] - 1}` : `>=${b}`,
                count: counts[i]
            }))
            .filter(x => x.count > 0);

        c.data.labels = filtered.map(x => x.label);
        c.data.datasets[0].data = filtered.map(x => x.count);
        c.data.datasets[0].backgroundColor = 'rgba(0,255,136,0.4)';
        c.data.datasets[0].borderColor = '#00ff88';
        c.update();

        // 无障碍表格
        this._updateDataTable('degree', '度数分布数据表', filtered.map(x => ({
            label: x.label,
            value: `${x.count} 个节点`
        })));
    }

    /** 更新社区分布图 */
    updateCommunityDistribution(communityMap) {
        const c = this.charts.community;
        if (!c) return;

        const counts = {};
        for (const comm of Object.values(communityMap)) {
            counts[comm] = (counts[comm] || 0) + 1;
        }

        const sorted = Object.entries(counts)
            .sort((a, b) => b[1] - a[1])
            .slice(0, 10);

        const colors = ['#ff0055', '#00ff88', '#0088ff', '#ffaa00', '#aa00ff',
                        '#00ffff', '#ffff00', '#ff00aa', '#ff5500', '#55ff00'];

        c.data.labels = sorted.map(([name, n]) => `${name} (${n})`);
        c.data.datasets[0].data = sorted.map(([, n]) => n);
        c.data.datasets[0].backgroundColor = colors.slice(0, sorted.length);
        c.update();

        this._updateDataTable('community', '社区分布数据表', sorted.map(([name, n]) => ({
            label: name,
            value: `${n} 个节点`
        })));
    }

    /** 更新 PageRank 柱状图 */
    updatePageRankBars(prData) {
        const c = this.charts.pagerank;
        if (!c || !Array.isArray(prData)) return;

        const sorted = [...prData]
            .sort((a, b) => (b.score || 0) - (a.score || 0))
            .slice(0, 20);

        c.data.labels = sorted.map(x => `ID ${x.node || x.id}`);
        c.data.datasets[0].data = sorted.map(x => +((x.score || 0) * 100).toFixed(2));
        c.data.datasets[0].backgroundColor = 'rgba(0,136,255,0.5)';
        c.data.datasets[0].borderColor = '#0088ff';
        c.update();

        this._updateDataTable('pagerank', 'PageRank 排行榜数据表', sorted.map(x => ({
            label: `节点 ${x.node || x.id}`,
            value: `${+((x.score || 0) * 100).toFixed(2)}%`
        })));
    }

    /** 更新算法性能对比图 */
    updateTimingComparison(timingData) {
        const c = this.charts.timing;
        if (!c) return;

        const entries = Object.entries(timingData);
        const colors = [
            'rgba(0,255,136,0.4)', 'rgba(0,136,255,0.4)', 'rgba(170,0,255,0.4)',
            'rgba(255,170,0,0.4)', 'rgba(255,0,85,0.4)', 'rgba(0,255,255,0.4)',
            'rgba(255,255,0,0.4)', 'rgba(255,0,255,0.4)'
        ];

        c.data.labels = entries.map(([k]) => k);
        c.data.datasets[0].data = entries.map(([, v]) => v);
        c.data.datasets[0].backgroundColor = entries.map((_, i) => colors[i % colors.length]);
        c.update();

        this._updateDataTable('timing', '算法性能数据表', entries.map(([k, v]) => ({
            label: k,
            value: `${v} ms`
        })));
    }

    // ============================================================
    // 显示控制
    // ============================================================

    show() {
        if (this.container) {
            this.container.style.display = 'flex';
            this.container.setAttribute('aria-hidden', 'false');
        }
        this.visible = true;

        // 重新调整图表大小
        Object.values(this.charts).forEach(c => {
            if (c && c.resize) c.resize();
        });
    }

    hide() {
        if (this.container) {
            this.container.style.display = 'none';
            this.container.setAttribute('aria-hidden', 'true');
        }
        this.visible = false;
    }

    // ============================================================
    // 工具
    // ============================================================

    /** 检查系统是否偏好减少动画 */
    _respectsReducedMotion() {
        return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    }

    /** 销毁所有图表 */
    destroy() {
        Object.values(this.charts).forEach(c => {
            try { c.destroy(); } catch (e) { /* ignore */ }
        });
        this.charts = {};
        this.dataTables = {};
        this.initialized = false;
        this.visible = false;
    }
}
