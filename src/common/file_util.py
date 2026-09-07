# -*- coding: utf-8 -*-
"""
文件工具模块。

核心原则（项目书 6.3 严禁自动覆盖）：
    存在则不处理；不存在才创建。
    已存在的文件绝不删除、不清空、不重新生成、不恢复默认值、不覆盖用户内容。
"""

import os
import tempfile
from pathlib import Path
from typing import Callable

from .errors import RadiusTestError


def ensure_dir(path: Path) -> Path:
    """确保目录存在（存在则跳过）。"""
    os.makedirs(path, exist_ok=True)
    return path


def exists(path: Path) -> bool:
    """判断文件是否存在且为文件。"""
    return path.is_file()


def create_if_missing(path: Path, content_provider: Callable[[], str]) -> bool:
    """
    文件不存在时创建并写入内容，存在时直接返回。

    参数：
        path: 目标文件路径
        content_provider: 无参回调函数，返回要写入的文本内容

    返回：
        True 表示本次创建了文件，False 表示文件已存在未做处理。
    """
    if path.is_file():
        return False
    ensure_dir(path.parent)
    content = content_provider()
    write_text_atomic(path, content)
    return True


def write_text_atomic(path: Path, content: str, encoding: str = "utf-8") -> None:
    """
    原子写入文本文件。

    先写临时文件再替换，避免写入过程中程序异常退出导致文件损坏。
    """
    ensure_dir(path.parent)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp_", suffix=".part")
    try:
        with os.fdopen(fd, "w", encoding=encoding, newline="") as f:
            f.write(content)
        os.replace(tmp_name, path)
    except Exception:
        if os.path.exists(tmp_name):
            os.remove(tmp_name)
        raise


def read_text(path: Path, encoding: str = "utf-8") -> str:
    """读取文本文件内容。"""
    with open(path, "r", encoding=encoding) as f:
        return f.read()


def read_bytes(path: Path) -> bytes:
    """读取二进制文件内容。"""
    with open(path, "rb") as f:
        return f.read()


def write_bytes_atomic(path: Path, data: bytes) -> None:
    """原子写入二进制文件。"""
    ensure_dir(path.parent)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp_", suffix=".part")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp_name, path)
    except Exception:
        if os.path.exists(tmp_name):
            os.remove(tmp_name)
        raise


def file_size(path: Path) -> int:
    """返回文件大小（字节），文件不存在返回 0。"""
    if not path.is_file():
        return 0
    return path.stat().st_size


def safe_remove(path: Path) -> bool:
    """删除文件，不存在或删除失败返回 False。"""
    try:
        if path.is_file():
            path.unlink()
            return True
    except OSError:
        pass
    return False


def load_optional(path: Path, encoding: str = "utf-8") -> str:
    """读取可选文件；文件不存在返回空字符串。"""
    if not path.is_file():
        return ""
    try:
        return read_text(path, encoding)
    except RadiusTestError:
        return ""
