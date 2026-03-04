# 需求文档

## 简介

本功能旨在重构 openGuiclaw 项目的底层自我进化数据存储结构，解决当前 `data/` 目录下文件散乱、职责重叠、目录命名与实际用途不符等问题。参考 openakita 的 `identity/` 目录设计，引入清晰的分层存储架构，使日记、日志、用户画像、交互习惯等数据各归其位，并优化每日归纳（DailyConsolidator）流程，提升自我进化引擎的可维护性与数据质量。

## 词汇表

- **Self_Evolution_Engine**：`core/self_evolution.py` 中的自我进化引擎，负责从日志提取记忆、写日记、更新知识图谱等。
- **DailyConsolidator**：每日归纳器，在每天凌晨或跨天首次启动时执行，负责整合当日数据并刷新 identity 层文件。
- **Identity_Layer**：新引入的 `data/identity/` 目录，存放结构化的身份与记忆文件，对应 openakita 的 `identity/` 设计。
- **USER_md**：`data/identity/USER.md`，存储用户客观档案（姓名、职业、设备等），替代原 `user_profile.json` 的 objective 层。
- **HABITS_md**：`data/identity/HABITS.md`，存储 AI 与用户的交互习惯与约束规则，替代原 `data/interaction_habits.md` 和 `user_profile.json` 的 subjective 层。
- **MEMORY_md**：`data/identity/MEMORY.md`，存储 AI 的进度记忆摘要，有字数上限，每日由 DailyConsolidator 刷新。
- **Persona_Snapshot_Dir**：快照目录，用于保存 HABITS_md 的历史版本，目录名应与实际用途一致。
- **Vector_Index**：向量索引文件（`.jsonl`），用于语义搜索，应存放在对应数据子目录中而非 `data/` 根目录。
- **Memory_Promotion**：记忆晋升机制，将高置信度的 `PERSONA_TRAIT` 类记忆从 JSONL 记忆库提升到 HABITS_md 或 USER_md。

---

## 需求

### 需求 1：重组 data/ 目录结构

**用户故事：** 作为开发者，我希望 `data/` 目录下的文件按功能分类存放，以便快速定位数据文件、减少维护成本。

#### 验收标准

1. THE Self_Evolution_Engine SHALL 将所有向量索引文件（`diary_vectors.jsonl`、`journal_vectors.jsonl`）存放在对应的子目录（`data/diary/` 和 `data/journals/`）中，而非 `data/` 根目录。
2. THE Self_Evolution_Engine SHALL 将 `knowledge_graph.jsonl` 和 `scene_memory.jsonl` 统一存放在 `data/memory/` 子目录中。
3. THE Self_Evolution_Engine SHALL 将 `store_index.json` 存放在 `data/memory/` 子目录中。
4. WHEN 系统启动时读取旧路径的文件，IF 旧路径文件存在而新路径文件不存在，THEN THE Self_Evolution_Engine SHALL 自动将旧路径文件迁移到新路径，并打印迁移日志。
5. THE Self_Evolution_Engine SHALL 在迁移完成后删除旧路径的文件，确保不留残留。

---

### 需求 2：引入 Identity Layer（data/identity/ 目录）

**用户故事：** 作为开发者，我希望参考 openakita 的设计，在 `data/` 下建立清晰的 `identity/` 目录，将用户档案、交互习惯、进度记忆分文件存储，职责明确。

#### 验收标准

1. THE Self_Evolution_Engine SHALL 在 `data/identity/` 目录下维护以下三个文件：`USER.md`（用户客观档案）、`HABITS.md`（交互习惯与约束规则）、`MEMORY.md`（进度记忆摘要，有字数上限）。
2. THE Self_Evolution_Engine SHALL 将原 `user_profile.json` 中 `objective_memory` 层的内容迁移到 `data/identity/USER.md`，并以 Markdown 格式存储。
3. THE Self_Evolution_Engine SHALL 将原 `user_profile.json` 中 `subjective_memory` 层的内容与原 `data/interaction_habits.md` 的内容合并迁移到 `data/identity/HABITS.md`。
4. WHEN 迁移完成后，THE Self_Evolution_Engine SHALL 保留原 `user_profile.json` 和 `interaction_habits.md` 作为备份，文件名加 `.bak` 后缀，不直接删除。
5. THE Self_Evolution_Engine SHALL 在系统提示词（system prompt）构建时，优先从 `data/identity/USER.md` 和 `data/identity/HABITS.md` 读取内容注入，而非从旧的 JSON 文件读取。

---

### 需求 3：重命名快照目录以匹配实际用途

**用户故事：** 作为开发者，我希望快照目录的名称能准确反映其存储内容，避免混淆。

#### 验收标准

1. THE Self_Evolution_Engine SHALL 将快照目录从 `data/persona_snapshots/` 重命名为 `data/identity/snapshots/`，以反映其实际存储的是 HABITS_md 的历史快照。
2. WHEN `data/persona_snapshots/` 目录存在且 `data/identity/snapshots/` 不存在，THE Self_Evolution_Engine SHALL 自动将旧目录内容迁移到新目录。
3. THE PersonaAudit SHALL 在快照文件头部注释中记录快照的目标文件名（如 `HABITS.md`），而非固定写 `PERSONA.md`。
4. THE PersonaAudit SHALL 在 `list()`、`diff()`、`rollback()` 方法中使用新的快照目录路径。

---

### 需求 4：清理 identities/ 目录

**用户故事：** 作为开发者，我希望 `data/identities/` 目录有明确的用途定义，或在不需要时被合并到 identity layer 中，避免空置目录造成混淆。

#### 验收标准

