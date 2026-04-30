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

    static async getFullGraph() { return this.request('/all'); }
    static async getPageRank() { return this.request('/pagerank'); }
    static async getCommunity() { return this.request('/community'); }
    static async getBetweenness() { return this.request('/betweenness'); }
    static async getConnectedComponents() { return this.request('/connected_components'); }
    static async getKCore() { return this.request('/kcore'); }
    static async getClusteringCoeff() { return this.request('/clustering_coeff'); }
    static async getGraphStats() { return this.request('/stats'); }
    static async checkHealth() { return fetch(`${CONFIG.API_BASE_URL}/../health`).then(r => r.json()); }

    static async getShortestPath(startNode, targetNode, algorithm = 'bfs') {
        return this.request('/shortest_path', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ start_node: startNode, target_node: targetNode, algorithm: algorithm })
        });
    }

    static async exportData(dataType, format = 'csv') {
        const url = `${CONFIG.API_BASE_URL}/export/${dataType}?format=${format}`;
        const response = await fetch(url);
        if (!response.ok) throw new Error(`导出失败: ${response.status}`);
        if (format === 'csv') {
            const blob = await response.blob();
            const a = document.createElement('a');
            a.href = URL.createObjectURL(blob);
            a.download = `${dataType}.csv`;
            a.click();
            URL.revokeObjectURL(a.href);
        } else {
            const data = await response.json();
            const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
            const a = document.createElement('a');
            a.href = URL.createObjectURL(blob);
            a.download = `${dataType}.json`;
            a.click();
            URL.revokeObjectURL(a.href);
        }
    }
}
