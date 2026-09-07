# -*- coding: utf-8 -*-
"""
CSV 工具模块。

职责：
    读写 data/users.csv（用户主数据，项目书第 10 节）。

格式约定：
    1. 文件包含以 # 开头的注释模板；
    2. 有效数据行字段为 username,password,enabled,remark；
    3. 解析时自动跳过注释行与空行；
    4. 导出时保留注释模板，可直接作为下一次导入的数据基础。
"""

import csv
import io
from typing import List, Tuple

from .errors import ValidationError
from .validator import is_valid_password, is_valid_username

# 用户 CSV 表头
USER_FIELDS = ("username", "password", "enabled", "remark")

# users.csv 初始模板（项目书 10.2）
USER_CSV_TEMPLATE = (
    "# Radius-Test 用户CSV模板\n"
    "#\n"
    "# 第一行为字段名称；\n"
    "#\n"
    "# username：用户名，必填；\n"
    "# password：密码，必填；\n"
    "# enabled：是否启用，只允许true或false；\n"
    "# remark：备注，可为空；\n"
    "\n"
    "username,password,enabled,remark\n"
    "\n"
    "# test001,123456,true,测试用户1\n"
    "# test002,123456,true,测试用户2\n"
)


def _normalize_enabled(value: str) -> bool:
    """
    把 enabled 字段归一化为布尔值。

    允许：true/false（不区分大小写）、1/0、yes/no、是/否、空值视为 true。
    """
    text = (value or "").strip().lower()
    if text in ("", "true", "1", "yes", "y", "是", "on"):
        return True
    if text in ("false", "0", "no", "n", "否", "off"):
        return False
    raise ValidationError("enabled 字段取值非法", "实际=%s；只允许 true 或 false" % value)


def parse_users_csv(text: str) -> List[dict]:
    """
    解析用户 CSV 文本。

    参数：
        text: CSV 文本内容

    返回：
        用户字典列表，键为 username/password/enabled/remark。

    说明：
        # 开头的整行注释被跳过；空行被跳过；首行表头被跳过。
    """
    users = []
    seen = set()
    reader = csv.reader(io.StringIO(text))
    header_passed = False
    for row in reader:
        if not row:
            continue
        first = (row[0] or "").strip()
        if first.startswith("#") or first == "":
            continue
        cells = [c.strip() for c in row]
        if not header_passed:
            # 遇到表头行，跳过
            if [c.lower() for c in cells[:2]] == ["username", "password"]:
                header_passed = True
            continue
        username = cells[0]
        password = cells[1] if len(cells) > 1 else ""
        enabled_raw = cells[2] if len(cells) > 2 else "true"
        remark = cells[3] if len(cells) > 3 else ""
        if not is_valid_username(username):
            raise ValidationError("用户名非法", "用户名=%s" % username)
        if not is_valid_password(password):
            raise ValidationError("密码非法", "用户名=%s" % username)
        if username in seen:
            raise ValidationError("导入文件中存在重复用户名", "用户名=%s" % username)
        seen.add(username)
        users.append({
            "username": username,
            "password": password,
            "enabled": _normalize_enabled(enabled_raw),
            "remark": remark,
        })
    return users


def render_users_csv(users: List[dict]) -> str:
    """
    生成用户 CSV 文本（含注释模板）。

    生成结果可直接作为下一次导入的数据基础。
    """
    buffer = io.StringIO()
    buffer.write(USER_CSV_TEMPLATE)
    buffer.write("\n")
    writer = csv.writer(buffer, lineterminator="\n")
    for user in users:
        writer.writerow([
            user.get("username", ""),
            user.get("password", ""),
            "true" if user.get("enabled", True) else "false",
            user.get("remark", ""),
        ])
    return buffer.getvalue()


def merge_users(existing: List[dict], imported: List[dict], overwrite: bool) -> Tuple[int, int]:
    """
    合并导入用户到已有用户列表（项目书 10.3）。

    参数：
        existing: 已有用户列表（原地修改）
        imported: 导入用户列表
        overwrite: 同名用户是否覆盖

    返回：
        (新增数量, 更新数量)
    """
    index = {u["username"]: i for i, u in enumerate(existing)}
    added = 0
    updated = 0
    for user in imported:
        name = user["username"]
        if name in index:
            if overwrite:
                existing[index[name]] = user
                updated += 1
        else:
            existing.append(user)
            index[name] = len(existing) - 1
            added += 1
    return added, updated
