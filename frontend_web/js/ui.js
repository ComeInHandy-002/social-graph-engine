// js/ui.js — UI 工具模块
//
// 提供 Toast 通知、模态框、加载状态、快捷键面板等 UI 工具
//
// 导入: store (state.js)
// 导出: UIManager 类
//
// 连接: app.js 创建实例, 所有模块通过 store 或直接调用 UI 方法

import { store } from './state.js';

export class UIManager {
    constructor() {
        this.toastTimer = null;
    }

    // ============================
    // Toast 通知
    // ============================

    /**
     * 显示 Toast 通知
     * @param {string} message - 消息内容
     * @param {string} type - 'success' | 'warning' | 'error' | 'info'
     * @param {number} duration - 显示时长(ms), 默认 3000
     */
    toast(message, type = 'success', duration = 3000) {
        const container = document.getElementById('toast-container');
        if (!container) {
            console.warn(`[Toast] ${message}`);
            return;
        }

        const icons = {
            success: '✅', // ✅
            warning: '⚠️', // ⚠️
            error: '\u{1F6A8}', // 🚨
            info: 'ℹ️' // ℹ️
        };

        const toast = document.createElement('div');
        toast.className = `cyber-toast ${type}`;
        toast.setAttribute('role', 'status');
        toast.setAttribute('aria-live', 'polite');
        toast.innerHTML = `<span aria-hidden="true">${icons[type] || ''}</span> <span>${this._escapeHtml(message)}</span>`;

        container.appendChild(toast);

        // 自动移除
        const removeTimer = setTimeout(() => {
            toast.style.animation = 'fadeOutUp 0.3s forwards';
            setTimeout(() => {
                if (toast.parentNode) toast.remove();
            }, 300);
        }, duration);

        // 点击可提前关闭
        toast.addEventListener('click', () => {
            clearTimeout(removeTimer);
            toast.style.animation = 'fadeOutUp 0.3s forwards';
            setTimeout(() => {
                if (toast.parentNode) toast.remove();
            }, 300);
        });

        return toast;
    }

    // ============================
    // 加载状态
    // ============================

    showLoading(text = '系统休眠中...', progress = '') {
        const screen = document.getElementById('loading-screen');
        const textEl = document.getElementById('loading-text');
        const progEl = document.getElementById('loading-progress');

        if (!screen) return;

        screen.style.display = 'flex';
        screen.setAttribute('aria-hidden', 'false');

        if (textEl) textEl.innerText = text;

        if (progEl) {
            if (progress) {
                progEl.style.display = 'block';
                progEl.innerText = progress;
            } else {
                progEl.style.display = 'none';
            }
        }

        store.set('uiState', {
            ...store.get('uiState'),
            loading: true,
            loadingText: text,
            loadingProgress: progress
        });
    }

    hideLoading() {
        const screen = document.getElementById('loading-screen');
        if (!screen) return;

        screen.style.display = 'none';
        screen.setAttribute('aria-hidden', 'true');

        store.set('uiState', {
            ...store.get('uiState'),
            loading: false,
            loadingText: '',
            loadingProgress: ''
        });
    }

    // ============================
    // 模态框
    // ============================

