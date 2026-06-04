// ============================================================================
// SocialGraph Pro — MongoDB 集合设计与运维手册
// 版本: 2.0.0 (生产级增强版)
// 数据库: socialgraph_analytics
// 兼容: MongoDB 5.0+ / 6.0 / 7.0
// ============================================================================
// 变更日志:
//   v2.0.0 — 新增 cache_registry + graph_snapshots 集合; 增强分布式追踪字段;
//           8 个生产级聚合管道; 完整索引策略(ESR+Partial+Text+Wildcard);
//           分片评估; 备份恢复脚本
//   v1.0.0 — 初始版本: analysis_snapshots + operation_logs + performance_metrics
// ============================================================================
// MongoDB 选型理由:
//   - 分析结果数据结构多变 (PageRank → {node, score}，
//     LPA → {node, community}，路径查询 → {path: [...]})
//   - JSON 文档天然适配半结构化算法输出
//   - TTL 索引自动清理历史快照和日志，无需 cron 定时 DELETE
//   - 聚合管道实现运营分析，无需额外 OLAP 系统
//   - 时间序列集合原生支持压缩与自动分桶
// ============================================================================

// ============================================================================
// 全局写关注 (Write Concern) 策略
// ============================================================================
// | 场景               | writeConcern | 说明                             |
// |--------------------|-------------|----------------------------------|
// | analysis_snapshots | { w: 1 }    | 算法结果可重算，w:1 足够         |
// | operation_logs     | { w: 0 }    | fire-and-forget，极致低延迟      |
// | performance_metrics| { w: 0 }    | 高频写入，不阻塞 API 响应        |
// | cache_registry     | { w: 1 }    | 缓存状态需即时一致               |
// | graph_snapshots    | { w: 1 }    | 定期写入，频率低无性能压力       |
// | 批量运维写入        | { w: "majority" } | 数据一致性优先              |
// =============================================================================

// ============================================================================
// 全局读偏好 (Read Preference) 策略
// ============================================================================
//   primaryPreferred — 优先读主节点（实时一致性），主节点不可用时降级读副本
//   Python 驱动: readPreference="primaryPreferred"
//   适用: 所有读操作（分析结果查询、日志聚合、指标看板）
// ============================================================================

// ============================================================================
// 第 1 部分: 集合定义、校验器与索引 (5 个集合)
// ============================================================================

// ════════════════════════════════════════════════════════════════════════════
// 集合 1: analysis_snapshots — 算法运行结果快照
// ════════════════════════════════════════════════════════════════════════════
// 用途: 保存每次算法运行的完整输出。
// 设计决策:
//   - 算法结果嵌入 (embed) 而非引用：结果数据与快照强绑定，无独立查询需求，
//     嵌入避免 $lookup 开销，单文档读取即可获得完整快照。
//   - graph_snapshot 子文档（图中嵌入）：记录快照时的图统计，避免跨集合关联。
//   - 存储估算: 单文档 ~3-8 KB (PageRank 1000 节点 ≈ 25KB 数组; 路径 ≈ 500B)
//               平均 ~5KB/doc * 1000/day * 365 = ~1.8GB/year
// ============================================================================

db.createCollection("analysis_snapshots", {
    validator: {
        $jsonSchema: {
            bsonType: "object",
            required: ["snapshot_id", "user_id", "algorithm", "result_data", "created_at"],
            additionalProperties: false,
            properties: {
                snapshot_id: {
                    bsonType: "string",
                    pattern: "^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
                    description: "UUID v4，快照全局唯一标识"
                },
                request_id: {
                    bsonType: "string",
                    description: "关联 HTTP 请求的 X-Request-ID，用于分布式追踪"
                },
                user_id: {
                    bsonType: "string",
                    description: "关联 users.id (UUID)，anonymous 表示未登录"
                },
                analysis_id: {
                    bsonType: ["string", "null"],
                    description: "关联 MySQL saved_analyses.id；null=快速运行未保存到MySQL"
                },
                algorithm: {
                    bsonType: "string",
                    enum: [
                        "pagerank", "community", "betweenness", "kcore",
                        "clustering_coeff", "connected_components",
                        "shortest_path", "dijkstra", "echo_chamber", "graph_stats",
                        "bfs", "dfs", "label_propagation", "triangle_count",
                        "closeness_centrality", "eigenvector_centrality"
                    ],
                    description: "算法类型标识"
                },
                parameters: {
                    bsonType: "object",
                    description: "运行时的算法参数（冗余存储，便于回放和历史对比）",
                    properties: {
                        damping_factor: {
                            bsonType: ["double", "null"],
                            description: "PageRank 阻尼系数，默认 0.85"
                        },
                        max_iterations: {
                            bsonType: ["int", "null"],
                            description: "最大迭代次数"
                        },
                        source_node: {
                            bsonType: ["string", "null"],
                            description: "路径类算法的起始节点"
                        },
                        target_node: {
                            bsonType: ["string", "null"],
                            description: "路径类算法的目标节点"
                        },
                        k_value: {
                            bsonType: ["int", "null"],
                            description: "K-Core 的 K 值"
                        },
                        description: {
                            bsonType: "string",
                            description: "用户自定义分析备注，用于全文搜索"
                        }
                    }
                },
                result_data: {
                    bsonType: "array",
                    description: "核心算法输出。PageRank→[{node,score}]，LPA→[{node,community}]，路径→[{step,node}]"
                },
                result_metadata: {
                    bsonType: "object",
                    description: "非数组结果（如最短路径串、图聚合统计、异常检测分数等）"
                },
                result_summary: {
                    bsonType: "object",
                    description: "结果摘要（用于仪表板预览，避免加载完整数组）",
                    properties: {
                        top_nodes: {
                            bsonType: "array",
                            description: "PageRank Top 10 节点 [{node,score}]"
                        },
                        community_count: {
                            bsonType: ["int", "null"],
                            description: "LPA 发现的社区数量"
                        },
                        path_length: {
                            bsonType: ["int", "null"],
                            description: "最短路径跳数"
                        },
                        graph_density: {
                            bsonType: ["double", "null"],
                            description: "图密度"
                        }
                    }
                },
                execution_time_ms: {
                    bsonType: "int",
                    minimum: 0,
                    description: "C++ 引擎执行耗时 (毫秒)"
                },
                graph_snapshot: {
                    bsonType: "object",
                    description: "运行时图统计信息（嵌入，避免跨集合查询）",
                    properties: {
                        node_count: {
                            bsonType: "int",
                            minimum: 0
                        },
                        edge_count: {
                            bsonType: "int",
                            minimum: 0
                        },
                        data_file_hash: {
                            bsonType: "string",
                            description: "图数据文件 MD5，用于检测数据变更"
                        },
                        density: {
                            bsonType: ["double", "null"],
                            description: "图密度 = 2*E/(N*(N-1))"
                        }
                    }
                },
                engine_version: {
                    bsonType: "string",
                    description: "C++ 引擎版本号，用于追溯性能回归"
                },
                cache_hit: {
                    bsonType: "bool",
                    description: "是否命中 Redis 缓存（true=跳过 C++ 计算）"
                },
                tags: {
                    bsonType: "array",
                    description: "用户自定义标签，如 [\"production\", \"benchmark\", \"demo\"]",
                    items: { bsonType: "string" }
                },
                created_at: {
                    bsonType: "date",
                    description: "快照创建时间 (UTC)"
                }
            }
        }
    },
    validationLevel: "moderate",
    validationAction: "warn"
});

// --- 索引: analysis_snapshots ---

// 1. 主键 — snapshot_id 唯一索引
db.analysis_snapshots.createIndex(
    { snapshot_id: 1 },
    { unique: true, name: "idx_snapshot_id" }
);

// 2. ESR: E=user_id, S=created_at — "我的分析"时间线
db.analysis_snapshots.createIndex(
    { user_id: 1, created_at: -1 },
    { name: "idx_user_timeline" }
);

// 3. ESR: E=algorithm, S=created_at — 仪表板: 某算法近期趋势
db.analysis_snapshots.createIndex(
    { algorithm: 1, created_at: -1 },
    { name: "idx_algorithm_time" }
);

// 4. ESR: E=user_id, E=algorithm, S=created_at — 用户按算法筛选
db.analysis_snapshots.createIndex(
    { user_id: 1, algorithm: 1, created_at: -1 },
    { name: "idx_user_algo_time" }
);

// 5. ESR: E=algorithm, S=execution_time_ms — 慢算法排行
db.analysis_snapshots.createIndex(
    { algorithm: 1, execution_time_ms: -1 },
    { name: "idx_algo_exec_time" }
);

// 6. TTL 索引 — 90 天后自动清理
db.analysis_snapshots.createIndex(
    { created_at: 1 },
    { expireAfterSeconds: 7776000, name: "idx_ttl_90d" }
);

// 7. 部分索引 — 仅索引慢查询 (>1s)，过滤掉 95% 的快速执行，索引大小减少 ~95%
db.analysis_snapshots.createIndex(
    { algorithm: 1, execution_time_ms: -1, created_at: -1 },
    { partialFilterExpression: { execution_time_ms: { $gt: 1000 } }, name: "idx_slow_queries_partial" }
);

// 8. 文本索引 — 支持按算法名或用户备注搜索
db.analysis_snapshots.createIndex(
    { algorithm: "text", "parameters.description": "text" },
    { name: "idx_text_search", weights: { algorithm: 10, "parameters.description": 5 } }
);

// 9. 通配符索引 — 灵活查询 result_metadata 中的动态字段
db.analysis_snapshots.createIndex(
    { "result_metadata.$**": 1 },
    { name: "idx_metadata_wildcard" }
);

// 10. request_id — 分布式追踪
db.analysis_snapshots.createIndex(
    { request_id: 1 },
    { name: "idx_request_id" }
);


// ════════════════════════════════════════════════════════════════════════════
// 集合 2: operation_logs — 用户操作审计日志
// ════════════════════════════════════════════════════════════════════════════
// 用途: 审计/调试/安全分析。记录每一次 API 调用。
//
// Capped vs TTL 分析:
//   capped 集合 (固定大小循环覆盖):
//     优点: 写入性能极高(O(1)追加)，自动清理最老文档，无需索引维护
//     缺点: 大小限制固定(max 1GB)，达到上限后丢新数据；无法删除/更新单文档；
//           无法支持复杂查询(需额外集合)；无法升级/拆分
//     适用: 低价值、高频率、仅尾部读取的日志(如调试日志)
//   TTL 集合 (基于时间过期):
//     优点: 按时间清理(符合审计需求"保留30天")；文档可删除；支持任意查询；
//           保留周期可按需调整；单集合查询即可
//     缺点: 定期扫描过期文档有后台开销；写入性能略低于 capped
//     适用: 有明确保留期的业务日志
//   选定: TTL — operation_logs 有明确的 30 天保留需求和复杂查询需求(聚合管道/过滤)
//
// 批量写入优化:
//   - Python 侧使用 insert_many(ordered=False) 合并 100ms 窗口内的日志写入
//   - Motor 异步驱动天然的背压处理: 连接池 max 50
//   - 宽松校验 (validationAction: "warn"): 结构异常不丢数据
//
// 预聚合策略:
//   - 每小时由定时任务执行 aggregate → 写入 operation_stats_hourly (第2.5节)
//   - 仪表板直接查询预聚合集合，避免扫描数百万原始日志
// ============================================================================

