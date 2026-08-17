import shutil
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel

from src.ai_write_x.utils.path_manager import PathManager

from src.ai_write_x.web.i18n import translate
from src.ai_write_x.web.safe_path import resolve_within, safe_name
from src.ai_write_x.web.local_guard import PREVIEW_CSP


router = APIRouter(prefix="/api/templates", tags=["templates"])


# Pydantic 模型定义
class TemplateContentUpdate(BaseModel):
    content: str


class TemplateCreate(BaseModel):
    name: str
    category: str
    content: str = ""


class TemplateCopy(BaseModel):
    source_path: str
    new_name: str
    target_category: str


class TemplateMove(BaseModel):
    source_path: str
    target_category: str


class CategoryCreate(BaseModel):
    name: str


class CategoryRename(BaseModel):
    old_name: str
    new_name: str


class TemplateRename(BaseModel):
    old_path: str
    new_name: str


@router.get("/categories")
async def list_categories():
    """获取所有分类"""
    template_dir = PathManager.get_template_dir()
    categories = []

    # 排除的目录名称
    excluded_dirs = {"components", "__pycache__", ".git"}

    for item in template_dir.iterdir():
        if item.is_dir() and item.name not in excluded_dirs:
            template_count = len(list(item.glob("*.html")))
            categories.append(
                {"name": item.name, "path": str(item), "template_count": template_count}
            )

    return {"status": "success", "data": categories}


@router.post("/categories")
async def create_category(category: CategoryCreate):
    """创建新分类"""
    template_dir = PathManager.get_template_dir()
    category_path = template_dir / safe_name(category.name, "category")

    if category_path.exists():
        raise HTTPException(status_code=409, detail=translate("api.category_exists"))

    category_path.mkdir(parents=True, exist_ok=True)
    return {"status": "success", "message": translate("api.category_created")}


@router.put("/categories/{category_name}")
async def rename_category(category_name: str, rename_data: CategoryRename):
    """重命名分类"""
    template_dir = PathManager.get_template_dir()
    old_path = template_dir / safe_name(category_name, "category")
    new_path = template_dir / safe_name(rename_data.new_name, "new_name")

    if not old_path.exists():
        raise HTTPException(status_code=404, detail=translate("api.category_not_found"))

    if new_path.exists():
        raise HTTPException(status_code=409, detail=translate("api.category_target_exists"))

    # 重命名目录
    old_path.rename(new_path)

    return {
        "status": "success",
        "message": translate("api.category_renamed"),
        "old_name": category_name,
        "new_name": rename_data.new_name,
    }


@router.delete("/categories/{category_name}")
async def delete_category(category_name: str, force: bool = False):
    """删除分类"""
    template_dir = PathManager.get_template_dir()
    category_path = template_dir / safe_name(category_name, "category")

    if not category_path.exists():
        raise HTTPException(status_code=404, detail=translate("api.category_not_found"))

    templates = list(category_path.glob("*.html"))
    if templates and not force:
        raise HTTPException(status_code=400, detail=translate("api.category_not_empty", count=len(templates)))

    shutil.rmtree(category_path)
    return {"status": "success", "message": translate("api.category_deleted")}


@router.get("/default-template-categories")
async def get_default_template_categories():
    """获取系统默认模板分类"""
    try:
        from src.ai_write_x.config.config import DEFAULT_TEMPLATE_CATEGORIES

        # 返回中文名称列表
        categories = list(DEFAULT_TEMPLATE_CATEGORIES.values())

        return {"status": "success", "data": categories}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/")
async def list_templates(category: str = None):
    """获取模板列表"""
    templates = []
    template_dir = PathManager.get_template_dir()

    # 排除的目录名称
    excluded_dirs = {"components", "__pycache__", ".git"}

    if category:
        category_path = template_dir / safe_name(category, "category")
        if category_path.exists():
            for file in category_path.glob("*.html"):
                templates.append(
                    {
                        "name": file.stem,
                        "path": str(file),
                        "category": category,
                        "size": f"{file.stat().st_size / 1024:.2f} KB",
                        "create_time": datetime.fromtimestamp(file.stat().st_ctime).strftime(
                            "%Y-%m-%d %H:%M:%S"
                        ),
                    }
                )
    else:
        # 返回所有分类的模板 - 添加过滤
        for category_dir in template_dir.iterdir():
            if category_dir.is_dir() and category_dir.name not in excluded_dirs:  # 添加过滤条件
                for file in category_dir.glob("*.html"):
                    templates.append(
                        {
                            "name": file.stem,
                            "path": str(file),
                            "category": category_dir.name,
                            "size": f"{file.stat().st_size / 1024:.2f} KB",
                            "create_time": datetime.fromtimestamp(file.stat().st_ctime).strftime(
                                "%Y-%m-%d %H:%M:%S"
                            ),
                        }
                    )

    return {"status": "success", "data": templates}


