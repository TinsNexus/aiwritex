#!/usr/bin/env python
# -*- coding: UTF-8 -*-
"""本地访问守卫 | Host/Origin guard for the local HTTP server

服务只监听 127.0.0.1，但"只听本地"并不等于"只有本应用能访问"：

1. **DNS rebinding**：攻击者把自己的域名解析到 127.0.0.1，浏览器便认为
   其页面与本地服务同源，从而绕过同源策略。此时请求头里的
   ``Host`` 仍是攻击者的域名 —— 校验 Host 即可挡住。
2. **CSRF**：外部页面可以直接发出"简单请求"（例如无请求体的 POST
   ``/shutdown``），浏览器不会预检。这类请求会带上 ``Origin``，校验即可挡住。
3. **WebSocket 不受同源策略约束**：任何页面都能连上
   ``ws://127.0.0.1:<port>/api/ws/generate/logs`` 读取运行日志，
   服务端检查 ``Origin`` 是唯一的拦截手段。

因此这里用的是**纯 ASGI 中间件**而不是 BaseHTTPMiddleware —— 后者拦不到
websocket 作用域。
"""

from urllib.parse import urlparse

# 允许的主机名（端口不参与判断：浏览器无法伪造 Host，
# 端口变化时也不该误伤本应用自身）
ALLOWED_HOSTNAMES = frozenset({"127.0.0.1", "localhost", "::1"})


def _hostname_from_host_header(value):
    """从 Host 头中取出主机名，兼容 ``[::1]:8000`` 这种写法"""
    if not value:
        return None

    value = value.strip()
    if value.startswith("["):  # IPv6
        end = value.find("]")
        return value[1:end] if end != -1 else None

    return value.rsplit(":", 1)[0] if ":" in value else value


def _hostname_from_origin(value):
    """从 Origin 头中取出主机名"""
    if not value:
        return None
    try:
        return urlparse(value).hostname
    except ValueError:
        return None


def is_request_allowed(host_header, origin_header, allowed=ALLOWED_HOSTNAMES):
    """判断一次请求是否来自本机应用自身

    - Host 必须是环回主机名，否则说明是通过别的域名访问进来的（DNS rebinding）。
    - Origin 只在存在时校验：同源 GET 通常不带 Origin，
      应用自身的健康检查等非浏览器请求也不带。
    """
    host = _hostname_from_host_header(host_header)
    if host is None or host.lower() not in allowed:
        return False, "host"

    if origin_header:
        origin = _hostname_from_origin(origin_header)
        if origin is None or origin.lower() not in allowed:
            return False, "origin"

    return True, None


class LocalOriginGuard:
    """拒绝非本机来源的 HTTP 与 WebSocket 请求"""

    def __init__(self, app, allowed_hostnames=ALLOWED_HOSTNAMES):
        self.app = app
        self.allowed = frozenset(allowed_hostnames)

    async def __call__(self, scope, receive, send):
        if scope.get("type") not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        headers = {}
        for raw_key, raw_value in scope.get("headers") or []:
            headers[raw_key.decode("latin-1").lower()] = raw_value.decode("latin-1")

        allowed, reason = is_request_allowed(
            headers.get("host"), headers.get("origin"), self.allowed
        )
        if allowed:
            await self.app(scope, receive, send)
            return

        if scope["type"] == "websocket":
            # ASGI 要求先收到 websocket.connect 才能关闭连接
            await receive()
            await send({"type": "websocket.close", "code": 1008})
            return

        body = f"Forbidden: request rejected by local origin guard ({reason})".encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": 403,
                "headers": [
                    (b"content-type", b"text/plain; charset=utf-8"),
                    (b"content-length", str(len(body)).encode("latin-1")),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})
