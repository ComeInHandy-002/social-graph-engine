"""
SocialGraph Pro — C++ gRPC 客户端

取代原有的 asyncio.create_subprocess_exec 调用方式，通过 gRPC 长连接
与 C++ 微服务通信，消除进程启动开销 (~50ms → <1ms)。

使用方式:
    from services.cpp_grpc_client import CppGrpcClient

    client = CppGrpcClient("localhost:50051")
    await client.connect()

    # 一元调用
    result = await client.compute_pagerank(iterations=100, damping=0.85)

    # 流式调用
    async for chunk in client.compute_pagerank_stream(iterations=100):
        print(f"iteration {chunk.chunk_index}: {len(chunk.data)} nodes")

    # 路径查询
    path = await client.find_path("bfs", "node1", "node2")

    await client.close()

gRPC vs HTTP/JSON 对比:
    序列化:     protobuf 二进制 (小 3-10x, 快 5-10x)
    流式:       内建 server-streaming
    连接:       HTTP/2 多路复用, 单连接承载数百并发请求
    类型安全:   .proto 自动生成桩代码
    超时/取消:   内置 deadline 传播

环境变量:
    CPP_GRPC_ADDR    C++ gRPC 服务地址 (默认: localhost:50051)
    CPP_GRPC_TIMEOUT 默认超时秒数 (默认: 60)

依赖:
    pip install grpcio grpcio-tools

编译 proto:
    python -m grpc_tools.protoc \
        --python_out=services/ \
        --grpc_python_out=services/ \
        -I../../backend_cpp/proto \
        ../../backend_cpp/proto/socialgraph.proto
"""

import asyncio
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional, AsyncIterator, Dict, List

import grpc
from grpc import aio

logger = logging.getLogger("socialgraph.services.cpp_grpc")

# ── gRPC 桩代码导入 (带容错) ──────────────────────────────────────────
try:
    from services import socialgraph_pb2 as pb
    from services import socialgraph_pb2_grpc as pb_grpc
    GRPC_AVAILABLE = True
except ImportError:
    logger.warning(
        "gRPC 桩代码未找到。请运行: "
        "python -m grpc_tools.protoc --python_out=services/ "
        "--grpc_python_out=services/ "
        "-I../../backend_cpp/proto "
        "../../backend_cpp/proto/socialgraph.proto"
    )
    GRPC_AVAILABLE = False


# ═══════════════════════════════════════════════════════════════════════════
# 配置
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class GrpcClientConfig:
    """gRPC 客户端配置。"""
    address: str = field(default_factory=lambda: os.getenv("CPP_GRPC_ADDR", "localhost:50051"))
    default_timeout: float = float(os.getenv("CPP_GRPC_TIMEOUT", "60.0"))
    max_retries: int = 3
    retry_delay: float = 0.1
    max_send_message_length: int = 100 * 1024 * 1024  # 100MB
    max_receive_message_length: int = 100 * 1024 * 1024
    keepalive_time_ms: int = 30000
    keepalive_timeout_ms: int = 10000
    keepalive_permit_without_calls: bool = True


# ═══════════════════════════════════════════════════════════════════════════
# C++ gRPC 客户端
# ═══════════════════════════════════════════════════════════════════════════

