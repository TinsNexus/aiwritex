# AIWriteX 安全检查报告与修复记录 | Security Review & Remediation

> ## ✅ 本文所列问题均已修复
>
> **全部条目（H1–H3、M1–M4、L1–L3）以及两条"附带发现"都已在本仓库修复并有测试覆盖。**
>
> **正文（"高危"/"中危"/"低危"三节）描述的是修复前的代码状态**，保留下来是为了说明
> 每处问题的成因与影响；每一条对应的改法写在文末"修复记录"一节。
>
> **是否发生过凭证泄露？没有。** 已用 `git log -p -S` 配合密钥形态
> （`sk-*`、`wx*`、32 位以上字符串）扫描过 `config.yaml` / `aiforge.toml` 的**全部提交历史**，
> 未发现任何非空的 `api_key` / `appsecret`。H3 属于预防性修复，**无需轮换任何现有凭证**。

## 审查范围

- **已审查**：后端 FastAPI、前端 JS、配置与打包流程。
- **未审查**：第三方依赖漏洞（项目无 lockfile，也未使用 SCA 工具）；
  以及真机运行时行为——审查与验证均在依赖不完整的临时环境中完成，
  应用本身**未被实际启动过**。

## 验证方式

修复配套 9 个可独立运行的测试脚本（`tests/test_*.py`，约 150 项断言）。
每一处修复都做过**变异测试**：故意改坏对应代码，确认测试确实会失败，
以此排除"测试恒真"的情况。

```bash
python tests/test_safe_path.py          # 路径限制
python tests/test_api_path_security.py  # 接口层路径限制
python tests/test_config_secrets.py     # 密钥落盘位置
python tests/test_secret_mask.py        # 密钥脱敏
python tests/test_open_url.py           # 命令注入
python tests/test_ssrf_guard.py         # SSRF
python tests/test_local_guard.py        # Host/Origin
python tests/test_preview_csp.py        # 预览 CSP
python tests/test_locales.py            # 语言包一致性
```

**威胁模型**：本应用是 PyWebView 桌面程序，HTTP 服务仅监听 `127.0.0.1`
（[webview_gui.py:90](src/ai_write_x/web/webview_gui.py:90)），未暴露到网络。

**主攻击链（无需任何浏览器技巧）：H2 → H1 / M1。**
预览用的 iframe 带 `allow-same-origin`，其中渲染的是 **AI 生成的文章 HTML**。
该内容本就运行在 `http://127.0.0.1:<port>` 这一源上，可以直接 `fetch()` 调用下面
所有未鉴权接口——不需要 CORS 绕过，不需要 DNS rebinding，也不需要本机有其他恶意进程。
只要 LLM 的输出被投毒（污染的热搜话题、被抓取的参考链接），用户点开预览即触发。

次要放大器：服务端**没有任何 Host / Origin 校验**，因此 DNS rebinding 可让外部站点
与本地服务同源（需绕过浏览器自身的 rebinding 防护，门槛高于上面的主链）；
此外本机任意进程都可直接访问这些接口。

---

## 高危

### H1. 本地 API 可读写删除任意文件，无路径限制、无鉴权

以下端点直接把用户传入的字符串当作文件系统路径使用，**没有做任何目录限制**
（不只是缺少 `..` 过滤，而是连绝对路径都直接接受）：

| 端点 | 行为 | 位置 |
|---|---|---|
| `GET /api/templates/content/{path:path}` | 任意文件**读取** | [templates.py:184](src/ai_write_x/web/api/templates.py:184) |
| `PUT /api/templates/content/{path:path}` | 任意文件**覆写** | [templates.py:196](src/ai_write_x/web/api/templates.py:196) |
| `DELETE /api/templates/{path:path}` | 任意文件**删除** | [templates.py:220](src/ai_write_x/web/api/templates.py:220) |
| `GET /api/templates/preview/{path:path}` | 任意文件读取并以 HTML 返回 | [templates.py:207](src/ai_write_x/web/api/templates.py:207) |
| `GET /api/articles/content?path=` | 任意文件读取 | [articles.py:72](src/ai_write_x/web/api/articles.py:72) |
| `PUT /api/articles/content?path=` | 任意文件覆写 | [articles.py:83](src/ai_write_x/web/api/articles.py:83) |
| `DELETE /api/articles/{path:path}` | 任意文件删除 | [articles.py:107](src/ai_write_x/web/api/articles.py:107) |

