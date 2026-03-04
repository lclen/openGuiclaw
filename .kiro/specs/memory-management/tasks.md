# 实现计划：记忆管理功能 (Memory Management)

## 概述

基于现有 `core/memory.py` 进行最小化扩展，新增记忆类型分类、REST API、LLM 自动提取和前端面板。

## 任务列表

- [x] 1. 扩展 MemoryItem 和 MemoryManager（`core/memory.py`）
  - [x] 1.1 为 MemoryItem 添加 `type` 和 `source` 字段
    - 在 `__init__` 中新增 `type: str = "fact"` 和 `source: str = "manual"` 参数
    - 添加 `MEMORY_TYPES = {"fact", "skill", "error", "preference", "rule", "experience"}` 常量
    - `type` 不在枚举中时自动回退为 `"fact"`
    - 更新 `to_dict()` 输出 `type` 和 `source` 字段
    - 更新 `from_dict()` 读取 `type`（缺失时默认 `"fact"`）和 `source`（缺失时默认 `"manual"`）
    - _需求：1.1、1.2、1.3、1.5_

  - [ ]* 1.2 为 MemoryItem 编写属性测试（往返序列化）
    - **属性 1：MemoryItem 往返序列化**
    - **验证：需求 1.2、1.5**
    - 使用 `@given(content, tags, memory_type, source)` 生成任意输入
    - 断言 `from_dict(to_dict())` 后四个字段与原始对象完全一致
    - 写入 `tests/test_memory_management.py`

  - [x] 1.3 扩展 MemoryManager 的 `add()` 和 `update()` 方法
    - `add()` 新增 `type` 和 `source` 参数，传递给 `MemoryItem`
    - `update()` 新增 `new_type: str = None` 参数，支持更新 `type` 字段
    - _需求：1.2、2.4、2.8_

  - [x] 1.4 新增 `MemoryManager.list_by_type()` 方法
    - 实现 `list_by_type(self, memory_type: str) -> List[MemoryItem]`
    - 返回 `[m for m in self._memories if m.type == memory_type]`
    - _需求：1.4、2.2_

  - [ ]* 1.5 为 list_by_type 编写属性测试（过滤完整性）
    - **属性 2：按类型过滤的完整性**
    - **验证：需求 1.4、2.2**
    - 使用 `@given(items_list, filter_type)` 生成任意记忆集合
    - 断言结果中所有条目 `type == filter_type`，且数量与预期一致（无遗漏、无误包含）
    - 使用临时目录隔离测试数据
    - 写入 `tests/test_memory_management.py`

- [x] 2. 新增 REST API 端点（`core/server.py`）
  - [x] 2.1 实现 `GET /api/memory` 端点
    - 支持可选查询参数 `type`（按类型过滤）和 `q`（关键词搜索）
    - 无参数时返回全部记忆列表
    - 返回格式：`{"memories": [...]}`
    - _需求：2.1、2.2、2.3_

  - [x] 2.2 实现 `POST /api/memory` 端点
    - 定义 Pydantic 请求体：`content`（必填）、`type`（可选，默认 `"fact"`）、`tags`（可选）
    - 缺少 `content` 时 FastAPI 自动返回 HTTP 422
    - 成功时返回创建的记忆条目
    - _需求：2.4、2.5_

  - [x] 2.3 实现 `DELETE /api/memory/{memory_id}` 端点
    - 调用 `memory_manager.delete(memory_id)`
    - 返回 `False` 时响应 HTTP 404
    - _需求：2.6、2.7_

  - [x] 2.4 实现 `PUT /api/memory/{memory_id}` 端点
    - 定义 Pydantic 请求体：`content`、`type`、`tags` 均为可选
    - 调用扩展后的 `memory_manager.update()`
    - 返回 `False` 时响应 HTTP 404
    - _需求：2.8_

  - [ ]* 2.5 为 API 增删往返编写属性测试
    - **属性 3：API 增删往返**
    - **验证：需求 2.1、2.4、2.6**
    - 使用 FastAPI `TestClient`，`@given(content, memory_type)` 生成任意输入
    - 断言 POST 后 GET 可见，DELETE 后 GET 不可见
    - 写入 `tests/test_memory_management.py`

  - [ ]* 2.6 为 API 更新往返编写属性测试
    - **属性 4：API 更新往返**
    - **验证：需求 2.8**
    - 使用 `@given(original_content, new_content, new_type)` 生成任意输入
    - 断言 PUT 后 GET 返回的条目反映更新后的值
    - 写入 `tests/test_memory_management.py`

- [x] 3. 检查点 — 确保所有测试通过
  - 确保所有测试通过，如有疑问请询问用户。