class CppGrpcClient:
    """SocialGraph C++ 微服务 gRPC 客户端。

    特性:
      - 异步 gRPC (grpc.aio)
      - 自动重连 + 指数退避
      - Deadline 传播
      - 连接健康检查
      - 与现有 execute_command() API 兼容的结果格式

    使用示例:
        async with CppGrpcClient() as client:
            result = await client.compute_pagerank()
            print(result)
    """

    def __init__(self, address: Optional[str] = None, config: Optional[GrpcClientConfig] = None):
        """
        Args:
            address: C++ gRPC 服务地址 (如 "localhost:50051")
            config: 客户端配置 (不提供则使用默认值)
        """
        if not GRPC_AVAILABLE:
            raise RuntimeError("gRPC 不可用，请安装 grpcio 并编译 proto 桩代码")

        self.config = config or GrpcClientConfig()
        if address:
            self.config.address = address

        self._channel: Optional[aio.Channel] = None
        self._stub: Optional[pb_grpc.GraphComputeStub] = None
        self._connected = False
        self._connect_lock = asyncio.Lock()

    # ── 连接管理 ─────────────────────────────────────────────────

    async def connect(self) -> bool:
        """建立 gRPC 连接 (幂等)。"""
        async with self._connect_lock:
            if self._connected and self._channel:
                return True

            try:
                # 构建 Channel 选项
                options = [
                    ("grpc.max_send_message_length", self.config.max_send_message_length),
                    ("grpc.max_receive_message_length", self.config.max_receive_message_length),
                    ("grpc.keepalive_time_ms", self.config.keepalive_time_ms),
                    ("grpc.keepalive_timeout_ms", self.config.keepalive_timeout_ms),
                    ("grpc.keepalive_permit_without_calls", self.config.keepalive_permit_without_calls),
                    ("grpc.http2.max_pings_without_data", 0),
                ]

                self._channel = aio.insecure_channel(
                    self.config.address, options=options
                )
                self._stub = pb_grpc.GraphComputeStub(self._channel)

                # 健康检查 (Ping)
                await self._stub.Ping(
                    pb.PingRequest(client_id="python-client"),
                    timeout=5.0,
                )
                self._connected = True
                logger.info("gRPC 已连接: %s", self.config.address)
                return True

            except Exception as e:
                logger.warning("gRPC 连接失败 (%s): %s", self.config.address, e)
                self._connected = False
                self._channel = None
                self._stub = None
                return False

    async def close(self):
        """关闭 gRPC 连接。"""
        if self._channel:
            await self._channel.close()
            self._channel = None
            self._stub = None
            self._connected = False
            logger.info("gRPC 连接已关闭")

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, *args):
        await self.close()

    def is_connected(self) -> bool:
        return self._connected

    # ── 内部: 带重试的调用 ───────────────────────────────────────

    async def _call_with_retry(self, call_fn, timeout: float = 0):
        """带自动重连和重试的 gRPC 调用包装器。

        Args:
            call_fn: async callable，接受 timeout 参数
            timeout: deadline (秒), 0 表示使用默认值

        Returns:
            gRPC 响应对象
        """
        if timeout <= 0:
            timeout = self.config.default_timeout

        last_error = None
        for attempt in range(self.config.max_retries):
            try:
                if not self._connected:
                    await self.connect()
                    if not self._connected:
                        raise ConnectionError(f"无法连接 C++ 引擎 ({self.config.address})")

                return await call_fn(timeout=timeout)

            except grpc.aio.AioRpcError as e:
                last_error = e
                code = e.code()

                if code == grpc.StatusCode.UNAVAILABLE:
                    logger.warning(
                        "gRPC 服务不可用 (%s)，尝试重连 (%d/%d)",
                        self.config.address, attempt + 1, self.config.max_retries,
                    )
                    self._connected = False
                    if attempt < self.config.max_retries - 1:
                        delay = self.config.retry_delay * (2 ** attempt)
                        await asyncio.sleep(delay)
                        continue

                elif code == grpc.StatusCode.DEADLINE_EXCEEDED:
                    raise TimeoutError(f"gRPC 调用超时 ({timeout}s)")

                elif code == grpc.StatusCode.UNIMPLEMENTED:
                    raise NotImplementedError(f"算法未实现: {e.details()}")

                break  # 其他错误不重试

            except asyncio.TimeoutError:
                last_error = TimeoutError(f"gRPC 调用超时 ({timeout}s)")
                break

            except ConnectionError:
                last_error = ConnectionError(f"无法连接 C++ 引擎 ({self.config.address})")
                break

            except Exception as e:
                last_error = e
                if attempt < self.config.max_retries - 1:
                    delay = self.config.retry_delay * (2 ** attempt)
                    await asyncio.sleep(delay)
                else:
                    break

        raise last_error or RuntimeError("gRPC 调用失败")

    # ── 算法接口 ─────────────────────────────────────────────────

    async def ping(self) -> dict:
        """健康检查。"""
        resp = await self._call_with_retry(
            lambda timeout: self._stub.Ping(
                pb.PingRequest(client_id="python"),
                timeout=min(timeout, 5.0),
            )
        )
        return {
            "status": "ok",
            "node_count": resp.node_count,
            "edge_count": resp.edge_count,
            "uptime_seconds": resp.uptime_seconds,
        }

    async def compute_pagerank(
        self,
        iterations: int = 100,
        damping: float = 0.85,
        convergence: float = 1e-6,
    ) -> dict:
        """计算 PageRank (一元调用)。

        Returns:
            {"status": "ok", "time_ms": N, "data": [{"node": ..., "score": ...}, ...]}
        """
        request_id = str(uuid.uuid4())
        resp = await self._call_with_retry(
            lambda timeout: self._stub.ComputePageRank(
                pb.PageRankRequest(
                    request_id=request_id,
                    max_iterations=iterations,
                    damping_factor=damping,
                    convergence_threshold=convergence,
                    deadline_ms=int(timeout * 1000),
                ),
                timeout=timeout,
            )
        )
        return self._scoring_response_to_dict(resp)

    async def compute_pagerank_stream(
        self,
        iterations: int = 100,
        damping: float = 0.85,
        convergence: float = 1e-6,
    ) -> AsyncIterator[dict]:
        """计算 PageRank (流式调用)。

        每次迭代返回 top-100 节点的当前 PageRank 值。
        """
        request_id = str(uuid.uuid4())
        call = self._stub.ComputePageRankStream(
            pb.PageRankRequest(
                request_id=request_id,
                max_iterations=iterations,
                damping_factor=damping,
                convergence_threshold=convergence,
            )
        )
        async for chunk in call:
            yield self._scoring_chunk_to_dict(chunk)

    async def compute_betweenness(self, sample_ratio: float = 1.0) -> dict:
        """计算 Betweenness Centrality (一元调用)。

        Args:
            sample_ratio: 顶点采样比例 (0.01-1.0)，大图建议 0.01-0.1
        """
        request_id = str(uuid.uuid4())
        resp = await self._call_with_retry(
            lambda timeout: self._stub.ComputeBetweenness(
                pb.BetweennessRequest(
                    request_id=request_id,
                    sample_ratio=sample_ratio,
                    deadline_ms=int(timeout * 1000),
                ),
                timeout=timeout,
            )
        )
        return self._scoring_response_to_dict(resp)

    async def compute_betweenness_stream(self, sample_ratio: float = 1.0) -> AsyncIterator[dict]:
        """计算 Betweenness (流式调用)。

        每处理 10 个源节点输出一次中间结果。
        """
        request_id = str(uuid.uuid4())
        call = self._stub.ComputeBetweennessStream(
            pb.BetweennessRequest(
                request_id=request_id,
                sample_ratio=sample_ratio,
            )
        )
        async for chunk in call:
            yield self._scoring_chunk_to_dict(chunk)

    async def compute_community(self, max_iterations: int = 10) -> dict:
        """LPA 社区发现 (一元调用)。"""
        request_id = str(uuid.uuid4())
        resp = await self._call_with_retry(
            lambda timeout: self._stub.ComputeCommunity(
                pb.CommunityRequest(
                    request_id=request_id,
                    max_iterations=max_iterations,
                    deadline_ms=int(timeout * 1000),
                ),
                timeout=timeout,
            )
        )
        return self._community_response_to_dict(resp)

    async def compute_community_stream(self, max_iterations: int = 10) -> AsyncIterator[dict]:
        """LPA 社区发现 (流式调用)。"""
        request_id = str(uuid.uuid4())
        call = self._stub.ComputeCommunityStream(
            pb.CommunityRequest(
                request_id=request_id,
                max_iterations=max_iterations,
            )
        )
        async for chunk in call:
            yield self._community_chunk_to_dict(chunk)

    async def compute_connected_components(self) -> dict:
        """连通分量分析。"""
        request_id = str(uuid.uuid4())
        resp = await self._call_with_retry(
            lambda timeout: self._stub.ComputeConnectedComponents(
                pb.ConnectedComponentsRequest(
                    request_id=request_id,
                    deadline_ms=int(timeout * 1000),
                ),
                timeout=timeout,
            )
        )
        return {
            "status": "ok" if resp.status == "ok" else "error",
            "time_ms": resp.time_ms,
            "component_count": resp.component_count,
            "component_sizes": dict(resp.component_sizes),
            "data": [
                {"node": e.node_id, "component": e.community_id}
                for e in resp.data
            ],
        }

    async def compute_kcore(self) -> dict:
        """K-Core 分解。"""
        request_id = str(uuid.uuid4())
        resp = await self._call_with_retry(
            lambda timeout: self._stub.ComputeKCore(
                pb.KCoreRequest(
                    request_id=request_id,
                    deadline_ms=int(timeout * 1000),
                ),
                timeout=timeout,
            )
        )
        return self._scoring_response_to_dict(resp)

    async def compute_clustering_coeff(self) -> dict:
        """聚类系数。"""
        request_id = str(uuid.uuid4())
        resp = await self._call_with_retry(
            lambda timeout: self._stub.ComputeClusteringCoeff(
                pb.ClusteringCoeffRequest(
                    request_id=request_id,
                    deadline_ms=int(timeout * 1000),
                ),
                timeout=timeout,
            )
        )
        return self._scoring_response_to_dict(resp)

    async def compute_graph_stats(self) -> dict:
        """图统计。"""
        request_id = str(uuid.uuid4())
        resp = await self._call_with_retry(
            lambda timeout: self._stub.ComputeGraphStats(
                pb.GraphStatsRequest(request_id=request_id),
                timeout=timeout,
            )
        )
        return {
            "status": "ok" if resp.status == "ok" else "error",
            "time_ms": resp.time_ms,
            "node_count": resp.node_count,
            "edge_count": resp.edge_count,
            "density": resp.density,
            "avg_degree": resp.avg_degree,
            "max_degree": resp.max_degree,
            "avg_clustering": resp.avg_clustering,
        }

    async def get_full_graph(self) -> dict:
        """全网拓扑。"""
        request_id = str(uuid.uuid4())
        resp = await self._call_with_retry(
            lambda timeout: self._stub.GetFullGraph(
                pb.FullGraphRequest(
                    request_id=request_id,
                    deadline_ms=int(timeout * 1000),
                ),
                timeout=timeout,
            )
        )
        return {
            "status": "ok" if resp.status == "ok" else "error",
            "time_ms": resp.time_ms,
            "nodes": [{"id": n.id} for n in resp.nodes],
            "links": [
                {"source": e.source, "target": e.target}
                for e in resp.edges
            ],
        }

    async def find_path(
        self,
        algorithm: str,
        start_node: str,
        target_node: str,
    ) -> dict:
        """路径查询。

        Args:
            algorithm: "bfs" | "dijkstra" | "dfs"
            start_node: 起始节点 ID
            target_node: 目标节点 ID

        Returns:
            {"status": "ok", "time_ms": N, "path": [...], "path_length": N}
        """
        request_id = str(uuid.uuid4())
        resp = await self._call_with_retry(
            lambda timeout: self._stub.FindPath(
                pb.PathRequest(
                    request_id=request_id,
                    algorithm=algorithm,
                    start_node=start_node,
                    target_node=target_node,
                    deadline_ms=int(timeout * 1000),
                ),
                timeout=timeout,
            )
        )
        return {
            "status": "ok" if resp.status == "ok" else "error",
            "time_ms": resp.time_ms,
            "path": list(resp.path),
            "path_length": resp.path_length,
            "error_code": resp.error_code,
            "error_message": resp.error_message,
        }

    # ── 管理接口 ─────────────────────────────────────────────────

    async def reload_graph(self, data_file: str = "") -> dict:
        """热重载图数据。"""
        request_id = str(uuid.uuid4())
        resp = await self._call_with_retry(
            lambda timeout: self._stub.ReloadGraph(
                pb.ReloadRequest(
                    request_id=request_id,
                    data_file_path=data_file,
                ),
                timeout=10.0,
            )
        )
        return {
            "status": resp.status,
            "node_count": resp.node_count,
            "edge_count": resp.edge_count,
        }

    async def shutdown_server(self) -> dict:
        """发送关闭信号。"""
        request_id = str(uuid.uuid4())
        resp = await self._call_with_retry(
            lambda timeout: self._stub.Shutdown(
                pb.ShutdownRequest(request_id=request_id),
                timeout=5.0,
            )
        )
        return {"status": resp.status}

    # ── 结果转换辅助 ─────────────────────────────────────────────

    @staticmethod
    def _scoring_response_to_dict(resp) -> dict:
        """将 ScoringResponse 转换为与现有 API 兼容的 dict。"""
        return {
            "status": "ok" if resp.status == "ok" else "error",
            "time_ms": resp.time_ms,
            "data": [
                {"node": e.node_id, "score": e.score}
                for e in resp.data
            ],
            "total_nodes": resp.total_nodes,
            "error_code": resp.error_code,
            "error_message": resp.error_message,
        }

    @staticmethod
    def _scoring_chunk_to_dict(chunk) -> dict:
        return {
            "request_id": chunk.request_id,
            "chunk_index": chunk.chunk_index,
            "is_last": chunk.is_last,
            "data": [
                {"node": e.node_id, "score": e.score}
                for e in chunk.data
            ],
        }

    @staticmethod
    def _community_response_to_dict(resp) -> dict:
        return {
            "status": "ok" if resp.status == "ok" else "error",
            "time_ms": resp.time_ms,
            "data": [
                {"node": e.node_id, "community": e.community_id}
                for e in resp.data
            ],
            "community_count": resp.community_count,
            "total_nodes": resp.total_nodes,
        }

    @staticmethod
    def _community_chunk_to_dict(chunk) -> dict:
        return {
            "request_id": chunk.request_id,
            "chunk_index": chunk.chunk_index,
            "is_last": chunk.is_last,
            "data": [
                {"node": e.node_id, "community": e.community_id}
                for e in chunk.data
            ],
        }


