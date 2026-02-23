// N.E.K.O 架构精简版 App 初始化脚本
// 负责协调 UI、SSE 流式接收、以及 VRMManager 的生命周期

class App {
    constructor() {
        this.vrmManager = null;
        this.isInitialized = false;

        // UI 元素
        this.chatContainer = document.getElementById('chat-container');
        this.chatInput = document.getElementById('chat-input');
        this.sendTtn = document.getElementById('send-btn');
    }

    async init() {
        if (this.isInitialized) return;

        try {
            console.log("[App] 初始化 3D 引擎...");
            await this.initVRM();

            console.log("[App] 初始化事件监听...");
            this.initEvents();

            this.isInitialized = true;
            console.log("[App] 所有组件就绪。");
        } catch (error) {
            console.error("[App] 初始化失败:", error);
        }
    }

    async initVRM() {
        while (!window.VRMManager) {
            console.warn("[App] 等待 VRMManager 加载...");
            await new Promise(resolve => setTimeout(resolve, 100));
        }

        const canvas = document.getElementById('vrm-canvas');
        if (!canvas) throw new Error("找不到 Canvas 容器");

        try {
            this.vrmManager = new window.VRMManager();

            // 使用正确的 API: initThreeJS(canvasId, containerId)
            await this.vrmManager.initThreeJS('vrm-canvas', 'canvas-container');

            // 挂载可能存在的其它模块
            if (window.VRMInteraction) {
                this.vrmManager.interaction = new window.VRMInteraction(this.vrmManager);
            }
            if (window.VRMExpression) {
                this.vrmManager.expression = new window.VRMExpression(this.vrmManager);
            }

            // 优先从服务端读取已保存的模型路径，fallback 到 localStorage 或默认模型
            let modelToLoad = '/static/models/sister1.0.vrm';
            let hasServerPreferences = false;
            try {
                const prefsRes = await fetch('/api/config/preferences');
                if (prefsRes.ok) {
                    const prefs = await prefsRes.json();
                    if (prefs && prefs.model_path) {
                        modelToLoad = prefs.model_path;
                        hasServerPreferences = true;
                        console.log('[App] 从服务端偏好加载模型:', modelToLoad);
                    } else {
                        // 服务端没有记录，尝试 localStorage
                        const localSaved = localStorage.getItem('activeVrmModel');
                        if (localSaved) modelToLoad = localSaved;
                    }
                }
            } catch (e) {
                // 网络失败时退而求其次读 localStorage
                const localSaved = localStorage.getItem('activeVrmModel');
                if (localSaved) modelToLoad = localSaved;
                console.warn('[App] 读取服务端偏好失败，使用本地缓存:', e);
            }

            let loadSuccess;
            try {
                loadSuccess = await this.vrmManager.loadModel(modelToLoad, { autoPlay: true });
            } catch (e) {
                console.error("[App] VRM 模型加载失败:", e);
                // 向用户显示错误提示
                const errEl = document.getElementById('vrm-load-error');
                if (errEl) {
                    errEl.textContent = `VRM 模型加载失败: ${e.message}`;
                    errEl.style.display = 'block';
                }
            }

            if (loadSuccess) {
                console.log("[App] VRM 模型加载成功。");

                // If there were no server preferences loaded, apply the default optimized camera/model placement
                // Note: apply to the VRM model's scene node, not the Three.js Scene root
                if (!hasServerPreferences && this.vrmManager.currentModel?.vrm?.scene && this.vrmManager.camera) {
                    const scene = this.vrmManager.currentModel.vrm.scene;
                    const cam = this.vrmManager.camera;
                    // Apply user requested default positions
                    scene.position.set(0.017, -0.076, -0.002);
                    scene.scale.set(1.0, 1.0, 1.0);
                    scene.rotation.set(0, 0, 0);
                    cam.position.set(0.200, 1.070, -2.659);
                    // Match the reported quaternion/target to maintain precise framing
                    cam.quaternion.set(-0.0006, 0.9992, 0.0180, 0.0343);
                    if (this.vrmManager.controls) {
                        this.vrmManager.controls.target.set(0.002, 0.966, 0.216);
                        this.vrmManager.controls.update();
                    }
                    console.log("[App] 应用原生默认的优化观察视角");
                }

                if (this.vrmManager.interaction && this.vrmManager.interaction.setupInteraction) {
                    this.vrmManager.interaction.setupInteraction();
                }
            } else {
                console.error("[App] VRM 模型加载失败。");
            }
        } catch (e) {
            console.error("[App] VRM 初始化异常:", e);
        }
    }

    initEvents() {
        // Alpine.js 数据监听与 UI 交互代理通过 Alpine 完成
        // 这里绑定原生键盘事件（使用 keydown，keypress 已废弃）
        if (this.chatInput) {
            this.chatInput.addEventListener('keydown', (e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    const value = this.chatInput.value;
                    this.chatInput.value = '';  // 清空输入框，防止重复发送
                    document.dispatchEvent(new CustomEvent('app:send-message', { detail: value }));
                }
            });
        }
    }
}

// 暴露给全局以便 HTML 能够访问
window.appInstance = new App();

// 因为脚本是动态插入的，DOMContentLoaded 已经触发过了，直接立即初始化
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => window.appInstance.init());
} else {
    window.appInstance.init();
}
