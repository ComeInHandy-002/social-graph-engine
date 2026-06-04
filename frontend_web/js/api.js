// js/api.js — API 客户端 (增强版)
//
// 功能:
//   - HTTP 请求封装 (基于 Fetch)
//   - 内存缓存 (TTL 可配置)
//   - 请求去重 (相同请求不重复发出)
//   - AbortController 取消支持
//   - 自动重试 (指数退避)
//
// 导入: CONFIG (config.js)
// 导出: APIService 类 (全静态方法)
//
// 连接: app.js 通过 APIService 调用后端接口

import { CONFIG } from './config.js';

// ---- 内存缓存 ----
const cache = new Map();

// ---- 请求去重: 正在进行中的请求 ----
const pendingRequests = new Map();

// ---- 当前活跃的 AbortController ----
let activeControllers = [];


export class APIService {
    // ============================================================
    // 配置
    // ============================================================

    static CACHE_TTL = {
        default: 3600000,       // 1 小时
        topology: 3600000,
        pagerank: 86400000,     // 24 小时
        community: 86400000,
        betweenness: 3600000,
        kcore: 3600000,
        clustering_coeff: 3600000,
        stats: 86400000,
        connected_components: 3600000,
        shortest_path: 0,       // 路径不缓存
    };

    static MAX_RETRIES = 2;
    static RETRY_DELAY_MS = 1000;

    // ============================================================
    // 缓存管理
    // ============================================================

    /**
     * 获取缓存的响应
     * @returns {object|null}
     */
    static getCached(key) {
        const entry = cache.get(key);
        if (!entry) return null;
        if (Date.now() - entry.timestamp > entry.ttl) {
            cache.delete(key);
            return null;
        }
        return entry.data;
    }

    /**
     * 设置缓存
     * @param {string} key
     * @param {object} data
     * @param {number} ttl - 毫秒
     */
    static setCache(key, data, ttl) {
        cache.set(key, {
            data,
            timestamp: Date.now(),
            ttl
        });
    }

    /**
     * 清除所有缓存
     */
    static clearCache() {
        cache.clear();
    }

    /**
     * 清除特定 endpoint 的缓存
     */
    static invalidateCache(endpoint) {
        cache.delete(endpoint);
    }

    // ============================================================
    // 请求去重
    // ============================================================

    /**
     * 获取或创建 pending request (去重)
     */
    static _deduplicate(key, requestFn) {
        if (pendingRequests.has(key)) {
            return pendingRequests.get(key);
        }

        const promise = requestFn()
            .then(result => {
                pendingRequests.delete(key);
                return result;
            })
            .catch(err => {
                pendingRequests.delete(key);
                throw err;
            });

        pendingRequests.set(key, promise);
        return promise;
    }

    // ============================================================
    // 核心请求方法
    // ============================================================

