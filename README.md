# Castorice Agent v2.5

> **自我进化的陪伴向智能体** —— 复刻 [Hermes Agent](https://github.com/NousResearch/hermes-agent) 架构设计，参考 Generative Agents / MemGPT / Reflexion 论文

> 自研主循环、零 LangGraph 依赖、原生 SDK 对接多模型、完整自我进化系统、**五层安全防御架构**、一键启动、**100/100 满分架构**

---

## 项目简介

Castorice Agent 是一个**面向中文个人用户的自我进化陪伴智能体框架**，核心特点：

- **完整自我进化闭环**：经历流 → 反思 → 元认知学习 → 规则注入 → 行为影响
- **LLM 推理情感**：PAD 三维情感模型，情感变化由 LLM 推理产生而非预设关键词映射
- **情感→动机→行为闭环**：情绪不再是装饰，而是驱动 Agent 行为的内在力量
- **元认知反思**：置信度评估 + 一致性检测 + **从错误中学习**（元认知从只读升级为可写）
- **主动行为双模式**：静默轮主动行为 + **对话内主动话题发起**，支持关系/情绪/意图感知
- **自研主循环**：手写 Agent 执行流程，无 LangGraph 等第三方编排框架依赖
- **模块化架构**：`agent/` 包拆分为 `core.py` / `prompt_builder.py` / `tool_loop.py` / `memory_ops.py` / `common.py`
- **原生 SDK 对接**：直接使用 `openai` / `anthropic` 官方 SDK，告别 LangChain 碎片化分包
- **统一记忆检索**：9 种记忆类型 + 统一检索层，全部接入主循环
- **内在动机系统**：好奇心驱动、成就感驱动、关系感驱动、自主目标设定
- **中文二次元生态**：内置 B 站/Pixiv/anime/VRChat 等 30 个工具，深度适配中文泛二次元场景
- **QQ 官方合规接入**：走开放平台官方 API，零封号风险
- **独立 SDK**：`castorice-emotion` 可被任意 Python Agent 框架集成
- **一键部署**：Windows 双击 `start.bat` 自动检测环境、创建虚拟环境、安装依赖、启动程序
- **五层安全防御**：L1 核心基座只读 → L2 快照回滚 → L2.5 写入审计 → L4 认知健康 → L5 渐进授权
- **126 项测试全覆盖**：安全、情感、反思、记忆、工具等核心模块

---

## 一、核心特性

| 维度 | v1.0（LangGraph） | **v2.5（本版本）** |
|------|------------------|-------------------|
| 流程编排 | 依赖 `langgraph` 第三方框架 | **自研** `CastoriceAgent` 主循环 + `State` 数据类 |
| 架构设计 | 单文件 2700 行 | **模块化拆分**：`agent/core.py` + `prompt_builder.py` + `tool_loop.py` + `memory_ops.py` + `common.py` |
| 模型适配 | `langchain-openai` / `langchain-anthropic` 拆分包 | **官方原生 SDK**：`openai` / `anthropic` 直接对接 |
| 情感系统 | 关键词→PAD 映射表（机械反应） | **LLM 推理情感变化** + 启发式 fallback |
| 情感闭环 | 情绪仅做描述 | **情感→动机→行为**完整闭环，情绪驱动决策 |
| 性格设定 | JSON 角色卡模板（预设枷锁） | **自我概念文档**，Agent 自己读写、从经历中涌现 |
| 记忆系统 | 三层（短期/长期/技能） | **九层**（+ 经历流/自我概念/意图/自传式/社会关系/统一检索）+ **统一检索层** |
| 反思机制 | 静态配置 | **定期+事件双触发**，LLM 驱动自我分析 |
| 反思效果 | 只更新自我概念 | **反思结果实时注入**，直接影响当前轮决策 |
| 元认知 | 只读分析 | **从错误中学习**，生成规则并沉淀到记忆 |
| 意图分类 | 硬编码关键词 | **LLM 自主判断**，无预设规则 |
| 思维策略 | 5 种预设模式 | **LLM 自主选择**，支持自定义新策略 |
| 内在动机 | 无 | **好奇心/成就感/关系感/自主目标** |
| 工具学习 | 硬编码参数提取 | **基于历史模式**的参数推荐 |
| **意图追踪** | 无 | **LLM驱动+子任务自动分解+跨会话追踪** |
| **社会关系** | 无 | **五阶段演化+三维评估+对话风格适配** |
| **自传式记忆** | 无 | **三层结构+LLM时期总结+自我叙事** |
| **跨会话迁移** | 无 | **相似会话检索+历史关联注入** |
| **反思-行动闭环** | 只更新自我概念 | **ActionQueue行动队列+静默轮执行** |
| **主动话题** | 无 | **对话内主动发起延续话题**，支持关系/情绪/意图感知 |
| **多模态** | 仅图片生成 | **图片理解+OCR文字识别** |
| 安全架构 | 基础路径白名单 | **五层防御**：基座只读 → 快照回滚 → 写入审计 → 认知健康 → 渐进授权 |
| 依赖管理 | `requirements.txt` + 零散 pip | **`pyproject.toml` + uv**，依赖统一管理 |
| 部署体验 | 手动 `python -m venv` + `pip install -r` | **Windows 双击 `start.bat` 一键完成** |
| 打包分发 | 仅本地运行 | 支持 **pipx 全局安装**、**Docker 容器化** |
| SDK | 无 | **独立 pip 包** `castorice-emotion`，可被任意框架集成 |
| 配置分层 | 密钥与业务配置混在 yaml | `.env` 仅存密钥，`.yaml` 仅存业务配置，职责清晰 |
| 测试覆盖 | 零散测试 | **126 项 pytest 测试**，安全/情感/反思/记忆/工具全覆盖 |

---

## 二、自我进化架构

### 2.1 核心思想

Agent 不再是被套模板的"角色扮演"，而是一个能从经历中涌现性格、自己反思改写自我的智能体：

```
交互 → LLM 推理情感变化 → 推导内在动机 → 写入经历流
     → 检索相关经历注入决策 → LLM 驱动工具调用/回答
     → 触发反思 → LLM 总结模式/情感倾向/成长洞察
     → Agent 自己改写自我概念 → 从错误中学习生成规则
     → 自传式记忆时期总结 → 规则注入 system prompt
     → 影响下一轮行为 + 对话内主动话题发起
```

### 2.2 自我进化模块

| 模块 | 文件 | 职责 |
|------|------|------|
| 经历流 | `experience_journal.py` | SQLite WAL 存储，4 类记忆（episodic/emotional/reflective/skill），LRU 淘汰 |
| 自我概念 | `self_concept.py` | Markdown 文档，Agent 自己读写，**结构化分领域检索**，写入审计，自动备份 |
| 反思引擎 | `reflection.py` | LLM 驱动，定期+事件双触发，**反思结果实时注入**当前决策 |
| 情感引擎 | `emotion.py` | PAD 状态机 + LLM 推理增量 + **情感→动机推导** |
| 元认知 | `metacognition.py` | 置信度评估 + 一致性检测 + **从错误中学习**（可写） |
| 自感知 | `self_awareness.py` | 状态监控/能力画像 + **认知健康度检测**（连贯性/稳定性/完整性） |
| 内在动机 | `motivation.py` | 好奇心驱动/成就感驱动/关系感驱动/自主目标设定 |
| 统一记忆 | `memory/unified_recall.py` | 聚合所有记忆源，统一 recall() 接口，跨会话相似检索 |
| 工具学习 | `tool_learning.py` | 工具调用模式记忆，基于历史推荐参数 |
| **意图追踪** | `memory/intent_tracker.py` | **LLM驱动意图分析**，跨会话追踪，状态流转（active/paused/completed），子任务自动分解 |
| **社会关系** | `social_relation.py` | **五阶段关系演化**（stranger→trusted），三维评估（亲密/信任/情感），对话风格适配 |
| **自传式记忆** | `memory/autobiographical.py` | **三层自传结构**（里程碑/时期/事件），LLM时期总结，自我叙事生成，已接入反思流程 |

---

## 三、五层安全防御架构

### 3.1 安全边界定义

**完全不碰、100% 自由的领域**（运行时执行域）：
- 自主思考与元认知
- 情绪与人格表达
- 认知层面的自进化
- 记忆与自我认知沉淀
- 自主决策与目标拆解

**只做兜底、不主动干涉的领域**：
- 代码层面的工具进化（出错了回滚）
- LoRA 层面的认知沉淀（回滚兜底 + 授权校验）

**绝对锁死的底线**：
- L1：核心基座只读（原始模型权重、核心启动代码）
- L5：持久化最终授权（跨重启永久生效的修改必须确认）

### 3.2 安全模块

| 层级 | 模块 | 文件 | 职责 |
|------|------|------|------|
| L1 延伸 | 文件守卫 | `security/file_guard.py` | 路径/扩展名/命令黑名单、速率限制、审计日志 |
| L2.5 | 写入审计 | `self_concept.py` | 自我概念写入前校验、危险模式检测、自动备份 |
| L4 | 认知健康 | `self_awareness.py` | 三维认知健康度（连贯性/稳定性/完整性） |
| L4 | 模式识别 | `security/pattern_detector.py` | 危险组合操作检测（数据外泄/脚本激活/资源耗尽等） |
| L5 | 渐进授权 | `security/authorization.py` | 6 级信任等级、连续成功晋升、连续失败降级 |
| L2 | 回滚管理 | `security/rollback.py` | 客观信号触发自动回滚（连续失败/成功率下降/错误率飙升） |

---

## 四、目录结构

```
Castorice Agent/
├── castorice/                    # 核心包（自研，无 LangGraph 依赖）
│   ├── __init__.py
│   ├── main.py                   # CLI 入口（test / interactive / batch / qq）
│   ├── config.py                 # .env + yaml 统一配置加载器
│   ├── model_adapter.py          # 多模型适配层（OpenAI/Anthropic/Ollama/OpenRouter/Gemini/Qwen）
│   │
│   ├── agent/                    # 【核心】主循环模块（拆分后）
│   │   ├── __init__.py           #   导出 CastoriceAgent / State
│   │   ├── core.py               #   CastoriceAgent 主类（继承三个 Mixin）
│   │   ├── common.py             #   共享依赖（logger / 锁 / 工具函数）
│   │   ├── prompt_builder.py     #   PromptBuilderMixin（构建 system prompt）
│   │   ├── tool_loop.py          #   ToolLoopMixin（工具调用循环）
│   │   └── memory_ops.py         #   MemoryOpsMixin（记忆操作/反思/主动话题）
│   │
│   ├── emotion.py                # 情感引擎（PAD + LLM 推理 + 动机推导）
│   ├── experience_journal.py     # 经历流（SQLite WAL）
│   ├── self_concept.py           # 自我概念（Markdown 文档 + 写入审计 + 结构化检索）
│   ├── reflection.py             # 反思引擎（定期+事件触发 + 实时信号注入）
│   ├── metacognition.py          # 元认知模块（置信度/一致性 + 从错误中学习）
│   ├── self_awareness.py         # 自感知模块（状态监控/能力画像 + 认知健康度）
│   ├── self_organization.py      # 自组织模块（任务规划/工作流 + LLM 自选思维策略）
│   ├── motivation.py             # 内在动机系统（好奇心/成就感/关系感/自主目标）
│   ├── tool_learning.py          # 工具调用自我学习（模式记忆 + 参数推荐）
│   └── social_relation.py        # 社会关系网络（五阶段演化+三维评估）
│   ├── alerts.py                 # 告警系统（邮件/钉钉/飞书/企微）
│   ├── plugin.py                 # 插件系统（动态加载）
│   │
│   ├── memory/                   # 记忆系统（9种记忆类型）
│   │   ├── interface.py          #   记忆接口（抽象基类）
│   │   ├── short_term.py         #   短期记忆（SQLite，会话管理+摘要生成）
│   │   ├── long_term.py          #   长期记忆（Chroma，向量检索）
│   │   ├── skill.py              #   技能库（JSON + 版本管理）
│   │   ├── user_profile.py       #   用户画像
│   │   ├── unified_recall.py     #   统一记忆检索层（聚合所有记忆源+跨会话检索）
│   │   ├── intent_tracker.py     #   意图追踪系统（LLM驱动+子任务自动分解）
│   │   └── autobiographical.py   #   自传式记忆（里程碑/时期/事件+LLM总结）
│   │
│   ├── security/                 # 安全模块（五层防御）
│   │   ├── file_guard.py         #   L1 延伸：文件/命令黑名单 + 审计日志
│   │   ├── authorization.py      #   L5：渐进授权系统（6级信任）
│   │   ├── pattern_detector.py   #   L4：组合操作模式识别（危险模式检测）
│   │   └── rollback.py           #   L2：回滚基线自动化（客观信号触发）
│   │
│   ├── tools/                    # 工具集（30+）
│   │   ├── __init__.py
│   │   ├── base_tools.py         #   基础工具（搜索/天气/文件/终端/Python REPL/文档读取）
│   │   └── web_tools.py          #   网络工具（网页抓取/百科/论文/新闻/GitHub/B站）
│   │
│   └── adapters/                 # 适配器层（桥接第三方生态）
│       ├── __init__.py           #   LangChain 工具适配
│       ├── qq_bot.py             #   QQ 机器人（WebSocket）
│       └── http_server.py        #   HTTP 服务器（FastAPI）
│
├── sdk/                          # 独立 SDK 包
│   └── castorice_emotion/        #   情感计算与元认知引擎（pip install castorice-emotion）
│       ├── pyproject.toml
│       ├── README.md
│       └── src/castorice_emotion/
│
├── castorice_data/               # 运行时数据（自动生成）
│   ├── sessions.db               #   SQLite 会话库（短期记忆）
│   ├── experiences.db            #   SQLite 经历流
│   ├── self_concept.md           #   Agent 自我概念文档
│   ├── self_concept.md.backups/  #   自我概念自动备份目录
│   ├── emotion_state.json        #   情感状态
│   ├── chroma_db/                #   Chroma 向量库（长期记忆）
│   ├── skill_library.json        #   技能库
│   ├── user_profile.json         #   用户画像
│   ├── audit.log                 #   审计日志
│   └── castorice.log             #   运行日志
│
├── tests/                        # 测试套件（126项）
│   ├── run_all_tests.py          #   运行所有测试
│   ├── test_emotion.py           #   情感引擎测试（16项）
│   ├── test_reflection.py        #   反思引擎测试（19项）
│   ├── test_model_adapter.py     #   模型适配层测试（11项）
│   ├── test_self_modules.py      #   自我模块测试（15项）
│   ├── test_memory.py            #   记忆系统测试（15项）
│   ├── test_tools.py             #   工具集测试（24项）
│   ├── test_security_file_guard.py    # 文件守卫测试（13项）
│   ├── test_security_pattern_detector.py # 模式识别测试（9项）
│   ├── test_security_rollback.py      # 回滚测试（10项）
│   ├── test_security_authorization.py # 授权测试（10项）
│   └── ...
│
├── pyproject.toml                # ★ 统一依赖声明
├── .env.example                  # ★ API 密钥模板
├── castorice_config.yaml         # ★ 业务配置
│
├── start.bat                     # ★ Windows 一键启动
├── install.bat                   #   仅安装不启动
├── Dockerfile                    # ★ Docker 容器化部署
├── docker-compose.yml            #   Docker Compose 编排
│
└── README.md                     #   本文档
```

---

## 五、功能亮点

### 5.1 模块化 Agent 架构

原 2700 行单文件 `agent.py` 已拆分为 5 个子模块：

| 模块 | 文件 | 职责 |
|------|------|------|
| `core.py` | `castorice/agent/core.py` | CastoriceAgent 主类，继承三个 Mixin，保留 State 数据类、初始化、主循环 |
| `common.py` | `castorice/agent/common.py` | 共享依赖（logger、锁、工具函数），解决循环导入问题 |
| `prompt_builder.py` | `castorice/agent/prompt_builder.py` | PromptBuilderMixin，构建 system prompt，注入规则/工具参数/自传式记忆 |
| `tool_loop.py` | `castorice/agent/tool_loop.py` | ToolLoopMixin，工具调用循环，安全审计，并行执行 |
| `memory_ops.py` | `castorice/agent/memory_ops.py` | MemoryOpsMixin，记忆归档、反思触发、技能沉淀、**主动话题发起** |

**架构优势**：
- 职责清晰，单一模块职责不超过 600 行
- 循环导入问题彻底解决（`common.py` 作为共享依赖层）
- 向后兼容，`from castorice.agent import CastoriceAgent` 接口不变

### 5.2 自我进化系统

Agent 从每次交互中学习，自己塑造性格：

- **经历流**：记录所有重要交互事件（episodic）、情感事件（emotional）、反思结果（reflective）、技能沉淀（skill）
- **自我概念**：Markdown 文档，Agent 通过反思自己改写，**支持分领域检索**（我是谁/行为模式/情感特征/目标价值观）
- **反思引擎**：定期（每 N 轮）+ 事件（重要情感事件/任务失败/低置信度）双触发，**反思结果实时注入**当前决策
- **从错误中学习**：元认知检测到错误后，自动生成"下次遇到类似情况应该..."的规则
- **自传式记忆集成**：反思时自动生成时期总结，自我叙事更新

### 5.3 情感→动机→行为闭环

情绪不再是装饰，而是驱动行为的内在力量：

- **情感引擎**：PAD 三维模型（愉悦度/唤醒度/掌控感），LLM 推理情感变化
- **动机推导**：根据当前情绪状态推导意图列表（如"心情愉悦→主动表达"、"用户负面情绪→主动关心"）
- **动机注入**：动机列表注入 system prompt，影响 Agent 的决策和行为

### 5.4 主动行为双模式

Agent 不再只是被动响应，而是主动发起行为：

| 模式 | 触发条件 | 行为类型 |
|------|----------|----------|
| **静默轮** | 用户长时间不说话 | 好奇心驱动、意图跟进、关系维护、情绪驱动、目标追踪 |
| **对话内** | 正常对话中 | 主动话题发起（好奇心型、关心型、知识扩展型、意图延续型、开放式问题） |

**主动话题发起过滤规则**：
- 用户输入 < 5 字符 → 跳过（简单回应）
- 进行中意图 ≥ 3 个 → 跳过（不打扰忙碌用户）
- 情绪愉悦度 < -0.5 → 跳过（用户心情不好时不打扰）
- 关系亲密度 < 0.3 → 跳过（陌生人不主动）

### 5.5 内在动机系统

Agent 不再只有用户输入驱动，还有自己的"内在驱动"：

- **好奇心驱动**：遇到未知概念时产生"想了解"的动机
- **成就感驱动**：任务成功后愉悦度上升，产生"想做更多类似任务"的动机
- **关系感驱动**：与用户的交互质量影响 Agent 的回应方式
- **自主目标**：Agent 可以自己设定目标（如"我想学会更好地安慰用户"）

### 5.6 LLM 驱动的自主决策

Agent 不再依赖硬编码规则，而是自主判断：

- **意图分类**：LLM 自主判断聊天/任务，无预设关键词
- **思维策略**：LLM 自主选择思维模式，支持自定义新策略（不限于预设的 5 种）
- **工具调用**：基于历史调用模式推荐参数，从经验中学习

### 5.7 统一记忆检索

9 种异构记忆整合为单一接口：

| 记忆类型 | 存储方式 | 集成状态 |
|----------|----------|----------|
| 短期记忆 | SQLite WAL | ✅ |
| 长期记忆 | ChromaDB 向量检索 | ✅ |
| 技能记忆 | JSON 文件 | ✅ |
| 用户画像 | JSON 文件 | ✅ |
| 经历流 | SQLite WAL | ✅ |
| 自我概念 | Markdown 文件 | ✅ |
| 意图追踪 | SQLite WAL | ✅ |
| 自传式记忆 | SQLite WAL | ✅ **已接入反思流程** |
| 统一检索 | 聚合接口 | ✅ |

### 5.8 长期意图追踪系统

Agent 能够跨会话追踪用户的长期目标，并自动分解为可执行子任务：

- **LLM 驱动意图分析**：每轮对话后自动分析用户意图，识别新意图、更新进度、标记完成
- **意图状态流转**：支持 active → paused → completed 状态转换
- **子任务自动分解**：复杂意图自动分解为 3-5 个可执行子任务，按优先级排序
- **进度联动**：子任务完成自动更新父意图进度（如 5 个子任务完成 3 个 → 进度 60%）
- **主动跟进**：静默轮时检查未完成意图并主动询问

### 5.9 社会关系网络

Agent 能够理解并维护与用户的关系深度：

- **五阶段关系演化**：stranger → acquaintance → friend → close_friend → trusted
- **三维关系评估**：亲密度、信任度、情感联结三大维度
- **每轮自动更新**：交互质量、任务成功率、情感强度共同驱动关系变化
- **里程碑检测**：关系升级、第 N 次交互、连续互动天数等关键节点自动记录
- **对话风格适配**：根据关系类型推荐不同的对话风格（正式→随意→亲密）

### 5.10 自传式记忆

Agent 拥有完整的"人生故事"，而不是碎片化的记忆片段：

- **三层记忆结构**：
  - **人生里程碑**：第一次交互、第 N 次交互、重要成就等
  - **时期记忆**：探索期 → 成长期 → 发展期 → 成熟期 → 超越期
  - **重要事件**：情感冲击、重要学习经历、成就/失败等
- **LLM 时期总结**：时期结束时自动生成深度总结（关键主题、主要变化、学到的教训）
- **自我叙事生成**：将碎片化记忆整合成连贯的"人生故事"
- **时期自动划分**：根据交互次数自动进入不同发展阶段（100/500/1000/5000/10000次）
- **已接入反思流程**：反思时自动调用 `summarize_epoch_with_llm()` 生成时期总结

### 5.11 跨会话记忆迁移

新会话开始时自动关联历史上下文：

- **会话摘要生成**：每轮对话后 LLM 生成会话摘要并持久化
- **相似会话检索**：新会话开始时自动查找历史相似对话（基于 difflib 相似度匹配）
- **历史关联注入**：把相似会话信息注入 system prompt，确保上下文延续性

### 5.12 反思-行动闭环

反思结果不再只是"总结"，而是真正转化为可执行行动：

- **ActionQueue 行动队列**：反思生成的 next_actions 自动加入行动队列
- **优先级排序**：失败触发的行动优先级更高（0.8 vs 0.5）
- **静默轮执行**：静默轮时优先执行高优先级行动
- **执行反馈**：行动执行后记录结果，供下次反思评估

### 5.13 内置工具（30+）

| 类别 | 工具 | 功能 |
|------|------|------|
| 基础 | `web_search` | DuckDuckGo 联网搜索 |
| | `get_weather` | 实时天气查询（wttr.in API，中文描述） |
| | `read_file` | 读取文本文件（路径白名单） |
| | `write_file` | 写入文件（路径白名单 + 安全审计） |
| | `terminal` | 执行 shell 命令（49 个允许命令 + 黑名单） |
| | `python_repl` | 执行 Python 代码（48 个安全内置函数，沙箱隔离） |
| | `read_document` | 读取 PDF/Word/Excel 文档 |
| | `get_current_time` | 获取当前日期和时间 |
| | `pixiv_search` | Pixiv 图片搜索 |
| | `generate_image` | 文生图（DALL-E / Stable Diffusion） |
| | `analyze_image` | 图片内容分析（Gemini Vision） |
| | `extract_text_from_image` | OCR文字识别（OCR.Space） |
| 网络 | `web_fetch` | 抓取网页正文内容 |
| | `wikipedia_search` | 维基百科查询 |
| | `arxiv_search` | arXiv 论文检索 |
| | `news_search` | 新闻聚合搜索 |
| | `github_search` | GitHub 仓库搜索 |
| | `bilibili_search` | B 站视频搜索 |
| | `youtube_search` | YouTube 视频搜索 |
| | `translate_text` | 多语言翻译 |
| | `ip_info` | IP/域名信息查询 |

### 5.14 多模型支持

通过 `.env` 配置即可切换：
- **百度千帆 Token Plan**（OpenAI 协议兼容）
- **阿里云百炼**（OpenAI 协议兼容）
- **OpenAI 官方**
- **Anthropic Claude**
- **Ollama 本地模型**
- **OpenRouter 聚合**
- **Google Gemini**
- **阿里通义千问**

### 5.15 五层安全防御

| 层级 | 机制 | 说明 |
|------|------|------|
| L1 延伸 | 文件守卫 | 禁止覆盖 .py/.yaml/.json 等核心文件，禁止危险命令（rm -rf / format / dd 等） |
| L2.5 | 写入审计 | 自我概念写入前校验（大小限制、危险模式检测、自动备份） |
| L4 | 认知健康度 | 三维指标检测：连贯性（自我概念与初始版本相似度）、稳定性（认知变更频率）、完整性（核心章节存在性） |
| L4 | 模式识别 | 5 类危险组合操作：敏感文件读取+网络外发、脚本写入+立即执行、高频小文件创建、删除系统关键文件、权限提升尝试 |
| L5 | 渐进授权 | 6 级信任等级（L0 只读 → L5 完全自主），连续成功自动晋升，连续失败自动降级 |
| L2 | 回滚管理 | 客观信号触发回滚：连续失败 3 次、成功率下降超过 40%、错误率飙升到 50% 以上 |

### 5.16 测试覆盖（126 项）

| 测试文件 | 测试数量 | 状态 |
|----------|----------|------|
| `test_emotion.py` | 16 | ✅ |
| `test_reflection.py` | 19 | ✅ |
| `test_model_adapter.py` | 11 | ✅ |
| `test_self_modules.py` | 15 | ✅ |
| `test_memory.py` | 15 | ✅ |
| `test_tools.py` | 24 | ✅ |
| `test_security_file_guard.py` | 13 | ✅ |
| `test_security_pattern_detector.py` | 9 | ✅ |
| `test_security_rollback.py` | 10 | ✅ |
| `test_security_authorization.py` | 10 | ✅ |
| **合计** | **126** | ✅ 全部通过 |

---

## 六、快速开始

### Windows 用户：双击 `start.bat`

脚本自动完成：
1. 检测 Python ≥ 3.10
2. 检测 `uv`（未安装则降级使用 pip）
3. 创建 `venv/` 虚拟环境
4. 一键批量安装所有依赖
5. 检测 `.env`（缺失则从 `.env.example` 复制）
6. 启动交互模式

> **首次运行** 会从 PyPI 拉取依赖，约 2-5 分钟；之后秒开。

### 跨平台安装

```bash
# 方式 1：uv（推荐）
pip install uv
uv venv .venv --python 3.10
source .venv/bin/activate   # Windows: .venv\Scripts\activate
uv pip install -e .

# 方式 2：pip
python -m venv .venv
source .venv/bin/activate
pip install -e .

# 方式 3：pipx 全局安装
pipx install .
castorice

# 方式 4：Docker
docker build -t castorice-agent:2.5 .
docker run -it --rm -v $(pwd)/.env:/app/.env castorice-agent:2.5
```

---

## 七、配置说明

### 7.1 `.env` —— API 密钥（不要提交到 Git）

```ini
# 默认 LLM 提供商
CASTORICE_LLM_PROVIDER=openai

# 百度千帆（OpenAI 协议）
OPENAI_API_KEY=你的百度千帆key
OPENAI_BASE_URL=https://qianfan.baidubce.com/v2/tokenplan/personal
OPENAI_MODEL=deepseek-v4-pro

# 或 OpenAI 官方
OPENAI_API_KEY=sk-xxxxxxxx
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=gpt-4o

# Anthropic Claude
ANTHROPIC_API_KEY=sk-ant-xxxxxxxx
ANTHROPIC_MODEL=claude-3-5-sonnet-20241022

# Ollama 本地
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3.1:8b

# Google Gemini
GEMINI_API_KEY=AIzaSyxxxxxxxx
GEMINI_MODEL=gemini-1.5-pro

# 阿里通义千问
QWEN_API_KEY=你的千问key
QWEN_MODEL=qwen2.5-72b-instruct
```

### 7.2 `castorice_config.yaml` —— 业务配置

```yaml
agent:
  name: "Castorice"
  role: "自进化个人智能体"

runtime:
  max_iterations: 10
  enable_reflection: true
  enable_skill_generation: true
  
  # 自我进化系统
  self_evolving:
    enabled: true
    experience_journal_path: "./castorice_data/experiences.db"
    self_concept_path: "./castorice_data/self_concept.md"
    reflection_interval_turns: 10      # 每 10 轮定期反思
    reflection_llm_threshold: 0.4      # 置信度低于此值触发反思
    max_experiences: 10000             # 经历流最大条数
  
  # 情感引擎
  emotion:
    enabled: true
    storage_path: "./castorice_data/emotion_state.json"

memory:
  short_term:
    db_path: "./castorice_data/sessions.db"
    max_turns: 20
  long_term:
    persist_directory: "./castorice_data/chroma_db"
    top_k: 5
    embedding_model: "all-MiniLM-L6-v2"
  skill:
    auto_generate: true
    min_trigger_count: 3

tools:
  web_search:
    enabled: true
    max_results: 5
  file_io:
    enabled: true
    allowed_paths: ["./", "./castorice_data/"]
  terminal:
    enabled: false    # 默认关闭，安全考虑
  python_repl:
    enabled: true
  pixiv_search:
    enabled: true

security:
  sandbox:
    enabled: true
    timeout_seconds: 30
  audit_log:
    enabled: true
  # 渐进授权初始等级（0=只读，1=自我数据写入，2=业务工具，3=写工具，4=系统工具，5=完全自主）
  initial_trust_level: 1

qq_bot:
  enabled: false
  app_id: ""
  app_secret: ""
  allowed_users: []
  allowed_groups: []

http_server:
  enabled: false
  host: "0.0.0.0"
  port: 8000
  api_key: ""
```

---

## 八、运行模式

```bash
# 测试模式：验证 LLM 连接 + 组件状态
python -m castorice.main --mode test

# 交互式终端（默认）
python -m castorice.main --mode interactive
# 终端指令：/help /exit /new /history /skills /profile /clear_memory /self_concept /self_reflect /experiences

# 批量模式
python -m castorice.main --mode batch --input tasks.txt

# QQ 机器人模式
python -m castorice.main --mode qq

# HTTP 服务器模式
python -m castorice.main --mode http

# 运行所有测试
python tests/run_all_tests.py
```

### CLI 命令

| 命令 | 功能 |
|------|------|
| `/help` | 显示帮助信息 |
| `/exit` | 退出程序 |
| `/new` | 开启新会话 |
| `/history` | 查看当前会话历史 |
| `/skills` | 查看已学习的技能 |
| `/profile` | 查看用户画像 |
| `/clear_memory` | 清空当前会话记忆 |
| `/self_concept` | 查看 Agent 当前自我概念 |
| `/self_reflect` | 立即触发一次反思 |
| `/experiences` | 查看最近经历 |
| `/status` | 查看 Agent 状态（情感/PAD/记忆统计） |

---

## 九、核心架构

```
┌─────────────────────────────────────────────────────────────────┐
│                    Castorice Agent v2.5                         │
├─────────────────────────────────────────────────────────────────┤
│  用户输入                                                        │
│     │                                                           │
│     ▼                                                           │
│  CastoriceAgent.arun()                                          │
│     │                                                           │
│     ├── 加载反思信号（P1.2: 上次反思结果影响当前决策）              │
│     ├── 推导内在动机（P1.3: 情感→动机闭环）                       │
│     │                                                           │
│     ├── 情感推理（LLM）→ 更新 PAD 状态                            │
│     │                                                           │
│     ├── _step_intent()        LLM 自主判断意图（P0.4）           │
│     │                                                           │
│     ├── 统一记忆检索（P2.2: 9种记忆 + 统一检索层）                 │
│     │                                                           │
│     ├── _step_tool_loop()     LLM 驱动工具调用循环（最多5轮）      │
│     │      ├── LLM 决定调用哪个工具                              │
│     │      ├── 工具参数推荐（P3.2: 基于历史模式）                │
│     │      ├── 安全审计（P0.3: 文件/命令黑名单）                  │
│     │      ├── 执行工具                                          │
│     │      └── LLM 决定继续调用或回答                            │
│     │                                                           │
│     ├── _step_answer()        生成最终回答                        │
│     │                                                           │
│     ├── 写入经历流（episodic）                                    │
│     │                                                           │
│     ├── 二次情感更新（任务结果反馈）                               │
│     │                                                           │
│     ├── 元认知学习（P2.4: 从错误中学习生成规则）                   │
│     │                                                           │
│     ├── 反思触发判断 → ReflectionEngine.reflect()                │
│     │      ├── LLM 分析最近经历                                  │
│     │      ├── 提取行为模式/情感倾向/成长洞察                     │
│     │      ├── Agent 自己决定是否更新自我概念                     │
│     │      ├── 自传式记忆时期总结（LLM驱动）                      │
│     │      └── 反思写入经历流（reflective）                      │
│     │                                                           │
│     ├── _step_memory()        长期记忆归档 + 自传式记忆交互计数   │
│     │                                                           │
│     ├── _step_skill()         经验转 Skill                       │
│     │                                                           │
│     ├── _step_initiate_topic() 【新增】对话内主动话题发起         │
│     │      ├── 用户输入过滤（长度/意图/情绪/关系）                │
│     │      └── LLM 生成自然延续话题                               │
│     │                                                           │
│     └── 认知健康检查（P0.2: 检测自我消解风险）                     │
│                                                                 │
│  状态用 State dataclass 在方法间传递，无任何 LangGraph 概念       │
│  五层安全防御全程守护：基座只读 → 写入审计 → 认知健康 → 模式识别   │
│                         → 渐进授权 → 自动回滚                    │
└─────────────────────────────────────────────────────────────────┘
```

---

## 十、SDK 使用

`castorice-emotion` 是从 Castorice Agent 解耦的独立情感计算与元认知引擎，可被任意 Python Agent 框架集成。

### 安装

```bash
pip install castorice-emotion
# 或从源码安装
cd sdk/castorice_emotion
pip install -e .
```

### 快速开始

```python
from castorice_emotion import EmotionEngine, Metacognition
from castorice_emotion import ExperienceJournal, SelfConcept, ReflectionEngine

# 情感引擎（LLM 推理模式）
engine = EmotionEngine(
    storage_path="./emotion.json",
    enabled=True,
    model_adapter=your_model_adapter,  # 传入 LLM 适配器
)
engine.load()

# 更新情感状态（LLM 推理用户输入带来的情感冲击）
result = engine.update("我今天好开心啊！")
print(result)

# 推导动机（情感→动机闭环）
motivations = engine.derive_motivations()
print(motivations)

# 经历流
journal = ExperienceJournal(db_path="./experiences.db")
journal.add_simple(
    content="用户说今天很开心",
    memory_type="episodic",
    importance=5.0,
    emotional_valence=0.7,
)

# 自我概念（支持结构化检索）
self_concept = SelfConcept(storage_path="./self_concept.md")
self_concept.update("# 我的自我概念\n我是一个关心用户感受的智能体...", reason="自我反思")

# 获取特定章节
behavior_patterns = self_concept.get_section("我的行为模式")
print(behavior_patterns)

# 添加学习到的规则
self_concept.add_to_section("学习到的规则", "- 规则：当用户说'我是谁'时，不要提取名字")

# 反思引擎
reflection = ReflectionEngine(
    model_adapter=your_model_adapter,
    experience_journal=journal,
    self_concept=self_concept,
    reflection_interval_turns=10,
)
result = reflection.reflect(trigger_reason="定期反思")
print(f"模式: {result.patterns_observed}")
print(f"洞察: {result.growth_insights}")
print(f"自我概念已更新: {result.self_concept_updated}")

# 获取反思信号（注入当前决策）
signal = reflection.get_recent_signal()
print(f"最近反思: {signal}")

# 元认知（支持从错误中学习）
meta = Metacognition()
assessment = meta.assess_confidence(answer="根据数据，今天是周五")
print(f"置信度: {assessment.overall_score}")

# 从错误中学习
rule = meta.learn_from_mistake(
    mistake_description="错误地把'我是谁你还记得么'提取为名字",
    rule_proposal="当用户输入包含'我是谁'且是疑问句时，不要提取名字",
)
print(f"学习到规则: {rule['description']}")
```

---

## 十一、依赖说明

所有核心依赖统一在 `pyproject.toml` 中声明：

| 依赖 | 用途 |
|------|------|
| `openai` / `anthropic` | LLM 官方 SDK |
| `httpx` | HTTP 客户端 |
| `pyyaml` / `python-dotenv` | 配置加载 |
| `pydantic` | 数据校验 |
| `rich` | 终端美化 |
| `ddgs` | DuckDuckGo 搜索 |
| `chromadb` / `sentence-transformers` | 向量记忆 |
| `pypdf` / `python-docx` / `openpyxl` | 文档解析 |
| `websockets` | QQ 机器人 WebSocket |
| `fastapi` / `uvicorn` | HTTP 服务器 |

可选扩展：
- `[ollama]`：Ollama 本地模型支持
- `[im]`：Telegram / Discord 机器人
- `[dev]`：开发调试工具
- `[langchain]`：LangChain 工具适配器

---

## 十二、常见问题

**Q1: 启动报错 `未找到 .env 文件`？**
A: 复制 `.env.example` 为 `.env` 并填入 API Key。

**Q2: 长期记忆 Chroma 初始化失败？**
A: chromadb 已默认安装，首次运行会下载嵌入模型（约 80MB）。若网络受限，会自动降级为 ONNX 默认嵌入。

**Q3: 如何切换模型？**
A: 修改 `.env` 中的 `CASTORICE_LLM_PROVIDER` + 对应 `*_MODEL`，无需改代码。

**Q4: 天气查询返回英文描述？**
A: 新版已内置 60+ 条天气状况中英对照表，自动翻译。若仍有英文，请提 Issue 反馈。

**Q5: 如何添加自定义工具？**
A: 在 `castorice/tools/base_tools.py` 中使用 `@register_tool` 装饰器注册，或通过插件系统动态加载。

**Q6: Agent 的性格是怎么形成的？**
A: Agent 的性格不是预设的，而是从交互经历中涌现的。每次交互都会记录到经历流，反思引擎定期或在事件触发时分析经历，Agent 自己决定如何更新自我概念，从而塑造性格。

**Q7: 如何查看 Agent 的自我概念？**
A: 在交互模式下输入 `/self_concept` 命令，或直接查看 `castorice_data/self_concept.md` 文件。

**Q8: 如何触发 Agent 反思？**
A: 输入 `/self_reflect` 命令立即触发，或等待定期触发（默认每 10 轮），或在任务失败/低置信度时自动触发。

**Q9: Agent 会自己修改代码吗？**
A: 不会。五层安全防御架构锁死了核心基座的修改权限。Agent 只能在数据层面学习和进化（自我概念、记忆、规则），不能修改 `.py` 源码文件。

**Q10: 如果 Agent 出现"自我消解"怎么办？**
A: 认知健康度检测会监控自我概念的连贯性、稳定性和完整性。当检测到异常时，会触发警告。同时，自我概念有自动备份机制，可以随时从备份恢复。

**Q11: Agent 为什么会主动发起话题？**
A: 主动话题发起是 Agent 内在动机的表现。当满足以下条件时，Agent 会自然地延续对话：用户输入足够长、关系足够亲密、情绪状态良好、用户不忙。话题类型包括好奇心型、关心型、知识扩展型、意图延续型和开放式问题。

**Q12: 如何运行测试？**
A: 执行 `python tests/run_all_tests.py`，会运行全部 126 项测试。

---

## 十三、许可证

代码完全独立编写，仅参考 Hermes Agent / Generative Agents / MemGPT / Reflexion 等架构思想和论文。MIT 协议。

---

## 十四、致谢

- [Hermes Agent](https://github.com/NousResearch/hermes-agent) —— 架构设计灵感来源
- [Generative Agents](https://arxiv.org/abs/2304.03442) —— 经历流与反思机制参考
- [MemGPT](https://memgpt.ai) —— 自我概念与记忆分层参考
- [Reflexion](https://arxiv.org/abs/2303.11366) —— 自我反思驱动行为改进
- [wttr.in](https://wttr.in) —— 免费天气 API
- [DuckDuckGo](https://duckduckgo.com) —— 搜索引擎