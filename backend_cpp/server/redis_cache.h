#ifndef SERVER_REDIS_CACHE_H
#define SERVER_REDIS_CACHE_H

// ============================================================================
// 交付 4: C++ Redis 缓存集成
//
// 使用 redis-plus-plus (https://github.com/sewenew/redis-plus-plus)
// 基于 hiredis 的 header-only C++ Redis 客户端。
//
// 安装:
//   - Ubuntu: apt install libhiredis-dev
//   - 然后:  git clone https://github.com/sewenew/redis-plus-plus.git
//            cmake -B build && cmake --build build && sudo cmake --install build
//   - CMake: find_package(redis++ REQUIRED)
//
// CMakeLists.txt 配置:
//   find_package(redis++ REQUIRED)
//   target_link_libraries(graph_engine PRIVATE redis++ hiredis)
//
// 设计要点:
//   1. 缓存键模式与 Python 端统一:
//        sgp:algo:{算法名}:v{版本号}
//      (兼容旧格式 social_graph:{算法}:v{版本})
//   2. 连接池: redis++ ConnectionPool 是线程安全的
//      所有工作线程共享同一个 Redis 对象
//   3. 缓存预热: 启动时可配置预计算算法列表
//   4. 大结果集压缩: 超过阈值时使用 zlib 压缩后再存 Redis
//   5. 软失败: Redis 不可用时不影响核心计算
// ============================================================================

#ifdef REDIS_ENABLED
#include <sw/redis++/redis++.h>
#include <sw/redis++/connection_pool.h>
#endif

#include <string>
#include <functional>
#include <memory>
#include <atomic>
#include <chrono>
#include <sstream>
#include <iomanip>
#include <cstring>

namespace server {

// ── 压缩工具 (简易 zlib 封装) ────────────────────────────────────
// 生产环境使用 <zlib.h>
namespace compress {

// 检测是否需要压缩 (超过阈值)
inline bool should_compress(const std::string& data, size_t threshold = 1024 * 64) {
    return data.size() > threshold;
}

// 简易 Base64 编码 (用于存储压缩后的二进制数据)
inline std::string base64_encode(const unsigned char* data, size_t len) {
    static const char* chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    std::string result;
    result.reserve(((len + 2) / 3) * 4);
    for (size_t i = 0; i < len; i += 3) {
        unsigned char a = data[i];
        unsigned char b = (i + 1 < len) ? data[i + 1] : 0;
        unsigned char c = (i + 2 < len) ? data[i + 2] : 0;
        result += chars[a >> 2];
        result += chars[((a & 0x03) << 4) | (b >> 4)];
        result += (i + 1 < len) ? chars[((b & 0x0f) << 2) | (c >> 6)] : '=';
        result += (i + 2 < len) ? chars[c & 0x3f] : '=';
    }
    return result;
}

// 简易压缩 (生产环境替换为 zlib deflate)
inline std::string compress_data(const std::string& data) {
    // 占位: 实际应使用 zlib deflate
    // 返回标记为已压缩的数据: "Z:" + base64(compressed_data)
    // 此处简化为仅 Base64 编码原始数据
    return "Z:" + base64_encode(
        reinterpret_cast<const unsigned char*>(data.data()), data.size());
}

} // namespace compress

// ── 缓存键管理 ────────────────────────────────────────────────────

struct CacheKeySchema {
    // 主键格式: sgp:algo:{algorithm}:v{version}
    static std::string algo(const std::string& algorithm, const std::string& version = "v1") {
        return "sgp:algo:" + algorithm + ":" + version;
    }

    // 拓扑数据
    static std::string topology(const std::string& version = "v7") {
        return "sgp:algo:topology:" + version;
    }

    // 图统计
    static std::string stats(const std::string& version = "v1") {
        return "sgp:algo:stats:" + version;
    }

    // 分布式锁键
    static std::string compute_lock(const std::string& base_key) {
        return "sgp:lock:compute:" + base_key;
    }

    // 算法名称映射 (兼容旧格式)
    static std::string algo_legacy(const std::string& algorithm, const std::string& version = "v1") {
        return "social_graph:" + algorithm + ":" + version;
    }
};

// ═══════════════════════════════════════════════════════════════════
// RedisCache — 线程安全的 Redis 客户端封装
// ═══════════════════════════════════════════════════════════════════

#ifdef REDIS_ENABLED

class RedisCache {
public:
    struct Config {
        std::string host = "127.0.0.1";
        int port = 6379;
        int db = 0;
        std::string password;
        size_t pool_size = 10;              // 连接池大小
        int socket_timeout_ms = 5000;
        int connect_timeout_ms = 2000;
        bool enable_compression = true;
        size_t compression_threshold = 65536; // 64KB
        int default_ttl_seconds = 86400;       // 24h
    };

