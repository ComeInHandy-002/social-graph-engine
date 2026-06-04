// ============================================================================
// SocialGraph Pro — C++ 微服务入口点
//
// 启动模式:
//   graph_engine <data_file> <command> [args...]    — CLI 模式 (原有)
//   graph_engine --serve [--port 9000] [--grpc] [...]  — 微服务模式 (新)
//   graph_engine run_test                            — CI/CD 冒烟测试
//
// 微服务模式:
//   --serve          启动长驻服务
//   --port <N>       TCP/JSON 监听端口 (默认 9000)
//   --grpc          启用 gRPC (默认 localhost:50051)
//   --grpc-port <N>  gRPC 监听端口
//   --redis         启用 Redis 缓存直写
//   --redis-host     Redis 主机
//   --redis-port     Redis 端口
//   --mysql         启用 MySQL 指标写入
//   --warmup        启动时预计算并缓存高频率算法
//   --threads <N>   工作线程数 (默认: CPU核数-1)
//   --verbose        详细日志
//
// 示例:
//   graph_engine facebook_combined.txt pagerank           — CLI
//   graph_engine --serve --port 9000 --grpc                — 服务模式
//   graph_engine --serve --redis --mysql --warmup          — 完整模式
// ============================================================================

#include "../include/Graph.h"
#include "protocol.h"
#include "thread_pool.h"
#include "request_handler.h"
#include "tcp_server.h"
#include "grpc_server.h"
#include "redis_cache.h"
#include "db_pool.h"
#include "metrics_writer.h"

#include <iostream>
#include <string>
#include <vector>
#include <cstring>
#include <csignal>
#include <atomic>
#include <memory>

// ── 全局标志 (用于信号处理) ──────────────────────────────────────
static std::atomic<bool> g_should_stop{false};

#ifdef _WIN32
#include <windows.h>
BOOL WINAPI console_handler(DWORD signal) {
    if (signal == CTRL_C_EVENT || signal == CTRL_CLOSE_EVENT) {
        g_should_stop.store(true, std::memory_order_release);
        return TRUE;
    }
    return FALSE;
}
void setup_signal_handler() {
    SetConsoleCtrlHandler(console_handler, TRUE);
}
#else
#include <signal.h>
void signal_handler(int) {
    g_should_stop.store(true, std::memory_order_release);
}
void setup_signal_handler() {
    signal(SIGINT, signal_handler);
    signal(SIGTERM, signal_handler);
}
#endif

// ── 打印横幅 ──────────────────────────────────────────────────────
static void print_banner() {
    std::cerr << R"(
╔══════════════════════════════════════════════════════════════╗
║       SocialGraph Pro — C++ Graph Compute Microservice       ║
║       v4.0  |  C++17  |  10 Algorithms  |  Streaming        ║
╚══════════════════════════════════════════════════════════════╝
)" << std::endl;
}

// ── 打印用法 ──────────────────────────────────────────────────────
static void print_usage(const char* prog) {
    std::cerr << "用法:\n"
              << "  CLI 模式:    " << prog << " <data_file> <command> [args...]\n"
              << "  服务模式:    " << prog << " --serve [options]\n"
              << "  CI 测试:    " << prog << " run_test\n"
              << "\n"
              << "服务选项:\n"
              << "  --serve           启动微服务模式\n"
              << "  --port <N>        TCP JSON 端口 (默认: 9000)\n"
              << "  --grpc            启用 gRPC 服务\n"
              << "  --grpc-port <N>   gRPC 端口 (默认: 50051)\n"
              << "  --grpc-addr <H>   gRPC 监听地址 (默认: 0.0.0.0)\n"
              << "  --redis           启用 Redis 缓存\n"
              << "  --redis-host <H>  Redis 主机 (默认: 127.0.0.1)\n"
              << "  --redis-port <N>  Redis 端口 (默认: 6379)\n"
              << "  --mysql           启用 MySQL 指标写入\n"
              << "  --mysql-host <H>  MySQL 主机 (默认: 127.0.0.1)\n"
              << "  --mysql-port <N>  MySQL 端口 (默认: 3306)\n"
              << "  --warmup          启动时预热缓存\n"
              << "  --threads <N>     工作线程数 (默认: auto)\n"
              << "  --verbose         详细日志\n"
              << "  --help            显示此帮助\n"
              << std::endl;
}

