# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

---

## [3.0.0] - 2026-07-31

### 🏗️ Architecture

- **core.py 上帝文件拆分**: 2118 行 → 951 行，采用 Mixin 架构拆分为 6 个独立模块（`postprocessing` / `workflow_steps` / `silent_round` / `tool_loop` / `memory_ops` / `prompt_builder`），主类 `CastoriceAgent` 组合所有 Mixin
- **安全模块依赖注入**: 6 个安全系统全局单例（`get_authorization` / `get_rollback_manager` / `get_self_protection` / `get_file_guard` / `get_pattern_detector` / `get_audit_logger`）改为实例属性，支持多 Agent 实例和单元测试 mock
- **HTTP Server 合并**: `server/http_server.py` 从独立实现改为继承 `adapters/http_server.py` 的 `HTTPServerAdapter`，消除约 100 行重复代码

### 🧠 Self-Evolution

- **Thinking 模式 (v3.0 核心)**: 新增 `agent_mode: "thinking"`，Agent 通过 `ThinkingLoop` 自主决定执行顺序，不再被硬编码工作流束缚
- **意识引擎 (ConsciousnessEngine)**: 支持前台/后台双模式切换，用户说话时集中注意力，空闲时进入"漫游思维"模式
- **自主循环 (AutonomousLoop)**: 空闲时自主反思、写经历、更新自我概念，模拟真实的"持续存在"

## [2.6.0] - 2026-07-31

### ⚡ Performance

- **用户轮内省并发化**: `_phase_self_organization` 中 5 个串行 LLM 调用（思维策略/对话策略/能力评估/资源感知/状态模型）改为 `asyncio.gather` 并发执行，延迟从"求和"变为"取最大"，内省保留不变
- **Provider 级 Prompt Caching**: 支持 OpenAI 和 Anthropic 的 `cache_control` 机制。标记为 `cacheable=True` 的 system 消息（主回答循环、ThinkingLoop、ToolLoop、自主循环）将被 provider 缓存，缓存命中时 input token 费用降至 10%（OpenAI）或免费（Anthropic）

### 🛡️ Safety & Control

- **成本闸 (CostBudget)**: 全新模块，防止 LLM 调用失控
  - 每小时 / 每天 token 硬上限（可配置）
  - ThinkingLoop 每会话步数硬上限（默认 16 步/天）
  - AutonomousLoop 空闲反思频率硬上限（quick 默认 60s，deep 默认 600s）
  - 超 70% 预算自动降频（间隔加倍），超 95% 暂停自主活动
  - `/status` 接口新增成本闸状态字段（throttled/paused/hourly_used/daily_used）
  - 已接入 `engine_factory`（初始化）、`model_adapter`（token 记录）、`autonomous_loop`（频率检查）

### 🧠 Self-Evolution

- **可选身份种子层**: `self_concept.seed.md` 作为自我概念的可选初始锚点
  - 放在 `castorice_data/` 目录下即可生效
  - **只在自我概念为空时生效**，已有自我概念时完全不影响
  - 默认纯涌现（无种子），不剥夺任何涌现特性，仅提供可复现起点

### 🏗️ Architecture

- **反思调度器 (ReflectionScheduler)**: 统一所有反思触发入口
  - 三处分散触发点（轮末周期性、自我概念不一致、workflow 显式步骤）全部收敛为 `_try_reflection(state, trigger)`
  - 阈值集中管理，避免同一轮重复触发反思浪费 token
  - 轮末、不一致、显式三种触发类型走不同判断路径

### 📝 Docs & Metadata

- **pyproject.toml**: version 2.5.0 → 2.6.0，description 更新为真实描述（"自主进化的 AI Agent 框架"，移除"复刻 Hermes / 依托 LangGraph"等过时措辞）

### 🔧 Bug Fixes

- `core.py` 情感事件归档处加 `self.long_term is not None` 空值检查，防止 ChromaDB 异步初始化阶段抛出 `AttributeError` 导致 HTTP 500
- 所有 `except` 块补充 `AttributeError` 容错，避免异步初始化竞态条件导致未捕获异常

---

## [2.5.0]

初始发布版本（参考 v2.5.0 源码快照）。
