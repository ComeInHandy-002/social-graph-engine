#include "../include/Graph.h"
#include <stack>
#include <vector>
#include <string>
#include <unordered_map>
#include <unordered_set>
#include <algorithm>

// ==========================================
// 标准 DFS 寻路：start → target
// ==========================================
std::vector<std::string> DFSAlgorithm::execute(const SocialGraph& graph, const std::string& start, const std::string& target) {
    std::vector<std::string> path;
    if (!graph.has_node(start) || !graph.has_node(target)) return path;

    std::stack<std::string> stk;
    std::unordered_set<std::string> visited;
    std::unordered_map<std::string, std::string> parent;

    stk.push(start);
    visited.insert(start);

    while (!stk.empty()) {
        std::string current = stk.top();
        stk.pop();

        if (current == target) {
            std::string curr = target;
            while (curr != start) {
                path.push_back(curr);
                curr = parent[curr];
            }
            path.push_back(start);
            std::reverse(path.begin(), path.end());
            return path;
        }

        for (const std::string& neighbor : graph.get_neighbors(current)) {
            if (visited.find(neighbor) == visited.end()) {
                visited.insert(neighbor);
                parent[neighbor] = current;
                stk.push(neighbor);
            }
        }
    }
    return path;
}

// ==========================================
// 辅助函数：检测有向环（回声室探测）
// colors: 0-未访问, 1-访问中(在栈里), 2-已完成
// ==========================================
static bool detectCycleDFS(const std::string& u,
                    const SocialGraph& graph,
                    std::unordered_map<std::string, int>& colors,
                    std::unordered_map<std::string, std::string>& parent,
                    std::vector<std::string>& cycleNodes) {
    colors[u] = 1;

    for (const std::string& v : graph.get_neighbors(u)) {
        if (colors[v] == 1) {
            std::string curr = u;
            cycleNodes.push_back(v);
            while (curr != v && curr != "") {
                cycleNodes.push_back(curr);
                curr = parent[curr];
            }
            cycleNodes.push_back(v);
            return true;
        }
        if (colors[v] == 0) {
            parent[v] = u;
            if (detectCycleDFS(v, graph, colors, parent, cycleNodes)) return true;
        }
    }

    colors[u] = 2;
    return false;
}

std::vector<std::string> DFSAlgorithm::detectEchoChamber(const SocialGraph& graph, const std::string& startNode) {
    std::unordered_map<std::string, int> colors;
    std::unordered_map<std::string, std::string> parent;
    std::vector<std::string> cycleNodes;

    for (const auto& node : graph.get_all_nodes()) colors[node] = 0;

    if (graph.has_node(startNode)) {
        detectCycleDFS(startNode, graph, colors, parent, cycleNodes);
    }

    return cycleNodes;
}