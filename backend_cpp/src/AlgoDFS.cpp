#include "../include/Graph.h"
#include <stack>
#include <vector>
#include <string>
#include <unordered_map>
#include <algorithm>

// 🌟 辅助函数：深度优先搜索核心逻辑
// colors: 0-未访问, 1-访问中(在栈里), 2-已完成
bool detectCycleDFS(const std::string& u,
                    const SocialGraph& graph,
                    std::unordered_map<std::string, int>& colors,
                    std::unordered_map<std::string, std::string>& parent,
                    std::vector<std::string>& cycleNodes) {
    colors[u] = 1; // 标记为访问中（变灰色）

    for (const std::string& v : graph.get_neighbors(u)) {
        if (colors[v] == 1) {
            // 🚨 发现回边 (Back-edge)！回声室锁定！
            // 开始回溯提取闭环路径
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

    colors[u] = 2; // 标记为已处理（变黑色）
    return false;
}

std::vector<std::string> DFSAlgorithm::execute(const SocialGraph& graph, const std::string& start, const std::string& target) {
    // 此接口原本用于寻路，我们现在复用它来执行回声室探测
    // 实际逻辑由 main.cpp 中的新指令调用
    return {};
}

// 🌟 新增：专门的回声室探测接口
std::vector<std::string> DFSAlgorithm::detectEchoChamber(const SocialGraph& graph, const std::string& startNode) {
    std::unordered_map<std::string, int> colors;
    std::unordered_map<std::string, std::string> parent;
    std::vector<std::string> cycleNodes;

    // 初始化所有节点为 0 (未访问)
    for (const auto& node : graph.get_all_nodes()) colors[node] = 0;

    if (graph.has_node(startNode)) {
        detectCycleDFS(startNode, graph, colors, parent, cycleNodes);
    }

    return cycleNodes;
}