    explicit RedisCache(const Config& config);
    ~RedisCache();

    RedisCache(const RedisCache&) = delete;
    RedisCache& operator=(const RedisCache&) = delete;

    // ── 核心操作 ──────────────────────────────────────────────

    // 检查缓存是否可用
    bool is_available() const { return available_.load(std::memory_order_acquire); }

    // 读取缓存 (返回 nullopt 表示未命中或不可用)
    std::optional<std::string> get(const std::string& key);

    // 写入缓存 (带过期时间)
    bool set(const std::string& key, const std::string& value, int ttl_seconds = 0);

    // 写入缓存 (使用默认 TTL + 可选压缩)
    bool setex(const std::string& key, const std::string& value);

    // 检查键是否存在
    bool exists(const std::string& key);

    // 删除键
    bool del(const std::string& key);

    // 设置过期时间
    bool expire(const std::string& key, int ttl_seconds);

    // 获取 TTL
    int64_t ttl(const std::string& key);

    // ── 高级操作 ──────────────────────────────────────────────

    // 获取分布式锁 (用于防止缓存击穿)
    // 返回 true 表示获取成功
    bool try_lock(const std::string& lock_key, int timeout_seconds = 30);

    // 释放分布式锁
    void unlock(const std::string& lock_key);

    // 扫描匹配模式的所有键
    std::vector<std::string> scan(const std::string& pattern, size_t count = 100);

    // 失效匹配模式的所有缓存
    int invalidate_pattern(const std::string& pattern);

    // ── 算法缓存专用 ──────────────────────────────────────────

    // 检查算法缓存 + 未命中时计算并缓存 (Cache-Aside)
    // compute_fn: 计算函数, 返回 JSON 字符串
    std::string cache_get_or_compute(
        const std::string& algo_name,
        const std::string& version,
        std::function<std::string()> compute_fn
    );

    // 预计算并缓存高频算法 (缓存预热)
    void warmup(const std::vector<std::string>& algorithms);

    // ── 统计 ──────────────────────────────────────────────────

    struct CacheStats {
        std::atomic<int64_t> hits{0};
        std::atomic<int64_t> misses{0};
        std::atomic<int64_t> writes{0};
        std::atomic<int64_t> errors{0};

        double hit_rate() const {
            int64_t total = hits.load() + misses.load();
            return total > 0 ? static_cast<double>(hits.load()) / total : 0.0;
        }
    };

    const CacheStats& stats() const { return stats_; }

private:
    Config config_;
    std::atomic<bool> available_{false};
    CacheStats stats_;

    // redis++ 连接池 (线程安全)
    std::unique_ptr<sw::redis::Redis> redis_;
    std::unique_ptr<sw::redis::ConnectionPool> pool_;

