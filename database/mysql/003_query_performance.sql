-- ============================================================================
-- SocialGraph Pro — 核心查询性能文档
-- 版本: 1.0.0
-- 索引定义参见 001_init_schema.sql
-- ============================================================================

-- ============================================================================
-- 查询 1: 用户邮箱登录查找
-- ============================================================================
-- 场景: POST /api/v1/auth/login {email, password}
-- 频率: 高频 (每次登录 / token 刷新)
-- 目标: < 1ms (主键/唯一索引查找)

SELECT id, email, password_hash, display_name, role, email_verified_at
FROM users
WHERE email = 'admin@socialgraph.io'
  AND deleted_at IS NULL;

-- EXPLAIN 预期输出:
-- +----+-------------+-------+-------+-------------+-------+-------+-----+------+-------+
-- | id | select_type | table | type  | key         | ref   | rows  | filtered | Extra       |
-- +----+-------------+-------+-------+-------------+-------+-------+-----+------+-------+
-- |  1 | SIMPLE      | users | const | uk_email    | const |     1 |   100.00 | Using where |
-- +----+-------------+-------+-------+-------------+-------+-------+-----+------+-------+
-- 解释:
--   type=const  — 最优访问类型 (唯一索引等值查找)
--   key=uk_email — 使用邮箱唯一索引
--   rows=1       — 仅扫描 1 行
--   Extra 的 "Using where" 是针对 deleted_at IS NULL 条件，不影响性能


-- ============================================================================
-- 查询 2: 用户最近分析列表 (分页)
-- ============================================================================
-- 场景: GET /api/v1/analyses?page=1&per_page=20
-- 频率: 高频 (每次打开 "我的分析" 页面)
-- 目标: < 5ms (复合索引覆盖排序)

-- 方式 A: 常规分页 (首页 — 推荐)
SELECT id, name, analysis_type, parameters, is_public, created_at
FROM saved_analyses
WHERE user_id = 'a0000000-0000-4000-8000-000000000002'
  AND deleted_at IS NULL
ORDER BY created_at DESC
LIMIT 20 OFFSET 0;

-- EXPLAIN 预期输出:
-- +----+-------------+-----------------+------+------------------+------+-------+-----+------+-------------+
-- | id | select_type | table           | type | key              | ref  | rows  | filtered | Extra          |
-- +----+-------------+-----------------+------+------------------+------+-------+-----+------+-------------+
-- |  1 | SIMPLE      | saved_analyses  | ref  | idx_user_created | const|    20 |   100.00 | Using where   |
-- +----+-------------+-----------------+------+------------------+------+-------+-----+------+-------------+
-- 解释:
--   type=ref         — 非唯一索引查找
--   key=idx_user_created (user_id, created_at DESC) — 复合索引同时满足 WHERE + ORDER BY
--   rows=20          — 只需扫描前 20 行 (索引已排序)
--   Using where      — deleted_at 条件 (概率低)
--   无需 filesort    — 索引已按 created_at DESC 排序

-- 方式 B: 游标分页 (深层翻页时性能更好, 避免 OFFSET 扫描)
SELECT id, name, analysis_type, parameters, is_public, created_at
FROM saved_analyses
WHERE user_id = 'a0000000-0000-4000-8000-000000000002'
  AND deleted_at IS NULL
  AND created_at < '2025-01-01 00:00:00.000'  -- 上一页最后一条的 created_at
ORDER BY created_at DESC
LIMIT 20;
-- 游标分页优势: 始终扫描固定 20 行，不受 OFFSET 增长影响


-- ============================================================================
-- 查询 3: Top 10 最常运行的分析类型 (仪表板)
-- ============================================================================
-- 场景: GET /api/v1/analytics/dashboard — 管理仪表板
-- 频率: 中频 (管理页面加载)
-- 目标: < 30ms (聚合查询, 可接受 Group By 临时表)

SELECT analysis_type, COUNT(*) AS run_count
FROM saved_analyses
WHERE created_at >= DATE_SUB(NOW(), INTERVAL 30 DAY)
  AND deleted_at IS NULL