db.createCollection("operation_logs", {
    validator: {
        $jsonSchema: {
            bsonType: "object",
            required: ["user_id", "action", "created_at"],
            additionalProperties: false,
            properties: {
                user_id: {
                    bsonType: "string",
                    description: "操作者 ID，匿名请求为 'anonymous'"
                },
                request_id: {
                    bsonType: "string",
                    description: "HTTP X-Request-ID (UUID 前缀)，关联同一次请求的所有日志"
                },
                correlation_id: {
                    bsonType: "string",
                    description: "跨服务调用链 ID，用于连接 API→C++引擎→数据库的调用链"
                },
                action: {
                    bsonType: "string",
                    enum: [
                        "run_algorithm", "export_data", "save_analysis",
                        "delete_analysis", "login", "logout", "token_refresh",
                        "create_api_key", "revoke_api_key", "update_config",
                        "view_dashboard", "view_graph", "upload_data",
                        "ws_connect", "ws_disconnect", "ws_message"
                    ],
                    description: "操作类型"
                },
                resource: {
                    bsonType: "string",
                    description: "操作目标资源名 (如 pagerank, community, /api/v1/graph/all)"
                },
                endpoint: {
                    bsonType: "string",
                    description: "API 端点路径 (如 /api/v1/graph/pagerank)"
                },
                http_method: {
                    bsonType: "string",
                    enum: ["GET", "POST", "PUT", "DELETE", "PATCH", "WS"],
                    description: "HTTP 方法或 WebSocket"
                },
                details: {
                    bsonType: "object",
                    description: "操作详情，结构因 action 而异",
                    properties: {
                        algorithm: { bsonType: "string", description: "运行的算法" },
                        parameters: { bsonType: "object", description: "算法参数" },
                        cache_hit: { bsonType: "bool", description: "是否命中 Redis 缓存" },
                        export_format: { bsonType: "string", description: "导出格式 (json/csv/xml)" },
                        file_size_bytes: { bsonType: "int", description: "导出文件大小" },
                        ws_event: { bsonType: "string", description: "WebSocket 事件类型" },
                        graph_size: { bsonType: "string", description: "数据规模标签 (10K/50K/100K)" }
                    }
                },
                ip_address: {
                    bsonType: "string",
                    description: "请求来源 IP"
                },
                user_agent: {
                    bsonType: "string",
                    description: "User-Agent 头 (截断至 256 字符)"
                },
                duration_ms: {
                    bsonType: "int",
                    minimum: 0,
                    description: "操作耗时 (毫秒)"
                },
                status: {
                    bsonType: "string",
                    enum: ["success", "failure", "rate_limited", "unauthorized", "timeout"],
                    description: "执行结果"
                },
                error_code: {
                    bsonType: "string",
                    description: "失败时的错误码 (如 CPP_ENGINE_TIMEOUT、VALIDATION_ERROR)"
                },
                error_message: {
                    bsonType: "string",
                    description: "失败时的错误信息 (生产环境可能截断)"
                },
                stack_trace_hash: {
                    bsonType: "string",
                    description: "错误堆栈的 SHA256 前 8 位，用于聚合同类错误"
                },
                session_id: {
                    bsonType: "string",
                    description: "用户会话 ID，追踪同一会话内的操作序列"
                },
                metadata: {
                    bsonType: "object",
                    description: "扩展元数据 (环境信息、版本号等)",
                    properties: {
                        app_version: { bsonType: "string" },
                        environment: { bsonType: "string" },
                        engine_version: { bsonType: "string" }
                    }
                },
                created_at: {
                    bsonType: "date",
                    description: "操作发生时间 (UTC)"
                }
            }
        }
    },
    validationLevel: "moderate",
    validationAction: "warn"
});

// --- 索引: operation_logs ---

// 1. ESR: E=user_id, S=created_at — 审计: 某用户操作时间线
db.operation_logs.createIndex(
    { user_id: 1, created_at: -1 },
    { name: "idx_user_ops" }
);

// 2. ESR: E=action, S=created_at — 仪表板: 操作类型趋势
db.operation_logs.createIndex(
    { action: 1, created_at: -1 },
    { name: "idx_action_time" }
);

// 3. ESR: E=status, S=created_at — 错误监控: 近期失败操作
db.operation_logs.createIndex(
    { status: 1, created_at: -1 },
    { name: "idx_status_time" }
);

// 4. ESR: E=resource, S=created_at — 端点维度: 某算法调用趋势
db.operation_logs.createIndex(
    { resource: 1, created_at: -1 },
    { name: "idx_resource_time" }
);

// 5. ESR: E=action, E=status, S=created_at — 仪表板: 操作类型+状态组合筛选
db.operation_logs.createIndex(
    { action: 1, status: 1, created_at: -1 },
    { name: "idx_action_status_time" }
);

// 6. TTL — 30 天后自动清理
db.operation_logs.createIndex(
    { created_at: 1 },
    { expireAfterSeconds: 2592000, name: "idx_ttl_30d" }
);

// 7. request_id — 精确查找，用于分布式追踪回放
db.operation_logs.createIndex(
    { request_id: 1 },
    { name: "idx_request_id" }
);

// 8. correlation_id — 跨服务调用链追踪
db.operation_logs.createIndex(
    { correlation_id: 1 },
    { name: "idx_correlation_id" }
);

// 9. 部分索引 — 仅索引失败操作 (<5% 数据量)，快速定位异常
db.operation_logs.createIndex(
    { created_at: -1 },
    { partialFilterExpression: { status: { $in: ["failure", "timeout", "rate_limited"] } },
      name: "idx_failures_recent_partial" }
);

// 10. session_id — 会话追踪
db.operation_logs.createIndex(
    { session_id: 1, created_at: -1 },
    { name: "idx_session_time" }
);


// ════════════════════════════════════════════════════════════════════════════
// 集合 2.5: operation_stats_hourly — 操作日志预聚合 (小时级)
// ════════════════════════════════════════════════════════════════════════════
// 用途: 避免扫描百万级原始日志做仪表板查询。
// 更新: 每小时运行一次聚合任务 (由 Python cron / APScheduler 调度)，
//       从 operation_logs 聚合过去 1 小时数据写入此集合。
// 查询: 仪表板直接读此集合，1 个月 = 720 条文档 (远少于百万原始日志)。
// TTL: 90 天，比原始日志保留更久以支持季度趋势。
// 存储估算: 720 docs/month * ~1KB = ~1MB/year (可忽略)
// ============================================================================

db.createCollection("operation_stats_hourly", {
    validator: {
        $jsonSchema: {
            bsonType: "object",
            required: ["hour", "stats", "created_at"],
            properties: {
                hour: {
                    bsonType: "date",
                    description: "统计小时 (整点时间)"
                },
                total_operations: {
                    bsonType: "int",
                    description: "该小时总操作数"
                },
                unique_users: {
                    bsonType: "int",
                    description: "去重用户数"
                },
                status_breakdown: {
                    bsonType: "object",
                    description: "{success: N, failure: N, rate_limited: N, ...}"
                },
                action_breakdown: {
                    bsonType: "object",
                    description: "{run_algorithm: N, export_data: N, ...}"
                },
                resource_breakdown: {
                    bsonType: "object",
                    description: "{pagerank: N, community: N, ...}"
                },
                p50_duration_ms: {
                    bsonType: "double",
                    description: "所有操作 P50 延迟"
                },
                p95_duration_ms: {
                    bsonType: "double",
                    description: "所有操作 P95 延迟"
                },
                p99_duration_ms: {
                    bsonType: "double",
                    description: "所有操作 P99 延迟"
                },
                avg_duration_ms: {
                    bsonType: "double",
                    description: "平均延迟"
                },
                cache_hit_count: {
                    bsonType: "int",
                    description: "缓存命中次数"
                },
                cache_miss_count: {
                    bsonType: "int",
                    description: "缓存未命中次数"
                },
                top_ip_addresses: {
                    bsonType: "array",
                    description: "Top 5 来源 IP",
                    items: {
                        bsonType: "object",
                        properties: {
                            ip: { bsonType: "string" },
                            count: { bsonType: "int" }
                        }
                    }
                },
                error_codes: {
                    bsonType: "object",
                    description: "错误码 → 出现次数映射"
                },
                created_at: {
                    bsonType: "date",
                    description: "统计生成时间"
                }
            }
        }
    },
    validationLevel: "moderate"
});

// 索引: operation_stats_hourly
db.operation_stats_hourly.createIndex(
    { hour: -1 },
    { unique: true, name: "idx_hour_unique" }
);
db.operation_stats_hourly.createIndex(
    { created_at: 1 },
    { expireAfterSeconds: 7776000, name: "idx_ttl_90d" }
);


// ════════════════════════════════════════════════════════════════════════════
// 集合 3: performance_metrics — 性能指标时序数据
// ════════════════════════════════════════════════════════════════════════════
// 用途: 收集 C++ 引擎和 API 网关的性能数据。
//
// 时序集合优化 (MongoDB 5.0+):
//   - timeField: timestamp — 时间轴
//   - metaField: metric — 元数据字段（每个唯一 metric 值独立存储元数据）
//   - granularity: "seconds" — 匹配写入粒度 (每条 API 调用)
//   - bucketMaxSpanSeconds: 3600 (1小时) — 默认值，控制内存使用
//   - bucketRoundingSeconds: 3600 — 与小时预聚合对齐
//
// 下采样策略: raw(7d) → hourly(90d) → daily(1y)
//   - 原始数据 TTL=7 天: 最新 7 天保留完整精度
//   - 小时下采样 TTL=90 天: 由定时任务从原始数据聚合并写入 performance_metrics_hourly
//   - 天下采样 TTL=365 天: 从小时数据二次聚合
// ============================================================================