@router.get("/content/{template_path:path}")
async def get_template_content(template_path: str):
    """获取模板内容"""
    file_path = resolve_within(template_path, PathManager.get_template_dir())
    if not file_path.exists():
        raise HTTPException(status_code=404, detail=translate("api.template_not_found"))

    content = file_path.read_text(encoding="utf-8")
    # 返回纯文本,让JavaScript处理渲染
    return Response(content=content, media_type="text/plain; charset=utf-8")


@router.put("/content/{template_path:path}")
async def update_template_content(template_path: str, update: TemplateContentUpdate):
    """更新模板内容"""
    file_path = resolve_within(template_path, PathManager.get_template_dir())
    if not file_path.exists():
        raise HTTPException(status_code=404, detail=translate("api.template_not_found"))

    file_path.write_text(update.content, encoding="utf-8")
    return {"status": "success", "message": translate("api.template_saved")}


@router.get("/preview/{template_path:path}")
async def preview_template(template_path: str):
    """安全预览模板(返回HTML响应)"""
    file_path = resolve_within(template_path, PathManager.get_template_dir())
    if not file_path.exists():
        return HTMLResponse("<p>模板不存在</p>")

    content = file_path.read_text(encoding="utf-8")
    return HTMLResponse(
        content, headers={"Content-Security-Policy": PREVIEW_CSP}
    )


@router.delete("/{template_path:path}")
async def delete_template(template_path: str):
    """删除模板"""
    file_path = resolve_within(template_path, PathManager.get_template_dir())
    if file_path.exists():
        file_path.unlink()
        return {"status": "success", "message": translate("api.template_deleted")}
    raise HTTPException(status_code=404, detail=translate("api.template_not_found"))


@router.post("/")
async def create_template(template: TemplateCreate):
    """创建新模板"""
    template_dir = PathManager.get_template_dir()
    category_path = template_dir / safe_name(template.category, "category")
    category_path.mkdir(parents=True, exist_ok=True)

    file_path = category_path / f"{safe_name(template.name, 'name')}.html"
    if file_path.exists():
        raise HTTPException(status_code=409, detail=translate("api.template_exists"))

    file_path.write_text(template.content, encoding="utf-8")
    return {"status": "success", "message": translate("api.template_created"), "path": str(file_path)}


@router.post("/rename")
async def rename_template(rename_data: TemplateRename):
    """重命名模板"""
    source = resolve_within(rename_data.old_path, PathManager.get_template_dir())
    if not source.exists():
        raise HTTPException(status_code=404, detail=translate("api.template_not_found"))

    # 获取目标路径(同一目录下,只改文件名)
    target_path = source.parent / f"{safe_name(rename_data.new_name, 'new_name')}.html"

    if target_path.exists():
        raise HTTPException(status_code=409, detail=translate("api.template_target_exists"))

    # 重命名文件
    source.rename(target_path)

    return {"status": "success", "message": translate("api.template_renamed"), "path": str(target_path)}


@router.post("/copy")
async def copy_template(copy_data: TemplateCopy):
    """复制模板"""
    source = resolve_within(copy_data.source_path, PathManager.get_template_dir())
    if not source.exists():
        raise HTTPException(status_code=404, detail=translate("api.template_source_not_found"))

    template_dir = PathManager.get_template_dir()
    target_dir = template_dir / safe_name(copy_data.target_category, "target_category")
    target_dir.mkdir(parents=True, exist_ok=True)

    target_path = target_dir / f"{safe_name(copy_data.new_name, 'new_name')}.html"
    shutil.copy2(source, target_path)
    return {"status": "success", "path": str(target_path)}


@router.put("/move")
async def move_template(move_data: TemplateMove):
    """移动模板到其他分类"""
    source = resolve_within(move_data.source_path, PathManager.get_template_dir())
    if not source.exists():
        raise HTTPException(status_code=404, detail=translate("api.template_not_found"))

    template_dir = PathManager.get_template_dir()
    target_dir = template_dir / safe_name(move_data.target_category, "target_category")
    target_dir.mkdir(parents=True, exist_ok=True)

    target_path = target_dir / source.name
    shutil.move(str(source), str(target_path))
    return {"status": "success", "path": str(target_path)}
