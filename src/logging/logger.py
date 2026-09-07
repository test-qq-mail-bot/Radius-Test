# -*- coding: utf-8 -*-
"""
日志模块。

职责：
    提供全项目唯一的日志出口，同时输出到控制台与日志文件。

格式（项目书 22.2）：
    2026-08-29 00:00:01.123+08:00;level=INFO;module=test;message=测试任务开始;

要点：
    1. 只使用一个程序日志文件：log/日期-log.log；
    2. 日志必须包含时区信息；
    3. 日志详细程度通过日志等级控制，不设置独立 Debug 开关；
    4. 控制台输出与文件内容完全一致。
"""

import logging
import logging.handlers
import threading
from pathlib import Path
from typing import Optional

from ..common import paths
from ..common import time_util

# 允许在配置文件中使用的日志等级
LEVEL_NAMES = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")

_lock = threading.Lock()
_logger: Optional[logging.Logger] = None
_current_log_path: Optional[Path] = None
_console_handler: Optional[logging.Handler] = None
_file_handler: Optional[logging.Handler] = None


class RadiusFormatter(logging.Formatter):
    """RADIUS-Test 统一日志格式化器。"""

    def format(self, record: logging.LogRecord) -> str:
        timestamp = time_util.format_log_time()
        module = getattr(record, "module_name", None) or record.name
        # 消息中的换行替换为空格，保证单行一条日志
        message = record.getMessage().replace("\r", " ").replace("\n", " ")
        parts = [
            "time=%s" % timestamp,
            "level=%s" % record.levelname,
            "module=%s" % module,
            "message=%s" % message,
        ]
        # 结构化附加字段
        extra = getattr(record, "fields", None)
        if isinstance(extra, dict):
            for key, value in extra.items():
                parts.append("%s=%s" % (key, value))
        if record.exc_info:
            parts.append("exception=%s" % self.formatException(record.exc_info).replace("\n", " "))
        return ";".join(parts) + ";"


def _build_logger() -> logging.Logger:
    """构造 logger 实例，挂接控制台与文件处理器。"""
    global _logger, _console_handler, _file_handler, _current_log_path

    logger = logging.getLogger("radius-test")
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    for handler in list(logger.handlers):
        logger.removeHandler(handler)

    formatter = RadiusFormatter()

    console = logging.StreamHandler()
    console.setFormatter(formatter)
    console.setLevel(logging.DEBUG)
    logger.addHandler(console)
    _console_handler = console

    log_path = paths.log_dir() / time_util.log_file_name()
    paths.ensure_runtime_dirs()
    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.DEBUG)
    logger.addHandler(file_handler)
    _file_handler = file_handler
    _current_log_path = log_path

    return logger


def get_logger() -> logging.Logger:
    """获取全局 logger（首次调用时完成初始化）。"""
    global _logger
    if _logger is None:
        with _lock:
            if _logger is None:
                _logger = _build_logger()
    return _logger


def set_level(level_name: str) -> None:
    """
    设置日志等级。

    参数：
        level_name: DEBUG / INFO / WARNING / ERROR / CRITICAL，大小写不敏感。
    """
    name = (level_name or "INFO").upper()
    if name not in LEVEL_NAMES:
        name = "INFO"
    logger = get_logger()
    logger.setLevel(getattr(logging, name))
    if _console_handler is not None:
        _console_handler.setLevel(getattr(logging, name))
    if _file_handler is not None:
        _file_handler.setLevel(getattr(logging, name))


def is_debug_enabled() -> bool:
    """判断当前是否处于 DEBUG 等级（前端据此决定是否输出 Debug 信息）。"""
    return get_logger().isEnabledFor(logging.DEBUG)


def log_path() -> Path:
    """返回当前日志文件路径。"""
    get_logger()
    return _current_log_path


def _emit(level: int, module: str, message: str, fields: dict = None, exc_info=False) -> None:
    """统一日志出口。"""
    logger = get_logger()
    if not logger.isEnabledFor(level):
        return
    logger.log(
        level,
        message,
        extra={"module_name": module, "fields": fields or {}},
        exc_info=exc_info,
    )


def debug(module: str, message: str, fields: dict = None) -> None:
    """输出 DEBUG 级日志。"""
    _emit(logging.DEBUG, module, message, fields)


def info(module: str, message: str, fields: dict = None) -> None:
    """输出 INFO 级日志。"""
    _emit(logging.INFO, module, message, fields)


def warning(module: str, message: str, fields: dict = None) -> None:
    """输出 WARNING 级日志。"""
    _emit(logging.WARNING, module, message, fields)


def error(module: str, message: str, fields: dict = None, exc_info: bool = False) -> None:
    """输出 ERROR 级日志。"""
    _emit(logging.ERROR, module, message, fields, exc_info)


def critical(module: str, message: str, fields: dict = None, exc_info: bool = False) -> None:
    """输出 CRITICAL 级日志。"""
    _emit(logging.CRITICAL, module, message, fields, exc_info)
