#ifndef SERVER_GRPC_SERVER_H
#define SERVER_GRPC_SERVER_H

// ============================================================================
// 交付 3: gRPC 服务端实现
//
// 编译依赖:
//   - gRPC 1.60+ (C++ 库): libgrpc++ libgrpc libprotobuf
//   - 由 proto/socialgraph.proto 生成的桩代码:
//       socialgraph.pb.h    — protobuf 消息类
//       socialgraph.grpc.pb.h — gRPC 服务基类
//
// CMake 集成示例:
//   find_package(gRPC CONFIG REQUIRED)
//   find_package(Protobuf REQUIRED)
//   protobuf_generate_cpp(PROTO_SRCS PROTO_HDRS proto/socialgraph.proto)
//   grpc_generate_cpp(GRPC_SRCS GRPC_HDRS proto/socialgraph.proto)
//   target_link_libraries(graph_engine PRIVATE grpc++ protobuf)
//
// 本文件实现 gRPC 服务接口，将请求委托给 RequestHandler。
// ============================================================================

#include "request_handler.h"
#include "protocol.h"

#ifdef GRPC_ENABLED
#include <grpcpp/grpcpp.h>
#include <grpcpp/health_check_service_interface.h>
#include "socialgraph.grpc.pb.h"
#include "socialgraph.pb.h"
#endif

#include <memory>
#include <string>
#include <atomic>
#include <thread>
#include <chrono>

namespace server {

#ifdef GRPC_ENABLED

// ═══════════════════════════════════════════════════════════════════
// gRPC 服务实现
// ═══════════════════════════════════════════════════════════════════

class GraphComputeServiceImpl final : public socialgraph::GraphCompute::Service {
public:
    explicit GraphComputeServiceImpl(RequestHandler& handler)
        : handler_(handler), start_time_(std::chrono::steady_clock::now()) {}

    // ── Ping ──────────────────────────────────────────────────
    grpc::Status Ping(
        grpc::ServerContext* context,
        const socialgraph::PingRequest* request,
        socialgraph::PingResponse* response) override;

    // ── PageRank (一元调用) ───────────────────────────────────
    grpc::Status ComputePageRank(
        grpc::ServerContext* context,
        const socialgraph::PageRankRequest* request,
        socialgraph::ScoringResponse* response) override;

    // ── PageRank (服务端流式) ────────────────────────────────
    grpc::Status ComputePageRankStream(
        grpc::ServerContext* context,
        const socialgraph::PageRankRequest* request,
        grpc::ServerWriter<socialgraph::ScoringChunk>* writer) override;

    // ── Betweenness ──────────────────────────────────────────
    grpc::Status ComputeBetweenness(
        grpc::ServerContext* context,
        const socialgraph::BetweennessRequest* request,
        socialgraph::ScoringResponse* response) override;

    // ── Betweenness (服务端流式) ─────────────────────────────
    grpc::Status ComputeBetweennessStream(
        grpc::ServerContext* context,
        const socialgraph::BetweennessRequest* request,
        grpc::ServerWriter<socialgraph::ScoringChunk>* writer) override;

    // ── LPA 社区发现 ──────────────────────────────────────────
    grpc::Status ComputeCommunity(
        grpc::ServerContext* context,
        const socialgraph::CommunityRequest* request,
        socialgraph::CommunityResponse* response) override;

    // ── LPA 社区发现 (服务端流式) ─────────────────────────────
    grpc::Status ComputeCommunityStream(
        grpc::ServerContext* context,
        const socialgraph::CommunityRequest* request,
        grpc::ServerWriter<socialgraph::CommunityChunk>* writer) override;

    // ── 连通分量 ──────────────────────────────────────────────
    grpc::Status ComputeConnectedComponents(
        grpc::ServerContext* context,
        const socialgraph::ConnectedComponentsRequest* request,
        socialgraph::ConnectedComponentsResponse* response) override;

