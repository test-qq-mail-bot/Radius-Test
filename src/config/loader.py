# -*- coding: utf-8 -*-
"""
配置加载与保存模块。

职责：
    1. 启动时确保 data/config.yaml 存在（不存在才生成）；
    2. 合并「默认配置 + config.yaml」，config.yaml 优先；
    3. 只接受默认配置中已定义的键，未知键忽略；
    4. 提供保存接口供 Web 配置页调用。

约束（项目书 6.3）：
    已存在的配置文件绝不覆盖，仅在用户主动保存时写入。
"""

import copy
import threading
from typing import Any, Dict, List, Optional

from ..common import file_util, paths
from ..common import yaml_util
from ..common.errors import ConfigError
from ..logging import logger
from . import defaults

_lock = threading.RLock()
_config: Optional[Dict[str, Any]] = None


def ensure_config_file() -> bool:
    """
    确保 config.yaml 存在。

    返回：
        True 表示本次创建了文件，False 表示文件已存在未做处理。
    """
    return file_util.create_if_missing(
        paths.config_path(),
        lambda: defaults.CONFIG_YAML_TEMPLATE,
    )


def _filter_known(section_default: Any, user_value: Any) -> Any:
    """
    过滤用户输入，只保留默认配置中已定义的键。

    参数：
        section_default: 默认配置中的对应节点
        user_value: 配置文件中的对应节点

    返回：
        过滤后的值。
    """
    if isinstance(section_default, dict):
        if not isinstance(user_value, dict):
            return copy.deepcopy(section_default)
        result = copy.deepcopy(section_default)
        for key, value in user_value.items():
            if key not in result:
                # 未知键直接忽略
                continue
            result[key] = _filter_known(result[key], value)
        return result
    if user_value is None:
        return copy.deepcopy(section_default)
    return user_value


def load_config(force: bool = False) -> Dict[str, Any]:
    """
    加载生效配置。

    参数：
        force: True 时强制重新读取文件

    返回：
        合并后的配置字典。
    """
    global _config
    with _lock:
        if _config is not None and not force:
            return _config
        ensure_config_file()
        base = defaults.default_config()
        if paths.config_path().is_file():
            user_config = yaml_util.load_yaml(paths.config_path())
        else:
            user_config = {}
        merged = _filter_known(base, user_config)
        # 端口为空时随机选择并写回配置文件
        if not merged["web"].get("port"):
            from ..common import net_util

            port = net_util.choose_random_port("127.0.0.1")
            merged["web"]["port"] = port
            save_config(merged, write_template=False)
            logger.info("config", "端口为空，已随机选择并写回配置文件", {"port": port})
        _config = merged
        return _config


def get(section: str, key: str = None, default: Any = None) -> Any:
    """
    读取配置项。

    用法：
        get("web", "port")
        get("test")
    """
    config = load_config()
    if key is None:
        return config.get(section, default)
    return config.get(section, {}).get(key, default)


def save_config(config: Dict[str, Any], write_template: bool = True) -> None:
    """
    保存配置到 data/config.yaml。

    参数：
        config: 完整配置字典
        write_template: 是否写入含注释的模板头部

    说明：
        保存前会按默认配置白名单过滤，防止写入未知键。
    """
    global _config
    with _lock:
        cleaned = _filter_known(defaults.default_config(), config)
        if write_template:
            text = yaml_util.dump_yaml(cleaned)
        else:
            text = yaml_util.dump_yaml(cleaned)
        file_util.write_text_atomic(paths.config_path(), text)
        _config = cleaned
        logger.info("config", "配置已保存", {"path": str(paths.config_path())})


def update_section(section: str, values: Dict[str, Any]) -> Dict[str, Any]:
    """
    更新指定配置节并保存。

    参数：
        section: 配置节名称
        values: 待更新的键值对

    返回：
        更新后的完整配置。
    """
    with _lock:
        config = copy.deepcopy(load_config())
        if section not in config:
            raise ConfigError("配置节不存在", "节=%s" % section)
        if not isinstance(config[section], dict):
            raise ConfigError("配置节不是字典", "节=%s" % section)
        for key, value in values.items():
            if key not in config[section]:
                raise ConfigError("配置项未被定义", "项=%s.%s" % (section, key))
            config[section][key] = value
        save_config(config)
        return config


def get_servers() -> List[Dict[str, Any]]:
    """返回 RADIUS Server 列表。"""
    servers = get("radius_servers") or []
    result = []
    for item in servers:
        if not isinstance(item, dict):
            continue
        server = defaults.default_server()
        server.update({k: v for k, v in item.items() if k in server})
        result.append(server)
    return result


def save_servers(servers: List[Dict[str, Any]]) -> None:
    """
    保存 RADIUS Server 列表。

    参数：
        servers: Server 字典列表，只保留已定义字段。
    """
    with _lock:
        config = copy.deepcopy(load_config())
        cleaned = []
        for item in servers:
            server = defaults.default_server()
            server.update({k: v for k, v in item.items() if k in server})
            cleaned.append(server)
        config["radius_servers"] = cleaned
        save_config(config)
        logger.info("config", "RADIUS Server 列表已保存", {"count": len(cleaned)})


def reload() -> Dict[str, Any]:
    """重新从磁盘加载配置。"""
    return load_config(force=True)
