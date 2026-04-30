import pytest
from unittest.mock import patch


class TestShortestPath:
    def test_bfs_path_valid(self, client, mock_run_cpp_engine):
        mock_run_cpp_engine.return_value = {
            "status": "success",
            "time_ms": 10,
            "path": ["1", "2", "3"]
        }
        response = client.post("/api/v1/graph/shortest_path", json={
            "start_node": "1",
            "target_node": "3",
            "algorithm": "bfs"
        })
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert len(data["path"]) == 3

    def test_dijkstra_path_valid(self, client, mock_run_cpp_engine):
        mock_run_cpp_engine.return_value = {
            "status": "success",
            "time_ms": 15,
            "path": ["1", "2", "3"]
        }
        response = client.post("/api/v1/graph/shortest_path", json={
            "start_node": "1",
            "target_node": "3",
            "algorithm": "dijkstra"
        })
        assert response.status_code == 200

    def test_dfs_echo_chamber(self, client, mock_run_cpp_engine):
        mock_run_cpp_engine.return_value = {
            "status": "success",
            "time_ms": 5,
            "path": ["5", "6", "7", "5"]
        }
        response = client.post("/api/v1/graph/shortest_path", json={
            "start_node": "5",
            "target_node": "",
            "algorithm": "dfs"
        })
        assert response.status_code == 200
        assert response.json()["status"] == "success"


class TestAlgorithmEndpoints:
    def test_get_pagerank(self, client, mock_run_cpp_engine, mock_redis):
        mock_run_cpp_engine.return_value = {
            "status": "success",
            "time_ms": 2200,
            "data": [{"node": "1", "score": 0.5}, {"node": "2", "score": 0.5}]
        }
        response = client.get("/api/v1/graph/pagerank")
        assert response.status_code == 200

    def test_get_community(self, client, mock_run_cpp_engine, mock_redis):
        mock_run_cpp_engine.return_value = {
            "status": "success",
            "time_ms": 500,
            "data": [{"node": "1", "community": "A"}, {"node": "2", "community": "A"}]
        }
        response = client.get("/api/v1/graph/community")
        assert response.status_code == 200

    def test_get_betweenness(self, client, mock_run_cpp_engine, mock_redis):
        mock_run_cpp_engine.return_value = {
            "status": "success",
            "time_ms": 5000,
            "data": [{"node": "1", "score": 10.0}]
        }
        response = client.get("/api/v1/graph/betweenness")
        assert response.status_code == 200

    def test_get_kcore(self, client, mock_run_cpp_engine, mock_redis):
        mock_run_cpp_engine.return_value = {
            "status": "success",
            "time_ms": 100,
            "data": [{"node": "1", "coreness": 3.0}]
        }
        response = client.get("/api/v1/graph/kcore")
        assert response.status_code == 200

    def test_get_clustering_coeff(self, client, mock_run_cpp_engine, mock_redis):
        mock_run_cpp_engine.return_value = {
            "status": "success",
            "time_ms": 200,
            "data": [{"node": "1", "coefficient": 0.33}]
        }
        response = client.get("/api/v1/graph/clustering_coeff")
        assert response.status_code == 200

    def test_get_graph_stats(self, client, mock_run_cpp_engine, mock_redis):
        mock_run_cpp_engine.return_value = {
            "status": "success",
            "time_ms": 50,
            "nodes": 100,
            "edges": 500,
            "density": 0.1,
            "avg_degree": 10.0,
            "max_degree": 50,
            "diameter_approx": 6,
            "components": 1
        }
        response = client.get("/api/v1/graph/stats")
        assert response.status_code == 200
        data = response.json()
        assert data["nodes"] == 100


class TestHealthCheck:
    def test_health_endpoint(self, client):
        response = client.get("/api/v1/health")
        assert response.status_code == 200
        data = response.json()
        assert "cpp_engine_available" in data
        assert "redis_available" in data
        assert "neo4j_available" in data


class TestCORS:
    def test_cors_headers(self, client):
        response = client.options("/api/v1/graph/pagerank", headers={
            "Origin": "http://localhost",
            "Access-Control-Request-Method": "GET"
        })
        assert response.status_code in [200, 405]