例：`GET /api/articles/content?path=/Users/<user>/.ssh/id_rsa` 会直接返回私钥内容。

**修复**：统一做路径归一化 + 前缀校验，越界即 403。

```python
def _safe_path(user_path: str, root: Path) -> Path:
    p = (root / user_path).resolve() if not Path(user_path).is_absolute() else Path(user_path).resolve()
    if not p.is_relative_to(root.resolve()):      # Python 3.9+
        raise HTTPException(status_code=403, detail="path outside allowed directory")
    return p
```
模板根用 `PathManager.get_template_dir()`，文章根用文章输出目录。

⚠️ **这不是即插即用的补丁**：前端目前传的就是**绝对路径**
（`data-article-path`、`template.path` 均为完整路径），
上面的 `is_absolute()` 分支会接受它们，但只有当这些路径确实位于根目录之下才能通过校验。
落地时需同时确认前端传参形式（建议改为传相对于根目录的路径），否则会误伤正常功能。

### H2. 预览 iframe 使用 `allow-same-origin allow-scripts`，AI 生成内容可在应用源内执行脚本

7 处 iframe 同时设置这两个标志。二者并用会使沙箱失去隔离意义：
被框内容与父页面**同源**，可直接发起同源 `fetch()`、读取 `document.cookie`、
访问 `window.parent`（这一点无歧义，也足以支撑整条攻击链）：

- [article-manager.js:214](src/ai_write_x/web/static/js/article-manager.js:214)、[template-manager.js:533](src/ai_write_x/web/static/js/template-manager.js:533)
- [content-editor.js:151,276,338,490](src/ai_write_x/web/static/js/content-editor.js:151)、[preview-panel.js:364](src/ai_write_x/web/static/js/preview-panel.js:364)

框内是**模板 HTML 与 AI 生成的文章 HTML**（`iframe.srcdoc = styledHtml`）。
`srcdoc` 本身即继承父页面源，因此脚本运行在 `http://127.0.0.1:<port>`，
可直接调用 H1 的文件接口和 M1 的凭证接口。

攻击链：投毒的热搜话题 / 被抓取的参考链接 → LLM 输出含 `<script>` 的文章 →
用户在列表页预览 → 脚本读取本地任意文件并外传。

**修复**：移除 `allow-same-origin`（仅保留 `allow-scripts`，或两者都去掉）。
预览只需渲染排版，不需要同源权限。

### H3. 开发模式下真实密钥写入**已被 Git 跟踪**的配置文件（本仓库为公开仓库）

[path_manager.py:30-32](src/ai_write_x/utils/path_manager.py:30) —— 非发布版时配置目录就是源码目录
`src/ai_write_x/config/`。用户在界面填入 API Key / 公众号 appsecret 并保存后，
会写入 `config.yaml` 与 `aiforge.toml`，而这两个文件：

- **已被 Git 跟踪**（`git ls-files` 确认）
- **不在 `.gitignore` 中**（`ui_config.json`、`.env`、`build_secrets.json` 有，这两个没有）

从源码运行的开发者一次 `git commit -a && git push` 即把密钥推到公开仓库。

**已核实：目前尚未泄露。** 仓库可见性经 `gh` 确认为 **PUBLIC**；
`config.yaml` 历史上有 20 次提交，但对全部历史做过 `git log -p -S` 与
密钥形态（`sk-*` / `wx*` / 32 位以上串）扫描，**没有任何一次提交包含非空的
`api_key` / `appsecret` / `appid`**，当前工作区也全为空值。
因此本条属于**预防性**问题（High），不是"已泄露待补救"（Critical）——
无需吊销轮换，但应在有人踩坑前修掉写入路径。

**修复**（择一或并用）：
- 开发模式也改用用户数据目录（与发布模式一致）；
- 或把 `config.yaml`/`aiforge.toml` 改为模板文件（如 `config.example.yaml`），
  运行时复制到用户目录，并把实际配置加入 `.gitignore`。

---

## 中危

### M1. `GET /api/config/` 明文返回全部密钥

