#include "../include/Graph.h"
#include <unordered_set>

std::unordered_map<std::string, double> ClusteringCoefficientAlgorithm::execute(const SocialGraph& graph) {
    std::unordered_map<std::string, double> cc;
    auto nodes = graph.get_all_nodes();

    for (const auto& u : nodes) {
        const auto& neighbors = graph.get_neighbors(u);
        int k = static_cast<int>(neighbors.size());

        if (k < 2) {
            cc[u] = 0.0;
            continue;
        }

        // 将邻居放入集合以加速交集检测
        std::unordered_set<std::string> neighbor_set(neighbors.begin(), neighbors.end());

        int triangles = 0;
        for (size_t i = 0; i < neighbors.size(); ++i) {
            for (size_t j = i + 1; j < neighbors.size(); ++j) {
                const auto& a = neighbors[i];
                const auto& b = neighbors[j];
                // 只检查 a < b 方向，避免重复
                const auto& a_neighbors = graph.get_neighbors(a);
                // 遍历较少邻居的节点以加速
                if (a_neighbors.size() < neighbor_set.size()) {
                    for (const auto& w : a_neighbors) {
                        if (w == b) { triangles++; break; }
                    }
                } else {
                    if (neighbor_set.count(b)) triangles++;
                }
            }
        }

        double max_triangles = k * (k - 1.0) / 2.0;
        cc[u] = triangles / max_triangles;
    }

    return cc;
}
