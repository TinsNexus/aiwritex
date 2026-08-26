#!/usr/bin/env python
# -*- coding: UTF-8 -*-
"""路径限制回归测试 | Path confinement regression tests

覆盖 web/safe_path.py：越界路径必须被拒绝，目录内的合法路径
（含前端实际发送的绝对路径）必须放行。

运行: python tests/test_safe_path.py
"""

import sys
import tempfile
from pathlib import Path as _BootPath

sys.path.insert(0, str(_BootPath(__file__).resolve().parent.parent))
from pathlib import Path
from fastapi import HTTPException
from src.ai_write_x.web.safe_path import resolve_within, safe_name

root = Path(tempfile.mkdtemp()) / "articles"; (root/"sub").mkdir(parents=True)
(root/"ok.html").write_text("x"); (root/"sub"/"deep.html").write_text("y")
outside = root.parent / "secret.txt"; outside.write_text("SECRET")

def check(label, fn, expect):
    try:
        r = fn(); got = "allowed"
    except HTTPException as e: got = f"blocked({e.status_code})"
    ok = got.startswith(expect)
    print(f"{'PASS' if ok else 'FAIL'}  {label:<52} -> {got}")
    return ok

fails = 0
# --- phải CHẶN ---
for label, val in [
    ("absolute path outside root",        str(outside)),
    ("../ traversal",                     "../secret.txt"),
    ("nested ../../",                     "sub/../../secret.txt"),
    ("/etc/passwd",                       "/etc/passwd"),
    ("home ssh key",                      str(Path.home()/".ssh/id_rsa")),
    ("empty path",                        ""),
]:
    fails += not check(label, lambda v=val: resolve_within(v, root), "blocked")

# --- phải CHO PHÉP (không phá chức năng) ---
for label, val in [
    ("absolute path inside root (frontend sends this)", str(root/"ok.html")),
    ("absolute nested inside root",                     str(root/"sub"/"deep.html")),
    ("relative path inside root",                       "ok.html"),
    ("relative nested",                                 "sub/deep.html"),
    ("non-existent but inside root (404 handled later)", str(root/"new.html")),
]:
    fails += not check(label, lambda v=val: resolve_within(v, root), "allowed")

print()
# --- safe_name ---
for label, val, exp in [
    ("category '..'",            "..",            "blocked"),
    ("category '../../evil'",    "../../evil",    "blocked"),
    ("category with backslash",  "..\\..\\evil",  "blocked"),
    ("category with slash",      "a/b",           "blocked"),
    ("empty category",           "   ",           "blocked"),
    ("null byte",                "a\x00b",        "blocked"),
    ("normal Chinese category",  "科技数码",        "allowed"),
    ("normal ascii category",    "TechDigital",   "allowed"),
    ("name with space+dash",     "My Template-1", "allowed"),
]:
    fails += not check(label, lambda v=val: safe_name(v), exp)

print("\nRESULT:", "ALL PASS" if not fails else f"{fails} FAILURES")
sys.exit(1 if fails else 0)
