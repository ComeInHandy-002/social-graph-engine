// js/ranking.js — 排行榜模块
//
// 根据选中的度量指标动态渲染排行榜，支持多种算法结果
//
// 导入: store (state.js)
// 导出: RankingManager 类
//
// 连接: app.js 在加载数据和切换指标时调用 refresh()

import { store } from './state.js';

export class RankingManager {
    constructor() {
        this.listEl = null;
        this.metricSelect = null;
        this.onSelectItem = null; // 选中排名项的回调
    }

    init(listId = 'rank-list', metricSelectId = 'ranking-metric') {
        this.listEl = document.getElementById(listId);
        this.metricSelect = document.getElementById(metricSelectId);

        if (this.metricSelect) {
            this.metricSelect.addEventListener('change', () => {
                store.set('rankingMetric', this.metricSelect.value);
                this.refresh();
            });
        }

        // 订阅指标变化
        store.on('rankingMetric', () => this.refresh());

        // 订阅算法结果变化
        store.on('algorithmResults', () => this.refresh());
    }

    /**
     * 刷新排行榜
     */
    refresh() {
        if (!this.listEl) return;

        const metric = store.get('rankingMetric');
        const results = store.get('algorithmResults');
        let items = [];

        switch (metric) {
            case 'pagerank':
                items = this._buildItems(results.pagerank?.data, 'score', 'PR', 15, true);
                break;
            case 'betweenness':
                items = this._buildItems(results.betweenness?.data, 'score', 'BC', 15, false);
                break;
            case 'kcore':
                items = this._buildItems(results.kcore?.data, 'coreness', 'KC', 15, false, true);
                break;
            case 'clustering':
                items = this._buildItems(results.clustering_coeff?.data, 'coefficient', 'CC', 15, false);
                break;
            case 'pagerank_combined':
                items = this._buildItems(results.pagerank?.data, 'score', 'PR', 15, true);
                break;
            default:
                items = [];
        }

        store.set('rankings', items);
        this.render(items);
    }

    /**
     * 从算法结果构建排行项
     * @param {Array} data - 算法结果数据
     * @param {string} field - 排序字段
     * @param {string} label - 显示标签
     * @param {number} limit - 显示数量
     * @param {boolean} isPercent - 是否百分比显示
     * @param {boolean} round - 是否取整
     */
    _buildItems(data, field, label, limit, isPercent = false, round = false) {
        if (!Array.isArray(data)) return [];
        return [...data]
            .sort((a, b) => (b[field] || 0) - (a[field] || 0))
            .slice(0, limit)
            .map(item => ({
                id: item.node || item.id,
                val: isPercent
                    ? ((item[field] || 0) * 100).toFixed(2)
                    : round
                        ? Math.round(item[field] || 0).toString()
                        : (item[field] || 0).toFixed(round ? 0 : 4),
                label
            }));
    }

    /**
     * 渲染排行榜 HTML
     */
    render(items) {
        if (!this.listEl) return;

        if (items.length === 0) {
            this.listEl.innerHTML = `
                <div class="text-center text-muted" style="margin-top:10px; font-size:12px;">
                    等待载入...
                </div>`;
            return;
        }

        this.listEl.innerHTML = items.map((item, index) => `
            <div class="rank-item"
                 role="button"
                 tabindex="0"
                 aria-label="排名第 ${index + 1}, 节点 ID ${item.id}, ${item.label} 值 ${item.val}"
                 data-node-id="${item.id}">
                <span class="rank-id">TOP ${index + 1} <b>ID: ${item.id}</b></span>
                <span class="rank-score">${item.val}</span>
            </div>
        `).join('');

        // 绑定点击事件 (使用事件委托)
        this.listEl.querySelectorAll('.rank-item').forEach(el => {
            el.addEventListener('click', () => {
                const nodeId = el.dataset.nodeId;
                if (this.onSelectItem && nodeId) {
                    this.onSelectItem(nodeId);
                }
            });

            // 键盘可访问
            el.addEventListener('keydown', (e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    const nodeId = el.dataset.nodeId;
                    if (this.onSelectItem && nodeId) {
                        this.onSelectItem(nodeId);
                    }
                }
            });
        });
    }

    /** 获取当前排行项的节点 ID 数组 */
    getRankedNodeIds() {
        const rankings = store.get('rankings');
        return rankings.map(r => r.id);
    }
}