    /**
     * 发起 API 请求 (带缓存、去重、重试、取消支持)
     *
     * @param {string} endpoint - API 路径 (例如 '/all')
     * @param {object} options - Fetch options
     * @param {object} requestOptions
     * @param {boolean} [requestOptions.cache=true] - 是否使用缓存
     * @param {number}  [requestOptions.cacheTTL] - 自定义 TTL (ms)
     * @param {boolean} [requestOptions.deduplicate=true] - 是否去重
     * @param {AbortSignal} [requestOptions.signal] - 外部 AbortSignal
     * @returns {Promise<object>}
     */
    static async request(endpoint, options = {}, {
        cache: useCache = true,
        cacheTTL = null,
        deduplicate = true,
        signal = null
    } = {}) {
        const url = `${CONFIG.API_BASE_URL}${endpoint}`;
        const cacheKey = endpoint;

        // 1. 缓存命中
        if (useCache) {
            const cached = this.getCached(cacheKey);
            if (cached) return cached;
        }

        // 2. 请求去重
        const doRequest = async (retrySignal) => {
            const controller = new AbortController();
            const finalSignal = retrySignal || signal || controller.signal;

            // 跟踪活跃请求
            activeControllers.push(controller);

            let lastError = null;

            for (let attempt = 0; attempt <= this.MAX_RETRIES; attempt++) {
                try {
                    const response = await fetch(url, {
                        ...options,
                        signal: finalSignal
                    });

                    if (!response.ok) {
                        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
                    }

                    const data = await response.json();

                    // 移除 controller 跟踪
                    activeControllers = activeControllers.filter(c => c !== controller);

                    // 存入缓存
                    if (useCache) {
                        const ttl = cacheTTL || this.CACHE_TTL[endpoint.replace(/^\//, '')] || this.CACHE_TTL.default;
                        if (ttl > 0) {
                            this.setCache(cacheKey, data, ttl);
                        }
                    }

                    return data;

                } catch (error) {
                    // 如果是取消请求，不重试
                    if (error.name === 'AbortError') {
                        activeControllers = activeControllers.filter(c => c !== controller);
                        throw error;
                    }

                    lastError = error;

                    // 指数退避重试
                    if (attempt < this.MAX_RETRIES) {
                        const delay = this.RETRY_DELAY_MS * Math.pow(2, attempt);
                        console.warn(`[API] 请求 ${endpoint} 失败, ${delay}ms 后重试 (${attempt + 1}/${this.MAX_RETRIES}):`, error.message);
                        await new Promise(resolve => setTimeout(resolve, delay));
                    }
                }
            }

            activeControllers = activeControllers.filter(c => c !== controller);
            throw lastError;
        };

        if (deduplicate) {
            return this._deduplicate(cacheKey, () => doRequest());
        }

        return doRequest();
    }

    // ============================================================
    // 取消所有活跃请求
    // ============================================================

    static cancelAll() {
        activeControllers.forEach(c => {
            try { c.abort(); } catch (e) { /* ignore */ }
        });
        activeControllers = [];
        pendingRequests.clear();
    }

    // ============================================================
    // 业务 API 方法
    // ============================================================

    /** 获取完整图数据 (拓扑) */
    static async getFullGraph() {
        return this.request('/all');
    }

    /** PageRank 计算 */
    static async getPageRank() {
        return this.request('/pagerank');
    }

    /** 社区发现 (LPA) */
    static async getCommunity() {
        return this.request('/community');
    }

    /** Betweenness 中心性 */
    static async getBetweenness() {
        return this.request('/betweenness');
    }

    /** K-Core 核心度 */
    static async getKCore() {
        return this.request('/kcore');
    }

    /** 聚类系数 */
    static async getClusteringCoeff() {
        return this.request('/clustering_coeff');
    }

    /** 连通分量 */
    static async getConnectedComponents() {
        return this.request('/connected_components');
    }

    /** 图统计信息 */
    static async getGraphStats() {
        return this.request('/stats');
    }

    /** 健康检查 */
    static async checkHealth() {
        return fetch(`${CONFIG.API_BASE_URL}/../health`).then(r => r.json());
    }

    /** 路径查找 (不缓存) */
    static async getShortestPath(startNode, targetNode, algorithm = 'bfs') {
        return this.request('/shortest_path', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                start_node: startNode,
                target_node: targetNode,
                algorithm: algorithm
            })
        }, { cache: false, deduplicate: false });
    }

    /** 数据导出 */
    static async exportData(dataType, format = 'csv') {
        const url = `${CONFIG.API_BASE_URL}/export/${dataType}?format=${format}`;
        const controller = new AbortController();

        const response = await fetch(url, { signal: controller.signal });

        if (!response.ok) {
            throw new Error(`导出失败: HTTP ${response.status}`);
        }

        if (format === 'csv') {
            const blob = await response.blob();
            this._downloadBlob(blob, `${dataType}.csv`);
        } else {
            const data = await response.json();
            const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
            this._downloadBlob(blob, `${dataType}.json`);
        }
    }

    /** 批量获取多个端点 */
    static async batchRequest(endpoints) {
        const results = await Promise.allSettled(
            endpoints.map(ep => this.request(ep))
        );

        return results.map((result, i) => ({
            endpoint: endpoints[i],
            success: result.status === 'fulfilled',
            data: result.status === 'fulfilled' ? result.value : null,
            error: result.status === 'rejected' ? result.reason.message : null
        }));
    }

    // ============================================================
    // 工具
    // ============================================================

    static _downloadBlob(blob, filename) {
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
    }
}