db.createCollection("performance_metrics", {
    validator: {
        $jsonSchema: {
            bsonType: "object",
            required: ["metric", "value", "timestamp"],
            additionalProperties: false,
            properties: {
                metric: {
                    bsonType: "string",
                    description: "指标名: pagerank.p50_ms / api.latency.avg_ms / cache.hit_rate / engine.cpu_percent"
                },
                value: {
                    bsonType: "double",
                    description: "指标数值"
                },
                unit: {
                    bsonType: "string",
                    enum: ["ms", "percent", "bytes", "count", "ops_per_sec", "MB"],
                    description: "单位"
                },
                tags: {
                    bsonType: "object",
                    description: "标签维度 (用于分组聚合)",
                    properties: {
                        algorithm: {
                            bsonType: "string",
                            description: "关联算法 (pagerank, community, ...)"
                        },
                        engine: {
                            bsonType: "string",
                            description: "引擎标识 (cpp_v3.0.0)"
                        },
                        host: {
                            bsonType: "string",
                            description: "主机名"
                        },
                        graph_size: {
                            bsonType: "string",
                            description: "数据规模 (10K/50K/100K)"
                        },
                        data_file: {
                            bsonType: "string",
                            description: "图数据文件名"
                        }
                    }
                },
                timestamp: {
                    bsonType: "date",
                    description: "采样时间戳 (UTC)"
                }
            }
        }
    },
    validationLevel: "moderate",
    timeseries: {
        timeField: "timestamp",
        metaField: "metric",
        granularity: "seconds",
        bucketMaxSpanSeconds: 3600,
        bucketRoundingSeconds: 3600
    }
});

// 索引 (时序集合自动管理 _id 和 timestamp)
// 1. 指标维度 — 监控面板: "PageRank 最近 1 小时 P95 延迟趋势"
db.performance_metrics.createIndex(
    { metric: 1, timestamp: -1 },
    { name: "idx_metric_ts" }
);

// 2. 带标签的精确查询 — "某算法在某数据规模下的性能"
db.performance_metrics.createIndex(
    { metric: 1, "tags.algorithm": 1, timestamp: -1 },
    { name: "idx_metric_algo_ts" }
);

// 3. TTL — 7 天 (原始数据)
db.performance_metrics.createIndex(
    { timestamp: 1 },
    { expireAfterSeconds: 604800, name: "idx_ttl_7d" }
);


// ════════════════════════════════════════════════════════════════════════════
// 集合 3.5: performance_metrics_hourly — 性能指标小时下采样
// ════════════════════════════════════════════════════════════════════════════
// 下采样 pipeline 见第 2 部分。
// ============================================================================

db.createCollection("performance_metrics_hourly", {
    validator: {
        $jsonSchema: {
            bsonType: "object",
            required: ["metric", "hour", "p50", "p95", "p99", "count"],
            properties: {
                metric: {
                    bsonType: "string",
                    description: "指标名"
                },
                tags: {
                    bsonType: "object",
                    description: "聚合后的标签维度"
                },
                hour: {
                    bsonType: "date",
                    description: "小时整点时间"
                },
                min: { bsonType: "double" },
                max: { bsonType: "double" },
                avg: { bsonType: "double" },
                p50: { bsonType: "double" },
                p95: { bsonType: "double" },
                p99: { bsonType: "double" },
                stddev: { bsonType: "double" },
                count: { bsonType: "int" },
                created_at: {
                    bsonType: "date",
                    description: "聚合生成时间"
                }
            }
        }
    },
    validationLevel: "moderate"
});

db.performance_metrics_hourly.createIndex(
    { metric: 1, hour: -1 },
    { name: "idx_metric_hour" }
);
db.performance_metrics_hourly.createIndex(
    { created_at: 1 },
    { expireAfterSeconds: 7776000, name: "idx_ttl_90d" }
);


// ════════════════════════════════════════════════════════════════════════════
// 集合 4: cache_registry — 缓存注册表 (NEW)
// ════════════════════════════════════════════════════════════════════════════
// 用途: 从 MongoDB 一侧追踪 Redis 缓存内容，实现缓存感知查询。
//
// 为什么需要:
//   1. Redis 只是 key-value，MongoDB 没有缓存索引的可见性
//   2. 在 MongoDB 中记录缓存条目 → 仪表板可以计算缓存命中率/覆盖率
//   3. 支持缓存预热: 查询最近频繁访问的算法，主动预热
//   4. 支持缓存失效: 图数据更新时，批量标记相关缓存为过期
//
// 工作流:
//   1. API 调用算法 → 先查 Redis → 命中: 记录 cache_hit=true 到 operation_logs
//   2. 未命中 → C++ 计算 → 结果写入 Redis → 同时 register_cache_entry() 写入此集合
//   3. 图数据更新 → scan cache_registry → 标记所有条目为 stale
// ============================================================================

db.createCollection("cache_registry", {
    validator: {
        $jsonSchema: {
            bsonType: "object",
            required: ["cache_key", "algorithm", "created_at", "ttl_seconds"],
            additionalProperties: false,
            properties: {
                cache_key: {
                    bsonType: "string",
                    description: "Redis 缓存键 (如 algo:pagerank:params_hash:abc123)"
                },
                algorithm: {
                    bsonType: "string",
                    description: "算法类型"
                },
                parameters_hash: {
                    bsonType: "string",
                    description: "算法参数的 SHA256 前 16 字符"
                },
                graph_data_hash: {
                    bsonType: "string",
                    description: "图数据文件的 MD5，用于检测数据变更时批量失效"
                },
                result_size_bytes: {
                    bsonType: "int",
                    description: "缓存结果的大小 (字节)"
                },
                ttl_seconds: {
                    bsonType: "int",
                    minimum: 0,
                    description: "Redis 中的 TTL (秒)"
                },
                access_count: {
                    bsonType: "int",
                    minimum: 0,
                    default: 0,
                    description: "累计访问次数 (每次命中 +1)"
                },
                last_accessed_at: {
                    bsonType: ["date", "null"],
                    description: "最近一次缓存命中时间"
                },
                status: {
                    bsonType: "string",
                    enum: ["active", "expired", "stale", "evicted"],
                    description: "缓存状态"
                },
                created_at: {
                    bsonType: "date",
                    description: "缓存创建时间"
                },
                expires_at: {
                    bsonType: "date",
                    description: "缓存过期时间 (created_at + ttl_seconds)"
                }
            }
        }
    },
    validationLevel: "moderate"
});

// 索引: cache_registry
db.cache_registry.createIndex(
    { cache_key: 1 },
    { unique: true, name: "idx_cache_key_unique" }
);
db.cache_registry.createIndex(
    { algorithm: 1, status: 1, created_at: -1 },
    { name: "idx_algo_status_time" }
);
db.cache_registry.createIndex(
    { graph_data_hash: 1 },
    { name: "idx_data_hash" }
);
db.cache_registry.createIndex(
    { created_at: 1 },
    { expireAfterSeconds: 2592000, name: "idx_ttl_30d" }
);
db.cache_registry.createIndex(
    { status: 1, expires_at: 1 },
    { partialFilterExpression: { status: "active" }, name: "idx_active_expires_partial" }
);


// ════════════════════════════════════════════════════════════════════════════
// 集合 5: graph_snapshots — 图状态快照 (NEW)
// ════════════════════════════════════════════════════════════════════════════
// 用途: 定期记录整个图的状态，追踪图演化。
//
// 触发时机:
//   - 图数据文件变更时 (通过 data_file_hash 检测)
//   - 定期 (每天凌晨) 即使数据未变也记录一次 → 建立时间基线
//
// 价值:
//   1. 图增长趋势可视化 (节点数/边数随时间)
//   2. 分析结果随时间变化的归因 (是算法参数变了还是图结构变了?)
//   3. 异常检测: 突发的边数增加可能代表数据导入错误
// ============================================================================

db.createCollection("graph_snapshots", {
    validator: {
        $jsonSchema: {
            bsonType: "object",
            required: ["timestamp", "node_count", "edge_count"],
            additionalProperties: false,
            properties: {
                timestamp: {
                    bsonType: "date",
                    description: "快照时间"
                },
                node_count: {
                    bsonType: "int",
                    minimum: 0,
                    description: "图中节点总数"
                },
                edge_count: {
                    bsonType: "int",
                    minimum: 0,
                    description: "图中边总数"
                },
                density: {
                    bsonType: "double",
                    description: "图密度 = 2*E / (N*(N-1))"
                },
                component_count: {
                    bsonType: "int",
                    description: "连通分量数量"
                },
                largest_component_size: {
                    bsonType: "int",
                    description: "最大连通分量包含的节点数"
                },
                isolated_nodes: {
                    bsonType: "int",
                    description: "孤立节点 (度=0) 数量"
                },
                avg_degree: {
                    bsonType: "double",
                    description: "平均度 = 2*E/N"
                },
                max_degree: {
                    bsonType: "int",
                    description: "最大出/入度"
                },
                diameter: {
                    bsonType: ["int", "null"],
                    description: "图直径 (仅小图计算)"
                },
                clustering_coefficient: {
                    bsonType: ["double", "null"],
                    description: "全局聚类系数"
                },
                data_file_hash: {
                    bsonType: "string",
                    description: "图数据文件 MD5"
                },
                data_file_path: {
                    bsonType: "string",
                    description: "图数据文件路径"
                },
                file_size_bytes: {
                    bsonType: ["long", "null"],
                    description: "数据文件大小"
                },
                import_source: {
                    bsonType: "string",
                    enum: ["file", "neo4j", "api_upload", "manual"],
                    description: "数据来源"
                },
                engine_version: {
                    bsonType: "string",
                    description: "计算统计时使用的引擎版本"
                }
            }
        }
    },
    validationLevel: "moderate"
});

// 索引: graph_snapshots
db.graph_snapshots.createIndex(
    { timestamp: -1 },
    { name: "idx_timestamp_desc" }
);
// 覆盖索引: 仪表板趋势图只需要时间+节点+边+密度
db.graph_snapshots.createIndex(
    { timestamp: -1, node_count: 1, edge_count: 1, density: 1 },
    { name: "idx_snapshot_trend_covering" }
);
db.graph_snapshots.createIndex(
    { data_file_hash: 1, timestamp: -1 },
    { name: "idx_filehash_time" }
);


// ============================================================================
// 第 2 部分: 聚合管道模式 (8 个生产级管道)
// ============================================================================
// 格式说明:
//   每个管道标注:
//     - 使用的索引 (INDEX)
//     - 预期扫描文档数 (SCAN)
//     - 预计执行时间 (TIME)
//     - 预期输出格式 (OUTPUT)
// ============================================================================

// ════════════════════════════════════════════════════════════════════════════
// 管道 1: 用户活跃度仪表板
// 描述: 每日粒度，统计活跃用户数、各用户运行的算法种类、平均耗时
// INDEX: 使用 idx_action_time (action:1, created_at:-1)
// SCAN:  24小时窗口 ~10000 docs
// TIME:  <200ms (warm cache)
// OUTPUT: [{user_id, total_ops, unique_algorithms, avg_duration_ms, last_active}]
// ════════════════════════════════════════════════════════════════════════════

