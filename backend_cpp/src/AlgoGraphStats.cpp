#include "../include/Graph.h"
#include <queue>
#include <unordered_set>
#include <sstream>
#include <cmath>
#include <cstdlib>
#include <ctime>

std::string GraphStatsAlgorithm::execute(const SocialGraph& graph) {
    auto nodes = graph.get_all_nodes();
    size_t V = nodes.size();
    size_t E = graph.edge_count();

    // 密度
    double density = (V > 1) ? (2.0 * E) / (V * (V - 1.0)) : 0.0;

    // 度数统计
    size_t max_degree = 0;
    double sum_degree = 0.0;
    for (const auto& node : nodes) {
        size_t d = graph.get_neighbors(node).size();
        sum_degree += d;
        if (d > max_degree) max_degree = d;
    }
    double avg_degree = V > 0 ? sum_degree / V : 0.0;

    // 连通分量数（BFS 扫一遍）
    int components = 0;
    std::unordered_set<std::string> visited;
    for (const auto& start : nodes) {
        if (visited.count(start)) continue;
        components++;
        std::queue<std::string> q;
        q.push(start);
        visited.insert(start);
        while (!q.empty()) {
            std::string u = q.front(); q.pop();
            for (const auto& v : graph.get_neighbors(u)) {
                if (!visited.count(v)) {
                    visited.insert(v);
                    q.push(v);
                }
            }
        }
    }

    // 直径估算：从 10 个随机节点做 BFS，取最大离心率
    int diameter_approx = 0;
    std::srand(static_cast<unsigned>(std::time(nullptr)));
    int samples = std::min(10, static_cast<int>(V));
    for (int s = 0; s < samples; ++s) {
        int idx = std::rand() % V;
        std::string start = nodes[idx];

        std::unordered_map<std::string, int> dist;
        std::queue<std::string> q;
        q.push(start);
        dist[start] = 0;
        int max_dist = 0;

        while (!q.empty()) {
            std::string u = q.front(); q.pop();
            for (const auto& v : graph.get_neighbors(u)) {
                if (dist.find(v) == dist.end()) {
                    dist[v] = dist[u] + 1;
                    max_dist = std::max(max_dist, dist[v]);
                    q.push(v);
                }
            }
        }
        diameter_approx = std::max(diameter_approx, max_dist);
    }

    std::ostringstream json;
    json << "{"
         << "\"status\":\"success\","
         << "\"nodes\":" << V << ","
         << "\"edges\":" << E << ","
         << "\"density\":" << density << ","
         << "\"avg_degree\":" << avg_degree << ","
         << "\"max_degree\":" << max_degree << ","
         << "\"diameter_approx\":" << diameter_approx << ","
         << "\"components\":" << components
         << "}";
    return json.str();
}
