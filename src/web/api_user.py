# -*- coding: utf-8 -*-
"""
用户管理接口模块。

提供：
    GET    /api/users               列表
    POST   /api/users               新增
    PUT    /api/users/{username}    修改
    DELETE /api/users/{username}    删除
    POST   /api/users/import        导入 CSV
    GET    /api/users/export        导出 CSV（无需登录与密码）

数据源：data/users.csv（项目书 10.1，不使用用户数据库）
"""

import io
from typing import Any, Dict

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

from ..common import csv_util, file_util, paths
from ..common.errors import ValidationError
from ..common.validator import is_valid_password, is_valid_username
from ..logging import logger

router = APIRouter(prefix="/api/users", tags=["users"])


def _load_users() -> list:
    """从 users.csv 读取用户列表。"""
    if not paths.users_csv_path().is_file():
        file_util.create_if_missing(
            paths.users_csv_path(), lambda: csv_util.USER_CSV_TEMPLATE)
    text = file_util.read_text(paths.users_csv_path())
    try:
        return csv_util.parse_users_csv(text)
    except ValidationError as exc:
        logger.error("api", "users.csv 解析失败", {"error": str(exc)})
        return []


def _save_users(users: list) -> None:
    """把用户列表写回 users.csv。"""
    file_util.write_text_atomic(paths.users_csv_path(), csv_util.render_users_csv(users))


@router.get("")
async def list_users():
    """返回全部用户。"""
    users = _load_users()
    return {
        "users": users,
        "total": len(users),
        "fields": list(csv_util.USER_FIELDS),
    }


@router.post("")
async def create_user(payload: Dict[str, Any]):
    """新增用户。"""
    username = str(payload.get("username") or "").strip()
    password = str(payload.get("password") or "")
    if not is_valid_username(username):
        raise HTTPException(status_code=400, detail="用户名非法")
    if not is_valid_password(password):
        raise HTTPException(status_code=400, detail="密码非法")
    users = _load_users()
    if any(u["username"] == username for u in users):
        raise HTTPException(status_code=400, detail="用户名已存在")
    user = {
        "username": username,
        "password": password,
        "enabled": bool(payload.get("enabled", True)),
        "remark": str(payload.get("remark") or ""),
    }
    users.append(user)
    _save_users(users)
    logger.info("api", "已新增用户", {"username": username})
    return {"success": True, "user": user}


@router.post("/batch-delete")
async def batch_delete_users(payload: Dict[str, Any]):
    """批量删除用户，内部复用单条删除逻辑。"""
    usernames = payload.get("usernames") or []
    if not isinstance(usernames, list) or not usernames:
        raise HTTPException(status_code=400, detail="usernames 不能为空")
    users = _load_users()
    removed = []
    failed = []
    name_set = {str(u["username"]) for u in users}
    for raw in usernames:
        username = str(raw).strip()
        if not username:
            continue
        if username in name_set:
            users = [u for u in users if u["username"] != username]
            name_set.discard(username)
            removed.append(username)
        else:
            failed.append({"username": username, "reason": "用户不存在"})
    if removed:
        _save_users(users)
    logger.info("api", "批量删除用户完成", {"removed": len(removed), "failed": len(failed)})
    return {"success": True, "removed": removed, "failed": failed}


@router.put("/{username}")
async def update_user(username: str, payload: Dict[str, Any]):
    """修改用户。"""
    users = _load_users()
    for index, user in enumerate(users):
        if user["username"] == username:
            if "password" in payload:
                if not is_valid_password(payload["password"]):
                    raise HTTPException(status_code=400, detail="密码非法")
                users[index]["password"] = str(payload["password"])
            if "enabled" in payload:
                users[index]["enabled"] = bool(payload["enabled"])
            if "remark" in payload:
                users[index]["remark"] = str(payload["remark"] or "")
            _save_users(users)
            logger.info("api", "已修改用户", {"username": username})
            return {"success": True, "user": users[index]}
    raise HTTPException(status_code=404, detail="用户不存在")


@router.delete("/{username}")
async def delete_user(username: str):
    """删除用户。"""
    users = _load_users()
    remaining = [u for u in users if u["username"] != username]
    if len(remaining) == len(users):
        raise HTTPException(status_code=404, detail="用户不存在")
    _save_users(remaining)
    logger.info("api", "已删除用户", {"username": username})
    return {"success": True}


@router.post("/import")
async def import_users(file: UploadFile = File(...), overwrite: bool = Form(False)):
    """
    导入用户 CSV。

    参数：
        file: CSV 文件
        overwrite: 同名用户是否覆盖

    说明：
        导入不会覆盖整个 users.csv，
        只把解析成功的用户追加进去，同名用户按 overwrite 决定处理方式。
    """
    filename = (file.filename or "").lower()
    if not filename.endswith(".csv"):
        raise HTTPException(status_code=400, detail="只支持 CSV 文件")
    raw = await file.read()
    if len(raw) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="文件过大，上限 10 MB")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="文件编码必须是 UTF-8")
    try:
        imported = csv_util.parse_users_csv(text)
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if not imported:
        raise HTTPException(status_code=400, detail="未解析到有效用户数据")
    users = _load_users()
    added, updated = csv_util.merge_users(users, imported, overwrite)
    _save_users(users)
    logger.info("api", "用户导入完成", {"added": added, "updated": updated})
    return {
        "success": True,
        "added": added,
        "updated": updated,
        "skipped": len(imported) - added - updated,
        "total": len(users),
    }


@router.get("/export")
async def export_users():
    """
    导出用户 CSV。

    说明（项目书 10.4）：
        不需要管理员账号、不需要密码、不需要登录认证；
        导出的 CSV 包含注释模板，可直接作为下一次导入的数据基础。
    """
    users = _load_users()
    content = csv_util.render_users_csv(users)
    buffer = io.BytesIO(content.encode("utf-8-sig"))
    headers = {
        "Content-Disposition": 'attachment; filename="users.csv"',
    }
    logger.info("api", "用户导出完成", {"count": len(users)})
    return StreamingResponse(buffer, media_type="text/csv", headers=headers)
