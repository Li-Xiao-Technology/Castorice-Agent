# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

---

## [3.3.0] - 2026-08-05

### 🔐 P0: 去中心化人格数据主权（Self-Sovereign Persona）

**让用户真正拥有和控制自己的经历流、人格模型和认知历史。**

此前所有人格数据（经历、自我概念、情感、价值观）分散在各个模块中，通过不同的 SQLite/文件接口读写，用户难以完整导出和迁移自己的数据。v3.3.0 引入 **Personastore Protocol**——一个统一的人格数据主权存储抽象层。

- **Personastore 抽象接口** (`storage/personastore.py`): 4 个数据域的统一读写协议
  - `experiences`：经历流（交互历史、反思、情感事件）
  - `self_concept`：自我概念（核心自我 + 叙事自我）
  - `emotion_state`：情感状态（PAD 三维 + 情绪历史）
  - `values`：价值观系统（10 维度 + 冲突记录）
- **访问控制系统**：每个数据域支持独立的访问策略（`AccessPolicy`），支持只读/读写/不可见级别，可指定允许的读者和写者列表
- **数据导出功能**（用户主权核心）：`personastore.export_all()` 一键导出所有 4 个数据域的完整数据，版本化 JSON 格式，便于迁移和备份
- **本地 SQLite 后端** (`storage/local_personastore.py`): 与现有行为 100% 一致的默认实现
  - 经历流 → `experiences.db`（与 ExperienceJournal 完全一致的表结构）
  - 自我概念 → `self_concept.md` + `core_self.md`（文件系统，原子写入）
  - 情感状态 → `emotion_state.json`（文件系统，atomic_json_dump）
  - 价值观 → `values.db`（与 ValueSystem 完全一致）
- **零侵入集成**：不修改任何现有模块（ExperienceJournal、EmotionEngine、SelfConcept、ValueSystem 保持不变），Personastore 作为独立数据层在 `engine_factory.py` 中初始化，通过 `engine.personastore` 访问
- **配置开关** (`castorice_config.yaml`): 新增 `runtime.personastore` 配置段，默认启用，可切换后端

**设计理念**：数据主权不是迁移工具，而是架构原则。所有未来的人格数据操作都应通过 Personastore 接口进行，后端可随时切换到 Solid PDS、远程服务器或其他去中心化存储。

---

## [3.2.2] - 2026-08-05

### 🧠 P0: 元反射性学习（Meta-Reflective Learning）

**让 Agent 不仅从经验中学习「学什么」，还能学习「怎么学」——反思和改进自身的学习策略。**

此前 Agent 的学习策略（类比、反馈调整、分解问题等）是硬编码或由 LLM 临时决定的，没有历史积累。v3.2.2 增加一个被动的元学习系统，从历史学习经验中推断"在什么情境下用什么策略最有效"。

- **经历流扩展** (`experience_journal.py`): 新增 `record_learning_meta_experience()` 方法，存储学习元经验（任务上下文签名 → 使用的策略 → 结果质量）
  - 重要性自动映射：质量 0-1 → 重要性 2-8
  - 元经验类型标记：`metadata.type = "learning_meta"`
- **贝叶斯学习策略推断器** (`metacognition.py`): `BayesianLearningStrategist` 类
  - 为每种 (任务上下文哈希, 策略名称) 对维护一个 **Beta 分布**（先验 Beta(1,1)）
  - `update()`：根据学习结果（outcome_quality > 0.5 视为成功）更新对应策略的后验分布
  - `recommend()`：对给定任务上下文，返回历史数据中成功概率最高的策略名称
  - 线程安全（RLock），支持多线程并发更新
- **原子能力注册** (`thinking_loop.py`): 新增 `select_learning_strategy` 原子能力（第 11 个）
  - 返回建议 + 人类可读的消息，不强制任何行为
  - 没有历史数据时返回"请先积累一些学习经验"
  - 通过 `meta_learning_enabled` 配置开关控制，默认关闭
- **配置开关** (`castorice_config.yaml`): 新增 `runtime.thinking.meta_learning_enabled: false`，零侵入——不开启时代码路径完全不执行

