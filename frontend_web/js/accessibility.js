// js/accessibility.js — WCAG 无障碍辅助模块
//
// 提供屏幕阅读器通知、焦点管理、跳过链接、减少动画支持
//
// 导入: store (state.js)
// 导出: AccessibilityManager 类

import { store } from './state.js';

export class AccessibilityManager {
    constructor() {
        this.announcer = null;
        this.focusTrapElement = null;
        this.focusTrapPrevious = null;
    }

    /**
     * 初始化无障碍功能
     */
    init() {
        this._createAnnouncer();
        this._createSkipLink();
        this._watchMotionPreference();
        this._injectCanvasLabels();
    }

    // ============================
    // 屏幕阅读器通知区域 (aria-live)
    // ============================

    _createAnnouncer() {
        this.announcer = document.createElement('div');
        this.announcer.id = 'a11y-announcer';
        this.announcer.setAttribute('aria-live', 'polite');
        this.announcer.setAttribute('aria-atomic', 'true');
        this.announcer.className = 'sr-only';
        document.body.appendChild(this.announcer);
    }

    /**
     * 向屏幕阅读器发送消息
     * @param {string} message - 要朗读的消息
     * @param {'polite'|'assertive'} priority - 优先级
     */
    announce(message, priority = 'polite') {
        if (!this.announcer) this._createAnnouncer();

        // 使用双 div 技巧确保重复消息也会被朗读
        this.announcer.setAttribute('aria-live', priority);
        this.announcer.innerHTML = '';

        requestAnimationFrame(() => {
            this.announcer.innerHTML = `<p>${this._sanitize(message)}</p>`;
        });
    }

    // ============================
    // 跳过导航链接
    // ============================

    _createSkipLink() {
        const skipLink = document.createElement('a');
        skipLink.href = '#main-content';
        skipLink.className = 'skip-link';
        skipLink.textContent = '跳到主要内容';
        skipLink.addEventListener('click', (e) => {
            e.preventDefault();
            const main = document.getElementById('main-content') || document.getElementById('graph');
            if (main) {
                main.setAttribute('tabindex', '-1');
                main.focus();
            }
        });
        document.body.insertBefore(skipLink, document.body.firstChild);
    }

    // ============================
    // Canvas 标签注入
    // ============================

    _injectCanvasLabels() {
        // 为 3d-force-graph 创建的 canvas 添加 ARIA 标签
        const observer = new MutationObserver(() => {
            const canvas = document.querySelector('#graph canvas');
            if (canvas && !canvas.getAttribute('role')) {
                canvas.setAttribute('role', 'img');
                canvas.setAttribute('aria-label', '社交网络三维力导向图。使用键盘 Tab 键导航到控制面板，使用箭头键浏览图数据。');
                observer.disconnect();
            }
        });

        const graphContainer = document.getElementById('graph');
        if (graphContainer) {
            observer.observe(graphContainer, { childList: true, subtree: true });
        }
    }

    /**
     * 更新 Canvas 的 ARIA 描述 (反映当前图状态)
     */
    updateCanvasDescription() {
        const canvas = document.querySelector('#graph canvas');
        if (!canvas) return;

        const graphData = store.get('globalGraphData');
        const step = store.get('timelineStep');
        const focusNode = store.get('focusNode');

        let desc = '社交网络三维力导向图';

        if (graphData) {
            const visibleNodes = graphData.nodes.filter(n => n.birthFrame <= step).length;
            const visibleLinks = graphData.links.filter(l => l.birthFrame <= step).length;
            desc += `。当前显示 ${visibleNodes} 个节点和 ${visibleLinks} 条边`;
        }

        if (focusNode) {
            desc += `。已聚焦节点 ${focusNode}`;
        }

        desc += '。使用键盘 Tab 键导航到控制面板';

        canvas.setAttribute('aria-label', desc);
    }

    // ============================
    // 焦点陷阱 (用于模态框)
    // ============================

