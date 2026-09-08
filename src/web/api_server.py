# -*- coding: utf-8 -*-
"""
RADIUS Server 管理接口模块。

提供：
    GET    /api/servers               列表
    POST   /api/servers               新增
    PUT    /api/servers/{name}        修改
    DELETE /api/servers/{name}        删除
    POST   /api/servers/{name}/test   连通性测试（探测账号）
    POST   /api/servers/{name}/auth-test  Radius 用户认证测试（指定账号）

字段名称固定使用（项目书 12）：
    authentication_port / accounting_port / nas_ip_address
    不使用 auth_port / acct_port / nas_ip
"""

from typing import Any, Dict

from fastapi import APIRouter, HTTPException

from ..common import csv_util, file_util, paths, time_util
from ..common.errors import RadiusError, ValidationError
from ..common.validator import (
    is_valid_host,
    is_valid_port,
    is_valid_positive_int,
    is_valid_timeout,
)
from ..config import defaults, loader
from ..logging import logger
from ..radius.client import RadiusClient
from . import runtime

router = APIRouter(prefix="/api/servers", tags=["servers"])


def _validate_server(server: dict) -> None:
    """校验 Server 配置。"""
    name = str(server.get("name") or "").strip()
    if not name:
        raise ValidationError("Server 名称不能为空")
    if not is_valid_host(server.get("server_address")):
        raise ValidationError("Server 地址非法", "值=%s" % server.get("server_address"))
    if not str(server.get("shared_secret") or ""):
        raise ValidationError("共享密钥不能为空")
    # RADIUS 认证服务器 / 认证密钥（必填）
    auth_server = str(server.get("authentication_server_address") or "").strip()
    if not auth_server:
        raise ValidationError("RADIUS 认证服务器不能为空")
    if not is_valid_host(auth_server):
        raise ValidationError("RADIUS 认证服务器地址非法", "值=%s" % auth_server)
    if not str(server.get("authentication_secret") or ""):
        raise ValidationError("认证密钥不能为空")
    # RADIUS 计费服务器 / 计费密钥（必填）
    acct_server = str(server.get("accounting_server_address") or "").strip()
    if not acct_server:
        raise ValidationError("RADIUS 计费服务器不能为空")
    if not is_valid_host(acct_server):
        raise ValidationError("RADIUS 计费服务器地址非法", "值=%s" % acct_server)
    if not str(server.get("accounting_secret") or ""):
        raise ValidationError("计费密钥不能为空")
    # 计费间隔：非负整数，默认 0（0 表示不发送 Interim-Update）
    try:
        acct_interval = int(server.get("accounting_interval") or 0)
    except (TypeError, ValueError):
        raise ValidationError("计费间隔必须为整数", "值=%s" % server.get("accounting_interval"))
    if acct_interval < 0:
        raise ValidationError("计费间隔不能为负数", "值=%s" % acct_interval)
    if not is_valid_port(server.get("authentication_port")):
        raise ValidationError("认证端口非法", "值=%s" % server.get("authentication_port"))
    if not is_valid_port(server.get("accounting_port")):
        raise ValidationError("计费端口非法", "值=%s" % server.get("accounting_port"))
    nas_ip = str(server.get("nas_ip_address") or "").strip()
    if nas_ip and not is_valid_host(nas_ip):
        raise ValidationError("NAS IP 地址非法", "值=%s" % nas_ip)
    source = str(server.get("source_address") or "").strip()
    if source and not is_valid_host(source):
        raise ValidationError("报文源地址非法", "值=%s" % source)
    if not is_valid_timeout(server.get("timeout")):
        raise ValidationError("超时时间非法", "值=%s" % server.get("timeout"))
    if not is_valid_positive_int(server.get("retry_count"), 10):
        raise ValidationError("重试次数非法", "值=%s" % server.get("retry_count"))


@router.get("")
async def list_servers():
    """返回全部 RADIUS Server。"""
    return {
        "servers": loader.get_servers(),
        "fields": defaults.default_server(),
        "protocols": list(defaults.SUPPORTED_PROTOCOLS),
    }


@router.post("")
async def create_server(payload: Dict[str, Any]):
    """新增 RADIUS Server（名称为唯一键，同名时覆盖更新）。"""
    server = defaults.default_server()
    server.update({k: v for k, v in (payload or {}).items() if k in server})
    try:
        _validate_server(server)
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    servers = loader.get_servers()
    updated = False
    for index, existing in enumerate(servers):
        if existing.get("name") == server["name"]:
            # 名称作为唯一键：同名时用本次提交的字段覆盖更新
            servers[index] = server
            updated = True
            break
    if not updated:
        servers.append(server)
    loader.save_servers(servers)
    if updated:
        logger.info("api", "Server 名称已存在，覆盖更新", {"name": server["name"]})
    else:
        logger.info("api", "已新增 RADIUS Server", {"name": server["name"]})
    return {"success": True, "updated": updated, "server": server}


@router.put("/{name}")
async def update_server(name: str, payload: Dict[str, Any]):
    """修改 RADIUS Server。"""
    servers = loader.get_servers()
    for index, server in enumerate(servers):
        if server.get("name") == name:
            updated = dict(server)
            updated.update({k: v for k, v in (payload or {}).items() if k in updated})
            try:
                _validate_server(updated)
            except ValidationError as exc:
                raise HTTPException(status_code=400, detail=str(exc))
            servers[index] = updated
            loader.save_servers(servers)
            logger.info("api", "已修改 RADIUS Server", {"name": name})
            return {"success": True, "server": updated}
    raise HTTPException(status_code=404, detail="Server 不存在")


