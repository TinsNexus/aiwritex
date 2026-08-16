# 界面语言包 | UI locale files

## 目录说明

- `zh_CN.json` —— 基准语言（简体中文）。所有词条以此为准。
- `vi.json` —— 越南语。
- 放在 `web/static/` 下是为了随 `web` 资源目录一起打包，无需改动打包配置。

## 新增一种语言

1. 复制 `zh_CN.json` 为 `<语言代码>.json`（如 `en.json`），逐条翻译 value，**不要改动 key**。
2. 在 `web/i18n.py` 的 `LOCALE_DISPLAY_NAMES` 中加入该语言的本族语名称。
3. 运行校验：

```bash
python tests/test_locales.py
```

语言选择器会自动列出本目录下的所有语言包，无需改动前端代码。

## 词条约定

- **占位符** 用 `{name}` 形式，译文必须保留同名占位符（校验脚本会比对）。
- **含 HTML 的词条**（如 `common.save_with_changes`）译文需保留同样数量的标签。
- 缺失的词条会自动回退到 `zh_CN`，因此界面不会出现原始 key。

## 哪些内容**不**属于界面词条

以下均为程序行为或跨层协议，翻译会改变功能，请勿加入语言包：

- `config.yaml` / `config.py` 中 `dimension_options` 的 `value` 与 `description` ——
  它们会原样进入 AI 提示词。界面显示走 `dim.<维度>.<slug>` 词条层，
  两者互不影响（见 `config-manager.js` 中维度选择器的渲染逻辑）。
- `config.yaml` 中 `platforms[].name`（微博、抖音……）—— 用作查找键
  （`tools/hotnews.py`）。界面显示走 `platdesc.*` 词条。
- 跨层匹配的协议字符串，如 `任务执行完成`
  （`crew_main.py` → `api/generate.py` → `creative-workshop.js` 三处匹配）。
- `/ws/logs` 输出的运行日志（含第三方库输出），属于诊断信息。
- `console.*` 调试输出与源码注释。
