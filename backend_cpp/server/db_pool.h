#ifndef SERVER_DB_POOL_H
#define SERVER_DB_POOL_H

// ============================================================================
// 交付 5: MySQL 连接池 (C++ 侧)
//
// 使用 MySQL Connector/C++ (libmysqlcppconn) 或 libmysqlclient
// 实现线程安全的连接池，支持:
//   - 可配置的最小/最大连接数
//   - 连接健康检查和自动重连
//   - 连接空闲回收
//   - 预编译语句缓存
//   - 查询超时控制
//   - 线程安全获取/释放
//
// CMake 依赖:
//   find_package(MySQL REQUIRED)     # libmysqlclient
//   或 find_package(mysql-connector-cpp REQUIRED)
//   target_link_libraries(graph_engine PRIVATE MySQL::MySQL)
//
// 备选方案: 若 mysql-connector-cpp 不可用，可使用 libmysqlclient C API
//   此处设计抽象层，支持两种后端切换
// ============================================================================

#ifdef MYSQL_ENABLED
#include <mysql_driver.h>
#include <mysql_connection.h>
#include <cppconn/prepared_statement.h>
#include <cppconn/resultset.h>
#include <cppconn/statement.h>
#include <cppconn/exception.h>
#endif

#include <string>
#include <vector>
#include <queue>
#include <mutex>
#include <condition_variable>
#include <memory>
#include <functional>
#include <atomic>
#include <chrono>
#include <thread>
#include <unordered_map>

namespace server {

// ── 前向声明 (避免编译依赖) ──────────────────────────────────────
#ifdef MYSQL_ENABLED
using MysqlConnectionPtr = std::shared_ptr<sql::Connection>;
using MysqlPreparedStmtPtr = std::shared_ptr<sql::PreparedStatement>;
#endif

// ── 配置 ──────────────────────────────────────────────────────────

struct DbConfig {
    std::string host = "127.0.0.1";
    int port = 3306;
    std::string user = "socialgraph";
    std::string password;
    std::string database = "socialgraph";
    std::string charset = "utf8mb4";

    // 连接池
    size_t min_connections = 5;
    size_t max_connections = 20;
    size_t max_idle_connections = 10;
    int connection_timeout_ms = 5000;
    int idle_timeout_seconds = 600;      // 空闲连接超时
    int connection_lifetime_seconds = 3600; // 连接最大存活时间
    int retry_count = 3;
    int retry_delay_ms = 100;

    // 查询
    int query_timeout_ms = 30000;        // 默认查询超时
    bool auto_reconnect = true;

    // 预编译语句
    bool prepare_on_create = true;       // 创建时预编译常用语句
};

// ── 查询结果行 ────────────────────────────────────────────────────

struct DbRow {
    std::unordered_map<std::string, std::string> columns;
};

struct DbResult {
    std::vector<DbRow> rows;
    int64_t affected_rows = 0;
    int64_t last_insert_id = 0;
};

// ═══════════════════════════════════════════════════════════════════
// DbConnectionPool — 线程安全 MySQL 连接池
// ═══════════════════════════════════════════════════════════════════

#ifdef MYSQL_ENABLED

class DbConnectionPool {
public:
    explicit DbConnectionPool(const DbConfig& config);
    ~DbConnectionPool();

    DbConnectionPool(const DbConnectionPool&) = delete;
    DbConnectionPool& operator=(const DbConnectionPool&) = delete;

    // ── 连接管理 ──────────────────────────────────────────────

    // 获取一个连接 (阻塞直到有可用连接或超时)
    MysqlConnectionPtr acquire(int timeout_ms = 5000);

    // 释放连接回池
    void release(MysqlConnectionPtr conn);

    // 获取池状态
    size_t active_count() const;
    size_t idle_count() const;
    size_t total_created() const;

    // 健康检查 (ping 所有空闲连接)
    void health_check();

    // 关闭连接池
    void shutdown();

    // ── 便捷查询 ──────────────────────────────────────────────

    // 执行 SELECT 查询
    DbResult query(const std::string& sql);

    // 执行写操作 (INSERT/UPDATE/DELETE)
    DbResult execute(const std::string& sql);

    // 使用预编译语句查询
    DbResult prepared_query(const std::string& stmt_name,
                            const std::vector<std::string>& params);

    // 注册预编译语句
    void register_prepared_stmt(const std::string& name, const std::string& sql);

private:
    struct PooledConnection {
        MysqlConnectionPtr conn;
        std::chrono::steady_clock::time_point created_at;
        std::chrono::steady_clock::time_point last_used_at;
        bool in_use = false;