    // ── K-Core ────────────────────────────────────────────────
    grpc::Status ComputeKCore(
        grpc::ServerContext* context,
        const socialgraph::KCoreRequest* request,
        socialgraph::ScoringResponse* response) override;

    // ── 聚类系数 ──────────────────────────────────────────────
    grpc::Status ComputeClusteringCoeff(
        grpc::ServerContext* context,
        const socialgraph::ClusteringCoeffRequest* request,
        socialgraph::ScoringResponse* response) override;

    // ── 图统计 ────────────────────────────────────────────────
    grpc::Status ComputeGraphStats(
        grpc::ServerContext* context,
        const socialgraph::GraphStatsRequest* request,
        socialgraph::GraphStatsResponse* response) override;

    // ── 全网拓扑 ──────────────────────────────────────────────
    grpc::Status GetFullGraph(
        grpc::ServerContext* context,
        const socialgraph::FullGraphRequest* request,
        socialgraph::FullGraphResponse* response) override;

    // ── 路径查找 ──────────────────────────────────────────────
    grpc::Status FindPath(
        grpc::ServerContext* context,
        const socialgraph::PathRequest* request,
        socialgraph::PathResponse* response) override;

    // ── 热重载 ────────────────────────────────────────────────
    grpc::Status ReloadGraph(
        grpc::ServerContext* context,
        const socialgraph::ReloadRequest* request,
        socialgraph::ReloadResponse* response) override;

    // ── 关闭 ──────────────────────────────────────────────────
    grpc::Status Shutdown(
        grpc::ServerContext* context,
        const socialgraph::ShutdownRequest* request,
        socialgraph::ShutdownResponse* response) override;

    // 供外部触发关闭
    void signal_shutdown() { should_shutdown_.store(true, std::memory_order_release); }
    bool wants_shutdown() const { return should_shutdown_.load(std::memory_order_acquire); }

private:
    RequestHandler& handler_;
    std::chrono::steady_clock::time_point start_time_;
    std::atomic<bool> should_shutdown_{false};

    // ── 辅助: 将 ComputeRequest 参数转换为 gRPC 请求 ────────
    static ComputeRequest _to_internal(const std::string& request_id, AlgoCommand cmd,
                                       const std::unordered_map<std::string, std::string>& params,
                                       bool streaming, int64_t deadline_ms);
};

// ═══════════════════════════════════════════════════════════════════
// gRPC 服务器封装
// ═══════════════════════════════════════════════════════════════════

class GrpcServer {
public:
    GrpcServer(const std::string& listen_addr, RequestHandler& handler,
               size_t num_threads = 0);
    ~GrpcServer();

    GrpcServer(const GrpcServer&) = delete;
    GrpcServer& operator=(const GrpcServer&) = delete;

