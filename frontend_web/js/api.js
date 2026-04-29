// js/api.js
import { CONFIG } from './config.js';

export class APIService {
    static async request(endpoint, options = {}) {
        try {
            const response = await fetch(`${CONFIG.API_BASE_URL}${endpoint}`, options);
            if (!response.ok) throw new Error(`HTTP 状态码异常: ${response.status}`);
            return await response.json();
        } catch (error) {
            console.error(`[网络层异常] 请求 ${endpoint} 失败:`, error);
            throw error;
        }
    }

    static async getFullGraph() {
        return this.request('/all');
    }

    static async getPageRank() {
        return this.request('/pagerank');
    }

    static async getCommunity() {
        return this.request('/community');
    }

    // 注意：最短路径是 POST 请求
    static async getShortestPath(startNode, targetNode, algorithm = 'bfs') {
        return this.request('/shortest_path', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            // 🌟 把算法类型发给后端
            body: JSON.stringify({ start_node: startNode, target_node: targetNode, algorithm: algorithm })
        });
    }
}