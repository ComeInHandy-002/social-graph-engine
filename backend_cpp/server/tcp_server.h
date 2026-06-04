#ifndef SERVER_TCP_SERVER_H
#define SERVER_TCP_SERVER_H

// ============================================================================
// 交付 1: TCP 服务器 (事件驱动模型)
//
// 架构:
//   - 单线程 accept 循环，为每个连接创建独立的处理线程
//   - (或者) 使用 epoll/kqueue/IOCP 事件循环处理多连接
//   - 此处实现简化但功能完备的 "每连接一线程" 模型，
//     生产环境可升级为 Boost.Asio 事件驱动模型
//
// 协议:
//   - 行分隔JSON (每行以 \n 结尾)
//   - 客户端发送 Request JSON → 服务器返回 Response JSON (或Stream Chunk)
//   - 连接可复用: 在单连接上发送多个请求 (HTTP/1.1 Keep-Alive 类似)
// ============================================================================

#include "protocol.h"
#include "request_handler.h"
#include "thread_pool.h"

#include <string>
#include <thread>
#include <atomic>
#include <memory>
#include <functional>
#include <cstring>

#ifdef _WIN32
    #include <winsock2.h>
    #include <ws2tcpip.h>
    #pragma comment(lib, "ws2_32.lib")
    using socklen_t = int;
    #define SHUT_RDWR SD_BOTH
#else
    #include <sys/socket.h>
    #include <netinet/in.h>
    #include <netinet/tcp.h>
    #include <unistd.h>
    #include <arpa/inet.h>
    #include <fcntl.h>
    #include <errno.h>
    #include <signal.h>
    using SOCKET = int;
    constexpr int INVALID_SOCKET = -1;
    constexpr int SOCKET_ERROR = -1;
    #define closesocket close
#endif

namespace server {

class TcpServer {
public:
    TcpServer(uint16_t port, RequestHandler& handler, size_t io_threads = 4);
    ~TcpServer();

    // 禁止复制
    TcpServer(const TcpServer&) = delete;
    TcpServer& operator=(const TcpServer&) = delete;

    // 启动服务器 (非阻塞: 在单独线程中运行 accept 循环)
    bool start();

    // 停止服务器 (优雅关闭: 停止accept → 等待活跃连接结束)
    void stop();

    // 等待服务器线程退出
    void join();

    // 运行状态
    bool is_running() const { return running_.load(std::memory_order_acquire); }

    // 获取绑定端口 (如果port=0 则获取系统分配端口)
    uint16_t bound_port() const { return port_; }

    // 活跃连接数
    size_t active_connections() const { return conn_count_.load(std::memory_order_acquire); }

private:
    void accept_loop();
    void handle_client(SOCKET client_sock, const std::string& client_addr);

    // 从socket读取一行
    static std::optional<std::string> read_line(SOCKET sock, std::string& buffer);

    // 向socket写入完整数据
    static bool write_all(SOCKET sock, const std::string& data);

    uint16_t port_;
    RequestHandler& handler_;
    size_t io_threads_;

    SOCKET listen_sock_ = INVALID_SOCKET;
    std::thread accept_thread_;

    std::atomic<bool> running_{false};
    std::atomic<size_t> conn_count_{0};