// 1a. 用户活跃度仪表板 — 最近 7 天，Top 50 活跃用户
db.operation_logs.aggregate([
    // Stage 1: 时间范围过滤 — 使用 idx_action_time 索引
    { $match: {
        action: "run_algorithm",
        created_at: {
            $gte: new Date(new Date().getTime() - 7 * 86400000),
            $lt: new Date()
        }
    }},
    // Stage 2: 按用户分组，统计操作数和算法种类
    { $group: {
        _id: "$user_id",
        total_ops: { $sum: 1 },
        unique_algorithms: { $addToSet: "$resource" },
        total_duration: { $sum: "$duration_ms" },
        last_active: { $max: "$created_at" }
    }},
    // Stage 3: 计算平均值，展开算法列表
    { $project: {
        user_id: "$_id",
        total_ops: 1,
        algorithm_count: { $size: "$unique_algorithms" },
        algorithms: { $slice: ["$unique_algorithms", 10] },
        avg_duration_ms: { $round: [{ $divide: ["$total_duration", "$total_ops"] }, 2] },
        last_active: 1,
        _id: 0
    }},
    // Stage 4: 按活跃度降序
    { $sort: { total_ops: -1 } },
    // Stage 5: 限制输出
    { $limit: 50 }
]);

// 1b. 每日摘要 — 过去 24 小时，每小时操作量 + 去重用户 + 算法分布
db.operation_logs.aggregate([
    { $match: {
        created_at: { $gte: new Date(new Date().getTime() - 86400000) }
    }},
    { $group: {
        _id: {
            hour: { $dateToString: { format: "%Y-%m-%dT%H:00:00Z", date: "$created_at" } },
            action: "$action"
        },
        operation_count: { $sum: 1 },
        unique_users: { $addToSet: "$user_id" }
    }},
    { $group: {
        _id: "$_id.hour",
        total_ops: { $sum: "$operation_count" },
        user_set: { $addToSet: "$unique_users" },
        action_breakdown: {
            $push: {
                action: "$_id.action",
                count: "$operation_count"
            }
        }
    }},
    { $project: {
        _id: 0,
        hour: "$_id",
        total_ops: 1,
        unique_users: { $size: { $reduce: {
            input: "$user_set",
            initialValue: [],
            in: { $setUnion: ["$$value", "$$this"] }
        }}},
        action_breakdown: 1
    }},
    { $sort: { hour: 1 } }
]);


// ════════════════════════════════════════════════════════════════════════════
// 管道 2: 算法性能趋势 (P50/P95/P99 延迟)
// 描述: 按小时分组，计算各算法的分位数延迟趋势
// INDEX: 使用 idx_metric_ts (metric:1, timestamp:-1) 和 idx_metric_algo_ts
// SCAN:  24小时窗口 ~50000 docs per metric
// TIME:  <500ms (时序集合压缩 + 索引)
// OUTPUT: [{metric, hour, p50, p95, p99, avg, min, max, sample_count}]
// ════════════════════════════════════════════════════════════════════════════

db.performance_metrics.aggregate([
    // Stage 1: 时间 + 指标过滤
    { $match: {
        metric: { $in: ["pagerank.p95_ms", "community.p95_ms", "betweenness.p95_ms",
                        "api.latency.p50_ms", "api.latency.p95_ms"] },
        timestamp: { $gte: new Date(new Date().getTime() - 86400000) }
    }},
    // Stage 2: 按指标+小时分组，收集所有值用于分位数计算
    { $sort: { metric: 1, timestamp: 1 } },
    { $group: {
        _id: {
            metric: "$metric",
            hour: { $dateToString: { format: "%Y-%m-%dT%H:00:00Z", date: "$timestamp" } }
        },
        values: { $push: "$value" }
    }},
    // Stage 3: 计算分位数
    { $project: {
        _id: 0,
        metric: "$_id.metric",
        hour: "$_id.hour",
        sample_count: { $size: "$values" },
        avg: { $round: [{ $avg: "$values" }, 2] },
        min: { $round: [{ $min: "$values" }, 2] },
        max: { $round: [{ $max: "$values" }, 2] },
        p50: { $round: [
            { $arrayElemAt: ["$values", { $floor: { $multiply: [{ $size: "$values" }, 0.50] } }] },
            2
        ]},
        p95: { $round: [
            { $arrayElemAt: ["$values", { $floor: { $multiply: [{ $size: "$values" }, 0.95] } }] },
            2
        ]},
        p99: { $round: [
            { $arrayElemAt: ["$values", { $floor: { $multiply: [{ $size: "$values" }, 0.99] } }] },
            2
        ]}
    }},
    { $sort: { metric: 1, hour: 1 } }
]);


// ════════════════════════════════════════════════════════════════════════════
// 管道 3: 缓存命中率分析
// 描述: 从 operation_logs 中提取 cache_hit 标记，按小时计算命中率
// INDEX: 使用 idx_action_time (action:1, created_at:-1)
// SCAN:  24小时窗口 ~10000 "run_algorithm" docs
// TIME:  <100ms
// OUTPUT: [{hour, total, cache_hits, cache_misses, hit_rate_pct}]
// ════════════════════════════════════════════════════════════════════════════

db.operation_logs.aggregate([
    // Stage 1: 仅关注算法运行操作
    { $match: {
        action: "run_algorithm",
        created_at: { $gte: new Date(new Date().getTime() - 86400000) }
    }},
    // Stage 2: 按小时分组，计算缓存命中/未命中
    { $group: {
        _id: { $dateToString: { format: "%Y-%m-%dT%H:00:00Z", date: "$created_at" } },
        total: { $sum: 1 },
        cache_hits: {
            $sum: { $cond: [{ $eq: ["$details.cache_hit", true] }, 1, 0] }
        }
    }},
    // Stage 3: 计算命中率
    { $project: {
        _id: 0,
        hour: "$_id",
        total: 1,
        cache_hits: 1,
        cache_misses: { $subtract: ["$total", "$cache_hits"] },
        hit_rate_pct: { $round: [
            { $multiply: [{ $divide: ["$cache_hits", { $max: ["$total", 1] }] }, 100] },
            2
        ]}
    }},
    { $sort: { hour: 1 } }
]);

// 3b. 按算法粒度 — 哪些算法缓存收益最高
db.operation_logs.aggregate([
    { $match: {
        action: "run_algorithm",
        created_at: { $gte: new Date(new Date().getTime() - 7 * 86400000) }
    }},
    { $group: {
        _id: "$resource",
        total: { $sum: 1 },
        cache_hits: {
            $sum: { $cond: [{ $eq: ["$details.cache_hit", true] }, 1, 0] }
        },
        avg_duration_no_cache: {
            $avg: { $cond: [
                { $eq: ["$details.cache_hit", true] },
                null,
                "$duration_ms"
            ]}
        },
        avg_duration_cached: {
            $avg: { $cond: [
                { $eq: ["$details.cache_hit", true] },
                "$duration_ms",
                null
            ]}
        }
    }},
    { $project: {
        _id: 0,
        algorithm: "$_id",
        total: 1,
        cache_hits: 1,
        hit_rate_pct: { $round: [
            { $multiply: [{ $divide: ["$cache_hits", { $max: ["$total", 1] }] }, 100] },
            2
        ]},
        time_saved_ms: { $round: [
            { $subtract: [{ $ifNull: ["$avg_duration_no_cache", 0] }, { $ifNull: ["$avg_duration_cached", 0] }] },
            2
        ]}
    }},
    { $sort: { total: -1 } }
]);


// ════════════════════════════════════════════════════════════════════════════
// 管道 4: 错误率监控
// 描述: 按端点+小时分组，计算各端点的错误率
// INDEX: 使用 idx_status_time (status:1, created_at:-1) 或 idx_resource_time
// SCAN:  24小时窗口 ~10000-50000 docs (取决于 status 过滤)
// TIME:  <300ms
// OUTPUT: [{hour, endpoint, total, errors, error_rate_pct, top_error_codes}]
// ════════════════════════════════════════════════════════════════════════════

db.operation_logs.aggregate([
    // Stage 1: 时间范围
    { $match: {
        created_at: { $gte: new Date(new Date().getTime() - 86400000) }
    }},
    // Stage 2: 分组统计
    { $group: {
        _id: {
            hour: { $dateToString: { format: "%Y-%m-%dT%H:00:00Z", date: "$created_at" } },
            endpoint: "$endpoint",
            status: "$status"
        },
        count: { $sum: 1 },
        error_codes: { $addToSet: "$error_code" }
    }},
    // Stage 3: pivot status → total + error 两列
    { $group: {
        _id: { hour: "$_id.hour", endpoint: "$_id.endpoint" },
        total: { $sum: "$count" },
        errors: {
            $sum: {
                $cond: [{ $in: ["$_id.status", ["failure", "timeout"]] }, "$count", 0]
            }
        },
        all_error_codes: { $push: "$error_codes" }
    }},
    // Stage 4: 计算比率
    { $project: {
        _id: 0,
        hour: "$_id.hour",
        endpoint: "$_id.endpoint",
        total: 1,
        errors: 1,
        error_rate_pct: { $round: [
            { $multiply: [{ $divide: ["$errors", { $max: ["$total", 1] }] }, 100] },
            2
        ]},
        error_codes: { $reduce: {
            input: "$all_error_codes",
            initialValue: [],
            in: { $setUnion: ["$$value", "$$this"] }
        }}
    }},
    { $sort: { hour: 1, error_rate_pct: -1 } }
]);


// ════════════════════════════════════════════════════════════════════════════
// 管道 5: 用户参与漏斗
// 描述: 各阶段的用户数转化 — 活跃 → 运行算法 → 保存分析 → 导出数据
// INDEX: 使用 idx_action_time (action:1, created_at:-1)
// SCAN:  7天窗口 ~70000 docs
// TIME:  <500ms
// OUTPUT: {stage_1_active, stage_2_ran, stage_3_saved, stage_4_exported, conversion_rates}
// ════════════════════════════════════════════════════════════════════════════

db.operation_logs.aggregate([
    { $match: {
        created_at: { $gte: new Date(new Date().getTime() - 7 * 86400000) }
    }},
    { $group: {
        _id: null,
        active_users: { $addToSet: "$user_id" },
        ran_algorithm: {
            $addToSet: {
                $cond: [{ $eq: ["$action", "run_algorithm"] }, "$user_id", "$$REMOVE"]
            }
        },
        saved_analysis: {
            $addToSet: {
                $cond: [{ $eq: ["$action", "save_analysis"] }, "$user_id", "$$REMOVE"]
            }
        },
        exported_data: {
            $addToSet: {
                $cond: [{ $eq: ["$action", "export_data"] }, "$user_id", "$$REMOVE"]
            }
        },
        viewed_dashboard: {
            $addToSet: {
                $cond: [{ $eq: ["$action", "view_dashboard"] }, "$user_id", "$$REMOVE"]
            }
        }
    }},
    { $project: {
        _id: 0,
        stage_1_active: { $size: "$active_users" },
        stage_2_ran_algorithm: { $size: "$ran_algorithm" },
        stage_3_saved_analysis: { $size: "$saved_analysis" },
        stage_4_exported_data: { $size: "$exported_data" },
        stage_1b_dashboard: { $size: "$viewed_dashboard" },
        conversion: {
            ran_to_saved: { $round: [{ $multiply: [
                { $divide: [{ $size: "$saved_analysis" }, { $max: [{ $size: "$ran_algorithm" }, 1] }] },
                100
            ]}, 2] },
            ran_to_exported: { $round: [{ $multiply: [
                { $divide: [{ $size: "$exported_data" }, { $max: [{ $size: "$ran_algorithm" }, 1] }] },
                100
            ]}, 2] }
        }
    }}
]);


