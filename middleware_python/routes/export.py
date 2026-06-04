"""
SocialGraph Pro — 数据导出路由

端点:
  GET /api/v1/graph/export/{data_type}?format=csv|json

支持导出类型:
  - pagerank, community, betweenness, kcore, clustering_coeff, connected_components
  - topology (原始拓扑)
"""
import csv
import io
import json as json_module
import logging

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from core.dependencies import get_current_user
from core.exceptions import BadRequestError, NotFoundError
from services.cache import cache_get_or_compute
from services.cpp_engine import execute_command
from services.performance import log_operation
from core.config import get_settings

logger = logging.getLogger("socialgraph.routes.export")

router = APIRouter(prefix="/api/v1/graph/export", tags=["数据导出"])

# 支持的导出类型及其对应的 C++ 命令和缓存键
EXPORT_TYPES = {
    "pagerank": {"command": "pagerank", "cache_key": "social_graph:pagerank:v3"},
    "community": {"command": "community", "cache_key": "social_graph:community:v3"},
    "betweenness": {"command": "betweenness", "cache_key": "social_graph:betweenness:v1"},
    "kcore": {"command": "kcore", "cache_key": "social_graph:kcore:v1"},
    "clustering_coeff": {"command": "clustering_coeff", "cache_key": "social_graph:clustering:v1"},
    "connected_components": {"command": "connected_components", "cache_key": "social_graph:connected_components:v1"},
    "topology": {"command": "get_full_graph", "cache_key": "social_graph:topology:v7"},
}


@router.get("/{data_type}")
async def export_data(
    data_type: str,
    format: str = Query("csv", pattern="^(csv|json)$"),
    current_user: dict = Depends(get_current_user),
):
    """导出图计算结果为 CSV 或 JSON 文件。

    需要认证（任意角色）。
    """
    if data_type not in EXPORT_TYPES:
        raise NotFoundError(f"不支持的导出类型: {data_type}")

    config = EXPORT_TYPES[data_type]
    settings = get_settings()

    # 获取数据（优先缓存）
    data = await cache_get_or_compute(
        config["cache_key"],
        settings.cache_algorithm_ttl,
        execute_command, config["command"],
    )

    if data.get("status") != "success":
        raise BadRequestError("数据获取失败", detail={"error": data.get("message", "")})

    # 检查文件大小限制
    estimated_size = len(json_module.dumps(data)) * 2  # CSV 通常比 JSON 大
    if estimated_size > settings.export_max_file_size_bytes:
        raise BadRequestError(
            f"导出文件过大 (>{settings.export_max_file_size_bytes // 1048576}MB)，请缩小范围"
        )

    # 记录操作
    log_operation(
        "export_data",
        current_user["user_id"],
        data_type,
        details={"format": format},
    )

    if format == "csv":
        return _stream_csv(data, data_type)
    else:
        return _stream_json(data, data_type)


def _stream_csv(data: dict, data_type: str) -> StreamingResponse:
    """生成 CSV 流式响应。"""
    output = io.StringIO()
    writer = csv.writer(output)

    items = data.get("data", [])
    if items:
        # 写入表头
        if isinstance(items[0], dict):
            writer.writerow(items[0].keys())
            for item in items:
                writer.writerow(item.values())
        elif isinstance(items[0], list):
            for item in items:
                writer.writerow(item)
        else:
            writer.writerow(["value"])
            for item in items:
                writer.writerow([item])
    else:
        writer.writerow(["无数据"])

    output.seek(0)
    return StreamingResponse(
        output,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f"attachment; filename={data_type}.csv",
            "X-Content-Type-Options": "nosniff",
        },
    )


def _stream_json(data: dict, data_type: str) -> StreamingResponse:
    """生成 JSON 流式响应。"""
    output = io.StringIO()
    json_module.dump(data, output, ensure_ascii=False, indent=2)
    output.seek(0)
    return StreamingResponse(
        output,
        media_type="application/json; charset=utf-8",
        headers={
            "Content-Disposition": f"attachment; filename={data_type}.json",
            "X-Content-Type-Options": "nosniff",
        },
    )
