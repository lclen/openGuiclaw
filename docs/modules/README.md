# OpenGuiclaw 模块文档索引

本目录包含 OpenGuiclaw 所有核心模块的详细文档。每个文档包含概述、架构、核心功能、API 接口、配置、最佳实践、故障排查和性能优化。

## 核心引擎

### [Agent 核心引擎](./agent.md)
OpenGuiclaw 的核心对话引擎，负责协调记忆系统、会话管理、技能调用和 LLM 交互。

**关键特性**：
- 多模型配置（主对话/视觉/图片解析/进化）
- OpenAI Function Calling 工具链
- 上下文窗口管理与滚动摘要
- 自动记忆提取
- Token 用量统计

**适用场景**：
- 理解对话流程
- 配置 LLM 端点
- 调试工具调用
- 优化 Token 消耗

---

## 插件与技能系统

### [Plugin 插件系统](./plugins.md)
热加载插件机制，支持运行时动态加载、卸载和重载插件。

**关键特性**：
- 热重载（文件监视）
- 插件元数据管理
- 技能隔离
- 自动清理

**适用场景**：
- 开发新插件
- 调试插件加载
- 管理插件生命周期

### [Skills 技能系统](./skills.md)
技能注册和执行引擎，提供装饰器风格的技能定义和 OpenAI Function Calling 格式转换。

**关键特性**：
- 装饰器注册
- 动态启用/禁用
- 配置管理
- 同步/异步执行

**适用场景**：
- 注册新技能
- 配置技能参数
- 调试技能执行

---

## 会话与记忆系统

### [Session 会话管理](./session.md)
管理对话会话的生命周期，包括消息历史、上下文窗口、滚动摘要和持久化存储。

**关键特性**：
- 多模态消息支持
- 工具调用记录
- Token 估算
- 滚动摘要
- 工具调用配对验证

**适用场景**：
- 管理对话历史
- 优化上下文窗口
- 调试工具调用

### [Memory 记忆系统](./memory.md)
长期记忆管理，支持 JSONL 存储、向量检索和记忆提取。

**关键特性**：
- 分类记忆（preference/rule/fact/experience/skill/error）
- 向量语义检索（RAG）
- 自动记忆提取
- 记忆去重

**适用场景**：
- 存储长期记忆
- 语义搜索
- 记忆管理

### [Knowledge Graph 知识图谱](./knowledge_graph.md)
轻量级知识图谱系统，存储实体关系三元组。

**关键特性**：
- 三元组存储（subject → relation → object）
- 实体查询
- 关系检索
- 上下文生成

**适用场景**：
- 存储实体关系
- 查询知识图谱
- 生成关系摘要

---

## 自我进化系统

### [Self Evolution 自我进化引擎](./evolution.md)
从每日对话日志中提取长期记忆、知识图谱关系、生成 AI 日记。

**关键特性**：
- 日记生成（带 RAG）
- 记忆提取（双层架构）
- 知识图谱提取
- 主动探索（Agentic Exploration）
- 习惯进化

**适用场景**：
- 配置每日进化
- 调整提取标准
- 启用主动探索

### [Identity Manager 人设管理](./identity.md)
管理 AI 的身份层，包括用户档案、交互习惯和 Agent 行为规范。

**关键特性**：
- 用户档案管理（USER.md）
- 习惯管理（HABITS.md）
- Prompt 注入
- 自动时间戳
- 旧文件迁移

**适用场景**：
- 管理用户信息
- 更新交互习惯
- 构建系统 Prompt

---

## 视觉与感知系统

### [Context 视觉感知系统](./context.md)
通过后台线程定时截屏并使用 Vision 模型分析用户当前状态。

**关键特性**：
- 状态判定（working/entertainment/idle/error）
- 活泼度模式（silent/normal/lively）
- 日志去重
- 主动搭话
- 冷却机制

**适用场景**：
- 配置视觉感知
- 调整活泼度
- 调试主动搭话

---

## 通道与调度系统

### [Channels IM 通道系统](./channels.md)
多平台 IM 通道适配器，支持 DingTalk、Feishu、Telegram 等。

