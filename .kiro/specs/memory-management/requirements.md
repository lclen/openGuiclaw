# 需求文档：记忆管理功能 (Memory Management)

## 简介

为 openGuiclaw 项目实现类似 openakita 的结构化记忆管理功能。当前项目已有基于 JSONL 的简单记忆存储（`core/memory.py`），但缺乏记忆类型分类和前端可视化界面。本功能将扩展现有记忆系统，支持多种记忆类型（事实、技能、错误教训、偏好、规则、经验），并在前端新增记忆管理面板，供用户查看、搜索、编辑和删除记忆条目。

---

## 词汇表

- **Memory_Manager**：`core/memory.py` 中的记忆管理器，负责记忆的增删改查
- **Memory_Panel**：前端记忆管理面板（`panel_memory.html`），展示和操作记忆条目
- **MemoryItem**：单条记忆记录，包含内容、类型、标签、时间戳等字段
- **MemoryType**：记忆类型枚举，包括 `fact`（事实）、`skill`（技能/成功模式）、`error`（错误教训）、`preference`（用户偏好）、`rule`（规则约束）、`experience`（任务经验）
- **Memory_API**：FastAPI 后端提供的记忆管理 REST 接口
- **Server**：`core/server.py` 中的 FastAPI 应用实例

---

## 需求列表

### 需求 1：记忆类型扩展

**用户故事：** 作为 AI 助手，我希望记忆条目能按类型分类存储，以便在不同场景下检索到最相关的记忆。

#### 验收标准

1. THE Memory_Manager SHALL 支持以下记忆类型：`fact`（事实）、`skill`（技能/成功模式）、`error`（错误教训）、`preference`（用户偏好）、`rule`（规则约束）、`experience`（任务经验）
2. WHEN 创建 MemoryItem 时，THE Memory_Manager SHALL 将 `type` 字段持久化到 JSONL 存储文件中
3. IF 创建 MemoryItem 时未指定 `type`，THEN THE Memory_Manager SHALL 将类型默认设置为 `fact`
4. THE Memory_Manager SHALL 支持按 `type` 字段过滤检索记忆条目
5. FOR ALL 已存储的 MemoryItem，THE Memory_Manager SHALL 在序列化后反序列化时保持 `type` 字段不变（往返属性）

---

### 需求 2：记忆管理 REST API

**用户故事：** 作为前端开发者，我希望通过 REST API 对记忆条目进行增删改查，以便 Memory_Panel 能够与后端数据同步。

#### 验收标准

1. THE Memory_API SHALL 提供 `GET /api/memory` 端点，返回所有记忆条目的列表
2. WHEN 请求 `GET /api/memory` 时携带 `type` 查询参数，THE Memory_API SHALL 仅返回匹配该类型的记忆条目
3. WHEN 请求 `GET /api/memory` 时携带 `q` 查询参数，THE Memory_API SHALL 返回内容中包含该关键词的记忆条目
4. THE Memory_API SHALL 提供 `POST /api/memory` 端点，接受 `content`、`type`、`tags` 字段，创建新的记忆条目并返回创建结果
5. IF `POST /api/memory` 请求体缺少 `content` 字段，THEN THE Memory_API SHALL 返回 HTTP 422 状态码和描述性错误信息
6. THE Memory_API SHALL 提供 `DELETE /api/memory/{memory_id}` 端点，删除指定 ID 的记忆条目
7. IF `DELETE /api/memory/{memory_id}` 中的 `memory_id` 不存在，THEN THE Memory_API SHALL 返回 HTTP 404 状态码
8. THE Memory_API SHALL 提供 `PUT /api/memory/{memory_id}` 端点，更新指定 ID 记忆条目的 `content`、`type` 或 `tags` 字段

---

### 需求 3：前端记忆管理面板

**用户故事：** 作为用户，我希望在前端界面中查看和管理 AI 的记忆内容，以便了解 AI 记住了哪些信息并进行必要的修正。

#### 验收标准

