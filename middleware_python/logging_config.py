"""
SocialGraph Pro — 结构化日志配置

使用 Python 标准 logging 模块 + JSON 格式化器，输出到 stdout。
适用于 ELK / Loki / Datadog / CloudWatch 等日志聚合系统。

日志级别策略:
  - development:  DEBUG — 打印所有细节
  - staging:      INFO  — 标准请求日志
  - production:   INFO  — 标准请求日志 (WARNING 级别以减少噪音也是可选项)

日志内容:
  - 每条日志包含: timestamp, level, logger, request_id (如有), message
  - 请求日志由 middleware/request_logger.py 以 JSON 格式输出
  - 所有模块通过 logging.getLogger("socialgraph.xxx") 获取 logger
"""
import json
import logging
import logging.config
import sys
from datetime import datetime, timezone


class JSONFormatter(logging.Formatter):
    """结构化 JSON 日志格式化器。

    输出格式:
      {
        "timestamp": "2024-01-15T10:30:00.123Z",
        "level": "INFO",
        "logger": "socialgraph.routes.graph",
        "message": "请求处理完成",
        "module": "graph",
        "function": "get_pagerank",
        "line": 42
      }
    """

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        # 附加异常信息
        if record.exc_info and record.exc_info[0]:
            log_entry["exception"] = self.formatException(record.exc_info)

        # 附加额外字段 (通过 extra= 传入)
        if hasattr(record, "request_id"):
            log_entry["request_id"] = record.request_id
        if hasattr(record, "duration_ms"):
            log_entry["duration_ms"] = record.duration_ms

        return json.dumps(log_entry, ensure_ascii=False, default=str)


class ColoredConsoleFormatter(logging.Formatter):
    """开发环境用的彩色控制台格式化器。"""

    COLORS = {
        "DEBUG": "\033[36m",     # 青色
        "INFO": "\033[32m",      # 绿色
        "WARNING": "\033[33m",   # 黄色
        "ERROR": "\033[31m",     # 红色
        "CRITICAL": "\033[35m",  # 紫色
    }
    RESET = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:
        color = self.COLORS.get(record.levelname, "")
        timestamp = datetime.now(timezone.utc).strftime("%H:%M:%S")
        msg = f"{color}[{timestamp}] [{record.levelname:<7}] {record.name}: {record.getMessage()}{self.RESET}"

        if record.exc_info and record.exc_info[0]:
            msg += "\n" + self.formatException(record.exc_info)

        return msg


def setup_logging(level: str = "INFO", environment: str = "development", use_json: bool = False):
    """配置全局日志系统。

    Args:
        level:       日志级别 (DEBUG/INFO/WARNING/ERROR/CRITICAL)
        environment: 环境标识 (development/staging/production)
        use_json:    是否使用 JSON 格式 (生产环境推荐 True)
    """
    # 根 logger
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    # 清除已有 handler
    root_logger.handlers.clear()

    # 根据环境选择格式化器
    if use_json or environment in ("staging", "production"):
        formatter = JSONFormatter()
    else:
        formatter = ColoredConsoleFormatter()

    # 控制台 handler (stdout)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    # 抑制嘈杂的第三方库日志
    logging.getLogger("asyncio").setLevel(logging.WARNING)
    logging.getLogger("aiomysql").setLevel(logging.WARNING)
    logging.getLogger("motor").setLevel(logging.WARNING)
    logging.getLogger("neo4j").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    # 确保应用模块的 logger 都设置了合适的级别
    for module_prefix in ["socialgraph", "core", "auth", "routes", "services", "db", "middleware"]:
        logging.getLogger(module_prefix).setLevel(getattr(logging, level.upper(), logging.INFO))

    logging.getLogger("socialgraph").info(
        "日志系统已初始化: level=%s, environment=%s, format=%s",
        level, environment,
        "json" if (use_json or environment in ("staging", "production")) else "console",
    )
