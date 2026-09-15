# -*- coding: utf-8 -*-
"""
RADIUS Server 管理接口模块。

提供：
    GET    /api/servers               列表
    POST   /api/servers               新增
    PUT    /api/servers/{name}        修改
    DELETE /api/servers/{name}        删除
    POST   /api/servers/{name}/test   连通性测试（探测账号）
    POST   /api/servers/{name}/auth-test        Radius 用户认证测试（单个账号，保持在线）
    POST   /api/servers/{name}/batch-auth-test  Radius 用户认证测试（批量账号，均保持在线）
    POST   /api/servers/user-tests/stop         停止全部账号认证测试（发送 Accounting-Stop）

认证测试行为（20260915-V1 起）：
    auth-test / batch-auth-test 走「会话化」链路（见 src/web/user_test.py）：
    认证成功并计费上线后保持用户在线（后台按计费间隔发送 Interim-Update），
    直到调用 /user-tests/stop、或前端断开（见 src/web/ws.py）时才发送 Accounting-Stop。
    账号认证测试与性能测试互斥：任一方运行中发起另一方将返回 400。

认证测试请求体（auth-test / batch-auth-test）与性能测试请求体（POST /api/tasks）
均可带可选字段 dot1x，用于指定 Dot1X 接入与常用 RADIUS 参数；不传时沿用硬编码属性
（`NAS-Port=1`、`Called-Station-Id=00-00-00-00-00-00:Radius-Test`、
`Calling-Station-Id=02-00-00-00-00-01`）：

    {"access_type": "wired" | "wireless",        # 默认 wired（NAS-Port-Type 15 / 19）
     "ssid": "SSID",                             # 仅 wireless 生效，留空取 Radius-Test
     "nas_port": "2002",                         # NAS-Port(5) 端口号；留空则随机或按用户序号分配
     "nas_port_id": "GigabitEthernet0/0/1",      # NAS-Port-Id(87) 端口名称（字符串）
     "calling_station_id": "AA-BB-CC-DD-EE-FF",  # Calling-Station-Id(31) 终端 MAC；留空则随机
     "nas_identifier": "NAS-01",                 # NAS-Identifier(32)
     "service_type": "2",                        # Service-Type(6)，取值 1~15 或文本键
     "framed_ip_address": "10.1.2.3",            # Framed-IP-Address(8)
     "connect_info": "CONNECT 100000000"}        # Connect-Info(77)

注意：
    `NAS-Port(5)` 是端口号（数值），`NAS-Port-Id(87)` 是端口名称（字符串），二者语义不同；
    除 NAS-Port 与终端 MAC（留空自动生成）外，其余字段留空即「不发送该属性」；
    性能测试的 dot1x 同时作用于认证报文与计费报文（含 Interim-Update / Stop），
    保证服务端看到的接入属性前后一致。

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
from ..testing import single as single_mod
from . import runtime
from . import user_test

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


# 掩码哨兵对应字段的中文名，用于校验提示
SECRET_LABELS = {
    "shared_secret": "共享密钥",
    "authentication_secret": "认证密钥",
    "accounting_secret": "计费密钥",
}


def _apply_secret_sentinel(server: dict, existing: dict) -> None:
    """
    处理密钥掩码哨兵。

    规则：
        提交值等于掩码时代表“密钥不变”；存在同名旧配置则沿用原密钥，
        不存在（新建）时掩码属于无效输入，直接报错。

    参数：
        server: 本次提交的 Server 配置（原地修改）
        existing: 同名旧配置，None 表示新建
    """
    for field in defaults.SECRET_FIELDS:
        if str(server.get(field) or "") != defaults.SECRET_MASK:
            continue
        if existing is None:
            raise ValidationError(
                "%s不能为掩码值，请填写真实密钥" % SECRET_LABELS.get(field, field),
                "值=%s" % defaults.SECRET_MASK,
            )
        server[field] = str(existing.get(field) or "")


@router.get("")
async def list_servers():
    """返回全部 RADIUS Server（密钥字段脱敏，明文不下发到页面）。"""
    return {
        "servers": [defaults.mask_secrets(item) for item in loader.get_servers()],
        "fields": defaults.default_server(),
        "protocols": list(defaults.SUPPORTED_PROTOCOLS),
        "secret_mask": defaults.SECRET_MASK,
    }


@router.post("")
async def create_server(payload: Dict[str, Any]):
    """新增 RADIUS Server（名称为唯一键，同名时覆盖更新）。"""
    server = defaults.default_server()
    server.update({k: v for k, v in (payload or {}).items() if k in server})
    servers = loader.get_servers()
    existing = None
    for item in servers:
        if item.get("name") == server["name"]:
            existing = item
            break
    try:
        _apply_secret_sentinel(server, existing)
        _validate_server(server)
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    updated = False
    for index, item in enumerate(servers):
        if item.get("name") == server["name"]:
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
    return {"success": True, "updated": updated, "server": defaults.mask_secrets(server)}


@router.put("/{name}")
async def update_server(name: str, payload: Dict[str, Any]):
    """修改 RADIUS Server。"""
    servers = loader.get_servers()
    for index, server in enumerate(servers):
        if server.get("name") == name:
            updated = dict(server)
            updated.update({k: v for k, v in (payload or {}).items() if k in updated})
            try:
                _apply_secret_sentinel(updated, server)
                _validate_server(updated)
            except ValidationError as exc:
                raise HTTPException(status_code=400, detail=str(exc))
            servers[index] = updated
            loader.save_servers(servers)
            logger.info("api", "已修改 RADIUS Server", {"name": name})
            return {"success": True, "server": defaults.mask_secrets(updated)}
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


def _save_packets_enabled() -> bool:
    """读取系统配置：是否保存 RADIUS 报文。"""
    try:
        return bool(loader.load_config()["storage"]["save_packets"])
    except Exception:
        return False


async def _probe(target: dict, username: str, password: str, protocol: str,
              dot1x: Any = None) -> dict:
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
        auth_result = await client.authenticate(
            target, username, password, protocol, dot1x=dot1x)
        result["response_time_ms"] = round(auth_result.response_time_ms, 3)
        if auth_result.response_packet is not None:
            result["connect_result"] = "可达"
            result["radius_result"] = auth_result.code_name
            result["error"] = auth_result.error or ""
        else:
            result["connect_result"] = "无响应"
            result["radius_result"] = "无响应"
            result["error"] = auth_result.error or "未收到服务器响应"
        # 系统配置「保存 RADIUS 报文」开启时，把本次结果/报文落库（每用户仅保留最新一份）
        if _save_packets_enabled():
            try:
                result["task_id"] = single_mod.persist_single_test(
                    target, username, protocol, auth_result)
            except Exception as exc:
                logger.warning("api", "单次测试报文保存失败", {
                    "username": username,
                    "error": str(exc),
                }, exc_info=True)
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
    使用指定账号与协议，对该 Server 执行一次真实认证测试（需求3：测试后保持在线）。

    请求体：{"username": str, "password": str, "protocol": str(可选)}
    返回：结果字典（含 task_id / session_id / online，供前端停止测试）。

    说明：
        认证并计费上线成功后保持在线，直到用户点击「停止测试」或前端断开；
        与性能测试互斥（性能测试运行中时返回 400）。
    """
    target = _find_server(name)
    if target is None:
        raise HTTPException(status_code=404, detail="Server 不存在")
    username = str(payload.get("username") or "").strip()
    password = str(payload.get("password") or "")
    protocol = str(payload.get("protocol") or target.get("protocol") or "pap")
    dot1x = payload.get("dot1x")
    if not username:
        raise HTTPException(status_code=400, detail="用户名不能为空")
    logger.debug("api", "开始 Radius 用户认证测试", {
        "name": name, "username": username, "protocol": protocol,
    })
    try:
        result = await user_test.start_user_test(
            name, username, password, protocol, dot1x)
    except user_test.UserTestError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return result


