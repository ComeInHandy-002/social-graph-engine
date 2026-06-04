#include "../include/Graph.h"
#include <queue>
#include <unordered_set>
#include <unordered_map>
#include <algorithm>

std::vector<std::string> BFSAlgorithm::execute(const SocialGraph& graph, const std::string& start, const std::string& target) {
    std::vector<std::string> path;
    if (!graph.has_node(start) || !graph.has_node(target)) return path;

    std::queue<std::string> q;
    std::unordered_set<std::string> visited;
    std::unordered_map<std::string, std::string> parent;

    q.push(start);
    visited.insert(start);

    while (!q.empty()) {
        std::string current = q.front();
        q.pop();

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
                q.push(neighbor);
            }
        }
    }
    return path;
}