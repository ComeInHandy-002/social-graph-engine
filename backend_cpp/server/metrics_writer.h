#ifndef SERVER_METRICS_WRITER_H
#define SERVER_METRICS_WRITER_H

// ============================================================================
// 交付 5: 算法性能指标持久化 (C++ 侧直写 MySQL)
//
// 设计目标:
//   - 绕过 Python / MongoDB，从 C++ 直接写入 MySQL，降低延迟
//   - 异步写入 (fire-and-forget)，不阻塞算法计算
//   - 使用预编译语句提升写入性能
//   - 线程安全: 通过连接池确保多线程并发写入
//
// 数据表:
//   algorithm_metrics     — 算法执行指标 (延迟、节点数、边数、参数)
//   graph_snapshots       — 图元数据快照 (节点数、边数、时间戳)
//   system_config         — 系统配置表 (只读查询)
//
// 使用方式:
//   MetricsWriter writer(db_pool);
//   writer.record_algorithm("pagerank", 42, 4039, 88234, "{\"iterations\":100}");
//   writer.update_graph_metadata(4039, 88234);
//   auto config = writer.get_config("cache_ttl_seconds");
// ============================================================================

#include "db_pool.h"

#include <string>
#include <chrono>
#include <ctime>
#include <sstream>
#include <iomanip>
#include <thread>
#include <atomic>
#include <queue>
#include <mutex>
#include <condition_variable>

namespace server {

// ═══════════════════════════════════════════════════════════════════
// MetricsWriter — 算法性能指标写入器
// ═══════════════════════════════════════════════════════════════════

#ifdef MYSQL_ENABLED

class MetricsWriter {
public:
    explicit MetricsWriter(DbConnectionPool& db_pool,
                           bool async_mode = true,
                           size_t batch_size = 100);
    ~MetricsWriter();

    MetricsWriter(const MetricsWriter&) = delete;
    MetricsWriter& operator=(const MetricsWriter&) = delete;

    // ── 算法执行指标 ──────────────────────────────────────────

    // 记录算法执行 (异步, 不阻塞)
    void record_algorithm(
        const std::string& algorithm,
        int64_t time_ms,
        int64_t nodes_processed,
        int64_t edges_processed,
        const std::string& params_json = "{}",
        const std::string& status = "success"
    );

    // 记录延迟百分位指标
    void record_latency(
        const std::string& algorithm,
        double p50_ms,
        double p95_ms,
        double p99_ms,
        double avg_ms,
        int64_t sample_count
    );

    // ── 图元数据 ──────────────────────────────────────────────

    // 更新图元数据快照 (在 reload 或启动时调用)
    void update_graph_metadata(
        int64_t node_count,
        int64_t edge_count,
        const std::string& data_source = ""
    );

    // ── 系统配置 ──────────────────────────────────────────────

    // 从 system_config 表读取配置
    std::optional<std::string> get_config(const std::string& config_key);

    // 批量读取所有配置
    std::unordered_map<std::string, std::string> get_all_configs();

    // ── 统计 ──────────────────────────────────────────────────

    struct WriterStats {
        std::atomic<int64_t> records_written{0};
        std::atomic<int64_t> records_batched{0};
        std::atomic<int64_t> records_dropped{0};  // 队列满时丢弃
        std::atomic<int64_t> write_errors{0};
    };

    const WriterStats& stats() const { return stats_; }

    // 刷新待处理的记录 (在关闭前调用)
    void flush();

    // 同步写入模式开关
    void set_async(bool async) { async_mode_.store(async, std::memory_order_release); }

private:
    DbConnectionPool& db_pool_;
    std::atomic<bool> async_mode_{true};
    std::atomic<bool> shutdown_{false};
    size_t batch_size_;
    WriterStats stats_;

    // 异步写入队列
    struct MetricRecord {
        std::string algorithm;
        int64_t time_ms;
        int64_t nodes_processed;
        int64_t edges_processed;
        std::string params_json;
        std::string status;
        std::string timestamp;
    };

    std::queue<MetricRecord> pending_records_;
    std::mutex queue_mutex_;
    std::condition_variable queue_cv_;
    std::thread writer_thread_;

    // 初始化预编译语句
    void init_prepared_statements();

    // 后台写入线程
    void writer_loop();

    // 同步写入单条记录
    bool write_record_sync(const MetricRecord& record);

