#!/usr/bin/env python
# -*- coding: UTF-8 -*-
"""服务端语言包加载器 | Server-side locale loader

词条文件放在 web/static/locales 下，随 web 资源目录一起打包，无需额外的打包配置。
后端只负责读取词条并同步注入页面，翻译本身全部在前端完成（单一机制，避免遗漏）。
"""

import json
from functools import lru_cache
from pathlib import Path

# 回退语言：任何语言缺失的词条都会回退到这里
DEFAULT_LOCALE = "zh_CN"

# 语言显示名称（用于界面上的语言选择器，各语言均以本族语书写）
LOCALE_DISPLAY_NAMES = {
    "zh_CN": "简体中文",
    "vi": "Tiếng Việt",
}


def get_locales_dir() -> Path:
    """词条目录：与 web 静态资源同级，随 web 目录打包"""
    from src.ai_write_x.utils import utils

    if utils.get_is_release_ver():
        return Path(utils.get_res_path("web")) / "static" / "locales"
    return Path(__file__).parent / "static" / "locales"


def get_available_locales() -> list:
    """扫描词条目录，返回可用语言代码列表"""
    locales_dir = get_locales_dir()
    if not locales_dir.exists():
        return [DEFAULT_LOCALE]

    found = sorted(p.stem for p in locales_dir.glob("*.json"))
    if DEFAULT_LOCALE in found:
        # 默认语言排在最前
        found.remove(DEFAULT_LOCALE)
        found.insert(0, DEFAULT_LOCALE)
    return found or [DEFAULT_LOCALE]


@lru_cache(maxsize=8)
def load_messages(locale: str) -> dict:
    """读取指定语言的词条，失败时返回空字典（由回退语言兜底）"""
    locale_file = get_locales_dir() / f"{locale}.json"
    if not locale_file.exists():
        return {}
    try:
        return json.loads(locale_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def get_locale_bootstrap(locale: str) -> dict:
    """构造注入页面的 i18n 引导数据"""
    if locale not in get_available_locales():
        locale = DEFAULT_LOCALE

    return {
        "locale": locale,
        "messages": load_messages(locale),
        # 回退词条：默认语言，保证新增词条未翻译时界面不出现原始 key
        "fallback": load_messages(DEFAULT_LOCALE) if locale != DEFAULT_LOCALE else {},
        "available": [
            {"value": code, "label": LOCALE_DISPLAY_NAMES.get(code, code)}
            for code in get_available_locales()
        ],
    }


def translate(key: str, locale: str = None, **params) -> str:
    """服务端取词条：当前语言 -> 回退语言(zh_CN) -> key 本身

    仅用于 API 响应中直接回给界面的文本（前端把它们当普通字符串消费）。
    页面内的静态文案一律走前端 data-i18n / i18n.t()，避免两套机制。
    """
    if locale is None:
        locale = get_saved_locale()

    text = load_messages(locale).get(key)
    if text is None:
        text = load_messages(DEFAULT_LOCALE).get(key, key)

    if params:
        for name, value in params.items():
            text = text.replace("{" + name + "}", str(value))
    return text


def get_saved_locale() -> str:
    """从 ui_config.json 读取用户选择的界面语言"""
    from src.ai_write_x.utils.path_manager import PathManager

    config_file = PathManager.get_config_dir() / "ui_config.json"
    if not config_file.exists():
        return DEFAULT_LOCALE
    try:
        ui_config = json.loads(config_file.read_text(encoding="utf-8"))
        return ui_config.get("locale") or DEFAULT_LOCALE
    except (json.JSONDecodeError, OSError):
        return DEFAULT_LOCALE