# ═══════════════════════════════════════════════════════════════════════════
# 全局单例 (与现有 get_redis_async() 风格一致)
# ═══════════════════════════════════════════════════════════════════════════

_global_grpc_client: Optional[CppGrpcClient] = None
_grpc_init_lock = asyncio.Lock()


async def get_grpc_client() -> Optional[CppGrpcClient]:
    """获取全局 gRPC 客户端单例 (lazy-connect)。

    Returns:
        CppGrpcClient 或 None (连接失败时)
    """
    global _global_grpc_client

    if _global_grpc_client is not None and _global_grpc_client.is_connected():
        return _global_grpc_client

    async with _grpc_init_lock:
        if _global_grpc_client is not None and _global_grpc_client.is_connected():
            return _global_grpc_client

        try:
            client = CppGrpcClient()
            if await client.connect():
                _global_grpc_client = client
                return client
        except Exception as e:
            logger.warning("gRPC 客户端初始化失败: %s", e)

    return None


async def close_grpc_client():
    """关闭全局 gRPC 客户端。"""
    global _global_grpc_client
    if _global_grpc_client:
        await _global_grpc_client.close()
        _global_grpc_client = None


# ═══════════════════════════════════════════════════════════════════════════
# 桥接函数: 兼容现有 execute_command() API
# ═══════════════════════════════════════════════════════════════════════════

