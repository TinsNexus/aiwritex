// 国际化(i18n)运行时 | i18n runtime
// 词条由后端在 index.html 中同步注入(window.__I18N__)，因此本文件无需异步加载，
// 可安全地在其他脚本之前完成初始化。
class I18n {
    constructor() {
        const bootstrap = window.__I18N__ || {};
        this.locale = bootstrap.locale || 'zh_CN';
        this.messages = bootstrap.messages || {};
        this.fallback = bootstrap.fallback || {};
        this.available = bootstrap.available || ['zh_CN'];
        this._missing = new Set();
    }

    // 取词条：当前语言 -> 回退语言(zh_CN) -> key 本身
    t(key, params) {
        let text = this.messages[key];
        if (text === undefined) {
            text = this.fallback[key];
            if (text === undefined) {
                if (!this._missing.has(key)) {
                    this._missing.add(key);
                    console.warn(`[i18n] 缺失词条 / missing key: ${key}`);
                }
                return key;
            }
        }
        if (params) {
            text = text.replace(/\{(\w+)\}/g, (match, name) =>
                params[name] !== undefined ? params[name] : match
            );
        }
        return text;
    }

    // 是否存在词条
    has(key) {
        return this.messages[key] !== undefined || this.fallback[key] !== undefined;
    }

    // 处理 DOM 中的 data-i18n* 标记
    // data-i18n            -> textContent
    // data-i18n-html       -> innerHTML(词条含标签时使用)
    // data-i18n-placeholder/title/aria-label -> 对应属性
    apply(root) {
        const scope = root || document;

        scope.querySelectorAll('[data-i18n]').forEach((el) => {
            el.textContent = this.t(el.getAttribute('data-i18n'));
        });

        scope.querySelectorAll('[data-i18n-html]').forEach((el) => {
            el.innerHTML = this.t(el.getAttribute('data-i18n-html'));
        });

        const attrMap = {
            'data-i18n-placeholder': 'placeholder',
            'data-i18n-title': 'title',
            'data-i18n-aria-label': 'aria-label',
            'data-i18n-value': 'value',
        };
        Object.keys(attrMap).forEach((dataAttr) => {
            scope.querySelectorAll(`[${dataAttr}]`).forEach((el) => {
                el.setAttribute(attrMap[dataAttr], this.t(el.getAttribute(dataAttr)));
            });
        });
    }

    // 应用文档级别的语言标记与标题
    applyDocument() {
        const htmlLang = this.t('app.html_lang');
        document.documentElement.setAttribute('lang', htmlLang);
        document.title = this.t('app.title');
    }
}

window.i18n = new I18n();
// 供其他模块以更短的方式调用
window.t = (key, params) => window.i18n.t(key, params);

document.addEventListener('DOMContentLoaded', () => {
    window.i18n.applyDocument();
    window.i18n.apply(document);
});
