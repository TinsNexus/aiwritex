#!/usr/bin/env python
# -*- coding: UTF-8 -*-
"""语言包一致性检查 | Locale consistency checks

不依赖 fastapi / crewai，可直接运行：
    python tests/test_locales.py
"""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "src" / "ai_write_x" / "web"
LOCALES = WEB / "static" / "locales"
BASE_LOCALE = "zh_CN"

# 词条中允许出现的 HTML 标签（用于校验译文没有破坏标记）
TAG_RE = re.compile(r"<[^>]+>")
PARAM_RE = re.compile(r"\{(\w+)\}")


def load(locale):
    return json.loads((LOCALES / f"{locale}.json").read_text(encoding="utf-8"))


def locale_names():
    return sorted(p.stem for p in LOCALES.glob("*.json"))


def collect_used_keys():
    """扫描模板与 JS 中实际引用的词条 key"""
    keys = set()

    for html in WEB.joinpath("templates").rglob("*.html"):
        text = html.read_text(encoding="utf-8")
        keys |= set(re.findall(r'data-i18n(?:-[\w-]+)?="([^"]+)"', text))

    for js in WEB.joinpath("static", "js").glob("*.js"):
        text = js.read_text(encoding="utf-8")
        # i18n.t('key') / t('key') / t("key")
        keys |= set(re.findall(r"\bt\(\s*['\"]([\w.]+)['\"]", text))

    return keys


def load_dimension_sources():
    """读取维度定义的两处来源：config.yaml 与 config.py 中的默认配置

    两者若不一致，走默认配置的用户会看到未翻译的中文选项，因此都要校验。
    """
    sources = {}

    yaml_path = ROOT / "src" / "ai_write_x" / "config" / "config.yaml"
    try:
        import yaml as _yaml

        data = _yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
        sources["config.yaml"] = data["dimensional_creative"]["dimension_options"]
    except ImportError:
        print("  (跳过 config.yaml 校验：未安装 PyYAML)")
    except (OSError, KeyError, TypeError):
        pass

    # config.py 中的默认配置：不导入模块（依赖较重），用 AST 提取字面量
    py_path = ROOT / "src" / "ai_write_x" / "config" / "config.py"
    try:
        import ast

        tree = ast.parse(py_path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Dict):
                continue
            for key, value in zip(node.keys, node.values):
                if (
                    isinstance(key, ast.Constant)
                    and key.value == "dimension_options"
                    and isinstance(value, ast.Dict)
                ):
                    try:
                        sources["config.py"] = ast.literal_eval(value)
                    except ValueError:
                        pass
    except (OSError, SyntaxError):
        pass

    return sources


def check_dimension_keys(base, locales):
    """校验维度显示词条：每个维度及其预设选项都要有对应 key"""
    failures = []
    sources = load_dimension_sources()
    if not sources:
        failures.append("未能读取任何维度定义来源，维度词条未经校验")
        return failures

    all_slugs = {}
    for source_name, dims in sources.items():
        for cat, cfg in dims.items():
            slugs = {o["name"] for o in (cfg.get("preset_options") or []) if isinstance(o, dict)}
            all_slugs.setdefault(cat, {})[source_name] = slugs

            for loc in locales:
                messages = load(loc)
                if f"dim.{cat}.name" not in messages:
                    failures.append(f"[{loc}] 缺少维度名称词条: dim.{cat}.name ({source_name})")
                missing = sorted(s for s in slugs if f"dim.{cat}.{s}" not in messages)
                if missing:
                    failures.append(
                        f"[{loc}] 维度 {cat} 缺少 {len(missing)} 个选项词条 ({source_name}): {missing[:6]}"
                    )

    # 两处来源的 slug 集合必须一致
    for cat, by_source in all_slugs.items():
        if len(by_source) > 1:
            names = list(by_source)
            a, b = by_source[names[0]], by_source[names[1]]
            if a != b:
                failures.append(
                    f"维度 {cat} 在 {names[0]} 与 {names[1]} 之间 slug 不一致: "
                    f"仅前者={sorted(a - b)[:5]} 仅后者={sorted(b - a)[:5]}"
                )

    print(f"维度定义来源 / dimension sources: {list(sources)}  维度数: {len(all_slugs)}")
    return failures


def main():
    failures = []
    locales = locale_names()
    base = load(BASE_LOCALE)
    print(f"语言包 / locales: {locales}  基准 / base: {BASE_LOCALE} ({len(base)} keys)")

    # 1. 各语言 key 集合必须与基准一致
    for loc in locales:
        if loc == BASE_LOCALE:
            continue
        other = load(loc)
        missing = sorted(set(base) - set(other))
        extra = sorted(set(other) - set(base))
        if missing:
            failures.append(f"[{loc}] 缺失 {len(missing)} 个词条: {missing[:10]}")
        if extra:
            failures.append(f"[{loc}] 多出 {len(extra)} 个词条: {extra[:10]}")

        # 2. 译文不得为空
        empty = sorted(k for k, v in other.items() if not str(v).strip())
        if empty:
            failures.append(f"[{loc}] 空译文: {empty[:10]}")

        # 3. 占位符与 HTML 标签必须保持一致
        for key, base_val in base.items():
            val = other.get(key)
            if val is None:
                continue
            if set(PARAM_RE.findall(base_val)) != set(PARAM_RE.findall(val)):
                failures.append(f"[{loc}] 占位符不一致: {key}")
            if len(TAG_RE.findall(base_val)) != len(TAG_RE.findall(val)):
                failures.append(f"[{loc}] HTML 标签数量不一致: {key}")

    # 4. 代码中引用的 key 必须存在于基准语言包
    used = collect_used_keys()
    undefined = sorted(k for k in used if k not in base)
    if undefined:
        failures.append(f"代码引用了未定义的词条 ({len(undefined)}): {undefined[:15]}")
    print(f"代码引用词条 / keys referenced in code: {len(used)}")

    # 5. 动态拼接的维度词条（t(`dim.${...}`) 无法被静态扫描覆盖）
    failures.extend(check_dimension_keys(base, locales))

    if failures:
        print("\n检查未通过 / FAILED:")
        for f in failures:
            print("  -", f)
        return 1

    print("\n全部检查通过 / ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