1. THE Memory_Panel SHALL 在侧边栏中显示为可点击的导航按钮，与现有面板（技能、日记等）保持一致的视觉风格
2. WHEN 用户切换到记忆面板时，THE Memory_Panel SHALL 自动从 `GET /api/memory` 加载并展示所有记忆条目
3. THE Memory_Panel SHALL 按记忆类型（`fact`、`skill`、`error`、`preference`、`rule`、`experience`）提供过滤标签，WHEN 用户点击某类型标签时，THE Memory_Panel SHALL 仅显示该类型的记忆条目
4. THE Memory_Panel SHALL 提供搜索输入框，WHEN 用户输入关键词时，THE Memory_Panel SHALL 实时过滤显示匹配的记忆条目
5. THE Memory_Panel SHALL 为每条记忆条目显示：类型标签、内容文本、创建时间、标签列表
6. THE Memory_Panel SHALL 为每条记忆条目提供删除按钮，WHEN 用户点击删除时，THE Memory_Panel SHALL 调用 `DELETE /api/memory/{id}` 并从列表中移除该条目
7. IF 记忆列表为空，THEN THE Memory_Panel SHALL 显示空状态提示文字
8. THE Memory_Panel SHALL 提供手动刷新按钮，WHEN 用户点击时，THE Memory_Panel SHALL 重新从后端加载记忆列表

---

### 需求 4：记忆类型的视觉区分

**用户故事：** 作为用户，我希望不同类型的记忆在界面上有明显的视觉区分，以便快速识别记忆的性质。

#### 验收标准

1. THE Memory_Panel SHALL 为每种记忆类型分配不同的颜色标签：`fact` 使用蓝色、`skill` 使用绿色、`error` 使用红色、`preference` 使用紫色、`rule` 使用黄色、`experience` 使用橙色
2. THE Memory_Panel SHALL 为每种记忆类型显示对应的中文名称：`fact`→事实、`skill`→技能、`error`→教训、`preference`→偏好、`rule`→规则、`experience`→经验
3. WHILE 记忆数据正在从后端加载时，THE Memory_Panel SHALL 显示加载状态指示器

---

### 需求 5：记忆统计摘要

**用户故事：** 作为用户，我希望在记忆面板顶部看到各类型记忆的数量统计，以便快速了解记忆库的整体状况。

#### 验收标准

1. THE Memory_Panel SHALL 在面板顶部显示记忆总数
2. THE Memory_Panel SHALL 在过滤标签旁显示每种类型的记忆条目数量
3. WHEN 记忆列表发生变化（新增或删除）时，THE Memory_Panel SHALL 实时更新统计数字


---

### 需求 6：LLM 驱动的记忆自动提取

**用户故事：** 作为 AI 助手，我希望在对话过程中自动识别并提取值得长期记住的信息，以便无需用户手动操作即可积累有价值的记忆。

#### 验收标准

1. THE Memory_Manager SHALL 提供 `extract_from_turn(user_message, assistant_message)` 方法，在每轮对话结束后调用 LLM 分析对话内容，判断是否包含值得长期记住的信息

2. WHEN `extract_from_turn` 被调用时，THE Memory_Manager SHALL 向 LLM 提交结构化提示，要求输出包含以下字段的 JSON：`type`（记忆类型）、`subject`（主体）、`predicate`（谓词）、`content`（内容）、`importance`（重要性 1-5）；IF 无值得记录的信息，THEN LLM 输出 `NONE`

3. THE Memory_Manager SHALL 提供 `extract_from_conversation(messages)` 方法，在会话结束时接收完整对话历史，批量提取用户画像信息（身份、偏好、规则、技能、事实）

4. THE Memory_Manager SHALL 提供 `extract_experience(messages, task_result)` 方法，专门从已完成的任务对话中提取可复用的经验教训，仅输出 `skill`、`error`、`experience` 类型的记忆

5. WHEN LLM 提取结果返回时，THE Memory_Manager SHALL 自动将提取到的记忆条目写入持久化存储，并为每条记忆附加 `source: auto_extracted` 标记

6. IF LLM 返回的 JSON 格式无效或字段缺失，THEN THE Memory_Manager SHALL 记录错误日志并跳过该条目，不中断后续处理

7. THE Memory_Manager SHALL 在提取时遵循以下原则：区分「用户长期特征」（偏好、身份、规则）和「一次性任务内容」，仅提取在未来新对话中仍有价值的信息；宁少勿多，绝大多数对话轮次应输出 `NONE`

8. FOR ALL 通过 `extract_from_turn` 自动提取的记忆，THE Memory_Manager SHALL 确保其可通过 `GET /api/memory` 接口正常检索（与手动添加的记忆保持一致的存储格式）
