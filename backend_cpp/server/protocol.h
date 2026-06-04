#ifndef SERVER_PROTOCOL_H
#define SERVER_PROTOCOL_H

// ============================================================================
// 交付 1 + 3: 请求/响应协议定义
// 支持两种传输模式：
//   Mode A (TCP JSON):  行分隔 JSON, 人可读, curl可测
//   Mode B (gRPC):      protobuf二进制, 通过 proto/socialgraph.proto 定义
//
// JSON 协议格式 (TCP模式):
//   Request:  {"id":"uuid","cmd":"pagerank","params":{"iterations":100},"stream":false}
//   Response: {"id":"uuid","status":"ok","time_ms":42,"data":{...}}
//   Stream:   {"id":"uuid","chunk":0,"data":[...]}
//   Error:    {"id":"uuid","status":"error","code":404,"message":"..."}
//
// 所有行以 \n 分隔。流式结果以 chunk 字段区分。
// ============================================================================

#include <string>
#include <vector>
#include <unordered_map>
#include <variant>
#include <optional>
#include <cstdint>
#include <sstream>
#include <iomanip>

namespace server {

// ── 算法命令枚举 ───────────────────────────────────────────────
enum class AlgoCommand : uint8_t {
    PING = 0,
    PAGE_RANK,
    COMMUNITY,
    BETWEENNESS,
    CONNECTED_COMPONENTS,
    KCORE,
    CLUSTERING_COEFF,
    SHORTEST_PATH,
    DIJKSTRA_PATH,
    ECHO_CHAMBER,
    GRAPH_STATS,
    GET_FULL_GRAPH,
    RELOAD_GRAPH,       // 热重载图数据
    SHUTDOWN,
    UNKNOWN = 255
};

inline AlgoCommand parse_command(const std::string& cmd) {
    static const std::unordered_map<std::string, AlgoCommand> map = {
        {"ping",                AlgoCommand::PING},
        {"pagerank",            AlgoCommand::PAGE_RANK},
        {"community",           AlgoCommand::COMMUNITY},
        {"betweenness",         AlgoCommand::BETWEENNESS},
        {"connected_components",AlgoCommand::CONNECTED_COMPONENTS},
        {"kcore",              AlgoCommand::KCORE},
        {"clustering_coeff",   AlgoCommand::CLUSTERING_COEFF},
        {"shortest_path",      AlgoCommand::SHORTEST_PATH},
        {"dijkstra_path",      AlgoCommand::DIJKSTRA_PATH},
        {"echo_chamber",       AlgoCommand::ECHO_CHAMBER},
        {"graph_stats",        AlgoCommand::GRAPH_STATS},
        {"get_full_graph",     AlgoCommand::GET_FULL_GRAPH},
        {"reload_graph",       AlgoCommand::RELOAD_GRAPH},
        {"shutdown",           AlgoCommand::SHUTDOWN},
    };
    auto it = map.find(cmd);
    return (it != map.end()) ? it->second : AlgoCommand::UNKNOWN;
}

inline std::string command_name(AlgoCommand cmd) {
    switch (cmd) {
        case AlgoCommand::PING:                  return "ping";
        case AlgoCommand::PAGE_RANK:             return "pagerank";
        case AlgoCommand::COMMUNITY:             return "community";
        case AlgoCommand::BETWEENNESS:           return "betweenness";
        case AlgoCommand::CONNECTED_COMPONENTS:  return "connected_components";
        case AlgoCommand::KCORE:                 return "kcore";
        case AlgoCommand::CLUSTERING_COEFF:      return "clustering_coeff";
        case AlgoCommand::SHORTEST_PATH:         return "shortest_path";
        case AlgoCommand::DIJKSTRA_PATH:         return "dijkstra_path";
        case AlgoCommand::ECHO_CHAMBER:          return "echo_chamber";
        case AlgoCommand::GRAPH_STATS:           return "graph_stats";
        case AlgoCommand::GET_FULL_GRAPH:        return "get_full_graph";
        case AlgoCommand::RELOAD_GRAPH:           return "reload_graph";
        case AlgoCommand::SHUTDOWN:              return "shutdown";
        default: return "unknown";
    }
}

// ── 请求结构 ────────────────────────────────────────────────────
struct ComputeRequest {
    std::string request_id;             // 客户端生成UUID，用于关联请求/响应
    AlgoCommand command;
    std::unordered_map<std::string, std::string> params;
    bool streaming = false;             // 是否启用流式返回
    int64_t deadline_ms = 60000;        // 请求超时(ms)

