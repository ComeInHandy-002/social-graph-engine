-- ============================================================================
-- SocialGraph Pro — 多数据库协作数据流与零停机迁移策略
-- 版本: 1.0.0
-- ============================================================================


-- ============================================================================
-- 第 1 章: 连接池配置建议
-- ============================================================================

-- 1.1 MySQL (用户/Session/配置)
--     池类型:  应用层连接池 (Python: SQLAlchemy QueuePool)
--     池大小:  20 基础 + 10 溢出 (max_overflow)
--     计算:    峰值并发 50 req/s × 平均 DB 时间 80ms = 4 活跃连接
--              × 5 倍安全系数 = 20
--     回收:    pool_recycle=3600 (MySQL wait_timeout 通常 8h, 提前回收防断开)
--     预检:    pool_pre_ping=True (检测断开后自动重连)
--     监控:    SHOW PROCESSLIST; SHOW STATUS LIKE 'Threads_connected';

-- 1.2 MongoDB (分析快照/日志/指标)
--     池类型:  PyMongo MongoClient 内置池
--     池大小:  maxPoolSize=50, minPoolSize=10
--     计算:    MongoDB 主要承载写入操作(异步日志, 快照保存), 峰值写入 ~20 req/s
--             超额配置用于批量导入/聚合查询峰值
--     超时:    connectTimeoutMS=5000, serverSelectionTimeoutMS=30000

-- 1.3 Redis (缓存/限流/会话)
--     池类型:  redis-py ConnectionPool
--     池大小:  max_connections=20
--     计算:    每个 API 请求可能访问 1-3 个 Redis key, 50 req/s 峰值
--             Redis 单线程处理极快 (< 1ms), 20 连接足够
--     超时:    socket_timeout=5, socket_connect_timeout=2, retry_on_timeout=True

-- 1.4 Neo4j (图拓扑)
--     池类型:  neo4j-python-driver 内置池
--     池大小:  max_connection_pool_size=10
--     计算:    拓扑查询频率低 (仅前端首次加载, 且被 Redis 缓存), 10 足够


-- ============================================================================
-- 第 2 章: PageRank 计算请求全链路数据流
-- ============================================================================

