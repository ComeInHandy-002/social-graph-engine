-- ============================================================================
-- SocialGraph Pro — MySQL 初始化建表脚本
-- 版本: 1.0.0
-- 引擎: InnoDB (行级锁，事务支持)
-- 字符集: utf8mb4 (完整 Unicode 支持，含 emoji)
-- 排序规则: utf8mb4_unicode_ci (大小写不敏感，适合用户输入)
-- ============================================================================

CREATE DATABASE IF NOT EXISTS socialgraph
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_unicode_ci;

USE socialgraph;

-- ============================================================================
-- 部门 1: 用户账户 (users)
-- ============================================================================
-- 主键策略: CHAR(36) UUID v4
-- 理由:
--   1. 分布式安全 — 未来若分库分表，UUID 不会发生主键冲突
--   2. 安全加固 — 自增 ID 暴露用户总量，UUID 防止枚举攻击 (e.g. /user/1, /user/2)
--   3. 前端暴露 — 用户 ID 会出现在 URL / WebSocket 消息中，UUID 不泄密
-- 代价:
--   - 存储: CHAR(36) = 36 bytes vs BIGINT = 8 bytes (4K 用户差 112KB, 可忽略)
--   - 写入: 随机 UUID 导致 B-tree 页分裂, 但 10K 用户 / day 的量级完全不构成瓶颈
--   - 替代方案 (未来): 使用 ULID 或 UUID v7 (时间有序) 可优化写入, 当前无需
-- ============================================================================
CREATE TABLE users (
    id              CHAR(36)        NOT NULL COMMENT 'UUID v4 主键',
    email           VARCHAR(255)    NOT NULL COMMENT '登录邮箱，全局唯一',
    password_hash   VARCHAR(255)    NOT NULL COMMENT 'bcrypt 哈希 (cost=12), 60字符 + 预留',
    display_name    VARCHAR(100)    NOT NULL COMMENT '用户显示名称',
    role            ENUM('admin','analyst','viewer') NOT NULL DEFAULT 'viewer'
                    COMMENT 'RBAC 角色: admin=全局管理, analyst=可运行分析, viewer=只读',
    avatar_url      VARCHAR(500)    NULL     COMMENT '头像 CDN 地址',
    email_verified_at DATETIME(3)   NULL     COMMENT '邮箱验证时间, NULL=未验证',
    last_login_at   DATETIME(3)     NULL     COMMENT '最后登录时间 (用于审计/流失分析)',
    created_at      DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    updated_at      DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
    deleted_at      DATETIME(3)     NULL     COMMENT '软删除时间, NULL=正常状态',

    PRIMARY KEY (id),
    UNIQUE KEY uk_email (email),
    KEY idx_role (role),
    KEY idx_deleted_at (deleted_at),
    KEY idx_created_at (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='用户账户表 — 核心身份认证数据';

-- 行大小估算 (未加索引):
--   CHAR(36)+VARCHAR(255)+VARCHAR(255)+VARCHAR(100)+ENUM(1)+VARCHAR(500)+
--   3×DATETIME(3)+2×DATETIME(3)+DATETIME(3)+ 开销 ≈ 1200 bytes / 行
-- 增长预测: 启动 50 分析师 → 1 年 500 用户 → 3 年 < 5K 用户

-- ============================================================================
-- 部门 2: 用户会话 (sessions)
-- ============================================================================
-- 设计目标:
--   - 支持一个用户多设备登录 (手机 + 桌面 + 平板 各自独立会话)
--   - refresh_token 仅存哈希, 即使数据库泄露也无法伪造 token
--   - 定时清理过期会话 (MySQL Event Scheduler 或 应用 Cron)
-- ============================================================================
CREATE TABLE sessions (
    id                  CHAR(36)        NOT NULL COMMENT 'UUID v4 会话 ID',
    user_id             CHAR(36)        NOT NULL COMMENT '关联用户',
    refresh_token_hash  VARCHAR(255)    NOT NULL COMMENT 'SHA-256(refresh_token), 从不存明文',
    device_info         VARCHAR(500)    NULL     COMMENT 'User-Agent 摘要 (浏览器/OS)',
    ip_address          VARCHAR(45)     NULL     COMMENT '登录 IP (IPv4:15字节 / IPv6:45字节)',
    expires_at          DATETIME(3)     NOT NULL COMMENT 'refresh token 过期时间 (典型 30 天)',
    created_at          DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    revoked_at          DATETIME(3)     NULL     COMMENT '主动登出 / 强制撤销时间',

    PRIMARY KEY (id),
    KEY idx_user_id (user_id),
    KEY idx_expires_at (expires_at),
    KEY idx_refresh_token_hash (refresh_token_hash),
    CONSTRAINT fk_sessions_user
        FOREIGN KEY (user_id) REFERENCES users(id)
        ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='JWT refresh token 会话表 — 多设备管理';

-- 行大小估算: ~450 bytes / 行
-- 增长预测: 500 用户 × 平均 3 设备 = 1500 活跃会话
-- 清理策略: 每 6 小时运行 DELETE/UPDATE revoked_at WHERE expires_at < NOW()

-- ============================================================================
-- 部门 3: 保存的分析配置 (saved_analyses)
-- ============================================================================
-- 用途: 用户可保存分析参数配置，下次一键重跑
-- 典型场景: "我对 PageRank(d=0.85, iter=200) 的结果很满意，保存为'核心用户排序'"
-- JSON 参数存储: MySQL 5.7+ 原生 JSON 类型，支持虚拟列索引和 JSON 路径查询
-- ============================================================================
CREATE TABLE saved_analyses (
    id              CHAR(36)        NOT NULL COMMENT 'UUID v4',
    user_id         CHAR(36)        NOT NULL COMMENT '所有者',
    name            VARCHAR(255)    NOT NULL COMMENT '用户自定义分析名称 (如 "2024 Q1 影响力报告")',
    analysis_type   VARCHAR(50)     NOT NULL COMMENT '算法类型: pagerank|community|betweenness|kcore|clustering|connected_components|shortest_path|dijkstra|echo_chamber|graph_stats',
    parameters      JSON            NOT NULL COMMENT '算法参数 JSON (不含结果, 结果存 MongoDB)',
    is_public       TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '是否公开分享 (0=私有, 1=公开)',
    created_at      DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    updated_at      DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
    deleted_at      DATETIME(3)     NULL     COMMENT '软删除',

    -- 虚拟列: 从 JSON 字段中抽取高频过滤键 (MySQL 5.7+)
    -- 例如 JSON 参数内的 start_node / target_node 可用于索引加速
    -- param_start_node VARCHAR(50) GENERATED ALWAYS AS (parameters->>'$.start_node') VIRTUAL,

    PRIMARY KEY (id),
    KEY idx_user_created (user_id, created_at DESC),
    KEY idx_type (analysis_type, created_at DESC),
    KEY idx_public_created (is_public, created_at DESC),
    KEY idx_deleted_at (deleted_at),
    CONSTRAINT fk_analyses_user
        FOREIGN KEY (user_id) REFERENCES users(id)
        ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='用户保存的分析配置 — 参数存 JSON, 结果存 MongoDB';

-- 行大小估算: 基础 ~800 bytes + JSON (~200 bytes) ≈ 1000 bytes
-- 增长预测: 500 用户 × 平均 20 次分析保存 = 10K 行
-- 复合索引 idx_user_created 同时服务于:
--   (a) WHERE user_id = ? ORDER BY created_at DESC (个人分析列表)
--   (b) WHERE user_id = ? AND deleted_at IS NULL ORDER BY created_at DESC (活跃分析)

-- ============================================================================
-- 部门 4: 导出历史 (export_history)
-- ============================================================================
-- 用途: 跟踪每一次数据导出操作 (CSV / JSON / Parquet)
-- 审计日志: 谁在什么时候导出了什么数据，文件多大
-- ============================================================================
CREATE TABLE export_history (
    id              CHAR(36)        NOT NULL COMMENT 'UUID v4',
    user_id         CHAR(36)        NOT NULL COMMENT '导出者',
    analysis_id     CHAR(36)        NULL     COMMENT '关联的分析 ID (可能为空, 如原始拓扑导出)',
    data_type       VARCHAR(50)     NOT NULL COMMENT '导出数据类型: pagerank|community|betweenness|topology|etc.',
    format          ENUM('csv','json','parquet') NOT NULL COMMENT '导出文件格式',
    file_size_bytes BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '文件大小 (字节)',
    status          ENUM('pending','processing','completed','failed') NOT NULL DEFAULT 'pending',
    error_message   TEXT            NULL     COMMENT '失败原因 (status=failed 时填充)',
    created_at      DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3),

    PRIMARY KEY (id),
    KEY idx_user_created (user_id, created_at DESC),
    KEY idx_status (status),
    KEY idx_date_type (data_type, created_at DESC),
    CONSTRAINT fk_export_user
        FOREIGN KEY (user_id) REFERENCES users(id)
        ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT fk_export_analysis
        FOREIGN KEY (analysis_id) REFERENCES saved_analyses(id)
        ON DELETE SET NULL ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='文件导出审计日志 — 追踪每次 CSV/JSON/Parquet 导出';

-- 行大小估算: ~500 bytes / 行
-- 增长预测: 500 用户 × 每月 5 次导出 × 12 月 = 30K/年

-- ============================================================================
-- 部门 5: 系统配置 (system_config)
-- ============================================================================
-- 用途: 动态系统参数，无需重启即可生效 (如 API 限流阈值, 前端开关, 维护模式)
-- 替代方案对比:
--   - .env 文件: 需要重启, 不适合动态变更
--   - etcd/Consul: 过重，当前规模不需要
--   - 数据库 KV 表: 轻量、事务安全、变更审计
-- ============================================================================
CREATE TABLE system_config (
    id              INT             NOT NULL AUTO_INCREMENT COMMENT '自增 ID (配置项少, 无需 UUID)',
    config_key      VARCHAR(100)    NOT NULL COMMENT '配置键名 (e.g. rate_limit.per_minute)',
    config_value    TEXT            NOT NULL COMMENT '配置值 (字符串存储, 应用层解析类型)',
    value_type      ENUM('string','int','float','bool','json') NOT NULL DEFAULT 'string'
                    COMMENT '值类型提示, 帮助应用层正确解析',
    description     VARCHAR(500)    NULL     COMMENT '配置说明 (人类可读)',
    updated_by      CHAR(36)        NULL     COMMENT '最后修改者 (管理员 ID)',
    created_at      DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    updated_at      DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),

    PRIMARY KEY (id),
    UNIQUE KEY uk_config_key (config_key),
    CONSTRAINT fk_config_updater
        FOREIGN KEY (updated_by) REFERENCES users(id)
        ON DELETE SET NULL ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='系统动态配置 — KV 存储, 支持运行时热更新';

-- 行大小估算: ~300 bytes / 行, 预计 < 50 行

-- ============================================================================
-- 部门 6: API 密钥管理 (api_keys)
-- ============================================================================
-- 用途: 未来支持外部程序通过 API Key 调用分析接口
-- 安全设计:
--   - 仅存储 key_hash (SHA-256), 前缀 key_prefix 用于 UI 展示 (如 "sk_a1b2...c3d4")
--   - 细粒度权限控制 (JSON 数组: ["read:graph", "run:pagerank", "export:csv"])
--   - 支持到期时间 和 主动撤销
-- ============================================================================
CREATE TABLE api_keys (
    id              CHAR(36)        NOT NULL COMMENT 'UUID v4',
    user_id         CHAR(36)        NOT NULL COMMENT '密钥所有者',
    key_hash        VARCHAR(255)    NOT NULL COMMENT 'SHA-256(api_key_raw), 从不存明文',
    key_prefix      VARCHAR(12)     NOT NULL COMMENT '密钥前缀用于 UI 展示 (如 sk_a1b2c3d4...)',
    name            VARCHAR(100)    NOT NULL COMMENT '密钥用途标签 (如 "自动化报告脚本")',
    permissions     JSON            NOT NULL COMMENT '权限范围: ["read:graph","run:pagerank","export:csv"]',
    last_used_at    DATETIME(3)     NULL     COMMENT '最近使用时间 (监控/清理用)',
    expires_at      DATETIME(3)     NULL     COMMENT '到期时间, NULL=永不过期',
    created_at      DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    revoked_at      DATETIME(3)     NULL     COMMENT '撤销时间, NULL=有效',

    PRIMARY KEY (id),
    UNIQUE KEY uk_key_hash (key_hash),
    KEY idx_user_id (user_id),
    KEY idx_expires_at (expires_at),
    CONSTRAINT fk_apikey_user
        FOREIGN KEY (user_id) REFERENCES users(id)
        ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='API 密钥管理 — 程序化访问授权';

-- 行大小估算: ~600 bytes / 行
-- 增长预测: 50 个活跃密钥 (仅面向高级用户/内部工具)

-- ============================================================================
-- 插入默认系统配置
-- ============================================================================
INSERT INTO system_config (config_key, config_value, value_type, description) VALUES
('rate_limit.anonymous_per_minute', '10', 'int', '匿名用户每分钟 API 请求上限'),
('rate_limit.authenticated_per_minute', '60', 'int', '登录用户每分钟 API 请求上限'),
('rate_limit.api_key_per_minute', '300', 'int', 'API Key 用户每分钟请求上限'),
('cache.default_ttl_seconds', '3600', 'int', 'Redis 缓存默认 TTL (秒)'),
('cache.algorithm_result_ttl_seconds', '86400', 'int', '图算法结果缓存 TTL (秒) — 数据静态, 1天'),
('cache.topology_ttl_seconds', '3600', 'int', '拓扑结构缓存 TTL (秒) — 变更频率低'),
('session.refresh_token_lifetime_days', '30', 'int', 'Refresh Token 有效天数'),
('session.access_token_lifetime_minutes', '15', 'int', 'Access Token 有效分钟数'),
('export.max_file_size_bytes', '52428800', 'int', '单次导出文件大小上限 (50MB)'),
('maintenance.mode', 'false', 'bool', '维护模式开关 (true=只允许 admin 访问)');
