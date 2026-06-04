// js/state.js — 集中式事件驱动状态管理
//
// 设计原则:
//   - 单例 Store, 全局共享状态
//   - 发布/订阅模式: set() 触发注册的监听器
//   - 不可变更新: 所有修改通过 set()/update() 完成
//   - 支持序列化/反序列化 (localStorage 持久化)
//
// 导出:
//   - store (单例)
//   - Store 类 (测试用)

export class Store {
    constructor(initialState = {}) {
        this._state = { ...initialState };
        this._listeners = {};     // key -> Set<callback>
        this._globalListeners = new Set(); // 所有变更都触发
        this._frozen = false;
    }

    // ---- 基础操作 ----

    /** 获取当前状态快照 (返回新对象, 不可直接修改) */
    get(key) {
        if (key === undefined) return { ...this._state };
        return this._state[key];
    }

    /** 设置单个 key 的值, 触发该 key 和 global 的监听器 */
    set(key, value) {
        if (this._frozen) return;
        const oldValue = this._state[key];
        if (oldValue === value) return; // 相同值跳过

        this._state[key] = value;

        // 触发 key 特定监听器
        const callbacks = this._listeners[key];
        if (callbacks) {
            callbacks.forEach(fn => {
                try { fn(value, oldValue, key); }
                catch (e) { console.error(`[Store] 监听器异常 (${key}):`, e); }
            });
        }

        // 触发全局监听器
        this._globalListeners.forEach(fn => {
            try { fn(key, value, oldValue); }
            catch (e) { console.error('[Store] 全局监听器异常:', e); }
        });
    }

    /** 批量更新多个 key, 仅触发一次通知 */
    batch(updates) {
        if (this._frozen) return;
        const changes = [];
        for (const [key, value] of Object.entries(updates)) {
            const oldValue = this._state[key];
            if (oldValue !== value) {
                this._state[key] = value;
                changes.push({ key, value, oldValue });
            }
        }

        // 批量触发
        for (const { key, value, oldValue } of changes) {
            const callbacks = this._listeners[key];
            if (callbacks) {
                callbacks.forEach(fn => {
                    try { fn(value, oldValue, key); }
                    catch (e) { console.error(`[Store] 监听器异常 (${key}):`, e); }
                });
            }
        }

        // 全局通知仅一次
        if (changes.length > 0) {
            this._globalListeners.forEach(fn => {
                try { fn('__batch__', changes, null); }
                catch (e) { console.error('[Store] 全局监听器异常:', e); }
            });
        }
    }

    /** 通过 updater 函数更新某个 key (函数式更新) */
    update(key, updater) {
        const current = this._state[key];
        const next = updater(current);
        this.set(key, next);
    }

    // ---- 订阅/取消 ----

    /** 订阅某个 key 的变化 */
    on(key, callback) {
        if (!this._listeners[key]) {
            this._listeners[key] = new Set();
        }
        this._listeners[key].add(callback);

        // 返回取消订阅函数
        return () => this.off(key, callback);
    }

    /** 取消订阅 */
    off(key, callback) {
        const callbacks = this._listeners[key];
        if (callbacks) {
            callbacks.delete(callback);
            if (callbacks.size === 0) delete this._listeners[key];
        }
    }

    /** 订阅所有状态变更 */
    onAny(callback) {
        this._globalListeners.add(callback);
        return () => this._globalListeners.delete(callback);
    }

    /** 一次性订阅 (触发后自动取消) */
    once(key, callback) {
        const wrapper = (value, oldValue, k) => {
            this.off(key, wrapper);
            callback(value, oldValue, k);
        };
        this.on(key, wrapper);
    }

    // ---- 工具 ----

    /** 冻结状态 (暂停所有通知) */
    freeze() { this._frozen = true; }

    /** 解冻并触发 pending 通知 */
    unfreeze() { this._frozen = false; }

    /** 重置为初始状态 */
    reset(initialState = {}) {
        this._state = { ...initialState };
        this._listeners = {};
        this._globalListeners = new Set();
        this._frozen = false;
    }

    /** 导出快照 (用于持久化) */
    snapshot() {
        return JSON.parse(JSON.stringify(this._state));
    }

    /** 调试: 获取监听器数量 */
    debugInfo() {
        let count = 0;
        for (const set of Object.values(this._listeners)) count += set.size;
        return {
            keys: Object.keys(this._state).length,
            listeners: count,
            globalListeners: this._globalListeners.size,
            frozen: this._frozen
        };
    }
}


// ============================================================
// 默认状态形状
// ============================================================

const DEFAULT_STATE = {
    // 算法
    currentAlgorithm: 'pagerank',
    algorithmResult: null,
    algorithmResults: {},
    algorithmTiming: {},

    // 图数据
    globalGraphData: null,
    graphLoaded: false,

    // 选中节点 & 邻居
    selectedNode: null,
    startNode: null,
    targetNode: null,
    neighbors: [],
    focusNode: null,

    // 搜索
    searchQuery: '',
    searchResults: [],

    // 排行榜
    rankingMetric: 'pagerank',
    rankings: [],

    // 时间轴 (Big Bang)
    timelineStep: 1,
    timelineMax: 100,
    isPlaying: false,
    timelineVisible: false,

    // UI 状态
    uiState: {
        loading: false,
        loadingText: '系统休眠中...',
        loadingProgress: '',
        activePanel: null,       // 'dashboard' | 'shortcuts' | 'radar' | null
        toasts: [],
        legendVisible: false,
        linksVisible: false
    },

    // WebSocket
    wsConnected: false,

    // 力场参数
    forceRepel: 30,
    forceLink: 30
};


// ============================================================
// 单例导出
// ============================================================

export const store = new Store(DEFAULT_STATE);

// 挂载到 window 方便在面板 HTML 的 onclick 中访问
if (typeof window !== 'undefined') {
    window.__store = store;
}
