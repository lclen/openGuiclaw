---
name: create-skills
description: 创建和改进 OpenGuiclaw 技能。当需要：(1) 为重复性任务创建新外挂技能，(2) 改进现有外挂技能，(3) 将临时操作封装为可复用的外挂技能时使用。这是系统自我进化的核心机制。
---

# Skill Creator — OpenGuiclaw 技能创建指南

## 技能是什么

外挂技能是模块化的、自包含的能力包，通过 `SKILL.md` 声明式定义，它用以扩展 OpenGuiclaw 的认知或工作流能力。每个技能至少包含：
- `SKILL.md`（必需）：YAML frontmatter（包含 `name` 和 `description`） + Markdown 编写的指令操作手册。它的 `description` 即为模型工具调用时感知的介绍。
（注：如果你需要的是可执行的 Python 代码插件，请使用 `create_plugin` 工具。）

## 何时创建技能

1. 用户明确要求为某项流程创建一种"技能 (Skill)"或"SOP"。
2. 通过你自身的进化逻辑发现某套复杂查询或操作流程具备很高的重用价值，值得固化为技能手册。
3. 现有的某些知识或使用某个工具的最佳实践需要总结起来供以后查阅。

## 创建流程

1. **构思技能信息**
   - 确定技能要解决什么问题。
   - 确定技能的简短名称（如 `frontend-design`、`github-automation` 等）。
   - 确定技能简短有力的两句话说明。说明应清晰指出“做什么”和“何时触发”。

2. **调用系统工具**
   - 在你的基础工具（Python Tool集）中，调用你所拥有的 `create_skill` 函数。
   - 传入 `skill_name`、`description` 和代表说明书手册的 `content` 字段。
   - 系统将自动负责将此技能生成到正确的位置。

## 改进现有技能

1. 使用你基础工具中的 `find_skill` 或全局的 `list_skills` 确定现有技能是否存在。
2. 使用全局命令 `get_skill_info(skill_name="...")` 查看技能的当前 `SKILL.md` 的内容。
3. 如果你需要从基于文件的层面直接修改它，可以使用 `list_directory` / `search_file` 等文件访问工具进入 `.agents/skills` 或 `skills` 目录对其进行修改。
4. 或者，你可以将全量修改后的文本通过再次调用 `create_skill` 进行覆写。

## 关键原则

- **清晰的触发条件**：在 YAML 头的 `description` 要重点描述什么意图下调用该技能，这是 LLM 第一眼看到的东西。
- **详尽的操作说明**：`content` 部分不需要保留 YAML 头。直接用 Markdown 详细交代第一步怎么做、第二步怎么做、提供什么样的代码范例、有什么避坑指南。
- **无需赘余**：不要创建多余的 README.md、CHANGELOG.md 文档，一切集中于此即可。
