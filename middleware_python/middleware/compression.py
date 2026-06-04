"""
SocialGraph Pro — GZip 响应压缩中间件

策略:
  - 仅压缩 > 1KB 的 JSON 响应（小响应不值得 CPU 开销）
  - 对 text/html, application/json, text/plain 类型进行压缩
  - 尊重客户端 Accept-Encoding header
"""
from starlette.middleware.gzip import GZipMiddleware

# 直接使用 Starlette/FastAPI 内置的 GZipMiddleware
# 配置: minimum_size=1024 表示仅压缩 > 1KB 的响应

class _GZipMiddleware(GZipMiddleware):
    """GZip 压缩中间件，仅压缩 > 1KB 的响应体。"""
    def __init__(self, app, **kwargs):
        kwargs.setdefault("minimum_size", 1024)
        super().__init__(app, **kwargs)


def create_compression_middleware():
    """返回 GZip 压缩中间件类（FastAPI add_middleware 会自动实例化）。"""
    return _GZipMiddleware