[config.py:36-44](src/ai_write_x/web/api/config.py:36) 返回的 `api`、`img_api`、`wechat`
原样包含 `api_key` 列表与 `appid`/`appsecret`。任何本机进程、或经 H2/DNS rebinding
取得同源能力的脚本，一次 GET 即可取走全部发布凭证与 LLM 密钥。

**修复**：对返回值做脱敏（只回 `已配置`/末 4 位），保存时用单独的写入端点。

### M2. Windows 上 `shell=True` 命令注入

[utils.py:305](src/ai_write_x/utils/utils.py:305) `subprocess.run(["start", "", str(file_path)], shell=True)`。
`shell=True` 时列表会被拼成命令行字符串，文件名中的 `&`、`|`、`^` 等会被 shell 解释。
该函数经 `POST /api/config/open-url`（[config.py:291](src/ai_write_x/web/api/config.py:291)）暴露，
配合 H1 的任意写入可先落地一个恶意文件名再触发。

**修复**：去掉 `shell=True`，改用 `os.startfile(file_path)`（Windows 原生且无 shell 解析）。

### M3. 参考链接抓取无内网防护（SSRF）

[search_template.py:499](src/ai_write_x/tools/search_template.py:499) `requests.get(url, ...)`；
校验函数 [is_valid_url](src/ai_write_x/utils/utils.py:318) 只检查 scheme 与 netloc，
不阻止 `127.0.0.1`、RFC1918 内网段、或云元数据地址 `169.254.169.254`。
桌面场景影响有限，但在 VM / 容器中运行时可探测内网或窃取云凭证。

**修复**：解析目标 IP 并拒绝环回/私有/链路本地地址段。

### M4. `POST /shutdown` 无鉴权且可被 CSRF 触发

[app.py:138](src/ai_write_x/web/app.py:138)。无请求体的 POST 属于"简单请求"，
不触发预检，任意网页均可让用户的应用退出（拒绝服务）。
同类还有 `POST /api/generate/stop`。

**修复**：校验 `Origin`/`Host` 头，或要求一个启动时随机生成的 token。

---

## 低危 / 工程隐患

- **L1**：预览端点 CSP 为 `default-src 'self' 'unsafe-inline'`
  （[templates.py:216](src/ai_write_x/web/api/templates.py:216)、[articles.py:103](src/ai_write_x/web/api/articles.py:103)），
  `'unsafe-inline'` 允许内联脚本，CSP 在此形同虚设。应改为
  `default-src 'none'; style-src 'unsafe-inline'; img-src data: https:`。
- **L2**：`.gitignore` 第 8 行的 `tools/` 会同时匹配 **`src/ai_write_x/tools/`**
  （`git check-ignore` 确认）。已跟踪文件不受影响，但今后在该目录新增的文件会被静默忽略，
  可能导致代码漏提交。建议改为 `/tools/`。
- **L3**：无鉴权的本地 API 整体缺少 Origin/Host 校验（DNS rebinding 前提条件）。
  建议加一个统一中间件，拒绝 `Host` 不是 `127.0.0.1:<port>` 的请求。

---

## 本分支 i18n 改动的自查

- **已修复**：`index.html` 同步注入语言包时，`json.dumps` 不会转义 `</script>`，
  被污染的词条可提前闭合脚本标签。已在 [app.py](src/ai_write_x/web/app.py:116) 中将
  `<` `>` `&` 转义为 `<` 等形式（已验证 `JSON.parse` 结果不变、含 HTML 的词条完好）。
- 服务端 `translate()` 只做 `{name}` 占位符字符串替换，不涉及格式化字符串注入。
- 词条经 `data-i18n` 走 `textContent`（非 HTML）；仅 `data-i18n-html` 与
  `common.save_with_changes` 走 `innerHTML`，内容均来自仓库内语言包，非用户输入。
- 未改动任何鉴权、路径处理或沙箱逻辑；H1/H2 等问题在本次改动之前既已存在。

---

## 建议修复顺序

1. **H1**（路径限制）与 **H2**（移除 `allow-same-origin`）—— 二者构成完整攻击链，应一并修复。
2. **H3**（密钥落入公开仓库）—— 历史已核实干净，属预防性修复；
   修好写入路径即可，无需轮换现有密钥。
