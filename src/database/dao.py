# -*- coding: utf-8 -*-
"""
数据访问模块。

职责：
    1. 提供测试会话、测试结果、报文、属性的写入接口（走异步写队列）；
    2. 提供结果查询接口，支持筛选、排序与分页；
    3. 提供测试详情查询（含请求/响应报文与属性匹配结果）。

说明：
    写入走 AsyncDatabaseWriter，不阻塞事件循环；
    查询使用独立只读连接，在线程执行器中执行。
"""

import sqlite3
import threading
from typing import Any, Dict, List, Optional, Tuple

from ..common import paths
from ..logging import logger
from . import schema
from .writer import AsyncDatabaseWriter

# 允许参与排序的结果字段，防止 SQL 注入
SORTABLE_FIELDS = {
    "username": "username",
    "server": "server",
    "test_time": "test_time",
    "online": "online",
    "success": "success",
    "status": "status",
    "response_time": "response_time",
    "id": "id",
}

_writer: Optional[AsyncDatabaseWriter] = None
_read_connection: Optional[sqlite3.Connection] = None

# 报文 ID 预分配器。
# 存在原因：写入走异步批量队列，无法立即取到自增 ID，
# 而属性表必须引用报文 ID；若改为「写入后回查」会与批量提交产生竞态，
# 导致属性全部丢失。因此由本模块在内存中顺序分配 ID。
_id_lock = threading.Lock()
_next_packet_id: Optional[int] = None


def _ensure_packet_id_counter() -> None:
    """初始化报文 ID 计数器，初始值为当前表内最大 ID + 1。"""
    global _next_packet_id
    if _next_packet_id is not None:
        return
    connection = _get_read_connection()
    cursor = connection.execute("SELECT COALESCE(MAX(id), 0) FROM radius_packets")
    row = cursor.fetchone()
    cursor.close()
    _next_packet_id = int(row[0]) + 1


def allocate_packet_ids(count: int = 1) -> List[int]:
    """
    预分配若干个报文 ID。

    参数：
        count: 需要的 ID 数量

    返回：
        ID 列表，按升序排列。
    """
    global _next_packet_id
    with _id_lock:
        _ensure_packet_id_counter()
        start = _next_packet_id
        _next_packet_id += max(1, int(count))
        return list(range(start, _next_packet_id))


def init(db_path: str = None) -> None:
    """
    初始化数据库。

    参数：
        db_path: 数据库路径，默认取 data/results.db
    """
    global _writer, _read_connection
    if _writer is not None:
        return
    path = db_path or str(paths.db_path())
    connection = sqlite3.connect(path, check_same_thread=False)
    schema.apply_pragmas(connection)
    schema.create_tables(connection)
    connection.close()
    _writer = AsyncDatabaseWriter(path)
    _writer.start()
    _read_connection = sqlite3.connect(path, check_same_thread=False)
    _read_connection.row_factory = sqlite3.Row
    schema.apply_pragmas(_read_connection)
    logger.info("database", "数据库已初始化", {"path": path})


def shutdown() -> None:
    """关闭数据库。"""
    global _writer, _read_connection
    if _writer is not None:
        _writer.stop()
        _writer = None
    if _read_connection is not None:
        try:
            _read_connection.close()
        except Exception:
            pass
        _read_connection = None


def _get_writer() -> AsyncDatabaseWriter:
    """获取写入器，未初始化时先初始化。"""
    global _writer
    if _writer is None:
        init()
    return _writer


def _get_read_connection() -> sqlite3.Connection:
    """获取只读连接，未初始化时先初始化。"""
    global _read_connection
    if _read_connection is None:
        init()
    return _read_connection


# ---------------- 写入 ----------------

def save_session(session: Dict[str, Any]) -> None:
    """写入测试会话记录。"""
    _get_writer().submit(
        "INSERT OR REPLACE INTO test_sessions "
        "(task_id, start_time, end_time, server, protocol, status, stop_reason, concurrency, rate) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            session.get("task_id", ""),
            session.get("start_time", ""),
            session.get("end_time", ""),
            session.get("server", ""),
            session.get("protocol", ""),
            session.get("status", ""),
            session.get("stop_reason", ""),
            session.get("concurrency", 0),
            session.get("rate", 0),
        ),
    )