    // Socket初始化 (跨平台)
    static bool init_sockets();
    static void cleanup_sockets();
};

// ═══════════════════════════════════════════════════════════════════
// 构造 / 析构
// ═══════════════════════════════════════════════════════════════════

inline TcpServer::TcpServer(uint16_t port, RequestHandler& handler, size_t io_threads)
    : port_(port), handler_(handler), io_threads_(io_threads)
{
    init_sockets();
}

inline TcpServer::~TcpServer() {
    stop();
#ifdef _WIN32
    cleanup_sockets();
#endif
}

// ═══════════════════════════════════════════════════════════════════
// 跨平台 Socket 初始化
// ═══════════════════════════════════════════════════════════════════

inline bool TcpServer::init_sockets() {
#ifdef _WIN32
    WSADATA wsa_data;
    if (WSAStartup(MAKEWORD(2, 2), &wsa_data) != 0) {
        std::cerr << "[TCP] WSAStartup 失败" << std::endl;
        return false;
    }
#endif
#ifndef _WIN32
    // 忽略 SIGPIPE (防止向已关闭socket写入时进程退出)
    signal(SIGPIPE, SIG_IGN);
#endif
    return true;
}

inline void TcpServer::cleanup_sockets() {
#ifdef _WIN32
    WSACleanup();
#endif
}

// ═══════════════════════════════════════════════════════════════════
// 启动
// ═══════════════════════════════════════════════════════════════════

inline bool TcpServer::start() {
    if (running_.load(std::memory_order_acquire)) {
        std::cerr << "[TCP] 服务器已在运行" << std::endl;
        return false;
    }

    // 创建监听 socket
    listen_sock_ = socket(AF_INET, SOCK_STREAM, 0);
    if (listen_sock_ == INVALID_SOCKET) {
        std::cerr << "[TCP] 创建socket失败" << std::endl;
        return false;
    }

    // 设置 SO_REUSEADDR (快速重启)
    int opt = 1;
    setsockopt(listen_sock_, SOL_SOCKET, SO_REUSEADDR,
#ifdef _WIN32
               reinterpret_cast<const char*>(&opt),
#else
               &opt,
#endif
               sizeof(opt));

    // 绑定
    struct sockaddr_in addr;
    std::memset(&addr, 0, sizeof(addr));
    addr.sin_family = AF_INET;
    addr.sin_addr.s_addr = INADDR_ANY;
    addr.sin_port = htons(port_);

    if (bind(listen_sock_, reinterpret_cast<struct sockaddr*>(&addr), sizeof(addr)) != 0) {
        std::cerr << "[TCP] 绑定端口 " << port_ << " 失败" << std::endl;
        closesocket(listen_sock_);
        listen_sock_ = INVALID_SOCKET;
        return false;
    }

    // 如果 port_==0 则读取系统分配的实际端口
    if (port_ == 0) {
        socklen_t addr_len = sizeof(addr);
        getsockname(listen_sock_, reinterpret_cast<struct sockaddr*>(&addr), &addr_len);
        port_ = ntohs(addr.sin_port);
    }

    // 监听
    constexpr int BACKLOG = 128;
    if (listen(listen_sock_, BACKLOG) != 0) {
        std::cerr << "[TCP] 监听失败" << std::endl;
        closesocket(listen_sock_);
        listen_sock_ = INVALID_SOCKET;
        return false;
    }

    running_.store(true, std::memory_order_release);
    accept_thread_ = std::thread(&TcpServer::accept_loop, this);

    std::cerr << "[TCP] 服务器已启动: 0.0.0.0:" << port_
              << " (io_threads=" << io_threads_ << ")" << std::endl;
    return true;
}

// ═══════════════════════════════════════════════════════════════════
// 停止
// ═══════════════════════════════════════════════════════════════════

inline void TcpServer::stop() {
    if (!running_.load(std::memory_order_acquire)) return;

    running_.store(false, std::memory_order_release);

    // 关闭监听socket以中断accept
    if (listen_sock_ != INVALID_SOCKET) {
        closesocket(listen_sock_);
        listen_sock_ = INVALID_SOCKET;
    }

    if (accept_thread_.joinable()) {
        accept_thread_.join();
    }

    std::cerr << "[TCP] 服务器已停止" << std::endl;
}

inline void TcpServer::join() {
    if (accept_thread_.joinable()) {
        accept_thread_.join();
    }
}

// ═══════════════════════════════════════════════════════════════════
// Accept 循环 (accept线程)
// ═══════════════════════════════════════════════════════════════════

inline void TcpServer::accept_loop() {
    ThreadPool client_threads(io_threads_);

    while (running_.load(std::memory_order_acquire)) {
        struct sockaddr_in client_addr;
        socklen_t addr_len = sizeof(client_addr);

        SOCKET client_sock = accept(listen_sock_,
                                    reinterpret_cast<struct sockaddr*>(&client_addr),
                                    &addr_len);
        if (client_sock == INVALID_SOCKET) {
            if (running_.load(std::memory_order_acquire)) {
                std::cerr << "[TCP] accept 错误" << std::endl;
            }
            break;
        }

        // TCP_NODELAY: 禁用Nagle算法，降低延迟
        int nodelay = 1;
        setsockopt(client_sock, IPPROTO_TCP, TCP_NODELAY,
#ifdef _WIN32
                   reinterpret_cast<const char*>(&nodelay),
#else
                   &nodelay,
#endif
                   sizeof(nodelay));

        // 设置 socket 超时: 30秒
#ifdef _WIN32
        DWORD timeout = 30000;
        setsockopt(client_sock, SOL_SOCKET, SO_RCVTIMEO,
                   reinterpret_cast<const char*>(&timeout), sizeof(timeout));
        setsockopt(client_sock, SOL_SOCKET, SO_SNDTIMEO,
                   reinterpret_cast<const char*>(&timeout), sizeof(timeout));
#else
        struct timeval tv;
        tv.tv_sec = 30;
        tv.tv_usec = 0;
        setsockopt(client_sock, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv));
        setsockopt(client_sock, SOL_SOCKET, SO_SNDTIMEO, &tv, sizeof(tv));
#endif

        char ip_str[INET_ADDRSTRLEN];
        inet_ntop(AF_INET, &client_addr.sin_addr, ip_str, sizeof(ip_str));
        std::string client_id = std::string(ip_str) + ":" + std::to_string(ntohs(client_addr.sin_port));

        conn_count_.fetch_add(1, std::memory_order_release);

        // 提交到IO线程池处理
        try {
            client_threads.submit([this, client_sock, client_id]() {
                handle_client(client_sock, client_id);
            });
        } catch (...) {
            // 线程池满 → 拒绝连接
            std::cerr << "[TCP] IO线程池满, 拒绝连接: " << client_id << std::endl;
            closesocket(client_sock);
            conn_count_.fetch_sub(1, std::memory_order_release);
        }
    }
}