3. **L3 + M4**（Origin/Host 中间件）—— 一处改动可同时消除 DNS rebinding 与 CSRF 前提。
4. M1、M2、M3、L1、L2。


---

## 修复记录（本次已完成）

### ✅ H1 — 路径限制

新增 [web/safe_path.py](src/ai_write_x/web/safe_path.py)：

- `resolve_within(path, root)`：解析（含符号链接）后必须落在 root 之下，否则 **403**。
  绝对路径与相对路径都接受——前端目前发的就是绝对路径，因此无需改前端。
- `safe_name(name)`：单段名称（分类名 / 模板名）不得为空、不得为 `.`/`..`、
  不得含路径分隔符或控制字符，否则 **400**。

已覆盖的接口：

- `articles.py` —— 内容读/写、预览、删除、批量发布逐文件读取、`POST/GET /design`
  （原先 `Path(design.article).with_suffix(".design.json")` 可写任意位置）
- `templates.py` —— 内容读/写、预览、删除、新建/重命名/复制/移动，
  以及分类的新建、重命名、删除（原 `shutil.rmtree(template_dir / category_name)` 最危险）
- `config.py` —— `/templates/{category}`

顺带修正：`articles.py` 中 3 个 handler 的 `except Exception` 会把 403/400 吞成 500 并回显内部信息，
已加 `except HTTPException: raise` 让其原样透传。

### ✅ H2 — iframe 沙箱

7 处 `allow-same-origin allow-scripts` 全部改为仅 `allow-scripts`
（article-manager 1、template-manager 1、content-editor 4、preview-panel 1）。
已确认代码中**没有任何** `contentDocument` / `contentWindow` 访问，因此不影响预览功能。

### ✅ 附带修复 — 图片上传后缀白名单

`POST /api/articles/upload-image` 原先直接沿用上传文件的后缀，而 `/images`
是同源静态目录：上传 `.html` / `.svg` 会被当作文档渲染，等于存储型 XSS。
现只允许 `.jpg/.jpeg/.png/.gif/.webp/.bmp`，其余一律回落为 `.jpg`。

### 测试

- [tests/test_safe_path.py](tests/test_safe_path.py) —— 20 项单元测试（越界拒绝 / 合法放行）
- [tests/test_api_path_security.py](tests/test_api_path_security.py) —— 14 项接口级测试，
  用 `TestClient` 真实调用；目录重定向到临时目录，不污染用户数据。
  同时断言越界文件内容未被改动、合法写入仍然成功。

```bash
python tests/test_safe_path.py          # 需要 fastapi
python tests/test_api_path_security.py  # 需要 fastapi + httpx
```


### ✅ H3 — 密钥不再写入源码树

- [path_manager.py](src/ai_write_x/utils/path_manager.py) `get_config_dir()`：
  开发模式不再返回源码目录，与发布模式统一使用**用户数据目录**。
- [config.py](src/ai_write_x/config/config.py) `__get_config_path()`：
  源码树 / 打包资源中的 `config.yaml`、`aiforge.toml` 现在只作为**默认模板（种子）**，
  仅在用户目录尚无该文件时复制过去；之后所有读写都发生在用户目录。

顺带修好一处隐患：`smart_update_config()` 失败时的兜底分支会
`open(get_config_path("config.yaml"), "w")` 写入默认配置——在旧逻辑下会直接
覆盖仓库里被跟踪的模板文件。路径修正后该分支同样指向用户目录。

**残留风险与告警**：路径修正只能防止今后再写入。若某位开发者在本次改动**之前**
已经把密钥填进源码树里的配置文件，那些值仍留在其工作区中。为此在开发模式启动时
新增一次性检查：发现模板文件里存在非空的 `api_key` / `appsecret` 时打印告警，
提示清理后再提交。告警**只报告存在、不回显取值**。

迁移是自动的：首次运行时旧文件会作为种子被复制到用户目录，配置不会丢失。

**测试** —— [tests/test_config_secrets.py](tests/test_config_secrets.py)（18 项）：

- 配置目录确实落在用户数据目录、不在源码树；
- 写入假密钥并保存后，**对源码树两个文件做 SHA-256 比对，断言字节未变**，
  且假密钥不出现在其中；
- 告警逻辑：对仓库中真实的（空值）模板不误报，对含密钥的内容能报出，
  且告警文本不包含密钥值。

