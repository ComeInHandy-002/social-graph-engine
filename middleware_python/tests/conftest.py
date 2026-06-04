import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture
def client():
    """创建 TestClient，模拟所有外部依赖为不可用状态。"""
    with patch.dict(os.environ, {
        "REDIS_HOST": "localhost",
        "REDIS_PORT": "6379",
        "NEO4J_URI": "bolt://localhost:7687",
        "NEO4J_USER": "neo4j",
        "NEO4J_PASSWORD": "password123",
        "CPP_ENGINE_PATH": "/fake/path/graph_engine",
        "GRAPH_DATA_PATH": "/fake/path/data.txt",
        "MYSQL_DSN": "mysql+asyncmy://fake:fake@localhost:3306/test",
        "MONGO_URI": "mongodb://fake:fake@localhost:27017",
    }):
        # 在导入 app 之前，先确保数据库模块不会被真正连接
        with patch("db.redis.get_redis_async", return_value=None), \
             patch("db.redis.get_redis", return_value=None), \
             patch("db.mysql.get_mysql_pool", return_value=None), \
             patch("db.mongodb.get_mongo_db", return_value=None), \
             patch("db.neo4j.get_neo4j_driver", return_value=None):
            from server import app
            with TestClient(app) as c:
                yield c


@pytest.fixture
def mock_run_cpp_engine():
    """模拟 C++ 引擎执行 — 在路由模块中 patch 导入的函数。"""
    with patch("routes.graph.execute_command") as mock:
        yield mock


@pytest.fixture
def mock_redis():
    """模拟 Redis 不可用 — patch db 层的 get_redis_async 返回 None。"""
    with patch("db.redis.get_redis_async", return_value=None) as mock:
        yield mock


@pytest.fixture
def mock_neo4j():
    """模拟 Neo4j 不可用 — patch services.neo4j_service 中的 get_full_topology。"""
    with patch("services.neo4j_service.get_full_topology", return_value=None) as mock:
        yield mock
