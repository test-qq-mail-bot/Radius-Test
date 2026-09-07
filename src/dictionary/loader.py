# -*- coding: utf-8 -*-
"""
Dictionary 加载模块。

职责：
    1. 加载源码内置的 Dictionary 配置文件（src/dictionary/data/*.yaml）；
    2. 扫描并加载自定义 Dictionary（data/dictionaries/*.yaml）；
    3. 维护模板索引，供解析器按属性编号匹配。

规则（项目书 18.x）：
    1. 内置 Dictionary 位于源码内部，用户不可直接修改；
    2. 自定义 Dictionary 位于 data/dictionaries/；
    3. 自定义 YAML 格式正确且符合模板规范才加载，否则忽略，不处理；
    4. 内置模板只读，可通过「派生为自定义模板」生成可编辑副本。

匹配规则（项目书 17.2）：
    标准属性按 (属性编号) 索引；
    厂商属性按 (Vendor-ID, 子类型编号) 索引；
    一个属性可能命中多个模板，全部列出。
"""

from typing import Dict, List, Optional

from ..common import file_util, paths
from ..common import yaml_util
from ..logging import logger
from ..radius.codes import SUPPORTED_TYPES, TYPE_UNKNOWN

# 模板文件扩展名
DICTIONARY_EXTENSIONS = (".yaml", ".yml")


class AttributeDefinition:
    """单条属性定义。"""

    __slots__ = ("attr_id", "name", "name_zh", "type", "desc", "vendor", "vendor_id",
                 "template", "packet_support")

    def __init__(self, attr_id: int, name: str, name_zh: str, type_name: str,
                 desc: str, vendor: str, vendor_id: Optional[int], template: str,
                 packet_support: dict = None):
        self.attr_id = attr_id
        self.name = name
        self.name_zh = name_zh
        self.type = type_name
        self.desc = desc
        self.vendor = vendor
        self.vendor_id = vendor_id
        self.template = template
        self.packet_support = packet_support or {}

    def to_dict(self) -> dict:
        """转换为可序列化字典。"""
        return {
            "id": self.attr_id,
            "name": self.name,
            "name_zh": self.name_zh,
            "type": self.type,
            "desc": self.desc,
            "vendor": self.vendor,
            "vendor_id": self.vendor_id,
            "template": self.template,
            "packet_support": self.packet_support,
        }


class DictionaryTemplate:
    """
    一个 Dictionary 模板。

    属性：
        name: 模板名称
        vendor: 厂商名称，标准属性模板为空字符串
        vendor_id: 厂商编号，标准属性模板为 None
        source: builtin 或 custom
        file: 来源文件名
        attributes: 属性定义列表
        index: 属性索引，键为 (vendor_id, attr_id)，标准属性 vendor_id 为 None
    """

    __slots__ = ("name", "vendor", "vendor_id", "source", "file",
                 "attributes", "index", "error")

    def __init__(self, name: str, vendor: str = "", vendor_id: Optional[int] = None,
                 source: str = "builtin", file: str = ""):
        self.name = name
        self.vendor = vendor
        self.vendor_id = vendor_id
        self.source = source
        self.file = file
        self.attributes: List[AttributeDefinition] = []
        self.index: Dict[tuple, List[AttributeDefinition]] = {}
        self.error = ""

    @property
    def attribute_count(self) -> int:
        """属性数量。"""
        return len(self.attributes)

    def build_index(self) -> None:
        """构建属性索引。"""
        self.index.clear()
        for definition in self.attributes:
            key = (self.vendor_id, definition.attr_id)
            self.index.setdefault(key, []).append(definition)

    def lookup(self, attr_id: int, vendor_id: Optional[int]) -> List[AttributeDefinition]:
        """按编号查找属性定义，未命中返回空列表。"""
        return self.index.get((vendor_id, attr_id), [])

    def to_dict(self) -> dict:
        """转换为可序列化字典，供 API 与前端使用。"""
        return {
            "template": self.name,
            "vendor": self.vendor,
            "vendor_id": self.vendor_id,
            "source": self.source,
            "file": self.file,
            "attribute_count": self.attribute_count,
            "attributes": [a.to_dict() for a in self.attributes],
        }


