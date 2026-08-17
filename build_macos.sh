#!/usr/bin/env bash
# 使用 Nuitka 构建 macOS 桌面应用（AIWriteX.app）
#
# 资源放置规则由 utils.get_res_path() 决定：Nuitka standalone 下走
#   os.path.dirname(sys.executable) + relative_path
# 在 .app 里 sys.executable 是 Contents/MacOS/AIWriteX，
# 因此下面每个 --include-data-dir 的目标名必须与代码里请求的相对路径一致：
#   get_res_path("web")            -> web/
#   get_res_path("config/<file>")  -> config/
#   get_res_path("templates")      -> templates/
#   get_res_path("UI/icon.png")    -> UI/
#
# 用法: ./build_macos.sh   （需先 uv venv 并安装 requirements.txt 与 nuitka）
set -euo pipefail

cd "$(dirname "$0")"
PY="${PY:-.venv/bin/python}"
OUT="${OUT:-make_app}"          # 已在 .gitignore 中

[ -x "$PY" ] || { echo "找不到 $PY，请先创建虚拟环境并安装依赖"; exit 1; }

echo "==> 清理旧产物"
rm -rf "$OUT/main.dist" "$OUT/main.build" "$OUT/AIWriteX.app"
mkdir -p "$OUT"

echo "==> 开始编译（Nuitka standalone，耗时较长）"
"$PY" -m nuitka \
  --standalone \
  --macos-create-app-bundle \
  --macos-app-name=AIWriteX \
  --macos-app-icon=src/ai_write_x/assets/UI/icon.icns \
  --company-name="墨智工坊" \
  --product-name=AIWriteX \
  --output-dir="$OUT" \
  --output-filename=AIWriteX \
  --assume-yes-for-downloads \
  --static-libpython=no \
  --remove-output \
  --include-data-dir=src/ai_write_x/web=web \
  --include-data-dir=src/ai_write_x/config=config \
  --include-data-dir=knowledge/templates=templates \
  --include-data-dir=src/ai_write_x/assets/UI=UI \
  --include-package=src.ai_write_x \
  --include-package=crewai \
  --include-package=aiforge \
  --include-package=litellm \
  --enable-plugin=pywebview \
  --include-package=uvicorn \
  --include-package=fastapi \
  --include-package-data=litellm \
  --include-package-data=crewai \
  --include-package-data=aiforge \
  --nofollow-import-to=pytest \
  --nofollow-import-to=tests \
  main.py

echo "==> 构建完成: $OUT/main.app 或 $OUT/AIWriteX.app"
ls -d "$OUT"/*.app 2>/dev/null || true

# ---------------------------------------------------------------------------
# 环境注意事项（都是实际构建时踩到的）
#
# 1) Python 3.12：pyproject 要求 >=3.10,<3.13。3.13 装不上 crewai。
#      uv venv --python 3.12 .venv
#
# 2) peewee 必须锁 3.x：requirements.txt 写的是 peewee>=3.14.0，没有上限，
#    会装到 4.x，而 aiforge 依赖 3.x 的 playhouse.sqlite_ext.SqliteExtDatabase，
#    4.x 已移除该名字，导致 import 直接失败。
#      uv pip install "peewee<4"
#
# 3) setuptools 必须升级：requirements.txt 锁的是 setuptools==65.5.0，
#    它在 Python 3.12 下 import pkg_resources 会因 pkgutil.ImpImporter 被移除而崩，
#    Nuitka 的 pkg-resources 插件初始化随之失败。
#      uv pip install -U setuptools
#
# 4) --static-libpython=no：Homebrew Python 不提供静态 libpython。
#
# 5) 不要加 --include-package=webview：会与 Nuitka 内置的 pywebview 插件
#    对 webview.platforms.android 的处理冲突，报 "Conflict between user and
#    plugin decision"。该插件默认就是启用的。
# ---------------------------------------------------------------------------
