#include "../include/Graph.h"
#include <queue>
#include <unordered_set>
#include <vector>

std::unordered_map<std::string, std::string> ConnectedComponentsAlgorithm::execute(const SocialGraph& graph) {
    std::unordered_map<std::string, std::string> components;
    std::unordered_set<std::string> visited;
    auto nodes = graph.get_all_nodes();

    _component_count = 0;
    _component_sizes.clear();

    for (const auto& start : nodes) {
        if (visited.count(start)) continue;

        std::string min_id = start;
        std::vector<std::string> comp_nodes;
        std::queue<std::string> q;
        q.push(start);
        visited.insert(start);

        while (!q.empty()) {
            std::string u = q.front(); q.pop();
            comp_nodes.push_back(u);
            if (u < min_id) min_id = u;
            for (const auto& v : graph.get_neighbors(u)) {
                if (!visited.count(v)) {
                    visited.insert(v);
                    q.push(v);
                }
            }
        }

        _component_count++;
        _component_sizes[min_id] = static_cast<int>(comp_nodes.size());
        for (const auto& node : comp_nodes) {
            components[node] = min_id;
        }
    }

    return components;
}

int ConnectedComponentsAlgorithm::get_component_count() const {
    return _component_count;
}

std::unordered_map<std::string, int> ConnectedComponentsAlgorithm::get_component_sizes() const {
    return _component_sizes;
}