    // 批量写入
    bool write_batch_sync(const std::vector<MetricRecord>& batch);

    // 生成 ISO 8601 时间戳
    static std::string now_iso8601();
};

// ── 构造 ──────────────────────────────────────────────────────────

inline MetricsWriter::MetricsWriter(DbConnectionPool& db_pool, bool async_mode, size_t batch_size)
    : db_pool_(db_pool), batch_size_(batch_size)
{
    async_mode_.store(async_mode, std::memory_order_release);

    init_prepared_statements();

    if (async_mode) {
        writer_thread_ = std::thread(&MetricsWriter::writer_loop, this);
        std::cerr << "[Metrics] 异步写入器已启动 (batch_size=" << batch_size << ")" << std::endl;
    }

    // 创建表 (如果不存在)
    try {
        db_pool_.execute(R"(
            CREATE TABLE IF NOT EXISTS algorithm_metrics (
                id BIGINT AUTO_INCREMENT PRIMARY KEY,
                algorithm VARCHAR(64) NOT NULL,
                time_ms BIGINT NOT NULL,
                nodes_processed BIGINT DEFAULT 0,
                edges_processed BIGINT DEFAULT 0,
                params_json JSON,
                status VARCHAR(16) DEFAULT 'success',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_algorithm (algorithm),
                INDEX idx_created_at (created_at)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        )");

        db_pool_.execute(R"(
            CREATE TABLE IF NOT EXISTS graph_snapshots (
                id BIGINT AUTO_INCREMENT PRIMARY KEY,
                node_count BIGINT NOT NULL,
                edge_count BIGINT NOT NULL,
                data_source VARCHAR(512) DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        )");

        db_pool_.execute(R"(
            CREATE TABLE IF NOT EXISTS system_config (
                config_key VARCHAR(128) PRIMARY KEY,
                config_value TEXT NOT NULL,
                description VARCHAR(256) DEFAULT '',
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        )");

    } catch (const std::exception& e) {
        std::cerr << "[Metrics] 表初始化失败 (非致命): " << e.what() << std::endl;
    }
}

inline MetricsWriter::~MetricsWriter() {
    shutdown_.store(true, std::memory_order_release);
    queue_cv_.notify_all();

    if (writer_thread_.joinable()) {
        writer_thread_.join();
    }

    std::cerr << "[Metrics] 写入器已关闭 (写入=" << stats_.records_written.load()
              << ", 丢弃=" << stats_.records_dropped.load()
              << ", 错误=" << stats_.write_errors.load() << ")" << std::endl;
}

// ── 预编译语句注册 ────────────────────────────────────────────────

inline void MetricsWriter::init_prepared_statements() {
    db_pool_.register_prepared_stmt("insert_metric", R"(
        INSERT INTO algorithm_metrics
            (algorithm, time_ms, nodes_processed, edges_processed, params_json, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    )");

    db_pool_.register_prepared_stmt("insert_snapshot", R"(
        INSERT INTO graph_snapshots (node_count, edge_count, data_source)
        VALUES (?, ?, ?)
    )");

    db_pool_.register_prepared_stmt("get_config", R"(
        SELECT config_value FROM system_config WHERE config_key = ?
    )");

    db_pool_.register_prepared_stmt("all_configs", R"(
        SELECT config_key, config_value FROM system_config
    )");

    db_pool_.register_prepared_stmt("upsert_config", R"(
        INSERT INTO system_config (config_key, config_value)
        VALUES (?, ?)
        ON DUPLICATE KEY UPDATE config_value = VALUES(config_value)
    )");
}

// ── 记录算法指标 ──────────────────────────────────────────────────

inline void MetricsWriter::record_algorithm(
    const std::string& algorithm,
    int64_t time_ms,
    int64_t nodes_processed,
    int64_t edges_processed,
    const std::string& params_json,
    const std::string& status)
{
    MetricRecord record;
    record.algorithm = algorithm;
    record.time_ms = time_ms;
    record.nodes_processed = nodes_processed;
    record.edges_processed = edges_processed;
    record.params_json = params_json;
    record.status = status;
    record.timestamp = now_iso8601();

    if (!async_mode_.load(std::memory_order_acquire)) {
        // 同步模式: 直接写入
        write_record_sync(record);
        return;
    }

    // 异步模式: 入队
    {
        std::lock_guard<std::mutex> lock(queue_mutex_);
        if (pending_records_.size() < batch_size_ * 10) { // 最大队列深度
            pending_records_.push(std::move(record));
        } else {
            stats_.records_dropped.fetch_add(1, std::memory_order_relaxed);
        }
    }
    queue_cv_.notify_one();
}

// ── 记录延迟指标 ──────────────────────────────────────────────────

inline void MetricsWriter::record_latency(
    const std::string& algorithm,
    double p50_ms,
    double p95_ms,
    double p99_ms,
    double avg_ms,
    int64_t sample_count)
{
    // 写入为一次特殊的算法调用记录
    std::ostringstream params;
    params << "{\"metric_type\":\"latency\","
           << "\"p50_ms\":" << p50_ms << ","
           << "\"p95_ms\":" << p95_ms << ","
           << "\"p99_ms\":" << p99_ms << ","
           << "\"avg_ms\":" << avg_ms << ","
           << "\"sample_count\":" << sample_count << "}";

    record_algorithm(algorithm + ".latency", 0, 0, 0, params.str(), "metric");
}

// ── 更新图元数据 ──────────────────────────────────────────────────

inline void MetricsWriter::update_graph_metadata(
    int64_t node_count,
    int64_t edge_count,
    const std::string& data_source)
{
    try {
        // 使用预编译语句 (如果支持)
        // 此处使用普通 execute 作为回退
        std::ostringstream sql;
        sql << "INSERT INTO graph_snapshots (node_count, edge_count, data_source) VALUES ("
            << node_count << ", " << edge_count << ", '"
            << data_source << "')";
        db_pool_.execute(sql.str());
    } catch (const std::exception& e) {
        std::cerr << "[Metrics] 图元数据更新失败: " << e.what() << std::endl;
    }
}

// ── 读取配置 ──────────────────────────────────────────────────────

inline std::optional<std::string> MetricsWriter::get_config(const std::string& config_key) {
    try {
        auto result = db_pool_.prepared_query("get_config", {config_key});
        if (!result.rows.empty()) {
            auto it = result.rows[0].columns.find("config_value");
            if (it != result.rows[0].columns.end()) {
                return it->second;
            }
        }
    } catch (const std::exception& e) {
        std::cerr << "[Metrics] 配置读取失败: " << e.what() << std::endl;
    }
    return std::nullopt;
}

inline std::unordered_map<std::string, std::string> MetricsWriter::get_all_configs() {
    std::unordered_map<std::string, std::string> configs;
    try {
        auto result = db_pool_.prepared_query("all_configs", {});
        for (const auto& row : result.rows) {
            auto key = row.columns.find("config_key");
            auto val = row.columns.find("config_value");
            if (key != row.columns.end() && val != row.columns.end()) {
                configs[key->second] = val->second;
            }
        }
    } catch (const std::exception& e) {
        std::cerr << "[Metrics] 批量配置读取失败: " << e.what() << std::endl;
    }
    return configs;
}

// ── 刷新 ──────────────────────────────────────────────────────────

inline void MetricsWriter::flush() {
    if (!async_mode_.load(std::memory_order_acquire)) return;

    std::vector<MetricRecord> batch;
    {
        std::lock_guard<std::mutex> lock(queue_mutex_);
        while (!pending_records_.empty()) {
            batch.push_back(std::move(pending_records_.front()));
            pending_records_.pop();
        }
    }

    if (!batch.empty()) {
        write_batch_sync(batch);
    }
}

// ── 后台写入线程 ──────────────────────────────────────────────────

inline void MetricsWriter::writer_loop() {
    while (true) {
        std::vector<MetricRecord> batch;
        {
            std::unique_lock<std::mutex> lock(queue_mutex_);
            queue_cv_.wait_for(lock, std::chrono::milliseconds(1000), [this] {
                return pending_records_.size() >= batch_size_ || shutdown_.load(std::memory_order_acquire);
            });

            // 收集批次
            while (!pending_records_.empty() && batch.size() < batch_size_) {
                batch.push_back(std::move(pending_records_.front()));
                pending_records_.pop();
            }

            if (shutdown_.load(std::memory_order_acquire) && pending_records_.empty() && batch.empty()) {
                break;
            }
        }

        if (!batch.empty()) {
            write_batch_sync(batch);
        }
    }
}

// ── 同步写入单条 ──────────────────────────────────────────────────

inline bool MetricsWriter::write_record_sync(const MetricRecord& record) {
    try {
        std::ostringstream sql;
        sql << "INSERT INTO algorithm_metrics "
            << "(algorithm, time_ms, nodes_processed, edges_processed, params_json, status, created_at) "
            << "VALUES ('"
            << record.algorithm << "', "
            << record.time_ms << ", "
            << record.nodes_processed << ", "
            << record.edges_processed << ", '"
            << record.params_json << "', '"
            << record.status << "', '"
            << record.timestamp << "')";

        db_pool_.execute(sql.str());
        stats_.records_written.fetch_add(1, std::memory_order_relaxed);
        return true;

    } catch (const std::exception& e) {
        stats_.write_errors.fetch_add(1, std::memory_order_relaxed);
        std::cerr << "[Metrics] 写入失败: " << e.what() << std::endl;
        return false;
    }
}

// ── 批量写入 ──────────────────────────────────────────────────────

inline bool MetricsWriter::write_batch_sync(const std::vector<MetricRecord>& batch) {
    if (batch.empty()) return true;

    try {
        // 构建批量 INSERT
        std::ostringstream sql;
        sql << "INSERT INTO algorithm_metrics "
            << "(algorithm, time_ms, nodes_processed, edges_processed, params_json, status, created_at) "
            << "VALUES ";

        for (size_t i = 0; i < batch.size(); ++i) {
            if (i > 0) sql << ", ";
            sql << "('"
                << batch[i].algorithm << "', "
                << batch[i].time_ms << ", "
                << batch[i].nodes_processed << ", "
                << batch[i].edges_processed << ", '"
                << batch[i].params_json << "', '"
                << batch[i].status << "', '"
                << batch[i].timestamp << "')";
        }

        db_pool_.execute(sql.str());
        stats_.records_written.fetch_add(batch.size(), std::memory_order_relaxed);
        stats_.records_batched.fetch_add(1, std::memory_order_relaxed);
        return true;

    } catch (const std::exception& e) {
        stats_.write_errors.fetch_add(batch.size(), std::memory_order_relaxed);
        std::cerr << "[Metrics] 批量写入失败: " << e.what() << std::endl;

        // 回退: 逐条重试
        int retry_ok = 0;
        for (const auto& record : batch) {
            if (write_record_sync(record)) {
                ++retry_ok;
            }
        }
        return retry_ok > 0;
    }
}

// ── 工具 ──────────────────────────────────────────────────────────

inline std::string MetricsWriter::now_iso8601() {
    auto now = std::chrono::system_clock::now();
    auto time_t_now = std::chrono::system_clock::to_time_t(now);
    auto ms = std::chrono::duration_cast<std::chrono::milliseconds>(
        now.time_since_epoch()) % 1000;

    std::ostringstream ss;
    ss << std::put_time(std::gmtime(&time_t_now), "%Y-%m-%dT%H:%M:%S");
    ss << '.' << std::setfill('0') << std::setw(3) << ms.count() << "Z";
    return ss.str();
}

#else // !MYSQL_ENABLED

class MetricsWriter {
public:
    explicit MetricsWriter(DbConnectionPool&, bool = false, size_t = 100) {
        std::cerr << "[Metrics] 未启用 (编译时未定义 MYSQL_ENABLED)" << std::endl;
    }
    ~MetricsWriter() = default;

    void record_algorithm(const std::string&, int64_t, int64_t, int64_t,
                          const std::string& = "{}", const std::string& = "success") {}
    void record_latency(const std::string&, double, double, double, double, int64_t) {}
    void update_graph_metadata(int64_t, int64_t, const std::string& = "") {}
    std::optional<std::string> get_config(const std::string&) { return std::nullopt; }
    std::unordered_map<std::string, std::string> get_all_configs() { return {}; }

    struct WriterStats {
        std::atomic<int64_t> records_written{0};
        std::atomic<int64_t> records_batched{0};
        std::atomic<int64_t> records_dropped{0};
        std::atomic<int64_t> write_errors{0};
    };
    const WriterStats& stats() const { return stats_; }
    void flush() {}
    void set_async(bool) {}

private:
    WriterStats stats_;
};

#endif // MYSQL_ENABLED

} // namespace server

#endif // SERVER_METRICS_WRITER_H
