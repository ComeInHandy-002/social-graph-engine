-- ============================================================================
-- SocialGraph Pro — 回滚脚本 (DOWN Migration)
-- 版本: 1.0.0
-- 执行此脚本将完全移除所有业务表 (保留数据库本身)
-- WARNING: 所有数据将不可恢复！
-- ============================================================================

USE socialgraph;

-- 按外键依赖顺序反向删除 (子表先删, 父表后删)
DROP TABLE IF EXISTS api_keys;
DROP TABLE IF EXISTS export_history;
DROP TABLE IF EXISTS saved_analyses;
DROP TABLE IF EXISTS sessions;
DROP TABLE IF EXISTS system_config;
DROP TABLE IF EXISTS users;
