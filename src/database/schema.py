# -*- coding: utf-8 -*-
"""
数据库结构定义模块。

职责：
    定义 data/results.db 的全部数据表与索引。

数据表（项目书第 20 节）：
    test_sessions      测试任务
    test_results       每次测试结果
    radius_packets     RADIUS 报文
    radius_attributes  RADIUS 属性

要点：
    1. 使用 WAL 模式，读写不互斥；
    2. 只在表不存在时创建，绝不删除或重建已有表；
    3. 建表后补齐缺失索引，已有索引不受影响。
"""

from typing import List

# 版本标记，用于未来结构演进时判断是否需要迁移
SCHEMA_VERSION = 1

TABLES: List[str] = [
    """
    CREATE TABLE IF NOT EXISTS test_sessions (
        task_id        TEXT PRIMARY KEY,
        start_time     TEXT,
        end_time       TEXT,
        server         TEXT,
        protocol       TEXT,
        status         TEXT,
        stop_reason    TEXT,
        concurrency    INTEGER,
        rate           INTEGER
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS test_results (
        id             INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id        TEXT,
        username       TEXT,
        server         TEXT,
        test_time      TEXT,
        online         INTEGER DEFAULT 0,
        success        INTEGER DEFAULT 0,
        status         TEXT,
        response_time  REAL,
        error          TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS radius_packets (
        id             INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id        TEXT,
        username       TEXT,
        server         TEXT,
        packet_type    TEXT,
        packet_time    TEXT,
        raw_packet     TEXT,
        parse_status   TEXT,
        parse_error    TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS radius_attributes (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        packet_id        INTEGER,
        attribute_id     INTEGER,
        radius_template  TEXT,
        name             TEXT,
        name_zh          TEXT,
        type             TEXT,
        value            TEXT,
        vendor_id        INTEGER
    )
    """,
]

INDEXES: List[str] = [
    "CREATE INDEX IF NOT EXISTS idx_results_task ON test_results(task_id)",
    "CREATE INDEX IF NOT EXISTS idx_results_username ON test_results(username)",
    "CREATE INDEX IF NOT EXISTS idx_results_server ON test_results(server)",
    "CREATE INDEX IF NOT EXISTS idx_results_time ON test_results(test_time)",
    "CREATE INDEX IF NOT EXISTS idx_results_status ON test_results(status)",
    "CREATE INDEX IF NOT EXISTS idx_packets_task ON radius_packets(task_id)",
    "CREATE INDEX IF NOT EXISTS idx_packets_username ON radius_packets(username)",
    "CREATE INDEX IF NOT EXISTS idx_attributes_packet ON radius_attributes(packet_id)",
    "CREATE INDEX IF NOT EXISTS idx_sessions_time ON test_sessions(start_time)",
]

# WAL 相关 PRAGMA
PRAGMAS: List[str] = [
    "PRAGMA journal_mode=WAL",
    "PRAGMA synchronous=NORMAL",
    "PRAGMA temp_store=MEMORY",
    "PRAGMA busy_timeout=5000",
]


def apply_pragmas(connection) -> None:
    """应用性能相关 PRAGMA。"""
    cursor = connection.cursor()
    for pragma in PRAGMAS:
        try:
            cursor.execute(pragma)
        except Exception:
            pass
    cursor.close()


def create_tables(connection) -> None:
    """
    创建全部数据表与索引。

    说明：
        全部使用 IF NOT EXISTS，已存在的表与索引不会被修改。
    """
    cursor = connection.cursor()
    for statement in TABLES:
        cursor.execute(statement)
    for statement in INDEXES:
        cursor.execute(statement)
    connection.commit()
    cursor.close()