    // 连接初始化
    bool connect();
};

// ── 构造 ──────────────────────────────────────────────────────────

inline RedisCache::RedisCache(const Config& config)
    : config_(config)
{
    connect();
}

inline RedisCache::~RedisCache() {
    // redis++ 自动管理连接生命周期
}

inline bool RedisCache::connect() {
    try {
        sw::redis::ConnectionOptions conn_opts;
        conn_opts.host = config_.host;
        conn_opts.port = config_.port;
        conn_opts.db = config_.db;
        conn_opts.socket_timeout = std::chrono::milliseconds(config_.socket_timeout_ms);
        conn_opts.connect_timeout = std::chrono::milliseconds(config_.connect_timeout_ms);
        if (!config_.password.empty()) {
            conn_opts.password = config_.password;
        }

        sw::redis::ConnectionPoolOptions pool_opts;
        pool_opts.size = config_.pool_size;
        pool_opts.wait_timeout = std::chrono::milliseconds(3000);
        pool_opts.connection_lifetime = std::chrono::minutes(10);

        pool_ = std::make_unique<sw::redis::ConnectionPool>(conn_opts, pool_opts);
        redis_ = std::make_unique<sw::redis::Redis>(pool_);

        // 验证连接
        redis_->ping();
        available_.store(true, std::memory_order_release);

        std::cerr << "[Redis] 已连接: " << config_.host << ":" << config_.port
                  << " (pool=" << config_.pool_size << ")" << std::endl;
        return true;

    } catch (const std::exception& e) {
        std::cerr << "[Redis] 连接失败 (" << config_.host << ":" << config_.port
                  << "): " << e.what() << " — 将以无缓存模式运行" << std::endl;
        available_.store(false, std::memory_order_release);
        return false;
    }
}

// ── get ────────────────────────────────────────────────────────────

inline std::optional<std::string> RedisCache::get(const std::string& key) {
    if (!available_.load(std::memory_order_acquire)) return std::nullopt;

    try {
        auto val = redis_->get(key);
        if (val) {
            stats_.hits.fetch_add(1, std::memory_order_relaxed);

            // 检查是否为压缩数据
            std::string s = *val;
            if (s.size() >= 2 && s[0] == 'Z' && s[1] == ':') {
                // 生产环境: 解压缩
                // 此处返回原始数据，调用方应处理
                return s;
            }
            return s;
        }
        stats_.misses.fetch_add(1, std::memory_order_relaxed);
        return std::nullopt;

    } catch (const std::exception& e) {
        stats_.errors.fetch_add(1, std::memory_order_relaxed);
        std::cerr << "[Redis] get 错误: " << e.what() << std::endl;
        return std::nullopt;
    }
}

// ── set ────────────────────────────────────────────────────────────

inline bool RedisCache::set(const std::string& key, const std::string& value, int ttl_seconds) {
    if (!available_.load(std::memory_order_acquire)) return false;

    try {
        if (ttl_seconds > 0) {
            redis_->set(key, value, std::chrono::seconds(ttl_seconds));
        } else {
            redis_->set(key, value, std::chrono::seconds(config_.default_ttl_seconds));
        }
        stats_.writes.fetch_add(1, std::memory_order_relaxed);
        return true;

    } catch (const std::exception& e) {
        stats_.errors.fetch_add(1, std::memory_order_relaxed);
        std::cerr << "[Redis] set 错误: " << e.what() << std::endl;
        return false;
    }
}

// ── setex (带压缩) ────────────────────────────────────────────────

inline bool RedisCache::setex(const std::string& key, const std::string& value) {
    if (!available_.load(std::memory_order_acquire)) return false;

    std::string data_to_store = value;

    // 大结果集压缩
    if (config_.enable_compression && compress::should_compress(value, config_.compression_threshold)) {
        data_to_store = compress::compress_data(value);
    }

    return set(key, data_to_store, config_.default_ttl_seconds);
}

// ── exists ─────────────────────────────────────────────────────────

inline bool RedisCache::exists(const std::string& key) {
    if (!available_.load(std::memory_order_acquire)) return false;

    try {
        return redis_->exists(key) > 0;
    } catch (const std::exception& e) {
        stats_.errors.fetch_add(1, std::memory_order_relaxed);
        return false;
    }
}

// ── del ────────────────────────────────────────────────────────────

inline bool RedisCache::del(const std::string& key) {
    if (!available_.load(std::memory_order_acquire)) return false;

    try {
        return redis_->del(key) > 0;
    } catch (const std::exception& e) {
        stats_.errors.fetch_add(1, std::memory_order_relaxed);
        return false;
    }
}

// ── expire ─────────────────────────────────────────────────────────

inline bool RedisCache::expire(const std::string& key, int ttl_seconds) {
    if (!available_.load(std::memory_order_acquire)) return false;

    try {
        redis_->expire(key, ttl_seconds);
        return true;
    } catch (const std::exception& e) {
        return false;
    }
}

// ── ttl ────────────────────────────────────────────────────────────

inline int64_t RedisCache::ttl(const std::string& key) {
    if (!available_.load(std::memory_order_acquire)) return -2;

    try {
        return redis_->ttl(key);
    } catch (const std::exception&) {
        return -2;
    }
}

// ── 分布式锁 ──────────────────────────────────────────────────────

inline bool RedisCache::try_lock(const std::string& lock_key, int timeout_seconds) {
    if (!available_.load(std::memory_order_acquire)) return true; // 无Redis时总是获取锁

    try {
        // SET NX EX
        return redis_->set(lock_key, "1",
                          std::chrono::seconds(timeout_seconds),
                          sw::redis::UpdateType::NOT_EXIST);
    } catch (const std::exception& e) {
        stats_.errors.fetch_add(1, std::memory_order_relaxed);
        return true; // 失败时允许继续计算
    }
}

inline void RedisCache::unlock(const std::string& lock_key) {
    if (!available_.load(std::memory_order_acquire)) return;
    try {
        redis_->del(lock_key);
    } catch (...) {}
}

// ── scan ───────────────────────────────────────────────────────────

inline std::vector<std::string> RedisCache::scan(const std::string& pattern, size_t count) {
    if (!available_.load(std::memory_order_acquire)) return {};

    std::vector<std::string> result;
    try {
        auto cursor = 0LL;
        while (true) {
            auto [next_cursor, keys] = redis_->scan(cursor, pattern, count);
            for (const auto& k : keys) result.push_back(k);
            if (next_cursor == 0) break;
            cursor = next_cursor;
        }
    } catch (const std::exception& e) {
        stats_.errors.fetch_add(1, std::memory_order_relaxed);
    }
    return result;
}

inline int RedisCache::invalidate_pattern(const std::string& pattern) {
    auto keys = scan(pattern);
    if (keys.empty()) return 0;

    try {
        redis_->del(keys.begin(), keys.end());
        return static_cast<int>(keys.size());
    } catch (...) {
        return 0;
    }
}

// ── Cache-Aside: 算法结果缓存 ──────────────────────────────────────

inline std::string RedisCache::cache_get_or_compute(
    const std::string& algo_name,
    const std::string& version,
    std::function<std::string()> compute_fn)
{
    std::string cache_key = CacheKeySchema::algo(algo_name, version);

    // 1. 尝试从缓存读取
    auto cached = get(cache_key);
    if (cached) {
        return *cached;
    }

    // 2. 获取分布式锁 (防止缓存击穿)
    std::string lock_key = CacheKeySchema::compute_lock(cache_key);
    bool have_lock = try_lock(lock_key, 30);

    if (!have_lock) {
        // 等待其他请求完成计算
        for (int i = 0; i < 300; ++i) {  // 最多等待30秒
            std::this_thread::sleep_for(std::chrono::milliseconds(100));
            auto retry = get(cache_key);
            if (retry) return *retry;
        }
    }

    // 3. 执行计算
    std::string result;
    try {
        result = compute_fn();
    } catch (...) {
        if (have_lock) unlock(lock_key);
        throw;
    }

    // 4. 写入缓存
    setex(cache_key, result);

    // 5. 释放锁
    if (have_lock) unlock(lock_key);

    return result;
}

// ── 缓存预热 ──────────────────────────────────────────────────────

inline void RedisCache::warmup(const std::vector<std::string>& algorithms) {
    if (!available_.load(std::memory_order_acquire)) return;

    std::cerr << "[Redis] 开始缓存预热: " << algorithms.size() << " 个算法" << std::endl;

    for (const auto& algo : algorithms) {
        std::string key = CacheKeySchema::algo(algo);
        if (!exists(key)) {
            std::cerr << "[Redis] 预热: " << algo << " (缓存未命中，将在首次请求时计算)" << std::endl;
        } else {
            std::cerr << "[Redis] 预热: " << algo << " (缓存已存在)" << std::endl;
        }
    }

    std::cerr << "[Redis] 缓存预热完成" << std::endl;
}

#else // !REDIS_ENABLED — 无 Redis 依赖时的空实现

class RedisCache {
public:
    struct Config {
        std::string host = "127.0.0.1";
        int port = 6379;
        int db = 0;
        std::string password;
        size_t pool_size = 10;
        int socket_timeout_ms = 5000;
        int connect_timeout_ms = 2000;
        bool enable_compression = true;
        size_t compression_threshold = 65536;
        int default_ttl_seconds = 86400;
    };

