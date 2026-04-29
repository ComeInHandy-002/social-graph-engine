#ifndef GRAPH_H
#define GRAPH_H

#include <vector>
#include <string>
#include <unordered_map>
#include <iostream>
#include <fstream>
#include <chrono>
#include <iomanip>

// ==========================================
// 部门 1：工业级日志系统
// ==========================================
class SocialLogger {
public:
    static void log(const std::string& level, const std::string& message) {
        auto now = std::chrono::system_clock::to_time_t(std::chrono::system_clock::now());
        std::cerr << "[" << std::put_time(std::localtime(&now), "%Y-%m-%d %H:%M:%S") << "] "
                  << "[" << level << "] " << message << std::endl;
    }
};

#define LOG_INFO(msg)  SocialLogger::log("INFO", msg)
#define LOG_ERROR(msg) SocialLogger::log("ERROR", msg)

// ==========================================
// 部门 2：纯粹的数据结构层 (只负责存数据，没有任何高阶算法)
// ==========================================
class SocialGraph {
public:
    void add_edge(const std::string& u, const std::string& v);
    const std::vector<std::string>& get_neighbors(const std::string& node) const;
    bool has_node(const std::string& node) const;

    std::vector<std::string> get_all_nodes() const;
    std::vector<std::pair<std::string, std::string>> get_all_edges() const;

private:
    std::unordered_map<std::string, std::vector<std::string>> adj_list;
};

// ==========================================
// 🌟 核心升级：抽象算法接口 (策略模式基石)
// 规定了所有算法都必须是独立的插件，并且有一个统一个执行入口
// ==========================================
class IGraphAlgorithm {
public:
    virtual ~IGraphAlgorithm() = default;
};

// 为寻路算法定制的接口
class IPathFindingAlgorithm : public IGraphAlgorithm {
public:
    virtual std::vector<std::string> execute(const SocialGraph& graph, const std::string& start, const std::string& target) = 0;
};

// 为全网权重计算定制的接口
class IScoringAlgorithm : public IGraphAlgorithm {
public:
    virtual std::unordered_map<std::string, double> execute(const SocialGraph& graph) = 0;
};

// 为社区聚类定制的接口
class ICommunityAlgorithm : public IGraphAlgorithm {
public:
    virtual std::unordered_map<std::string, std::string> execute(const SocialGraph& graph) = 0;
};


// ==========================================
// 部门 3：数据持久化层
// ==========================================
class DataManager {
public:
    static bool loadFromFile(const std::string& path, SocialGraph& graph) {
        std::ifstream file(path);
        if (!file.is_open()) {
            LOG_ERROR("无法打开数据源文件: " + path);
            return false;
        }
        std::string u, v;
        int count = 0;
        while (file >> u >> v) {
            graph.add_edge(u, v);
            count++;
        }
        LOG_INFO("成功加载拓扑数据，共计注入 " + std::to_string(count) + " 条连线。");
        return true;
    }
};

// ==========================================
// 🌟 插件花名册：向系统注册我们拥有的具体算法
// ==========================================

// 1. PageRank 插件
class PageRankAlgorithm : public IScoringAlgorithm {
public:
    PageRankAlgorithm(int iterations = 100, double d = 0.85);
    std::unordered_map<std::string, double> execute(const SocialGraph& graph) override;
private:
    int _iterations;
    double _d;
};

// 2. BFS 寻路插件
class BFSAlgorithm : public IPathFindingAlgorithm {
public:
    std::vector<std::string> execute(const SocialGraph& graph, const std::string& start, const std::string& target) override;
};

// 3. LPA 社区裂变插件
class LPAAlgorithm : public ICommunityAlgorithm {
public:
    std::unordered_map<std::string, std::string> execute(const SocialGraph& graph) override;
};

// 4. Dijkstra 寻路插件 (带权最短路径)
class DijkstraAlgorithm : public IPathFindingAlgorithm {
public:
    std::vector<std::string> execute(const SocialGraph& graph, const std::string& start, const std::string& target) override;
};

class DFSAlgorithm : public IPathFindingAlgorithm {
public:
    std::vector<std::string> execute(const SocialGraph& graph, const std::string& start, const std::string& target) override;
    // 🌟 新增：深度穿透探测
    std::vector<std::string> detectEchoChamber(const SocialGraph& graph, const std::string& startNode);
};
#endif // GRAPH_H