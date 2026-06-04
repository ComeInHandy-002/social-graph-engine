#ifndef SERVER_REQUEST_HANDLER_H
#define SERVER_REQUEST_HANDLER_H

// ============================================================================
// 交付 1 + 2: 请求处理器
//
// 核心职责:
//   1. 解析请求 → 匹配算法 → 执行计算 → 序列化结果
//   2. 支持两种模式:
//      - 同步模式: 完整计算后一次性返回
//      - 流式模式: 逐批产生 StreamChunk 并通过回调发送
//   3. 持有 const SocialGraph& 的共享引用 (线程安全只读)
//   4. 集成 Benchmark 计时
//
// 并发安全:
//   - 所有算法在调用线程上执行 (ThreadPool worker thread)
//   - SocialGraph 为只读访问
//   - 每个请求创建独立的算法实例
//
// 流式输出适用算法:
//   - PageRank: 每次迭代后输出各节点的PR值
//   - Betweenness: 每个源节点计算后输出增量
//   - LPA: 每次迭代后输出新的社区划分
// ============================================================================

#include "protocol.h"
#include "../include/Graph.h"

#include <functional>
#include <memory>
#include <chrono>
#include <sstream>
#include <cmath>
#include <algorithm>
#include <atomic>

namespace server {

// ── 流式回调类型: C++端通过此回调逐批返回结果 ─────────────────
using StreamCallback = std::function<void(const StreamChunk&)>;

class RequestHandler {
public:
    explicit RequestHandler(const SocialGraph& graph)
        : graph_(graph) {}

    // ── 同步处理请求 (非流式) ──────────────────────────────────
    ComputeResponse handle_sync(const ComputeRequest& req);

    // ── 流式处理请求 ──────────────────────────────────────────
    // 对每个数据块调用 on_chunk 回调
    // 返回最终的摘要响应 (time_ms, status)
    ComputeResponse handle_streaming(const ComputeRequest& req, StreamCallback on_chunk);

    // ── Benchmark 统计 (线程安全累加) ─────────────────────────
    struct BenchStats {
        std::atomic<int64_t> total_calls{0};
        std::atomic<int64_t> total_time_us{0};
        std::atomic<int64_t> max_time_us{0};
        std::atomic<int64_t> min_time_us{INT64_MAX};

        void record(int64_t time_us) {
            total_calls.fetch_add(1, std::memory_order_relaxed);
            total_time_us.fetch_add(time_us, std::memory_order_relaxed);
            // CAS loop for max
            int64_t cur = max_time_us.load(std::memory_order_relaxed);
            while (time_us > cur && !max_time_us.compare_exchange_weak(cur, time_us, std::memory_order_relaxed));
            // CAS loop for min
            cur = min_time_us.load(std::memory_order_relaxed);
            while (time_us < cur && !min_time_us.compare_exchange_weak(cur, time_us, std::memory_order_relaxed));
        }

        double avg_ms() const {
            int64_t calls = total_calls.load(std::memory_order_relaxed);
            if (calls == 0) return 0.0;
            return static_cast<double>(total_time_us.load(std::memory_order_relaxed)) / calls / 1000.0;
        }

        int64_t max_ms() const {
            return max_time_us.load(std::memory_order_relaxed) / 1000;
        }

        int64_t min_ms() const {
            int64_t v = min_time_us.load(std::memory_order_relaxed);
            return (v == INT64_MAX) ? 0 : v / 1000;
        }
    };

    const BenchStats& stats() const { return bench_; }
    BenchStats& mutable_stats() { return bench_; }

private:
    const SocialGraph& graph_;
    BenchStats bench_;

