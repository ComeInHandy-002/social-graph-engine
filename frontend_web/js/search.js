// js/search.js — 搜索模块
//
// 从全局图数据中搜索节点，支持键盘导航和防抖
//
// 导入: store (state.js)
// 导出: SearchManager 类
//
// 连接: app.js 初始化后调用 init(), 通过 store 获取 graphData

import { store } from './state.js';

export class SearchManager {
    constructor() {
        this.inputEl = null;
        this.resultsEl = null;
        this.selectedIdx = -1;
        this.debounceTimer = null;
        this.DEBOUNCE_MS = 300; // 300ms 防抖
        this.onSelectNode = null; // 选中节点后的回调
    }

    /**
     * 初始化搜索组件
     * @param {string} inputId - 搜索输入框 ID
     * @param {string} resultsId - 搜索结果容器 ID
     */
    init(inputId = 'global-search', resultsId = 'search-results') {
        this.inputEl = document.getElementById(inputId);
        this.resultsEl = document.getElementById(resultsId);

        if (!this.inputEl || !this.resultsEl) {
            console.warn('[SearchManager] 搜索 DOM 元素未找到');
            return;
        }

        this._bindEvents();
    }

    _bindEvents() {
        // 输入事件 (带防抖)
        this.inputEl.addEventListener('input', () => {
            clearTimeout(this.debounceTimer);
            this.debounceTimer = setTimeout(() => this._performSearch(), this.DEBOUNCE_MS);
        });

        // 键盘导航
        this.inputEl.addEventListener('keydown', (e) => this._handleKeyboard(e));

        // 点击选中
        this.resultsEl.addEventListener('click', (e) => {
            const item = e.target.closest('.search-result-item');
            if (item) {
                const id = item.dataset.id;
                this._selectResult(id);
            }
        });

        // 点击外部关闭
        document.addEventListener('click', (e) => {
            if (!this.inputEl.contains(e.target) && !this.resultsEl.contains(e.target)) {
                this.hide();
            }
        });

        // 订阅图数据变化
        store.on('globalGraphData', () => {
            this._performSearch(); // 数据更新后重新搜索
        });
    }

    _performSearch() {
        const query = this.inputEl.value.trim().toLowerCase();
        const graphData = store.get('globalGraphData');

        if (!query || !graphData) {
            this.hide();
            return;
        }

        // 使用 requestIdleCallback 避免阻塞主线程
        const doSearch = () => {
            const matches = graphData.nodes
                .filter(n => n.id.toLowerCase().includes(query))
                .slice(0, 20);

            store.set('searchQuery', query);
            store.set('searchResults', matches);

            if (matches.length === 0) {
                this.hide();
                return;
            }

            this.renderResults(matches);
            this.selectedIdx = 0;
        };

        if (window.requestIdleCallback) {
            requestIdleCallback(doSearch, { timeout: 100 });
        } else {
            setTimeout(doSearch, 0);
        }
    }

    renderResults(matches) {
        if (!this.resultsEl) return;

        this.resultsEl.innerHTML = matches.map((n, i) => `
            <div class="search-result-item ${i === 0 ? 'active' : ''}"
                 data-id="${n.id}"
                 role="option"
                 aria-selected="${i === 0 ? 'true' : 'false'}">
                <span class="sr-id">ID: ${n.id}</span>
                <span class="sr-info">社群:${n.community || '-'} | 度:${n.degree || 0} | PR:${n.prScore ? (n.prScore * 100).toFixed(1) : 0}%</span>
            </div>
        `).join('');

        this.resultsEl.style.display = 'block';
        this.resultsEl.setAttribute('role', 'listbox');
    }

    _handleKeyboard(e) {
        const items = this.resultsEl.querySelectorAll('.search-result-item');
        if (items.length === 0) return;

        switch (e.key) {
            case 'ArrowDown':
                e.preventDefault();
                this.selectedIdx = Math.min(this.selectedIdx + 1, items.length - 1);
                this._updateSelection(items);
                break;

            case 'ArrowUp':
                e.preventDefault();
                this.selectedIdx = Math.max(this.selectedIdx - 1, 0);
                this._updateSelection(items);
                break;

            case 'Enter':
                e.preventDefault();
                if (items[this.selectedIdx]) {
                    const id = items[this.selectedIdx].dataset.id;
                    this._selectResult(id);
                }
                break;

            case 'Escape':
                this.hide();
                this.inputEl.value = '';
                break;
        }
    }

    _updateSelection(items) {
        items.forEach((el, i) => {
            const isActive = i === this.selectedIdx;
            el.classList.toggle('active', isActive);
            el.setAttribute('aria-selected', isActive ? 'true' : 'false');
        });
        // 滚动到可见区域
        const active = items[this.selectedIdx];
        if (active) active.scrollIntoView({ block: 'nearest' });
    }

    _selectResult(nodeId) {
        this.hide();
        this.inputEl.value = '';
        store.set('searchQuery', '');

        if (this.onSelectNode) {
            this.onSelectNode(nodeId);
        }
    }

    hide() {
        if (this.resultsEl) {
            this.resultsEl.style.display = 'none';
            this.resultsEl.innerHTML = '';
        }
        this.selectedIdx = -1;
    }

    focus() {
        if (this.inputEl) this.inputEl.focus();
    }

    destroy() {
        clearTimeout(this.debounceTimer);
        this.hide();
        // 事件监听器通过 DOM 移除自动清理
    }
}