    // 便捷参数访问
    std::optional<std::string> get_param(const std::string& key) const {
        auto it = params.find(key);
        if (it != params.end()) return it->second;
        return std::nullopt;
    }
};

// ── 响应状态 ────────────────────────────────────────────────────
enum class ResponseStatus : uint8_t {
    OK = 0,
    ERROR = 1,
    STREAMING = 2,          // 流式传输中
    STREAM_END = 3,         // 流式结束
    TIMEOUT = 4,
};

// ── 响应结构 (非流式) ────────────────────────────────────────────
struct ComputeResponse {
    std::string request_id;
    ResponseStatus status = ResponseStatus::OK;
    int64_t time_ms = 0;
    int error_code = 0;
    std::string error_message;
    std::string json_data;          // JSON 序列化的结果数据
};

// ── 流式块 ──────────────────────────────────────────────────────
// 用于 PageRank / Betweenness 等大规模算法，逐批返回结果
struct StreamChunk {
    std::string request_id;
    uint32_t chunk_index = 0;
    bool is_last = false;
    std::string json_data;          // 此批次的结果JSON
};

// ── JSON 序列化工具函数 ─────────────────────────────────────────
// 使用手写序列化避免引入第三方JSON库，保持零依赖原则

inline std::string escape_json(const std::string& s) {
    std::ostringstream oss;
    for (char c : s) {
        switch (c) {
            case '"':  oss << "\\\""; break;
            case '\\': oss << "\\\\"; break;
            case '\n': oss << "\\n";  break;
            case '\r': oss << "\\r";  break;
            case '\t': oss << "\\t";  break;
            default:   oss << c;
        }
    }
    return oss.str();
}

// 请求JSON: {"id":"...","cmd":"...","params":{...},"streaming":bool,"deadline_ms":int}
inline std::string request_to_json(const ComputeRequest& req) {
    std::ostringstream j;
    j << "{\"id\":\"" << escape_json(req.request_id) << "\""
      << ",\"cmd\":\"" << command_name(req.command) << "\"";
    if (!req.params.empty()) {
        j << ",\"params\":{";
        bool first = true;
        for (const auto& [k, v] : req.params) {
            if (!first) j << ",";
            j << "\"" << escape_json(k) << "\":\"" << escape_json(v) << "\"";
            first = false;
        }
        j << "}";
    }
    if (req.streaming) {
        j << ",\"streaming\":true";
    }
    if (req.deadline_ms != 60000) {
        j << ",\"deadline_ms\":" << req.deadline_ms;
    }
    j << "}\n";
    return j.str();
}

// 响应JSON: {"id":"...","status":"ok","time_ms":42,"data":{...}}
inline std::string response_to_json(const ComputeResponse& resp) {
    std::ostringstream j;
    j << "{\"id\":\"" << escape_json(resp.request_id) << "\"";
    switch (resp.status) {
        case ResponseStatus::OK:         j << ",\"status\":\"ok\""; break;
        case ResponseStatus::ERROR:      j << ",\"status\":\"error\""; break;
        case ResponseStatus::TIMEOUT:    j << ",\"status\":\"timeout\""; break;
        case ResponseStatus::STREAM_END: j << ",\"status\":\"stream_end\""; break;
        default:                         j << ",\"status\":\"unknown\""; break;
    }
    j << ",\"time_ms\":" << resp.time_ms;
    if (resp.error_code != 0) {
        j << ",\"error_code\":" << resp.error_code
          << ",\"error_message\":\"" << escape_json(resp.error_message) << "\"";
    }
    if (!resp.json_data.empty()) {
        // json_data 是已序列化的JSON，直接拼接
        j << ",\"data\":" << resp.json_data;
    }
    j << "}\n";
    return j.str();
}

// 流式块JSON: {"id":"...","chunk":N,"data":[...],"last":bool}
inline std::string chunk_to_json(const StreamChunk& chunk) {
    std::ostringstream j;
    j << "{\"id\":\"" << escape_json(chunk.request_id) << "\""
      << ",\"chunk\":" << chunk.chunk_index;
    if (!chunk.json_data.empty()) {
        j << ",\"data\":" << chunk.json_data;
    }
    if (chunk.is_last) {
        j << ",\"last\":true";
    }
    j << "}\n";
    return j.str();
}

// ── 从原始文本行解析请求 ────────────────────────────────────────
// 最小JSON解析器：仅解析我们需要的字段，避免引入依赖
inline std::optional<ComputeRequest> parse_request_line(const std::string& line) {
    // 简化版JSON解析 — 生产环境中考虑使用 nlohmann/json 或 rapidjson
    // 此处实现支持 { "id":"...", "cmd":"...", "params":{...}, "streaming":true/false, "deadline_ms":N }
    ComputeRequest req;

    auto find_field = [&](const std::string& key) -> std::optional<std::string> {
        size_t pos = line.find("\"" + key + "\"");
        if (pos == std::string::npos) return std::nullopt;
        pos = line.find(':', pos + key.length() + 2);
        if (pos == std::string::npos) return std::nullopt;
        // 跳过空白和引号
        while (pos < line.length() && (line[pos] == ':' || line[pos] == ' ' || line[pos] == '\t')) ++pos;
        if (pos >= line.length()) return std::nullopt;

        if (line[pos] == '"') {
            // 字符串值
            size_t end = pos + 1;
            while (end < line.length() && line[end] != '"') {
                if (line[end] == '\\') ++end; // 跳过转义
                ++end;
            }
            return line.substr(pos + 1, end - pos - 1);
        } else if (line[pos] == 't' || line[pos] == 'f') {
            // 布尔值
            size_t end = pos;
            while (end < line.length() && std::isalpha(static_cast<unsigned char>(line[end]))) ++end;
            return line.substr(pos, end - pos);
        } else {
            // 数值
            size_t end = pos;
            while (end < line.length() && (std::isdigit(static_cast<unsigned char>(line[end])) || line[end] == '.' || line[end] == '-')) ++end;
            return line.substr(pos, end - pos);
        }
    };

    auto id = find_field("id");
    auto cmd = find_field("cmd");
    if (!id || !cmd) {
        return std::nullopt;
    }
    req.request_id = *id;
    req.command = parse_command(*cmd);

    // 可选参数 streaming
    auto streaming = find_field("streaming");
    if (streaming && *streaming == "true") {
        req.streaming = true;
    }

    // 可选参数 deadline_ms
    auto deadline = find_field("deadline_ms");
    if (deadline) {
        try { req.deadline_ms = std::stoll(*deadline); } catch (...) {}
    }

    // 解析 params 子对象 (简化: 查找 "params" 后的 { ... })
    size_t params_pos = line.find("\"params\"");
    if (params_pos != std::string::npos) {
        size_t open_brace = line.find('{', params_pos);
        size_t close_brace = line.find('}', open_brace);
        if (open_brace != std::string::npos && close_brace != std::string::npos) {
            std::string params_str = line.substr(open_brace + 1, close_brace - open_brace - 1);
            // 解析 "key":"value" 对
            size_t i = 0;
            while (i < params_str.length()) {
                // 跳过空白和逗号
                while (i < params_str.length() && (params_str[i] == ' ' || params_str[i] == ',' || params_str[i] == '\t')) ++i;
                if (i >= params_str.length()) break;
                if (params_str[i] != '"') break;

                size_t key_start = i + 1;
                size_t key_end = params_str.find('"', key_start);
                if (key_end == std::string::npos) break;
                std::string key = params_str.substr(key_start, key_end - key_start);

                size_t colon = params_str.find(':', key_end + 1);
                if (colon == std::string::npos) break;

                size_t val_start = colon + 1;
                while (val_start < params_str.length() && (params_str[val_start] == ' ' || params_str[val_start] == '\t')) ++val_start;
                if (val_start >= params_str.length()) break;

                std::string val;
                if (params_str[val_start] == '"') {
                    size_t val_end = params_str.find('"', val_start + 1);
                    if (val_end == std::string::npos) break;
                    val = params_str.substr(val_start + 1, val_end - val_start - 1);
                    i = val_end + 1;
                } else {
                    size_t val_end = val_start;
                    while (val_end < params_str.length() && params_str[val_end] != ',' && params_str[val_end] != '}') ++val_end;
                    val = params_str.substr(val_start, val_end - val_start);
                    // trim
                    while (!val.empty() && val.back() == ' ') val.pop_back();
                    i = val_end;
                }
                req.params[key] = val;
            }
        }
    }

    return req;
}

// ── 缓存键命名规范 (与Python端保持统一) ─────────────────────────
inline std::string cache_key_for(const std::string& algorithm, const std::string& version = "v1") {
    return "sgp:algo:" + algorithm + ":" + version;
}
// 兼容旧Python风格
inline std::string cache_key_legacy(const std::string& algorithm, const std::string& version = "v1") {
    return "social_graph:" + algorithm + ":" + version;
}

} // namespace server

#endif // SERVER_PROTOCOL_H
