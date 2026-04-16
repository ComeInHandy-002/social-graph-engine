#include "../include/Graph.h"

std::unordered_map<std::string, std::string> LPAAlgorithm::execute(const SocialGraph& graph) {
    std::unordered_map<std::string, std::string> communities;
    auto nodes = graph.get_all_nodes();

    // 初始化：每个节点属于自己的社区
    for (const auto& node : nodes) {
        communities[node] = node;
    }

    bool changed = true;
    int max_iters = 10; // 防止无限震荡

    while (changed && max_iters > 0) {
        changed = false;
        max_iters--;

        for (const auto& u : nodes) {
            std::unordered_map<std::string, int> label_counts;
            for (const auto& v : graph.get_neighbors(u)) {
                label_counts[communities[v]]++;
            }

            if (label_counts.empty()) continue;

            std::string best_label = communities[u];
            int max_count = 0;
            for (const auto& pair : label_counts) {
                if (pair.second > max_count) {
                    max_count = pair.second;
                    best_label = pair.first;
                }
            }

            if (communities[u] != best_label) {
                communities[u] = best_label;
                changed = true;
            }
        }
    }
    return communities;
}