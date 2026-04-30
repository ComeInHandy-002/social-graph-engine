#include "../include/Graph.h"
#include <vector>
#include <string>
#include <unordered_map>
#include <unordered_set>
#include <algorithm>

std::unordered_map<std::string, double> KCoreAlgorithm::execute(const SocialGraph& graph) {
    std::unordered_map<std::string, double> coreness;
    std::unordered_map<std::string, int> degree;
    auto nodes = graph.get_all_nodes();
    int n = static_cast<int>(nodes.size());

    for (const auto& node : nodes) {
        degree[node] = static_cast<int>(graph.get_neighbors(node).size());
    }

    // 找出最大度数，用于桶排序
    int max_deg = 0;
    for (const auto& p : degree) max_deg = std::max(max_deg, p.second);

    // 桶：每个度数对应一个节点集合
    std::vector<std::unordered_set<std::string>> buckets(max_deg + 1);
    std::unordered_map<std::string, int> node_bucket;
    for (const auto& node : nodes) {
        int d = degree[node];
        buckets[d].insert(node);
        node_bucket[node] = d;
    }

    // Batagelj-Zaversnik 核心剥离
    int processed = 0;
    for (int k = 0; k <= max_deg && processed < n; ++k) {
        while (!buckets[k].empty()) {
            auto it = buckets[k].begin();
            std::string u = *it;
            buckets[k].erase(it);

            coreness[u] = static_cast<double>(k);
            processed++;

            for (const auto& v : graph.get_neighbors(u)) {
                int dv = degree[v];
                if (dv > k) {
                    // 将 v 从桶 dv 移到桶 dv-1
                    buckets[dv].erase(v);
                    degree[v] = dv - 1;
                    buckets[dv - 1].insert(v);
                }
            }
        }
    }

    return coreness;
}
