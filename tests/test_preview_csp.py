#!/usr/bin/env python
# -*- coding: UTF-8 -*-
"""预览接口 CSP 测试 | Preview Content-Security-Policy tests

原策略 ``default-src 'self' 'unsafe-inline'`` 允许内联脚本，等于没有 CSP。
现在改为 ``default-src 'none'`` 且不放开 script-src——预览内容里的 <script>
无法执行；同时按内置模板的真实需要放行内联样式、Google Fonts 与图片。

依赖: fastapi, httpx
运行: python tests/test_preview_csp.py
"""

import glob
import re
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


def run_csp_tests():
    from src.ai_write_x.utils.path_manager import PathManager

    TMP = Path(tempfile.mkdtemp())
    ART = TMP / "output" / "article"
    TPL = TMP / "templates"
    ART.mkdir(parents=True)
    TPL.mkdir(parents=True)
    PathManager.get_article_dir = staticmethod(lambda: ART)
    PathManager.get_template_dir = staticmethod(lambda: TPL)

    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from src.ai_write_x.web.api.articles import router as ar
    from src.ai_write_x.web.api.templates import router as tr
    from src.ai_write_x.web.local_guard import PREVIEW_CSP


    app=FastAPI(); app.include_router(ar); app.include_router(tr)
    c=TestClient(app, raise_server_exceptions=False)

    EVIL = '<html><body><h1 style="color:red">hi</h1><script>fetch("/api/config/")</script></body></html>'
    (ART/"a.html").write_text(EVIL, encoding="utf-8")
    (TPL/"t.html").write_text(EVIL, encoding="utf-8")

    print("--- CSP thuc su chan script ---")
    def directives(csp):
        return {d.strip().split(" ")[0]: d.strip() for d in csp.split(";") if d.strip()}
    d = directives(PREVIEW_CSP)
    check("co default-src 'none'", d.get("default-src") == "default-src 'none'")
    check("KHONG mo script-src (script bi default-src 'none' chan)", "script-src" not in d)
    check("KHONG con 'unsafe-inline' o default-src", "unsafe-inline" not in d.get("default-src",""))
    check("base-uri 'none'", d.get("base-uri") == "base-uri 'none'")
    check("form-action 'none'", d.get("form-action") == "form-action 'none'")

    print("--- Header duoc gui dung tren ca 2 endpoint ---")
    for name, url in [("article", "/api/articles/preview?path=" + str(ART/"a.html")),
                      ("template", "/api/templates/preview/" + str(TPL/"t.html"))]:
        r = c.get(url)
        csp = r.headers.get("content-security-policy","")
        check(f"{name}: 200", r.status_code==200)
        check(f"{name}: CSP == PREVIEW_CSP", csp == PREVIEW_CSP)
        check(f"{name}: CSP khong con 'default-src self unsafe-inline'", "default-src 'self' 'unsafe-inline'" not in csp)
        check(f"{name}: noi dung van tra ve nguyen ven", "<h1" in r.text)

    print("--- Van cho phep thu template that su can ---")
    check("inline style duoc phep", "'unsafe-inline'" in d.get("style-src",""))
    check("google fonts stylesheet duoc phep", "https:" in d.get("style-src",""))
    check("font file duoc phep", "https:" in d.get("font-src",""))
    check("anh picsum(https) duoc phep", "https:" in d.get("img-src",""))
    check("anh local /images (self) duoc phep", "'self'" in d.get("img-src",""))
    check("data: URI anh duoc phep", "data:" in d.get("img-src",""))



def run_template_compat():
    """确认这套 CSP 不会破坏仓库内置的模板"""
    print("\n=== 与内置模板的兼容性 ===")
    files = glob.glob(str(REPO_ROOT / "knowledge" / "templates" / "**" / "*.html"), recursive=True)
    if not files:
        print("  (未找到内置模板，跳过)")
        return

    with_script = []
    non_https_ext = []
    for path in files:
        text = Path(path).read_text(encoding="utf-8", errors="ignore")
        if re.search(r"<script", text, re.I):
            with_script.append(Path(path).name)
        # 外链样式/字体若走 http: 会被 style-src/font-src 的 https: 拒绝
        for match in re.findall(r'<link[^>]+href="([^"]+)"', text, re.I):
            if match.startswith("http://"):
                non_https_ext.append((Path(path).name, match))

    print(f"  扫描模板数: {len(files)}")
    check(f"没有模板依赖 <script>（否则会被 CSP 拦下）: {with_script[:3]}", not with_script)
    check(f"没有模板通过 http: 引入外部样式: {non_https_ext[:2]}", not non_https_ext)


def main():
    run_csp_tests()
    run_template_compat()
    if _failures:
        print("\nFAILED:")
        for item in _failures:
            print("  -", item)
        return 1
    print("\nALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
