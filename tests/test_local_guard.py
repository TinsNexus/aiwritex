#!/usr/bin/env python
# -*- coding: UTF-8 -*-
"""本地来源守卫测试 | Host/Origin guard tests

覆盖三类攻击：DNS rebinding（Host 是攻击者域名）、跨站 CSRF（Origin 是外站）、
以及**跨站 WebSocket**——WebSocket 不受同源策略约束，服务端检查 Origin 是唯一手段。

同时反向验证不会误伤应用自身：同源页面、静态资源、以及不带 Origin 的
健康检查请求都必须照常通过。

依赖: fastapi, httpx
运行: python tests/test_local_guard.py
"""

import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

_failures = []


def check(label, condition):
    print(f"{'PASS' if condition else 'FAIL'}  {label}")
    if not condition:
        _failures.append(label)


def run_guard_tests():
    from src.ai_write_x.utils.path_manager import PathManager

    PathManager.get_app_data_dir = staticmethod(lambda: Path(tempfile.mkdtemp()))

    from fastapi import FastAPI, WebSocket
    from fastapi.testclient import TestClient
    from src.ai_write_x.web.local_guard import LocalOriginGuard, is_request_allowed


    print("--- 1. Logic thuan ---")
    cases = [
     ("host 127.0.0.1 + khong Origin", "127.0.0.1:8000", None, True),
     ("host localhost + khong Origin", "localhost:8000", None, True),
     ("host [::1]", "[::1]:8000", None, True),
     ("host 127.0.0.1 khong port", "127.0.0.1", None, True),
     ("same-origin POST", "127.0.0.1:8000", "http://127.0.0.1:8000", True),
     ("DNS rebinding (host la domain la)", "evil.com:8000", None, False),
     ("DNS rebinding + origin la", "evil.com:8000", "https://evil.com", False),
     ("CSRF: host dung, origin ngoai", "127.0.0.1:8000", "https://evil.com", False),
     ("origin null", "127.0.0.1:8000", "null", False),
     ("khong co Host", None, None, False),
     ("host tuong tu nhung khac", "127.0.0.1.evil.com:8000", None, False),
     ("localhost.evil.com", "localhost.evil.com", None, False),
    ]
    for label, host, origin, want in cases:
        got, _ = is_request_allowed(host, origin)
        check(f"{label} -> {'cho phep' if want else 'chan'}", got is want)

    print("--- 2. HTTP qua middleware ---")
    app = FastAPI()
    @app.get("/ping")
    async def ping(): return {"ok": True}
    @app.post("/shutdown")
    async def sd(): return {"ok": "shutdown"}
    @app.websocket("/ws")
    async def ws(w: WebSocket):
        await w.accept(); await w.send_json({"log":"secret"}); await w.close()
    app.add_middleware(LocalOriginGuard)
    c = TestClient(app, base_url="http://127.0.0.1:8000")

    check("GET same-origin -> 200", c.get("/ping").status_code == 200)
    check("POST /shutdown same-origin -> 200", c.post("/shutdown").status_code == 200)
    check("POST /shutdown tu trang ngoai (CSRF) -> 403",
          c.post("/shutdown", headers={"Origin":"https://evil.com"}).status_code == 403)
    check("GET voi Host la (DNS rebinding) -> 403",
          c.get("/ping", headers={"Host":"evil.com:8000"}).status_code == 403)
    check("than 403 co neu ly do", "origin" in c.post("/shutdown", headers={"Origin":"https://evil.com"}).text)

    print("--- 3. WebSocket (khong chiu rang buoc same-origin) ---")
    from starlette.websockets import WebSocketDisconnect
    # LUU Y: TestClient gui "Host: testserver" cho websocket, bo qua base_url,
    # nen phai dat Host thu cong cho ca hai truong hop moi phan anh dung thuc te.
    LOCAL = {"Host": "127.0.0.1:8000", "Origin": "http://127.0.0.1:8000"}
    with c.websocket_connect("/ws", headers=LOCAL) as w:
        check("WS same-origin van nhan duoc du lieu", w.receive_json() == {"log":"secret"})

    def ws_blocked(headers):
        try:
            with c.websocket_connect("/ws", headers=headers) as w:
                w.receive_json()
            return False
        except (WebSocketDisconnect, Exception):
            return True

    check("WS tu trang ngoai (Origin la) bi chan",
          ws_blocked({"Host":"127.0.0.1:8000","Origin":"https://evil.com"}))
    check("WS qua DNS rebinding (Host la) bi chan",
          ws_blocked({"Host":"evil.com:8000"}))

    print("--- 4. Khong pha health-check cua chinh app ---")
    check("health-check kieu requests (co Host, khong Origin)",
          c.get("/ping", headers={"Host":"127.0.0.1:8000"}).status_code == 200)



def run_real_app_tests():
    """用真实的 app 对象验证：正常访问不受影响，跨站访问一律 403"""
    print("\n=== 真实 app：同源正常 / 跨站 403 ===")
    from fastapi.testclient import TestClient
    from src.ai_write_x.web.app import app

    c = TestClient(app, base_url="http://127.0.0.1:8000")

    r = c.get("/")
    check("同源 GET / 正常渲染", r.status_code == 200 and "__I18N__" in r.text)
    check("同源 /health 正常", c.get("/health").status_code == 200)
    check("同源静态资源正常", c.get("/static/js/i18n.js").status_code == 200)
    check("同源 /api/config/ 正常", c.get("/api/config/").status_code == 200)

    check("跨站 GET /（Host 伪造）被拒", c.get("/", headers={"Host": "evil.com"}).status_code == 403)
    check(
        "跨站 POST /shutdown 被拒",
        c.post("/shutdown", headers={"Origin": "https://evil.com"}).status_code == 403,
    )
    check(
        "跨站读取配置被拒",
        c.get("/api/config/", headers={"Origin": "https://evil.com"}).status_code == 403,
    )
    check(
        "跨站访问静态资源被拒",
        c.get("/static/js/i18n.js", headers={"Host": "evil.com"}).status_code == 403,
    )


def main():
    run_guard_tests()
    run_real_app_tests()
    if _failures:
        print("\nFAILED:")
        for item in _failures:
            print("  -", item)
        return 1
    print("\nALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
