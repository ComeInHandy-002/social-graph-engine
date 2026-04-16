#include "../include/Graph.h"

// 构造函数：接收参数
PageRankAlgorithm::PageRankAlgorithm(int iterations, double d) : _iterations(iterations), _d(d) {}

// 具体的算法实现
std::unordered_map<std::string, double> PageRankAlgorithm::execute(const SocialGraph& graph) {
    std::unordered_map<std::string, double> pr;
    auto nodes = graph.get_all_nodes();
    double n = nodes.size();
    if (n == 0) return pr;

    for (const auto& node : nodes) pr[node] = 1.0 / n;

    for (int i = 0; i < _iterations; ++i) {
        std::unordered_map<std::string, double> next_pr;
        for (const auto& node : nodes) next_pr[node] = (1.0 - _d) / n;

        for (const auto& u : nodes) {
            const auto& neighbors = graph.get_neighbors(u);
            if (!neighbors.empty()) {
                double contribution = _d * pr[u] / neighbors.size();
                for (const auto& v : neighbors) next_pr[v] += contribution;
            }
        }
        pr = next_pr;
    }
    return pr;
}