// ════════════════════════════════════════════════════════════════════════════
// 管道 6: 存储增长预测
// 描述: 分析每日文档量 + 平均文档大小，预测未来 30/90 天存储需求
// INDEX: 使用 idx_ttl_30d / idx_ttl_90d (created_at:1)
// SCAN:  全量 (但 TTL 限制了范围)
// TIME:  <1s (取决于数据量)
// OUTPUT: {daily_avg_docs, daily_avg_size_mb, projected_30d_mb, projected_90d_mb}
// ════════════════════════════════════════════════════════════════════════════

// 6a. operation_logs 每日文档量趋势 (用于预测)
db.operation_logs.aggregate([
    { $match: {
        created_at: { $gte: new Date(new Date().getTime() - 30 * 86400000) }
    }},
    { $group: {
        _id: { $dateToString: { format: "%Y-%m-%d", date: "$created_at" } },
        doc_count: { $sum: 1 },
        total_bytes: { $sum: { $bsonSize: "$$ROOT" } }
    }},
    { $sort: { _id: 1 } },
    { $group: {
        _id: null,
        days: { $sum: 1 },
        total_docs: { $sum: "$doc_count" },
        total_bytes: { $sum: "$total_bytes" },
        daily_docs: { $push: "$doc_count" }
    }},
    { $project: {
        _id: 0,
        days: 1,
        avg_daily_docs: { $round: [{ $divide: ["$total_docs", "$days"] }, 0] },
        avg_daily_size_mb: { $round: [{ $divide: ["$total_bytes", { $multiply: ["$days", 1048576] }] }, 2] },
        projected_30d_docs: { $round: [{ $multiply: [{ $divide: ["$total_docs", "$days"] }, 30] }, 0] },
        projected_30d_mb: { $round: [{ $multiply: [{ $divide: ["$total_bytes", "$days"] }, 30] }, 2] },
        projected_90d_mb: { $round: [{ $multiply: [{ $divide: ["$total_bytes", "$days"] }, 90] }, 2] },
        trend: { $slice: ["$daily_docs", 30] }
    }}
]);

// 6b. TTL 清理速率 — 每天被 TTL 删除的文档数估算
// (通过统计 created_at < 30天前 但仍在集合中的文档 → 应该为 0)
db.operation_logs.aggregate([
    { $match: {
        created_at: { $lt: new Date(new Date().getTime() - 30 * 86400000) }
    }},
    { $count: "expired_but_not_cleaned" }
]);

// 6c. 集合存储统计 ($collStats — MongoDB 4.4+)
// 注意: 这个管道在驱动层执行，不是 aggregate()
// db.runCommand({ collStats: "operation_logs", scale: 1024*1024 })
// 输出: { size: MB, count: docs, avgObjSize: bytes, totalIndexSize: MB }


// ════════════════════════════════════════════════════════════════════════════
// 管道 7: 异常检测 — 执行时间 > 2 倍历史平均的算法
// 描述: 找出执行时间异常偏高的算法运行实例
// INDEX: idx_algorithm_time (algorithm:1, created_at:-1) + idx_slow_queries_partial
// SCAN:  24小时窗口 ~1000 docs per algorithm
// TIME:  <1s
// OUTPUT: [{algorithm, normal_avg_ms, anomaly_threshold_ms, anomalies: [...]}]
// ════════════════════════════════════════════════════════════════════════════

db.analysis_snapshots.aggregate([
    // Stage 1: 最近 24 小时
    { $match: {
        created_at: { $gte: new Date(new Date().getTime() - 86400000) }
    }},
    // Stage 2: 按算法计算基线统计
    { $group: {
        _id: "$algorithm",
        avg_time: { $avg: "$execution_time_ms" },
        stddev: { $stdDevPop: "$execution_time_ms" },
        count: { $sum: 1 },
        snapshots: { $push: {
            snapshot_id: "$snapshot_id",
            user_id: "$user_id",
            execution_time_ms: "$execution_time_ms",
            created_at: "$created_at",
            parameters: "$parameters"
        }}
    }},
    // Stage 3: 标记异常 (>2倍平均 且 >2个标准差)
    { $project: {
        _id: 0,
        algorithm: "$_id",
        normal_avg_ms: { $round: ["$avg_time", 2] },
        stddev_ms: { $round: ["$stddev", 2] },
        total_runs: "$count",
        anomaly_threshold_ms: {
            $round: [{ $max: [{ $multiply: ["$avg_time", 2] }, { $add: ["$avg_time", { $multiply: ["$stddev", 2] }] }] }, 2]
        },
        anomalies: {
            $filter: {
                input: "$snapshots",
                as: "snap",
                cond: {
                    $gt: ["$$snap.execution_time_ms",
                          { $max: [{ $multiply: ["$avg_time", 2] }, { $add: ["$avg_time", { $multiply: ["$stddev", 2] }] }] }
                    ]
                }
            }
        }
    }},
    // Stage 4: 只保留有异常的算法
    { $match: {
        $expr: { $gt: [{ $size: "$anomalies" }, 0] }
    }},
    // Stage 5: 裁剪输出
    { $project: {
        algorithm: 1,
        normal_avg_ms: 1,
        anomaly_threshold_ms: 1,
        anomaly_count: { $size: "$anomalies" },
        anomaly_rate_pct: { $round: [
            { $multiply: [{ $divide: [{ $size: "$anomalies" }, "$total_runs"] }, 100] },
            2
        ]},
        latest_anomalies: { $slice: ["$anomalies", 10] }
    }},
    { $sort: { anomaly_count: -1 } }
]);


// ════════════════════════════════════════════════════════════════════════════
// 管道 8: 跨集合关联 — $lookup analysis_snapshots ↔ operation_logs
// 描述: 为快照找到对应的操作日志，实现完整的请求追踪
// INDEX: analysis_snapshots 使用 idx_algorithm_time
//         operation_logs 使用 idx_user_ops (user_id:1, created_at:-1)
// SCAN:  快照集合 100 docs + 日志集合每次 lookup 扫描 ~10 docs
// TIME:  <500ms (小批量 limit 100)
// OUTPUT: [{snapshot_id, user_id, algorithm, operation_log, total_related_ops}]
// ════════════════════════════════════════════════════════════════════════════

db.analysis_snapshots.aggregate([
    // Stage 1: 限制范围 (避免全表 $lookup)
    { $match: {
        created_at: { $gte: new Date(new Date().getTime() - 86400000) }
    }},
    { $sort: { created_at: -1 } },
    { $limit: 200 },
    // Stage 2: 关联操作日志 (通过 user_id + algorithm + 时间窗口)
    { $lookup: {
        from: "operation_logs",
        let: {
            snap_user: "$user_id",
            snap_algo: "$algorithm",
            snap_time: "$created_at",
            snap_request: "$request_id"
        },
        pipeline: [
            { $match: {
                $expr: { $and: [
                    { $eq: ["$user_id", "$$snap_user"] },
                    { $eq: ["$resource", "$$snap_algo"] },
                    // 时间窗口 ±30 秒 (算法执行 + 网络往返)
                    { $gte: ["$created_at", { $subtract: ["$$snap_time", 30000] }] },
                    { $lte: ["$created_at", { $add: ["$$snap_time", 30000] }] }
                ]}
            }},
            { $limit: 5 }
        ],
        as: "related_operations"
    }},
    // Stage 3: 计算关联度评分 (request_id 完全匹配 = 强关联)
    { $addFields: {
        exact_match: {
            $filter: {
                input: "$related_operations",
                as: "op",
                cond: { $eq: ["$$op.request_id", "$request_id"] }
            }
        },
        total_related: { $size: "$related_operations" }
    }},
    // Stage 4: 选择最佳匹配
    { $addFields: {
        best_match: { $cond: [
            { $gt: [{ $size: "$exact_match" }, 0] },
            { $arrayElemAt: ["$exact_match", 0] },
            { $arrayElemAt: ["$related_operations", 0] }
        ]}
    }},
    // Stage 5: 投影输出
    { $project: {
        _id: 0,
        snapshot_id: 1,
        request_id: 1,
        user_id: 1,
        algorithm: 1,
        execution_time_ms: 1,
        cache_hit: 1,
        created_at: 1,
        source: { $literal: "analysis_snapshots" },
        matched_operation: {
            action: "$best_match.action",
            duration_ms: "$best_match.duration_ms",
            status: "$best_match.status",
            ip_address: "$best_match.ip_address",
            correlation_id: "$best_match.correlation_id"
        },
        match_confidence: {
            $switch: {
                branches: [
                    { case: { $gt: [{ $size: "$exact_match" }, 0] }, then: "exact_request_id" },
                    { case: { $eq: ["$total_related", 1] }, then: "single_candidate" }
                ],
                default: "multiple_candidates"
            }
        },
        total_related_ops: "$total_related"
    }},
    { $sort: { created_at: -1 } }
]);


// ============================================================================
// 第 3 部分: 完整索引策略 (ESR 规则 + 部分索引 + 文本索引 + 通配符)
// ============================================================================

// --- ESR 规则说明 ---
// ESR = Equality → Sort → Range
// 复合索引字段顺序必须匹配查询模式:
//   1. Equality 字段 (精确匹配: user_id, algorithm, status) — 最前
//   2. Sort 字段 (排序: created_at, execution_time_ms) — 中间
//   3. Range 字段 (范围查询: timestamp gte/lte) — 最后
//
// 示例:
//   Query: db.ops.find({user_id: "u1"}).sort({created_at: -1})
//   ESR:  E=user_id, S=created_at → { user_id: 1, created_at: -1 }
//
//   Query: db.ops.find({user_id: "u1", created_at: {$gte: T}}).sort({created_at: -1})
//   ESR:  E=user_id, R=created_at(gte), S=created_at(desc) — Range 和 Sort 是同一字段
//         → { user_id: 1, created_at: -1 }  (created_at 同时覆盖 Range 和 Sort)
//
//   Query: db.ops.find({algorithm: "pagerank", execution_time_ms: {$gt: 1000}})
//          .sort({created_at: -1})
//   ESR:  E=algorithm, R=execution_time_ms, S=created_at
//         → { algorithm: 1, execution_time_ms: 1, created_at: -1 }
//         但: execution_time_ms 是范围查询，created_at 是排序，不能同时优化
//         优化: { algorithm: 1, created_at: -1 } + 内存中过滤 execution_time_ms

