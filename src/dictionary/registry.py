# -*- coding: utf-8 -*-
"""
模板登记模块。

职责：
    维护 data/radius.yaml，登记当前可用的 Radius 模板。

流程（项目书 18.3）：
    程序启动
        -> 读取 radius.yaml
        -> 扫描 data/dictionaries
        -> YAML 合法则加载模板
        -> 补充 radius.yaml 中的模板登记

规则：
    1. radius.yaml 不存在时自动生成；
    2. 已存在时只增加缺失的合法模板登记，
       不删除、不清空、不覆盖用户已有内容；
    3. 不增加「是否已经登记」的人工确认步骤。
"""

from typing import List

from ..common import file_util, paths
from ..common import yaml_util
from ..logging import logger

# radius.yaml 初始模板
RADIUS_YAML_TEMPLATE = (
    "# Radius-Test Radius 模板登记文件\n"
    "#\n"
    "# 本文件登记当前可用的 Radius Dictionary 模板。\n"
    "# 程序启动时自动补充缺失的模板登记，不会删除或覆盖已有内容。\n"
    "\n"
    "templates: []\n"
)


def ensure_registry_file() -> bool:
    """
    确保 radius.yaml 存在。

    返回：
        True 表示本次创建了文件。
    """
    return file_util.create_if_missing(
        paths.radius_yaml_path(),
        lambda: RADIUS_YAML_TEMPLATE,
    )


def read_registry() -> List[dict]:
    """
    读取已登记的模板列表。

    返回：
        登记项列表，每项为字典；读取失败时返回空列表。
    """
    if not paths.radius_yaml_path().is_file():
        return []
    try:
        data = yaml_util.load_yaml(paths.radius_yaml_path())
    except Exception as exc:
        logger.warning("dictionary", "radius.yaml 解析失败，按空登记处理", {
            "error": str(exc),
        })
        return []
    templates = data.get("templates")
    if not isinstance(templates, list):
        return []
    return [item for item in templates if isinstance(item, dict)]


def _key_of(item: dict) -> str:
    """取登记项的唯一键（模板名称）。"""
    return str(item.get("name") or "").strip()


def sync_registry(templates: List[dict]) -> int:
    """
    同步模板登记。

    参数：
        templates: 当前加载成功的模板摘要列表，
                   每项需含 name / source / vendor_id / attribute_count / file

    返回：
        本次新增的登记数量。

    说明：
        只增加缺失的登记项，已有条目原样保留。
    """
    ensure_registry_file()
    existing = read_registry()
    known = {_key_of(item) for item in existing}
    added = 0
    merged = list(existing)
    for template in templates:
        name = str(template.get("template") or "").strip()
        if not name or name in known:
            continue
        merged.append({
            "name": name,
            "source": template.get("source", ""),
            "vendor_id": template.get("vendor_id"),
            "attribute_count": template.get("attribute_count", 0),
            "file": template.get("file", ""),
        })
        known.add(name)
        added += 1
    if added:
        text = yaml_util.dump_yaml({"templates": merged})
        file_util.write_text_atomic(paths.radius_yaml_path(), text)
        logger.info("dictionary", "已补充 radius.yaml 模板登记", {"added": added})
    return added
