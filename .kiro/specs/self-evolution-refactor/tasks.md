# 实现计划：Self-Evolution Refactor

## 概述

按分层顺序实现：先建立 IdentityManager 核心层，再改造现有模块委托给它，然后实现 DailyConsolidator，最后完成迁移脚本与 SelfEvolution 的整合接入。

## 任务

- [x] 1. 实现 `core/identity_manager.py`
  - 创建 `IdentityManager` 类，管理 `data/identity/USER.md`、`HABITS.md`、`MEMORY.md`
  - 实现 `update_user(key, value)` / `get_user()` 解析 `- **key**: value` 格式
  - 实现 `append_habit(content)` / `modify_habit(target, replacement)` / `get_habits()`
  - 实现 `write_memory(content)` 截断到 800 字并追加 `<!-- 内容已截断 -->`
  - 实现 `build_prompt()` 拼接 USER.md + HABITS.md 内容
  - 实现 `migrate_from_legacy(profile_path, habits_path, identities_default_path)` 一次性迁移
  - 所有写入操作附加 `<!-- updated: YYYY-MM-DD -->` 时间戳
  - 文件不存在时自动创建并写入默认头部
  - _需求: 2.1, 2.2, 2.3, 2.4, 2.5, 6.1, 6.2, 6.3, 6.5_

  - [-]* 1.1 为 `IdentityManager` 编写属性测试
    - **Property 3: 迁移数据完整性** — 随机 profile dict，验证 USER.md/HABITS.md 包含所有键值
    - **Property 4: 迁移备份保留** — 验证 .bak 文件内容与原文件相同
    - **Property 5: build_prompt 从 identity 读取** — 随机写入内容，验证 build_prompt() 包含这些内容
    - **Property 11: 记忆按 layer 路由** — 随机 objective/subjective 提取结果，验证写入正确文件
    - **Property 12: 时间戳格式正确** — 写入后验证正则 `<!-- updated: \d{4}-\d{2}-\d{2} -->`
    - **Validates: Requirements 2.2, 2.3, 2.4, 2.5, 6.1, 6.2, 6.4, 6.5**
    - 测试文件：`tests/test_identity_manager.py`

- [x] 2. 改造 `core/user_profile.py` 委托给 IdentityManager
  - 构造函数新增 `identity_manager: IdentityManager = None` 参数
  - `update_objective` / `update_subjective` / `get_all` / `build_prompt` 内部路由到 IdentityManager
  - `identity_manager` 为 `None` 时回退到原有 JSON 读写逻辑（向后兼容）
  - _需求: 2.5, 6.3_

- [x] 3. 改造 `core/persona_audit.py` 更新快照目录
  - `snapshot_dir` 改为 `data/identity/snapshots/`
  - 构造函数中检查 `data/persona_snapshots/` 是否存在，若存在且新目录不存在则自动迁移
  - `snapshot(reason, target_file="HABITS.md")` 头部注释改为 `<!-- Snapshot: {ts} | Target: {target_file} | Reason: {reason} -->`
  - `list()` / `diff()` / `rollback()` 使用新路径
  - _需求: 3.1, 3.2, 3.3, 3.4_

  - [ ]* 3.1 为 `PersonaAudit` 编写属性测试
    - **Property 6: 快照目录迁移 round-trip** — 构造含旧目录的临时目录，初始化后验证迁移完整
    - **Property 7: 快照头部包含目标文件名** — 验证生成文件第一行含 `Target: HABITS.md`
    - **Validates: Requirements 3.2, 3.3**
    - 测试文件：`tests/test_persona_audit.py`

- [x] 4. 改造 `core/diary_index.py` 和 `core/journal_index.py` 更新索引路径
  - `DiaryIndex.__init__`：`index_file` 改为 `data/diary/diary_vectors.jsonl`
  - `JournalIndex.__init__`：`index_file` 改为 `data/journals/journal_vectors.jsonl`
  - 两者在 `_load()` 前检查旧路径（`data/diary_vectors.jsonl` / `data/journal_vectors.jsonl`），若存在则自动迁移并打印日志
  - _需求: 1.1, 7.1, 7.2, 7.3_

  - [ ]* 4.1 为向量索引编写属性测试
    - **Property 1: 向量索引路径正确性** — 随机 `data_dir`，验证 `index_file` 属性值正确
    - **Property 2: 旧路径自动迁移 round-trip** — 构造临时目录放置旧文件，初始化后验证迁移结果
    - **Property 13: 搜索结果迁移前后一致** — 构造随机向量数据，迁移后对随机查询验证结果相同
    - **Validates: Requirements 1.1, 1.4, 1.5, 7.1, 7.2, 7.3, 7.4**
    - 测试文件：`tests/test_vector_indices.py`

- [x] 5. 改造 `core/memory.py` 更新 scene_memory.jsonl 路径
  - `scene_memory.jsonl` 路径改为 `data/memory/scene_memory.jsonl`
  - `knowledge_graph.jsonl` 路径改为 `data/memory/knowledge_graph.jsonl`
  - `store_index.json` 路径改为 `data/memory/store_index.json`
  - 初始化时检查旧路径，若存在则自动迁移
  - _需求: 1.2, 1.3, 1.4, 1.5_