@router.delete("/{name}")
async def delete_server(name: str):
    """删除 RADIUS Server。"""
    servers = loader.get_servers()
    remaining = [s for s in servers if s.get("name") != name]
    if len(remaining) == len(servers):
        raise HTTPException(status_code=404, detail="Server 不存在")
    loader.save_servers(remaining)
    logger.info("api", "已删除 RADIUS Server", {"name": name})
    return {"success": True}


def _find_server(name: str):
    """按名称查找 RADIUS Server 配置。"""
    for server in loader.get_servers():
        if server.get("name") == name:
            return server
    return None


async def _probe(target: dict, username: str, password: str, protocol: str) -> dict:
    """
    对目标 Server 执行一次认证探测，返回统一结果字典。

    返回字段：server / authentication_port / accounting_port /
        connect_result / radius_result / response_time_ms / error。
    """
    client = RadiusClient(runtime.socket_manager)
    started = time_util.now()
    result = {
        "server": target.get("server_address"),
        "authentication_port": target.get("authentication_port"),
        "accounting_port": target.get("accounting_port"),
        "connect_result": "未知",
        "radius_result": "未知",
        "response_time_ms": 0.0,
        "error": "",
    }
    try:
        auth_result = await client.authenticate(target, username, password, protocol)
        result["response_time_ms"] = round(auth_result.response_time_ms, 3)
        if auth_result.response_packet is not None:
            result["connect_result"] = "可达"
            result["radius_result"] = auth_result.code_name
            result["error"] = auth_result.error or ""
        else:
            result["connect_result"] = "无响应"
            result["radius_result"] = "无响应"
            result["error"] = auth_result.error or "未收到服务器响应"
    except RadiusError as exc:
        result["connect_result"] = "失败"
        result["radius_result"] = "失败"
        result["error"] = str(exc)
    except Exception as exc:
        result["connect_result"] = "失败"
        result["radius_result"] = "失败"
        result["error"] = "未知错误；%s" % exc
    elapsed = time_util.elapsed_ms(started)
    if result["response_time_ms"] == 0.0:
        result["response_time_ms"] = round(elapsed, 3)
    return result


@router.post("/{name}/test")
async def test_server(name: str):
    """
    测试 RADIUS Server 连通性（使用探测账号 radtest-probe）。

    返回：
        Server 地址、认证端口、计费端口、连接结果、
        RADIUS 响应结果、响应时间、错误原因。
    """
    target = _find_server(name)
    if target is None:
        raise HTTPException(status_code=404, detail="Server 不存在")
    logger.debug("api", "开始 Server 连通性测试", {
        "name": name, "server": target.get("server_address"),
    })
    result = await _probe(target, "radtest-probe", "radtest-probe",
                          str(target.get("protocol") or "pap"))
    logger.info("api", "Server 连通性测试完成", {
        "name": name,
        "result": result["radius_result"],
        "error": result["error"],
    })
    return result


@router.post("/{name}/auth-test")
async def auth_test(name: str, payload: Dict[str, Any]):
    """
    使用指定账号与协议，对该 Server 执行一次真实认证测试。

    请求体：{"username": str, "password": str, "protocol": str(可选)}
    返回：与 test 一致的结果字典。
    """
    target = _find_server(name)
    if target is None:
        raise HTTPException(status_code=404, detail="Server 不存在")
    username = str(payload.get("username") or "").strip()
    password = str(payload.get("password") or "")
    protocol = str(payload.get("protocol") or target.get("protocol") or "pap")
    if not username:
        raise HTTPException(status_code=400, detail="用户名不能为空")
    logger.debug("api", "开始 Radius 用户认证测试", {
        "name": name, "username": username, "protocol": protocol,
    })
    result = await _probe(target, username, password, protocol)
    logger.info("api", "Radius 用户认证测试完成", {
        "name": name, "username": username,
        "result": result["radius_result"], "error": result["error"],
    })
    return result


@router.post("/{name}/batch-auth-test")
async def batch_auth_test(name: str, payload: Dict[str, Any]):
    """批量对多个用户执行认证测试，内部复用单用户测试逻辑（_probe）。"""
    target = _find_server(name)
    if target is None:
        raise HTTPException(status_code=404, detail="Server 不存在")
    usernames = payload.get("usernames") or []
    if not isinstance(usernames, list) or not usernames:
        raise HTTPException(status_code=400, detail="usernames 不能为空")
    protocol = str(payload.get("protocol") or target.get("protocol") or "pap")

    # 读取用户密码（用户列表接口本就返回明文密码）
    passwords = {}
    try:
        text = file_util.read_text(paths.users_csv_path())
        for user in csv_util.parse_users_csv(text):
            passwords[user["username"]] = user.get("password", "")
    except Exception:
        passwords = {}

    results = []
    for raw in usernames:
        username = str(raw).strip()
        if not username:
            continue
        password = passwords.get(username, "")
        try:
            result = await _probe(target, username, password, protocol)
            result["username"] = username
            results.append(result)
        except Exception as exc:
            results.append({
                "username": username,
                "server": target.get("server_address"),
                "authentication_port": target.get("authentication_port"),
                "accounting_port": target.get("accounting_port"),
                "connect_result": "失败",
                "radius_result": "失败",
                "response_time_ms": 0.0,
                "error": str(exc),
            })
    logger.info("api", "批量 Radius 用户认证测试完成", {
        "name": name, "count": len(results),
    })
    return {"success": True, "results": results}