    // ── 各算法的内部实现 ─────────────────────────────────────
    ComputeResponse _handle_pagerank(const ComputeRequest& req, StreamCallback* on_chunk);
    ComputeResponse _handle_betweenness(const ComputeRequest& req, StreamCallback* on_chunk);
    ComputeResponse _handle_community(const ComputeRequest& req, StreamCallback* on_chunk);
    ComputeResponse _handle_path(const ComputeRequest& req, bool dijkstra);
    ComputeResponse _handle_echo_chamber(const ComputeRequest& req);
    ComputeResponse _handle_full_graph(const ComputeRequest& req);
    ComputeResponse _handle_graph_stats(const ComputeRequest& req);
    ComputeResponse _handle_connected_components(const ComputeRequest& req);
    ComputeResponse _handle_kcore(const ComputeRequest& req);
    ComputeResponse _handle_clustering_coeff(const ComputeRequest& req);

    // ── JSON 序列化辅助 ──────────────────────────────────────
    static std::string _serialize_scoring(const std::unordered_map<std::string, double>& scores,
                                           const std::string& field_name = "score");
    static std::string _serialize_community(const std::unordered_map<std::string, std::string>& communities);
    static std::string _serialize_path(const std::vector<std::string>& path);
};

// ═══════════════════════════════════════════════════════════════════
// 公共入口: handle_sync
// ═══════════════════════════════════════════════════════════════════

inline ComputeResponse RequestHandler::handle_sync(const ComputeRequest& req) {
    return handle_streaming(req, nullptr);
}

// ═══════════════════════════════════════════════════════════════════
// 公共入口: handle_streaming (on_chunk==nullptr → 非流式)
// ═══════════════════════════════════════════════════════════════════

inline ComputeResponse RequestHandler::handle_streaming(const ComputeRequest& req, StreamCallback on_chunk) {
    switch (req.command) {
        case AlgoCommand::PING:
        {
            ComputeResponse resp;
            resp.request_id = req.request_id;
            resp.status = ResponseStatus::OK;
            resp.time_ms = 0;
            resp.json_data = "{\"message\":\"pong\",\"nodes\":" + std::to_string(graph_.node_count()) + "}";
            return resp;
        }

        case AlgoCommand::PAGE_RANK:
            return _handle_pagerank(req, on_chunk ? &on_chunk : nullptr);

        case AlgoCommand::BETWEENNESS:
            return _handle_betweenness(req, on_chunk ? &on_chunk : nullptr);

        case AlgoCommand::COMMUNITY:
            return _handle_community(req, on_chunk ? &on_chunk : nullptr);

        case AlgoCommand::SHORTEST_PATH:
            return _handle_path(req, false);

        case AlgoCommand::DIJKSTRA_PATH:
            return _handle_path(req, true);

        case AlgoCommand::ECHO_CHAMBER:
            return _handle_echo_chamber(req);

        case AlgoCommand::GET_FULL_GRAPH:
            return _handle_full_graph(req);

        case AlgoCommand::GRAPH_STATS:
            return _handle_graph_stats(req);

        case AlgoCommand::CONNECTED_COMPONENTS:
            return _handle_connected_components(req);

        case AlgoCommand::KCORE:
            return _handle_kcore(req);

        case AlgoCommand::CLUSTERING_COEFF:
            return _handle_clustering_coeff(req);

        default:
        {
            ComputeResponse resp;
            resp.request_id = req.request_id;
            resp.status = ResponseStatus::ERROR;
            resp.error_code = 400;
            resp.error_message = "未知算法命令: " + command_name(req.command);
            return resp;
        }
    }
}

// ═══════════════════════════════════════════════════════════════════
// PageRank 实现 (交付2: 收敛检测 + 流式输出)
// ═══════════════════════════════════════════════════════════════════

inline ComputeResponse RequestHandler::_handle_pagerank(const ComputeRequest& req, StreamCallback* on_chunk) {
    auto t_start = std::chrono::high_resolution_clock::now();

    // 读取参数
    int max_iters = 100;
    double damping = 0.85;
    double convergence_threshold = 1e-6;

    auto iters_param = req.get_param("iterations");
    if (iters_param) max_iters = std::stoi(*iters_param);

    auto damp_param = req.get_param("damping");
    if (damp_param) damping = std::stod(*damp_param);

    auto conv_param = req.get_param("convergence");
    if (conv_param) convergence_threshold = std::stod(*conv_param);

    // 初始化
    auto nodes = graph_.get_all_nodes();
    size_t n = nodes.size();
    if (n == 0) {
        ComputeResponse resp;
        resp.request_id = req.request_id;
        resp.status = ResponseStatus::ERROR;
        resp.error_code = 404;
        resp.error_message = "图为空";
        return resp;
    }

    std::unordered_map<std::string, double> pr;
    std::unordered_map<std::string, double> next_pr;
    double init_val = 1.0 / n;
    for (const auto& node : nodes) {
        pr[node] = init_val;
        next_pr[node] = (1.0 - damping) / n;
    }

    // 预计算出度用于向量化更新
    std::unordered_map<std::string, size_t> out_degree;
    for (const auto& node : nodes) {
        out_degree[node] = graph_.get_neighbors(node).size();
    }

    // Power iteration with convergence detection
    for (int iter = 0; iter < max_iters; ++iter) {
        // 重置 next_pr
        for (const auto& node : nodes) {
            next_pr[node] = (1.0 - damping) / n;
        }

        // 传播PageRank值
        for (const auto& u : nodes) {
            const auto& neighbors = graph_.get_neighbors(u);
            size_t deg = out_degree[u];
            if (deg > 0) {
                double contrib = damping * pr[u] / deg;
                for (const auto& v : neighbors) {
                    next_pr[v] += contrib;
                }
            }
        }

        // 收敛检测
        double max_diff = 0.0;
        for (const auto& node : nodes) {
            double diff = std::abs(next_pr[node] - pr[node]);
            if (diff > max_diff) max_diff = diff;
        }
        pr.swap(next_pr);

        // 流式输出 (每轮迭代)
        if (on_chunk) {
            StreamChunk chunk;
            chunk.request_id = req.request_id;
            chunk.chunk_index = static_cast<uint32_t>(iter);

            // 输出部分结果 (top-100)
            std::vector<std::pair<std::string, double>> sorted;
            sorted.reserve(std::min(n, size_t(100)));
            for (const auto& [node, score] : pr) {
                sorted.emplace_back(node, score);
            }
            std::partial_sort(sorted.begin(),
                              sorted.begin() + std::min(sorted.size(), size_t(100)),
                              sorted.end(),
                              [](const auto& a, const auto& b) { return a.second > b.second; });

            if (sorted.size() > 100) sorted.resize(100);

            std::ostringstream j;
            j << "[";
            for (size_t i = 0; i < sorted.size(); ++i) {
                if (i > 0) j << ",";
                j << "{\"node\":\"" << escape_json(sorted[i].first)
                  << "\",\"score\":" << sorted[i].second << "}";
            }
            j << "]";
            chunk.json_data = j.str();
            chunk.is_last = (iter == max_iters - 1) || (max_diff < convergence_threshold);

            (*on_chunk)(chunk);
        }

        if (max_diff < convergence_threshold) {
            break;
        }
    }

    auto t_end = std::chrono::high_resolution_clock::now();
    long long time_us = std::chrono::duration_cast<std::chrono::microseconds>(t_end - t_start).count();
    bench_.record(time_us);

    ComputeResponse resp;
    resp.request_id = req.request_id;
    resp.status = ResponseStatus::OK;
    resp.time_ms = time_us / 1000;
    resp.json_data = _serialize_scoring(pr);
    return resp;
}

// ═══════════════════════════════════════════════════════════════════
// Betweenness Centrality (交付2: 顶点采样模式)
// ═══════════════════════════════════════════════════════════════════

inline ComputeResponse RequestHandler::_handle_betweenness(const ComputeRequest& req, StreamCallback* on_chunk) {
    auto t_start = std::chrono::high_resolution_clock::now();

    auto nodes = graph_.get_all_nodes();
    size_t n = nodes.size();

    // 读取采样比例参数 (大图必备优化)
    double sample_ratio = 1.0;
    auto ratio_param = req.get_param("sample_ratio");
    if (ratio_param) {
        sample_ratio = std::stod(*ratio_param);
        sample_ratio = std::max(0.01, std::min(1.0, sample_ratio)); // clamp
    }

    // 大图自动降采样
    if (n > 100000 && !ratio_param.has_value()) {
        sample_ratio = std::min(1.0, 20000.0 / n);
    }

    std::unordered_map<std::string, double> betweenness;
    for (const auto& node : nodes) {
        betweenness[node] = 0.0;
    }

    // 确定采样哪些节点作为源
    std::vector<std::string> sources;
    if (sample_ratio >= 1.0) {
        sources = nodes;
    } else {
        size_t sample_count = std::max(size_t(1), static_cast<size_t>(n * sample_ratio));
        sources.reserve(sample_count);
        // 均匀采样
        size_t step = n / sample_count;
        for (size_t i = 0; i < sample_count; ++i) {
            sources.push_back(nodes[i * step]);
        }
    }

    size_t total_sources = sources.size();

    for (size_t si = 0; si < total_sources; ++si) {
        const auto& s = sources[si];

        // Brandes BFS from s
        std::stack<std::string> stk;
        std::unordered_map<std::string, std::vector<std::string>> pred;
        std::unordered_map<std::string, int64_t> sigma;
        std::unordered_map<std::string, int> dist;

        for (const auto& node : nodes) {
            sigma[node] = 0;
            dist[node] = -1;
        }
        sigma[s] = 1;
        dist[s] = 0;

        std::queue<std::string> q;
        q.push(s);

        while (!q.empty()) {
            std::string v = q.front(); q.pop();
            stk.push(v);
            for (const auto& w : graph_.get_neighbors(v)) {
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

        // Back-propagation
        std::unordered_map<std::string, double> delta;
        for (const auto& node : nodes) delta[node] = 0.0;

        while (!stk.empty()) {
            std::string w = stk.top(); stk.pop();
            for (const auto& v : pred[w]) {
                if (sigma[w] > 0) {
                    delta[v] += (static_cast<double>(sigma[v]) / sigma[w]) * (1.0 + delta[w]);
                }
            }
            if (w != s) {
                betweenness[w] += delta[w] / sample_ratio; // 缩放回全图
            }
        }

        // 流式输出: 每处理完 k个源节点 输出一次中间结果
        if (on_chunk && (si % 10 == 0 || si == total_sources - 1)) {
            StreamChunk chunk;
            chunk.request_id = req.request_id;
            chunk.chunk_index = static_cast<uint32_t>(si);
            chunk.json_data = _serialize_scoring(betweenness, "score");
            chunk.is_last = (si == total_sources - 1);
            (*on_chunk)(chunk);
        }
    }

    auto t_end = std::chrono::high_resolution_clock::now();
    long long time_us = std::chrono::duration_cast<std::chrono::microseconds>(t_end - t_start).count();
    bench_.record(time_us);

    ComputeResponse resp;
    resp.request_id = req.request_id;
    resp.status = ResponseStatus::OK;
    resp.time_ms = time_us / 1000;

    if (!on_chunk) {
        resp.json_data = _serialize_scoring(betweenness, "score");
    } else {
        // 流式模式下，最后一个chunk已经包含了完整数据
        resp.json_data = "{\"sampled_sources\":" + std::to_string(total_sources) + ",\"total_nodes\":" + std::to_string(n) + "}";
    }
    return resp;
}

// ═══════════════════════════════════════════════════════════════════
// LPA 社区发现 (交付2: 流式输出每次迭代)
// ═══════════════════════════════════════════════════════════════════

inline ComputeResponse RequestHandler::_handle_community(const ComputeRequest& req, StreamCallback* on_chunk) {
    auto t_start = std::chrono::high_resolution_clock::now();

    auto nodes = graph_.get_all_nodes();
    std::unordered_map<std::string, std::string> communities;
    for (const auto& node : nodes) {
        communities[node] = node;
    }

    int max_iters = 10;
    auto iters_param = req.get_param("iterations");
    if (iters_param) max_iters = std::stoi(*iters_param);

    bool changed = true;
    int iter = 0;

    while (changed && iter < max_iters) {
        changed = false;
        for (const auto& u : nodes) {
            std::unordered_map<std::string, int> label_counts;
            const auto& neighbors = graph_.get_neighbors(u);
            for (const auto& v : neighbors) {
                label_counts[communities[v]]++;
            }
            if (label_counts.empty()) continue;

            std::string best_label = communities[u];
            int max_count = 0;
            for (const auto& [label, count] : label_counts) {
                if (count > max_count) {
                    max_count = count;
                    best_label = label;
                }
            }

            if (communities[u] != best_label) {
                communities[u] = best_label;
                changed = true;
            }
        }

        // 流式输出每次迭代后的社区分布
        if (on_chunk) {
            StreamChunk chunk;
            chunk.request_id = req.request_id;
            chunk.chunk_index = static_cast<uint32_t>(iter);
            chunk.json_data = _serialize_community(communities);
            chunk.is_last = (!changed || iter >= max_iters - 1);
            (*on_chunk)(chunk);
        }

        ++iter;
    }

    auto t_end = std::chrono::high_resolution_clock::now();
    long long time_us = std::chrono::duration_cast<std::chrono::microseconds>(t_end - t_start).count();
    bench_.record(time_us);

    ComputeResponse resp;
    resp.request_id = req.request_id;
    resp.status = ResponseStatus::OK;
    resp.time_ms = time_us / 1000;
    resp.json_data = _serialize_community(communities);
    return resp;
}

// ═══════════════════════════════════════════════════════════════════
// 路径查找: BFS / Dijkstra
// ═══════════════════════════════════════════════════════════════════

inline ComputeResponse RequestHandler::_handle_path(const ComputeRequest& req, bool dijkstra) {
    auto t_start = std::chrono::high_resolution_clock::now();

    auto start = req.get_param("start");
    auto target = req.get_param("target");

    if (!start || !target) {
        ComputeResponse resp;
        resp.request_id = req.request_id;
        resp.status = ResponseStatus::ERROR;
        resp.error_code = 400;
        resp.error_message = "路径查询需要 start 和 target 参数";
        return resp;
    }

    ComputeResponse resp;
    resp.request_id = req.request_id;

    if (!graph_.has_node(*start) || !graph_.has_node(*target)) {
        resp.status = ResponseStatus::ERROR;
        resp.error_code = 404;
        resp.error_message = "节点不存在: " + *start + " 或 " + *target;
        return resp;
    }

    std::vector<std::string> path;

    if (dijkstra) {
        DijkstraAlgorithm algo;
        path = algo.execute(graph_, *start, *target);
    } else {
        BFSAlgorithm algo;
        path = algo.execute(graph_, *start, *target);
    }

    auto t_end = std::chrono::high_resolution_clock::now();
    long long time_us = std::chrono::duration_cast<std::chrono::microseconds>(t_end - t_start).count();
    bench_.record(time_us);

    resp.status = ResponseStatus::OK;
    resp.time_ms = time_us / 1000;
    resp.json_data = _serialize_path(path);
    return resp;
}

// ═══════════════════════════════════════════════════════════════════
// 回声室探测
// ═══════════════════════════════════════════════════════════════════

inline ComputeResponse RequestHandler::_handle_echo_chamber(const ComputeRequest& req) {
    auto t_start = std::chrono::high_resolution_clock::now();

    auto start = req.get_param("start");
    if (!start) {
        ComputeResponse resp;
        resp.request_id = req.request_id;
        resp.status = ResponseStatus::ERROR;
        resp.error_code = 400;
        resp.error_message = "回声室探测需要 start 参数";
        return resp;
    }

    DFSAlgorithm algo;
    auto path = algo.detectEchoChamber(graph_, *start);

    auto t_end = std::chrono::high_resolution_clock::now();
    long long time_us = std::chrono::duration_cast<std::chrono::microseconds>(t_end - t_start).count();
    bench_.record(time_us);

    ComputeResponse resp;
    resp.request_id = req.request_id;
    resp.status = ResponseStatus::OK;
    resp.time_ms = time_us / 1000;
    resp.json_data = _serialize_path(path);
    return resp;
}

// ═══════════════════════════════════════════════════════════════════
// 全网拓扑
// ═══════════════════════════════════════════════════════════════════

inline ComputeResponse RequestHandler::_handle_full_graph(const ComputeRequest& req) {
    auto t_start = std::chrono::high_resolution_clock::now();

    std::ostringstream j;
    j << "{\"nodes\":[";
    bool first = true;
    for (const auto& u : graph_.get_all_nodes()) {
        if (!first) j << ",";
        j << "{\"id\":\"" << escape_json(u) << "\"}";
        first = false;
    }
    j << "],\"links\":[";
    first = true;
    for (const auto& edge : graph_.get_all_edges()) {
        if (!first) j << ",";
        j << "{\"source\":\"" << escape_json(edge.first)
          << "\",\"target\":\"" << escape_json(edge.second) << "\"}";
        first = false;
    }
    j << "]}";

    auto t_end = std::chrono::high_resolution_clock::now();
    long long time_us = std::chrono::duration_cast<std::chrono::microseconds>(t_end - t_start).count();
    bench_.record(time_us);

    ComputeResponse resp;
    resp.request_id = req.request_id;
    resp.status = ResponseStatus::OK;
    resp.time_ms = time_us / 1000;
    resp.json_data = j.str();
    return resp;
}

// ═══════════════════════════════════════════════════════════════════
// 图统计
// ═══════════════════════════════════════════════════════════════════

inline ComputeResponse RequestHandler::_handle_graph_stats(const ComputeRequest& req) {
    auto t_start = std::chrono::high_resolution_clock::now();

    GraphStatsAlgorithm algo;
    std::string stats_json = algo.execute(graph_);

    auto t_end = std::chrono::high_resolution_clock::now();
    long long time_us = std::chrono::duration_cast<std::chrono::microseconds>(t_end - t_start).count();
    bench_.record(time_us);

    // stats_json 格式: {"nodes":N,"edges":M,...}
    // 需要去掉外层花括号
    auto brace = stats_json.find('{');
    auto last_brace = stats_json.rfind('}');
    std::string inner;
    if (brace != std::string::npos && last_brace != std::string::npos && last_brace > brace) {
        inner = stats_json.substr(brace + 1, last_brace - brace - 1);
    }

    ComputeResponse resp;
    resp.request_id = req.request_id;
    resp.status = ResponseStatus::OK;
    resp.time_ms = time_us / 1000;
    resp.json_data = "{" + inner + "}";
    return resp;
}

// ═══════════════════════════════════════════════════════════════════
// 连通分量
// ═══════════════════════════════════════════════════════════════════

inline ComputeResponse RequestHandler::_handle_connected_components(const ComputeRequest& req) {
    auto t_start = std::chrono::high_resolution_clock::now();

    ConnectedComponentsAlgorithm algo;
    auto comps = algo.execute(graph_);
    int comp_count = algo.get_component_count();
    auto comp_sizes = algo.get_component_sizes();

    std::ostringstream j;
    j << "{\"component_count\":" << comp_count
      << ",\"component_sizes\":{";
    bool first_cs = true;
    for (const auto& [id, size] : comp_sizes) {
        if (!first_cs) j << ",";
        j << "\"" << escape_json(id) << "\":" << size;
        first_cs = false;
    }
    j << "},\"data\":[";
    bool first = true;
    for (const auto& [node, comp] : comps) {
        if (!first) j << ",";
        j << "{\"node\":\"" << escape_json(node) << "\",\"component\":\"" << escape_json(comp) << "\"}";
        first = false;
    }
    j << "]}";

    auto t_end = std::chrono::high_resolution_clock::now();
    long long time_us = std::chrono::duration_cast<std::chrono::microseconds>(t_end - t_start).count();
    bench_.record(time_us);

    ComputeResponse resp;
    resp.request_id = req.request_id;
    resp.status = ResponseStatus::OK;
    resp.time_ms = time_us / 1000;
    resp.json_data = j.str();
    return resp;
}

// ═══════════════════════════════════════════════════════════════════
// K-Core
// ═══════════════════════════════════════════════════════════════════

inline ComputeResponse RequestHandler::_handle_kcore(const ComputeRequest& req) {
    auto t_start = std::chrono::high_resolution_clock::now();

    KCoreAlgorithm algo;
    auto kc = algo.execute(graph_);

    auto t_end = std::chrono::high_resolution_clock::now();
    long long time_us = std::chrono::duration_cast<std::chrono::microseconds>(t_end - t_start).count();
    bench_.record(time_us);

    ComputeResponse resp;
    resp.request_id = req.request_id;
    resp.status = ResponseStatus::OK;
    resp.time_ms = time_us / 1000;
    resp.json_data = _serialize_scoring(kc, "coreness");
    return resp;
}

// ═══════════════════════════════════════════════════════════════════
// 聚类系数
// ═══════════════════════════════════════════════════════════════════

inline ComputeResponse RequestHandler::_handle_clustering_coeff(const ComputeRequest& req) {
    auto t_start = std::chrono::high_resolution_clock::now();

    ClusteringCoefficientAlgorithm algo;
    auto cc = algo.execute(graph_);

    auto t_end = std::chrono::high_resolution_clock::now();
    long long time_us = std::chrono::duration_cast<std::chrono::microseconds>(t_end - t_start).count();
    bench_.record(time_us);

    ComputeResponse resp;
    resp.request_id = req.request_id;
    resp.status = ResponseStatus::OK;
    resp.time_ms = time_us / 1000;
    resp.json_data = _serialize_scoring(cc, "coefficient");
    return resp;
}

// ═══════════════════════════════════════════════════════════════════
// JSON 序列化辅助方法
// ═══════════════════════════════════════════════════════════════════

inline std::string RequestHandler::_serialize_scoring(
    const std::unordered_map<std::string, double>& scores,
    const std::string& field_name)
{
    std::ostringstream j;
    j << "[";
    bool first = true;
    for (const auto& [node, score] : scores) {
        if (!first) j << ",";
        j << "{\"node\":\"" << escape_json(node) << "\",\""
          << field_name << "\":" << score << "}";
        first = false;
    }
    j << "]";
    return j.str();
}

inline std::string RequestHandler::_serialize_community(
    const std::unordered_map<std::string, std::string>& communities)
{
    std::ostringstream j;
    j << "[";
    bool first = true;
    for (const auto& [node, community] : communities) {
        if (!first) j << ",";
        j << "{\"node\":\"" << escape_json(node)
          << "\",\"community\":\"" << escape_json(community) << "\"}";
        first = false;
    }
    j << "]";
    return j.str();
}

inline std::string RequestHandler::_serialize_path(const std::vector<std::string>& path) {
    std::ostringstream j;
    j << "{\"path\":[";
    for (size_t i = 0; i < path.size(); ++i) {
        if (i > 0) j << ",";
        j << "\"" << escape_json(path[i]) << "\"";
    }
    j << "],\"path_length\":" << path.size() << "}";
    return j.str();
}

} // namespace server

#endif // SERVER_REQUEST_HANDLER_H
