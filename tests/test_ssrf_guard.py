#!/usr/bin/env python
# -*- coding: UTF-8 -*-
"""SSRF 防护测试 | SSRF guard tests

只对"用户或 AI 提供的 URL"做限制（参考链接、文章内图片地址）；
程序自身固定的接口（热搜 API、微信接口、本地 Ollama、健康检查）不受影响——
这一点单独有断言覆盖，避免把本地 LLM 用法一起挡掉。

依赖: fastapi, httpx
运行: python tests/test_ssrf_guard.py
"""

import sys
import tempfile
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

_failures = []


def check(label, condition):
    print(f"{'PASS' if condition else 'FAIL'}  {label}")
    if not condition:
        _failures.append(label)


def run_unit():
    import src.ai_write_x.utils.utils as U

    print("=== 单元：is_safe_external_url ===")


    print("--- 1. Dia chi noi bo phai bi CHAN ---")
    blocked = [
     ("loopback v4","http://127.0.0.1:8000/x"), ("localhost","http://localhost:8000/x"),
     ("loopback v6","http://[::1]:8000/x"), ("cloud metadata","http://169.254.169.254/latest/meta-data/"),
     ("private 10/8","http://10.0.0.5/"), ("private 172.16/12","http://172.16.0.1/"),
     ("private 192.168/16","http://192.168.1.1/"), ("0.0.0.0","http://0.0.0.0/"),
     ("link-local v6","http://[fe80::1]/"), ("unique-local v6","http://[fd00::1]/"),
     ("scheme file","file:///etc/passwd"), ("scheme gopher","gopher://127.0.0.1/"),
     ("khong co host","http://"), ("chuoi rong",""),
    ]
    for label, url in blocked:
        check(f"chan {label}", U.is_safe_external_url(url) is False)

    print("--- 2. Ten mien phan giai ve noi bo cung bi chan ---")
    with mock.patch.object(U.socket,"getaddrinfo",return_value=[(2,1,6,'',('127.0.0.1',80))]):
        check("domain -> 127.0.0.1 bi chan", U.is_safe_external_url("http://evil.example/") is False)
    with mock.patch.object(U.socket,"getaddrinfo",return_value=[(2,1,6,'',('169.254.169.254',80))]):
        check("domain -> metadata bi chan", U.is_safe_external_url("http://evil.example/") is False)
    with mock.patch.object(U.socket,"getaddrinfo",return_value=[(2,1,6,'',('93.184.216.34',80)),(2,1,6,'',('10.0.0.1',80))]):
        check("mot IP noi bo trong nhieu ket qua -> chan", U.is_safe_external_url("http://mixed.example/") is False)
    with mock.patch.object(U.socket,"getaddrinfo",side_effect=U.socket.gaierror):
        check("khong phan giai duoc -> chan", U.is_safe_external_url("http://nx.invalid/") is False)

    print("--- 3. Dia chi cong cong phai duoc PHEP ---")
    with mock.patch.object(U.socket,"getaddrinfo",return_value=[(2,1,6,'',('93.184.216.34',80))]):
        for u in ["http://example.com/a","https://example.com/a?b=1"]:
            check(f"cho phep {u}", U.is_safe_external_url(u) is True)
    check("cho phep IP cong cong truc tiep", U.is_safe_external_url("https://93.184.216.34/") is True)

    print("--- 4. KHONG duoc pha cac loi goi hop le cua app ---")
    import inspect
    hot = inspect.getsource(U)  # guard chi nam trong download_and_save_image
    check("guard KHONG dat trong get_res_path/health-check", "is_safe_external_url" not in inspect.getsource(U.get_res_path))
    src_health = open(str(REPO_ROOT / 'src/ai_write_x/web/webview_gui.py'), encoding='utf-8').read()
    check("health-check 127.0.0.1 khong bi dong toi", "is_safe_external_url" not in src_health)
    hn = open(str(REPO_ROOT / 'src/ai_write_x/tools/hotnews.py'), encoding='utf-8').read()
    check("hotnews (API co dinh) khong bi dong toi", "is_safe_external_url" not in hn)
    cfgsrc = open(str(REPO_ROOT / 'src/ai_write_x/config/config.py'), encoding='utf-8').read()
    check("Ollama localhost van con trong cau hinh mac dinh", "http://localhost:11434" in cfgsrc)
    check("guard khong ap vao config.py (khong chan api_base Ollama)", "is_safe_external_url" not in cfgsrc)

    print("--- 5. download_and_save_image tu choi URL noi bo ---")
    called=[]
    with mock.patch.object(U.requests,"get",side_effect=lambda *a,**k: called.append(a)):
        r = U.download_and_save_image("http://169.254.169.254/latest/meta-data/", "/tmp/imgtest")
    check("tra ve None", r is None)
    check("KHONG he goi requests.get", called == [])



def run_e2e():
    print("\n=== 接口：POST /api/generate 的参考链接校验 ===")
    from src.ai_write_x.utils.path_manager import PathManager

    PathManager.get_app_data_dir = staticmethod(lambda: Path(tempfile.mkdtemp()))

    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import src.ai_write_x.web.api.generate as G
    from src.ai_write_x.config.config import Config

    app = FastAPI()
    app.include_router(G.router)
    c = TestClient(app, raise_server_exceptions=False)



    def post(url):
        return c.post("/api/generate", json={
            "topic":"t","platform":"wechat",
            "reference":{"reference_urls":url,"reference_ratio":30,
                         "template_category":"","template_name":""}})

    started=[]
    with mock.patch.object(Config, "validate_config", lambda self: True), \
         mock.patch.object(G, "ai_write_x_main", side_effect=lambda d: (started.append(d), (mock.Mock(), mock.Mock()))[1]):
        print("--- URL noi bo phai bi tu choi 400 ---")
        for label, u in [("loopback","http://127.0.0.1:8000/x"),
                         ("metadata","http://169.254.169.254/latest/meta-data/"),
                         ("private","http://192.168.1.1/"),
                         ("localhost","http://localhost:9999/")]:
            r = post(u); check(f"{label} -> 400", r.status_code==400)
        check("khong tac vu nao duoc khoi chay", started==[])

        print("--- URL cong cong van chay binh thuong ---")
        with mock.patch.object(G.utils, "is_safe_external_url", return_value=True):
            r = post("https://example.com/a")
        check("public URL di qua duoc kiem tra SSRF", r.status_code == 200)
        check("tac vu da duoc khoi chay", len(started) == 1)



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