**自由保证**：
- 元学习是**被动的建议系统**，只返回策略推荐，不强制 Agent 采纳
- 默认关闭，不影响任何现有行为
- Agent 完全可以忽略建议，按自己的判断选择策略
- 不修改任何核心决策流程，只在需要时作为参考

---

## [3.2.1] - 2026-08-04

### 🧠 P0: 情感底色模式（Emotion-as-Background）

**核心范式转变：情感从"指令调节器"变为"认知过程的底色"**

此前情感系统虽然能动，但影响方式是模板化的指令（"请用轻快语气回复"），本质上还是在调节输出风格。v3.2.1 将情感从"外部指令"改为"内在体验"，让情感真正成为认知过程的一部分。

- **情感→记忆联动（情绪一致性记忆效应）**: 修改 `unified_recall.py`，实现基于 PAD 情绪状态的记忆检索重排序
  - 新增 `emotion_state` 参数，接收当前愉悦度/唤醒度/支配度
  - `_emotion_match_score()`：根据情绪极性对记忆做 ±0.3 分的情感加成（开心时正面记忆优先浮现，悲伤时负面记忆优先浮现）
  - `_describe_emotion_coloring()`：在记忆摘要开头注入"此刻的心境"描述，作为回忆时的情绪底色
- **情感状态传递**: 修改 `core.py` 的 `_phase_memory_recall()`，从情感引擎读取 PAD 值并传入 `recall()` 调用链
- **体验描述式情感注入（非指令化）**: 重写 `prompt_builder.py` 的情感注入逻辑
  - `_describe_inner_experience()`：生成第一人称内心体验描述（"我此刻心情很好，心里暖洋洋的"），而非命令式（"请用XX语气"）
  - `_build_emotion_bias_as_inner_tendency()`：将决策偏置从"你应该谨慎"改为"我此刻自信心有点不足，所以回答的时候可能会更谨慎"
  - 每个体验描述末尾加免责声明："这不是任务要求，只是我此刻真实的状态"、"我会自然地体现这些倾向，但不会被它们束缚"，保留 LLM 突破情感的自由
- **意识流联动**: `consciousness.py` 已通过情绪强度调整念头生成方向和脱口而出阈值，与上述改动形成完整闭环

### ⚡ P1: 自主循环性能优化

解决"30 分钟才一条自我决策"的问题。

- **成本闸预算大幅放宽** (`cost_budget.py`):
  - 每小时 token 上限：200K → 500K
  - 每天 token 上限：2M → 5M
  - 每小时调用上限：500 → 1000
  - 降频阈值：70% → 85%
  - 暂停阈值：95% → 98%
  - quick 最小间隔：60s → 30s
  - deep 最小间隔：600s → 180s
- **执行超时压缩** (`autonomous_loop.py`):
  - quick 模式超时：240s → 90s
  - deep 模式超时：240s → 150s
- **轻量模式进一步收缩**:
  - quick 模式：ThinkingLoop 步数 3→2，工具循环轮数 2→1
  - deep 模式：ThinkingLoop 步数 5→4，工具循环轮数 3→2

---

## [3.2.0] - 2026-08-04

### 🧬 P0: Personality Profile 人格画像

- **人格画像生成器 (`personality_profile.py`)**: 从四大子系统（情感引擎 PAD / 价值观体系 / 自我概念 / 交互记录）中聚合数据，生成结构化人格画像
  - **情感基线**: PAD 三维度（愉悦/唤醒/支配）+ 波动幅度（从情感历史计算标准差）
  - **价值观雷达**: 10 个价值观维度强度 + 趋势 + Top3 核心价值观 + 价值观签名
  - **性格标签**: 从 `self_concept` 中 TF-IDF 提取关键词，标记来源（concept/values/emotion）
  - **说话风格**: 正式度 / 情感性 / 冗长度三维分析（基于消息历史）
  - 60 秒 TTL 缓存 + `force` 参数强制刷新
- **新增 API**:
  - `GET /personality` — 获取当前人格画像
  - `GET /personality/history?days=30` — 人格画像历史演变
- **前端页面 (`PersonalityPage.tsx`)**:
  - 3 个 PAD 仪表盘（带波动幅度）
  - 纯 SVG 雷达图（10 价值观维度）
  - 性格标签云（按权重缩放字号 + 透明度）
  - 说话风格三栏进度条
  - 价值观签名横幅