- [x] 4. 新增 MemoryExtractor（`core/memory_extractor.py`）
  - [x] 4.1 实现 MemoryExtractor 类骨架和 `_call_llm` / `_parse_response`
    - 构造函数接收 `llm_client`、`memory_manager: MemoryManager`、`model: str`
    - `_call_llm(prompt: str) -> str`：调用 LLM，网络异常时捕获并记录日志，返回空字符串
    - `_parse_response(raw: str) -> Optional[dict]`：解析 JSON，失败时返回 `None` 并记录 `[MemoryExtractor] 解析失败` 日志，不抛出异常
    - _需求：6.6_

  - [ ]* 4.2 为 _parse_response 编写属性测试（无效 JSON 不中断）
    - **属性 7：无效 JSON 不中断处理**
    - **验证：需求 6.6**
    - 使用 `@given(st.text())` 生成任意字符串（包含无效 JSON）
    - 断言 `_parse_response` 不抛出异常，返回值为 `None` 或 `dict`
    - 写入 `tests/test_memory_management.py`

  - [x] 4.3 实现 `extract_from_turn()` 方法
    - 使用设计文档中的提示模板，向 LLM 提交单轮对话
    - LLM 返回 `NONE` 时返回空列表
    - 解析成功时调用 `memory_manager.add(..., source="auto_extracted")` 写入记忆
    - 返回写入的 `List[MemoryItem]`
    - _需求：6.1、6.2、6.5、6.7_

  - [x] 4.4 实现 `extract_from_conversation()` 方法
    - 接收完整对话历史 `messages: List[dict]`
    - 构造批量提取提示，要求 LLM 输出用户画像信息（偏好、身份、规则、技能、事实）
    - 解析并批量写入，每条附加 `source="auto_extracted"`
    - _需求：6.3、6.5_

  - [x] 4.5 实现 `extract_experience()` 方法
    - 接收 `messages: List[dict]` 和 `task_result: str`
    - 提示 LLM 仅输出 `skill`、`error`、`experience` 类型的记忆
    - 过滤掉不属于这三种类型的条目后再写入
    - _需求：6.4_

  - [ ]* 4.6 为 extract_experience 编写属性测试（输出类型约束）
    - **属性 6：extract_experience 输出类型约束**
    - **验证：需求 6.4**
    - Mock LLM 返回包含各种类型的 JSON 列表
    - 使用 `@given` 生成任意类型组合的 LLM 响应
    - 断言写入的所有记忆 `type` 均属于 `{"skill", "error", "experience"}`
    - 写入 `tests/test_memory_management.py`

  - [ ]* 4.7 为自动提取存储一致性编写属性测试
    - **属性 5：自动提取记忆的存储一致性**
    - **验证：需求 6.5、6.8**
    - Mock LLM 返回有效 JSON，`@given` 生成任意 content 和 type
    - 断言写入的记忆 `source == "auto_extracted"`，且可通过 `list_all()` 检索到
    - 写入 `tests/test_memory_management.py`

- [x] 5. 将 MemoryExtractor 集成到 Agent（`core/agent.py`）
  - [x] 5.1 在 Agent 初始化时实例化 MemoryExtractor
    - 在 `__init__` 中创建 `self.memory_extractor = MemoryExtractor(llm_client, memory_manager, model)`
    - 仅当 `memory_manager` 存在时才初始化
    - _需求：6.1_

  - [x] 5.2 在 `chat()` / `chat_stream()` 返回后异步触发 `extract_from_turn`
    - 每轮对话结束后，使用 `threading.Thread` 在后台调用 `memory_extractor.extract_from_turn(user_msg, assistant_msg)`
    - 后台线程异常不影响主流程
    - _需求：6.1、6.2_

  - [x] 5.3 在 `_evolution_loop` 中添加空闲超时批量提取逻辑
    - 记录最后一次消息时间戳 `self._last_message_time`
    - 在 `_evolution_loop` 中检查：距上次消息超过 30 分钟时，调用 `memory_extractor.extract_from_conversation(current_session_messages)`
    - 提取完成后重置计时器，避免重复提取同一段对话
    - _需求：6.3_

- [x] 6. 新增前端记忆管理面板（`templates/panels/panel_memory.html`）
  - [x] 6.1 创建面板骨架，与 panel_skills.html 保持一致的 Alpine.js + Tailwind 结构
    - 定义 Alpine.js `x-data` 组件，包含 `memories`、`loading`、`filterType`、`searchQuery` 状态
    - 实现 `loadMemories()` 方法，调用 `GET /api/memory` 并更新状态
    - 面板挂载时（`x-init`）自动调用 `loadMemories()`
    - _需求：3.1、3.2_

  - [x] 6.2 实现顶部统计摘要和类型过滤标签
    - 显示记忆总数
    - 渲染 6 种类型的过滤标签，每个标签旁显示该类型的数量
    - 点击标签时更新 `filterType`，触发列表过滤
    - 包含「全部」标签（`filterType = null`）
    - _需求：3.3、4.1、4.2、5.1、5.2_

  - [x] 6.3 实现搜索框、加载状态和空状态
    - 搜索框绑定 `searchQuery`，实时过滤（前端过滤，无需额外 API 调用）
    - 加载时显示 spinner 指示器
    - 列表为空时显示空状态提示文字
    - _需求：3.4、3.7、4.3_

  - [x] 6.4 实现记忆条目列表渲染
    - 每条记忆显示：类型标签（带颜色）、内容文本、创建时间、标签列表
    - 类型标签颜色：fact=蓝、skill=绿、error=红、preference=紫、rule=黄、experience=橙
    - 类型标签显示中文名称
    - _需求：3.5、4.1、4.2_

  - [x] 6.5 实现删除功能和手动刷新按钮
    - 每条记忆的删除按钮调用 `DELETE /api/memory/{id}`，成功后从列表移除
    - 刷新按钮重新调用 `loadMemories()`
    - 删除/刷新后统计数字实时更新
    - _需求：3.6、3.8、5.3_

  - [x] 6.6 在侧边栏导航中注册记忆面板入口
    - 在主模板（`index.html` 或对应布局文件）中添加记忆面板的导航按钮
    - 视觉风格与现有面板（技能、日记等）保持一致
    - _需求：3.1_

- [x] 7. 最终检查点 — 确保所有测试通过
  - 确保所有测试通过，如有疑问请询问用户。

## 备注

- 标有 `*` 的子任务为可选属性测试，可跳过以加快 MVP 交付
- 每个任务均引用具体需求条款，确保可追溯性
- 属性测试写入同一文件 `tests/test_memory_management.py`，避免分散
- 任务 1-2 完成后即可进行前端联调，任务 4-5 可并行开发