GROUP BY analysis_type
ORDER BY run_count DESC
LIMIT 10;

-- EXPLAIN 预期输出:
-- +----+-------------+-----------------+------+----------+------+-------+-----+------+---------------------------------+
-- | id | select_type | table           | type | key      | ref  | rows  | filtered | Extra                           |
-- +----+-------------+-----------------+------+----------+------+-------+-----+------+---------------------------------+
-- |  1 | SIMPLE      | saved_analyses  | index| idx_type | NULL |  1000 |    33.00 | Using where; Using temporary;   |
-- |    |             |                 |      |          |      |       |          | Using filesort                  |
-- +----+-------------+-----------------+------+----------+------+-------+-----+------+---------------------------------+
-- 解释:
--   type=index              — 全索引扫描 (因需 GROUP BY analysis_type)
--   Using temporary         — GROUP BY 需要临时表 (10 种算法类型, 极小)
--   Using filesort          — ORDER BY run_count DESC 需要排序 (LIMIT 10, 量可忽略)
--
-- 性能优化方案 (如果未来数据量 > 100K):
--   方案 A: 创建物化视图/汇总表 → 每日定时刷新 (推荐)
--     CREATE TABLE analysis_type_daily_stats (
--       stat_date DATE, analysis_type VARCHAR(50), run_count INT, ...
--     )
--   方案 B: 使用 application-level Redis HyperLogLog 近似计数
--   方案 C: 添加覆盖索引 idx_type_created (analysis_type, created_at)


-- ============================================================================
-- 查询 4: 用户导出历史 (日期范围筛选)
-- ============================================================================
-- 场景: GET /api/v1/exports?from=2025-01-01&to=2025-01-31
-- 频率: 低频 (用户查看自己的导出记录)
-- 目标: < 10ms (复合索引)

SELECT id, data_type, format, file_size_bytes, status, error_message, created_at
FROM export_history
WHERE user_id = 'a0000000-0000-4000-8000-000000000002'
  AND created_at BETWEEN '2025-01-01 00:00:00' AND '2025-01-31 23:59:59'
ORDER BY created_at DESC;

-- EXPLAIN 预期输出:
-- +----+-------------+----------------+-------+------------------+------+-------+-----+------+-----------------------+
-- | id | select_type | table          | type  | key              | ref  | rows  | filtered | Extra                    |
-- +----+-------------+----------------+-------+------------------+------+-------+-----+------+-----------------------+
-- |  1 | SIMPLE      | export_history | range | idx_user_created | NULL |     5 |   100.00 | Using index condition   |
-- +----+-------------+----------------+-------+------------------+------+-------+-----+------+-----------------------+
-- 解释:
--   type=range                    — 范围扫描
--   key=idx_user_created(user_id, created_at DESC) — 复合索引, user_id 精确定位 + created_at 范围扫描
--   rows=5                        — 用户月导出量极小
--   Using index condition         — MySQL 5.6+ ICP (Index Condition Pushdown), 在引擎层过滤


-- ============================================================================
-- 查询 5: 过期会话清理 (定时任务)
-- ============================================================================
-- 场景: 定时任务 (每 6 小时) 清理过期 JWT refresh token 会话
-- 频率: 定时 (4次/天)
-- 目标: < 100ms

-- 步骤 1: 软撤销过期会话 (保留记录用于审计)
UPDATE sessions
SET revoked_at = NOW()
WHERE expires_at < NOW()
  AND revoked_at IS NULL
LIMIT 1000;  -- 分批处理，避免长事务锁表