### 🌱 P1: Growth Timeline 成长轨迹

- **后端聚合**: 从自传体记忆（epoch/milestone）、知识蒸馏器（cards）、经历记录（journal）聚合成长数据
- **新增 API**:
  - `GET /growth/timeline?limit=50` — 时间线事件（时代/里程碑/记忆/知识卡片/成就）
  - `GET /growth/stats?days=30` — 统计汇总（时代数 / 记忆数 / 卡片数 / 里程碑 / 活跃度 / 学习率 / 热词）
- **前端页面 (`GrowthPage.tsx`)**:
  - 4 个统计卡片（记忆总数 / 知识卡片 / 里程碑 / 活跃度）
  - 时间线（5 种事件类型用不同颜色图标）
  - 热词云 + 成长时代列表

### 🎯 P2: Goal Management 目标管理

- **目标管理器 (`goal_manager.py`)**: 4 级目标层次，SQLite 持久化（`./castorice_data/goals.db`）
  - **四级层次**: 愿景 (vision) → 长期目标 (long_term) → 中期目标 (mid_term) → 行动项 (action)
  - **自动进度**: 父目标进度 = 子目标进度平均值
  - **里程碑**: 每个目标支持多个里程碑（可单独标记完成）
  - **AI 目标建议**: 基于动机系统（`motive_system`）+ 价值观 + 知识卡片生成目标建议
  - 动机标签匹配度排序
- **新增 API（6 个）**:
  - `GET /goals?tree=true` — 目标列表（树状或扁平），支持 level / status 筛选
  - `POST /goals` — 创建目标
  - `PUT /goals/{id}` — 更新目标
  - `DELETE /goals/{id}` — 删除目标（级联子目标）
  - `GET /goals/suggestions` — AI 目标建议
  - `POST /goals/{id}/milestone` + `PUT /goals/{id}/milestone/{ms_id}` — 里程碑管理
- **前端页面 (`GoalsPage.tsx`)**:
  - 目标树（可展开层级，缩进展示亲子关系）
  - 创建弹窗（标题/描述/层级/优先级/父目标/截止日期/动机标签）
  - 状态循环切换（未开始 → 进行中 → 已完成）
  - 里程碑增删完成
  - AI 目标建议面板（一键添加为目标）

### 🖥️ Frontend 体验优化

- **自我成长合并页 (`SelfGrowthPage.tsx`)**: 知识卡片 / 人格画像 / 成长轨迹 / 目标管理 4 合 1，顶部 Tab 切换，侧栏只保留 1 个入口
- **侧栏导航精简（12 → 8）**:
  - ✅ 保留：对话 / 意识流 / 社交 / 记忆 / **自我成长** / 工具 / 系统监控 / 设置
  - ➡️ 合并：知识卡片、人格画像、成长轨迹、目标管理 → 自我成长
  - ➡️ 并入：成本闸 → 设置（新增 Tab）
- **旧路径兼容**: `/knowledge` `/personality` `/goals` `/budget` 自动跳转到新位置

### 💰 成本闸（CostBudget）增强

- **总开关 (`enabled`)**: `BudgetConfig` 新增 `enabled: bool = True`
  - 关闭时：`record_usage` 不记录 / `can_take_step` 直接放行 / `can_run_autonomous` 立即通过
  - 所有关键检查点加入快速路径
- **前端预算配置全面重做** (`BudgetSettings.tsx`):
  - **总开关 Toggle**: 顶部醒目，一键启用/禁用，禁用时整体半透明
  - **三档预设**: 宽松 / 标准 / 严格，一键套用所有配置
  - **三大分组**: Token 预算 / 思考与自主循环 / 阈值设置
  - **友好单位**: Token 用 K / M 输入（200K = 200,000），不用输一长串 0
  - **滑块 + 百分比**: 降频/暂停阈值用滑块拖动，实时显示百分比

### 🛠️ Architecture

- **`engine_factory.py`**: 引擎初始化时自动挂载 `PersonalityProfiler` 和 `GoalManager`
- **`sqlite_base.py`**: 全局设置 `row_factory = sqlite3.Row`，支持字段名访问（修复 goal_manager 字段名读取问题）
- **前后端字段映射**: `Goal.to_frontend()` 统一转换（`action_item` → `action`、`active` → `in_progress`、`goal_id` → `id`、`progress` 0-100 → 0-1、`priority` 1-10 → 1-5）