def save_result(result: Dict[str, Any]) -> None:
    """写入单条测试结果。"""
    _get_writer().submit(
        "INSERT INTO test_results "
        "(task_id, username, server, test_time, online, success, status, response_time, error) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            result.get("task_id", ""),
            result.get("username", ""),
            result.get("server", ""),
            result.get("test_time", ""),
            1 if result.get("online") else 0,
            1 if result.get("success") else 0,
            result.get("status", ""),
            result.get("response_time", 0.0),
            result.get("error", ""),
        ),
    )


def save_packet(packet: Dict[str, Any], packet_id: int = None) -> int:
    """
    写入单条报文明细。

    参数：
        packet: 报文字段字典
        packet_id: 指定报文 ID，未提供时自动预分配

    返回：
        写入使用的报文 ID，供属性表引用。
    """
    if packet_id is None:
        packet_id = allocate_packet_ids(1)[0]
    _get_writer().submit(
        "INSERT INTO radius_packets "
        "(id, task_id, username, server, packet_type, packet_time, raw_packet, "
        "parse_status, parse_error) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            packet_id,
            packet.get("task_id", ""),
            packet.get("username", ""),
            packet.get("server", ""),
            packet.get("packet_type", ""),
            packet.get("packet_time", ""),
            packet.get("raw_packet", ""),
            packet.get("parse_status", ""),
            packet.get("parse_error", ""),
        ),
    )
    return packet_id


def save_attributes(attributes: List[Dict[str, Any]]) -> None:
    """批量写入属性解析结果。"""
    if not attributes:
        return
    tasks = []
    for attribute in attributes:
        tasks.append((
            "INSERT INTO radius_attributes "
            "(packet_id, attribute_id, radius_template, name, name_zh, type, value, vendor_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                attribute.get("packet_id", 0),
                attribute.get("attribute_id", 0),
                attribute.get("radius_template", ""),
                attribute.get("name", ""),
                attribute.get("name_zh", ""),
                attribute.get("type", ""),
                attribute.get("value", ""),
                attribute.get("vendor_id"),
            ),
        ))
    _get_writer().submit_many(tasks)


def stats() -> Dict[str, int]:
    """返回写入器统计信息。"""
    writer = _get_writer()
    return {
        "pending": writer.pending,
        "written": writer.written,
        "dropped": writer.dropped,
    }


# ---------------- 查询 ----------------

def _build_filters(filters: Dict[str, Any]) -> Tuple[str, list]:
    """
    构造查询条件。

    参数：
        filters: 筛选条件字典，支持 username / server / status / online / success / task_id。
                 单字段可传入列表，表示多选（SQL IN）。

    返回：
        (WHERE 子句, 参数列表)
    """
    clauses = []
    params = []

    def add_equal(column: str, value) -> None:
        """按取值类型追加等值或 IN 条件。"""
        if value is None or value == "":
            return
        if isinstance(value, (list, tuple)):
            values = [v for v in value if v not in (None, "")]
            if not values:
                return
            placeholders = ", ".join("?" for _ in values)
            clauses.append("%s IN (%s)" % (column, placeholders))
            params.extend(values)
        else:
            clauses.append("%s = ?" % column)
            params.append(value)

    add_equal("task_id", filters.get("task_id"))
    add_equal("username", filters.get("username"))
    add_equal("server", filters.get("server"))
    add_equal("status", filters.get("status"))
    online = filters.get("online")
    if online is not None and online != "":
        if isinstance(online, (list, tuple)):
            values = [1 if str(v) in ("1", "true", "True", "在线") else 0 for v in online]
            placeholders = ", ".join("?" for _ in values)
            clauses.append("online IN (%s)" % placeholders)
            params.extend(values)
        else:
            clauses.append("online = ?")
            params.append(1 if str(online) in ("1", "true", "True", "在线") else 0)
    success = filters.get("success")
    if success is not None and success != "":
        if isinstance(success, (list, tuple)):
            values = [1 if str(v) in ("1", "true", "True", "成功") else 0 for v in success]
            placeholders = ", ".join("?" for _ in values)
            clauses.append("success IN (%s)" % placeholders)
            params.extend(values)
        else:
            clauses.append("success = ?")
            params.append(1 if str(success) in ("1", "true", "True", "成功") else 0)
    time_from = filters.get("time_from")
    if time_from:
        clauses.append("test_time >= ?")
        params.append(time_from)
    time_to = filters.get("time_to")
    if time_to:
        clauses.append("test_time <= ?")
        params.append(time_to)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    return where, params


