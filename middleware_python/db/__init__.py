"""
db/ — 异步数据库驱动层

Lazy-Connect 模式: 首次调用时建立连接，后续复用全局单例。
连接失败时返回 None，所有上层代码按需降级。

模块清单:
  - redis.py:   redis.asyncio (异步) + redis-py (同步), 双客户端
  - mysql.py:   aiomysql 连接池, 事务支持 + CRUD 便捷函数
  - mongodb.py: Motor (motor.motor_asyncio), Fire-and-forget + TTL 索引
  - neo4j.py:   neo4j AsyncDriver, Cypher 参数化查询, 自动回退 C++ 引擎
"""
