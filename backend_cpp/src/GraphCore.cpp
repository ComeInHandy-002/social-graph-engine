#include "../include/Graph.h"

void SocialGraph::add_edge(const std::string& u, const std::string& v) {
    adj_list[u].push_back(v);
    adj_list[v].push_back(u);
}

const std::vector<std::string>& SocialGraph::get_neighbors(const std::string& node) const {
    static const std::vector<std::string> empty_list;
    auto it = adj_list.find(node);
    if (it != adj_list.end()) return it->second;
    return empty_list;
}

bool SocialGraph::has_node(const std::string& node) const {
    return adj_list.find(node) != adj_list.end();
}
// ==========================================
// 辅助接口：安全地暴露图的节点和边
// ==========================================
std::vector<std::string> SocialGraph::get_all_nodes() const {
    std::vector<std::string> nodes;
    for (const auto& pair : adj_list) nodes.push_back(pair.first);
    return nodes;
}

std::vector<std::pair<std::string, std::string>> SocialGraph::get_all_edges() const {
    std::vector<std::pair<std::string, std::string>> edges;
    for (const auto& pair : adj_list) {
        for (const std::string& neighbor : pair.second) {
            // 防止无向图输出双向边导致连线数量翻倍
            if (pair.first < neighbor) {
                edges.push_back({pair.first, neighbor});
            }
        }
    }
    return edges;
}