- [x] 6. 检查点 — 确保所有测试通过
  - 确保所有测试通过，如有疑问请向用户确认。

- [x] 7. 实现 `core/daily_consolidator.py`
  - 创建 `DailyConsolidator` 类，接受 `client`、`model`、`identity`、`memory`、`journal`、`data_dir`、`promotion_threshold`、`similarity_threshold` 参数
  - 实现 `should_run()` 检查当日 `consolidation_YYYY-MM-DD.json` 是否存在
  - 实现 `_summarize_journal(date_str)` 读取当日日志，调用 LLM 生成 ≤800 字摘要
  - 实现 `_promote_memories()` 扫描 `scene_memory.jsonl`，晋升 `PERSONA_TRAIT` + confidence > threshold 的条目到 HABITS.md/USER.md，并从 JSONL 删除
  - 实现 `_deduplicate_memories()` 去除相似度 > 0.9 的重复条目，保留最新版本
  - 实现 `_save_report(date_str, stats)` 保存 `consolidation_YYYY-MM-DD.json`
  - 实现 `run(date_str)` 串联以上步骤，返回统计 dict
  - LLM 调用失败时写入空摘要并记录错误，不阻塞主流程
  - _需求: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7_

  - [ ]* 7.1 为 `DailyConsolidator` 编写属性测试
    - **Property 8: MEMORY.md 字数上限** — 随机长度日志，执行归纳，验证 MEMORY.md 正文 ≤ 800 字
    - **Property 9: 记忆晋升 round-trip** — 随机 PERSONA_TRAIT 条目，晋升后验证出现在目标文件且从 JSONL 删除
    - **Property 10: 去重后无高相似度条目对** — 随机相似条目，去重后验证无相似度 > 0.9 的条目对
    - **Validates: Requirements 5.2, 5.3, 5.4, 5.5, 5.6**
    - 测试文件：`tests/test_daily_consolidator.py`

- [x] 8. 改造 `core/self_evolution.py` 接入 IdentityManager 和 DailyConsolidator
  - `__init__` 新增 `identity: IdentityManager` 和 `daily_consolidator: DailyConsolidator = None` 参数
  - `self.habits_path` 改为指向 `data/identity/HABITS.md`
  - `self.audit` 的 `persona_path` 改为 `data/identity/HABITS.md`
  - `_extract_memories()` 中 `layer=objective` 调用 `identity.update_user()`，`layer=subjective` 调用 `identity.append_habit()`，写入时附加时间戳
  - `evolve_persona()` 从 `identity.get_habits()` 读取，append/modify 操作路由到 IdentityManager
  - `evolve_from_journal()` Step 1 前检查并执行 `DailyConsolidator`（若已注入）
  - 屏幕监控相关逻辑（`[视觉日志]` 去重）注释掉，不删除
  - `identity` 不存在时回退到原有逻辑（向后兼容）
  - _需求: 2.5, 5.1, 6.1, 6.2, 6.4, 6.5_

- [x] 9. 实现 `scripts/migrate_data.py` 迁移脚本
  - 创建 `MigrationRunner` 类，接受 `data_dir` 和 `dry_run` 参数
  - 实现 `_backup_file(path)` 在 `data/migration_backup/<timestamp>_<filename>` 创建备份
  - 实现 `_move_file(src, dst)` 移动文件，dry-run 时只打印不执行
  - 实现 `_migrate_user_profile()` 调用 `IdentityManager.migrate_from_legacy()`
  - 实现 `_migrate_vector_indices()` 移动 diary/journal 向量索引文件
  - 实现 `_migrate_memory_files()` 移动 scene_memory / knowledge_graph / store_index
  - 实现 `_migrate_snapshots()` 移动 `persona_snapshots/` → `identity/snapshots/`
  - 实现 `_save_manifest(manifest)` 保存 `migration_manifest.json`
  - 迁移过程中异常时回滚已移动文件，写入 `migration_error.log`
  - `run()` 执行前打印迁移计划并等待确认（dry-run 模式跳过确认直接打印）
  - `__main__` 入口支持 `--dry-run` 参数
  - _需求: 8.1, 8.2, 8.3, 8.4_

  - [ ]* 9.1 为 `MigrationRunner` 编写属性测试
    - **Property 14: 迁移前备份存在** — 执行迁移后验证 migration_backup/ 下备份文件存在且含时间戳
    - **Property 15: 迁移失败回滚** — 注入异常，验证文件状态回滚到迁移前
    - **Property 16: dry-run 不修改文件** — dry-run 后验证目录快照与执行前完全相同
    - **Validates: Requirements 8.1, 8.2, 8.4**
    - 测试文件：`tests/test_migration.py`

- [x] 10. 最终检查点 — 确保所有测试通过
  - 确保所有测试通过，如有疑问请向用户确认。

## 备注

- 标有 `*` 的子任务为可选项，可跳过以加快 MVP 进度
- 每个任务引用具体需求条款以保证可追溯性
- 属性测试使用 `hypothesis` 库，每个属性最少运行 100 次
- 每个属性测试注释格式：`# Feature: self-evolution-refactor, Property N: <property_text>`
- 屏幕监控代码注释掉但不删除，日记功能完整保留
- 所有迁移操作先备份再执行，支持回滚