def parse_template(data: dict, source: str = "builtin", file: str = "") -> DictionaryTemplate:
    """
    解析模板字典数据。

    参数：
        data: 已解析的 YAML 字典
        source: builtin / custom
        file: 来源文件名

    返回：
        DictionaryTemplate 对象。

    异常：
        DictionaryError: 缺少必需字段或字段类型非法。
    """
    from ..common.errors import DictionaryError

    if not isinstance(data, dict):
        raise DictionaryError("模板根节点必须是字典")
    name = str(data.get("template") or "").strip()
    if not name:
        raise DictionaryError("模板缺少 template 字段", "文件=%s" % file)
    raw_vendor_id = data.get("vendor_id")
    vendor_id = None
    if raw_vendor_id is not None and str(raw_vendor_id).strip() != "":
        try:
            vendor_id = int(raw_vendor_id)
        except (TypeError, ValueError):
            raise DictionaryError("vendor_id 必须是整数", "模板=%s" % name)
    vendor = str(data.get("vendor") or "").strip()
    template = DictionaryTemplate(
        name=name,
        vendor=vendor,
        vendor_id=vendor_id,
        source=source,
        file=file,
    )
    raw_attributes = data.get("attributes")
    if not isinstance(raw_attributes, list):
        raise DictionaryError("模板缺少 attributes 列表", "模板=%s" % name)
    for item in raw_attributes:
        if not isinstance(item, dict):
            continue
        try:
            attr_id = int(item.get("id"))
        except (TypeError, ValueError):
            continue
        type_name = str(item.get("type") or TYPE_UNKNOWN).strip()
        if type_name not in SUPPORTED_TYPES:
            type_name = TYPE_UNKNOWN
        definition = AttributeDefinition(
            attr_id=attr_id,
            name=str(item.get("name") or "Unknown"),
            name_zh=str(item.get("name_zh") or item.get("name") or "Unknown"),
            type_name=type_name,
            desc=str(item.get("desc") or ""),
            vendor=vendor,
            vendor_id=vendor_id,
            template=name,
            packet_support=item.get("packet_support") if isinstance(item.get("packet_support"), dict) else {},
        )
        template.attributes.append(definition)
    template.build_index()
    return template


def load_builtin_templates() -> List[DictionaryTemplate]:
    """
    加载内置 Dictionary 模板。

    内置模板位于源码目录 src/dictionary/data/，随程序一起分发。
    """
    result: List[DictionaryTemplate] = []
    directory = paths.builtin_dictionary_dir()
    if not directory.is_dir():
        logger.warning("dictionary", "内置 Dictionary 目录不存在", {"path": str(directory)})
        return result
    for path in sorted(directory.glob("*.yaml")):
        try:
            data = yaml_util.load_yaml_text(file_util.read_text(path))
            template = parse_template(data, source="builtin", file=path.name)
            result.append(template)
        except Exception as exc:
            logger.warning("dictionary", "内置模板加载失败，已跳过", {
                "file": path.name,
                "error": str(exc),
            })
    logger.info("dictionary", "已加载内置 Dictionary 模板", {"count": len(result)})
    return result


def load_custom_templates() -> List[DictionaryTemplate]:
    """
    加载自定义 Dictionary 模板。

    扫描 data/dictionaries/*.yaml，格式不合法的直接忽略，不抛异常。
    """
    result: List[DictionaryTemplate] = []
    directory = paths.dictionaries_dir()
    if not directory.is_dir():
        return result
    for path in sorted(directory.iterdir()):
        if not path.is_file() or path.suffix.lower() not in DICTIONARY_EXTENSIONS:
            continue
        try:
            data = yaml_util.load_yaml_text(file_util.read_text(path))
            template = parse_template(data, source="custom", file=path.name)
            result.append(template)
        except Exception as exc:
            logger.warning("dictionary", "自定义 Dictionary 格式不合法，已忽略", {
                "file": path.name,
                "error": str(exc),
            })
    return result


class DictionaryStore:
    """
    Dictionary 仓库。

    对外提供统一的模板列表与属性匹配能力。
    """

    def __init__(self):
        self.templates: List[DictionaryTemplate] = []
        self._by_name: Dict[str, DictionaryTemplate] = {}

    def reload(self) -> None:
        """重新加载全部模板（内置 + 自定义）。"""
        self.templates = []
        self._by_name = {}
        for template in load_builtin_templates():
            self._add(template)
        for template in load_custom_templates():
            self._add(template)
        logger.info("dictionary", "Dictionary 全部模板加载完成", {
            "count": len(self.templates),
        })

    def _add(self, template: DictionaryTemplate) -> None:
        """加入模板，同名模板后者覆盖前者（自定义优先于内置）。"""
        existing = self._by_name.get(template.name)
        if existing is not None:
            self.templates.remove(existing)
        self.templates.append(template)
        self._by_name[template.name] = template

    def get(self, name: str) -> Optional[DictionaryTemplate]:
        """按名称获取模板。"""
        return self._by_name.get(name)

    def names(self) -> List[str]:
        """返回全部模板名称。"""
        return [t.name for t in self.templates]

    def summary(self) -> List[dict]:
        """返回模板摘要列表（不含属性明细）。"""
        return [
            {
                "template": t.name,
                "vendor": t.vendor,
                "vendor_id": t.vendor_id,
                "source": t.source,
                "file": t.file,
                "attribute_count": t.attribute_count,
            }
            for t in self.templates
        ]

    def match(self, attr_id: int, vendor_id: Optional[int]) -> List[AttributeDefinition]:
        """
        遍历全部模板匹配属性。

        参数：
            attr_id: 属性编号（VSA 时为子类型编号）
            vendor_id: 厂商编号，标准属性为 None

        返回：
            命中的属性定义列表；未命中返回空列表。
        """
        matches: List[AttributeDefinition] = []
        for template in self.templates:
            if vendor_id is not None and template.vendor_id != vendor_id:
                continue
            if vendor_id is None and template.vendor_id is not None:
                continue
            matches.extend(template.lookup(attr_id, vendor_id))
        return matches


_store: Optional[DictionaryStore] = None


def get_store() -> DictionaryStore:
    """获取全局 Dictionary 仓库（首次调用时加载）。"""
    global _store
    if _store is None:
        _store = DictionaryStore()
        _store.reload()
    return _store