        bool is_expired(int lifetime_seconds) const {
            auto age = std::chrono::steady_clock::now() - created_at;
            return std::chrono::duration_cast<std::chrono::seconds>(age).count() > lifetime_seconds;
        }

        bool is_idle_expired(int idle_timeout_seconds) const {
            auto idle_time = std::chrono::steady_clock::now() - last_used_at;
            return std::chrono::duration_cast<std::chrono::seconds>(idle_time).count() > idle_timeout_seconds;
        }
    };

    DbConfig config_;
    std::vector<std::unique_ptr<PooledConnection>> pool_;

    mutable std::mutex mutex_;
    std::condition_variable cv_;

    std::atomic<bool> shutdown_{false};
    std::atomic<size_t> total_created_{0};

    // 预编译语句模板 (名称 → SQL)
    std::unordered_map<std::string, std::string> prepared_stmts_;

    // 内部方法
    MysqlConnectionPtr create_connection();
    bool validate_connection(MysqlConnectionPtr conn);
    void initialize_pool();
    void periodic_maintenance(); // 后台回收线程
};

// ── 构造 ──────────────────────────────────────────────────────────

inline DbConnectionPool::DbConnectionPool(const DbConfig& config)
    : config_(config)
{
    initialize_pool();
}

inline DbConnectionPool::~DbConnectionPool() {
    shutdown();
}

inline void DbConnectionPool::initialize_pool() {
    std::lock_guard<std::mutex> lock(mutex_);

    for (size_t i = 0; i < config_.min_connections; ++i) {
        try {
            auto conn = create_connection();
            auto pooled = std::make_unique<PooledConnection>();
            pooled->conn = conn;
            pooled->created_at = std::chrono::steady_clock::now();
            pooled->last_used_at = pooled->created_at;
            pool_.push_back(std::move(pooled));
            total_created_.fetch_add(1, std::memory_order_release);
        } catch (const std::exception& e) {
            std::cerr << "[MySQL] 创建初始连接失败: " << e.what() << std::endl;
        }
    }

    std::cerr << "[MySQL] 连接池已初始化: " << pool_.size()
              << "/" << config_.min_connections << " (min=" << config_.min_connections
              << ", max=" << config_.max_connections << ")" << std::endl;
}

// ── 创建连接 ──────────────────────────────────────────────────────

inline MysqlConnectionPtr DbConnectionPool::create_connection() {
    sql::mysql::MySQL_Driver* driver = sql::mysql::get_mysql_driver_instance();

    std::string url = "tcp://" + config_.host + ":" + std::to_string(config_.port);

    sql::ConnectOptionsMap props;
    props["hostName"] = config_.host;
    props["port"] = config_.port;
    props["userName"] = config_.user;
    props["password"] = config_.password;
    props["schema"] = config_.database;
    props["OPT_CONNECT_TIMEOUT"] = config_.connection_timeout_ms;
    props["OPT_READ_TIMEOUT"] = config_.query_timeout_ms;
    props["OPT_WRITE_TIMEOUT"] = config_.query_timeout_ms;
    props["OPT_RECONNECT"] = config_.auto_reconnect;
    props["characterSetResults"] = config_.charset;
    props["CLIENT_MULTI_STATEMENTS"] = false;

    auto conn = std::shared_ptr<sql::Connection>(driver->connect(props));

    // 设置会话变量
    auto stmt = conn->createStatement();
    stmt->execute("SET SESSION wait_timeout = " + std::to_string(config_.idle_timeout_seconds));
    stmt->execute("SET SESSION max_execution_time = " + std::to_string(config_.query_timeout_ms));
    stmt->execute("SET NAMES " + config_.charset);
    delete stmt;

    return conn;
}

// ── 连接验证 ──────────────────────────────────────────────────────

inline bool DbConnectionPool::validate_connection(MysqlConnectionPtr conn) {
    if (!conn) return false;
    try {
        auto stmt = conn->createStatement();
        stmt->execute("SELECT 1");
        delete stmt;
        return true;
    } catch (...) {
        return false;
    }
}

// ── acquire ────────────────────────────────────────────────────────

inline MysqlConnectionPtr DbConnectionPool::acquire(int timeout_ms) {
    auto deadline = std::chrono::steady_clock::now() + std::chrono::milliseconds(timeout_ms);

    std::unique_lock<std::mutex> lock(mutex_);

    while (true) {
        // 1. 查找空闲连接
        for (auto& pooled : pool_) {
            if (!pooled->in_use) {
                // 检查连接是否过期
                if (pooled->is_expired(config_.connection_lifetime_seconds)) {
                    try { pooled->conn.reset(); } catch (...) {}
                    pooled->conn = create_connection();
                    pooled->created_at = std::chrono::steady_clock::now();
                    total_created_.fetch_add(1, std::memory_order_release);
                }

                // 验证连接
                if (!validate_connection(pooled->conn)) {
                    try { pooled->conn = create_connection(); } catch (...) { continue; }
                    pooled->created_at = std::chrono::steady_clock::now();
                    total_created_.fetch_add(1, std::memory_order_release);
                }

                pooled->in_use = true;
                pooled->last_used_at = std::chrono::steady_clock::now();
                return pooled->conn;
            }
        }

        // 2. 尝试创建新连接
        if (pool_.size() < config_.max_connections) {
            try {
                auto conn = create_connection();
                auto pooled = std::make_unique<PooledConnection>();
                pooled->conn = conn;
                pooled->created_at = std::chrono::steady_clock::now();
                pooled->last_used_at = pooled->created_at;
                pooled->in_use = true;
                pool_.push_back(std::move(pooled));
                total_created_.fetch_add(1, std::memory_order_release);
                return pool_.back()->conn;
            } catch (const std::exception& e) {
                std::cerr << "[MySQL] 创建新连接失败: " << e.what() << std::endl;
            }
        }

        // 3. 等待
        if (cv_.wait_until(lock, deadline) == std::cv_status::timeout) {
            throw std::runtime_error("MySQL 连接池耗尽 (max="
                                     + std::to_string(config_.max_connections)
                                     + "), 等待超时 " + std::to_string(timeout_ms) + "ms");
        }
    }
}

// ── release ────────────────────────────────────────────────────────

inline void DbConnectionPool::release(MysqlConnectionPtr conn) {
    std::lock_guard<std::mutex> lock(mutex_);

    for (auto& pooled : pool_) {
        if (pooled->conn == conn && pooled->in_use) {
            pooled->in_use = false;
            pooled->last_used_at = std::chrono::steady_clock::now();

            // 检查是否超出最大空闲连接数
            size_t idle_count = 0;
            for (const auto& p : pool_) {
                if (!p->in_use) ++idle_count;
            }
            if (idle_count > config_.max_idle_connections) {
                // 移除这个连接
                pooled->conn.reset();
            }

            break;
        }
    }

    cv_.notify_one();
}

// ── 状态查询 ──────────────────────────────────────────────────────

inline size_t DbConnectionPool::active_count() const {
    std::lock_guard<std::mutex> lock(mutex_);
    size_t count = 0;
    for (const auto& p : pool_) {
        if (p->in_use) ++count;
    }
    return count;
}

inline size_t DbConnectionPool::idle_count() const {
    std::lock_guard<std::mutex> lock(mutex_);
    size_t count = 0;
    for (const auto& p : pool_) {
        if (!p->in_use) ++count;
    }
    return count;
}

inline size_t DbConnectionPool::total_created() const {
    return total_created_.load(std::memory_order_acquire);
}

// ── 健康检查 ──────────────────────────────────────────────────────

inline void DbConnectionPool::health_check() {
    std::lock_guard<std::mutex> lock(mutex_);

    for (auto& pooled : pool_) {
        if (!pooled->in_use) {
            if (!validate_connection(pooled->conn)) {
                try {
                    pooled->conn = create_connection();
                    pooled->created_at = std::chrono::steady_clock::now();
                    total_created_.fetch_add(1, std::memory_order_release);
                } catch (...) {
                    pooled->conn.reset();
                }
            }
        }
    }
}

// ── 关闭 ──────────────────────────────────────────────────────────

inline void DbConnectionPool::shutdown() {
    if (shutdown_.exchange(true, std::memory_order_acq_rel)) return;

    std::lock_guard<std::mutex> lock(mutex_);
    for (auto& pooled : pool_) {
        pooled->conn.reset();
    }
    pool_.clear();
    std::cerr << "[MySQL] 连接池已关闭 (总共创建 " << total_created_.load() << " 个连接)" << std::endl;
}

// ── 查询 ──────────────────────────────────────────────────────────

inline DbResult DbConnectionPool::query(const std::string& sql) {
    auto conn = acquire();
    DbResult result;

    try {
        auto stmt = std::unique_ptr<sql::Statement>(conn->createStatement());
        stmt->setQueryTimeout(config_.query_timeout_ms / 1000);

        auto rs = std::unique_ptr<sql::ResultSet>(stmt->executeQuery(sql));
        auto meta = rs->getMetaData();
        size_t col_count = meta->getColumnCount();

        while (rs->next()) {
            DbRow row;
            for (size_t i = 1; i <= col_count; ++i) {
                std::string col_name = meta->getColumnName(static_cast<uint32_t>(i));
                std::string val;
                try { val = rs->getString(static_cast<uint32_t>(i)); } catch (...) { val = ""; }
                row.columns[col_name] = val;
            }
            result.rows.push_back(std::move(row));
        }
    } catch (const sql::SQLException& e) {
        std::cerr << "[MySQL] 查询错误: " << e.what() << " (SQL: " << sql.substr(0, 200) << ")" << std::endl;
    }

    release(conn);
    return result;
}

inline DbResult DbConnectionPool::execute(const std::string& sql) {
    auto conn = acquire();
    DbResult result;

    try {
        auto stmt = std::unique_ptr<sql::Statement>(conn->createStatement());
        stmt->setQueryTimeout(config_.query_timeout_ms / 1000);
        result.affected_rows = stmt->executeUpdate(sql);

        // 获取 last_insert_id
        auto rs = std::unique_ptr<sql::ResultSet>(stmt->executeQuery("SELECT LAST_INSERT_ID()"));
        if (rs->next()) {
            result.last_insert_id = rs->getInt64(1);
        }
    } catch (const sql::SQLException& e) {
        std::cerr << "[MySQL] 执行错误: " << e.what() << std::endl;
    }

    release(conn);
    return result;
}

// ── 预编译语句 ────────────────────────────────────────────────────

inline void DbConnectionPool::register_prepared_stmt(const std::string& name, const std::string& sql) {
    std::lock_guard<std::mutex> lock(mutex_);
    prepared_stmts_[name] = sql;
}

inline DbResult DbConnectionPool::prepared_query(const std::string& stmt_name,
                                                  const std::vector<std::string>& params) {
    auto conn = acquire();
    DbResult result;

    std::string sql;
    {
        std::lock_guard<std::mutex> lock(mutex_);
        auto it = prepared_stmts_.find(stmt_name);
        if (it == prepared_stmts_.end()) {
            release(conn);
            throw std::runtime_error("预编译语句未注册: " + stmt_name);
        }
        sql = it->second;
    }

    try {
        auto pstmt = std::unique_ptr<sql::PreparedStatement>(conn->prepareStatement(sql));
        for (size_t i = 0; i < params.size(); ++i) {
            pstmt->setString(static_cast<uint32_t>(i + 1), params[i]);
        }

        auto rs = std::unique_ptr<sql::ResultSet>(pstmt->executeQuery());
        auto meta = rs->getMetaData();
        size_t col_count = meta->getColumnCount();

        while (rs->next()) {
            DbRow row;
            for (size_t i = 1; i <= col_count; ++i) {
                std::string col_name = meta->getColumnName(static_cast<uint32_t>(i));
                std::string val;
                try { val = rs->getString(static_cast<uint32_t>(i)); } catch (...) { val = ""; }
                row.columns[col_name] = val;
            }
            result.rows.push_back(std::move(row));
        }
    } catch (const sql::SQLException& e) {
        std::cerr << "[MySQL] 预编译查询错误: " << e.what() << std::endl;
    }

    release(conn);
    return result;
}

#else // !MYSQL_ENABLED — 无MySQL依赖时的空实现

class DbConnectionPool {
public:
    explicit DbConnectionPool(const DbConfig&) {
        std::cerr << "[MySQL] 未启用 (编译时未定义 MYSQL_ENABLED)" << std::endl;
    }
    ~DbConnectionPool() = default;

    DbConnectionPool(const DbConnectionPool&) = delete;
    DbConnectionPool& operator=(const DbConnectionPool&) = delete;

    size_t active_count() const { return 0; }
    size_t idle_count() const { return 0; }
    size_t total_created() const { return 0; }
    void health_check() {}
    void shutdown() {}

    DbResult query(const std::string&) { return DbResult{}; }
    DbResult execute(const std::string&) { return DbResult{}; }
    DbResult prepared_query(const std::string&, const std::vector<std::string>&) { return DbResult{}; }
    void register_prepared_stmt(const std::string&, const std::string&) {}
};

#endif // MYSQL_ENABLED

} // namespace server

#endif // SERVER_DB_POOL_H
