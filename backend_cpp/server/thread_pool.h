#ifndef SERVER_THREAD_POOL_H
#define SERVER_THREAD_POOL_H

// ============================================================================
// 交付 1: 工作线程池
//
// 设计要点:
//   - 基于 std::thread + 无锁任务队列 (互斥锁保护)
//   - 固定大小线程池，启动时创建，关闭时 join
//   - 支持 std::future 返回异步结果
//   - 线程安全的 submit/try_submit
//   - 优雅关闭: 排空队列 → 发送哨兵 → join 所有线程
//
// 并发模型:
//   - 共享只读 SocialGraph 由所有工作线程访问 (const&)
//   - 每个算法实例分配在各自线程栈上 (thread-local)
//   - 任务队列用 std::mutex + std::condition_variable 保护
// ============================================================================

#include <vector>
#include <queue>
#include <thread>
#include <mutex>
#include <condition_variable>
#include <functional>
#include <future>
#include <atomic>
#include <memory>
#include <stdexcept>
#include <chrono>
#include <iostream>

namespace server {

class ThreadPool {
public:
    explicit ThreadPool(size_t num_threads = 0);
    ~ThreadPool();

    // 禁止复制
    ThreadPool(const ThreadPool&) = delete;
    ThreadPool& operator=(const ThreadPool&) = delete;

    // 提交任务并获取 future
    template<typename F, typename... Args>
    auto submit(F&& f, Args&&... args)
        -> std::future<typename std::invoke_result_t<F, Args...>>;

    // 尝试提交 (队列满时立即返回 false)
    template<typename F, typename... Args>
    bool try_submit(F&& f, Args&&... args);

    // 获取当前排队的任务数
    size_t pending_tasks() const;

    // 活跃线程数
    size_t active_threads() const { return workers_.size(); }

    // 优雅关闭: 等待所有任务完成后退出
    void shutdown();

    // 立即关闭: 丢弃未执行的任务
    void shutdown_now();

    // 是否为关闭状态
    bool is_shutdown() const { return stop_.load(std::memory_order_acquire); }

    // 设置最大队列深度 (0 = 无限制)
    void set_max_queue_depth(size_t depth) { max_queue_depth_.store(depth, std::memory_order_release); }

private:
    void worker_loop();

    std::vector<std::thread> workers_;
    std::queue<std::function<void()>> tasks_;

    mutable std::mutex mutex_;
    std::condition_variable cv_;
    std::condition_variable cv_done_;   // 等待所有任务完成

    std::atomic<bool> stop_{false};
    std::atomic<size_t> pending_{0};
    std::atomic<size_t> max_queue_depth_{0};  // 0 = 无限制
};

// ── 构造: num_threads=0 表示自动检测硬件并发 ────────────────────
inline ThreadPool::ThreadPool(size_t num_threads) {
    if (num_threads == 0) {
        num_threads = std::thread::hardware_concurrency();
        if (num_threads == 0) num_threads = 4; // 回退值
    }

    // 至少保留1个核给OS和网络线程
    if (num_threads > 2) num_threads -= 1;

    workers_.reserve(num_threads);
    for (size_t i = 0; i < num_threads; ++i) {
        workers_.emplace_back(&ThreadPool::worker_loop, this);
    }
}

inline ThreadPool::~ThreadPool() {
    if (!stop_.load(std::memory_order_acquire)) {
        shutdown();
    }
}

template<typename F, typename... Args>
auto ThreadPool::submit(F&& f, Args&&... args)
    -> std::future<typename std::invoke_result_t<F, Args...>>
{
    using ReturnType = typename std::invoke_result_t<F, Args...>;

    if (stop_.load(std::memory_order_acquire)) {
        throw std::runtime_error("ThreadPool: 无法向已关闭的线程池提交任务");
    }

    auto task = std::make_shared<std::packaged_task<ReturnType()>>(
        std::bind(std::forward<F>(f), std::forward<Args>(args)...)
    );
    std::future<ReturnType> result = task->get_future();

    {
        std::unique_lock<std::mutex> lock(mutex_);

        // 队列深度限制检查
        size_t max_depth = max_queue_depth_.load(std::memory_order_acquire);
        if (max_depth > 0 && tasks_.size() >= max_depth) {
            throw std::runtime_error("ThreadPool: 任务队列已满 (max_depth="
                                     + std::to_string(max_depth) + ")");
        }

        tasks_.emplace([task]() { (*task)(); });
        pending_.fetch_add(1, std::memory_order_release);
    }
    cv_.notify_one();
    return result;
}

template<typename F, typename... Args>
bool ThreadPool::try_submit(F&& f, Args&&... args) {
    if (stop_.load(std::memory_order_acquire)) return false;

    using ReturnType = typename std::invoke_result_t<F, Args...>;
    auto task = std::make_shared<std::packaged_task<ReturnType()>>(
        std::bind(std::forward<F>(f), std::forward<Args>(args)...)
    );

    {
        std::unique_lock<std::mutex> lock(mutex_);
        size_t max_depth = max_queue_depth_.load(std::memory_order_acquire);
        if (max_depth > 0 && tasks_.size() >= max_depth) {
            return false;
        }
        tasks_.emplace([task]() { (*task)(); });
        pending_.fetch_add(1, std::memory_order_release);
    }
    cv_.notify_one();
    return true;  // 非阻塞提交，调用者需要自己处理结果
}

inline size_t ThreadPool::pending_tasks() const {
    std::lock_guard<std::mutex> lock(mutex_);
    return tasks_.size();
}

inline void ThreadPool::shutdown() {
    stop_.store(true, std::memory_order_release);
    cv_.notify_all();

    for (auto& worker : workers_) {
        if (worker.joinable()) {
            worker.join();
        }
    }
}

inline void ThreadPool::shutdown_now() {
    stop_.store(true, std::memory_order_release);
    {
        std::lock_guard<std::mutex> lock(mutex_);
        // 清空队列
        std::queue<std::function<void()>> empty;
        std::swap(tasks_, empty);
        pending_.store(0, std::memory_order_release);
    }
    cv_.notify_all();
    for (auto& worker : workers_) {
        if (worker.joinable()) {
            worker.join();
        }
    }
}

inline void ThreadPool::worker_loop() {
    while (true) {
        std::function<void()> task;
        {
            std::unique_lock<std::mutex> lock(mutex_);
            cv_.wait(lock, [this] {
                return stop_.load(std::memory_order_acquire) || !tasks_.empty();
            });

            if (stop_.load(std::memory_order_acquire) && tasks_.empty()) {
                return;
            }

            task = std::move(tasks_.front());
            tasks_.pop();
        }

        task();
        pending_.fetch_sub(1, std::memory_order_release);

        // 如果队列为空，通知等待者
        if (pending_.load(std::memory_order_acquire) == 0) {
            cv_done_.notify_all();
        }
    }
}

} // namespace server

#endif // SERVER_THREAD_POOL_H
