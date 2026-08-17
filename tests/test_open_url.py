#!/usr/bin/env python
# -*- coding: UTF-8 -*-
"""open_url 命令注入与文件类型测试 | open_url hardening tests

原实现在 Windows 上用 subprocess.run([...], shell=True) 打开文件，文件名里的
& | ^ 会被 shell 解释，构成命令注入；改用 os.startfile 之后还必须限制文件类型，
因为 os.startfile 会直接“运行”可执行文件。接口层另外只放行 http/https。

依赖: fastapi, httpx
运行: python tests/test_open_url.py
"""

import io
import sys
import tempfile
import tokenize
import types
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_failures = []


def check(label, condition):
    print(f"{'PASS' if condition else 'FAIL'}  {label}")
    if not condition:
        _failures.append(label)


def run_unit():
    import src.ai_write_x.utils.utils as U

    print("=== 单元：open_url ===")


    print("--- 1. Khong con dung shell ---")
    import io, tokenize
    _src = Path(U.__file__).read_text(encoding="utf-8")
    _code = " ".join(t.string for t in tokenize.generate_tokens(io.StringIO(_src).readline)
                     if t.type != tokenize.COMMENT)          # bo comment truoc khi quet
    check("khong con shell=True trong CODE", "shell=True" not in _code.replace(" ",""))
    check("khong con subprocess trong CODE", "subprocess" not in _code)
    check("da dung os.startfile", "os.startfile" in _code.replace(" ",""))

    print("--- 2. is_http_url ---")
    for v, want in [("http://a.com",True),("https://a.com",True),("HTTPS://A.com",True),
                    ("file:///etc/passwd",False),("javascript:alert(1)",False),
                    ("/etc/passwd",False),("C:\\evil.exe",False),("",False)]:
        check(f"is_http_url({v!r}) == {want}", U.is_http_url(v) is want)

    print("--- 3. Windows: dung os.startfile, KHONG qua shell ---")
    tmp = Path(tempfile.mkdtemp())
    evil = tmp / "a & calc.exe & .html"      # ten file co ky tu shell
    evil.write_text("x", encoding="utf-8")
    started = []
    with mock.patch.object(U.sys, "platform", "win32"), \
         mock.patch.object(U.os, "startfile", create=True, side_effect=lambda p: started.append(p)), \
         mock.patch.object(U, "webbrowser", types.SimpleNamespace(open=lambda u: started.append(("browser",u)))):
        import subprocess as real_sp
        with mock.patch.object(real_sp, "run", side_effect=AssertionError("subprocess.run KHONG duoc goi!")):
            out = U.open_url(str(evil))
    check("mo duoc file .html hop le", out == "")
    check("da dung os.startfile", len(started)==1)
    check("duong dan truyen nguyen ven, khong bi shell tach", started and "& calc.exe &" in str(started[0]))

    print("--- 4. Chan file thuc thi (os.startfile se CHAY chung) ---")
    for name in ["evil.exe","evil.bat","evil.cmd","evil.ps1","evil.scr"]:
        f = tmp/name; f.write_text("x", encoding="utf-8")
        with mock.patch.object(U.sys,"platform","win32"), \
             mock.patch.object(U.os,"startfile",create=True,side_effect=lambda p: started.append(p)):
            r = U.open_url(str(f))
        check(f"tu choi {name}", r == "不支持打开该类型的文件")

    print("--- 5. Van mo duoc noi dung hop le ---")
    ok_file = tmp/"article.html"; ok_file.write_text("x", encoding="utf-8")
    opened=[]
    with mock.patch.object(U.sys,"platform","darwin"), \
         mock.patch.object(U,"webbrowser",types.SimpleNamespace(open=lambda u: opened.append(u))):
        r = U.open_url(str(ok_file))
    check("mo .html tren macOS", r=="" and opened and opened[0].startswith("file://"))
    opened.clear()
    with mock.patch.object(U,"webbrowser",types.SimpleNamespace(open=lambda u: opened.append(u))):
        r = U.open_url("https://aiwritex.voidai.cc")
    check("mo link https (usecase that)", r=="" and opened==["https://aiwritex.voidai.cc"])

    print("--- 6. File co dau cach/# duoc escape dung ---")
    sp = tmp/"my file #1.html"; sp.write_text("x", encoding="utf-8")
    opened.clear()
    with mock.patch.object(U.sys,"platform","darwin"), \
         mock.patch.object(U,"webbrowser",types.SimpleNamespace(open=lambda u: opened.append(u))):
        U.open_url(str(sp))
    check("escape khoang trang va #", opened and "%20" in opened[0] and "%23" in opened[0])



def run_e2e():
    print("\n=== 接口：POST /api/config/open-url ===")
    from src.ai_write_x.utils.path_manager import PathManager

    PathManager.get_app_data_dir = staticmethod(lambda: Path(tempfile.mkdtemp()))

    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import src.ai_write_x.utils.utils as U
    from src.ai_write_x.web.api.config import router

    app = FastAPI()
    app.include_router(router)
    c = TestClient(app, raise_server_exceptions=False)



    opened=[]
    with mock.patch.object(U, "webbrowser", mock.Mock(open=lambda u: opened.append(u))):
        print("--- Phai BI CHAN (400) ---")
        tmp = Path(tempfile.mkdtemp()); ev = tmp/"x.exe"; ev.write_text("x")
        for label, url in [("duong dan tuyet doi", "/etc/passwd"),
                           ("file:// scheme", "file:///etc/passwd"),
                           ("javascript:", "javascript:alert(1)"),
                           ("file .exe cuc bo", str(ev)),
                           ("Windows path", "C:\\Windows\\System32\\calc.exe"),
                           ("chuoi rong", "")]:
            r = c.post("/api/config/open-url", json={"url": url})
            check(f"{label} -> 400", r.status_code == 400)
        check("khong co gi bi mo ra", opened == [])

        print("--- Phai VAN HOAT DONG (usecase that) ---")
        r = c.post("/api/config/open-url", json={"url": "https://aiwritex.voidai.cc"})
        check("https 200", r.status_code == 200)
        check("da mo dung link", opened == ["https://aiwritex.voidai.cc"])



def main():
    run_unit()
    run_e2e()
    if _failures:
        print("\nFAILED:")
        for item in _failures:
            print("  -", item)
        return 1
    print("\nALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
