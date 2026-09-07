# -*- coding: utf-8 -*-
"""
时间工具模块。

职责：
    提供带时区的统一时间格式，供后端日志与前端 Debug 共用。

格式规范（项目书 22.2）：
    2026-08-29 00:00:01.123+08:00
"""

from datetime import datetime, timedelta, timezone

# 日志时间戳格式：秒后三位毫秒 + 时区偏移
LOG_TIME_FORMAT = "%Y-%m-%d %H:%M:%S.%f"
LOG_FILE_NAME_FORMAT = "%Y%m%d"


def local_tz() -> timezone:
    """返回本机本地时区（带 UTC 偏移量的固定时区对象）。"""
    return datetime.now().astimezone().tzinfo


def now() -> datetime:
    """返回带本机时区信息的当前时间。"""
    return datetime.now().astimezone()


def utc_now() -> datetime:
    """返回带 UTC 时区信息的当前时间。"""
    return datetime.now(timezone.utc)


def format_log_time(dt: datetime = None) -> str:
    """
    格式化为日志时间戳。

    输出示例：2026-08-29 00:00:01.123+08:00
    """
    if dt is None:
        dt = now()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=local_tz())
    base = dt.strftime(LOG_TIME_FORMAT)[:-3]  # %f 为 6 位微秒，截取前 3 位得毫秒
    offset = dt.strftime("%z")
    if offset:
        offset = offset[:3] + ":" + offset[3:]
    return base + offset


def format_display(dt: datetime = None) -> str:
    """
    格式化为页面展示时间。

    输出示例：2026-08-29 00:00:01
    """
    if dt is None:
        dt = now()
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def log_file_name(dt: datetime = None) -> str:
    """
    返回日志文件名。

    输出示例：20260829-log.log
    """
    if dt is None:
        dt = now()
    return dt.strftime(LOG_FILE_NAME_FORMAT) + "-log.log"


def timestamp_ms(dt: datetime = None) -> int:
    """返回毫秒级 Unix 时间戳，用于响应时间统计。"""
    if dt is None:
        dt = now()
    return int(dt.timestamp() * 1000)


def elapsed_ms(start: datetime, end: datetime = None) -> float:
    """计算两个时间点之间的毫秒差。"""
    if end is None:
        end = now()
    return (end - start).total_seconds() * 1000.0


def sleep_deadline(seconds: float) -> datetime:
    """根据秒数计算超时截止时刻。"""
    return now() + timedelta(seconds=seconds)
