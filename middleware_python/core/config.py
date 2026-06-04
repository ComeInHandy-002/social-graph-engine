"""
SocialGraph Pro — 统一配置中心
基于 Pydantic BaseSettings，支持 .env 文件和环境变量覆盖。
所有模块从此处获取配置，消除分散的 os.environ.get() 调用。
"""
import os
import secrets
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """应用全局配置。环境变量前缀为 SGP_ (SocialGraph Pro)。"""

    # ── 应用基础 ──────────────────────────────────────────────
    app_name: str = "SocialGraph Pro"
    app_version: str = "3.0.0"
    debug: bool = False
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    environment: Literal["development", "staging", "production"] = "development"

    # ── C++ 引擎 ──────────────────────────────────────────────
    cpp_engine_path: str = ""
    graph_data_path: str = ""
    cpp_engine_pool_size: int = 4   # 预派生子进程数量
    cpp_engine_tcp_host: str = "127.0.0.1"  # TCP 长连接模式主机
    cpp_engine_tcp_port: int = 9555         # TCP 长连接模式端口

    # ── JWT / 认证 ────────────────────────────────────────────
    jwt_secret_key: str = ""
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 30
    api_key_prefix: str = "sk_"
    bcrypt_cost: int = 12

    # ── Redis ─────────────────────────────────────────────────
    redis_host: str = "127.0.0.1"
    redis_port: int = 6379
    redis_db: int = 0
    redis_password: str = ""
    redis_pool_max_connections: int = 20
    redis_socket_timeout: float = 5.0
    redis_socket_connect_timeout: float = 2.0
    redis_socket_keepalive: bool = True       # TCP keepalive 保活
    redis_health_check_interval: int = 30      # 连接健康检查间隔（秒）— redis-py >= 5.0.2 推荐
    redis_slow_query_threshold_ms: int = 10    # Redis 慢查询记录阈值（毫秒）
    redis_key_namespace: str = "sgp"           # 新版键命名空间（SocialGraph Pro）

    # ── Neo4j ─────────────────────────────────────────────────
    neo4j_uri: str = "bolt://127.0.0.1:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = ""
    neo4j_max_pool_size: int = 10
    neo4j_connection_acquisition_timeout: float = 10.0
    neo4j_connection_lifetime: int = 3600        # 1 小时
    neo4j_connection_idle_timeout: int = 600      # 10 分钟空闲自动关闭
    neo4j_liveness_check_timeout: float = 30.0    # 空闲连接健康检查间隔(秒)
    neo4j_query_timeout: float = 30.0             # 单次查询超时
    neo4j_max_retry_attempts: int = 3             # 瞬态错误重试次数
    neo4j_retry_base_delay: float = 1.0           # 重试基础延迟（秒，指数退避）

    # ── MySQL ─────────────────────────────────────────────────
    mysql_host: str = "127.0.0.1"
    mysql_port: int = 3306
    mysql_user: str = "socialgraph"
    mysql_password: str = ""
    mysql_database: str = "socialgraph"
    mysql_pool_min_size: int = 5
    mysql_pool_max_size: int = 20
    mysql_pool_recycle: int = 3600
    mysql_connect_timeout: int = 5

    # ── MongoDB ───────────────────────────────────────────────
    mongodb_uri: str = ""
    mongodb_database: str = "socialgraph_analytics"
    mongodb_min_pool_size: int = 10
    mongodb_max_pool_size: int = 50
    mongodb_connect_timeout_ms: int = 5000
    mongodb_server_selection_timeout_ms: int = 5000

    # ── 缓存策略 ──────────────────────────────────────────────
    cache_topology_ttl: int = 3600        # 拓扑结构 1 小时
    cache_algorithm_ttl: int = 86400      # 算法结果 24 小时
    cache_stats_ttl: int = 600            # 图统计 10 分钟
    cache_default_ttl: int = 3600
    cache_compression_threshold: int = 65536     # 压缩阈值：大于 64KB 自动 zlib 压缩
    cache_ttl_jitter_percent: float = 0.10       # TTL 随机偏移比例（±10%，防止缓存雪崩）
    cache_warm_on_startup: bool = True           # 启动时预热 P0 级缓存
    cache_stats_enabled: bool = True             # 启用命中率统计

    # ── 限流 ──────────────────────────────────────────────────
    rate_limit_anonymous_per_minute: int = 10
    rate_limit_authenticated_per_minute: int = 60
    rate_limit_api_key_per_minute: int = 300

    # ── 登录安全 ──────────────────────────────────────────────
    login_max_attempts: int = 5
    login_lockout_minutes: int = 15

    # ── 导出 ──────────────────────────────────────────────────
    export_max_file_size_bytes: int = 52_428_800  # 50MB

    # ── 维护 ──────────────────────────────────────────────────
    maintenance_mode: bool = False

    # ── 慢查询阈值 ─────────────────────────────────────────────
    slow_query_threshold_ms: int = 500

    class Config:
        env_prefix = "SGP_"
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False

        @classmethod
        def customise_sources(cls, init_settings, env_settings, file_secret_settings):
            """确保原始环境变量名也能被识别（向后兼容）。"""
            return (init_settings, env_settings, file_secret_settings)


