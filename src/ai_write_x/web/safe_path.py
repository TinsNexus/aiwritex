#!/usr/bin/env python
# -*- coding: UTF-8 -*-
"""路径安全校验 | Filesystem path confinement

Web 接口收到的路径/名称一律先经过这里，确保所有文件操作都被限制在
模板目录或文章目录之内。前端目前传的是绝对路径，因此 resolve_within()
同时接受绝对路径与相对路径，但两者都必须落在允许的根目录下。
"""

import re
from pathlib import Path

from fastapi import HTTPException

# 单段名称（分类名、模板名）中不允许出现的字符：
# 路径分隔符、Windows 保留字符、控制字符
_UNSAFE_NAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def safe_name(name: str, field: str = "name") -> str:
    """校验单段名称：不得为空、不得为 . 或 ..、不得含路径分隔符

    用于分类名、模板文件名等由用户输入、随后被拼进路径的片段。
    """
    cleaned = (name or "").strip()

    if not cleaned:
        raise HTTPException(status_code=400, detail=f"{field} must not be empty")

    if cleaned in (".", "..") or _UNSAFE_NAME_CHARS.search(cleaned):
        raise HTTPException(
            status_code=400,
            detail=f"{field} contains characters that are not allowed",
        )

    return cleaned


def resolve_within(user_path, root: Path) -> Path:
    """把用户提供的路径限制在 root 之内，越界返回 403

    绝对路径与相对路径都接受，但解析（含符号链接）后必须位于 root 之下。
    """
    root_resolved = Path(root).resolve()

    # 先判空字符串：Path("") 会变成 Path(".")，最终解析回 root 本身
    raw = str(user_path or "").strip()
    if not raw or raw in (".", "./"):
        raise HTTPException(status_code=400, detail="path must not be empty")

    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = root_resolved / candidate

    resolved = candidate.resolve()

    if resolved != root_resolved and not resolved.is_relative_to(root_resolved):
        raise HTTPException(status_code=403, detail="path is outside the allowed directory")

    return resolved
