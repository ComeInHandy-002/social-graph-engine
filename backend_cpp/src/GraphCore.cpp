#include "../include/Graph.h"

void SocialGraph::add_edge(const std::string& u, const std::string& v) {
    adj_list[u].push_back(v);
    adj_list[v].push_back(u);
    nodes_cache_valid = false;
    edges_cache_valid = false;
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
    if (!nodes_cache_valid) {
        cached_nodes.clear();
        cached_nodes.reserve(adj_list.size());
        for (const auto& pair : adj_list) cached_nodes.push_back(pair.first);
        nodes_cache_valid = true;
    }
    return cached_nodes;
}

std::vector<std::pair<std::string, std::string>> SocialGraph::get_all_edges() const {
    if (!edges_cache_valid) {
        cached_edges.clear();
        for (const auto& pair : adj_list) {
            for (const std::string& neighbor : pair.second) {
                if (pair.first < neighbor) {
                    cached_edges.push_back({pair.first, neighbor});
                }
            }
        }
        edges_cache_valid = true;
    }
    return cached_edges;
}

size_t SocialGraph::node_count() const {
    return adj_list.size();
}

size_t SocialGraph::edge_count() const {
    get_all_edges(); // 确保缓存有效
    return cached_edges.size();
}

std::vector<std::string> SocialGraph::get_neighbors_copy(const std::string& node) const {
    auto it = adj_list.find(node);
    if (it != adj_list.end()) return it->second;
    return {};
}