async def execute_via_grpc(command: str, *args: str, timeout: float = 60.0) -> dict:
    """通过 gRPC 执行 C++ 算法 (兼容现有 execute_command 签名)。

    如果 gRPC 客户端不可用，回退到原有的子进程调用。

    Args:
        command: 算法命令 ("pagerank", "community", "shortest_path", ...)
        *args:   命令参数
        timeout: 超时 (秒)

    Returns:
        {"status": "ok"/"error", "time_ms": N, "data": [...]}
    """
    client = await get_grpc_client()
    if client is None:
        # 回退到原有子进程调用
        logger.debug("gRPC 不可用，回退到子进程调用")
        from services.cpp_engine import execute_command as execute_via_subprocess
        return await execute_via_subprocess(command, *args, timeout=timeout)

    try:
        cmd = command.lower()

        if cmd == "pagerank":
            return await client.compute_pagerank()

        elif cmd == "community":
            return await client.compute_community()

        elif cmd == "betweenness":
            return await client.compute_betweenness()

        elif cmd == "connected_components":
            return await client.compute_connected_components()

        elif cmd == "kcore":
            return await client.compute_kcore()

        elif cmd == "clustering_coeff":
            return await client.compute_clustering_coeff()

        elif cmd == "graph_stats":
            return await client.compute_graph_stats()

        elif cmd == "get_full_graph":
            return await client.get_full_graph()

        elif cmd in ("shortest_path", "dijkstra_path", "echo_chamber"):
            algo_map = {
                "shortest_path": "bfs",
                "dijkstra_path": "dijkstra",
                "echo_chamber": "dfs",
            }
            if len(args) < 2:
                return {"status": "error", "message": f"路径查询需要2个参数, 收到了{len(args)}"}
            return await client.find_path(algo_map[cmd], args[0], args[1])

        else:
            return {"status": "error", "message": f"未知命令: {command}"}

    except TimeoutError:
        return {"status": "error", "message": f"gRPC 计算超时 ({timeout}s): {command}"}
    except ConnectionError as e:
        return {"status": "error", "message": str(e)}
    except NotImplementedError as e:
        return {"status": "error", "message": str(e)}
    except Exception as e:
        logger.error("gRPC 调用异常 (%s): %s", command, e)
        return {"status": "error", "message": f"C++ gRPC 执行失败: {e}"}
