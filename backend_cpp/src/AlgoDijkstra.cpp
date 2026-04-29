#include "../include/Graph.h"
#include <queue>
#include <unordered_map>
#include <unordered_set>
#include <vector>
#include <string>
#include <algorithm>

// 🌟 核心极客技巧：用稳定哈希伪造 1-10 的“沟通阻力”
// 这样不需要修改数据文件，就能让无权图瞬间变成带权图！
double get_resistance(const std::string& u, const std::string& v) {
    size_t h1 = std::hash<std::string>{}(u);
    size_t h2 = std::hash<std::string>{}(v);
    return 1.0 + (h1 ^ h2) % 10;
}

std::vector<std::string> DijkstraAlgorithm::execute(const SocialGraph& graph, const std::string& start, const std::string& target) {
    std::vector<std::string> path;
    if (!graph.has_node(start) || !graph.has_node(target)) return path;

    // 🌟 优先队列(最小堆)：<距离, 节点ID>，永远先弹出当前阻力最小的节点！
    using NodeDist = std::pair<double, std::string>;
    std::priority_queue<NodeDist, std::vector<NodeDist>, std::greater<NodeDist>> pq;

    std::unordered_map<std::string, double> dist;
    std::unordered_map<std::string, std::string> parent;

    // 初始化所有节点的距离为无穷大
    for (const auto& node : graph.get_all_nodes()) {
        dist[node] = 1e18;
    }

    dist[start] = 0.0;
    pq.push({0.0, start});

    while (!pq.empty()) {
        auto [current_dist, u] = pq.top();
        pq.pop();

        // 🎯 贪心特性：一旦弹出目标节点，当前路径绝对是最优解
        if (u == target) {
            std::string curr = target;
            while (curr != start) {
                path.push_back(curr);
                curr = parent[curr];
            }
            path.push_back(start);
            std::reverse(path.begin(), path.end());
            return path;
        }

        // ⚡ 极其关键的优化：废弃的旧状态直接跳过
        if (current_dist > dist[u]) continue;

        for (const std::string& v : graph.get_neighbors(u)) {
            double weight = get_resistance(u, v);
            // 状态转移方程：如果通过 u 走到 v 的阻力，小于之前记录的阻力，就松弛它！
            if (dist[u] + weight < dist[v]) {
                dist[v] = dist[u] + weight;
                parent[v] = u;
                pq.push({dist[v], v});
            }
        }
    }
    return path;
}