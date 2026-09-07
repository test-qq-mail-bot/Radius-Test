# -*- coding: utf-8 -*-
"""
Dictionary 管理接口模块。

提供：
    GET    /api/dictionaries                 模板列表
    GET    /api/dictionaries/{name}          模板明细
    POST   /api/dictionaries/derive          从内置模板派生自定义模板
    POST   /api/dictionaries/upload          上传自定义模板
    DELETE /api/dictionaries/{name}          删除自定义模板
    GET    /api/dictionaries/{name}/export   导出模板 YAML
    POST   /api/dictionaries/reload          重新加载全部模板

规则（项目书 18.x）：
    1. 内置模板位于源码内部，只读，不可修改；
    2. 自定义模板位于 data/dictionaries/，可增删改；
    3. 非法自定义模板在加载时被忽略。
"""

import io
from typing import Any, Dict

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

from ..common import file_util, paths
from ..common.errors import DictionaryError
from ..common.validator import is_valid_template_name
from ..dictionary import loader as dict_loader
from ..dictionary import registry
from ..logging import logger

router = APIRouter(prefix="/api/dictionaries", tags=["dictionaries"])


@router.get("")
async def list_templates():
    """返回全部模板摘要。"""
    store = dict_loader.get_store()
    return {
        "templates": store.summary(),
        "total": len(store.templates),
        "registry_file": str(paths.radius_yaml_path()),
        "custom_dir": str(paths.dictionaries_dir()),
    }


@router.post("/reload")
async def reload_templates():
    """重新加载全部模板并同步 radius.yaml 登记。"""
    store = dict_loader.get_store()
    store.reload()
    added = registry.sync_registry(store.summary())
    logger.info("api", "Dictionary 已重新加载", {"count": len(store.templates)})
    return {
        "success": True,
        "templates": store.summary(),
        "registry_added": added,
    }


@router.get("/{name}")
async def get_template(name: str):
    """返回模板明细。"""
    store = dict_loader.get_store()
    template = store.get(name)
    if template is None:
        raise HTTPException(status_code=404, detail="模板不存在")
    return template.to_dict()


@router.get("/{name}/export")
async def export_template(name: str):
    """导出模板 YAML。"""
    store = dict_loader.get_store()
    template = store.get(name)
    if template is None:
        raise HTTPException(status_code=404, detail="模板不存在")
    source = paths.dictionaries_dir() / template.file
    if template.source == "builtin":
        source = paths.builtin_dictionary_dir() / template.file
    if not source.is_file():
        raise HTTPException(status_code=404, detail="模板文件不存在")
    content = file_util.read_text(source)
    buffer = io.BytesIO(content.encode("utf-8"))
    headers = {"Content-Disposition": 'attachment; filename="%s"' % template.file}
    return StreamingResponse(buffer, media_type="application/x-yaml", headers=headers)


@router.post("/derive")
async def derive_template(payload: Dict[str, Any]):
    """
    从已有模板派生一个自定义模板。

    请求体：
        {"source": "RFC2865", "new_name": "MyCompany", "vendor_id": 12345}

    说明：
        派生结果写入 data/dictionaries/{new_name}.yaml，
        用户可在该文件中自由增删改属性，内置模板始终保持只读。
    """
    source_name = str(payload.get("source") or "").strip()
    new_name = str(payload.get("new_name") or "").strip()
    if not source_name:
        raise HTTPException(status_code=400, detail="源模板名称不能为空")
    if not is_valid_template_name(new_name):
        raise HTTPException(status_code=400, detail="新模板名称非法，只允许字母、数字、下划线与短横线")
    store = dict_loader.get_store()
    source = store.get(source_name)
    if source is None:
        raise HTTPException(status_code=404, detail="源模板不存在")
    if store.get(new_name) is not None:
        raise HTTPException(status_code=400, detail="同名模板已存在")
    raw_vendor_id = payload.get("vendor_id")
    vendor_id = source.vendor_id
    if raw_vendor_id is not None and str(raw_vendor_id).strip() != "":
        try:
            vendor_id = int(raw_vendor_id)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="厂商编号必须是整数")
    data = {
        "template": new_name,
        "vendor": str(payload.get("vendor") or source.vendor or new_name),
        "vendor_id": vendor_id,
        "attributes": [a.to_dict() for a in source.attributes],
    }
    from ..common import yaml_util

    content = yaml_util.dump_yaml(data)
    target = paths.dictionaries_dir() / ("%s.yaml" % new_name)
    file_util.write_text_atomic(target, content)
    store.reload()
    registry.sync_registry(store.summary())
    logger.info("api", "已从内置模板派生自定义模板", {
        "source": source_name,
        "new_name": new_name,
        "attributes": len(source.attributes),
    })
    return {
        "success": True,
        "file": target.name,
        "attribute_count": len(source.attributes),
        "templates": store.summary(),
    }


@router.post("/upload")
async def upload_template(file: UploadFile = File(...)):
    """上传自定义模板 YAML。"""
    filename = (file.filename or "").lower()
    if not (filename.endswith(".yaml") or filename.endswith(".yml")):
        raise HTTPException(status_code=400, detail="只支持 YAML 文件")
    raw = await file.read()
    if len(raw) > 5 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="文件过大，上限 5 MB")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="文件编码必须是 UTF-8")
    # 后端必须再次验证（前端限制不能替代后端验证）
    try:
        template = dict_loader.parse_template(
            __import__("yaml").safe_load(text), source="custom", file=filename)
    except DictionaryError as exc:
        raise HTTPException(status_code=400, detail="模板格式不合法；%s" % exc)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="模板解析失败；%s" % exc)
    if not is_valid_template_name(template.name):
        raise HTTPException(status_code=400, detail="模板名称非法")
    target = paths.dictionaries_dir() / ("%s.yaml" % template.name)
    file_util.write_text_atomic(target, text)
    store = dict_loader.get_store()
    store.reload()
    registry.sync_registry(store.summary())
    logger.info("api", "已上传自定义模板", {"name": template.name})
    return {"success": True, "file": target.name, "templates": store.summary()}


@router.delete("/{name}")
async def delete_template(name: str):
    """删除自定义模板（内置模板不可删除）。"""
    store = dict_loader.get_store()
    template = store.get(name)
    if template is None:
        raise HTTPException(status_code=404, detail="模板不存在")
    if template.source != "custom":
        raise HTTPException(status_code=400, detail="内置模板不可删除，请使用派生功能")
    target = paths.dictionaries_dir() / template.file
    if not file_util.safe_remove(target):
        raise HTTPException(status_code=404, detail="模板文件不存在或删除失败")
    store.reload()
    logger.info("api", "已删除自定义模板", {"name": name})
    return {"success": True, "templates": store.summary()}