-- EXPLAIN 预期 (转为 SELECT 分析):
-- SELECT id FROM sessions
-- WHERE expires_at < NOW() AND revoked_at IS NULL LIMIT 1000;
-- +----+-------------+----------+-------+----------------+------+-------+-----+------+-------------+
-- | id | select_type | table    | type  | key            | ref  | rows  | filtered | Extra       |
-- +----+-------------+----------+-------+----------------+------+-------+-----+------+-------------+
-- |  1 | SIMPLE      | sessions | range | idx_expires_at | NULL |   500 |    50.00 | Using where |
-- +----+-------------+----------+-------+----------------+------+-------+-----+------+-------------+
-- 解释:
--   type=range              — 范围扫描过期时间
--   key=idx_expires_at      — 使用过期时间索引
--   rows=500                — 取决于当前过期量
--   LIMIT 1000 分批         — 防止一次性删除过多行引发长事务

-- 步骤 2 (可选): 定期硬删除已被撤销超过 7 天的记录
DELETE FROM sessions
WHERE revoked_at IS NOT NULL
  AND revoked_at < DATE_SUB(NOW(), INTERVAL 7 DAY)
LIMIT 500;


-- ============================================================================
-- 查询 6: 公开分析发现 (社区分享)
-- ============================================================================
-- 场景: GET /api/v1/analyses/discover — 浏览其他用户公开分享的分析
-- 频率: 中频
-- 目标: < 10ms

SELECT a.id, a.name, a.analysis_type, a.created_at,
       u.display_name AS author_name
FROM saved_analyses a
JOIN users u ON a.user_id = u.id
WHERE a.is_public = 1
  AND a.deleted_at IS NULL
ORDER BY a.created_at DESC
LIMIT 20 OFFSET 0;

-- EXPLAIN 预期输出:
-- +----+-------------+-------+------+--------------------+------+-------+-----+------+-------------+
-- | id | select_type | table | type | key                | ref  | rows  | filtered | Extra       |
-- +----+-------------+-------+------+--------------------+------+-------+-----+------+-------------+
-- |  1 | SIMPLE      | a     | ref  | idx_public_created | const|    30 |   100.00 | Using where |
-- |  1 | SIMPLE      | u     | eq_ref| PRIMARY           | a.user_id | 1 |   100.00 | NULL        |
-- +----+-------------+-------+------+--------------------+------+-------+-----+------+-------------+
-- 解释:
--   驱动表 a: type=ref, key=idx_public_created — 过滤公开分析
--   被驱动表 u: type=eq_ref, key=PRIMARY — 主键关联, 每行 a 匹配 1 行 u
--   EQ_REF = JOIN 最优类型 (唯一索引等值关联)


-- ============================================================================
-- 查询 7: API Key 校验
-- ============================================================================
-- 场景: 每个携带 API Key 的请求都要验证 (从 Authorization: Bearer sk_xxx 头提取)
-- 频率: 极高 (每次 API 调用)
-- 优化: 用 Redis 缓存验证结果 (key = api_key:{key_hash}, TTL = 5 分钟)
-- 目标: < 1ms (有 Redis 缓存时)

-- 步骤 1: 应用层计算 key_hash = SHA-256(raw_key)
-- 步骤 2: 查 Redis → 命中则直接放行
-- 步骤 3: Redis 未命中时查 MySQL
SELECT id, user_id, permissions, expires_at
FROM api_keys
WHERE key_hash = 'abc123def456...'
  AND revoked_at IS NULL
  AND (expires_at IS NULL OR expires_at > NOW());

-- EXPLAIN 预期:
-- +----+-------------+----------+-------+-------------+-------+-------+-----+------+-------+
-- | id | select_type | table    | type  | key         | ref   | rows  | filtered | Extra |
-- +----+-------------+----------+-------+-------------+-------+-------+-----+------+-------+
-- |  1 | SIMPLE      | api_keys | const | uk_key_hash | const |     1 |   100.00 | NULL  |
-- +----+-------------+----------+-------+-------------+-------+-------+-----+------+-------+
-- 解释:
--   type=const — 唯一索引, 最优
--   rows=1     — 1 行

-- ============================================================================
-- N+1 反模式识别与优化
-- ============================================================================

