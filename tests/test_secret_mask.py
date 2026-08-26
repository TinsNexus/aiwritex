#!/usr/bin/env python
# -*- coding: UTF-8 -*-
"""配置密钥脱敏测试 | Secret masking tests

两个方向都必须成立：
1. GET /api/config/ 不再泄露任何密钥明文；
2. 界面把脱敏值原样回传时，**不会**把掩码写成真实密钥（这是脱敏最容易踩的坑）。

依赖: fastapi, httpx
运行: python tests/test_secret_mask.py
"""

import copy
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


_failures = []


def check(label, got, want=True):
    ok = (got == want)
    print(f"{'PASS' if ok else 'FAIL'}  {label}")
    if not ok:
        print(f"        got : {got!r}")
        print(f"        want: {want!r}")
        _failures.append(label)


def run_unit():
    print("=== 单元：脱敏 / 还原 ===")
    from src.ai_write_x.web.secret_mask import mask_config, unmask_config, mask_secret, is_masked


    STORED = {
      "api": {"api_type":"OpenRouter",
              "OpenRouter": {"api_key": ["sk-AAAA1111","sk-BBBB2222","sk-CCCC3333"], "model":["m"]},
              "Deepseek": {"api_key": [], "model":["m"]}},
      "img_api": {"api_type":"ali", "ali": {"api_key":"img-KEY-9999"}, "picsum": {"api_key":""}},
      "wechat": {"credentials":[{"appid":"wx1","appsecret":"SECRET-ONE-1111","author":"a"},
                                {"appid":"wx2","appsecret":"SECRET-TWO-2222","author":"b"}]},
    }
    AIF = {"llm": {"openrouter": {"api_key":"forge-KEY-7777"}, "deepseek": {"api_key":""}}}

    m, ma = mask_config(STORED, AIF)

    print("--- 1. Xuat ra KHONG con bi mat ---")
    blob = repr(m)+repr(ma)
    for secret in ["sk-AAAA1111","sk-BBBB2222","sk-CCCC3333","img-KEY-9999","SECRET-ONE-1111","SECRET-TWO-2222","forge-KEY-7777"]:
        check(f"khong lo {secret}", secret in blob, False)
    check("giu duoc duoi 4 ky tu de nhan biet", m["api"]["OpenRouter"]["api_key"][0].endswith("1111"), True)
    check("appid van hien (de phan biet tai khoan)", m["wechat"]["credentials"][0]["appid"], "wx1")
    check("gia tri rong van rong", m["img_api"]["picsum"]["api_key"], "")
    check("list rong van rong", m["api"]["Deepseek"]["api_key"], [])
    check("goc KHONG bi sua", STORED["api"]["OpenRouter"]["api_key"][0], "sk-AAAA1111")

    print("\n--- 2. Luu lai nguyen ven (khong sua gi) ---")
    back = copy.deepcopy(m); back["aiforge_config"] = copy.deepcopy(ma)
    unmask_config(back, STORED, AIF)
    check("api_key khoi phuc day du", back["api"]["OpenRouter"]["api_key"], ["sk-AAAA1111","sk-BBBB2222","sk-CCCC3333"])
    check("img api_key khoi phuc", back["img_api"]["ali"]["api_key"], "img-KEY-9999")
    check("appsecret[0] khoi phuc", back["wechat"]["credentials"][0]["appsecret"], "SECRET-ONE-1111")
    check("appsecret[1] khoi phuc", back["wechat"]["credentials"][1]["appsecret"], "SECRET-TWO-2222")
    check("aiforge api_key khoi phuc", back["aiforge_config"]["llm"]["openrouter"]["api_key"], "forge-KEY-7777")

    print("\n--- 3. Sua that su ---")
    b = copy.deepcopy(m); b["aiforge_config"]=copy.deepcopy(ma)
    b["api"]["OpenRouter"]["api_key"][1] = "sk-NEWKEY-9999"
    b["wechat"]["credentials"][0]["appsecret"] = "SECRET-CHANGED"
    unmask_config(b, STORED, AIF)
    check("key moi duoc luu", b["api"]["OpenRouter"]["api_key"], ["sk-AAAA1111","sk-NEWKEY-9999","sk-CCCC3333"])
    check("appsecret moi duoc luu", b["wechat"]["credentials"][0]["appsecret"], "SECRET-CHANGED")

    print("\n--- 4. Ca de sai: xoa / dao thu tu / them ---")
    b = copy.deepcopy(m); b["api"]["OpenRouter"]["api_key"].pop(0)     # xoa key dau
    unmask_config(b, STORED, AIF)
    check("xoa key dau -> con dung 2 key sau", b["api"]["OpenRouter"]["api_key"], ["sk-BBBB2222","sk-CCCC3333"])

    b = copy.deepcopy(m); k=b["api"]["OpenRouter"]["api_key"]; k[0],k[2]=k[2],k[0]  # dao
    unmask_config(b, STORED, AIF)
    check("dao thu tu -> dung thu tu moi", b["api"]["OpenRouter"]["api_key"], ["sk-CCCC3333","sk-BBBB2222","sk-AAAA1111"])

    b = copy.deepcopy(m); b["api"]["OpenRouter"]["api_key"].append("sk-ADDED-0000")
    unmask_config(b, STORED, AIF)
    check("them key moi", b["api"]["OpenRouter"]["api_key"], ["sk-AAAA1111","sk-BBBB2222","sk-CCCC3333","sk-ADDED-0000"])

    b = copy.deepcopy(m); b["api"]["OpenRouter"]["api_key"]=[]
    unmask_config(b, STORED, AIF)
    check("xoa het", b["api"]["OpenRouter"]["api_key"], [])

    print("\n--- 5. PATCH mot phan (chi gui 1 muc) ---")
    partial = {"img_api": {"ali": {"api_key": mask_secret("img-KEY-9999")}}}
    unmask_config(partial, STORED, AIF)
    check("patch mot phan van khoi phuc dung", partial["img_api"]["ali"]["api_key"], "img-KEY-9999")

    print("\n--- 6. Mask la (khong khop) khong duoc luu thanh mat khau ---")
    b = copy.deepcopy(m); b["wechat"]["credentials"][0]["appsecret"] = "••••••••ZZZZ"
    unmask_config(b, STORED, AIF)
    check("mask khong khop -> ve gia tri da luu, khong phai chuoi bullet",
          is_masked(b["wechat"]["credentials"][0]["appsecret"]), False)

    _UNIT_END = True


