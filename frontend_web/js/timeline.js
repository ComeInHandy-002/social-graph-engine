// js/timeline.js — Big Bang 时间轴模块
//
// 控制宇宙膨胀时间轴: 播放/暂停、逐帧渲染、滑块拖动
//
// 导入: store (state.js), Engine3D (graphEngine.js)
// 导出: TimelineManager 类
//
// 连接: app.js 在引擎就绪后设置 engine 引用

import { store } from './state.js';

export class TimelineManager {
    constructor() {
        this.engine = null;      // Engine3D 引用, 由 app.js 设置
        this.playInterval = null;
        this.playSpeed = 80;     // ms per step
    }

    init(playBtnId = 'btn-play', sliderId = 'timeline-slider', panelId = 'timeline-panel') {
        this.playBtn = document.getElementById(playBtnId);
        this.slider = document.getElementById(sliderId);
        this.panel = document.getElementById(panelId);

        if (this.playBtn) {
            this.playBtn.addEventListener('click', () => this.togglePlayback());
        }

        if (this.slider) {
            this.slider.addEventListener('input', (e) => {
                if (store.get('isPlaying')) {
                    this.pause();
                }
                const step = parseInt(e.target.value);
                store.set('timelineStep', step);
                if (this.engine) {
                    this.engine.renderToTimeStep(step);
                }
            });
        }

        // 订阅 timelineVisible 变化
        store.on('timelineVisible', (visible) => {
            if (this.panel) {
                this.panel.style.display = visible ? 'block' : 'none';
            }
        });

        // 订阅 graphLoaded
        store.on('graphLoaded', (loaded) => {
            store.set('timelineVisible', loaded);
        });
    }

    /** 设置引擎引用 */
    setEngine(engine) {
        this.engine = engine;
    }

    /** 切换播放/暂停 */
    togglePlayback() {
        const isPlaying = store.get('isPlaying');
        if (isPlaying) {
            this.pause();
        } else {
            this.play();
        }
    }

    play() {
        const graphData = store.get('globalGraphData');
        if (!graphData) {
            console.warn('[Timeline] 无图数据, 无法播放');
            return;
        }

        const slider = this.slider;
        let currentStep = parseInt(slider.value);

        // 如果已到达终点, 回到起点
        if (currentStep >= 100) {
            currentStep = 1;
            slider.value = 1;
        }

        store.set('isPlaying', true);

        if (this.playBtn) {
            this.playBtn.innerHTML = '⏸️'; // ⏸️
            this.playBtn.setAttribute('aria-label', '暂停时间轴');
        }

        this.playInterval = setInterval(() => {
            let val = parseInt(slider.value);
            if (val >= 100) {
                this.pause();
                // 触发完成事件
                store.set('uiState', {
                    ...store.get('uiState'),
                    toasts: [
                        ...store.get('uiState').toasts,
                        { message: '宇宙演化完成!', type: 'success' }
                    ]
                });
                return;
            }
            val += 1;
            slider.value = val;
            store.set('timelineStep', val);
            if (this.engine) {
                this.engine.renderToTimeStep(val);
            }
        }, this.playSpeed);
    }

    pause() {
        clearInterval(this.playInterval);
        this.playInterval = null;
        store.set('isPlaying', false);

        if (this.playBtn) {
            this.playBtn.innerHTML = '▶️'; // ▶️
            this.playBtn.setAttribute('aria-label', '播放时间轴');
        }
    }

    /** 跳转到指定步骤 */
    goToStep(step) {
        const clamped = Math.max(1, Math.min(100, parseInt(step)));
        if (this.slider) this.slider.value = clamped;
        store.set('timelineStep', clamped);
        if (this.engine) {
            this.engine.renderToTimeStep(clamped);
        }
    }

    /** 重置到第一步 */
    reset() {
        if (store.get('isPlaying')) this.pause();
        this.goToStep(1);
    }

    destroy() {
        this.pause();
    }
}