-- 反模式 1: "加载用户列表 + 每个用户的最近分析"
--   错误写法 (伪代码):
--     users = SELECT * FROM users LIMIT 10                       -- 1 query
--     for user in users:                                          -- N queries
--         analyses = SELECT * FROM saved_analyses WHERE user_id = user.id LIMIT 3
--   问题: 11 次数据库往返 (1 + 10)
--
--   优化 A: 使用 JOIN + 窗口函数 (MySQL 8.0+)
SELECT u.id, u.display_name, a.id AS analysis_id, a.name, a.analysis_type, a.created_at
FROM users u
LEFT JOIN (
    SELECT sa.*,
           ROW_NUMBER() OVER (PARTITION BY user_id ORDER BY created_at DESC) AS rn
    FROM saved_analyses sa
    WHERE sa.deleted_at IS NULL
) a ON u.id = a.user_id AND a.rn <= 3
WHERE u.deleted_at IS NULL
  AND u.role = 'analyst'
ORDER BY u.id, a.created_at DESC;
--   结果: 1 次查询, 应用层按 user_id 分组即可
--
--   优化 B: 使用 LATERAL JOIN (MySQL 8.0.14+) — 更直观
-- SELECT u.id, u.display_name, a.name, a.analysis_type
-- FROM users u
-- LEFT JOIN LATERAL (
--     SELECT * FROM saved_analyses
--     WHERE user_id = u.id AND deleted_at IS NULL
--     ORDER BY created_at DESC LIMIT 3
-- ) a ON true
-- WHERE u.deleted_at IS NULL AND u.role = 'analyst';


-- 反模式 2: "加载分析列表 + 每个分析的作者信息"
--   错误写法 (伪代码):
--     analyses = SELECT * FROM saved_analyses WHERE is_public = 1 LIMIT 20;  -- 1 query
--     for analysis in analyses:                                                 -- N queries
--         author = SELECT display_name FROM users WHERE id = analysis.user_id
--   问题: 21 次查询
--
--   优化: 单次 JOIN (参见查询 6)
SELECT a.*, u.display_name AS author_name
FROM saved_analyses a
JOIN users u ON a.user_id = u.id
WHERE a.is_public = 1 AND a.deleted_at IS NULL
ORDER BY a.created_at DESC
LIMIT 20;
--   结果: 1 次查询, 20 行


-- 反模式 3: "获取导出历史 + 每个导出的分析名称"
--   错误写法: 同反模式 2 结构
--
--   优化:
SELECT e.id, e.data_type, e.format, e.file_size_bytes, e.status, e.created_at,
       COALESCE(a.name, '直接导出') AS analysis_name
FROM export_history e
LEFT JOIN saved_analyses a ON e.analysis_id = a.id
WHERE e.user_id = 'a0000000-0000-4000-8000-000000000002'
ORDER BY e.created_at DESC
LIMIT 20;


-- ============================================================================
-- 反模式 4: "SELECT * 查询"
-- ============================================================================
-- 问题: 取出大字段 (JSON parameters, TEXT error_message) 不需要
-- 影响: 网络传输放大 + InnoDB 可能访问溢出页 (off-page storage for BLOB/TEXT)
-- 修复: 只取需要的列
--   差: SELECT * FROM saved_analyses WHERE user_id = ?
--   好: SELECT id, name, analysis_type, created_at FROM saved_analyses WHERE user_id = ?


-- ============================================================================
-- 反模式 5: "缺失外键索引"
-- ============================================================================
-- 问题: saved_analyses.user_id 有 FK 但没有独立索引 (已在复合索引首列, 此项目 OK)
-- 检查所有 FK 都有对应的首列索引:
--   sessions.user_id          → KEY idx_user_id(user_id)              ✅
--   saved_analyses.user_id    → KEY idx_user_created(user_id, ...)    ✅
--   export_history.user_id    → KEY idx_user_created(user_id, ...)    ✅
--   export_history.analysis_id → 分析相关的查询通常是 "某分析的所有导出", 频率低, 可加可不加
--   api_keys.user_id          → KEY idx_user_id(user_id)              ✅
--   system_config.updated_by  → 极少使用, 不需要索引
