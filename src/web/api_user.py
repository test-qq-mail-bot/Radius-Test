# -*- coding: utf-8 -*-
"""
用户管理接口模块。

提供：
    GET    /api/users               列表
    POST   /api/users               新增/覆盖（用户名唯一键，密码留空=不修改）
    PUT    /api/users/{username}    修改
    DELETE /api/users/{username}    删除
    POST   /api/users/import        导入 CSV（逐行容错，返回成败明细，一律覆盖）
    GET    /api/users/template      下载导入模板 CSV
    GET    /api/users/export        导出 CSV（无需登录与密码，含全部用户）

数据源：data/users.csv（项目书 10.1，不使用用户数据库）
"""

import io
from typing import Any, Dict

from fastapi import APIRouter, File, HTTPException, UploadFile
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
    """
    新增或覆盖用户（用户名为唯一键）。

    规则：
        1. username 为唯一键，已存在则覆盖更新该用户（不再报「用户名已存在」）；
        2. 密码为空且用户已存在时，保留原密码——密码留空代表不修改密码；
        3. 新用户必须提供合法密码；
        4. 覆盖更新时 enabled 保持原值不变（表单无该字段，避免误改启用状态）。

    返回 created / updated 标记，供前端区分「已新增」与「已更新」。
    """
    username = str(payload.get("username") or "").strip()
    password = str(payload.get("password") or "")
    if not is_valid_username(username):
        raise HTTPException(status_code=400, detail="用户名非法")
    users = _load_users()
    for index, user in enumerate(users):
        if user["username"] == username:
            if password:
                if not is_valid_password(password):
                    raise HTTPException(status_code=400, detail="密码非法")
                users[index]["password"] = password
            users[index]["remark"] = str(payload.get("remark") or "")
            _save_users(users)
            logger.info("api", "已覆盖更新用户", {"username": username})
            return {
                "success": True,
                "user": users[index],
                "created": False,
                "updated": True,
            }
    if not is_valid_password(password):
        raise HTTPException(status_code=400, detail="密码非法")
    user = {
        "username": username,
        "password": password,
        "enabled": bool(payload.get("enabled", True)),
        "remark": str(payload.get("remark") or ""),
    }
    users.append(user)
    _save_users(users)
    logger.info("api", "已新增用户", {"username": username})
    return {"success": True, "user": user, "created": True, "updated": False}


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
async def import_users(file: UploadFile = File(...)):
    """
    导入用户 CSV（逐行容错，合法行全部导入，非法行返回明细）。

    参数：
        file: CSV 文件

    规则：
        1. 用户名是唯一键，同名用户**一律覆盖**（不再提供不覆盖选项）；
        2. 密码为空且该用户已存在 → 保留原密码（密码留空代表不修改）；
        3. 密码为空且该用户不存在 → 该行判为失败（新用户必须有密码）；
        4. 单行非法不影响其他行，导入结束后返回成功与失败条数。

    返回：
        total    解析出的合法行数
        added    新增条数
        updated  覆盖条数
        failed   失败条数
        failures 失败明细 [{line, username, reason}]
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

    imported, failures = csv_util.parse_users_csv_rows(text)
    if not imported:
        logger.warning("api", "用户导入无有效数据", {"failed": len(failures)})
        return {
            "success": False,
            "message": "未解析到有效用户数据",
            "total": 0,
            "added": 0,
            "updated": 0,
            "failed": len(failures),
            "failures": failures[:50],
        }

    users = _load_users()
    index = {u["username"]: i for i, u in enumerate(users)}
    added = 0
    updated = 0
    for user in imported:
        # 行号仅用于失败反馈，入库前必须移除，避免污染用户数据
        line_no = user.pop("_line", 0)
        name = user["username"]
        if not user["password"]:
            if name in index:
                user["password"] = users[index[name]]["password"]
            else:
                failures.append({
                    "line": line_no, "username": name, "reason": "新用户缺少密码"})
                continue
        if name in index:
            users[index[name]] = user
            updated += 1
        else:
            users.append(user)
            index[name] = len(users) - 1
            added += 1
    if added or updated:
        _save_users(users)
    logger.info("api", "用户导入完成",
                {"added": added, "updated": updated, "failed": len(failures)})
    return {
        "success": True,
        "total": len(imported),
        "added": added,
        "updated": updated,
        "failed": len(failures),
        "failures": failures[:50],
    }


@router.get("/template")
async def download_users_template():
    """
    下载用户导入模板 CSV。

    供「导入用户」弹窗的「导入文件下载」按钮使用，
    内容与新建 data/users.csv 时使用的模板一致（项目书 10.2）。
    """
    buffer = io.BytesIO(csv_util.USER_CSV_TEMPLATE.encode("utf-8-sig"))
    headers = {
        "Content-Disposition": 'attachment; filename="users-template.csv"',
    }
    logger.info("api", "用户导入模板下载完成")
    return StreamingResponse(buffer, media_type="text/csv", headers=headers)


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