    /**
     * 在指定元素内设置焦点陷阱
     * @param {HTMLElement} element - 陷阱容器
     */
    trapFocus(element) {
        this.releaseFocus();

        this.focusTrapElement = element;
        this.focusTrapPrevious = document.activeElement;

        const focusableSelector = [
            'a[href]', 'button:not([disabled])', 'input:not([disabled])',
            'select:not([disabled])', 'textarea:not([disabled])',
            '[tabindex]:not([tabindex="-1"])'
        ].join(',');

        const handler = (e) => {
            if (e.key !== 'Tab') return;

            const focusable = element.querySelectorAll(focusableSelector);
            if (focusable.length === 0) return;

            const first = focusable[0];
            const last = focusable[focusable.length - 1];

            if (e.shiftKey && document.activeElement === first) {
                e.preventDefault();
                last.focus();
            } else if (!e.shiftKey && document.activeElement === last) {
                e.preventDefault();
                first.focus();
            }
        };

        element.addEventListener('keydown', handler);
        element._focusTrapHandler = handler;

        // 自动聚焦第一个可聚焦元素
        const focusable = element.querySelectorAll(focusableSelector);
        if (focusable.length > 0) focusable[0].focus();
    }

    /**
     * 释放焦点陷阱，返回之前焦点
     */
    releaseFocus() {
        if (this.focusTrapElement) {
            if (this.focusTrapElement._focusTrapHandler) {
                this.focusTrapElement.removeEventListener('keydown', this.focusTrapElement._focusTrapHandler);
                delete this.focusTrapElement._focusTrapHandler;
            }
            this.focusTrapElement = null;
        }

        if (this.focusTrapPrevious) {
            this.focusTrapPrevious.focus();
            this.focusTrapPrevious = null;
        }
    }

    // ============================
    // 减少动画监听
    // ============================

    _watchMotionPreference() {
        const mq = window.matchMedia('(prefers-reduced-motion: reduce)');

        const handleChange = (e) => {
            if (e.matches) {
                document.documentElement.classList.add('reduced-motion');
                this.announce('已关闭动画效果', 'polite');
            } else {
                document.documentElement.classList.remove('reduced-motion');
            }
        };

        // 初始状态
        if (mq.matches) {
            document.documentElement.classList.add('reduced-motion');
        }

        mq.addEventListener('change', handleChange);
    }

    // ============================
    // 颜色对比度检查 (开发辅助)
    // ============================

    /**
     * 计算相对亮度 (WCAG 2.1)
     * 仅用于开发调试
     */
    static getLuminance(hex) {
        const rgb = hex.replace('#', '').match(/.{2}/g).map(c => {
            const s = parseInt(c, 16) / 255;
            return s <= 0.03928 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4);
        });
        return 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2];
    }

    /**
     * 计算两个颜色的对比度 (WCAG 2.1)
     */
    static getContrastRatio(hex1, hex2) {
        const l1 = AccessibilityManager.getLuminance(hex1);
        const l2 = AccessibilityManager.getLuminance(hex2);
        const lighter = Math.max(l1, l2);
        const darker = Math.min(l1, l2);
        return (lighter + 0.05) / (darker + 0.05);
    }

    // ============================
    // 工具
    // ============================

    _sanitize(str) {
        const div = document.createElement('div');
        div.appendChild(document.createTextNode(str));
        return div.innerHTML;
    }

    /**
     * 通知图加载完成
     */
    notifyGraphLoaded() {
        const graphData = store.get('globalGraphData');
        if (graphData) {
            this.announce(
                `图数据加载完成。共 ${graphData.nodes.length} 个节点, ` +
                `${graphData.links.length} 条边。使用 Tab 键导航到控制面板。`,
                'polite'
            );
        }
    }

    /**
     * 通知算法执行结果
     */
    notifyAlgorithmComplete(algoName, result) {
        if (result && result.status === 'success') {
            this.announce(`${algoName} 分析完成`, 'polite');
        } else {
            this.announce(`${algoName} 分析失败`, 'assertive');
        }
    }

    /**
     * 通知路径查找结果
     */
    notifyPathFound(pathLength) {
        this.announce(`路径追踪完成。经过 ${pathLength} 跳`, 'polite');
    }
}