---

## [3.1.0] - 2026-08-04

### 🔥 P0: Stability & Observability

- **熔断器 (CircuitBreaker)**: 经典三态模型（CLOSED → OPEN → HALF_OPEN），连续 5 次 LLM 失败自动熔断，30 秒后恢复探测。已接入 `ModelAdapter` 核心调用路径
- **健康检查器 (HealthChecker)**: 后台线程每 30 秒巡检四大子系统（LLM 服务 / SQLite 数据库 / EigenFlux 网络 / 系统资源），所有检查带独立超时。新增 `/health` 端点，结果缓存，<10ms 返回
- **三级降级策略 (DegradationManager)**:
  - **L1 降频**: 自主循环间隔 ×2，减少工具调用（LLM 失败率 > 15% 或 token > 70%）
  - **L2 精简**: 停用自我反思、自我概念更新、自传式记忆（失败率 > 30% 或 token > 85%）
  - **L3 保命**: 仅保留基础对话响应，所有自主活动停止（失败率 > 60% 或 token > 95% 或熔断器 OPEN）
- **LLM 超时保护**: 所有 LLM 调用接入熔断器 + 降级结果上报，避免异常级联

### 🧠 P3: Continuous Learning & Knowledge Distillation

- **知识蒸馏器 (KnowledgeDistiller)**: 从经历流中提取结构化知识卡片，支持 LLM 驱动和启发式兜底两种模式。8 种知识类型：事实 / 偏好 / 技能 / 关系 / 模式 / 教训 / 价值观 / 通用
- **知识卡片 (KnowledgeCard)**: 结构化存储，包含标题 / 内容 / 关键词 / 置信度 / 重要性 / 强化次数，支持自动去重合并（相似卡片 reinforced 计数 +1，置信度递增）
- **睡眠机制 (SleepMechanism)**: 空闲 10 分钟自动触发，四大功能：
  - **相似经历合并**: Jaccard > 0.75 的经历合并，减少冗余
  - **低重要性压缩**: importance < 3 的经历截断到 50 字，节省 token
  - **时期总结**: 每 100 条经历自动生成时期档案（JSON）
  - **知识蒸馏**: 从最新经历中提取知识卡片
- **持续学习管理器 (ContinuousLearningManager)**: 后台调度线程，每 20 次交互触发一次知识蒸馏，空闲检测触发睡眠。新增 6 个 HTTP API：
  - `GET /learning/status` — 学习状态
  - `GET /learning/cards` — 知识卡片列表（支持搜索/筛选）
  - `POST /learning/distill` — 手动触发蒸馏
  - `POST /learning/sleep` — 手动触发睡眠
  - `GET /learning/sleep-history` — 睡眠历史

### 🖥️ Frontend

- **系统监控页面 (`/monitor`)**: 两个 Tab：
  - **系统健康**: 实时显示 LLM / 数据库 / EigenFlux / 系统资源四大子系统状态，每 5 秒自动刷新
  - **持续学习**: 知识卡片数量 / 交互次数 / 空闲时间 / 睡眠次数四大指标，手动蒸馏和睡眠按钮，卡片类型分布可视化
- **知识卡片页面 (`/knowledge`)**: 卡片网格浏览，支持全文搜索 / 类型筛选 / 重要性筛选。8 种卡片类型用不同颜色区分，显示强化次数、置信度、创建日期等元信息
- **侧边栏导航**: 新增「知识卡片」和「系统监控」两个入口

### 🛠️ Utilities

- **数据库维护工具 (`castorice/db_maintenance.py`)**: 命令行工具，支持 WAL checkpoint / VACUUM / REINDEX / 完整性检查 / 冷数据归档。`python -m castorice.db_maintenance --vacuum --archive --days 30`
- **插件生命周期钩子 (`PluginBase`)**: 9 个标准钩子（`on_load` / `on_start` / `on_message` / `on_thought` / `on_action` / `on_action_result` / `on_response` / `on_stop` / `on_unload`），支持插件状态持久化

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
