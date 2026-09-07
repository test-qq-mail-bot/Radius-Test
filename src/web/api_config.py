# -*- coding: utf-8 -*-
"""
配置接口模块。

提供：
    GET  /api/config           读取全部配置
    PUT  /api/config           保存配置（只接受已定义参数）
    POST /api/config/reload    重新从磁盘加载

约束（项目书第 7 节）：
    1. Web 只能修改默认配置中已经定义的参数；
    2. Web 不得增加配置文件中不存在的配置项目；
    3. 修改后写入 data/config.yaml 并提示重启。
"""

from typing import Any, Dict

from fastapi import APIRouter, HTTPException

from ..common import net_util
from ..common.errors import ConfigError
from ..config import defaults, loader
from ..logging import logger

router = APIRouter(prefix="/api/config", tags=["config"])


@router.get("")
async def get_config():
    """返回当前生效配置与默认值，供页面渲染。"""
    config = loader.load_config()
    return {
        "config": config,
        "defaults": defaults.default_config(),
        "supported_protocols": list(defaults.SUPPORTED_PROTOCOLS),
        "log_levels": ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        "need_restart": False,
    }


@router.put("")
async def save_config(payload: Dict[str, Any]):
    """
    保存配置。

    请求体示例：
        {"web": {"port": 51234, "https": true}, "test": {"rate": 20}}
    """
    try:
        current = loader.load_config()
        merged = _deep_copy(current)
        for section, values in (payload or {}).items():
            if section not in merged:
                raise ConfigError("配置节不存在", "节=%s" % section)
            if not isinstance(values, dict):
                raise ConfigError("配置节必须是字典", "节=%s" % section)
            for key, value in values.items():
                if key not in merged[section]:
                    raise ConfigError("配置项未被定义", "项=%s.%s" % (section, key))
                merged[section][key] = value
        _validate(merged)
        loader.save_config(merged)
    except ConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    # 日志等级变更实时生效：无需重启即可在程序控制台与浏览器看到 DEBUG 信息
    new_level = str(merged.get("log", {}).get("level") or "INFO").upper()
    old_level = str(current.get("log", {}).get("level") or "INFO").upper()
    if new_level != old_level:
        logger.set_level(new_level)
    # 仅日志等级变更无需重启；其余配置项变更仍需重启生效
    changed_sections = [s for s in merged if current.get(s) != merged.get(s)]
    need_restart = any(s != "log" for s in changed_sections)
    logger.info("api", "配置已通过 Web 保存", {"need_restart": need_restart})
    return {
        "success": True,
        "message": "配置已保存" + ("，请重启程序后生效" if need_restart else "，日志等级已实时生效"),
        "need_restart": need_restart,
        "config": loader.load_config(),
    }


@router.post("/reload")
async def reload_config():
    """从磁盘重新加载配置。"""
    config = loader.reload()
    logger.info("api", "配置已重新加载", {})
    return {"success": True, "config": config}


def _deep_copy(data: dict) -> dict:
    """浅层深拷贝配置字典。"""
    result = {}
    for key, value in data.items():
        if isinstance(value, dict):
            result[key] = dict(value)
        elif isinstance(value, list):
            result[key] = list(value)
        else:
            result[key] = value
    return result


def _validate(config: dict) -> None:
    """校验关键配置取值。"""
    web = config.get("web", {})
    port = web.get("port")
    if port not in (None, "", 0):
        try:
            number = int(port)
        except (TypeError, ValueError):
            raise ConfigError("端口必须是整数", "值=%s" % port)
        if not (1 <= number <= 65535):
            raise ConfigError("端口必须在 1~65535 之间", "值=%s" % number)
    hosts = web.get("hosts") or []
    if not isinstance(hosts, list) or not hosts:
        raise ConfigError("监听地址不能为空")
    for host in hosts:
        if not isinstance(host, str) or not host.strip():
            raise ConfigError("监听地址非法", "值=%s" % host)
    test = config.get("test", {})
    if float(test.get("rate") or 0) < 0:
        raise ConfigError("测试速率不能为负数")
    if int(test.get("max_concurrency") or 0) < 1:
        raise ConfigError("最大并发数至少为 1")
    radius = config.get("radius", {})
    if int(radius.get("mschap_peer_challenge_bytes") or 8) not in (8, 16):
        raise ConfigError("MS-CHAP 对端挑战值字节数只能是 8 或 16")
    level = str(config.get("log", {}).get("level") or "INFO").upper()
    if level not in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
        raise ConfigError("日志等级非法", "值=%s" % level)
    if not net_util.is_local_only(hosts):
        logger.warning("api", "监听地址非本机，已记录安全提示", {"hosts": hosts})
