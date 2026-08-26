#!/usr/bin/env python
# -*- coding: UTF-8 -*-
"""配置密钥落盘位置测试 | Config secret-location tests

核心断言：保存配置时，密钥只写入用户数据目录，**绝不**写回源码树中
被 Git 跟踪的 config.yaml / aiforge.toml（本仓库为公开仓库）。

依赖: fastapi(间接)、yaml、tomlkit
运行: python tests/test_config_secrets.py
"""

import hashlib
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

REPO_ROOT = Path(__file__).resolve().parent.parent
SEED_YAML = REPO_ROOT / "src" / "ai_write_x" / "config" / "config.yaml"
SEED_TOML = REPO_ROOT / "src" / "ai_write_x" / "config" / "aiforge.toml"

# 测试用的假密钥（只在临时目录中出现）
FAKE_KEY = "sk-TEST-ONLY-NOT-A-REAL-KEY"
FAKE_SECRET = "wxTESTONLY0000000"


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    failures = []

    def check(label, condition):
        print(f"{'PASS' if condition else 'FAIL'}  {label}")
        if not condition:
            failures.append(label)

    before = {SEED_YAML: _sha(SEED_YAML), SEED_TOML: _sha(SEED_TOML)}

    from src.ai_write_x.utils.path_manager import PathManager

    # 先记下真实（未打桩）的运行时配置目录，后面用来做 .gitignore 检查
    real_config_dir = PathManager.get_config_dir()

    # 再把用户数据目录指向临时目录，避免污染真实环境
    tmp = Path(tempfile.mkdtemp())
    PathManager.get_app_data_dir = staticmethod(lambda: tmp)

    config_dir = PathManager.get_config_dir()
    check("配置目录位于用户数据目录", str(tmp) in str(config_dir))
    check("配置目录不在源码树中", "src/ai_write_x/config" not in str(config_dir))

    from src.ai_write_x.config.config import Config

    cfg = Config.get_instance()
    check("模板已复制到用户目录", Path(cfg.config_path).exists())
    check("config_path 指向用户目录", str(tmp) in cfg.config_path)
    check("aiforge 路径指向用户目录", str(tmp) in cfg.config_aiforge_path)

    # 写入"密钥"并保存
    cfg.load_config()
    cfg.config["api"]["OpenRouter"]["api_key"] = [FAKE_KEY]
    cfg.config["wechat"]["credentials"][0]["appsecret"] = FAKE_SECRET
    check("save_config 成功", bool(cfg.save_config(cfg.config, cfg.aiforge_config)))

    saved = Path(cfg.config_path).read_text(encoding="utf-8")
    check("密钥已写入用户目录", FAKE_KEY in saved)

    # —— 核心安全断言 ——
    check("源码树 config.yaml 未被修改", _sha(SEED_YAML) == before[SEED_YAML])
    check("源码树 aiforge.toml 未被修改", _sha(SEED_TOML) == before[SEED_TOML])
    check(
        "密钥未出现在源码树文件中",
        FAKE_KEY not in SEED_YAML.read_text(encoding="utf-8"),
    )

    # —— 残留密钥告警：不得误报，且不得回显密钥值 ——
    import src.ai_write_x.config.config as config_module

    warn = Config._Config__warn_if_seed_has_secrets
    messages = []
    original_log = config_module.log.print_log
    config_module.log.print_log = lambda msg, level="info": messages.append(msg)

    def warned_for(name, content):
        path = Path(tempfile.mkdtemp()) / name
        path.write_text(content, encoding="utf-8")
        messages.clear()
        warn(str(path))
        return bool(messages)

    try:
        check(
            "干净的仓库模板不告警(config.yaml)",
            not warned_for("config.yaml", SEED_YAML.read_text(encoding="utf-8")),
        )
        check(
            "干净的仓库模板不告警(aiforge.toml)",
            not warned_for("aiforge.toml", SEED_TOML.read_text(encoding="utf-8")),
        )
        check("空列表不告警", not warned_for("a.yaml", "    api_key: []\n"))
        check("空字符串不告警", not warned_for("b.toml", 'api_key = ""\n'))
        check("有密钥时告警(yaml)", warned_for("c.yaml", "    api_key: [sk-abc]\n"))
        check("有密钥时告警(toml)", warned_for("d.toml", 'api_key = "sk-abc"\n'))
        check("有 appsecret 时告警", warned_for("e.yaml", '    - appsecret: "wxabc"\n'))

        warned_for("f.toml", f'api_key = "{FAKE_KEY}"\n')
        check("告警内容不回显密钥值", all(FAKE_KEY not in m for m in messages))
    finally:
        config_module.log.print_log = original_log

    # —— 真实（未打桩）路径下：运行时配置目录绝不能被 Git 提交 ——
    # 开发模式 get_app_data_dir() 返回项目根目录，配置会落在 <repo>/config/，
    # 里面是真实密钥。若它既未被跟踪又不在 .gitignore 中，一次 git add . 就会泄露。
    import subprocess

    try:
        repo_rel = real_config_dir.resolve().relative_to(REPO_ROOT.resolve())
    except ValueError:
        repo_rel = None  # 在仓库之外，天然安全

    if repo_rel is None:
        check("运行时配置目录位于仓库之外", True)
    else:
        probe = f"{repo_rel.as_posix()}/config.yaml"
        ignored = (
            subprocess.run(
                ["git", "check-ignore", "-q", probe], cwd=REPO_ROOT
            ).returncode
            == 0
        )
        check(f"运行时配置目录 {repo_rel}/ 已被 .gitignore 排除", ignored)

    if failures:
        print("\nFAILED:")
        for item in failures:
            print("  -", item)
        return 1

    print("\nALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
