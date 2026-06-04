#include "../include/Graph.h"
#include <queue>
#include <stack>
#include <vector>
#include <string>
#include <unordered_map>
#include <algorithm>

std::unordered_map<std::string, double> BetweennessCentralityAlgorithm::execute(const SocialGraph& graph) {
    std::unordered_map<std::string, double> betweenness;
    auto nodes = graph.get_all_nodes();
    for (const auto& n : nodes) betweenness[n] = 0.0;

    for (const auto& s : nodes) {
        std::stack<std::string> stk;
        std::unordered_map<std::string, std::vector<std::string>> pred;
        std::unordered_map<std::string, int> sigma;
        std::unordered_map<std::string, int> dist;

        for (const auto& n : nodes) {
            sigma[n] = 0;
            dist[n] = -1;
        }
        sigma[s] = 1;
        dist[s] = 0;

        std::queue<std::string> q;
        q.push(s);

        while (!q.empty()) {
            std::string v = q.front(); q.pop();
            stk.push(v);

            for (const auto& w : graph.get_neighbors(v)) {
                if (dist[w] < 0) {
                    dist[w] = dist[v] + 1;
                    q.push(w);
                }
                if (dist[w] == dist[v] + 1) {
                    sigma[w] += sigma[v];
                    pred[w].push_back(v);
                }
            }
        }

        std::unordered_map<std::string, double> delta;
        for (const auto& n : nodes) delta[n] = 0.0;

        while (!stk.empty()) {
            std::string w = stk.top(); stk.pop();
            for (const auto& v : pred[w]) {
                delta[v] += (static_cast<double>(sigma[v]) / sigma[w]) * (1.0 + delta[w]);
            }
            if (w != s) {
                betweenness[w] += delta[w];
            }
        }
    }

    return betweenness;
}