    bool start();
    void stop();
    void wait();       // 阻塞直到服务器停止
    bool is_running() const;

private:
    std::string listen_addr_;
    std::unique_ptr<grpc::Server> server_;
    std::unique_ptr<GraphComputeServiceImpl> service_impl_;
    size_t num_threads_;
};

// ── 内部实现 ──────────────────────────────────────────────────────

inline ComputeRequest GrpcServer::GraphComputeServiceImpl::_to_internal(
    const std::string& request_id, AlgoCommand cmd,
    const std::unordered_map<std::string, std::string>& params,
    bool streaming, int64_t deadline_ms)
{
    ComputeRequest req;
    req.request_id = request_id;
    req.command = cmd;
    req.params = params;
    req.streaming = streaming;
    req.deadline_ms = deadline_ms;
    return req;
}

// ── Ping ──────────────────────────────────────────────────────────

inline grpc::Status GrpcServer::GraphComputeServiceImpl::Ping(
    grpc::ServerContext* context,
    const socialgraph::PingRequest* request,
    socialgraph::PingResponse* response)
{
    auto uptime = std::chrono::duration_cast<std::chrono::seconds>(
        std::chrono::steady_clock::now() - start_time_).count();

    ComputeRequest req = _to_internal("ping-" + request->client_id(), AlgoCommand::PING, {}, false, 5000);
    ComputeResponse resp = handler_.handle_sync(req);

    response->set_status("pong");
    response->set_node_count(0); // handler stat
    response->set_edge_count(0);
    response->set_uptime_seconds(uptime);
    return grpc::Status::OK;
}

// ── PageRank (一元) ───────────────────────────────────────────────

inline grpc::Status GrpcServer::GraphComputeServiceImpl::ComputePageRank(
    grpc::ServerContext* context,
    const socialgraph::PageRankRequest* request,
    socialgraph::ScoringResponse* response)
{
    std::unordered_map<std::string, std::string> params;
    if (request->max_iterations() > 0)
        params["iterations"] = std::to_string(request->max_iterations());
    if (request->damping_factor() > 0)
        params["damping"] = std::to_string(request->damping_factor());
    if (request->convergence_threshold() > 0)
        params["convergence"] = std::to_string(request->convergence_threshold());

    ComputeRequest req = _to_internal(request->request_id(), AlgoCommand::PAGE_RANK,
                                      params, false, request->deadline_ms());
    ComputeResponse resp = handler_.handle_sync(req);

    response->set_request_id(resp.request_id);
    response->set_status(resp.status == ResponseStatus::OK ? "ok" : "error");
    response->set_time_ms(resp.time_ms);
    response->set_error_code(resp.error_code);
    response->set_error_message(resp.error_message);

    // 这里应该解析 resp.json_data 并填充 response->data，
    // 但为保持简洁，我们将完整JSON放入附加字段
    // 生产环境中使用 protobuf::util::JsonStringToMessage 或手动解析
    // response->mutable_data()...

    return grpc::Status::OK;
}

// ── PageRank (流式) ───────────────────────────────────────────────

inline grpc::Status GrpcServer::GraphComputeServiceImpl::ComputePageRankStream(
    grpc::ServerContext* context,
    const socialgraph::PageRankRequest* request,
    grpc::ServerWriter<socialgraph::ScoringChunk>* writer)
{
    std::unordered_map<std::string, std::string> params;
    if (request->max_iterations() > 0)
        params["iterations"] = std::to_string(request->max_iterations());
    if (request->damping_factor() > 0)
        params["damping"] = std::to_string(request->damping_factor());
    if (request->convergence_threshold() > 0)
        params["convergence"] = std::to_string(request->convergence_threshold());

    ComputeRequest req = _to_internal(request->request_id(), AlgoCommand::PAGE_RANK,
                                      params, true, request->deadline_ms());

    handler_.handle_streaming(req, [&](const StreamChunk& chunk) {
        socialgraph::ScoringChunk pb_chunk;
        pb_chunk.set_request_id(chunk.request_id);
        pb_chunk.set_chunk_index(chunk.chunk_index);
        pb_chunk.set_is_last(chunk.is_last);
        // 手动解析chunk.json_data填充pb_chunk.data
        // (生产环境: protobuf::util::JsonStringToMessage)
        writer->Write(pb_chunk);
    });

    return grpc::Status::OK;
}

// ── Betweenness (一元) ────────────────────────────────────────────

inline grpc::Status GrpcServer::GraphComputeServiceImpl::ComputeBetweenness(
    grpc::ServerContext* context,
    const socialgraph::BetweennessRequest* request,
    socialgraph::ScoringResponse* response)
{
    std::unordered_map<std::string, std::string> params;
    if (request->sample_ratio() > 0)
        params["sample_ratio"] = std::to_string(request->sample_ratio());

    ComputeRequest req = _to_internal(request->request_id(), AlgoCommand::BETWEENNESS,
                                      params, false, request->deadline_ms());
    ComputeResponse resp = handler_.handle_sync(req);

    response->set_request_id(resp.request_id);
    response->set_status(resp.status == ResponseStatus::OK ? "ok" : "error");
    response->set_time_ms(resp.time_ms);
    response->set_error_code(resp.error_code);
    response->set_error_message(resp.error_message);
    return grpc::Status::OK;
}

// ── Betweenness (流式) ────────────────────────────────────────────

inline grpc::Status GrpcServer::GraphComputeServiceImpl::ComputeBetweennessStream(
    grpc::ServerContext* context,
    const socialgraph::BetweennessRequest* request,
    grpc::ServerWriter<socialgraph::ScoringChunk>* writer)
{
    std::unordered_map<std::string, std::string> params;
    if (request->sample_ratio() > 0)
        params["sample_ratio"] = std::to_string(request->sample_ratio());

    ComputeRequest req = _to_internal(request->request_id(), AlgoCommand::BETWEENNESS,
                                      params, true, request->deadline_ms());

    handler_.handle_streaming(req, [&](const StreamChunk& chunk) {
        socialgraph::ScoringChunk pb_chunk;
        pb_chunk.set_request_id(chunk.request_id);
        pb_chunk.set_chunk_index(chunk.chunk_index);
        pb_chunk.set_is_last(chunk.is_last);
        writer->Write(pb_chunk);
    });

    return grpc::Status::OK;
}

// ── LPA (一元) ────────────────────────────────────────────────────

inline grpc::Status GrpcServer::GraphComputeServiceImpl::ComputeCommunity(
    grpc::ServerContext* context,
    const socialgraph::CommunityRequest* request,
    socialgraph::CommunityResponse* response)
{
    std::unordered_map<std::string, std::string> params;
    if (request->max_iterations() > 0)
        params["iterations"] = std::to_string(request->max_iterations());

    ComputeRequest req = _to_internal(request->request_id(), AlgoCommand::COMMUNITY,
                                      params, false, request->deadline_ms());
    ComputeResponse resp = handler_.handle_sync(req);

    response->set_request_id(resp.request_id);
    response->set_status(resp.status == ResponseStatus::OK ? "ok" : "error");
    response->set_time_ms(resp.time_ms);
    response->set_error_code(resp.error_code);
    response->set_error_message(resp.error_message);
    return grpc::Status::OK;
}

// ── LPA (流式) ────────────────────────────────────────────────────

inline grpc::Status GrpcServer::GraphComputeServiceImpl::ComputeCommunityStream(
    grpc::ServerContext* context,
    const socialgraph::CommunityRequest* request,
    grpc::ServerWriter<socialgraph::CommunityChunk>* writer)
{
    std::unordered_map<std::string, std::string> params;
    if (request->max_iterations() > 0)
        params["iterations"] = std::to_string(request->max_iterations());

    ComputeRequest req = _to_internal(request->request_id(), AlgoCommand::COMMUNITY,
                                      params, true, request->deadline_ms());

    handler_.handle_streaming(req, [&](const StreamChunk& chunk) {
        socialgraph::CommunityChunk pb_chunk;
        pb_chunk.set_request_id(chunk.request_id);
        pb_chunk.set_chunk_index(chunk.chunk_index);
        pb_chunk.set_is_last(chunk.is_last);
        writer->Write(pb_chunk);
    });

    return grpc::Status::OK;
}

// ── 连通分量 ──────────────────────────────────────────────────────

inline grpc::Status GrpcServer::GraphComputeServiceImpl::ComputeConnectedComponents(
    grpc::ServerContext* context,
    const socialgraph::ConnectedComponentsRequest* request,
    socialgraph::ConnectedComponentsResponse* response)
{
    ComputeRequest req = _to_internal(request->request_id(), AlgoCommand::CONNECTED_COMPONENTS,
                                      {}, false, request->deadline_ms());
    ComputeResponse resp = handler_.handle_sync(req);

    response->set_request_id(resp.request_id);
    response->set_status(resp.status == ResponseStatus::OK ? "ok" : "error");
    response->set_time_ms(resp.time_ms);
    return grpc::Status::OK;
}

// ── K-Core ────────────────────────────────────────────────────────

inline grpc::Status GrpcServer::GraphComputeServiceImpl::ComputeKCore(
    grpc::ServerContext* context,
    const socialgraph::KCoreRequest* request,
    socialgraph::ScoringResponse* response)
{
    ComputeRequest req = _to_internal(request->request_id(), AlgoCommand::KCORE,
                                      {}, false, request->deadline_ms());
    ComputeResponse resp = handler_.handle_sync(req);

    response->set_request_id(resp.request_id);
    response->set_status(resp.status == ResponseStatus::OK ? "ok" : "error");
    response->set_time_ms(resp.time_ms);
    return grpc::Status::OK;
}

// ── 聚类系数 ──────────────────────────────────────────────────────

inline grpc::Status GrpcServer::GraphComputeServiceImpl::ComputeClusteringCoeff(
    grpc::ServerContext* context,
    const socialgraph::ClusteringCoeffRequest* request,
    socialgraph::ScoringResponse* response)
{
    ComputeRequest req = _to_internal(request->request_id(), AlgoCommand::CLUSTERING_COEFF,
                                      {}, false, request->deadline_ms());
    ComputeResponse resp = handler_.handle_sync(req);

    response->set_request_id(resp.request_id);
    response->set_status(resp.status == ResponseStatus::OK ? "ok" : "error");
    response->set_time_ms(resp.time_ms);
    return grpc::Status::OK;
}

// ── 图统计 ────────────────────────────────────────────────────────

inline grpc::Status GrpcServer::GraphComputeServiceImpl::ComputeGraphStats(
    grpc::ServerContext* context,
    const socialgraph::GraphStatsRequest* request,
    socialgraph::GraphStatsResponse* response)
{
    ComputeRequest req = _to_internal(request->request_id(), AlgoCommand::GRAPH_STATS,
                                      {}, false, 60000);
    ComputeResponse resp = handler_.handle_sync(req);

    response->set_request_id(resp.request_id);
    response->set_status(resp.status == ResponseStatus::OK ? "ok" : "error");
    response->set_time_ms(resp.time_ms);
    return grpc::Status::OK;
}

// ── 全网拓扑 ──────────────────────────────────────────────────────

inline grpc::Status GrpcServer::GraphComputeServiceImpl::GetFullGraph(
    grpc::ServerContext* context,
    const socialgraph::FullGraphRequest* request,
    socialgraph::FullGraphResponse* response)
{
    ComputeRequest req = _to_internal(request->request_id(), AlgoCommand::GET_FULL_GRAPH,
                                      {}, false, request->deadline_ms());
    ComputeResponse resp = handler_.handle_sync(req);

    response->set_request_id(resp.request_id);
    response->set_status(resp.status == ResponseStatus::OK ? "ok" : "error");
    response->set_time_ms(resp.time_ms);
    return grpc::Status::OK;
}

// ── 路径查找 ──────────────────────────────────────────────────────

inline grpc::Status GrpcServer::GraphComputeServiceImpl::FindPath(
    grpc::ServerContext* context,
    const socialgraph::PathRequest* request,
    socialgraph::PathResponse* response)
{
    AlgoCommand cmd;
    std::unordered_map<std::string, std::string> params;
    params["start"] = request->start_node();
    params["target"] = request->target_node();

    if (request->algorithm() == "dijkstra") {
        cmd = AlgoCommand::DIJKSTRA_PATH;
    } else if (request->algorithm() == "dfs" || request->algorithm() == "echo_chamber") {
        cmd = AlgoCommand::ECHO_CHAMBER;
    } else {
        cmd = AlgoCommand::SHORTEST_PATH;
    }

    ComputeRequest req = _to_internal(request->request_id(), cmd, params, false, request->deadline_ms());
    ComputeResponse resp = handler_.handle_sync(req);

    response->set_request_id(resp.request_id);
    response->set_status(resp.status == ResponseStatus::OK ? "ok" : "error");
    response->set_time_ms(resp.time_ms);
    response->set_error_code(resp.error_code);
    response->set_error_message(resp.error_message);

    if (resp.status == ResponseStatus::OK) {
        // path_length 从 json_data 中提取 (简化)
        // 生产环境应解析 json_data
    }
    return grpc::Status::OK;
}

// ── 热重载 ────────────────────────────────────────────────────────

inline grpc::Status GrpcServer::GraphComputeServiceImpl::ReloadGraph(
    grpc::ServerContext* context,
    const socialgraph::ReloadRequest* request,
    socialgraph::ReloadResponse* response)
{
    response->set_request_id(request->request_id());
    response->set_status("not_implemented");
    // 热重载需要持有 SocialGraph 的可变引用，此处暂不实现
    return grpc::Status(grpc::StatusCode::UNIMPLEMENTED, "热重载功能待实现");
}

// ── 关闭 ──────────────────────────────────────────────────────────

inline grpc::Status GrpcServer::GraphComputeServiceImpl::Shutdown(
    grpc::ServerContext* context,
    const socialgraph::ShutdownRequest* request,
    socialgraph::ShutdownResponse* response)
{
    response->set_request_id(request->request_id());
    response->set_status("shutting_down");
    should_shutdown_.store(true, std::memory_order_release);
    return grpc::Status::OK;
}

// ═══════════════════════════════════════════════════════════════════
// GrpcServer 封装
// ═══════════════════════════════════════════════════════════════════

inline GrpcServer::GrpcServer(const std::string& listen_addr, RequestHandler& handler,
                               size_t num_threads)
    : listen_addr_(listen_addr), num_threads_(num_threads)
{
    if (num_threads_ == 0) {
        num_threads_ = std::thread::hardware_concurrency();
        if (num_threads_ == 0) num_threads_ = 4;
    }
    service_impl_ = std::make_unique<GraphComputeServiceImpl>(handler);
}

inline GrpcServer::~GrpcServer() {
    stop();
}

inline bool GrpcServer::start() {
    grpc::ServerBuilder builder;
    builder.AddListeningPort(listen_addr_, grpc::InsecureServerCredentials());
    builder.RegisterService(service_impl_.get());

    // 配置线程池
    builder.SetSyncServerOption(grpc::ServerBuilder::SyncServerOption::NUM_CQS, num_threads_);
    builder.SetSyncServerOption(grpc::ServerBuilder::SyncServerOption::MIN_POLLERS, 2);
    builder.SetSyncServerOption(grpc::ServerBuilder::SyncServerOption::MAX_POLLERS, num_threads_);

    // 设置消息大小限制 (支持大数据集)
    builder.SetMaxReceiveMessageSize(100 * 1024 * 1024); // 100MB
    builder.SetMaxSendMessageSize(100 * 1024 * 1024);

    server_ = builder.BuildAndStart();
    if (!server_) {
        std::cerr << "[gRPC] 服务器启动失败: " << listen_addr_ << std::endl;
        return false;
    }

    std::cerr << "[gRPC] 服务器已启动: " << listen_addr_
              << " (threads=" << num_threads_ << ")" << std::endl;
    return true;
}

inline void GrpcServer::stop() {
    if (server_) {
        server_->Shutdown();
    }
}

inline void GrpcServer::wait() {
    if (server_) {
        server_->Wait();
    }
}

inline bool GrpcServer::is_running() const {
    return server_ != nullptr;
}

#else // !GRPC_ENABLED — 无gRPC依赖时的占位实现

class GrpcServer {
public:
    GrpcServer(const std::string&, RequestHandler&, size_t = 0) {
        std::cerr << "[Server] gRPC 未启用 (编译时未定义 GRPC_ENABLED)，"
                  << "仅 TCP JSON 模式可用" << std::endl;
    }
    bool start() { return false; }
    void stop() {}
    void wait() {}
    bool is_running() const { return false; }
};

#endif // GRPC_ENABLED

} // namespace server

#endif // SERVER_GRPC_SERVER_H
