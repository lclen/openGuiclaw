import re

# PATCH index.html
with open(r'd:\qwen_autogui\templates\index.html', 'r', encoding='utf-8') as f:
    html = f.read()

# 1. Update importmap
importmap_old = '"@pixiv/three-vrm": "/static/libs/three-vrm.module.min.js"'
importmap_new = '"@pixiv/three-vrm": "/static/libs/three-vrm.module.min.js",\n                "@pixiv/three-vrm-animation": "/static/libs/three-vrm-animation.module.js"'
if importmap_old in html and importmap_new not in html:
    html = html.replace(importmap_old, importmap_new)

# 2. Update the ES module block
es_block_old = '''    <!-- Step 1: Load Three.js via ES module and expose to window -->
    <script type="module">
        import * as THREE from 'three';
        import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
        import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
        window.THREE = THREE;
        window.GLTFLoader = GLTFLoader;
        window.OrbitControls = OrbitControls;
        console.log('[Three.js] core exposed to window.');
        window.dispatchEvent(new CustomEvent('three-ready'));
    </script>'''

es_block_new = '''    <!-- Step 1: Load Three.js & VRM via ES module and expose to window -->
    <script type="module">
        import * as THREE from 'three';
        import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
        import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
        import * as THREE_VRM from '@pixiv/three-vrm';
        import * as THREE_VRM_ANIM from '@pixiv/three-vrm-animation';
        window.THREE = THREE;
        window.GLTFLoader = GLTFLoader;
        window.OrbitControls = OrbitControls;
        window.THREE_VRM = THREE_VRM;
        window.THREE_VRM_ANIM = THREE_VRM_ANIM;
        console.log('[Three.js & VRM] core exposed to window.');
        window.dispatchEvent(new CustomEvent('three-ready'));
    </script>'''

if es_block_old in html:
    html = html.replace(es_block_old, es_block_new)

with open(r'd:\qwen_autogui\templates\index.html', 'w', encoding='utf-8') as f:
    f.write(html)
print("Patched index.html")

# PATCH vrm-animation.js
with open(r'd:\qwen_autogui\static\js\vrm-animation.js', 'r', encoding='utf-8') as f:
    anim = f.read()

anim_getmodule_old = '''    static async _getAnimationModule() {
        if (VRMAnimation._animationModuleCache) {
            return VRMAnimation._animationModuleCache;
        }
        let primaryError = null;
        try {
            // 使用 importmap 中的映射，确保与 @pixiv/three-vrm 使用相同的 three-vrm-core 版本
            VRMAnimation._animationModuleCache = await import('@pixiv/three-vrm-animation');
            return VRMAnimation._animationModuleCache;
        } catch (error) {
            primaryError = error;
            console.warn('[VRM Animation] 无法导入 @pixiv/three-vrm-animation，请检查 importmap 配置:', error);
            // 如果 importmap 失败，回退到硬编码路径（兼容性处理）；在尝试导入前检查回退文件是否存在
            try {
                const fallbackExists = await VRMAnimation._checkFallbackFileExists();
                if (!fallbackExists) {
                    console.warn('[VRM Animation] 回退文件不存在: /static/libs/three-vrm-animation.module.js，请确保文件已正确部署');
                }
                VRMAnimation._animationModuleCache = await import('/static/libs/three-vrm-animation.module.js');
                return VRMAnimation._animationModuleCache;
            } catch (fallbackError) {
                // fallback 也失败，抛出包含两次错误的详细错误信息
                const combinedError = new Error(
                    `[VRM Animation] 无法导入动画模块：\\n` +
                    `  主路径失败 (@pixiv/three-vrm-animation): ${primaryError?.message || primaryError}\\n` +
                    `  回退路径失败 (/static/libs/three-vrm-animation.module.js): ${fallbackError?.message || fallbackError}\\n` +
                    `请检查 importmap 配置或确保回退文件存在且路径正确。`
                );
                console.error(combinedError.message, { primaryError, fallbackError });
                VRMAnimation._animationModuleCache = null; // 清除缓存，允许重试
                throw combinedError;
            }
        }
    }'''

anim_getmodule_new = '''    static async _getAnimationModule() {
        if (VRMAnimation._animationModuleCache) {
            return VRMAnimation._animationModuleCache;
        }
        if (window.THREE_VRM_ANIM) {
            VRMAnimation._animationModuleCache = window.THREE_VRM_ANIM;
            return window.THREE_VRM_ANIM;
        }
        throw new Error('[VRM Animation] window.THREE_VRM_ANIM 未挂载，请检查 index.html 初始化逻辑。');
    }'''

if anim_getmodule_old in anim:
    anim = anim.replace(anim_getmodule_old, anim_getmodule_new)


anim_loader_old = '''    async _initLoader() {
        if (this._loaderPromise) return this._loaderPromise;

        this._loaderPromise = (async () => {
            try {
                const { GLTFLoader } = await import('three/addons/loaders/GLTFLoader.js');
                const animationModule = await VRMAnimation._getAnimationModule();
                const { VRMAnimationLoaderPlugin } = animationModule;
                const loader = new GLTFLoader();
                loader.register((parser) => new VRMAnimationLoaderPlugin(parser));
                return loader;
            } catch (error) {
                console.error('[VRM Animation] 加载器初始化失败:', error);
                this._loaderPromise = null;
                throw error;
            }
        })();
        return await this._loaderPromise;
    }'''

anim_loader_new = '''    async _initLoader() {
        if (this._loaderPromise) return this._loaderPromise;

        this._loaderPromise = (async () => {
            try {
                const GLTFLoader = window.GLTFLoader;
                if (!GLTFLoader) throw new Error('GLTFLoader未挂载到window。');
                const animationModule = await VRMAnimation._getAnimationModule();
                const { VRMAnimationLoaderPlugin } = animationModule;
                const loader = new GLTFLoader();
                loader.register((parser) => new VRMAnimationLoaderPlugin(parser));
                return loader;
            } catch (error) {
                console.error('[VRM Animation] 加载器初始化失败:', error);
                this._loaderPromise = null;
                throw error;
            }
        })();
        return await this._loaderPromise;
    }'''

if anim_loader_old in anim:
    anim = anim.replace(anim_loader_old, anim_loader_new)

with open(r'd:\qwen_autogui\static\js\vrm-animation.js', 'w', encoding='utf-8') as f:
    f.write(anim)

print("Patched vrm-animation.js")
