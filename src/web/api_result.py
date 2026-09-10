# -*- coding: utf-8 -*-
"""
测试结果与报文查询接口模块。

提供：
    GET  /api/results              测试结果分页查询（支持筛选与排序）
    GET  /api/results/filters      筛选项去重取值（筛选联动）
    GET  /api/results/{id}         单条结果详情（含报文与属性）
    GET  /api/sessions             测试会话列表
    POST /api/results/clear        清空测试结果数据

说明：
    测试详情（/api/results/{id}）包含该用户最新的认证请求/响应报文与属性匹配结果。
"""

import asyncio
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query

from ..authorization import authz
from ..database import dao
from ..logging import logger

router = APIRouter(prefix="/api", tags=["results"])


def _attach_authorization(detail: dict) -> dict:
    """
    给详情补充「授权属性」分区数据。

    说明：
        详情只保留该用户最新的请求与响应报文，
        授权属性取自最新响应报文（Access-Accept）的属性解析结果，
        并按 隧道/VLAN、QoS 限速、安全组/ACL、会话控制、其它 分类分组。
    """
    response = None
    for packet in detail.get("packets") or []:
        if str(packet.get("packet_type") or "").startswith("response-"):
            response = packet
            break
    items = authz.from_rows((response or {}).get("attributes") or [])
    detail["authorization"] = items
    detail["authorization_groups"] = authz.group_items(items)
    return detail


def _run_in_thread(func, *args):
    """在线程执行器中执行同步 SQL 查询。"""
    loop = asyncio.get_event_loop()
    return loop.run_in_executor(None, func, *args)


@router.get("/results")
async def query_results(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=1000),
    sort_field: str = Query("test_time"),
    sort_order: str = Query("desc"),
    task_id: Optional[List[str]] = Query(None),
    username: Optional[List[str]] = Query(None),
    server: Optional[List[str]] = Query(None),
    status: Optional[List[str]] = Query(None),
    online: Optional[List[str]] = Query(None),
    success: Optional[List[str]] = Query(None),
    time_from: Optional[str] = Query(None),
    time_to: Optional[str] = Query(None),
):
    """
    分页查询测试结果。

    字段含义见《数据表格需求描述》：默认用户名升序、每页 10 条、
    支持字段排序、字段筛选、多重筛选联动与分页数量切换。
    """
    filters = {
        "task_id": task_id,
        "username": username,
        "server": server,
        "status": status,
        "online": online,
        "success": success,
        "time_from": time_from,
        "time_to": time_to,
    }
    filters = {k: v for k, v in filters.items() if v not in (None, "")}
    total = await _run_in_thread(dao.count_results, filters)
    rows = await _run_in_thread(
        dao.query_results, filters, sort_field, sort_order, page, page_size)
    return {
        "rows": rows,
        "total": total,
        "page": page,
        "page_size": page_size,
        "sort_field": sort_field,
        "sort_order": sort_order,
    }


@router.get("/results/filters")
async def result_filters(
    field: Optional[str] = Query(None),
    task_id: Optional[List[str]] = Query(None),
    username: Optional[List[str]] = Query(None),
    server: Optional[List[str]] = Query(None),
    status: Optional[List[str]] = Query(None),
    online: Optional[List[str]] = Query(None),
    success: Optional[List[str]] = Query(None),
    time_from: Optional[str] = Query(None),
    time_to: Optional[str] = Query(None),
):
    """
    返回字段去重取值与出现次数，供筛选面板使用。

    筛选联动：
        请求某字段的取值时，传入「除该字段以外」的其他筛选条件，
        返回基于当前结果集计算出的可选项与出现次数，
        使前端可以实现「重复项」与「唯一项」筛选。
    """
    pool = {
        "task_id": task_id,
        "username": username,
        "server": server,
        "status": status,
        "online": online,
        "success": success,
        "time_from": time_from,
        "time_to": time_to,
    }
    pool = {k: v for k, v in pool.items() if v not in (None, "", [])}
    if field:
        others = {k: v for k, v in pool.items() if k != field}
        values = await _run_in_thread(dao.distinct_values, field, others)
        return {"filters": {field: values}}
    fields = ["username", "server", "status", "online", "success"]
    values = {}
    for name in fields:
        others = {k: v for k, v in pool.items() if k != name}
        values[name] = await _run_in_thread(dao.distinct_values, name, others)
    return {"filters": values}


@router.get("/results/{result_id}")
async def result_detail(result_id: int):
    """
    查询单条测试结果详情。

    详情结构（项目书 21.1）：
        测试信息 -> RADIUS 请求报文 -> RADIUS 响应报文
        -> 报文解析结果 -> Radius 模板匹配结果
        -> 授权属性（按 VLAN / QoS / 安全组 / 会话控制 分组）
    """
    detail = await _run_in_thread(dao.get_result_detail, result_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="测试结果不存在")
    return _attach_authorization(detail)


@router.get("/sessions")
async def list_sessions(page: int = Query(1, ge=1), page_size: int = Query(10, ge=1, le=1000)):
    """分页查询测试会话。"""
    rows, total = await _run_in_thread(dao.query_sessions, page, page_size)
    return {"rows": rows, "total": total, "page": page, "page_size": page_size}


@router.post("/results/clear")
async def clear_results():
    """清空全部测试结果数据。"""
    await _run_in_thread(dao.clear_results)
    logger.info("api", "测试结果数据已通过接口清空", {})
    return {"success": True}
