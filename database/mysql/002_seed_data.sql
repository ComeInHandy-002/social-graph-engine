-- ============================================================================
-- SocialGraph Pro — 种子数据
-- ============================================================================
-- 密码: "Admin@123456" -> bcrypt hash (cost=12)
-- 生产环境请使用应用层生成的 hash 替换

USE socialgraph;

-- 管理员账户
INSERT INTO users (id, email, password_hash, display_name, role, email_verified_at) VALUES
('a0000000-0000-4000-8000-000000000001', 'admin@socialgraph.io',
 '$2b$12$LJ3m4ys3Lk0TSwHCpNqrQO5zHLh4HZBxhqF6fXNxHxqgG8G8G8G8G',  -- placeholder, 应用层替换
 '系统管理员', 'admin', NOW());

-- 演示分析师账户
INSERT INTO users (id, email, password_hash, display_name, role, email_verified_at) VALUES
('a0000000-0000-4000-8000-000000000002', 'analyst@socialgraph.io',
 '$2b$12$LJ3m4ys3Lk0TSwHCpNqrQO5zHLh4HZBxhqF6fXNxHxqgG8G8G8G8G',  -- placeholder
 '数据分析师', 'analyst', NOW());

-- 演示只读账户
INSERT INTO users (id, email, password_hash, display_name, role, email_verified_at) VALUES
('a0000000-0000-4000-8000-000000000003', 'viewer@socialgraph.io',
 '$2b$12$LJ3m4ys3Lk0TSwHCpNqrQO5zHLh4HZBxhqF6fXNxHxqgG8G8G8G8G',  -- placeholder
 '访客用户', 'viewer', NOW());
