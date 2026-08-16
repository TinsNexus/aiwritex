// 界面语言管理器 | UI locale manager
// 语言包由后端在页面加载时注入，因此切换语言需要重新加载页面才能生效。
class LocaleManager {
    constructor() {
        this.currentLocale = (window.i18n && window.i18n.locale) || 'zh_CN';
        // 页面载入时的语言，用于判断保存后是否需要重新加载
        this.initialLocale = this.currentLocale;
        this.waitForConfigManager();
    }

    waitForConfigManager() {
        if (window.configManager) {
            this.configManager = window.configManager;
            // 等待 onConfigLoaded 回调，与 themeManager 保持一致
        } else {
            setTimeout(() => this.waitForConfigManager(), 50);
        }
    }

    onConfigLoaded() {
        this.init();
    }

    init() {
        this.populateSelector();
        this.bindLocaleSelector();
    }

    // 依据后端提供的可用语言列表填充下拉框
    populateSelector() {
        const selector = document.getElementById('locale-selector');
        if (!selector) return;

        const available = (window.i18n && window.i18n.available) || [];
        selector.innerHTML = '';
        available.forEach((item) => {
            const option = document.createElement('option');
            // 兼容两种格式：{value,label} 或纯字符串
            option.value = item.value || item;
            option.textContent = item.label || item;
            selector.appendChild(option);
        });
        selector.value = this.currentLocale;
    }

    bindLocaleSelector() {
        const selector = document.getElementById('locale-selector');
        if (!selector) return;

        selector.addEventListener('change', (e) => {
            this.currentLocale = e.target.value;
            if (this.configManager) {
                this.configManager.uiConfig.locale = this.currentLocale;
            }

            // 与主题/窗口模式选择器一致：仅标记未保存，保存时才落盘
            const saveBtn = document.getElementById('save-ui-config');
            if (saveBtn && !saveBtn.classList.contains('has-changes')) {
                saveBtn.classList.add('has-changes');
                saveBtn.innerHTML = window.i18n.t('common.save_with_changes');
            }
        });
    }

    // 保存后如语言发生变化则重新加载，使新的语言包生效
    reloadIfLocaleChanged() {
        if (this.currentLocale !== this.initialLocale) {
            window.location.reload();
            return true;
        }
        return false;
    }
}

document.addEventListener('DOMContentLoaded', () => {
    window.localeManager = new LocaleManager();
});
