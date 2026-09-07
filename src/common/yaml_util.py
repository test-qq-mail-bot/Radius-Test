# -*- coding: utf-8 -*-
"""
YAML 工具模块。

职责：
    封装 PyYAML 的安全读写，统一错误处理与中文输出。

说明：
    全部读取使用 yaml.safe_load，禁止执行任意 Python 对象构造。
"""

from pathlib import Path
from typing import Any, Dict

import yaml

from .errors import ConfigError, DictionaryError


def load_yaml(path: Path, error_cls=ConfigError) -> Dict[str, Any]:
    """
    安全加载 YAML 文件。

    参数：
        path: 文件路径
        error_cls: 解析失败时抛出的异常类型

    返回：
        解析后的字典；文件内容为空时返回空字典。
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as exc:
        raise error_cls("YAML 解析失败", "文件=%s；原因=%s" % (path, exc))
    except OSError as exc:
        raise error_cls("YAML 读取失败", "文件=%s；原因=%s" % (path, exc))
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise error_cls("YAML 根节点必须是字典", "文件=%s" % path)
    return data


def load_yaml_text(text: str, error_cls=DictionaryError) -> Dict[str, Any]:
    """
    安全解析 YAML 文本。

    用于解析用户上传的自定义 Dictionary 内容。
    """
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise error_cls("YAML 解析失败", "原因=%s" % exc)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise error_cls("YAML 根节点必须是字典", "实际类型=%s" % type(data).__name__)
    return data


def dump_yaml(data: Dict[str, Any], path: Path = None, sort_keys: bool = False) -> str:
    """
    序列化为 YAML 文本；传入 path 时同步原子写入文件。

    参数：
        data: 待序列化数据
        path: 可选，目标文件路径
        sort_keys: 是否按键排序

    返回：
        序列化后的 YAML 文本。
    """
    text = yaml.safe_dump(
        data,
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=sort_keys,
        indent=2,
    )
    if path is not None:
        from . import file_util

        file_util.write_text_atomic(path, text)
    return text


def deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """
    深度合并两个字典，override 覆盖 base。

    用于「默认配置 + config.yaml」的合并，只有默认配置中已定义的键才会被合并。
    """
    result = dict(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result