// ════════════════════════════════════════════════════════════════════════════
// 索引总览表
// ════════════════════════════════════════════════════════════════════════════
// | # | 集合                      | 索引定义                                      | 类型        | 大小估计 |
// |----|---------------------------|----------------------------------------------|-------------|---------|
// | 1  | analysis_snapshots        | { snapshot_id: 1 }                            | 唯一         | ~8 MB   |
// | 2  | analysis_snapshots        | { user_id: 1, created_at: -1 }                | 复合 ESR    | ~20 MB  |
// | 3  | analysis_snapshots        | { algorithm: 1, created_at: -1 }              | 复合 ESR    | ~15 MB  |
// | 4  | analysis_snapshots        | { user_id: 1, algorithm: 1, created_at: -1 }  | 复合 ESR    | ~25 MB  |
// | 5  | analysis_snapshots        | { algorithm: 1, execution_time_ms: -1 }       | 复合 ESR    | ~12 MB  |
// | 6  | analysis_snapshots        | { created_at: 1 }                             | TTL         | ~8 MB   |
// | 7  | analysis_snapshots        | { algorithm:1, execution_time_ms:-1, ... }    | 部分        | ~1 MB   |
// | 8  | analysis_snapshots        | { algorithm: "text", parameters.description: "text" } | 文本   | ~3 MB   |
// | 9  | analysis_snapshots        | { result_metadata.$**: 1 }                    | 通配符       | ~5 MB   |
// | 10 | analysis_snapshots        | { request_id: 1 }                             | 普通         | ~6 MB   |
// | 11 | operation_logs            | { user_id: 1, created_at: -1 }                | 复合 ESR    | ~30 MB  |
// | 12 | operation_logs            | { action: 1, created_at: -1 }                 | 复合 ESR    | ~20 MB  |
// | 13 | operation_logs            | { status: 1, created_at: -1 }                 | 复合 ESR    | ~15 MB  |
// | 14 | operation_logs            | { resource: 1, created_at: -1 }               | 复合 ESR    | ~20 MB  |
// | 15 | operation_logs            | { action: 1, status: 1, created_at: -1 }      | 复合 ESR    | ~25 MB  |
// | 16 | operation_logs            | { created_at: 1 }                             | TTL         | ~12 MB  |
// | 17 | operation_logs            | { request_id: 1 }                             | 普通         | ~20 MB  |
// | 18 | operation_logs            | { correlation_id: 1 }                         | 普通         | ~15 MB  |
// | 19 | operation_logs            | { created_at: -1 } where status in [...]      | 部分         | ~1 MB   |
// | 20 | operation_logs            | { session_id: 1, created_at: -1 }             | 复合 ESR    | ~20 MB  |
// | 21 | operation_stats_hourly    | { hour: -1 }                                  | 唯一         | <1 MB   |
// | 22 | operation_stats_hourly    | { created_at: 1 }                             | TTL         | <1 MB   |
// | 23 | performance_metrics       | { metric: 1, timestamp: -1 }                  | 复合 ESR    | ~5 MB   |
// | 24 | performance_metrics       | { metric: 1, tags.algorithm: 1, timestamp:-1 }| 复合 ESR    | ~8 MB   |
// | 25 | performance_metrics       | { timestamp: 1 }                              | TTL         | ~3 MB   |
// | 26 | performance_metrics_hourly| { metric: 1, hour: -1 }                       | 复合 ESR    | <2 MB   |
// | 27 | performance_metrics_hourly| { created_at: 1 }                             | TTL         | <1 MB   |
// | 28 | cache_registry            | { cache_key: 1 }                              | 唯一         | <5 MB   |
// | 29 | cache_registry            | { algorithm: 1, status: 1, created_at: -1 }    | 复合 ESR    | <5 MB   |
// | 30 | cache_registry            | { graph_data_hash: 1 }                        | 普通         | <3 MB   |
// | 31 | cache_registry            | { created_at: 1 }                             | TTL         | <3 MB   |
// | 32 | cache_registry            | { status: 1, expires_at: 1 } where active    | 部分         | <1 MB   |
// | 33 | graph_snapshots           | { timestamp: -1 }                             | 普通         | <2 MB   |
// | 34 | graph_snapshots           | { timestamp:-1, node_count:1, edge_count:1 }  | 覆盖         | <2 MB   |
// | 35 | graph_snapshots           | { data_file_hash: 1, timestamp: -1 }           | 复合 ESR    | <2 MB   |
// ════════════════════════════════════════════════════════════════════════════

// --- 部分索引 (Partial Index) 策略总结 ---
//
// 1. idx_slow_queries_partial (analysis_snapshots):
//    WHERE execution_time_ms > 1000
//    场景: 仅 <5% 的查询是慢查询，索引减少 ~95% 存储
//    EXPLAIN 对比:
//      无索引: COLLSCAN, 扫描 100K docs → 500ms
//      普通索引: IXSCAN + FETCH, 扫描 5K docs → 50ms
//      部分索引: IXSCAN (仅索引慢查询), 扫描 5K docs → 30ms (索引更紧凑)
//
// 2. idx_failures_recent_partial (operation_logs):
//    WHERE status IN ["failure", "timeout", "rate_limited"]
//    场景: 大多数查询只看失败，失败记录 <2%
//    EXPLAIN 对比:
//      无索引: COLLSCAN 300K docs → 800ms
//      普通索引: IXSCAN + FETCH 300K → 100ms (仍需扫描所有 created_at)
//      部分索引: IXSCAN 6K docs → 15ms (仅索引失败记录)
//
// 3. idx_active_expires_partial (cache_registry):
//    WHERE status = "active"
//    场景: 活跃缓存 <20%，定期清理过期缓存时精准定位

// --- 文本索引 (Text Index) 使用示例 ---
//
// 搜索用户备注: "分析关键节点的影响力"
db.analysis_snapshots.find(
    { $text: { $search: "关键节点 影响力" } },
    { score: { $meta: "textScore" } }
).sort({ score: { $meta: "textScore" } }).limit(20);

// 仅搜索算法名:
db.analysis_snapshots.find(
    { $text: { $search: "pagerank" } }
).limit(20);


// ============================================================================
// 第 4 部分: 分片策略评估
// ============================================================================

// --- 当前规模 ---
// 年度数据量: ~22M 文档, ~1.3GB (含索引 ~2.5GB)
// 3 年数据量 (TTL 限制): ~750MB (快照 90d + 日志 30d + 指标 180d)
// 写吞吐: 峰值 ~1000 ops/s (60K docs/day ≈ 0.7 docs/s 平均, 峰值 ~50x)
// 读吞吐: 仪表板刷新 ~5 QPS, 用户查询 ~20 QPS

// --- 分片必要性判断 ---
// 阈值:
//   - 文档数 > 100M → 当前 ~22M/year, TTL 内 ~2M (不需要)
//   - 数据量 > 100GB → 当前 ~1.3GB/year (不需要)
//   - 写吞吐 > 10K ops/sec → 当前峰值 ~1K (不需要)
//   - 读延迟 > 100ms P95 → 当前 ~15ms (不需要)
//
// 结论: **当前不需要分片**。建议采用预分片策略 (pre-split) 为未来扩展做准备。
//
// 3 年后评估 (假设 10x 增长):
//   文档数: ~220M/year, TTL 内 ~20M (接近阈值)
//   写吞吐: ~10K ops/s (达到阈值)
//   此时需要为 operation_logs + performance_metrics 启用分片

// --- 分片键候选分析表 ---
//
// | 集合                  | 候选键                           | 基数     | 查询隔离 | 写分布  | 判定      |
// |-----------------------|---------------------------------|---------|---------|--------|----------|
// | analysis_snapshots    | { user_id: 1, created_at: 1 }    | 高       | 好      | 好     | 推荐     |
// | analysis_snapshots    | { algorithm: 1, created_at: 1 }  | 低       | 差      | 差     | 不推荐   |
// | operation_logs        | { user_id: "hashed" }            | 高       | 一般    | 极好   | 推荐     |
// | operation_logs        | { created_at: 1 }                | 中       | 好      | 差     | 不推荐   |
// | performance_metrics   | { metric: 1, timestamp: 1 }      | 中       | 好      | 一般   | 可接受   |
// | performance_metrics   | { metric: "hashed" }             | 低       | 差      | 好     | 不推荐   |
// | cache_registry        | { cache_key: "hashed" }          | 高       | 好      | 极好   | 推荐     |
// | graph_snapshots       | { timestamp: 1 }                 | 高       | 好      | 一般   | 可接受   |
//
// 判定说明:
//   - analysis_snapshots: user_id 基数高 (用户数增长)，大部分查询按用户过滤 → 查询隔离好
//   - operation_logs: hashed user_id 确保写入均匀分布到所有分片，查询场景多为聚合(跨分片收集)
//   - performance_metrics: 时序集合，MongoDB 5.0+ 支持按 metaField 分片
//   - 不推荐单调递增键 (ObjectId/timestamp) 作为分片键 → 会导致热分片

// --- 预分片准备 (在不需要分片的现阶段就可以做) ---
//
// 1. 所有集合预先定义分片键字段 (已纳入 Schema 设计):
//    - analysis_snapshots.user_id 已包含在索引中
//    - operation_logs.user_id 已包含在索引中
//    - cache_registry.cache_key 已包含在索引中
//
// 2. 在首次部署时即启用分片 (即使只有 1 个分片):
//    sh.enableSharding("socialgraph_analytics")
//    // 预分片 — 创建分片但不拆分 (等需要时再 addShard)
//    sh.shardCollection("socialgraph_analytics.operation_logs", { user_id: "hashed" })
//
// 3. 分片键选择为 hashed 时注意事项:
//    - hashed 索引不支持范围查询 (user_id range 不再可用)
//    - 但 $eq 查询完全正常 (大多数查询)
//    - 聚合管道不受影响 (MongoDB 会 scatter-gather)