// ═══════════════════════════════════════════════════════════════════
// 单客户端处理 (io线程)
// ═══════════════════════════════════════════════════════════════════

inline void TcpServer::handle_client(SOCKET client_sock, const std::string& client_addr) {
    std::string recv_buffer;
    recv_buffer.reserve(4096);

    while (running_.load(std::memory_order_acquire)) {
        auto line_opt = read_line(client_sock, recv_buffer);

        if (!line_opt) {
            // 连接关闭或读取错误
            break;
        }

        const std::string& line = *line_opt;
        if (line.empty()) continue; // 跳过空行

        // 解析请求
        auto req_opt = parse_request_line(line);
        if (!req_opt) {
            ComputeResponse err;
            err.request_id = "unknown";
            err.status = ResponseStatus::ERROR;
            err.error_code = 400;
            err.error_message = "请求格式错误: " + line.substr(0, std::min(line.size(), size_t(100)));
            write_all(client_sock, response_to_json(err));
            continue;
        }

        ComputeRequest& req = *req_opt;

        // 特殊命令: shutdown / reload / ping
        if (req.command == AlgoCommand::PING) {
            ComputeResponse resp = handler_.handle_sync(req);
            write_all(client_sock, response_to_json(resp));
            continue;
        }

        // 流式处理
        if (req.streaming) {
            handler_.handle_streaming(req, [&](const StreamChunk& chunk) {
                std::string chunk_json = chunk_to_json(chunk);
                write_all(client_sock, chunk_json);
            });
        } else {
            ComputeResponse resp = handler_.handle_sync(req);
            write_all(client_sock, response_to_json(resp));
        }
    }

    closesocket(client_sock);
    conn_count_.fetch_sub(1, std::memory_order_release);
}

// ═══════════════════════════════════════════════════════════════════
// 行读取 (支持部分读取 + 缓冲)
// ═══════════════════════════════════════════════════════════════════

inline std::optional<std::string> TcpServer::read_line(SOCKET sock, std::string& buffer) {
    constexpr size_t CHUNK_SIZE = 4096;

    while (true) {
        // 检查buffer中是否已有完整的行
        size_t newline_pos = buffer.find('\n');
        if (newline_pos != std::string::npos) {
            std::string line = buffer.substr(0, newline_pos);
            buffer.erase(0, newline_pos + 1);
            // 去掉可能的 \r
            if (!line.empty() && line.back() == '\r') {
                line.pop_back();
            }
            return line;
        }

        // 读取更多数据
        char chunk[CHUNK_SIZE];
#ifdef _WIN32
        int bytes = recv(sock, chunk, CHUNK_SIZE, 0);
#else
        ssize_t bytes = recv(sock, chunk, CHUNK_SIZE, 0);
#endif
        if (bytes <= 0) {
            // 0 = 连接关闭, <0 = 错误
            return std::nullopt;
        }

        buffer.append(chunk, static_cast<size_t>(bytes));

        // 安全检查: 避免恶意客户端发送超大行
        if (buffer.size() > 10 * 1024 * 1024) { // 10MB
            return std::nullopt;
        }
    }
}

// ═══════════════════════════════════════════════════════════════════
// 完整写入
// ═══════════════════════════════════════════════════════════════════

inline bool TcpServer::write_all(SOCKET sock, const std::string& data) {
    size_t total_sent = 0;
    while (total_sent < data.size()) {
#ifdef _WIN32
        int sent = send(sock, data.data() + total_sent,
                        static_cast<int>(data.size() - total_sent), 0);
#else
        ssize_t sent = send(sock, data.data() + total_sent,
                            data.size() - total_sent, MSG_NOSIGNAL);
#endif
        if (sent <= 0) {
            return false;
        }
        total_sent += static_cast<size_t>(sent);
    }
    return true;
}

} // namespace server

#endif // SERVER_TCP_SERVER_H