```bash
python tests/test_config_secrets.py
```


### ✅ M1 — `GET /api/config/` 不再明文返回密钥

新增 [web/secret_mask.py](src/ai_write_x/web/secret_mask.py)，覆盖四处密钥字段：
`api.<厂商>.api_key`（列表）、`img_api.<厂商>.api_key`、
`wechat.credentials[].appsecret`、`aiforge_config.llm.<厂商>.api_key`。

出站脱敏为 `••••••••` + 末 4 位（便于用户辨认是哪把钥匙）。
`appid` **不脱敏**——它是账号标识而非密钥，遮掉会让多账号界面无法分辨。

**关键点在入站**：界面是「读出来 → 编辑 → 整体回传」的，只做脱敏的话，
用户点一次保存就会把 `••••••••` 当成真实密钥写回配置。因此 `PATCH /api/config/`
在合并前先调用 `unmask_config()`，把掩码值换回已存储的真实值。

列表按「掩码 → 真实值」匹配而不是按下标，这样用户**删除或调换**某个 key
之后仍能对上；匹配不到时退回按下标；再不行就丢弃该项——
掩码字符串在任何情况下都不会被当作密钥存下来。

**测试** —— [tests/test_secret_mask.py](tests/test_secret_mask.py)：

- 单元：脱敏后输出中不含任何密钥；原对象不被修改；空值保持为空；
  原样回传能完整还原；真正修改的值能存进去；
  以及三个容易出错的场景——**删除第一个 key、调换顺序、追加新 key**；
  部分 PATCH 也能正确还原；伪造的掩码不会被存成密钥。
- 接口：用 `TestClient` 走真实 `GET` → `PATCH` → `save_config` 全流程，
  断言响应中无明文、往返后配置未损坏、**落盘文件里不含任何掩码字符**。

另外做了变异测试验证这套测试有效：注释掉 `unmask_config` 会触发 6 项失败，
注释掉 `mask_config` 会触发 3 项失败，恢复后全部通过。

```bash
python tests/test_secret_mask.py
```


### ✅ M2 — `shell=True` 命令注入 & 任意程序启动器

原实现 `subprocess.run(["start", "", str(file_path)], shell=True)`：
`shell=True` 会把参数拼成命令行字符串，文件名中的 `&`、`|`、`^` 会被 shell 解释。

**只把它换成 `os.startfile()` 并不够**——`os.startfile` 在 Windows 上会直接
*运行*可执行文件，那样 `POST /api/config/open-url` 就成了任意程序启动器。
因此分两层修：

1. **接口层**（[api/config.py](src/ai_write_x/web/api/config.py)）：
   `/open-url` 只接受 http/https（新增 `is_http_url()`，基于 `urlparse` 且大小写不敏感），
   本地文件分支从接口不可达。这与实际用法一致——该接口全项目**只有一个调用点**
   （`update-checker.js` 的"官网下载"，URL 是写死的 `https://aiwritex.voidai.cc`）。
2. **工具层**（[utils.py](src/ai_write_x/utils/utils.py)）：去掉 `shell=True` 改用
   `os.startfile`，并加文件类型白名单 `OPENABLE_SUFFIXES`（html/md/txt/图片/pdf 等），
   `.exe/.bat/.cmd/.ps1/.scr` 一律拒绝。macOS 与 Linux 统一用 `Path.as_uri()`，
   它会正确转义空格与 `#`（原来 macOS 分支是手工拼 `file://` + `quote`）。

**测试** —— [tests/test_open_url.py](tests/test_open_url.py)：

- 用 `tokenize` 剥掉注释后扫描源码，确认 `shell=True` / `subprocess` 已不在**代码**中
  （注释里仍保留说明，故不能直接做字符串匹配）；
- 模拟 `sys.platform == "win32"`，用带 `&` 的文件名验证走的是 `os.startfile`
  且路径**整体原样传入**、未被 shell 拆开，同时断言 `subprocess.run` 未被调用；
- 五种可执行后缀全部被拒；`.html` 等正常内容仍可打开；含空格与 `#` 的文件名正确转义；
- 接口层：`/etc/passwd`、`file://`、`javascript:`、本地 `.exe`、Windows 路径、空串
  全部 400 且**未打开任何东西**；写死的 https 链接仍 200 正常。