def run_e2e():
    print("\n=== 接口：GET 脱敏 + PATCH 还原 ===")
    from pathlib import Path
    from src.ai_write_x.utils.path_manager import PathManager
    TMP = Path(tempfile.mkdtemp()); PathManager.get_app_data_dir = staticmethod(lambda: TMP)

    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from src.ai_write_x.config.config import Config
    from src.ai_write_x.web.api.config import router

    cfg = Config.get_instance(); cfg.load_config()
    REAL_KEY, REAL_SECRET, REAL_IMG = "sk-REALKEY-1234", "wxREALSECRET-5678", "img-REALKEY-9012"
    cfg.config["api"]["OpenRouter"]["api_key"] = [REAL_KEY]
    cfg.config["wechat"]["credentials"][0]["appsecret"] = REAL_SECRET
    cfg.config.setdefault("img_api", {}).setdefault("ali", {})["api_key"] = REAL_IMG

    app = FastAPI(); app.include_router(router)
    c = TestClient(app, raise_server_exceptions=False)


    r = c.get("/api/config/"); body = r.text
    check("GET tra ve 200", r.status_code==200)
    print("--- 1. GET khong con ro ri bi mat ---")
    for s in [REAL_KEY, REAL_SECRET, REAL_IMG]:
        check(f"khong lo {s}", s not in body)
    data = r.json()["data"]
    check("van thay duoi 4 ky tu", data["api"]["OpenRouter"]["api_key"][0].endswith("1234"))
    check("appid van ro", data["wechat"]["credentials"][0]["appid"] is not None)

    print("--- 2. Luu lai y nguyen -> bi mat KHONG bi hong ---")
    r2 = c.patch("/api/config/", json={"config_data": data})
    check("PATCH 200", r2.status_code==200)
    check("api_key con nguyen", cfg.config["api"]["OpenRouter"]["api_key"] == [REAL_KEY])
    check("appsecret con nguyen", cfg.config["wechat"]["credentials"][0]["appsecret"] == REAL_SECRET)
    check("img api_key con nguyen", cfg.config["img_api"]["ali"]["api_key"] == REAL_IMG)
    check("KHONG co chuoi bullet lot vao config", "•" not in json.dumps(cfg.config, ensure_ascii=False))

    print("--- 3. Doi khoa that su ---")
    d2 = c.get("/api/config/").json()["data"]
    d2["api"]["OpenRouter"]["api_key"] = ["sk-BRANDNEW-0000"]
    c.patch("/api/config/", json={"config_data": d2})
    check("khoa moi duoc luu", cfg.config["api"]["OpenRouter"]["api_key"] == ["sk-BRANDNEW-0000"])
    check("appsecret van khong bi anh huong", cfg.config["wechat"]["credentials"][0]["appsecret"] == REAL_SECRET)

    print("--- 4. Ghi ra dia roi doc lai (khong luu mask vao file) ---")
    cfg.save_config(cfg.config, cfg.aiforge_config)
    disk = Path(cfg.config_path).read_text(encoding="utf-8")
    check("file tren dia co khoa that", "sk-BRANDNEW-0000" in disk)
    check("file tren dia KHONG co bullet", "•" not in disk)



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
