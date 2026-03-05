function mainApp() {
    return {
        // UI state
        activePanel: 'chat',
        sidebarOpen: false,

        // Agent status
        agentOnline: false,
        statusText: '连接中...',

        // Chat
        messages: [{ id: 'sys-0', role: 'assistant', content: '主人，我回来啦~！' }],
        inputText: '',
        isReceiving: false,
        currentController: null,

        // Image paste / drop
        pendingImage: null,      // base64 data URL for preview
        pendingImageFile: null,  // File object to upload
        isDragOver: false,

        // Slash commands
        showCommandMenu: false,
        commandSelectedIndex: 0,
        availableCommands: [
            // ── 会话管理 ──
            { command: '/clear', desc: '清空当前页面对话历史', action: 'clear_chat', icon: '✗' },
            { command: '/new', desc: '新建会话并保存当前历史', action: 'new_session', icon: '+' },
            // ── 模型管理 ──
            { command: '/upload', desc: '上传本地文件（图片/文本）发给 AI 分析', action: 'upload_file', icon: '↑' },
            { command: '/save', desc: '保存当前模型视角与位置配置', action: 'save_vrm', icon: '▣' },
            // ── AI 快捷任务 ──
            { command: '/recall ', desc: '搜索长期记忆，如: /recall 南京', action: 'send_recall', icon: '◐' },
            { command: '/plan', desc: '查看当前活跃任务计划状态', action: 'send_plan', icon: '▤' },
            { command: '/weather ', desc: '查询天气，如: /weather 上海', action: 'send_weather', icon: '◑' },
            { command: '/remind ', desc: '设置提醒，如: /remind 10分钟后喝水', action: 'send_remind', icon: '◔' },
            { command: '/screenshot', desc: '截取屏幕并让 AI 分析当前画面', action: 'send_screenshot', icon: '▨' },
            // ── 系统维护 ──
            { command: '/poke', desc: '强制触发一次视觉感知', action: 'poke_ai', icon: '→' },
            { command: '/sandbox clear', desc: '清理所有后台沙箱实例', action: 'clear_sandbox', icon: '⊘' },
        ],
        filteredCommands: [],

        // Debug log
        debugLogs: [],
        contextStatus: '',
        expandedContext: false,

        // Data
        sessions: [],
        currentSessionId: null,
        diaryDates: [],
        selectedDiaryContent: null,
        memoryItems: [],
        personas: {},
        config: {
            browser_choice: 'edge',
            proactive: { interval_minutes: 5, cooldown_minutes: 5, verbose: true, mode: 'normal' }
        },
        proactiveDefaults: {
            silent: { interval_minutes: null, cooldown_minutes: null },
            normal: { interval_minutes: 5, cooldown_minutes: 15 },
            lively: { interval_minutes: 5, cooldown_minutes: 1 }
        },

        // Scheduler
        schedulerTasks: [],
        showSchedulerForm: false,
        schedulerFormData: {
            id: null,
            name: '',
            description: '',
            task_type: 'task',
            prompt: '',
            reminder_message: '',
            trigger_type: 'once',
            enabled: true,
            trigger_config_onceTime: '',
            trigger_config_intervalMinutes: 0,
            trigger_config_intervalHours: 0,
            trigger_config_cron: '0 9 * * *',
            trigger_preset_time: '09:00',
            trigger_preset_weekday: '1',
            trigger_preset_day: '1'
        },

        // Model Config Data
        vrmModels: [],
        vrmAnimations: [],
        uploadingModel: false,
        uploadStatus: '',
        saveVrmStatus: '',

        // Store state
        storeLoading: false,
        storeItems: { models: [], animations: [] },
        downloadingItems: [],
        selectedCategory: 'All',
        categories: ['All', 'Vroid', 'Official', 'Basic'],

        // Skills state
        skills: [],
        skillSearchQuery: '',
        skillCategoryFilter: 'all',
        skillStatusFilter: 'all',
        skillMarketplace: [],
        skillMarketLoading: false,
        skillMarketSearch: '',
        skillInstallingId: null,
        skillInstallMsg: null,

        // Model endpoint config state
        configTab: 'models',
        modelConfig: {},           // loaded from /api/config/model
        modelDrafts: {},           // edit drafts per role
        modelShowKey: {},          // show/hide API key per role
        modelExpandedRole: 'api',  // which accordion card is open
        modelSaving: {},           // saving spinner
        modelTesting: {},          // testing spinner
        modelTestResult: {},       // test result per role
        modelProviders: [],        // from /api/config/model/providers
        modelRoles: [],            // from /api/config/model/providers
        modelDraftProvider: {},    // currently selected provider slug per role

        // Chat Endpoints list state
        chatEndpoints: [],         // list of {id,name,provider,base_url,api_key,model,...}
        activeEndpointId: null,    // ID of the currently active endpoint
        endpointSwitching: false,  // spinner when switching active endpoint
        epEditIdx: null,           // which endpoint card is expanded for editing
        epShowKey: {},             // show/hide api_key per endpoint index
        epSaving: false,           // endpoint list save spinner
        epTesting: {},             // testing per endpoint index
        epTestResult: {},          // test result per endpoint index

        // Role Endpoints (extra endpoints per functional role: vision/image_analyzer/embedding/autogui)
        roleEndpoints: {},         // {role_key: [{name,provider,base_url,api_key,model,...}]}
        roleEpTesting: {},         // {'vision-0': true/false}
        roleEpTestResult: {},      // {'vision-0': {status,model,error}}
        roleEpSaving: {},          // {role_key: true/false}

        // Token stats
        tokenStats: {
            total_prompt_tokens: 0,
            total_completion_tokens: 0,
            total_tokens: 0,
            request_count: 0,
            by_model: {},
            timeline: [],
        },
        tokenPeriod: '1d',

        async init() {
            await this.checkStatus();
            setInterval(() => this.checkStatus(), 15000);
            this.loadSessions();
            this.loadDiaryDates();
            this.subscribeEvents();
            this.loadModels();
            this.loadAnimations();
            this.loadCurrentSession();
            this.loadGlobalConfig();
            this.loadSchedulerTasks();
            this.loadModelConfig();
            this.loadChatEndpoints();
            this.loadRoleEndpoints();
            this.loadMemories();
            this.loadTokenStats(this.tokenPeriod);
        },

        // ── loadRoleEndpoints ──────────────────────────────────────────────
        // Merges the primary config.json role sections (vision/image_analyzer/embedding/autogui)
        // with any extra endpoints stored under role_extra_endpoints.
        async loadRoleEndpoints() {
            const ROLE_KEYS = ['vision', 'image_analyzer', 'embedding', 'autogui'];
            try {
                // 1) Fetch primary role configs from /api/config/model
                let primary = {};
                const mr = await fetch('/api/config/model');
                if (mr.ok) {
                    const md = await mr.json();
                    const cfg = md.config || {};
                    for (const key of ROLE_KEYS) {
                        if (cfg[key] && cfg[key].configured !== false) {
                            primary[key] = {
                                name: key === 'vision' ? '视觉模型（主）' :
                                    key === 'image_analyzer' ? '图像解析（主）' :
                                        key === 'embedding' ? '嵌入模型（主）' : 'GUI操作（主）',
                                provider: '',
                                base_url: cfg[key].base_url || '',
                                api_key: cfg[key].api_key || '',
                                model: cfg[key].model || '',
                                _primary: true,  // marks this as the top-level config.json entry
                            };
                        }
                    }
                }

                // 2) Fetch extra endpoints from /api/config/role-endpoints
                let extra = {};
                const er = await fetch('/api/config/role-endpoints');
                if (er.ok) {
                    const ed = await er.json();
                    extra = ed.role_extra_endpoints || {};
                }

                // 3) Merge: primary first, then extra endpoints
                const merged = {};
                for (const key of ROLE_KEYS) {
                    const arr = [];
                    if (primary[key]) arr.push(primary[key]);
                    if (extra[key] && Array.isArray(extra[key])) {
                        extra[key].forEach(ep => {
                            if (!ep._primary) arr.push(ep);
                        });
                    }

                    // Auto-match provider for role endpoints
                    if (this.modelProviders && this.modelProviders.length > 0) {
                        arr.forEach(ep => {
                            if (!ep.provider || ep.provider === 'custom') {
                                const matched = this.modelProviders.find(pv =>
                                    (pv.base_url && ep.base_url) &&
                                    (pv.base_url.replace(/\/$/, '') === ep.base_url.replace(/\/$/, ''))
                                );
                                if (matched) ep.provider = matched.slug;
                            }
                        });
                    }

                    merged[key] = arr;
                }
                this.roleEndpoints = merged;
            } catch (e) { console.error('Failed to load role endpoints:', e); }
        },

        async loadMemories() {
            try {
                const r = await fetch('/api/memory');
                if (r.ok) {
                    const data = await r.json();
                    this.memoryItems = (data.memories || []).map(m => ({
                        ...m,
                        _selected: false,
                        _editing: false,
                        _editBuffer: ''
                    }));
                }
            } catch (e) { console.error('Failed to load memories:', e); }
        },

        get selectedMemoryCount() {
            return this.memoryItems.filter(m => m._selected).length;
        },

        get allMemoriesSelected() {
            return this.memoryItems.length > 0 && this.selectedMemoryCount === this.memoryItems.length;
        },

        toggleMemorySelectAll() {
            const select = !this.allMemoriesSelected;
            this.memoryItems.forEach(m => m._selected = select);
        },

        async batchDeleteMemories() {
            const ids = this.memoryItems.filter(m => m._selected).map(m => m.id);
            if (ids.length === 0) return;
            if (!confirm(`确定要删除选中的 ${ids.length} 条记忆吗？`)) return;

            try {
                const r = await fetch('/api/memory/batch_delete', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ ids })
                });
                if (r.ok) {
                    this.pushLog('status', `已删除 ${ids.length} 条记忆`);
                    await this.loadMemories();
                } else {
                    this.pushLog('error', '批量删除记忆失败');
                }
            } catch (e) { console.error(e); }
        },

        async deleteMemory(id) {
            if (!id) return;
            if (!confirm('确定要删除这条记忆吗？')) return;
            this.pushLog('status', `正在删除记忆...`);
            try {
                const r = await fetch(`/api/memory/${id}`, { method: 'DELETE' });
                if (r.ok) {
                    this.pushLog('status', '记忆已成功删除');
                    await this.loadMemories();
                } else {
                    this.pushLog('error', '删除记忆失败 (API 错误)');
                }
            } catch (e) {
                console.error(e);
                this.pushLog('error', '网络异常');
            }
        },

        startEditMemory(item) {
            item._editBuffer = item.content;
            item._editing = true;
        },

        cancelEditMemory(item) {
            item._editing = false;
        },

        async saveMemoryEdit(item) {
            try {
                const r = await fetch(`/api/memory/${item.id}`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ content: item._editBuffer })
                });
                if (r.ok) {
                    this.pushLog('status', '记忆已更新');
                    item.content = item._editBuffer;
                    item._editing = false;
                    // re-fetch to ensure sync (optional)
                    // await this.loadMemories();
                } else {
                    this.pushLog('error', '更新记忆失败');
                }
            } catch (e) { console.error(e); }
        },


        // ── Chat Endpoints Methods ────────────────────────────────────────────

        async loadChatEndpoints() {
            try {
                const r = await fetch('/api/endpoints');
                if (r.ok) {
                    const data = await r.json();
                    let endpoints = data.endpoints || [];

                    // Auto-match provider by base_url if not explicitly set
                    if (this.modelProviders && this.modelProviders.length > 0) {
                        endpoints.forEach(ep => {
                            if (!ep.provider || ep.provider === 'custom') {
                                const matched = this.modelProviders.find(pv =>
                                    (pv.base_url && ep.base_url) &&
                                    (pv.base_url.replace(/\/$/, '') === ep.base_url.replace(/\/$/, ''))
                                );
                                if (matched) ep.provider = matched.slug;
                            }
                        });
                    }

                    this.chatEndpoints = endpoints;
                    this.activeEndpointId = data.active_id || null;
                }
            } catch (e) { console.error('Failed to load chat endpoints:', e); }
        },

        addChatEndpoint() {
            this.chatEndpoints.push({
                id: null, name: '', provider: 'custom',
                base_url: '', api_key: '', model: '',
                max_tokens: 8000, temperature: 0.7,
                _new: true,
            });
            // Directly set epExpandedIdx to open the new card
            this.epExpandedIdx = this.chatEndpoints.length - 1;
        },

        deleteChatEndpoint(idx) {
            this.chatEndpoints.splice(idx, 1);
            if (this.epEditIdx === idx) this.epEditIdx = null;
            else if (this.epEditIdx > idx) this.epEditIdx--;
        },

        applyEpPreset(epIdx, provider) {
            const ep = this.chatEndpoints[epIdx];
            if (!ep) return;
            ep.provider = provider.slug;
            ep.base_url = provider.base_url || '';
            if (!ep.name) ep.name = provider.name;
            if (provider.models && provider.models.length > 0 && !ep.model) {
                ep.model = provider.models[0];
            }
            // Trigger reactivity
            this.chatEndpoints = [...this.chatEndpoints];
        },

        async saveChatEndpoints() {
            this.epSaving = true;
            try {
                const r = await fetch('/api/endpoints', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(this.chatEndpoints),
                });
                const data = await r.json();
                if (r.ok && data.status === 'ok') {
                    await this.loadChatEndpoints(); // reload with assigned IDs
                    this.epEditIdx = null;
                    this.pushLog('status', `✓ 已保存 ${data.count} 个端点配置`);
                } else {
                    this.pushLog('error', `端点保存失败：${data.detail || JSON.stringify(data)}`);
                }
            } catch (e) {
                this.pushLog('error', `端点保存异常：${e.message}`);
            } finally {
                this.epSaving = false;
            }
        },

        async testChatEndpoint(epIdx) {
            const ep = this.chatEndpoints[epIdx];
            if (!ep?.model) return;
            this.epTesting[epIdx] = true;
            this.epTestResult[epIdx] = null;
            try {
                const r = await fetch('/api/config/model/test', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        role: 'api',
                        base_url: ep.base_url || '',
                        api_key: ep.api_key || '',
                        model: ep.model || '',
                    }),
                });
                const data = await r.json();
                this.epTestResult[epIdx] = data;
                if (data.status === 'ok') {
                    setTimeout(() => { this.epTestResult[epIdx] = null; }, 5000);
                }
            } catch (e) {
                this.epTestResult[epIdx] = { status: 'error', error: e.message };
            } finally {
                this.epTesting[epIdx] = false;
            }
        },

        async switchChatEndpoint(id) {
            if (id === this.activeEndpointId || this.endpointSwitching) return;
            this.endpointSwitching = true;
            try {
                const r = await fetch('/api/endpoints/active', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ id }),
                });
                const data = await r.json();
                if (r.ok && data.status === 'ok') {
                    this.activeEndpointId = data.active_id;
                    this.pushLog('status', `✓ 已切换模型 → ${data.name} (${data.model})`);
                } else {
                    this.pushLog('error', `切换失败：${data.detail || JSON.stringify(data)}`);
                }
            } catch (e) {
                this.pushLog('error', `切换异常：${e.message}`);
            } finally {
                this.endpointSwitching = false;
            }
        },
        // ── Role Endpoint Methods (vision / image_analyzer / embedding / autogui) ──────────

        addRoleEndpoint(roleKey) {
            if (!this.roleEndpoints[roleKey]) this.roleEndpoints[roleKey] = [];
            this.roleEndpoints[roleKey].push({
                name: '', provider: 'custom',
                base_url: '', api_key: '', model: '',
                _new: true,   // triggers auto-open in x-data
            });
            // Trigger Alpine reactivity
            this.roleEndpoints = { ...this.roleEndpoints };
        },

        deleteRoleEndpoint(roleKey, idx) {
            if (!this.roleEndpoints[roleKey]) return;
            this.roleEndpoints[roleKey].splice(idx, 1);
            this.roleEndpoints = { ...this.roleEndpoints };
        },

        applyRoleEpPreset(roleKey, idx, provider) {
            if (!this.roleEndpoints[roleKey]?.[idx]) return;
            const rep = this.roleEndpoints[roleKey][idx];
            rep.provider = provider.slug;
            rep.base_url = provider.base_url || '';
            if (!rep.name) rep.name = provider.name;
            if (provider.models?.length && !rep.model) rep.model = provider.models[0];
            this.roleEndpoints = { ...this.roleEndpoints };
        },

        async testRoleEndpoint(roleKey, idx) {
            const rep = this.roleEndpoints[roleKey]?.[idx];
            if (!rep?.model) return;
            const key = `${roleKey}-${idx}`;
            this.roleEpTesting[key] = true;
            this.roleEpTestResult[key] = null;
            try {
                const r = await fetch('/api/config/model/test', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        role: roleKey, base_url: rep.base_url || '',
                        api_key: rep.api_key || '', model: rep.model || '',
                    }),
                });
                const data = await r.json();
                this.roleEpTestResult[key] = data;
                if (data.status === 'ok') {
                    setTimeout(() => { this.roleEpTestResult[key] = null; }, 5000);
                }
            } catch (e) {
                this.roleEpTestResult[key] = { status: 'error', error: e.message };
            } finally {
                this.roleEpTesting[key] = false;
            }
        },

        async saveRoleEndpoints(roleKey) {
            // Splits endpoints into primary (top-level config.json key) and extra (role_extra_endpoints).
            this.roleEpSaving[roleKey] = true;
            try {
                const allEps = this.roleEndpoints[roleKey] || [];
                const primaryEp = allEps.find(ep => ep._primary);
                const extraEps = allEps.filter(ep => !ep._primary);

                // Save primary endpoint via /api/config/model (writes top-level role key)
                if (primaryEp) {
                    const pr = await fetch('/api/config/model', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            role: roleKey,
                            base_url: primaryEp.base_url || '',
                            api_key: primaryEp.api_key || '',
                            model: primaryEp.model || '',
                        }),
                    });
                    const pd = await pr.json();
                    if (!pr.ok || pd.status !== 'ok') {
                        this.pushLog('error', `主端点保存失败：${pd.detail || JSON.stringify(pd)}`);
                        return;
                    }
                }

                // Save extra endpoints via /api/config/role-endpoints
                const er = await fetch('/api/config/role-endpoints', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ role: roleKey, endpoints: extraEps }),
                });
                const ed = await er.json();
                if (er.ok && ed.status === 'ok') {
                    // Clean _new flags
                    allEps.forEach(ep => delete ep._new);
                    this.roleEndpoints = { ...this.roleEndpoints };
                    this.pushLog('status', `✓ ${roleKey} 角色端点已保存`);
                } else {
                    this.pushLog('error', `额外端点保存失败：${ed.detail || JSON.stringify(ed)}`);
                }
            } catch (e) {
                this.pushLog('error', `保存异常：${e.message}`);
            } finally {
                this.roleEpSaving[roleKey] = false;
            }
        },
        // ── End Role Endpoint Methods ─────────────────────────────────────────────

        // ── End Chat Endpoints Methods ────────────────────────────────────────

        // ── Model Config Methods ─────────────────────────────────────────
        async loadModelConfig() {

            try {
                // Load providers/roles
                const pr = await fetch('/api/config/model/providers');
                if (pr.ok) {
                    const pd = await pr.json();
                    this.modelProviders = pd.providers || [];
                    this.modelRoles = pd.roles || [];
                }
                // Load current config
                const r = await fetch('/api/config/model');
                if (r.ok) {
                    const data = await r.json();
                    this.modelConfig = data.config || {};
                    // Initialize drafts from current config
                    for (const [key, val] of Object.entries(this.modelConfig)) {
                        if (!this.modelDrafts[key]) {
                            this.modelDrafts[key] = {
                                base_url: val.base_url || '',
                                api_key: val.api_key || '',
                                model: val.model || '',
                                max_tokens: val.max_tokens || 8192,
                                temperature: val.temperature || 0.7,
                            };
                        }
                    }
                }
            } catch (e) { console.error('Failed to load model config:', e); }
        },

        toggleModelRole(key) {
            this.modelExpandedRole = this.modelExpandedRole === key ? null : key;
            // Clear old test result when switching
            this.modelTestResult[key] = null;
        },

        setModelDraft(role, field, value) {
            if (!this.modelDrafts[role]) this.modelDrafts[role] = {};
            this.modelDrafts[role][field] = value;
        },

        applyProviderPreset(provider, currentRole) {
            const role = currentRole || this.modelExpandedRole;
            if (!role) return;
            if (!this.modelDrafts[role]) this.modelDrafts[role] = {};
            this.modelDrafts[role].base_url = provider.base_url || '';
            if (provider.models && provider.models.length > 0) {
                this.modelDrafts[role].model = provider.models[0];
            }
            this.modelDraftProvider[role] = provider.slug;
            // Expand the card for this role
            if (role) this.modelExpandedRole = role;
        },

        async saveModelEndpoint(role) {
            const draft = this.modelDrafts[role];
            if (!draft?.model) return;
            this.modelSaving[role] = true;
            this.modelTestResult[role] = null;
            try {
                const r = await fetch('/api/config/model', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        role,
                        base_url: draft.base_url || '',
                        api_key: draft.api_key || '',
                        model: draft.model || '',
                        max_tokens: draft.max_tokens || null,
                        temperature: draft.temperature || null,
                    })
                });
                const data = await r.json();
                if (r.ok && data.status === 'ok') {
                    // Refresh config from server
                    await this.loadModelConfig();
                    this.pushLog('status', `✓ ${role} 端点已保存：${draft.model}`);
                } else {
                    this.pushLog('error', `保存失败：${data.detail || JSON.stringify(data)}`);
                }
            } catch (e) {
                this.pushLog('error', `保存异常：${e.message}`);
            } finally {
                this.modelSaving[role] = false;
            }
        },

        async testModelEndpoint(role) {
            const draft = this.modelDrafts[role];
            if (!draft?.model) return;
            this.modelTesting[role] = true;
            this.modelTestResult[role] = null;
            try {
                const r = await fetch('/api/config/model/test', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        role,
                        base_url: draft.base_url || '',
                        api_key: draft.api_key || '',
                        model: draft.model || '',
                    })
                });
                const data = await r.json();
                this.modelTestResult[role] = data;
                // Auto-clear success result after 5s
                if (data.status === 'ok') {
                    setTimeout(() => { this.modelTestResult[role] = null; }, 5000);
                }
            } catch (e) {
                this.modelTestResult[role] = { status: 'error', error: e.message };
            } finally {
                this.modelTesting[role] = false;
            }
        },
        // ── End Model Config Methods ─────────────────────────────────────

        async loadGlobalConfig() {
            try {
                const r = await fetch('/api/config');
                if (r.ok) {
                    const data = await r.json();
                    if (data.proactive) {
                        this.config.proactive = data.proactive;
                    }
                    this._fullConfig = data;
                }
            } catch (e) { console.error('Failed to load global config:', e); }
        },

        async setProactiveMode(m) {
            this.config.proactive.mode = m;
            const def = this.proactiveDefaults[m];
            if (def) {
                this.config.proactive.interval_minutes = def.interval_minutes;
                this.config.proactive.cooldown_minutes = def.cooldown_minutes;
            }
            await this.saveGlobalConfig();
        },

        async saveGlobalConfig() {
            try {
                if (!this._fullConfig) {
                    this.pushLog('error', '⚠ 配置尚未加载完成，无法保存');
                    return;
                }
                this._fullConfig.proactive = this.config.proactive;
                const r = await fetch('/api/config', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(this._fullConfig)
                });
                if (r.ok) {
                    this.pushLog('status', '⚙ 主动感知系统配置已实时更新');
                } else {
                    const err = await r.json().catch(() => ({}));
                    this.pushLog('error', `⚠ 保存配置失败: ${err.detail || r.status}`);
                }
            } catch (e) {
                this.pushLog('error', '⚠ 保存配置失败: ' + e.message);
            }
        },

        async pokeAI() {
            try {
                const r = await fetch('/api/context/poke', { method: 'POST' });
                if (r.ok) {
                    this.pushLog('status', '⚡ 已强制触发视觉感知，AI 正在赶来...');
                }
            } catch (e) {
                this.pushLog('error', '❌ 触发失败: ' + e.message);
            }
        },

        async loadCurrentSession() {
            try {
                const r = await fetch('/api/sessions/current/info');
                if (r.ok) {
                    const { session_id } = await r.json();
                    if (session_id) {
                        this.currentSessionId = session_id;
                        await this.loadSession(session_id, true);
                    }
                }
            } catch { /* silently ignore startup failures */ }

            try {
                const pref = await (await fetch('/api/config/preferences')).json();
                if (pref && pref.browser_choice) {
                    this.config.browser_choice = pref.browser_choice;
                }
            } catch { /* silently ignore */ }
        },

        subscribeEvents() {
            const es = new EventSource('/api/events');
            es.onmessage = (e) => {
                try {
                    const ev = JSON.parse(e.data);
                    if (ev.type === 'context') {
                        const icon = { working: '💻', idle: '😴', error: '🔴', entertainment: '🎮' }[ev.status] || '❓';
                        this.pushLog('context', `${icon} ${ev.status} — ${ev.summary}`);
                        this.contextStatus = `${icon} ${ev.summary}`;
                    } else if (ev.type === 'system') {
                        this.pushLog('system', ev.text || '');
                    } else if (ev.type === 'proactive' && ev.message) {
                        this.pushLog('system', `👀 视觉系统观察到屏幕新动态 (已禁用自动搭话)`);
                    } else if (ev.type === 'chat_event') {
                        // Real-time chat update from scheduler or other background tasks
                        this.loadCurrentSession().then(() => {
                            this.$nextTick(() => this.scrollToBottom());
                        });
                        // If not on chat panel, switch to it so user sees the message
                        if (this.activePanel !== 'chat') {
                            this.activePanel = 'chat';
                        }
                    }
                } catch { }
            };
            es.onerror = () => {
                this.agentOnline = false;
                this.statusText = '连接中断，重连中...';
            };
            es.onopen = () => {
                this.checkStatus();
            };
        },

        async checkStatus() {
            try {
                const r = await fetch('/api/status');
                const data = await r.json();
                this.agentOnline = data.status === 'online';
                const persona = data.active_persona || 'unknown';
                this.statusText = this.agentOnline ? `在线 · ${persona}` : '离线';
                if (data.last_context_summary && !this.contextStatus) {
                    const icon = { working: '💻', idle: '😴', error: '🔴', entertainment: '🎮' }[data.last_context_status] || '❓';
                    this.contextStatus = `${icon} ${data.last_context_summary}`;
                }
            } catch {
                this.agentOnline = false;
                this.statusText = '连接失败';
            }
        },

        async switchPanel(panel) {
            this.activePanel = panel;
            if (panel === 'history' && this.sessions.length === 0) this.loadSessions();
            if (panel === 'diary' && this.diaryDates.length === 0) this.loadDiaryDates();
            if (panel === 'persona' && Object.keys(this.personas).length === 0) this.loadPersona();
            if (panel === 'skills' && this.skills.length === 0) this.loadSkills();
            if (panel === 'config' && this.vrmModels.length === 0) this.loadModels();
            if (panel === 'tokens') this.loadTokenStats(this.tokenPeriod);
            if (panel === 'debug') {
                this.$nextTick(() => {
                    const d = document.getElementById('debug-container');
                    if (d) d.scrollTop = d.scrollHeight;
                });
            }
        },

        async loadSessions() {
            try {
                this.sessions = await (await fetch('/api/sessions')).json();
            } catch { this.sessions = []; }
        },

        async loadSession(sessionId, keepPanel = false) {
            try {
                const data = await (await fetch(`/api/sessions/${sessionId}`)).json();
                this.debugLogs = [];
                const validMessages = [];
                let lastAssistantMsg = null;

                data.messages.forEach((m, i) => {
                    if (m.role === 'debug_log') {
                        try {
                            const ev = JSON.parse(m.content);
                            let text = '';
                            if (ev.type === 'tool_call') {
                                text = `${ev.name}(${JSON.stringify(ev.params || {}).slice(0, 50)}...)`;
                            } else if (ev.type === 'tool_result') {
                                text = `${ev.name} → ${ev.result}`;
                            } else if (ev.type === 'message') {
                                text = (ev.content || '响应已完成').replace(/\s+/g, ' ').slice(0, 80);
                                if ((ev.content || '').length > 80) text += '...';
                            } else {
                                text = ev.content || '';
                            }
                            this.debugLogs.push({ type: ev.type, text: text, ts: ev.ts || m.timestamp.split(' ')[1] });
                        } catch { }
                        return;
                    }

                    if (m.role === 'user') {
                        lastAssistantMsg = null;
                        let raw = Array.isArray(m.content)
                            ? m.content.filter(c => c.type === 'text').map(c => c.text).join(' ')
                            : (m.content || '');
                        validMessages.push({ id: `h-${i}`, role: m.role, content: raw });
                    } else if (m.role === 'assistant') {
                        if (!lastAssistantMsg) {
                            lastAssistantMsg = {
                                id: `h-${i}`,
                                role: 'assistant',
                                content: '',
                                thinkingHtml: '',
                                _thinkingRaw: '',
                                blocks: [],
                                _thinkCollapsed: true
                            };
                            validMessages.push(lastAssistantMsg);
                        }
                        if (m.thinking) {
                            lastAssistantMsg._thinkingRaw += (lastAssistantMsg._thinkingRaw ? '\n\n' : '') + m.thinking;
                            lastAssistantMsg.thinkingHtml = this.mdRender(lastAssistantMsg._thinkingRaw);
                        }
                        if (m.content) {
                            lastAssistantMsg.blocks.push({ type: 'text', content: m.content, html: this.mdRender(m.content) });
                        }
                        if (m.tool_calls) {
                            (m.tool_calls || []).forEach(tc => {
                                lastAssistantMsg.blocks.push({
                                    type: 'tool',
                                    id: tc.id || tc.function?.name,
                                    name: tc.function?.name || 'unknown',
                                    paramsStr: tc.function?.arguments || '{}',
                                    status: 'done',
                                    _collapsed: true,
                                    resultStr: null
                                });
                            });
                        }
                    } else if (m.role === 'tool') {
                        if (lastAssistantMsg) {
                            const block = lastAssistantMsg.blocks.find(b => b.id === m.tool_call_id || b.name === m.name);
                            if (block) block.resultStr = m.content;
                        }
                    } else if (m.role === 'visual_log') {
                        lastAssistantMsg = null;
                        validMessages.push({ id: `h-${i}`, role: 'visual_log', content: m.content, html: this.mdRender(m.content) });
                    }
                });

                this.messages = validMessages;
                this.currentSessionId = sessionId;
                if (!keepPanel) this.activePanel = 'chat';
                this.$nextTick(() => this.scrollToBottom());
            } catch { alert('加载对话失败。'); }
        },

        async loadDiaryDates() {
            try {
                this.diaryDates = await (await fetch('/api/diary')).json();
            } catch { this.diaryDates = []; }
        },

        async loadDiary(date) {
            try {
                const data = await (await fetch(`/api/diary/${date}`)).json();
                this.selectedDiaryContent = data.content;
            } catch { alert('加载日记失败。'); }
        },

        async loadPersona() {
            try {
                this.personas = await (await fetch('/api/persona')).json();
            } catch { this.personas = {}; }
        },

        async loadModels() {
            try {
                const r = await fetch('/api/vrm/models');
                const data = await r.json();
                this.vrmModels = data.models || [];
                this.uploadStatus = '';
            } catch (e) {
                this.vrmModels = [];
                this.uploadStatus = '加载模型列表失败: ' + e.message;
            }
        },

        async loadAnimations() {
            try {
                const r = await fetch('/api/vrm/animations');
                const data = await r.json();
                this.vrmAnimations = data.animations || [];
            } catch (e) {
                this.vrmAnimations = [];
            }
        },

        async uploadModel(e) {
            const file = e.target.files[0];
            if (!file) return;
            if (!file.name.toLowerCase().endsWith('.vrm')) {
                this.uploadStatus = '❌ 请上传 .vrm 格式文件';
                return;
            }
            this.uploadingModel = true;
            this.uploadStatus = '上传中...';
            const formData = new FormData();
            formData.append('file', file);
            try {
                const r = await fetch('/api/vrm/upload', { method: 'POST', body: formData });
                const data = await r.json();
                if (r.ok) {
                    this.uploadStatus = '✓ 上传成功';
                    this.loadModels();
                    this.switchVrmModel(data.path);
                } else {
                    this.uploadStatus = `❌ 上传失败: ${data.detail || '未知原因'}`;
                }
            } catch (err) {
                this.uploadStatus = `❌ 上传出错: ${err.message}`;
            } finally {
                this.uploadingModel = false;
                e.target.value = '';
                setTimeout(() => this.uploadStatus = '', 3000);
            }
        },

        switchVrmModel(modelPath) {
            const vm = window.appInstance?.vrmManager;
            if (!vm) return;
            let snapshot = null;
            try {
                const cam = vm.camera;
                const scene = vm.currentModel?.scene;
                if (cam && scene) {
                    snapshot = {
                        posX: scene.position.x, posY: scene.position.y, posZ: scene.position.z,
                        scaleX: scene.scale.x, scaleY: scene.scale.y, scaleZ: scene.scale.z,
                        camX: cam.position.x, camY: cam.position.y, camZ: cam.position.z,
                        qx: cam.quaternion.x, qy: cam.quaternion.y,
                        qz: cam.quaternion.z, qw: cam.quaternion.w,
                        tgtX: vm._cameraTarget?.x ?? 0,
                        tgtY: vm._cameraTarget?.y ?? 1,
                        tgtZ: vm._cameraTarget?.z ?? 0,
                    };
                }
            } catch (_) { }

            this.pushLog('status', `正在热切换模型: ${modelPath}`);
            const savedActionUrl = vm.animation?._lastVrmaUrl;

            vm.loadModel(modelPath, { autoPlay: false }).then(() => {
                const applySnapshot = () => {
                    if (snapshot) {
                        try {
                            const newScene = vm.currentModel?.scene;
                            const cam = vm.camera;
                            if (newScene) {
                                newScene.position.set(snapshot.posX, snapshot.posY, snapshot.posZ);
                                newScene.scale.set(snapshot.scaleX, snapshot.scaleY, snapshot.scaleZ);
                                newScene.rotation.set(0, 0, 0);
                            }
                            if (cam) {
                                cam.position.set(snapshot.camX, snapshot.camY, snapshot.camZ);
                                cam.quaternion.set(snapshot.qx, snapshot.qy, snapshot.qz, snapshot.qw);
                            }
                            if (window.THREE) {
                                vm._cameraTarget = new THREE.Vector3(snapshot.tgtX, snapshot.tgtY, snapshot.tgtZ);
                            }
                        } catch (_) { }
                    }
                    const lastUrl = savedActionUrl || '/static/vrm/animation/wait03.vrma';
                    if (vm.animation) {
                        vm.animation.playVRMAAnimation(lastUrl, { loop: true, immediate: true }).catch(() => { });
                    }
                    this.pushLog('status', `模型切换成功! 已继承当前视角并恢复动作`);
                };
                requestAnimationFrame(() => requestAnimationFrame(applySnapshot));
            }).catch(e => {
                this.pushLog('error', `模型切换失败: ${e.message}`);
            });
        },

        triggerExpression(mood) {
            if (window.appInstance?.vrmManager?.expression) {
                window.appInstance.vrmManager.expression.setMood(mood);
                this.pushLog('status', `触发表情: ${mood}`);
            }
        },

        triggerAction(url) {
            if (window.appInstance?.vrmManager) {
                window.appInstance.vrmManager.playVRMAAnimation(url, { loop: true });
                this.pushLog('status', `播放动作: ${url.split('/').pop()}`);
            }
        },

        async deleteModel(filename) {
            if (!confirm(`确定要删除模型 ${filename} 吗？`)) return;
            try {
                const r = await fetch(`/api/vrm/models/${encodeURIComponent(filename)}`, { method: 'DELETE' });
                const data = await r.json();
                if (r.ok) {
                    this.pushLog('status', `模型已删除: ${filename}`);
                    await this.loadModels();
                } else {
                    this.pushLog('error', `删除失败: ${data.detail || '未知原因'}`);
                }
            } catch (err) {
                this.pushLog('error', `删除出错: ${err.message}`);
            }
        },

        async saveVrmConfig() {
            const vm = window.appInstance?.vrmManager;
            if (!vm) {
                this.saveVrmStatus = 'error';
                setTimeout(() => this.saveVrmStatus = '', 3000);
                return;
            }
            this.saveVrmStatus = 'saving';
            try {
                const model = vm.currentModel;
                if (!model || !model.url || !model.scene) throw new Error('模型尚未加载');
                const scene = model.scene;
                const cam = vm.camera;
                const position = { x: scene.position.x, y: scene.position.y, z: scene.position.z };
                const scale = { x: scene.scale.x, y: scene.scale.y, z: scene.scale.z };
                const rotation = { x: scene.rotation.x, y: scene.rotation.y, z: scene.rotation.z };
                let cameraPosition = null;
                if (cam) {
                    const tgt = vm._cameraTarget || { x: 0, y: 0, z: 0 };
                    cameraPosition = {
                        x: cam.position.x, y: cam.position.y, z: cam.position.z,
                        qx: cam.quaternion.x, qy: cam.quaternion.y,
                        qz: cam.quaternion.z, qw: cam.quaternion.w,
                        targetX: tgt.x, targetY: tgt.y, targetZ: tgt.z
                    };
                }
                const payload = {
                    model_path: model.url, position, scale, rotation,
                    viewport: { width: window.screen.width, height: window.screen.height },
                    camera_position: cameraPosition
                };
                const r = await fetch('/api/config/preferences', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                if (!r.ok) throw new Error(`HTTP ${r.status}`);
                this.saveVrmStatus = 'ok';
                this.pushLog('status', '视角配置已保存，刷新后将自动恢复');
                this.pushLog('status', `模型位置: x=${position.x.toFixed(3)}, y=${position.y.toFixed(3)}, z=${position.z.toFixed(3)}`);
                this.pushLog('status', `模型缩放: x=${scale.x.toFixed(3)}, y=${scale.y.toFixed(3)}, z=${scale.z.toFixed(3)}`);
                if (cameraPosition) {
                    this.pushLog('status', `镜头位置: x=${cameraPosition.x.toFixed(3)}, y=${cameraPosition.y.toFixed(3)}, z=${cameraPosition.z.toFixed(3)}`);
                }
            } catch (e) {
                this.saveVrmStatus = 'error';
                this.pushLog('error', `保存视角失败: ${e.message}`);
            }
            setTimeout(() => this.saveVrmStatus = '', 3000);
        },

        async updateBrowserSetting(choice) {
            this.config.browser_choice = choice;
            try {
                const r = await fetch('/api/config/preferences', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ browser_choice: choice })
                });
                if (!r.ok) throw new Error(`HTTP ${r.status}`);
                this.pushLog('status', `默认浏览器已切换为: ${choice === 'edge' ? 'Microsoft Edge' : 'Google Chrome'}`);
            } catch (e) {
                this.pushLog('error', `保存浏览器设置失败: ${e.message}`);
            }
        },

        async loadStoreItems() {
            this.storeLoading = true;
            try {
                const r = await fetch('/api/store/list');
                this.storeItems = await r.json();
            } catch (e) {
                this.pushLog('error', `获取商店列表失败: ${e.message}`);
            } finally {
                this.storeLoading = false;
            }
        },

        async downloadStoreItem(item, type) {
            if (this.downloadingItems.includes(item.id)) return;
            this.downloadingItems.push(item.id);
            this.pushLog('status', `开始下载资源: ${item.name}`);
            try {
                const r = await fetch('/api/store/download', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ url: item.url, type: type, name: item.name })
                });
                const data = await r.json();
                if (!r.ok) throw new Error(data.detail || '下载请求失败');
                this.pushLog('status', `${item.name} 正在后台下载，等待完成...`);
                const expectedExt = type === 'model' ? '.vrm' : '.vrma';
                const expectedName = item.name + expectedExt;
                const deadline = Date.now() + 120_000;
                const poll = async () => {
                    if (type === 'model') await this.loadModels();
                    else await this.loadAnimations();
                    const found = type === 'model'
                        ? this.vrmModels.some(m => m.name === expectedName)
                        : this.vrmAnimations.some(a => a.name === item.name || a.name === expectedName);
                    if (found || Date.now() > deadline) {
                        this.downloadingItems = this.downloadingItems.filter(id => id !== item.id);
                        this.pushLog('status', found ? `资源 ${item.name} 下载完成` : `⚠ ${item.name} 下载超时，请手动刷新`);
                    } else {
                        setTimeout(poll, 3000);
                    }
                };
                setTimeout(poll, 3000);
            } catch (err) {
                this.pushLog('error', `下载 ${item.name} 失败: ${err.message}`);
                this.downloadingItems = this.downloadingItems.filter(id => id !== item.id);
            }
        },

        get filteredModels() {
            if (this.selectedCategory === 'All') return this.storeItems.models || [];
            return (this.storeItems.models || []).filter(item => item.category === this.selectedCategory);
        },

        isDownloaded(item) {
            if (!this.vrmModels) return false;
            const expectedName = item.name.endsWith('.vrm') ? item.name : item.name + '.vrm';
            return this.vrmModels.some(m => m.name === expectedName);
        },

        isAnimationDownloaded(item) {
            if (!this.vrmAnimations) return false;
            const expectedName = item.name.endsWith('.vrma') ? item.name : item.name + '.vrma';
            return this.vrmAnimations.some(a => a.name === item.name || a.name === expectedName);
        },

        get filteredAnimations() {
            if (this.selectedCategory === 'All') return this.storeItems.animations || [];
            return (this.storeItems.animations || []).filter(item => item.category === this.selectedCategory);
        },

        async newSession() {
            try {
                const r = await fetch('/api/sessions/new', { method: 'POST' });
                if (!r.ok) throw new Error('server error');
                this.messages = [{ id: 'sys-new', role: 'assistant', content: '开始新对话啊！有什么想聊的吗~' }];
                this.activePanel = 'chat';
                await this.loadSessions();
            } catch (e) { console.error('新建对话失败:', e); }
        },

        abortReceiving() {
            if (this.currentController) {
                this.currentController.abort();
                this.currentController = null;
                this.isReceiving = false;
            }
        },

        handleInput(e) {
            const text = this.inputText;
            if (text.startsWith('/')) {
                const search = text.toLowerCase();
                this.filteredCommands = this.availableCommands.filter(c => c.command.toLowerCase().startsWith(search));
                this.showCommandMenu = this.filteredCommands.length > 0;
                this.commandSelectedIndex = 0;
            } else {
                this.showCommandMenu = false;
            }
        },

        navigateCommand(dir, e) {
            if (this.showCommandMenu && this.filteredCommands.length > 0) {
                this.commandSelectedIndex += dir;
                if (this.commandSelectedIndex < 0) this.commandSelectedIndex = this.filteredCommands.length - 1;
                if (this.commandSelectedIndex >= this.filteredCommands.length) this.commandSelectedIndex = 0;
            }
        },

        handleEnter(e) {
            if (this.showCommandMenu && this.filteredCommands.length > 0) {
                this.selectCommand(this.filteredCommands[this.commandSelectedIndex]);
            } else if (e.shiftKey) {
                this.inputText += '\n';
                this.autoResize(e.target);
            } else {
                if (this.isReceiving) {
                    this.abortReceiving();
                } else {
                    this.sendMessage();
                }
            }
        },

        // ── Image paste / drop helpers ────────────────────────────────────────

        handlePaste(e) {
            const items = e.clipboardData && e.clipboardData.items;
            if (!items) return;
            for (const item of items) {
                if (item.type.startsWith('image/')) {
                    e.preventDefault();
                    const file = item.getAsFile();
                    if (file) this._setPendingImage(file);
                    return;
                }
            }
            // Non-image paste: let the browser handle it normally (text into textarea)
        },

        handleDrop(e) {
            this.isDragOver = false;
            const file = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
            if (!file) return;
            if (file.type.startsWith('image/')) {
                this._setPendingImage(file);
            } else {
                // Non-image file: delegate to sendFile directly
                this.sendFile(file, this.inputText.trim());
                this.inputText = '';
            }
        },

        _setPendingImage(file) {
            this.pendingImageFile = file;
            const reader = new FileReader();
            reader.onload = (ev) => { this.pendingImage = ev.target.result; };
            reader.readAsDataURL(file);
            this.$nextTick(() => {
                const ta = document.querySelector('textarea');
                if (ta) ta.focus();
            });
        },

        // ── Arg / dispatch helpers ─────────────────────────────────────────────

        // Extract the argument portion after a command prefix from the current inputText.
        // e.g. inputText="/recall 南京", cmdPrefix="/recall " → "南京"
        _extractArg(cmdPrefix, rawInput) {
            const src = rawInput || '';
            const prefix = cmdPrefix.trimEnd();
            if (src.toLowerCase().startsWith(prefix.toLowerCase())) {
                return src.slice(prefix.length).trim();
            }
            return src.trim();
        },

        // Set inputText and dispatch to AI on next tick.
        _dispatchToAI(message) {
            this.inputText = message;
            this.$nextTick(() => this.sendMessage());
        },

        // Restore inputText with a placeholder hint and focus the textarea.
        _focusInput(hint) {
            this.inputText = hint;
            this.$nextTick(() => {
                const ta = document.querySelector('textarea');
                if (ta) { ta.select(); ta.focus(); }
            });
        },

        selectCommand(cmd) {
            const rawInput = this.inputText; // capture before clearing
            this.inputText = '';
            this.showCommandMenu = false;
            this.$nextTick(() => {
                const ta = document.querySelector('textarea');
                if (ta) { ta.style.height = 'auto'; ta.focus(); }
            });
            const actions = {
                // ── 会话管理 ──
                clear_chat: () => {
                    this.messages = [{ id: 'sys-0', role: 'assistant', content: '对话已在前端清空。' }];
                    this.pushLog('system', '前端对话历史已清空。');
                },
                new_session: () => this.newSession(),

                // ── 模型管理 ──
                upload_file: () => {
                    // Trigger a hidden file input; result handled by _onUploadFileSelected
                    let input = document.getElementById('_slash-upload-input');
                    if (!input) {
                        input = document.createElement('input');
                        input.type = 'file';
                        input.id = '_slash-upload-input';
                        input.accept = 'image/*,text/plain,text/markdown,.txt,.md,.csv,.log';
                        input.style.display = 'none';
                        document.body.appendChild(input);
                        input.addEventListener('change', (e) => this._onUploadFileSelected(e));
                    }
                    input.value = '';
                    input.click();
                },
                save_vrm: () => this.saveVrmConfig(),

                // ── AI 快捷任务 ──
                send_recall: () => {
                    const keyword = this._extractArg(cmd.command, rawInput);
                    if (!keyword) { this._focusInput('请输入搜索关键词，如: /recall 南京'); return; }
                    this._dispatchToAI(`请帮我搜索长期记忆，关键词：${keyword}`);
                },
                send_plan: () => {
                    this._dispatchToAI('请调用 get_plan_status 工具，告诉我当前活跃任务计划的状态。');
                },
                send_weather: () => {
                    const city = this._extractArg(cmd.command, rawInput);
                    if (!city) { this._focusInput('请输入城市名，如: /weather 上海'); return; }
                    this._dispatchToAI(`请查询${city}的当前天气。`);
                },
                send_remind: () => {
                    const content = this._extractArg(cmd.command, rawInput);
                    if (!content) { this._focusInput('请输入提醒内容，如: /remind 10分钟后喝水'); return; }
                    this._dispatchToAI(`请帮我设置一个提醒：${content}`);
                },
                send_screenshot: () => {
                    this._dispatchToAI('请调用 get_screenshot 工具截取当前屏幕，然后告诉我你看到了什么。');
                },

                // ── 系统维护 ──
                poke_ai: () => {
                    fetch('/api/context/poke', { method: 'POST' })
                        .then(r => r.json())
                        .then(() => this.pushLog('status', '⚡ 已强制触发视觉感知。'))
                        .catch(e => this.pushLog('error', '触发失败: ' + e.message));
                },
                clear_sandbox: () => {
                    fetch('/api/sandbox/clear', { method: 'POST' })
                        .then(r => r.json())
                        .then(data => {
                            this.messages.push({ id: 'sys-' + Date.now(), role: 'assistant', content: '✓ ' + data.message });
                            this.scrollToBottom();
                        })
                        .catch(() => { });
                },
            };
            const handler = actions[cmd.action];
            if (handler) handler();
        },

        async _onUploadFileSelected(e) {
            const file = e.target.files[0];
            if (!file) return;
            const prompt = '';  // no extra prompt by default
            await this.sendFile(file, prompt);
        },

        async sendFile(file, prompt = '') {
            if (this.isReceiving) return;
            const label = prompt ? `${file.name}：${prompt}` : file.name;
            this.messages.push({ id: 'u-' + Date.now(), role: 'user', content: `[上传文件] ${label}` });
            this.scrollToBottom();

            const aiId = 'a-' + Date.now();
            this.messages.push({ id: aiId, role: 'assistant', content: '<span class="text-gray-400 text-xs italic animate-pulse">分析中...</span>', thinkingHtml: '', _thinkingRaw: '', _thinkCollapsed: true, blocks: [] });
            this.scrollToBottom();
            this.isReceiving = true;

            try {
                const formData = new FormData();
                formData.append('file', file);
                if (prompt) formData.append('prompt', prompt);

                this.currentController = new AbortController();
                const response = await fetch('/api/chat/upload', {
                    method: 'POST',
                    body: formData,
                    signal: this.currentController.signal,
                });
                // Reuse the same SSE reader logic as sendMessage
                const reader = response.body.getReader();
                const decoder = new TextDecoder('utf-8');
                let buffer = '';
                while (true) {
                    const { done, value } = await reader.read();
                    if (done) break;
                    buffer += decoder.decode(value, { stream: true });
                    const lines = buffer.split('\n');
                    buffer = lines.pop();
                    for (const line of lines) {
                        if (!line.startsWith('data: ')) continue;
                        const dataStr = line.slice(6).trim();
                        if (dataStr === '[DONE]') continue;
                        try {
                            const ev = JSON.parse(dataStr);
                            const idx = this.messages.findIndex(m => m.id === aiId);
                            if (ev.type === 'status') {
                                this.pushLog('status', ev.content || '');
                            } else if (ev.type === 'message_chunk') {
                                if (idx !== -1) {
                                    const m = this.messages[idx];
                                    if (!m._streaming) { m._streaming = true; m.content = ''; m.blocks = []; }
                                    const lastBlock = m.blocks && m.blocks[m.blocks.length - 1];
                                    if (lastBlock && lastBlock.type === 'text') {
                                        lastBlock.content += ev.content;
                                        lastBlock.html = this.mdRender(lastBlock.content);
                                    } else {
                                        if (!m.blocks) m.blocks = [];
                                        m.blocks.push({ type: 'text', content: ev.content, html: this.mdRender(ev.content) });
                                    }
                                    this.scrollToBottom();
                                }
                            } else if (ev.type === 'message') {
                                // finalize
                            } else if (ev.type === 'error') {
                                this.pushLog('error', ev.content || '');
                                if (idx !== -1) this.messages[idx].content = `<span class="text-red-400 text-xs">⚠ ${ev.content}</span>`;
                            }
                        } catch { /* ignore parse errors */ }
                    }
                }
            } catch (err) {
                if (err.name !== 'AbortError') {
                    const idx = this.messages.findIndex(m => m.id === aiId);
                    if (idx !== -1) this.messages[idx].content = '<span class="text-red-400 text-xs">⚠ 上传失败，请稍后再试。</span>';
                }
            } finally {
                this.isReceiving = false;
                this.currentController = null;
                this.scrollToBottom();
            }
        },

        async sendMessage(isProactive = false) {
            // If an image is staged, send it via the upload endpoint instead
            if (this.pendingImageFile && !isProactive) {
                const file = this.pendingImageFile;
                const prompt = this.inputText.trim();
                this.pendingImage = null;
                this.pendingImageFile = null;
                this.inputText = '';
                await this.sendFile(file, prompt);
                return;
            }

            const text = this.inputText.trim();
            if (!text || this.isReceiving) return;
            if (!isProactive) {
                this.messages.push({ id: 'u-' + Date.now(), role: 'user', content: text });
            }
            this.inputText = '';
            this.$nextTick(() => {
                const ta = document.querySelector('textarea');
                if (ta) { ta.style.height = 'auto'; }
            });
            this.scrollToBottom();
            const aiId = 'a-' + Date.now();
            this.messages.push({ id: aiId, role: 'assistant', content: '<span class="text-gray-400 text-xs italic animate-pulse">思考中...</span>', thinkingHtml: '', _thinkingRaw: '', _thinkCollapsed: true, blocks: [] });
            this.scrollToBottom();
            this.isReceiving = true;
            try {
                this.currentController = new AbortController();
                const response = await fetch('/api/chat/stream', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ message: text }),
                    signal: this.currentController.signal
                });
                const reader = response.body.getReader();
                const decoder = new TextDecoder('utf-8');
                let buffer = '';
                while (true) {
                    const { done, value } = await reader.read();
                    if (done) break;
                    buffer += decoder.decode(value, { stream: true });
                    const lines = buffer.split('\n');
                    buffer = lines.pop();
                    for (const line of lines) {
                        if (!line.startsWith('data: ')) continue;
                        const dataStr = line.slice(6).trim();
                        if (dataStr === '[DONE]') continue;
                        try {
                            const ev = JSON.parse(dataStr);
                            const idx = this.messages.findIndex(m => m.id === aiId);
                            if (ev.type === 'status') {
                                this.pushLog('status', ev.content || '');
                                if (idx !== -1) {
                                    const cur = this.messages[idx].content;
                                    if (cur.includes('animate-pulse') || cur.includes('thinking')) {
                                        this.messages[idx].content = `<span class="text-gray-500 text-xs italic">${ev.content}</span>`;
                                    }
                                }
                            } else if (ev.type === 'tool_call') {
                                const paramStr = ev.params ? JSON.stringify(ev.params, null, 2) : '';
                                this.pushLog('tool_call', `${ev.name}(${paramStr})`);
                                if (idx !== -1) {
                                    const m = this.messages[idx];
                                    if (!m._streaming) { m._streaming = true; m._rawContent = ''; m.content = ''; }
                                    if (!m.blocks) m.blocks = [];
                                    m.blocks.push({ type: 'tool', id: ev.id, name: ev.name, paramsStr: paramStr, status: 'running', _collapsed: false });
                                    this.scrollToBottom();
                                }
                            } else if (ev.type === 'tool_result') {
                                this.pushLog('tool_result', `${ev.name} → ${ev.result || ''}`);
                                if (idx !== -1) {
                                    const m = this.messages[idx];
                                    if (m.blocks) {
                                        const tc = m.blocks.find(t => t.type === 'tool' && t.id === ev.id);
                                        if (tc) { tc.status = 'done'; tc.resultStr = ev.result || ''; tc._collapsed = true; }
                                    }
                                    this.scrollToBottom();
                                }
                            } else if (ev.type === 'thinking_chunk') {
                                if (idx !== -1) {
                                    const m = this.messages[idx];
                                    if (!m._streaming) { m._streaming = true; m._rawContent = ''; m.content = ''; }
                                    m._thinkingRaw = (m._thinkingRaw || '') + (ev.content || '');
                                    m.thinkingHtml = this.mdRender(m._thinkingRaw);
                                    m._thinkCollapsed = false;
                                    this.scrollToBottom();
                                }
                            } else if (ev.type === 'message_chunk') {
                                if (idx !== -1) {
                                    const m = this.messages[idx];
                                    if (!m._streaming) { m._streaming = true; m._rawContent = ''; m.content = ''; }
                                    // Collapse thinking block only after a short delay so users can see it
                                    if (m._thinkCollapsed === false && !m._thinkCollapseScheduled) {
                                        m._thinkCollapseScheduled = true;
                                        setTimeout(() => {
                                            m._thinkCollapsed = true;
                                            m._thinkCollapseScheduled = false;
                                        }, 1200);
                                    }
                                    if (ev.content) {
                                        if (!m.blocks) m.blocks = [];
                                        const lastBlock = m.blocks[m.blocks.length - 1];
                                        if (lastBlock && lastBlock.type === 'text') {
                                            lastBlock.content += ev.content;
                                            lastBlock.html = this.mdRender(lastBlock.content);
                                        } else {
                                            m.blocks.push({ type: 'text', content: ev.content, html: this.mdRender(ev.content) });
                                        }
                                    }
                                    this.scrollToBottom();
                                }
                            } else if (ev.type === 'message') {
                                let logContent = (ev.content || '').trim();
                                if (!logContent && idx !== -1) {
                                    const m = this.messages[idx];
                                    if (m.blocks) {
                                        logContent = m.blocks.filter(b => b.type === 'text').map(b => b.content).join('').trim();
                                    }
                                }
                                if (!logContent) logContent = '响应已完成';
                                this.pushLog('message', logContent.replace(/\s+/g, ' ').slice(0, 80) + (logContent.length > 80 ? '...' : ''));

                                if (idx !== -1) {
                                    const m = this.messages[idx];
                                    delete m._streaming;
                                    delete m._rawContent;
                                    this.scrollToBottom();
                                }
                            } else if (ev.type === 'system') {
                                this.pushLog('system', ev.text || '');
                            } else if (ev.type === 'error') {
                                this.pushLog('error', ev.content || '');
                                if (idx !== -1) {
                                    this.messages[idx].content = `<span class="text-red-400 text-xs">❌ ${ev.content}</span>`;
                                }
                            }
                        } catch { /* ignore parse errors */ }
                    }
                }
            } catch (err) {
                if (err.name !== 'AbortError') {
                    const idx = this.messages.findIndex(m => m.id === aiId);
                    if (idx !== -1) this.messages[idx].content = '<span class="text-red-400 text-xs">❌ 网络异常，请稍后再试。</span>';
                }
            } finally {
                this.isReceiving = false;
                this.currentController = null;
                this.scrollToBottom();
                this.loadTokenStats(this.tokenPeriod);
            }
        },

        autoResize(el) {
            el.style.height = 'auto';
            el.style.height = Math.min(el.scrollHeight, 120) + 'px';
        },

        pushLog(type, text) {
            const ts = new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
            this.debugLogs.push({ type, text, ts });
            if (this.debugLogs.length > 500) this.debugLogs.shift();
            if (this.activePanel === 'debug') {
                this.$nextTick(() => {
                    const d = document.getElementById('debug-container');
                    if (d) d.scrollTop = d.scrollHeight;
                });
            }
        },

        mdRender(text) {
            if (!text || typeof text !== 'string') return text || '';
            if (text.startsWith('<span')) return text;
            try {
                return typeof marked !== 'undefined'
                    ? marked.parse(text, { breaks: true, gfm: true })
                    : text;
            } catch { return text; }
        },

        scrollToBottom() {
            this.$nextTick(() => {
                const c = document.getElementById('chat-container');
                if (c) c.scrollTop = c.scrollHeight;
            });
        },

        // ═══════════════ Scheduler Management ═══════════════
        async loadSchedulerTasks() {
            try {
                const res = await fetch('/api/scheduler/tasks');
                if (res.ok) {
                    const data = await res.json();
                    this.schedulerTasks = data.tasks || [];
                }
            } catch (e) {
                console.error('Failed to load scheduler tasks', e);
            }
        },

        openSchedulerForm() {
            this.schedulerFormData = {
                id: null,
                name: '',
                description: '',
                task_type: 'task',
                prompt: '',
                reminder_message: '',
                trigger_type: 'once',
                enabled: true,
                trigger_config_onceTime: '',
                trigger_config_intervalMinutes: 0,
                trigger_config_intervalHours: 0,
                trigger_config_cron: '0 9 * * *',
                trigger_preset_time: '09:00',
                trigger_preset_weekday: '1',
                trigger_preset_day: '1'
            };

            // Generate current time + 5 mins for onceTime default
            const now = new Date();
            now.setMinutes(now.getMinutes() + 5);
            // Format to YYYY-MM-DDThh:mm string
            const tzoffset = now.getTimezoneOffset() * 60000;
            const localISOTime = (new Date(now - tzoffset)).toISOString().slice(0, 16);
            this.schedulerFormData.trigger_config_onceTime = localISOTime;

            this.showSchedulerForm = true;
        },

        closeSchedulerForm() {
            this.showSchedulerForm = false;
        },

        editSchedulerTask(task) {
            // copy task data to form
            this.schedulerFormData = {
                id: task.id,
                name: task.name,
                description: task.description || '',
                task_type: task.task_type || 'task',
                prompt: task.prompt || '',
                reminder_message: task.reminder_message || '',
                trigger_type: task.trigger_type,
                enabled: task.enabled,
                trigger_config_onceTime: '',
                trigger_config_intervalMinutes: 0,
                trigger_config_intervalHours: 0,
                trigger_config_cron: '',
                trigger_preset_time: '09:00',
                trigger_preset_weekday: '1',
                trigger_preset_day: '1'
            };

            if (task.trigger_type === 'once') {
                if (task.trigger_config && (task.trigger_config.run_at || task.trigger_config.run_date)) {
                    try {
                        const d = new Date(task.trigger_config.run_at || task.trigger_config.run_date);
                        // Convert UTC string to local ISOTime string
                        const tzoffset = d.getTimezoneOffset() * 60000;
                        this.schedulerFormData.trigger_config_onceTime = (new Date(d.getTime() - tzoffset)).toISOString().slice(0, 16);
                    } catch (e) { }
                }
            } else if (task.trigger_type === 'interval') {
                if (task.trigger_config) {
                    const seconds = task.trigger_config.interval_seconds || task.trigger_config.seconds || 0;
                    this.schedulerFormData.trigger_config_intervalHours = Math.floor(seconds / 3600);
                    this.schedulerFormData.trigger_config_intervalMinutes = Math.floor((seconds % 3600) / 60);
                }
            } else if (task.trigger_type === 'cron') {
                const cronExp = task.trigger_config ? (task.trigger_config.cron || task.trigger_config.expression) : '';
                this.schedulerFormData.trigger_config_cron = cronExp;

                // Try to detect presets from Cron
                const parts = cronExp.split(/\s+/);
                if (parts.length === 5) {
                    const [m, h, d, mon, dow] = parts;
                    const timeStr = `${h.padStart(2, '0')}:${m.padStart(2, '0')}`;

                    if (d === '*' && mon === '*' && dow === '*') {
                        this.schedulerFormData.trigger_type = 'daily';
                        this.schedulerFormData.trigger_preset_time = timeStr;
                    } else if (d === '*' && mon === '*' && dow !== '*') {
                        this.schedulerFormData.trigger_type = 'weekly';
                        this.schedulerFormData.trigger_preset_time = timeStr;
                        this.schedulerFormData.trigger_preset_weekday = dow;
                    } else if (d !== '*' && mon === '*' && dow === '*') {
                        this.schedulerFormData.trigger_type = 'monthly';
                        this.schedulerFormData.trigger_preset_time = timeStr;
                        this.schedulerFormData.trigger_preset_day = d;
                    }
                }
            }

            this.showSchedulerForm = true;
        },

        async saveSchedulerTask() {
            const formData = this.schedulerFormData;

            // Validation
            if (!formData.name.trim()) {
                this.pushLog('error', '任务名称不能为空');
                return;
            }

            if (formData.task_type === 'task' && !formData.prompt.trim()) {
                this.pushLog('error', '给助手的 Prompt 指令不能为空');
                return;
            }
            if (formData.task_type === 'reminder' && !formData.reminder_message.trim()) {
                this.pushLog('error', '提醒文本内容不能为空');
                return;
            }

            let triggerConfig = {};
            let finalTriggerType = formData.trigger_type;

            if (formData.trigger_type === 'once') {
                if (!formData.trigger_config_onceTime) {
                    this.pushLog('error', '执行时间不能为空');
                    return;
                }
                const d = new Date(formData.trigger_config_onceTime);
                triggerConfig = { run_at: d.toISOString() };
            } else if (formData.trigger_type === 'interval') {
                const totalSeconds = (formData.trigger_config_intervalHours * 3600) + (formData.trigger_config_intervalMinutes * 60);
                if (totalSeconds <= 0) {
                    this.pushLog('error', '时间间隔必须大于 0');
                    return;
                }
                triggerConfig = { interval_seconds: totalSeconds };
            } else if (['daily', 'weekly', 'monthly', 'cron'].includes(formData.trigger_type)) {
                finalTriggerType = 'cron';
                let cronStr = '';

                if (formData.trigger_type === 'cron') {
                    if (!formData.trigger_config_cron.trim()) {
                        this.pushLog('error', 'Cron 规则不能为空');
                        return;
                    }
                    cronStr = formData.trigger_config_cron.trim();
                } else {
                    // Presets
                    const [h, m] = formData.trigger_preset_time.split(':').map(x => parseInt(x).toString());
                    if (formData.trigger_type === 'daily') {
                        cronStr = `${m} ${h} * * *`;
                    } else if (formData.trigger_type === 'weekly') {
                        cronStr = `${m} ${h} * * ${formData.trigger_preset_weekday}`;
                    } else if (formData.trigger_type === 'monthly') {
                        cronStr = `${m} ${h} ${formData.trigger_preset_day} * *`;
                    }
                }
                triggerConfig = { cron: cronStr };
            }

            const payload = {
                name: formData.name,
                description: formData.description,
                trigger_type: finalTriggerType,
                trigger_config: triggerConfig,
                task_type: formData.task_type,
                prompt: formData.task_type === 'task' ? formData.prompt : '',
                reminder_message: formData.task_type === 'reminder' ? formData.reminder_message : '',
                enabled: formData.enabled
            };

            try {
                let url = '/api/scheduler/tasks';
                let method = 'POST';
                if (formData.id) {
                    url += `/${formData.id}`;
                    method = 'PUT';
                }

                const res = await fetch(url, {
                    method: method,
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });

                if (res.ok) {
                    this.pushLog('system', formData.id ? '成功更新计划任务' : '成功创建计划任务');
                    this.closeSchedulerForm();
                    await this.loadSchedulerTasks();
                } else {
                    const err = await res.json();
                    this.pushLog('error', `保存计划任务失败: ${err.detail}`);
                }
            } catch (e) {
                console.error(e);
                this.pushLog('error', '网络错误，请查看控制台');
            }
        },

        async deleteSchedulerTask(taskId) {
            if (!confirm("确定要删除此计划任务吗？")) return;
            try {
                const res = await fetch(`/api/scheduler/tasks/${taskId}`, { method: 'DELETE' });
                if (res.ok) {
                    this.pushLog('system', '计划任务已删除');
                    await this.loadSchedulerTasks();
                } else {
                    const err = await res.json();
                    this.pushLog('error', `删除失败: ${err.detail}`);
                }
            } catch (e) { console.error(e); }
        },

        async toggleSchedulerTask(taskId, enabled) {
            try {
                const res = await fetch(`/api/scheduler/tasks/${taskId}/toggle`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ enabled: enabled })
                });
                if (res.ok) {
                    this.pushLog('system', enabled ? '已启用任务' : '已停用任务');
                    await this.loadSchedulerTasks();
                } else {
                    this.pushLog('error', '切换状态失败');
                }
            } catch (e) { console.error(e); }
        },

        async triggerSchedulerTask(taskId) {
            try {
                const res = await fetch(`/api/scheduler/tasks/${taskId}/trigger`, { method: 'POST' });
                if (res.ok) {
                    this.pushLog('system', '任务执行指令已发送');
                    await this.loadSchedulerTasks();
                } else {
                    this.pushLog('error', '触发任务失败');
                }
            } catch (e) { console.error(e); }
        },

        // ═══════════════ Skills Management ═══════════════
        async loadSkills() {
            try {
                console.log('[Skills] Loading skills...');
                const response = await fetch('/api/skills/list');
                console.log('[Skills] Response status:', response.status);
                if (response.ok) {
                    const data = await response.json();
                    console.log('[Skills] Loaded skills:', data.skills);
                    this.skills = (data.skills || []).map(skill => {
                        return {
                            ...skill,
                            _showConfig: false,
                            _saving: false,
                            config_values: skill.config_values || {}
                        };
                    });
                    console.log('[Skills] Skills array length:', this.skills.length);
                } else {
                    console.error('[Skills] Failed to load skills:', response.statusText);
                }
            } catch (error) {
                console.error('[Skills] Error loading skills:', error);
            }
        },

        async toggleSkill(name, enabled) {
            try {
                const response = await fetch('/api/skills/toggle', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ name, enabled })
                });

                if (response.ok) {
                    const skill = this.skills.find(s => s.name === name);
                    if (skill) {
                        skill.enabled = enabled;
                    }
                    this.pushLog('success', `技能 ${name} 已${enabled ? '启用' : '禁用'}`);
                } else {
                    this.pushLog('error', `切换技能状态失败`);
                    await this.loadSkills();
                }
            } catch (error) {
                console.error('Failed to toggle skill:', error);
                this.pushLog('error', `切换技能状态失败: ${error.message}`);
            }
        },

        async saveSkillConfig(skill) {
            skill._saving = true;
            try {
                const response = await fetch('/api/skills/config', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ name: skill.name, config: skill.config_values })
                });
                const data = await response.json();
                if (response.ok) {
                    this.pushLog('success', `技能配置 ${skill.name} 保存成功`);
                    skill.config_values = data.config_values || skill.config_values;
                } else {
                    this.pushLog('error', `技能配置保存失败: ${data.detail || '未知错误'}`);
                }
            } catch (error) {
                console.error('Failed to save skill config:', error);
                this.pushLog('error', `配置保存异常: ${error.message}`);
            } finally {
                skill._saving = false;
            }
        },

        async reloadSkills() {
            try {
                this.pushLog('status', '正在重新加载技能...');
                const response = await fetch('/api/skills/reload', {
                    method: 'POST'
                });

                if (response.ok) {
                    await this.loadSkills();
                    this.pushLog('success', '技能已重新加载');
                } else {
                    this.pushLog('error', '重新加载技能失败');
                }
            } catch (error) {
                console.error('Failed to reload skills:', error);
                this.pushLog('error', `重新加载技能失败: ${error.message}`);
            }
        },

        // ═══════════════ Token Stats ═══════════════
        async loadTokenStats(period) {
            try {
                const p = period || '1d';
                const res = await fetch(`/api/token-stats?period=${p}`);
                if (res.ok) this.tokenStats = await res.json();
            } catch (e) { console.error('Failed to load token stats:', e); }
        },

        async resetTokenStats() {
            if (!confirm('确定要重置 Token 统计数据吗？')) return;
            try {
                await fetch('/api/token-stats/reset', { method: 'POST' });
                await this.loadTokenStats(this.tokenPeriod);
            } catch (e) { console.error('Failed to reset token stats:', e); }
        },

        async searchSkillMarketplace(q) {
            this.skillMarketLoading = true;
            this.skillInstallMsg = null;
            try {
                const res = await fetch('/api/skills/marketplace?q=' + encodeURIComponent(q || 'agent'));
                const data = await res.json();
                this.skillMarketplace = data.skills || [];
            } catch (e) {
                this.skillInstallMsg = { type: 'error', text: '加载失败: ' + e.message };
            } finally {
                this.skillMarketLoading = false;
            }
        },

        async installSkillFromUrl(url) {
            if (!url.trim()) return;
            this.skillInstallMsg = null;
            try {
                const res = await fetch('/api/skills/install', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ url })
                });
                const data = await res.json();
                if (!res.ok || data.error) throw new Error(data.error || data.detail || '安装失败');
                this.skillInstallMsg = { type: 'success', text: '✓ 技能安装成功，已重新加载' };
                await this.reloadSkills();
            } catch (e) {
                this.skillInstallMsg = { type: 'error', text: e.message };
            }
        },

        async uninstallSkill(name) {
            if (!confirm('确认卸载技能「' + name + '」？这将从注册表中移除该技能。')) return;
            this.skillInstallMsg = null;
            try {
                const res = await fetch('/api/skills/uninstall', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ name })
                });
                const data = await res.json();
                if (!res.ok || data.error) throw new Error(data.error || data.detail || '卸载失败');
                this.skillInstallMsg = { type: 'success', text: '已卸载技能「' + name + '」' };
                await this.reloadSkills();
            } catch (e) {
                this.skillInstallMsg = { type: 'error', text: e.message };
            }
        },

        formatNum(n) {
            if (n == null) return '—';
            if (n >= 1000000) return (n / 1000000).toFixed(1) + 'M';
            if (n >= 1000) return (n / 1000).toFixed(1) + 'K';
            return String(n);
        },

        get filteredSkills() {
            let filtered = this.skills;

            if (this.skillSearchQuery.trim()) {
                const query = this.skillSearchQuery.toLowerCase();
                filtered = filtered.filter(skill =>
                    skill.name.toLowerCase().includes(query) ||
                    skill.description.toLowerCase().includes(query)
                );
            }

            if (this.skillCategoryFilter !== 'all') {
                filtered = filtered.filter(skill =>
                    skill.category === this.skillCategoryFilter
                );
            }

            if (this.skillStatusFilter === 'enabled') {
                filtered = filtered.filter(skill => skill.enabled);
            } else if (this.skillStatusFilter === 'disabled') {
                filtered = filtered.filter(skill => !skill.enabled);
            }

            return filtered;
        },

        get groupedSkills() {
            const groups = {};
            for (const skill of this.filteredSkills) {
                const cat = skill.category || 'general';
                if (!groups[cat]) groups[cat] = [];
                groups[cat].push(skill);
            }
            return Object.entries(groups).sort((a, b) => a[0].localeCompare(b[0]));
        }
    };
}