// --- 分片迁移计划 (当需要时) ---
//
// Phase 1: 启用 Config Server Replica Set (3 节点)
// Phase 2: 添加 2 个 Shard Server (每个 Replica Set 3 节点)
// Phase 3: 为 operation_logs 启用分片 (最大集合, 先迁移)
//   sh.shardCollection("socialgraph_analytics.operation_logs", { user_id: "hashed" })
// Phase 4: 为 performance_metrics 启用分片 (时序)
//   sh.shardCollection("socialgraph_analytics.performance_metrics", { metric: 1, timestamp: 1 })
// Phase 5: 为 analysis_snapshots 启用分片
//   sh.shardCollection("socialgraph_analytics.analysis_snapshots", { user_id: 1, created_at: 1 })
//
// 每个 Phase 期间设置 balancer 窗口 (凌晨 2-5 点):
//   db.adminCommand({ configureCollectionBalancing: "socialgraph_analytics.operation_logs",
//                      balancerWindow: "02:00-05:00" })


// ============================================================================
// 第 5 部分: 备份与恢复程序
// ============================================================================

// --- 备份策略 ---
//
// | 方法               | 频率     | 保留    | 说明                                      |
// |--------------------|---------|--------|-------------------------------------------|
// | mongodump (逻辑)   | 每日     | 30 天   | 完整数据库导出，可跨版本恢复                  |
// | 文件系统快照        | 每日     | 7 天    | 需要 LVM / 云磁盘快照，秒级完成              |
// | 本地增量 (oplog)   | 每小时   | 48 小时 | oplog 归档，用于 PITR                       |
// | Atlas Cloud Backup | 持续     | 按配置  | 如果用 MongoDB Atlas (托管)，自动备份        |
//
// 推荐组合: mongodump 每日全量 + oplog 每小时增量
//   - 每日 03:00 UTC: mongodump --gzip --archive → S3/本地存储
//   - 每小时: mongodump --oplog → 归档最近 1 小时 oplog
//   - 备份文件命名: socialgraph_analytics_YYYYMMDD_HHMMSS.archive.gz
//   - 异地存储: 同步到 S3/MinIO 或异地 rsync

// --- 备份脚本: backup_mongo.sh ---
/*
#!/bin/bash
# ═══════════════════════════════════════════════════════════════════════════
# backup_mongo.sh — SocialGraph Pro MongoDB 完整备份
# 用法: ./backup_mongo.sh [full|oplog]
# Cron: 0 3 * * * /opt/scripts/backup_mongo.sh full >> /var/log/mongo_backup.log
#       0 * * * * /opt/scripts/backup_mongo.sh oplog >> /var/log/mongo_backup.log
# ═══════════════════════════════════════════════════════════════════════════
set -euo pipefail

MONGO_URI="${MONGO_URI:-mongodb://admin:mongopass@localhost:27017}"
BACKUP_DIR="${BACKUP_DIR:-/data/backups/mongodb}"
RETENTION_DAYS_FULL="${RETENTION_DAYS_FULL:-30}"
RETENTION_HOURS_OPLOG="${RETENTION_HOURS_OPLOG:-48}"
TIMESTAMP=$(date -u +"%Y%m%d_%H%M%S")
LOG_FILE="${BACKUP_DIR}/backup_${TIMESTAMP}.log"

log() { echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] $*" | tee -a "$LOG_FILE"; }

mkdir -p "$BACKUP_DIR"

# ── 全量备份 ──────────────────────────────────────────────────────────────
full_backup() {
    local OUTPUT="${BACKUP_DIR}/full_${TIMESTAMP}.archive.gz"
    log "开始全量备份 → $OUTPUT"

    START=$(date +%s)
    mongodump --uri="$MONGO_URI" \
        --db=socialgraph_analytics \
        --gzip \
        --archive="$OUTPUT" \
        --readPreference=secondaryPreferred \
        2>&1 | tee -a "$LOG_FILE"

    DURATION=$(( $(date +%s) - START ))
    SIZE=$(du -h "$OUTPUT" | cut -f1)

    log "全量备份完成: 大小=$SIZE 耗时=${DURATION}s"
    log "验证归档完整性..."
    mongorestore --uri="$MONGO_URI" --gzip --archive="$OUTPUT" --dryRun --quiet \
        && log "验证通过" || log "验证失败!"

    # 清理超过保留期的备份
    find "$BACKUP_DIR" -name "full_*.archive.gz" -mtime +$RETENTION_DAYS_FULL -delete
    log "已清理 ${RETENTION_DAYS_FULL} 天前的全量备份"
}

# ── 增量备份 (oplog) ──────────────────────────────────────────────────────
oplog_backup() {
    local OUTPUT="${BACKUP_DIR}/oplog_${TIMESTAMP}.bson.gz"
    log "开始 oplog 增量备份 → $OUTPUT"

    # 获取最近 1 小时的 oplog
    local SINCE=$(date -u -d '1 hour ago' +%s)
    mongodump --uri="$MONGO_URI" \
        --db=local \
        --collection=oplog.rs \
        --query="{\"ts\": {\"\$gte\": Timestamp($SINCE, 0)}}" \
        --gzip \
        --archive="$OUTPUT" \
        --readPreference=secondaryPreferred \
        2>&1 | tee -a "$LOG_FILE"

    log "oplog 增量备份完成"

    # 清理超过保留期的 oplog
    find "$BACKUP_DIR" -name "oplog_*.bson.gz" -mmin +$((RETENTION_HOURS_OPLOG * 60)) -delete
}

# ── 主逻辑 ─────────────────────────────────────────────────────────────────
case "${1:-full}" in
    full)  full_backup  ;;
    oplog) oplog_backup ;;
    *)
        echo "用法: $0 [full|oplog]"
        exit 1
        ;;
esac

log "备份任务结束"
*/

// --- 恢复脚本: restore_mongo.sh ---
/*
#!/bin/bash
# ═══════════════════════════════════════════════════════════════════════════
# restore_mongo.sh — SocialGraph Pro MongoDB 恢复 (含 PITR)
# 用法:
#   ./restore_mongo.sh full <备份文件>                    # 恢复全量备份
#   ./restore_mongo.sh pitr <全量文件> <目标时间>          # 时间点恢复
#   ./restore_mongo.sh collection <备份文件> <集合名>      # 恢复单个集合
#   ./restore_mongo.sh dry-run <备份文件>                 # 测试验证
# ═══════════════════════════════════════════════════════════════════════════
set -euo pipefail

MONGO_URI="${MONGO_URI:-mongodb://admin:mongopass@localhost:27017}"
BACKUP_DIR="${BACKUP_DIR:-/data/backups/mongodb}"
TEMP_RESTORE_DB="socialgraph_restore_verify"

log() { echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] $*"; }

# ── 场景 1: 全量恢复 (灾难恢复) ───────────────────────────────────────────
full_restore() {
    local ARCHIVE="$1"
    if [ ! -f "$ARCHIVE" ]; then
        log "错误: 备份文件不存在: $ARCHIVE"
        exit 1
    fi

    log "警告: 将删除现有 socialgraph_analytics 数据库并恢复!"
    log "按 Ctrl+C 取消，或等待 5 秒继续..."
    sleep 5

    log "删除现有数据库..."
    mongosh --quiet --eval 'db.getSiblingDB("socialgraph_analytics").dropDatabase()'

    log "恢复全量备份: $ARCHIVE"
    mongorestore --uri="$MONGO_URI" \
        --gzip \
        --archive="$ARCHIVE" \
        --drop \
        --numInsertionWorkersPerCollection=4 \
        2>&1

    log "全量恢复完成"
    verify_restore "socialgraph_analytics"
}

# ── 场景 2: 时间点恢复 (PITR) ─────────────────────────────────────────────
pitr_restore() {
    local FULL_ARCHIVE="$1"
    local TARGET_TIME="$2"  # 格式: "2024-06-15T14:30:00Z"

    if [ ! -f "$FULL_ARCHIVE" ]; then
        log "错误: 全量备份文件不存在: $FULL_ARCHIVE"
        exit 1
    fi

    log "时间点恢复: 目标时间=$TARGET_TIME"

    # Step 1: 恢复全量备份到临时数据库
    log "Step 1/4: 恢复全量备份到 $TEMP_RESTORE_DB..."
    mongorestore --uri="$MONGO_URI" \
        --gzip \
        --archive="$FULL_ARCHIVE" \
        --nsFrom="socialgraph_analytics.*" \
        --nsTo="${TEMP_RESTORE_DB}.*" \
        --numInsertionWorkersPerCollection=4 \
        2>&1

    # Step 2: 找到全量备份时间点之后的 oplog 文件并 replay
    local FULL_TS=$(basename "$FULL_ARCHIVE" | grep -oP '\d{8}_\d{6}' | head -1)
    log "Step 2/4: 查找 $FULL_TS 之后的 oplog 备份..."

    for OPLOG in $(ls -1 "$BACKUP_DIR"/oplog_*.bson.gz | sort); do
        # 简化检查: 只 replay 时间上在后的 oplog
        log "  重放 oplog: $OPLOG"
        mongorestore --uri="$MONGO_URI" \
            --gzip \
            --archive="$OPLOG" \
            --oplogReplay \
            --oplogLimit="$TARGET_TIME" \
            2>&1 || log "  (部分 oplog 可能已应用，继续...)"
    done

    # Step 3: 从临时数据库合并到正式数据库
    log "Step 3/4: 合并临时数据库到正式库..."
    mongosh --quiet --eval "
        var src = db.getSiblingDB('$TEMP_RESTORE_DB');
        var dst = db.getSiblingDB('socialgraph_analytics');
        src.getCollectionNames().forEach(function(coll) {
            var count = src[coll].countDocuments();
            print('  迁移: ' + coll + ' (' + count + ' 文档)');
            src[coll].aggregate([{ \$out: { db: 'socialgraph_analytics', coll: coll } }]);
        });
    "

    # Step 4: 清理临时数据库
    log "Step 4/4: 清理临时数据库..."
    mongosh --quiet --eval "db.getSiblingDB('$TEMP_RESTORE_DB').dropDatabase()"

    log "PITR 恢复完成，目标时间: $TARGET_TIME"
    verify_restore "socialgraph_analytics"
}

# ── 场景 3: 单集合恢复 ───────────────────────────────────────────────────
collection_restore() {
    local ARCHIVE="$1"
    local COLLECTION="$2"

    if [ ! -f "$ARCHIVE" ]; then
        log "错误: 备份文件不存在: $ARCHIVE"
        exit 1
    fi

    log "恢复集合 socialgraph_analytics.$COLLECTION..."

    mongorestore --uri="$MONGO_URI" \
        --gzip \
        --archive="$ARCHIVE" \
        --nsInclude="socialgraph_analytics.${COLLECTION}" \
        --numInsertionWorkersPerCollection=2 \
        2>&1

    log "集合恢复完成: $COLLECTION"
    verify_collection "$COLLECTION"
}

# ── 验证恢复结果 ──────────────────────────────────────────────────────────
verify_restore() {
    local DB="$1"
    log "验证数据库完整性..."
    mongosh --quiet --eval "
        var db = db.getSiblingDB('$DB');
        var collections = ['analysis_snapshots', 'operation_logs', 'performance_metrics',
                           'cache_registry', 'graph_snapshots'];
        collections.forEach(function(c) {
            var cnt = db[c].estimatedDocumentCount();
            print('  ' + c + ': ' + cnt + ' 文档');
            if (cnt === 0) print('  WARNING: ' + c + ' 为空!');
        });
        db.analysis_snapshots.getIndexes().forEach(function(idx) {
            print('  Index: ' + idx.name);
        });
    "
}

verify_collection() {
    local COLL="$1"
    log "验证集合 $COLL 数据..."
    mongosh --quiet --eval "
        var cnt = db.getSiblingDB('socialgraph_analytics').$COLL.countDocuments();
        print('  ' + cnt + ' 文档');
        // 随机抽样验证
        var sample = db.getSiblingDB('socialgraph_analytics').$COLL.aggregate([{ \$sample: { size: 5 } }]);
        sample.forEach(function(doc) { printjson(doc); });
    "
}

# ── 主逻辑 ─────────────────────────────────────────────────────────────────
case "${1:-}" in
    full)
        full_restore "${2:?需要备份文件路径}"
        ;;
    pitr)
        pitr_restore "${2:?需要全量备份文件}" "${3:?需要目标时间(如 2024-06-15T14:30:00Z)}"
        ;;
    collection)
        collection_restore "${2:?需要备份文件路径}" "${3:?需要集合名}"
        ;;
    dry-run)
        mongorestore --uri="$MONGO_URI" --gzip --archive="${2:?需要备份文件}" --dryRun --verbose
        ;;
    *)
        echo "用法: $0 {full|pitr|collection|dry-run} <args...>"
        echo "  full        <备份文件>                     — 全量恢复"
        echo "  pitr        <全量文件> <目标时间ISO8601>    — 时间点恢复"
        echo "  collection  <备份文件> <集合名>             — 单集合恢复"
        echo "  dry-run     <备份文件>                     — 验证备份内容"
        exit 1
        ;;
esac
*/

