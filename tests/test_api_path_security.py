#!/usr/bin/env python
# -*- coding: UTF-8 -*-
"""接口层路径安全测试 | API path-confinement tests

验证越界读写删被拒绝，同时确认前端实际使用的绝对路径仍然可用。
测试目录被重定向到临时目录，不会污染用户数据。

依赖: fastapi, httpx
运行: python tests/test_api_path_security.py
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.ai_write_x.utils.path_manager import PathManager  # noqa: E402

# 重定向到临时目录（必须在导入路由之前完成）
_TMP = Path(tempfile.mkdtemp())
_ART = _TMP / "output" / "article"
_TPL = _TMP / "templates"
_ART.mkdir(parents=True, exist_ok=True)
_TPL.mkdir(parents=True, exist_ok=True)
PathManager.get_article_dir = staticmethod(lambda: _ART)
PathManager.get_template_dir = staticmethod(lambda: _TPL)

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from src.ai_write_x.web.api.articles import router as articles_router  # noqa: E402
from src.ai_write_x.web.api.templates import router as templates_router  # noqa: E402


def main():
    (_ART / "demo.html").write_text("<h1>hello</h1>", encoding="utf-8")
    secret = _TMP / "SECRET_probe.txt"
    secret.write_text("TOP-SECRET", encoding="utf-8")

    app = FastAPI()
    app.include_router(articles_router)
    app.include_router(templates_router)
    client = TestClient(app, raise_server_exceptions=False)

    failures = []

    def check(label, resp, allowed_status, forbidden_text=None):
        ok = resp.status_code in allowed_status
        if ok and forbidden_text:
            ok = forbidden_text not in resp.text
        if not ok:
            failures.append(f"{label} -> {resp.status_code}")
        print(f"{'PASS' if ok else 'FAIL'}  {label:<52} {resp.status_code}")

    print("--- 必须被拒绝 ---")
    check("read outside root", client.get("/api/articles/content", params={"path": str(secret)}),
          {403}, "TOP-SECRET")
    check("read /etc/passwd", client.get("/api/articles/content", params={"path": "/etc/passwd"}),
          {403}, "root:")
    check("preview outside root", client.get("/api/articles/preview", params={"path": str(secret)}),
          {403}, "TOP-SECRET")
    check("overwrite outside root",
          client.put("/api/articles/content", params={"path": str(secret)},
                     json={"content": "PWNED"}), {403})
    check("delete outside root", client.request("DELETE", f"/api/articles/{secret}"), {403})
    check("design write outside root",
          client.post("/api/articles/design",
                      json={"article": str(secret), "html": "x", "css": "", "cover": ""}), {403})
    check("template read /etc/passwd", client.get("/api/templates/content//etc/passwd"), {403, 404},
          "root:")
    check("template delete traversal", client.request("DELETE", "/api/templates//etc/hosts"),
          {403, 404})
    check("category rmtree '..'", client.request("DELETE", "/api/templates/categories/.."),
          {400, 404})
    check("create category '../../evil'",
          client.post("/api/templates/categories", json={"name": "../../evil"}), {400})

    print("--- 必须仍然可用 ---")
    check("read valid absolute path (as the frontend sends)",
          client.get("/api/articles/content", params={"path": str(_ART / "demo.html")}), {200})
    check("preview valid", client.get("/api/articles/preview",
                                      params={"path": str(_ART / "demo.html")}), {200})
    check("write valid", client.put("/api/articles/content",
                                    params={"path": str(_ART / "demo.html")},
                                    json={"content": "<h1>edited</h1>"}), {200})
    check("missing file inside root still 404",
          client.get("/api/articles/content", params={"path": str(_ART / "nope.html")}), {404})

    assert secret.read_text(encoding="utf-8") == "TOP-SECRET", "越界文件被修改!"
    assert (_ART / "demo.html").read_text(encoding="utf-8") == "<h1>edited</h1>", "合法写入失败!"

    if failures:
        print("\nFAILED:")
        for f in failures:
            print("  -", f)
        return 1
    print("\nALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