    /**
     * 显示模态框
     * @param {object} options
     * @param {string} options.title - 标题
     * @param {string|HTMLElement} options.content - 内容 (HTML 字符串或 DOM 元素)
     * @param {Array<{text:string, onClick:Function, primary?:boolean}>} [options.buttons] - 按钮
     * @param {boolean} [options.closeOnOverlay=true] - 点击遮罩关闭
     * @returns {HTMLElement} 模态框元素
     */
    showModal({ title, content, buttons = [], closeOnOverlay = true }) {
        // 移除已有模态框
        this.closeModal();

        const modal = document.createElement('div');
        modal.className = 'modal-overlay';
        modal.setAttribute('role', 'dialog');
        modal.setAttribute('aria-modal', 'true');
        modal.setAttribute('aria-label', title);

        const dialog = document.createElement('div');
        dialog.className = 'modal-dialog';

        // 标题
        const h3 = document.createElement('h3');
        h3.textContent = title;
        dialog.appendChild(h3);

        // 内容
        if (typeof content === 'string') {
            const body = document.createElement('div');
            body.innerHTML = content;
            dialog.appendChild(body);
        } else if (content instanceof HTMLElement) {
            dialog.appendChild(content);
        }

        // 按钮
        if (buttons.length > 0) {
            const btnRow = document.createElement('div');
            btnRow.style.cssText = 'display:flex;gap:8px;justify-content:flex-end;margin-top:16px;';

            buttons.forEach(btn => {
                const button = document.createElement('button');
                button.textContent = btn.text;
                button.style.width = 'auto';
                if (btn.primary) button.className = 'btn-primary';
                button.addEventListener('click', () => {
                    if (btn.onClick) btn.onClick();
                    this.closeModal();
                });
                btnRow.appendChild(button);
            });

            dialog.appendChild(btnRow);
        }

        modal.appendChild(dialog);
        document.body.appendChild(modal);

        // 点击遮罩关闭
        if (closeOnOverlay) {
            modal.addEventListener('click', (e) => {
                if (e.target === modal) this.closeModal();
            });
        }

        // 焦点陷阱: 第一个可聚焦元素
        const focusable = dialog.querySelectorAll(
            'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
        );
        if (focusable.length > 0) focusable[0].focus();
        else dialog.setAttribute('tabindex', '-1');

        // Escape 关闭
        const escHandler = (e) => {
            if (e.key === 'Escape') {
                this.closeModal();
                document.removeEventListener('keydown', escHandler);
            }
        };
        document.addEventListener('keydown', escHandler);

        modal._escHandler = escHandler;
        store.set('uiState', { ...store.get('uiState'), activePanel: 'modal' });

        return modal;
    }

    /**
     * 关闭当前模态框
     */
    closeModal() {
        const existing = document.querySelector('.modal-overlay');
        if (existing) {
            if (existing._escHandler) {
                document.removeEventListener('keydown', existing._escHandler);
            }
            existing.remove();
        }
        store.set('uiState', { ...store.get('uiState'), activePanel: null });
    }

    // ============================
    // 快捷键面板
    // ============================

    showShortcuts() {
        // 如果已存在则切换关闭
        const existing = document.querySelector('.modal-overlay');
        if (existing && existing.querySelector('.modal-dialog table')) {
            this.closeModal();
            return;
        }

        const shortcuts = [
            { key: 'H', desc: '显示 / 隐藏此面板' },
            { key: 'R', desc: '重置视角与状态' },
            { key: 'L', desc: '载入核心数据集' },
            { key: 'F', desc: '聚焦搜索栏' },
            { key: 'S', desc: '切换数据洞察面板' },
            { key: 'Space', desc: '播放 / 暂停时间轴' },
            { key: 'Esc', desc: '关闭面板 / 清空搜索' },
            { key: '← ↑ → ↓', desc: '图导航 / 结果列表' },
            { key: '右键 / 长按', desc: '探测目标人脉圈' },
            { key: '拖拽节点', desc: '自定义星网布局' },
        ];

        const tableHtml = `
            <table>
                ${shortcuts.map(s => `
                    <tr>
                        <td><kbd>${s.key}</kbd></td>
                        <td>${s.desc}</td>
                    </tr>
                `).join('')}
            </table>`;

        this.showModal({
            title: '⌨️ 键盘快捷键', // ⌨️
            content: tableHtml,
            buttons: [{ text: '关闭', onClick: () => {}, primary: true }]
        });
    }

    // ============================
    // 确认对话框
    // ============================

    /**
     * 确认对话框
     * @param {string} message
     * @returns {Promise<boolean>}
     */
    confirm(message) {
        return new Promise((resolve) => {
            this.showModal({
                title: '确认操作',
                content: `<p style="color:var(--color-text-primary);">${this._escapeHtml(message)}</p>`,
                buttons: [
                    { text: '取消', onClick: () => resolve(false) },
                    { text: '确认', onClick: () => resolve(true), primary: true }
                ]
            });
        });
    }

    // ============================
    // 工具方法
    // ============================

    _escapeHtml(str) {
        const div = document.createElement('div');
        div.appendChild(document.createTextNode(str));
        return div.innerHTML;
    }

    /**
     * 更新状态面板 (节点/边计数)
     */
    updateStats(nodes, edges) {
        const statNodes = document.getElementById('stat-nodes');
        const statEdges = document.getElementById('stat-edges');
        if (statNodes) statNodes.innerText = nodes;
        if (statEdges) statEdges.innerText = edges;
    }
}