// --- 恢复验证检查表 ---
//
// 恢复后自动验证项目:
// 1. 文档计数: 每个集合 estimatedDocumentCount() vs 备份时的计数
// 2. 索引完整性: 检查所有索引是否存在 (getIndexes())
// 3. 抽样数据: 每个集合随机抽取 5 条，验证 JSON Schema 合法性
// 4. TTL 索引: 确认所有 TTL 索引的 expireAfterSeconds 设置正确
// 5. 应用层冒烟测试:
//    - GET /api/v1/health → 200
//    - GET /api/v1/graph/pagerank → 200 (需 C++ 引擎可用)
//    - 检查最近 1 小时的 operation_logs 是否可查询

// --- 监控指标 (Prometheus / Cron 脚本) ---
//
// 备份健康检查:
//   - backup_last_success_timestamp: 最近一次成功备份的时间戳 (alert if > 25h)
//   - backup_duration_seconds: 备份耗时 (alert if > 3600)
//   - backup_size_bytes: 备份文件大小 (日增长率 > 20% 需关注)
//   - oplog_backup_lag_seconds: oplog 备份延迟 (alert if > 7200)
//
// Prometheus pushgateway 示例 (在 backup script 末尾):
//   echo "mongo_backup_last_success $(date +%s)" | curl --data-binary @- $PUSHGATEWAY/metrics/job/mongo_backup


// ============================================================================
// 附录 A: 生产环境部署检查表
// ============================================================================
//
// [ ] MongoDB Replica Set 配置 (至少 3 节点)
// [ ] 连接字符串包含所有节点: mongodb://host1,host2,host3/?replicaSet=rs0
// [ ] 所有索引在部署前通过 background:true 创建
// [ ] TTL 索引 expireAfterSeconds 确认 (7776000 / 2592000 / 15552000)
// [ ] 备份脚本已部署到 cron
// [ ] 恢复脚本已测试 (dry-run 至少一次)
// [ ] 监控告警已配置 (备份延迟 / 复制延迟 / 磁盘使用率)
// [ ] 认证已启用 (SCRAM-SHA-256, 非默认用户名/密码)
// [ ] 网络加密已启用 (TLS/SSL)
// [ ] 审计日志已启用 (MongoDB Enterprise / Atlas)
// [ ] Python 驱动连接超时已设置 (connectTimeoutMS=5000)
// [ ] Fire-and-forget 确认使用 {w:0} (日志/指标集合)
// [ ] 读偏好已设置 (primaryPreferred)
// ============================================================================


// ============================================================================
// 附录 B: 常用运维命令速查
// ============================================================================
//
// // 查看集合统计
// db.analysis_snapshots.stats()
// db.operation_logs.stats()
//
// // 查看索引使用情况
// db.analysis_snapshots.aggregate([{ $indexStats: {} }])
//
// // 查看当前操作 (长时间运行的查询)
// db.currentOp({ "secs_running": { $gt: 5 } })
//
// // 杀死慢查询
// db.killOp(<opId>)
//
// // 手动触发 TTL 清理 (MongoDB 默认每 60 秒检查一次)
// db.analysis_snapshots.reIndex()
//
// // 手动执行预聚合 (每小时运行)
// // 见聚合管道之后的 "Hourly Rollup Job" 部分
//
// // 检查复制延迟
// db.printSecondaryReplicationInfo()
//
// // 紧凑集合 (释放删除文档后的磁盘空间)
// db.runCommand({ compact: "operation_logs" })
//
// // 设置分析器 (记录慢查询)
// db.setProfilingLevel(1, { slowms: 100 })
//
// // 查看最近的慢查询
// db.system.profile.find().sort({ ts: -1 }).limit(10).pretty()
// ============================================================================


// ============================================================================
// 附录 C: 预聚合定时任务 (Python APScheduler)
// ============================================================================
//
// 以下为 Python 伪代码，展示如何实现 operation_logs → operation_stats_hourly 的预聚合。
// 应通过 APScheduler / Celery Beat / cron 每小时触发一次。
//
// ```python
// from datetime import datetime, timedelta, timezone
// from db.mongodb import get_mongo_db
// import logging
//
// logger = logging.getLogger(__name__)
//
// async def rollup_operation_logs_hourly():
//     """将过去 1 小时的 operation_logs 聚合写入 operation_stats_hourly。"""
//     db = await get_mongo_db()
//     if db is None:
//         return
//
//     now = datetime.now(timezone.utc)
//     hour_start = now.replace(minute=0, second=0, microsecond=0) - timedelta(hours=1)
//     hour_end = hour_start + timedelta(hours=1)
//
//     pipeline = [
//         {"$match": {
//             "created_at": {"$gte": hour_start, "$lt": hour_end}
//         }},
//         {"$facet": {
//             "overview": [
//                 {"$group": {
//                     "_id": None,
//                     "total_operations": {"$sum": 1},
//                     "unique_users": {"$addToSet": "$user_id"},
//                     "durations": {"$push": "$duration_ms"}
//                 }}
//             ],
//             "status_breakdown": [
//                 {"$group": {"_id": "$status", "count": {"$sum": 1}}}
//             ],
//             "action_breakdown": [
//                 {"$group": {"_id": "$action", "count": {"$sum": 1}}}
//             ],
//             "resource_breakdown": [
//                 {"$group": {"_id": "$resource", "count": {"$sum": 1}}}
//             ],
//             "cache_stats": [
//                 {"$match": {"action": "run_algorithm"}},
//                 {"$group": {
//                     "_id": None,
//                     "cache_hits": {"$sum": {"$cond": [{"$eq": ["$details.cache_hit", True]}, 1, 0]}},
//                     "cache_misses": {"$sum": {"$cond": [{"$eq": ["$details.cache_hit", True]}, 0, 1]}}
//                 }}
//             ]
//         }}
//     ]
//
//     result = await db.operation_logs.aggregate(pipeline).to_list(1)
//     if not result:
//         return
//
//     r = result[0]
//     overview = r["overview"][0] if r["overview"] else {}
//
//     durations = sorted(overview.get("durations", [0]))
//     n = len(durations) or 1
//
//     doc = {
//         "hour": hour_start,
//         "total_operations": overview.get("total_operations", 0),
//         "unique_users": len(overview.get("unique_users", [])),
//         "status_breakdown": {s["_id"]: s["count"] for s in r["status_breakdown"]},
//         "action_breakdown": {s["_id"]: s["count"] for s in r["action_breakdown"]},
//         "resource_breakdown": {s["_id"]: s["count"] for s in r["resource_breakdown"]},
//         "p50_duration_ms": durations[int(n * 0.50)],
//         "p95_duration_ms": durations[int(n * 0.95)],
//         "p99_duration_ms": durations[int(n * 0.99)],
//         "avg_duration_ms": sum(durations) / n,
//         "cache_hit_count": r["cache_stats"][0].get("cache_hits", 0) if r["cache_stats"] else 0,
//         "cache_miss_count": r["cache_stats"][0].get("cache_misses", 0) if r["cache_stats"] else 0,
//         "created_at": now,
//     }
//
//     # Upsert (幂等 — 同一小时重复执行只更新)
//     await db.operation_stats_hourly.update_one(
//         {"hour": hour_start},
//         {"$set": doc},
//         upsert=True
//     )
//     logger.info("预聚合完成: %s → %d 操作, %d 用户",
//                  hour_start.isoformat(), doc["total_operations"], doc["unique_users"])
//
// # 在 lifespan() 中注册:
// # scheduler.add_job(rollup_operation_logs_hourly, 'cron', minute=5)  # 每小时第5分钟
// ```
// ============================================================================


// ============================================================================
// 附录 D: 数据保留策略总览
// ============================================================================
//
// | 集合                      | 保留天数 | TTL 字段    | 过期后行为          | 理由                      |
// |---------------------------|---------|------------|--------------------|--------------------------|
// | analysis_snapshots        | 90      | created_at | 自动删除            | 季度趋势 + 存储成本平衡     |
// | operation_logs            | 30      | created_at | 自动删除            | 审计合规 (最小 30d)        |
// | operation_stats_hourly    | 90      | created_at | 自动删除            | 比原始日志长 3 倍          |
// | performance_metrics       | 7       | timestamp  | 自动删除            | 原始数据仅需 7 天          |
// | performance_metrics_hourly| 90      | created_at | 自动删除            | 小时聚合保留 90 天         |
// | cache_registry            | 30      | created_at | 自动删除            | 跟踪近期缓存活动           |
// | graph_snapshots           | 365     | N/A        | 手动归档 (每年)      | 图演化历史分析             |
//
// 注意事项:
//   - MongoDB TTL 后台线程每 60 秒扫描一次索引，过期文档不会精确到秒删除
//   - 删除操作有 I/O 开销，建议在业务低峰期让 TTL 自然运行
//   - TTL 索引 __不能__ 是复合索引的一部分，必须是单字段
// ============================================================================