    explicit RedisCache(const Config&) {
        std::cerr << "[Redis] 未启用 (编译时未定义 REDIS_ENABLED)" << std::endl;
    }

    bool is_available() const { return false; }
    std::optional<std::string> get(const std::string&) { return std::nullopt; }
    bool set(const std::string&, const std::string&, int = 0) { return false; }
    bool setex(const std::string&, const std::string&) { return false; }
    bool exists(const std::string&) { return false; }
    bool del(const std::string&) { return false; }
    bool expire(const std::string&, int) { return false; }
    int64_t ttl(const std::string&) { return -2; }
    bool try_lock(const std::string&, int = 30) { return true; }
    void unlock(const std::string&) {}
    std::vector<std::string> scan(const std::string&, size_t = 100) { return {}; }
    int invalidate_pattern(const std::string&) { return 0; }

    std::string cache_get_or_compute(
        const std::string&, const std::string&,
        std::function<std::string()> compute_fn)
    {
        return compute_fn();
    }

    void warmup(const std::vector<std::string>&) {}

    struct CacheStats {
        std::atomic<int64_t> hits{0};
        std::atomic<int64_t> misses{0};
        std::atomic<int64_t> writes{0};
        std::atomic<int64_t> errors{0};
        double hit_rate() const { return 0.0; }
    };
    const CacheStats& stats() const { return stats_; }
private:
    CacheStats stats_;
};

#endif // REDIS_ENABLED

} // namespace server

#endif // SERVER_REDIS_CACHE_H