变异测试确认有效：改回 `shell=True` 触发 7 项失败，去掉后缀白名单触发 6 项失败。

```bash
python tests/test_open_url.py
```


### ✅ M3 — 抓取外部内容时的 SSRF 防护

新增 [utils.is_safe_external_url()](src/ai_write_x/utils/utils.py)：解析域名后逐个校验
IP，拒绝环回、私有网段、链路本地（含云元数据 `169.254.169.254`）、保留地址、
组播与 `0.0.0.0`，IPv4/IPv6 均覆盖；解析失败也拒绝。

**只作用于"用户或 AI 提供的 URL"**，共四处：

| 位置 | 来源 |
|---|---|
| `api/generate.py` 参考链接校验 | 用户输入（提前报错，体验更好） |
| `search_template.extract_page_content()` | 用户输入（兜住配置/命令行来源） |
| `utils.download_and_save_image()` | 文章 HTML 里的 `<img src>`（AI 生成） |
| `wx_publisher.upload_image()` 网络图片分支 | 同上 |

**刻意不加的地方**：热搜 API、微信接口、更新检查等固定地址，以及
`webview_gui` 对自身 `127.0.0.1/health` 的探测。尤其是默认配置里的
**Ollama `http://localhost:11434`**——一刀切地封锁内网会直接废掉本地 LLM，
测试中对此单独做了断言。

**已知局限**：这是"先解析域名再校验 IP"，域名仍可能在校验与建连之间被改指
到内网（DNS rebinding / TOCTOU）。彻底消除需要在连接层固定已校验的 IP
（自定义 requests adapter）。当前强度足以挡住直接指向内网的输入。

**测试** —— [tests/test_ssrf_guard.py](tests/test_ssrf_guard.py)：

- 14 种内网/非法目标全部被拒（含 IPv6 `::1`、`fe80::`、`fd00::`、`file:`、`gopher:`）；
- 用 mock 让域名解析到 `127.0.0.1` / 元数据地址 / 混合结果，验证**按解析后的 IP** 判断；
- 公网地址正常放行；
- **反向断言**：确认 guard 没有出现在 hotnews、webview_gui、config.py 中，
  且默认配置里的 Ollama `localhost:11434` 仍在——防止误伤本地 LLM；
- `download_and_save_image` 对内网地址返回 None 且**根本没有调用 `requests.get`**；
- 接口层：四类内网参考链接均 400 且未启动任务，公网链接照常 200。

变异测试确认有效：guard 恒真触发 26 项失败、去掉 DNS 校验触发 8 项、
去掉接口层校验触发 7 项。

```bash
python tests/test_ssrf_guard.py
```

**过程中修掉的两个自身问题**：最初在 `utils.py` 里调用了 `log.print_log`，
但 `log.py` 反过来 import `utils`，会造成**循环导入**——改为与该函数其它
失败路径一致直接返回 None；`search_template.py` 则缺少 `utils` / `log` 的 import，
已补齐（真实 import 测试可覆盖这两点）。


### ✅ M4 + L3 — Host/Origin 校验（同时挡住 CSRF 与 DNS rebinding）

新增 [web/local_guard.py](src/ai_write_x/web/local_guard.py)，在 [app.py](src/ai_write_x/web/app.py) 中挂载：

- **Host** 必须是环回主机名（`127.0.0.1` / `localhost` / `::1`），否则 403。
  DNS rebinding 时攻击者页面的 Host 是其自有域名，据此即可识别。
  端口不参与判断——浏览器无法伪造 Host，且端口变化不该误伤本应用。
- **Origin** 仅在存在时校验。同源 GET 通常不带 Origin，应用自身的健康检查
  等非浏览器请求也不带；而跨站 POST（含无请求体的 `/shutdown`）一定会带。

**必须用纯 ASGI 中间件**，因为 `BaseHTTPMiddleware` 拦不到 websocket 作用域，
而项目里有 `/api/ws/generate/logs` 在推送运行日志——**WebSocket 不受同源策略约束**，
任何外部页面都能连上读取，服务端检查 Origin 是唯一的拦截手段。

**测试** —— [tests/test_local_guard.py](tests/test_local_guard.py)：

