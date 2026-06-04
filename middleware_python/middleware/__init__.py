"""
middleware/ — ASGI 中间件栈

执行顺序 (请求从外到内):
  1. CORS (CORSMiddleware)                     — 跨域处理, 最先短路 OPTIONS preflight
  2. Compression (GZipMiddleware)               — 响应体 > 1KB 时 GZip 压缩
  3. Rate Limiting (RateLimitMiddleware)        — 滑动窗口限流, 三层: anonymous/auth/api_key
  4. Request Logging (RequestLoggingMiddleware) — JSON 结构化日志, request_id 传播
  5. Error Handling (ErrorHandlerMiddleware)    — 统一异常捕获, 最接近路由处理器

各中间件配置键 (SGP_* 前缀):
  - CORS: 环境自适应 (production=白名单, dev=*)
  - Compression: minimum_size=1024 (仅压 > 1KB JSON/text/html)
  - RateLimit: anonymous=10/min, authenticated=60/min, api_key=300/min
  - Logging: slow_query_threshold_ms=500 (慢请求 WARNING)
  - ErrorHandler: production 模式隐藏错误细节
"""
