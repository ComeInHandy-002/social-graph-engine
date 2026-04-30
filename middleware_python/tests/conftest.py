import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture
def client():
    # 在导入 server 之前模拟外部依赖
    with patch.dict(os.environ, {
        "REDIS_HOST": "localhost",
        "REDIS_PORT": "6379",
        "NEO4J_URI": "bolt://localhost:7687",
        "NEO4J_USER": "neo4j",
        "NEO4J_PASSWORD": "password123",
        "CPP_ENGINE_PATH": "/fake/path/graph_engine",
        "GRAPH_DATA_PATH": "/fake/path/data.txt"
    }):
        from server import app
        with TestClient(app) as c:
            yield c


@pytest.fixture
def mock_run_cpp_engine():
    with patch("server.run_cpp_engine") as mock:
        yield mock


@pytest.fixture
def mock_redis():
    with patch("server.get_redis", return_value=None) as mock:
        yield mock


@pytest.fixture
def mock_neo4j():
    with patch("server.get_neo4j", return_value=None) as mock:
        yield mock