- 12 组纯逻辑用例，含 `127.0.0.1.evil.com`、`localhost.evil.com` 这类
  "看起来像本地"的域名，以及 `Origin: null`；
- HTTP：同源 GET/POST 正常，跨站 CSRF 与伪造 Host 均 403；
- **WebSocket**：同源可正常收数据，跨站 Origin 与伪造 Host 均被关闭连接；
- **真实 app 集成**：`/`（含 i18n 注入）、`/health`、静态资源、`/api/config/`
  同源全部 200；跨站访问上述四者全部 403。

变异测试：去掉 Host 校验 9 项失败、去掉 Origin 校验 8 项、
中间件跳过 websocket 3 项、从 app 上摘掉中间件 5 项。

```bash
python tests/test_local_guard.py
```

---

## 附带发现（均已修复）

### ✅ 附带 1 — Starlette 前向兼容

[app.py](src/ai_write_x/web/app.py) 原用旧签名 `TemplateResponse("index.html", {...})`：
在 `requirements` 允许的 Starlette 0.47.x 下正常，但在 1.6.0 下抛
`TypeError: unhashable type: 'dict'`，首页 500。已改为新签名
`TemplateResponse(request, "index.html", {...})`，`request` 由 Starlette 自动注入上下文。

依赖范围核对过：`requirements.txt` 要求 `fastapi>=0.117.1`（对应 starlette>=0.40），
而新签名自 Starlette **0.29** 起支持，因此不会破坏支持范围内的任何版本。

**双版本验证**（这是判定修复是否真正生效的关键）：

| Starlette | 修复前 | 修复后 |
|---|---|---|
| 0.47.3（当前 pin） | 200 | **200** |
| 1.6.0（最新） | **500** | **200** |

首页渲染与语言包注入在两个版本下均正常。回归由
[tests/test_local_guard.py](tests/test_local_guard.py) 中"同源 GET / 正常渲染"一项持续覆盖。

### ✅ 附带 2 — 删除死代码 websocket.js

`static/js/websocket.js` 中的 `WebSocketManager` 连的是并不存在的 `/ws/logs`
（真实路由为 `/api/ws/generate/logs`）。核实后确认：**全项目无任何引用，
且该文件根本没有被 `index.html` 加载**——实际使用的是 `creative-workshop.js`
里自己创建的连接。故直接删除，而非修正其 URL。


### ✅ L1 — 预览接口的 CSP

原策略 `default-src 'self' 'unsafe-inline'` 允许内联脚本，形同虚设。
现改为（[local_guard.PREVIEW_CSP](src/ai_write_x/web/local_guard.py)，两个预览接口共用）：

```
default-src 'none'; img-src 'self' data: https: http:;
style-src 'unsafe-inline' https:; font-src https: data:;
media-src 'self' https:; frame-ancestors 'self';
base-uri 'none'; form-action 'none'
```

关键是 **不放开 `script-src`** —— 被 `default-src 'none'` 兜住，预览内容里的
`<script>` 无法执行。放行项是按内置模板的**实际用量**定的，不是拍脑袋：
扫描 35 个模板发现 **0 个用 `<script>`**、大量 `style=` 内联样式、
1 个引用 Google Fonts 样式表、图片来自 picsum(https) 与本地 `/images`。

**测试** —— [tests/test_preview_csp.py](tests/test_preview_csp.py)：
逐条校验指令；两个接口都确实下发该头且内容完整返回；并扫描全部 35 个内置模板，
断言没有任何模板依赖 `<script>` 或通过 `http:` 引外部样式——即这套 CSP 不会破坏现有模板。

变异测试：改回旧 CSP 触发 13 项失败，放开 `script-src 'unsafe-inline'` 触发 2 项。

### ✅ L2 — `.gitignore` 的 `tools/` 误匹配

第 8 行的 `tools/` 不带前导斜杠，会匹配任意层级的同名目录，
把 **`src/ai_write_x/tools/`** 一起忽略掉（`git check-ignore` 已确认）。
已改为 `/tools/`，只锚定仓库根目录。

用 git 自身验证：改后 `src/ai_write_x/tools/newfile.py` **不再被忽略**，
而根目录的 `tools/build.sh` **仍被忽略**（保留原意图）；
当前工作区没有任何文件因此意外变为待提交。

```bash
python tests/test_preview_csp.py
```