1. THE Self_Evolution_Engine SHALL 将 `data/identities/default.md` 的内容合并到 `data/identity/USER.md` 中（如有非重复内容）。
2. WHEN `data/identities/` 目录中只有 `default.md` 且内容已迁移，THE Self_Evolution_Engine SHALL 将该目录标记为废弃，并在启动日志中提示开发者可手动删除。
3. WHERE 未来需要多角色人设支持，THE Self_Evolution_Engine SHALL 使用 `data/identity/personas/` 子目录存放多角色文件，而非 `data/identities/`。

---

### 需求 5：实现 DailyConsolidator（每日归纳器）

**用户故事：** 作为 AI 系统，我希望每天凌晨自动归纳当日数据，刷新 MEMORY.md，并将高置信度的用户特征晋升到 identity 层，保持记忆库的精简与准确。

#### 验收标准

1. THE DailyConsolidator SHALL 在每天凌晨（或跨天首次启动时）自动执行归纳流程。
2. WHEN 归纳执行时，THE DailyConsolidator SHALL 读取当日日志，生成不超过 800 字的进度摘要，并写入 `data/identity/MEMORY.md`，覆盖旧内容。
3. WHEN `data/identity/MEMORY.md` 中的内容超过 800 字，THE DailyConsolidator SHALL 截断超出部分，保留最重要的内容，并在文件末尾追加截断说明。
4. THE DailyConsolidator SHALL 扫描近期记忆库（`scene_memory.jsonl`），将标签包含 `PERSONA_TRAIT` 且置信度高于阈值的记忆条目晋升到 `data/identity/HABITS.md` 或 `data/identity/USER.md`。
5. THE DailyConsolidator SHALL 在晋升记忆后，从 `scene_memory.jsonl` 中删除已晋升的条目，避免重复。
6. THE DailyConsolidator SHALL 扫描记忆库中重复或高度相似（相似度 > 0.9）的条目，保留最新版本，删除旧版本，并记录清理数量到日志。
7. THE DailyConsolidator SHALL 将每次归纳的摘要（执行时间、晋升数量、清理数量）保存为 `data/memory/consolidation_YYYY-MM-DD.json`。

---

### 需求 6：解决 user_profile.json 与 interaction_habits.md 的职责重叠

**用户故事：** 作为开发者，我希望用户画像和交互习惯有清晰的边界定义，避免同类信息分散在两个文件中。

#### 验收标准

1. THE Self_Evolution_Engine SHALL 将用户客观事实（姓名、年龄、职业、设备等）统一写入 `data/identity/USER.md`，不再写入 `interaction_habits.md`。
2. THE Self_Evolution_Engine SHALL 将 AI 行为约束与交互规则（回复语言、格式偏好、禁忌事项等）统一写入 `data/identity/HABITS.md`，不再写入 `user_profile.json`。
3. THE UserProfileManager SHALL 在 `build_prompt()` 方法中，从 `data/identity/USER.md` 和 `data/identity/HABITS.md` 读取内容，而非从 JSON 文件读取。
4. WHEN Self_Evolution_Engine 提取记忆时，IF 提取结果的 `layer` 为 `objective`，THEN THE Self_Evolution_Engine SHALL 将其写入 `data/identity/USER.md`；IF `layer` 为 `subjective`，THEN THE Self_Evolution_Engine SHALL 将其写入 `data/identity/HABITS.md`。
5. THE Self_Evolution_Engine SHALL 在 `data/identity/USER.md` 和 `data/identity/HABITS.md` 中为每条记录附加最后更新时间戳，格式为 `<!-- updated: YYYY-MM-DD -->`。

---

### 需求 7：向量索引文件路径迁移的向后兼容性

**用户故事：** 作为开发者，我希望路径迁移不会破坏现有的向量搜索功能，旧数据能无缝迁移到新路径。

#### 验收标准

1. THE Self_Evolution_Engine SHALL 在初始化 `DiaryIndex` 时，使用 `data/diary/diary_vectors.jsonl` 作为索引文件路径。
2. THE Self_Evolution_Engine SHALL 在初始化 `JournalIndex` 时，使用 `data/journals/journal_vectors.jsonl` 作为索引文件路径。
3. WHEN `DiaryIndex` 或 `JournalIndex` 初始化时，IF 旧路径（`data/diary_vectors.jsonl` 或 `data/journal_vectors.jsonl`）存在，THEN THE Self_Evolution_Engine SHALL 自动将旧文件移动到新路径，并打印迁移提示。
4. FOR ALL 已索引的日记和日志条目，迁移前后的语义搜索结果 SHALL 保持一致（round-trip 属性：迁移前搜索结果 == 迁移后搜索结果）。

---

### 需求 8：数据迁移的安全性与可回滚性

**用户故事：** 作为开发者，我希望所有数据迁移操作都是安全的、可回滚的，避免因迁移失败导致数据丢失。

#### 验收标准

1. WHEN 任何迁移操作开始前，THE Self_Evolution_Engine SHALL 在 `data/migration_backup/` 目录下创建原始文件的完整备份，备份文件名包含时间戳。
2. IF 迁移过程中发生异常，THEN THE Self_Evolution_Engine SHALL 回滚到迁移前的状态，并将错误信息写入 `data/migration_backup/migration_error.log`。
3. THE Self_Evolution_Engine SHALL 在迁移完成后生成 `data/migration_backup/migration_manifest.json`，记录所有迁移操作（源路径、目标路径、操作类型、时间戳）。
4. WHEN 开发者手动执行迁移脚本时，THE Self_Evolution_Engine SHALL 在执行前打印迁移计划并等待确认（dry-run 模式），确认后再执行实际迁移。