def count_results(filters: Dict[str, Any]) -> int:
    """统计符合条件的测试结果数量。"""
    where, params = _build_filters(filters)
    connection = _get_read_connection()
    cursor = connection.execute("SELECT COUNT(*) AS total FROM test_results" + where, params)
    row = cursor.fetchone()
    cursor.close()
    return int(row["total"]) if row else 0


def query_results(filters: Dict[str, Any], sort_field: str = "test_time",
                  sort_order: str = "desc", page: int = 1,
                  page_size: int = 10) -> List[Dict[str, Any]]:
    """
    分页查询测试结果。

    参数：
        filters: 筛选条件
        sort_field: 排序字段，必须在 SORTABLE_FIELDS 中
        sort_order: asc / desc
        page: 页码，从 1 开始
        page_size: 每页条数

    返回：
        结果字典列表。
    """
    where, params = _build_filters(filters)
    column = SORTABLE_FIELDS.get(sort_field, "test_time")
    order = "DESC" if str(sort_order).lower() == "desc" else "ASC"
    limit = max(1, min(int(page_size), 1000))
    offset = max(0, (max(1, int(page)) - 1) * limit)
    sql = (
        "SELECT id, task_id, username, server, test_time, online, success, status, "
        "response_time, error FROM test_results"
        + where
        + " ORDER BY %s %s, id %s LIMIT ? OFFSET ?" % (column, order, order)
    )
    connection = _get_read_connection()
    cursor = connection.execute(sql, params + [limit, offset])
    rows = cursor.fetchall()
    cursor.close()
    return [dict(row) for row in rows]


def distinct_values(field: str, filters: Dict[str, Any] = None) -> List[dict]:
    """
    获取某字段的去重取值与出现次数，供筛选面板使用。

    参数：
        field: 字段名，必须在 SORTABLE_FIELDS 中
        filters: 其他字段的筛选条件，用于筛选联动

    返回：
        [{"value": 取值, "count": 出现次数}]，
        供前端实现「重复项」（count > 1）与「唯一项」（count == 1）。
    """
    column = SORTABLE_FIELDS.get(field)
    if not column:
        return []
    where, params = _build_filters(filters or {})
    connection = _get_read_connection()
    cursor = connection.execute(
        "SELECT %s AS value, COUNT(*) AS cnt FROM test_results%s "
        "GROUP BY %s ORDER BY value" % (column, where, column),
        params,
    )
    rows = cursor.fetchall()
    cursor.close()
    return [
        {"value": str(row["value"]), "count": int(row["cnt"])}
        for row in rows if row["value"] is not None
    ]


def get_result_detail(result_id: int) -> Optional[Dict[str, Any]]:
    """
    查询单条测试结果详情，含报文与属性。

    参数：
        result_id: test_results.id

    返回：
        详情字典；不存在时返回 None。
    """
    connection = _get_read_connection()
    cursor = connection.execute(
        "SELECT id, task_id, username, server, test_time, online, success, status, "
        "response_time, error FROM test_results WHERE id = ?",
        (result_id,),
    )
    row = cursor.fetchone()
    cursor.close()
    if row is None:
        return None
    detail = dict(row)
    cursor = connection.execute(
        "SELECT id, packet_type, packet_time, raw_packet, parse_status, parse_error "
        "FROM radius_packets WHERE task_id = ? AND username = ? ORDER BY id",
        (detail["task_id"], detail["username"]),
    )
    packets = [dict(r) for r in cursor.fetchall()]
    cursor.close()
    for packet in packets:
        cursor = connection.execute(
            "SELECT attribute_id, radius_template, name, name_zh, type, value, vendor_id "
            "FROM radius_attributes WHERE packet_id = ? ORDER BY id",
            (packet["id"],),
        )
        packet["attributes"] = [dict(r) for r in cursor.fetchall()]
        cursor.close()
    detail["packets"] = packets
    cursor = connection.execute(
        "SELECT task_id, start_time, end_time, server, protocol, status, "
        "stop_reason, concurrency, rate FROM test_sessions WHERE task_id = ?",
        (detail["task_id"],),
    )
    session_row = cursor.fetchone()
    cursor.close()
    detail["session"] = dict(session_row) if session_row else {}
    return detail