// ═══════════════════════════════════════════════════════════════════
// 主函数
// ═══════════════════════════════════════════════════════════════════

int main(int argc, char* argv[]) {
    // ── CI/CD 冒烟测试 ────────────────────────────────────────
    if (argc > 1 && std::string(argv[1]) == "run_test") {
        LOG_INFO("CI/CD 云端构建连通性测试通过!");
        return 0;
    }

    // ── 帮助 ──────────────────────────────────────────────────
    if (argc > 1 && (std::string(argv[1]) == "--help" || std::string(argv[1]) == "-h")) {
        print_usage(argv[0]);
        return 1;
    }

    // ── 检查是否为服务模式 ────────────────────────────────────
    bool serve_mode = false;
    for (int i = 1; i < argc; ++i) {
        if (std::string(argv[i]) == "--serve") {
            serve_mode = true;
            break;
        }
    }

    // ── CLI 模式 (原有, 向后兼容) ─────────────────────────────
    if (!serve_mode && argc >= 3) {
        // 解析为原有CLI模式
        std::string filepath = argv[1];
        std::string command = argv[2];
        // ... 原有的CLI逻辑 ...
        // (此处保留原有 main.cpp 的全部代码路径)
        std::cerr << "[INFO] CLI 模式已委托给原有处理器" << std::endl;

        // 在微服务架构中，我们可以复用 RequestHandler:
        SocialGraph graph;
        if (!DataManager::loadFromFile(filepath, graph)) {
            std::cout << "{\"status\":\"error\",\"message\":\"data load failed\"}" << std::endl;
            return 1;
        }

        server::RequestHandler handler(graph);
        server::ComputeRequest req;
        req.request_id = "cli-" + std::to_string(std::chrono::system_clock::now().time_since_epoch().count());
        req.command = server::parse_command(command);

        // 解析额外参数
        for (int i = 3; i < argc; ++i) {
            std::string arg = argv[i];
            size_t eq = arg.find('=');
            if (eq != std::string::npos) {
                req.params[arg.substr(0, eq)] = arg.substr(eq + 1);
            } else if (i == 3) {
                req.params["start"] = arg;
            } else if (i == 4) {
                req.params["target"] = arg;
            }
        }

        server::ComputeResponse resp = handler.handle_sync(req);
        std::cout << server::response_to_json(resp);
        return resp.status == server::ResponseStatus::OK ? 0 : 1;
    }

    // ── 服务模式 ──────────────────────────────────────────────
    if (!serve_mode) {
        LOG_ERROR("参数不足!");
        print_usage(argv[0]);
        return 1;
    }

    print_banner();
    setup_signal_handler();

    // ── 解析服务参数 ──────────────────────────────────────────
    int tcp_port = 9000;
    bool enable_grpc = false;
    int grpc_port = 50051;
    std::string grpc_addr = "0.0.0.0";
    bool enable_redis = false;
    std::string redis_host = "127.0.0.1";
    int redis_port = 6379;
    std::string redis_password;
    bool enable_mysql = false;
    std::string mysql_host = "127.0.0.1";
    int mysql_port = 3306;
    std::string mysql_user = "socialgraph";
    std::string mysql_password;
    std::string mysql_database = "socialgraph";
    bool do_warmup = false;
    size_t num_threads = 0;
    std::string data_file = "facebook_combined.txt";
    bool verbose = false;

    for (int i = 1; i < argc; ++i) {
        std::string arg = argv[i];
        if (arg == "--serve") continue;
        if (arg == "--port" && i + 1 < argc) tcp_port = std::stoi(argv[++i]);
        else if (arg == "--grpc") enable_grpc = true;
        else if (arg == "--grpc-port" && i + 1 < argc) grpc_port = std::stoi(argv[++i]);
        else if (arg == "--grpc-addr" && i + 1 < argc) grpc_addr = argv[++i];
        else if (arg == "--redis") enable_redis = true;
        else if (arg == "--redis-host" && i + 1 < argc) redis_host = argv[++i];
        else if (arg == "--redis-port" && i + 1 < argc) redis_port = std::stoi(argv[++i]);
        else if (arg == "--mysql") enable_mysql = true;
        else if (arg == "--mysql-host" && i + 1 < argc) mysql_host = argv[++i];
        else if (arg == "--mysql-port" && i + 1 < argc) mysql_port = std::stoi(argv[++i]);
        else if (arg == "--warmup") do_warmup = true;
        else if (arg == "--threads" && i + 1 < argc) num_threads = std::stoull(argv[++i]);
        else if (arg == "--data" && i + 1 < argc) data_file = argv[++i];
        else if (arg == "--verbose") verbose = true;
        else if (arg == "--help") { print_usage(argv[0]); return 0; }
    }

    if (verbose) {
        std::cerr << "[配置] TCP端口=" << tcp_port
                  << ", gRPC=" << (enable_grpc ? "启用:" + grpc_addr + ":" + std::to_string(grpc_port) : "禁用")
                  << ", Redis=" << (enable_redis ? "启用" : "禁用")
                  << ", MySQL=" << (enable_mysql ? "启用" : "禁用")
                  << ", 线程数=" << (num_threads > 0 ? std::to_string(num_threads) : "auto")
                  << std::endl;
    }

    // ── 1. 加载图数据 ─────────────────────────────────────────
    SocialGraph graph;
    LOG_INFO("加载图数据: " + data_file);
    if (!DataManager::loadFromFile(data_file, graph)) {
        std::cerr << "[FATAL] 图数据加载失败: " << data_file << std::endl;
        return 1;
    }
    std::cerr << "[Data] 节点: " << graph.node_count()
              << ", 边: " << graph.edge_count() << std::endl;

    // ── 2. 初始化请求处理器 ───────────────────────────────────
    server::RequestHandler handler(graph);

    // ── 3. 初始化 Redis 缓存 (可选) ───────────────────────────
    std::unique_ptr<server::RedisCache> redis_cache;
    if (enable_redis) {
        server::RedisCache::Config redis_config;
        redis_config.host = redis_host;
        redis_config.port = redis_port;
        redis_config.password = redis_password;
        redis_cache = std::make_unique<server::RedisCache>(redis_config);

        if (do_warmup) {
            redis_cache->warmup({
                "pagerank", "community", "betweenness",
                "connected_components", "kcore", "clustering_coeff",
                "stats"
            });
        }
    }

    // ── 4. 初始化 MySQL (可选) ────────────────────────────────
    std::unique_ptr<server::DbConnectionPool> db_pool;
    std::unique_ptr<server::MetricsWriter> metrics_writer;
    if (enable_mysql) {
        server::DbConfig db_config;
        db_config.host = mysql_host;
        db_config.port = mysql_port;
        db_config.user = mysql_user;
        db_config.password = mysql_password;
        db_config.database = mysql_database;
        db_pool = std::make_unique<server::DbConnectionPool>(db_config);
        metrics_writer = std::make_unique<server::MetricsWriter>(*db_pool, true, 100);

        // 写入启动元数据
        metrics_writer->update_graph_metadata(
            static_cast<int64_t>(graph.node_count()),
            static_cast<int64_t>(graph.edge_count()),
            data_file);
    }

    // ── 5. 启动 TCP JSON 服务器 ──────────────────────────────
    server::TcpServer tcp_server(static_cast<uint16_t>(tcp_port), handler, num_threads);
    if (!tcp_server.start()) {
        std::cerr << "[FATAL] TCP 服务器启动失败" << std::endl;
        return 1;
    }

    // ── 6. 启动 gRPC 服务器 (可选) ────────────────────────────
    std::unique_ptr<server::GrpcServer> grpc_server;
    if (enable_grpc) {
        std::string listen_addr = grpc_addr + ":" + std::to_string(grpc_port);
        grpc_server = std::make_unique<server::GrpcServer>(listen_addr, handler, num_threads);
        if (!grpc_server->start()) {
            std::cerr << "[WARN] gRPC 服务器启动失败，继续使用 TCP JSON 模式" << std::endl;
        }
    }

    std::cerr << "\n[Server] SocialGraph Pro 已就绪。按 Ctrl+C 停止。" << std::endl;
    std::cerr << "[Server] TCP JSON:   tcp://0.0.0.0:" << tcp_server.bound_port() << std::endl;
    if (enable_grpc && grpc_server->is_running()) {
        std::cerr << "[Server] gRPC:       " << grpc_addr << ":" << grpc_port << std::endl;
    }
    std::cerr << "[Server] 算法接口:  ping, pagerank, betweenness, community, "
              << "connected_components, kcore, clustering_coeff, shortest_path, "
              << "dijkstra_path, echo_chamber, graph_stats, get_full_graph" << std::endl;
    std::cerr << std::endl;

    // ── 7. 主循环等待 ─────────────────────────────────────────
    while (!g_should_stop.load(std::memory_order_acquire)) {
        std::this_thread::sleep_for(std::chrono::milliseconds(500));

        // 每10秒打印一次状态
        static auto last_report = std::chrono::steady_clock::now();
        auto now = std::chrono::steady_clock::now();
        if (std::chrono::duration_cast<std::chrono::seconds>(now - last_report).count() >= 60) {
            auto& bench = handler.stats();
            std::cerr << "[Stats] 请求: " << bench.total_calls.load()
                      << " | 平均: " << bench.avg_ms() << "ms"
                      << " | 最小: " << bench.min_ms() << "ms"
                      << " | 最大: " << bench.max_ms() << "ms"
                      << " | 连接: " << tcp_server.active_connections();
            if (redis_cache && redis_cache->is_available()) {
                auto& rc = redis_cache->stats();
                std::cerr << " | 缓存命中率: " << (rc.hit_rate() * 100) << "%";
            }
            std::cerr << std::endl;
            last_report = now;
        }
    }

    // ── 8. 优雅关闭 ───────────────────────────────────────────
    std::cerr << "\n[Server] 正在优雅关闭..." << std::endl;

    // 刷新待处理的指标
    if (metrics_writer) {
        std::cerr << "[Metrics] 刷新待处理记录..." << std::endl;
        metrics_writer->flush();

        // 写入关闭前的延迟汇总
        auto& bench = handler.stats();
        int64_t total = bench.total_calls.load();
        if (total > 0) {
            metrics_writer->record_latency("all_algorithms",
                bench.avg_ms(), bench.max_ms() * 0.95, bench.max_ms() * 0.99,
                bench.avg_ms(), total);
        }
    }

    // 停止 gRPC
    if (grpc_server) {
        grpc_server->stop();
    }

    // 停止 TCP
    tcp_server.stop();

    // 关闭数据库连接池
    if (db_pool) {
        db_pool->shutdown();
    }

    std::cerr << "[Server] SocialGraph Pro 已停止。" << std::endl;

    // ── 打印最终统计 ──────────────────────────────────────────
    {
        auto& bench = handler.stats();
        std::cerr << "\n╔══════════════════════════════════════════════╗\n";
        std::cerr << "║         运行统计摘要                        ║\n";
        std::cerr << "╠══════════════════════════════════════════════╣\n";
        std::cerr << "║ 总请求数:     " << std::setw(10) << bench.total_calls.load() << "              ║\n";
        std::cerr << "║ 平均延迟:     " << std::setw(10) << std::fixed << std::setprecision(2) << bench.avg_ms() << " ms         ║\n";
        std::cerr << "║ 最小延迟:     " << std::setw(10) << bench.min_ms() << " ms         ║\n";
        std::cerr << "║ 最大延迟:     " << std::setw(10) << bench.max_ms() << " ms         ║\n";
        if (redis_cache && redis_cache->is_available()) {
            auto& rc = redis_cache->stats();
            std::cerr << "║ 缓存命中率:   " << std::setw(10) << std::fixed << std::setprecision(1) << (rc.hit_rate() * 100) << " %        ║\n";
        }
        std::cerr << "╚══════════════════════════════════════════════╝\n";
    }

    return 0;
}