@router.post("/{name}/batch-auth-test")
async def batch_auth_test(name: str, payload: Dict[str, Any]):
    """
    批量对多个用户执行认证测试（需求3：每个用户测试后保持在线）。

    说明：
        内部复用单用户会话化测试逻辑（user_test.start_user_test），
        每个成功上线的用户都会保持在线，可在前端统一「停止测试」；
        与性能测试互斥。
    """
    target = _find_server(name)
    if target is None:
        raise HTTPException(status_code=404, detail="Server 不存在")
    usernames = payload.get("usernames") or []
    if not isinstance(usernames, list) or not usernames:
        raise HTTPException(status_code=400, detail="usernames 不能为空")
    protocol = str(payload.get("protocol") or target.get("protocol") or "pap")
    dot1x = payload.get("dot1x")

    # 互斥预检查：性能测试运行中直接拒绝，避免部分用户已上线后才报错
    try:
        user_test.ensure_no_perf_test()
    except user_test.UserTestError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

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
            result = await user_test.start_user_test(
                name, username, password, protocol, dot1x)
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
                "online": False,
            })
    logger.info("api", "批量 Radius 用户认证测试完成", {
        "name": name, "count": len(results),
    })
    return {"success": True, "results": results}


@router.post("/user-tests/stop")
async def stop_user_tests():
    """停止全部账号认证测试：发送 Accounting-Stop 并清理在线会话（需求5）。"""
    stopped = await user_test.stop_user_tests()
    return {"success": True, "stopped": stopped}