def query_sessions(page: int = 1, page_size: int = 10) -> Tuple[List[Dict[str, Any]], int]:
    """
    分页查询测试会话。

    返回：
        (会话列表, 总数)
    """
    connection = _get_read_connection()
    cursor = connection.execute("SELECT COUNT(*) AS total FROM test_sessions")
    row = cursor.fetchone()
    total = int(row["total"]) if row else 0
    cursor.close()
    limit = max(1, min(int(page_size), 1000))
    offset = max(0, (max(1, int(page)) - 1) * limit)
    cursor = connection.execute(
        "SELECT task_id, start_time, end_time, server, protocol, status, "
        "stop_reason, concurrency, rate FROM test_sessions "
        "ORDER BY start_time DESC, task_id DESC LIMIT ? OFFSET ?",
        (limit, offset),
    )
    rows = [dict(r) for r in cursor.fetchall()]
    cursor.close()
    return rows, total


def get_session(task_id: str) -> Optional[Dict[str, Any]]:
    """查询单个测试会话。"""
    connection = _get_read_connection()
    cursor = connection.execute(
        "SELECT task_id, start_time, end_time, server, protocol, status, "
        "stop_reason, concurrency, rate FROM test_sessions WHERE task_id = ?",
        (task_id,),
    )
    row = cursor.fetchone()
    cursor.close()
    return dict(row) if row else None


def query_packets(filters: Dict[str, Any], page: int = 1,
                  page_size: int = 10) -> Tuple[List[Dict[str, Any]], int]:
    """
    分页查询报文记录，供 RADIUS 解析页面使用。

    返回：
        (报文列表, 总数)
    """
    clauses = []
    params = []
    for field in ("task_id", "username", "server", "packet_type"):
        value = filters.get(field)
        if value:
            clauses.append("%s = ?" % field)
            params.append(value)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    connection = _get_read_connection()
    cursor = connection.execute(
        "SELECT COUNT(*) AS total FROM radius_packets" + where, params
    )
    row = cursor.fetchone()
    total = int(row["total"]) if row else 0
    cursor.close()
    limit = max(1, min(int(page_size), 1000))
    offset = max(0, (max(1, int(page)) - 1) * limit)
    cursor = connection.execute(
        "SELECT id, task_id, username, server, packet_type, packet_time, "
        "parse_status, parse_error FROM radius_packets"
        + where
        + " ORDER BY id DESC LIMIT ? OFFSET ?",
        params + [limit, offset],
    )
    rows = [dict(r) for r in cursor.fetchall()]
    cursor.close()
    return rows, total


def get_packet_detail(packet_id: int) -> Optional[Dict[str, Any]]:
    """查询单个报文及其属性解析结果。"""
    connection = _get_read_connection()
    cursor = connection.execute(
        "SELECT id, task_id, username, server, packet_type, packet_time, "
        "raw_packet, parse_status, parse_error FROM radius_packets WHERE id = ?",
        (packet_id,),
    )
    row = cursor.fetchone()
    cursor.close()
    if row is None:
        return None
    detail = dict(row)
    cursor = connection.execute(
        "SELECT attribute_id, radius_template, name, name_zh, type, value, vendor_id "
        "FROM radius_attributes WHERE packet_id = ? ORDER BY id",
        (packet_id,),
    )
    detail["attributes"] = [dict(r) for r in cursor.fetchall()]
    cursor.close()
    return detail


def delete_single_test(username: str) -> None:
    """
    清理某个用户上一次的单次测试记录。

    说明：
        单次测试的任务 ID 以 UT- 开头（见 testing.single.SINGLE_TASK_PREFIX），
        据此与批量/性能测试任务区分，避免误删任务报文。
        删除与后续写入统一走异步写队列，保证「先清旧、再写新」的顺序。

    参数：
        username: 用户名
    """
    writer = _get_writer()
    writer.submit(
        "DELETE FROM radius_attributes WHERE packet_id IN "
        "(SELECT id FROM radius_packets WHERE task_id LIKE 'UT-%' AND username = ?)",
        (username,),
    )
    writer.submit(
        "DELETE FROM radius_packets WHERE task_id LIKE 'UT-%' AND username = ?",
        (username,),
    )
    writer.submit(
        "DELETE FROM test_results WHERE task_id LIKE 'UT-%' AND username = ?",
        (username,),
    )
    logger.debug("database", "已清理用户上一次单次测试记录", {"username": username})


def clear_results() -> None:
    """清空测试结果数据（保留表结构）。"""
    connection = _get_read_connection()
    cursor = connection.cursor()
    for table in ("test_results", "radius_packets", "radius_attributes", "test_sessions"):
        cursor.execute("DELETE FROM %s" % table)
    connection.commit()
    cursor.close()
    logger.info("database", "测试结果数据已清空", {})