# ── 已知的弱默认值模式（用于启动时检测）──────────────────────────
_INSECURE_PATTERNS = [
    "CHANGE_ME", "CHANGEME", "change_me", "changeme",
    "password123", "password", "admin123", "admin",
    "secret", "SECRET", "default", "DEFAULT",
    "changethis", "replaceme", "todo",
]


def _is_insecure(value: str) -> bool:
    """检查值是否为已知的不安全默认值。"""
    if not value:
        return True  # 空值也是不安全的
    for pattern in _INSECURE_PATTERNS:
        if pattern in value.lower():
            return True
    return False


def _validate_secrets(settings: "Settings") -> list[str]:
    """验证关键密钥是否已配置。返回警告信息列表。"""
    warnings = []

    secrets_to_check = [
        ("jwt_secret_key", settings.jwt_secret_key, "JWT 签名密钥", 32),
        ("neo4j_password", settings.neo4j_password, "Neo4j 密码", 8),
        ("mysql_password", settings.mysql_password, "MySQL 密码", 8),
        ("mongodb_uri", settings.mongodb_uri, "MongoDB URI", 20),
    ]

    for name, value, label, min_len in secrets_to_check:
        if _is_insecure(value) or len(value) < min_len:
            warnings.append(
                f"安全警告: {label} ({name}) "
                f"未设置或使用不安全的默认值。"
                f"请设置 SGP_{name.upper()} 环境变量。"
            )

    return warnings


@lru_cache()
def get_settings() -> Settings:
    """获取全局配置单例 (lru_cache 确保只初始化一次)。"""
    settings = Settings()

    # ── 向后兼容旧环境变量名 ──────────────────────────────────
    overrides = {}
    if not settings.cpp_engine_path and os.environ.get("CPP_ENGINE_PATH"):
        overrides["cpp_engine_path"] = os.environ["CPP_ENGINE_PATH"]
    if not settings.graph_data_path and os.environ.get("GRAPH_DATA_PATH"):
        overrides["graph_data_path"] = os.environ["GRAPH_DATA_PATH"]
    if not settings.redis_host or settings.redis_host == "127.0.0.1":
        if os.environ.get("REDIS_HOST"):
            overrides["redis_host"] = os.environ["REDIS_HOST"]
    if os.environ.get("REDIS_PORT"):
        overrides["redis_port"] = int(os.environ["REDIS_PORT"])
    if os.environ.get("NEO4J_URI"):
        overrides["neo4j_uri"] = os.environ["NEO4J_URI"]
    if os.environ.get("NEO4J_USER"):
        overrides["neo4j_user"] = os.environ["NEO4J_USER"]
    if os.environ.get("NEO4J_PASSWORD"):
        overrides["neo4j_password"] = os.environ["NEO4J_PASSWORD"]
    if os.environ.get("MYSQL_HOST"):
        overrides["mysql_host"] = os.environ["MYSQL_HOST"]
    if os.environ.get("MYSQL_PORT"):
        overrides["mysql_port"] = int(os.environ["MYSQL_PORT"])
    if os.environ.get("MYSQL_USER"):
        overrides["mysql_user"] = os.environ["MYSQL_USER"]
    if os.environ.get("MYSQL_PASSWORD"):
        overrides["mysql_password"] = os.environ["MYSQL_PASSWORD"]
    if os.environ.get("MYSQL_DATABASE"):
        overrides["mysql_database"] = os.environ["MYSQL_DATABASE"]
    if os.environ.get("MONGODB_URI"):
        overrides["mongodb_uri"] = os.environ["MONGODB_URI"]
    if os.environ.get("MONGODB_DATABASE"):
        overrides["mongodb_database"] = os.environ["MONGODB_DATABASE"]

    if overrides:
        settings = settings.copy(update=overrides)

    # ── 开发环境自动生成密钥 ──────────────────────────────────
    if not settings.jwt_secret_key:
        if settings.environment == "development":
            settings.jwt_secret_key = "dev_" + secrets.token_hex(32)
        # 非开发环境在验证阶段报告

    # ── C++ 引擎路径自动探测 ──────────────────────────────────
    if not settings.cpp_engine_path:
        settings.cpp_engine_path = _resolve_path(
            "../backend_cpp/cmake-build-release/graph_engine.exe",
            "../backend_cpp/cmake-build-debug/graph_engine.exe",
            "../backend_cpp/build/graph_engine",
            "../backend_cpp/build/graph_engine.exe",
        )

    if not settings.graph_data_path:
        settings.graph_data_path = _resolve_path(
            "../backend_cpp/facebook_combined.txt",
        )

    # ── 安全验证 ──────────────────────────────────────────────
    secret_warnings = _validate_secrets(settings)
    if secret_warnings:
        import logging
        logger = logging.getLogger("socialgraph.config")
        for w in secret_warnings:
            logger.warning(w)

        if settings.environment == "production":
            raise RuntimeError(
                "生产环境禁止使用不安全的默认密钥。"
                "请通过环境变量设置所有 SGP_* 安全配置项。\n"
                + "\n".join(secret_warnings)
            )

    return settings


def _resolve_path(*candidates: str) -> str:
    """在候选路径中查找第一个存在的文件。"""
    base = Path(__file__).resolve().parent.parent  # middleware_python/
    for c in candidates:
        path = (base / c).resolve()
        if path.exists():
            return str(path)
    return str((base / candidates[0]).resolve())
