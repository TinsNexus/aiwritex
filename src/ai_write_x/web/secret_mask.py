#!/usr/bin/env python
# -*- coding: UTF-8 -*-
"""配置密钥脱敏 | Masking of secrets in config responses

`GET /api/config/` 原先明文返回全部 api_key 与公众号 appsecret，任何本机进程
或取得同源能力的脚本一次请求即可取走全部凭证。现在返回脱敏值。

难点在于界面是"读出来 → 编辑 → 整体回传"的：如果只做脱敏，用户一保存就会把
掩码字符串当成真实密钥写回去。因此这里成对提供：

- mask_config()   —— 出站脱敏
- unmask_config() —— 入站还原：凡是掩码值一律用已存储的真实值替换

掩码形如 ``••••••••abcd``（保留末 4 位便于辨认）。真实密钥都是 ASCII，
不会包含 U+2022，因此"是否含 •"是可靠的判据。
"""

import copy

MASK_CHAR = "•"  # •
MASK_BODY = MASK_CHAR * 8


def is_masked(value) -> bool:
    """判断某个值是否是本模块产生的掩码"""
    return isinstance(value, str) and MASK_CHAR in value


def mask_secret(value):
    """把单个密钥转成掩码；空值与非字符串原样返回"""
    if not isinstance(value, str) or not value:
        return value
    # 只在足够长时保留末 4 位，避免短值几乎等于明文
    tail = value[-4:] if len(value) > 8 else ""
    return MASK_BODY + tail


def _mask_in_place(container, key):
    """对 container[key] 脱敏，支持字符串与字符串列表两种形态"""
    if not isinstance(container, dict) or key not in container:
        return
    value = container[key]
    if isinstance(value, list):
        container[key] = [mask_secret(v) for v in value]
    else:
        container[key] = mask_secret(value)


def _restore_in_place(incoming, stored, key):
    """把 incoming[key] 中的掩码值还原成 stored[key] 中的真实值

    列表按"掩码值 -> 真实值"匹配而非按下标，这样用户删除或调换某个 key 之后
    仍能对上；匹配不到时退回按下标还原；再不行则丢弃该项
    （掩码字符串本身绝不能被当作真实密钥写入）。
    """
    if not isinstance(incoming, dict) or key not in incoming:
        return
    stored_value = stored.get(key) if isinstance(stored, dict) else None
    value = incoming[key]

    if isinstance(value, list):
        stored_list = stored_value if isinstance(stored_value, list) else []
        lookup = {}
        for item in stored_list:
            if isinstance(item, str) and item:
                lookup.setdefault(mask_secret(item), item)

        restored = []
        for index, item in enumerate(value):
            if not is_masked(item):
                restored.append(item)
                continue
            if item in lookup:
                restored.append(lookup[item])
            elif index < len(stored_list):
                restored.append(stored_list[index])
            # 匹配不到就丢弃，避免把 •••• 存成密钥
        incoming[key] = restored
    elif is_masked(value):
        incoming[key] = stored_value if isinstance(stored_value, str) else ""


def _walk(config, aiforge_config, handler):
    """遍历所有密钥字段，对每一处调用 handler(container, stored_container, key)

    覆盖：api.<厂商>.api_key(列表)、img_api.<厂商>.api_key、
    wechat.credentials[].appsecret、aiforge_config.llm.<厂商>.api_key
    """
    for section in ("api", "img_api"):
        node = config.get(section) if isinstance(config, dict) else None
        if not isinstance(node, dict):
            continue
        for provider, provider_cfg in node.items():
            if provider == "api_type" or not isinstance(provider_cfg, dict):
                continue
            handler(provider_cfg, provider, section, "api_key")

    wechat = config.get("wechat") if isinstance(config, dict) else None
    if isinstance(wechat, dict) and isinstance(wechat.get("credentials"), list):
        for index, cred in enumerate(wechat["credentials"]):
            if isinstance(cred, dict):
                handler(cred, index, "wechat", "appsecret")

    llm = aiforge_config.get("llm") if isinstance(aiforge_config, dict) else None
    if isinstance(llm, dict):
        for provider, provider_cfg in llm.items():
            if isinstance(provider_cfg, dict):
                handler(provider_cfg, provider, "llm", "api_key")


def mask_config(config: dict, aiforge_config: dict = None):
    """返回脱敏后的深拷贝，不改动传入对象"""
    masked_config = copy.deepcopy(config) if isinstance(config, dict) else config
    masked_aiforge = copy.deepcopy(aiforge_config) if isinstance(aiforge_config, dict) else aiforge_config

    def handler(container, _ident, _section, key):
        _mask_in_place(container, key)

    _walk(masked_config, masked_aiforge, handler)
    return masked_config, masked_aiforge


def unmask_config(incoming: dict, stored_config: dict, stored_aiforge: dict = None):
    """就地把 incoming 中的掩码值还原成已存储的真实值

    incoming 可能只是部分配置（界面是增量 PATCH），未出现的字段不受影响。
    """
    incoming_aiforge = incoming.get("aiforge_config") if isinstance(incoming, dict) else None

    def handler(container, ident, section, key):
        if section == "wechat":
            creds = (stored_config or {}).get("wechat", {}).get("credentials", [])
            stored = creds[ident] if isinstance(creds, list) and ident < len(creds) else {}
        elif section == "llm":
            stored = (stored_aiforge or {}).get("llm", {}).get(ident, {})
        else:
            stored = (stored_config or {}).get(section, {}).get(ident, {})
        _restore_in_place(container, stored if isinstance(stored, dict) else {}, key)

    _walk(incoming, incoming_aiforge, handler)
    return incoming