-- 场景: 用户通过 Web 前端点击"加载系统" → 触发 PageRank 计算
--
-- 时间轴 (每个步骤标注了涉及的数据库):
--
-- ═══════════════════════════════════════════════════════════════════════
-- 步骤 | 组件           | 数据库操作                           | 耗时
-- ─────┼────────────────┼──────────────────────────────────────┼──────
--  1   | 浏览器         | (无)                                 | -
--  2   | Nginx          | (反向代理, 转发到 FastAPI:8000)      | <1ms
--  3   | FastAPI        | Redis: GET rate_limit:user:XXX      | <1ms
--      | (中间件)       | → 检查限流计数器, 通过              |
--  4   | FastAPI        | JWT 解析 + MySQL: 查找 sessions    | <2ms
--      | (认证)         | 验证 refresh token (首次访问时)     |
--  5   | FastAPI        | Redis: GET social_graph:pagerank:v3 | <1ms
--      | (缓存检查)     | → 命中! 直接返回 (跳过 6-7-8)      |
--  6*  | FastAPI        | Redis: SET lock:compute:pagerank    | <1ms
--      | (分布式锁)     | NX EX 30 (缓存未命中时获取计算锁)   |
--  7*  | C++ Engine     | (无数据库 — 纯内存图计算)           | ~245ms
--      | (子进程)       | 读取 facebook_combined.txt →       |
--      |                | PageRank 迭代 → stdout JSON          |
--  8*  | FastAPI → Redis| Redis: SET social_graph:pagerank:v3  | <1ms
--      |                | EX 86400 (写入缓存)                  |
--  9   | FastAPI        | MongoDB: insertOne →                | <2ms
--      |                | operation_logs {action:"run_        |
--      |                | algorithm", resource:"pagerank"}     |
-- 10   | FastAPI        | MongoDB: insertOne →                | <3ms
--      |                | performance_metrics {metric:         |
--      |                | "pagerank", value: 245, unit: "ms"}  |
-- 11   | FastAPI →      | HTTP Response (JSON)                 | -
--      | 浏览器         |                                      |
-- 12   | 浏览器         | 3d-force-graph 渲染 + 排行榜刷新     | ~500ms
-- ═══════════════════════════════════════════════════════════════════════
-- * 步骤 6-8 仅在缓存未命中时执行 (首次请求 / 缓存过期后)
--
-- 总耗时:
--   缓存命中:   步骤 1-5,9-12  ≈ 5ms (服务器) + 500ms (渲染)
--   缓存未命中: 步骤 1-12 (全链路) ≈ 260ms (服务器) + 500ms (渲染)
--
-- 涉及的数据库:
--   Redis (3次):   限流检查 → 缓存读取/写入 → 分布式锁
--   MySQL (1次):   Session 验证 (仅在首次 / token 刷新时)
--   MongoDB (2次):  操作日志写入 + 性能指标写入
--   Neo4j (0次):   PageRank 不依赖 Neo4j
--   C++ Engine:    纯内存计算, 无数据库交互


-- ============================================================================
-- 第 3 章: 用户登录全链路数据流
-- ============================================================================

-- 时间轴:
-- ═══════════════════════════════════════════════════════════════════════
-- 步骤 | 数据库          | 操作                                 | 耗时
-- ─────┼─────────────────┼──────────────────────────────────────┼──────
--  1   | Redis           | rate_limit:login:{IP} 检查           | <1ms
--  2   | MySQL           | SELECT users WHERE email = ?         | <1ms
--  3   | 应用层          | bcrypt.verify(password, hash)        | ~50ms
--  4   | MySQL           | INSERT sessions (新 refresh token)   | <2ms
--  5   | Redis           | SADD session:token_family:{id}       | <1ms
--  6   | Redis           | HSET session:user:{id} 会话列表       | <1ms
--  7   | MongoDB         | insertOne → operation_logs (login)   | <2ms
-- ═══════════════════════════════════════════════════════════════════════
-- 总耗时: ~60ms


-- ============================================================================
-- 第 4 章: 缓存失效策略
-- ============================================================================

-- 当前项目的缓存失效非常简单 — 因为数据集是静态的:
--   facebook_combined.txt — 4K 节点, 88K 边, 一次导入后不变
--
-- 但需要为未来数据更新场景做准备。以下是完整的失效矩阵:

-- 场景 A: 管理员导入新数据集
--   触发: POST /api/v1/admin/data/import
--   失效:
--     1. DEL social_graph:topology:*          (多个版本 key — 使用 SCAN + DEL)
--     2. DEL social_graph:pagerank:*
--     3. DEL social_graph:community:*
--     4. DEL social_graph:betweenness:*
--     5. DEL social_graph:kcore:*
--     6. DEL social_graph:clustering:*
--     7. DEL social_graph:connected_components:*
--     8. DEL social_graph:stats:*
--   实现: 应用层调用 redis_client.delete_by_pattern("social_graph:*")
--   替代: 版本化 key, 新版数据使用新版本号 (推荐, 旧 key 依靠 TTL 自然过期)

-- 场景 B: 用户手动刷新某算法 (强制重算)
--   触发: POST /api/v1/analyses/{id}/rerun
--   失效: DEL social_graph:{algorithm}:{version}
--   后续: 设置 lock:compute:{algorithm} 防止并发重算

-- 场景 C: 定时任务 (主动预热)
--   策略: 在 TTL 过期前 1 小时，后台异步重算并更新缓存
--   实现:
--     TTL = 86400 (24h), 在 82800 秒时 (TTL - 3600) 触发异步预热
--     使用 Redis 键空间通知: CONFIG SET notify-keyspace-events Ex
--     订阅 __keyevent@0__:expired 频道 (但 TTL 无法精确获取剩余时间)
--   替代: 应用层定时任务 (Cron) 比键空间通知更可靠


-- ============================================================================
-- 第 5 章: 零停机 Schema 迁移策略
-- ============================================================================

-- 原则:
--   1. 永远只加不删 — 新列加 DEFAULT 值, 旧列标记 deprecated 但不删除
--   2. 索引创建使用 INPLACE — 避免 LOCK=NONE 阻塞写入
--   3. 重命名列 = 加新列 + 双写 + 迁移数据 + 删旧列 (分 4 个部署)
--   4. 大表变更使用 pt-online-schema-change 或 gh-ost

-- 示例: 为 saved_analyses 添加 tags 字段
--
-- 版本 1.0.1 (部署 1: 加列)
ALTER TABLE saved_analyses
    ADD COLUMN tags JSON NULL COMMENT '用户自定义标签'
    AFTER parameters,
    ALGORITHM=INPLACE, LOCK=NONE;  -- MySQL 8.0 在线 DDL, 不锁表
-- 耗时: 即时 (JSON NULL, 无数据需要回填)

-- 版本 1.0.2 (部署 2: 应用层开始双写)
-- 应用代码同时写入 parameters 和 tags 字段 (如果有 tags)
-- 同时读取时优先读 tags, 回退到从 parameters 中提取

-- 版本 1.0.3 (部署 3: 如果是重命名)
-- 运行数据迁移脚本: UPDATE saved_analyses SET new_column = old_column WHERE ...
-- 分批执行, 每批 1000 行, 间隔 1 秒

-- 版本 1.0.4 (部署 4: 清理)
-- 确认旧列无读取后删除:
-- ALTER TABLE saved_analyses DROP COLUMN old_column, ALGORITHM=INPLACE, LOCK=NONE;

-- 索引创建 (在线)
CREATE INDEX idx_tags ON saved_analyses(
    (CAST(tags->>'$[*]' AS CHAR(100) ARRAY))
) ALGORITHM=INPLACE, LOCK=NONE;
-- 注意: 虚拟列索引语法因 MySQL 版本而异, 以上为 MySQL 8.0.17+ 多值索引


-- ============================================================================
-- 第 6 章: pt-online-schema-change 大表迁移示例
-- ============================================================================

-- 当表超过 100 万行且需要长时间锁定的变更时, 使用 pt-osc:
--
-- pt-online-schema-change \
--     --alter "ADD COLUMN tags JSON NULL AFTER parameters" \
--     --execute \
--     --critical-load="Threads_running=50" \
--     --max-load="Threads_running=25" \
--     --chunk-size=1000 \
--     --chunk-time=0.5 \
--     h=localhost,D=socialgraph,t=saved_analyses
--
-- pt-osc 原理:
--   1. 创建影子表 (saved_analyses_new), 结构与 ALTER 后一致
--   2. 在原表上创建 INSERT/UPDATE/DELETE 触发器, 将变更同步到影子表
--   3. 分批复制数据 (默认每块 1000 行)
--   4. 复制完成后, 原子 RENAME TABLE 新旧切换 (短暂锁)
--   5. 删除旧表和触发器
--
-- RENAME 这一步需要短暂元数据锁 (通常 < 100ms), 实现了"准"零停机


-- ============================================================================
-- 第 7 章: 备份策略
-- ============================================================================

-- MySQL:
--   全量: mysqldump --single-transaction --routines --triggers  (每天 03:00)
--   增量: binlog 保留 7 天
--   恢复: 全量 + binlog 回放到指定时间点

-- MongoDB:
--   全量: mongodump --db=socialgraph_analytics (每天 04:00)
--   增量: 依赖副本集 oplog (如果配置了副本集)
--   注意: TTL 索引会自动清理数据, 确保备份窗口早于 TTL

-- Redis:
--   持久化: RDB (每小时) + AOF (每秒 fsync)
--   备份: 复制 RDB 文件到异地存储
--   恢复: 从备份 RDB 文件恢复 + AOF 重放

-- Neo4j:
--   全量: neo4j-admin dump --to=/backup/neo4j-$(date +%Y%m%d).dump


-- ============================================================================
-- 第 8 章: 监控指标
-- ============================================================================

-- 需要监控的关键指标:

-- MySQL (来源: performance_schema):
--   慢查询数/分钟         SELECT * FROM sys.x$statements_with_runtimes_in_95th_percentile LIMIT 10;
--   连接数                  SHOW STATUS LIKE 'Threads_connected';
--   缓冲池命中率           SHOW STATUS LIKE 'Innodb_buffer_pool_read_requests'; / Innodb_buffer_pool_reads
--   行锁等待数             SHOW STATUS LIKE 'Innodb_row_lock_waits';

-- MongoDB (来源: db.serverStatus()):
--   操作计数器             db.serverStatus().opcounters
--   连接数                  db.serverStatus().connections
--   锁等待                  db.serverStatus().locks
--   WiredTiger 缓存        db.serverStatus().wiredTiger.cache

-- Redis (来源: redis-cli INFO):
--   命中率                  keyspace_hits / (keyspace_hits + keyspace_misses)
--   内存用量               used_memory_human
--   连接数                  connected_clients
--   CPU 使用               instantaneous_ops_per_sec

-- Neo4j:
--   页面缓存命中率         CALL dbms.queryJmx('org.neo4j.metrics:name=pagecache.hitratio')
--   事务吞吐量             CALL dbms.queryJmx('org.neo4j.metrics:name=tx.active')