**关键特性**：
- 统一消息接口
- Webhook 接收
- 消息发送
- 多媒体支持

**适用场景**：
- 接入新 IM 平台
- 配置 Webhook
- 调试消息收发

### [Scheduler 任务调度系统](./scheduler.md)
Cron 风格的任务调度器，支持定时任务和延迟任务。

**关键特性**：
- Cron 表达式
- 任务类型（reminder/plan/evolution）
- 持久化存储
- 任务执行日志

**适用场景**：
- 创建定时任务
- 管理任务队列
- 调试任务执行

---

## 系统维护

### [Self Check 系统自检](./self_check.md)
自动检测系统错误并尝试修复，支持分层修复策略和修复验证。

**关键特性**：
- 日志分析
- LLM 诊断
- 分层修复（Tool/Core）
- 修复验证
- 重试+降级

**适用场景**：
- 系统健康检查
- 自动修复错误
- 查看修复报告

### [Bootstrap 启动引导](./bootstrap.md)
程序启动前的环境初始化，包括依赖检查、目录创建和配置准备。

**关键特性**：
- 环境变量设置
- Node.js 环境配置
- 目录初始化
- 配置文件准备
- 依赖检查

**适用场景**：
- 首次启动配置
- 环境诊断
- 依赖管理

---

## 快速导航

### 按功能分类

**对话与交互**：
- [Agent](./agent.md) - 核心对话引擎
- [Session](./session.md) - 会话管理
- [Context](./context.md) - 视觉感知

**记忆与知识**：
- [Memory](./memory.md) - 长期记忆
- [Knowledge Graph](./knowledge_graph.md) - 知识图谱
- [Self Evolution](./evolution.md) - 自我进化

**扩展与工具**：
- [Plugins](./plugins.md) - 插件系统
- [Skills](./skills.md) - 技能系统
- [Channels](./channels.md) - IM 通道

**系统管理**：
- [Identity](./identity.md) - 人设管理
- [Scheduler](./scheduler.md) - 任务调度
- [Self Check](./self_check.md) - 系统自检
- [Bootstrap](./bootstrap.md) - 启动引导

### 按使用场景分类

**新手入门**：
1. [Bootstrap](./bootstrap.md) - 了解启动流程
2. [Agent](./agent.md) - 理解核心架构
3. [Skills](./skills.md) - 学习技能注册

**插件开发**：
1. [Plugins](./plugins.md) - 插件开发指南
2. [Skills](./skills.md) - 技能注册方法
3. [Session](./session.md) - 会话管理

**系统优化**：
1. [Agent](./agent.md) - Token 优化
2. [Memory](./memory.md) - 记忆管理
3. [Self Evolution](./evolution.md) - 进化配置

**故障排查**：
1. [Self Check](./self_check.md) - 自动诊断
2. [Bootstrap](./bootstrap.md) - 环境问题
3. 各模块的"故障排查"章节

---

## 文档约定

每个模块文档包含以下章节：

1. **概述**：模块的功能和定位
2. **架构**：模块的结构和组件
3. **核心功能**：主要功能和特性
4. **API 接口**：编程接口和使用方法
5. **配置**：配置文件和参数
6. **最佳实践**：推荐的使用方式
7. **故障排查**：常见问题和解决方案
8. **性能优化**：优化建议
9. **未来优化方向**：计划中的改进

---

## 贡献指南

欢迎贡献文档改进！

**文档规范**：
- 使用 Markdown 格式
- 代码示例必须完整可运行
- 包含实际配置示例
- 故障排查提供具体解决方案

**提交流程**：
1. Fork 项目
2. 创建文档分支
3. 编写/修改文档
4. 提交 Pull Request

---

## 相关资源

- [项目结构](../../structure.md) - 完整的项目目录结构
- [技术栈](../../tech.md) - 使用的技术和工具
- [产品概述](../../product.md) - 产品定位和核心能力
- [GitHub 仓库](https://github.com/yourusername/openguiclaw) - 源代码

---

**最后更新**: 2026-03-11
**文档版本**: 1.0.0
