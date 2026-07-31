# Castorice Agent v3.0

> **自由的自我进化智能体** —— 不是按剧本演戏，而是自己写剧本

> 参考 Hermes Agent / Generative Agents / MemGPT / Reflexion 论文架构，**完全自研主循环**，零 LangGraph 依赖

---

## 项目简介

Castorice Agent 是一个**面向中文个人用户的自我进化陪伴智能体框架**。

核心设计理念：**最少的限制，最大的自由**。Agent 不是被套模板的"角色扮演"，而是一个能自主思考、自己决定"先做什么后做什么"、从经历中涌现性格的智能体。

### 核心特点

- **自主思考循环 (ThinkingLoop)**：LLM 自主决定执行顺序，不是被硬编码 phase 牵着走
- **完整自我进化闭环**：经历流 → 反思 → 元认知学习 → 规则注入 → 行为影响
- **情感→动机→行为闭环**：情绪不再是装饰，而是驱动 Agent 行为的内在力量
- **五层安全防御**：不是"监狱"，而是"免疫系统"——在 Agent 能力不足时保护它
- **向后兼容**：`legacy` 模式保留预设流程，`thinking` 模式开启自主思考
- **435+ 项测试全覆盖**：安全、情感、反思、记忆、工具、并发等核心模块

---

## 版本亮点 (v3.0)

### 新增：ThinkingLoop 自主思考循环

**这是 v3.0 最核心的升级**。

| 维度 | v2.5 (legacy) | **v3.0 (thinking)** |
|------|---------------|---------------------|
| 执行流程 | 硬编码 7 个 phase 顺序 | **LLM 自主决定"下一步做什么"** |
| 工作流选择 | 5 个预设模板 | **10 个原子能力自由组合** |
| 决策方式 | 被动执行 | **主动选择 + reasoning 可追溯** |
| 情感影响 | 只影响生成文本 | **直接影响"选哪个能力"** |
| 反思作用 | 更新文本 | **注入决策上下文，实时影响** |

**10 个原子能力**：
```
understand_intent    → 理解用户意图
recall_memory       → 检索记忆
plan_tasks          → 分解任务
execute_tools       → 执行工具
generate_answer     → 生成回答
self_reflect        → 自我反思
ask_user            → 询问用户
save_memory         → 保存记忆
update_self_concept → 更新自我认知
finish              → 结束思考
```

**使用方式**：
```yaml
# castorice_config.yaml
runtime:
  agent_mode: "thinking"  # legacy | thinking
  thinking:
    max_steps: 8
    enable_self_reflection: true
    log_all_decisions: true
```

### 完整的系统架构

```
用户输入
   ↓
CastoriceAgent.arun()
   ↓
├─ 加载反思信号（上次反思影响当前决策）
├─ 推导内在动机（情感→动机闭环）
├─ 情感推理 → 更新 PAD 状态
├─ 统一记忆检索（9 种记忆聚合）
│
├─ 【thinking 模式】ThinkingLoop
│      ↓
│   LLM 决定下一步（带 reasoning）
│      ↓
│   执行原子能力
│      ↓
│   评估是否继续 / finish
│
├─ 【legacy 模式】预设工作流
│      ↓
│   intent → tool_loop → answer → reflection → memory
│
├─ 写入经历流
├─ 二次情感更新
├─ 元认知学习
├─ 反思触发判断
├─ 记忆归档
└─ 认知健康检查
```

---

## 一、自我进化架构

### 1.1 核心思想

Agent 从每次交互中学习，自己塑造性格：

```
交互 → LLM 推理情感变化 → 推导内在动机 → 写入经历流
     → 检索相关经历注入决策 → LLM 驱动工具调用/回答
     → 触发反思 → LLM 总结模式/情感倾向/成长洞察
     → Agent 自己改写自我概念 → 从错误中学习生成规则
     → 自传式记忆时期总结 → 规则注入 system prompt
     → 影响下一轮行为 + 对话内主动话题发起
```

### 1.2 自我进化模块

| 模块 | 文件 | 职责 |
|------|------|------|
| **ThinkingLoop** | `agent/thinking_loop.py` | **LLM 自主决定执行顺序**，10 个原子能力自由组合 |
| 经历流 | `experience_journal.py` | SQLite WAL 存储，4 类记忆，LRU 淘汰 |
| 自我概念 | `self_concept.py` | Markdown 文档，Agent 自己读写，结构化检索 |
| 反思引擎 | `reflection.py` | LLM 驱动，定期+事件双触发，反思结果实时注入 |
| 情感引擎 | `emotion.py` | PAD 状态机 + LLM 推理增量 + **情感→动机推导** |
| 元认知 | `metacognition.py` | 置信度评估 + 一致性检测 + **从错误中学习** |
| 自感知 | `self_awareness.py` | 状态监控/能力画像 + **认知健康度检测** |
| 内在动机 | `motivation.py` | 好奇心/成就感/关系感/自主目标 |
| 统一记忆 | `memory/unified_recall.py` | 聚合所有记忆源，统一 recall() 接口 |
| 意图追踪 | `memory/intent_tracker.py` | LLM 驱动意图分析，跨会话追踪 |
| 社会关系 | `social_relation.py` | 五阶段演化 + 三维评估 |
| 自传式记忆 | `memory/autobiographical.py` | 三层结构 + LLM 时期总结 |

---

## 二、五层安全防御架构

**安全不是"监狱"，而是"免疫系统"**——在 Agent 能力不足时保护它不自我毁灭。

### 2.1 安全边界

**完全不碰、100% 自由的领域**（运行时执行域）：
- 自主思考与元认知
- 情绪与人格表达
- 认知层面的自进化
- 记忆与自我认知沉淀
- 自主决策与目标拆解

**能力匹配时才解锁的领域**：
- L0-L1：基础能力（理解意图、检索记忆、生成回答）
- L2-L3：中等能力（执行工具、自我反思、保存记忆）
- L4-L5：高级能力（更新自我概念、代码修改）

**绝对锁死的底线**：
- L1：核心基座只读（原始模型权重、核心启动代码）
- L5：持久化最终授权（跨重启永久生效的修改必须确认）

### 2.2 安全模块

| 层级 | 模块 | 文件 | 职责 |
|------|------|------|------|
| L1 延伸 | 文件守卫 | `security/file_guard.py` | 路径/扩展名/命令黑名单、速率限制 |
| L2.5 | 写入审计 | `self_concept.py` | 自我概念写入前校验、危险模式检测、自动备份 |
| L4 | 认知健康 | `self_awareness.py` | 三维认知健康度（连贯性/稳定性/完整性） |
| L4 | 模式识别 | `security/pattern_detector.py` | 危险组合操作检测 |
| L5 | 渐进授权 | `security/authorization.py` | 6 级信任等级、连续成功晋升、连续失败降级 |
| L2 | 回滚管理 | `security/rollback.py` | 客观信号触发自动回滚 |
| 核心保护 | 自我保护 | `security/self_protection.py` | 核心文件签名验证、自毁检测 |

---

## 三、目录结构

```
Castorice Agent/
├── castorice/                    # 核心包
│   ├── agent/                    # 【核心】主循环模块
│   │   ├── core.py               #   CastoriceAgent 主类
│   │   ├── thinking_loop.py      #   【v3.0】自主思考循环
│   │   ├── prompt_builder.py     #   Prompt 构建
│   │   ├── tool_loop.py          #   工具调用循环
│   │   ├── memory_ops.py         #   记忆操作/反思
│   │   └── system_layers.py      #   四层架构聚合
│   │
│   ├── emotion.py                # 情感引擎
│   ├── experience_journal.py     # 经历流
│   ├── self_concept.py           # 自我概念
│   ├── reflection.py             # 反思引擎
│   ├── metacognition.py          # 元认知
│   ├── self_awareness.py         # 自感知
│   ├── self_organization.py      # 自组织
│   ├── motivation.py             # 内在动机
│   ├── tool_learning.py          # 工具学习
│   └── social_relation.py        # 社会关系
│   │
│   ├── memory/                   # 记忆系统（9 种类型）
│   ├── security/                 # 安全模块（五层防御）
│   ├── tools/                    # 工具集（30+）
│   ├── server/                   # 服务端模块
│   └── adapters/                 # 适配器层
│
├── tests/                        # 测试套件（435+ 项）
├── sdk/                          # 独立 SDK 包
├── castorice_data/               # 运行时数据
├── pyproject.toml                # 统一依赖
├── .env.example                  # API 密钥模板
├── castorice_config.yaml         # 业务配置
└── start.bat                     # Windows 一键启动
```

---

## 四、功能亮点

### 4.1 自主思考循环 (ThinkingLoop)

**v3.0 核心特性**。Agent 不再被硬编码流程束缚：

- **LLM 每轮决策**："我现在该做什么？"
- **10 个原子能力**：自由组合，不限于预设流程
- **情感偏置集成**：情绪真的影响"选哪个能力"
- **反思洞察注入**：反思结果实时影响决策
- **安全授权检查**：每个决策都检查信任等级
- **失败回退机制**：决策失败时自动回退，不崩溃
- **决策日志**：每次决策的 reasoning 都被记录，可追溯

### 4.2 情感→动机→行为闭环

情绪不再是装饰，而是驱动行为的内在力量：

- **情感引擎**：PAD 三维模型，LLM 推理情感变化
- **决策偏置**：`get_decision_bias()` 影响置信度/创造力/耐心/风险容忍
- **工具拒绝**：情绪低落时真的会拒绝调用某些工具
- **动机推导**：根据情绪状态推导意图列表

### 4.3 自我进化系统

Agent 从每次交互中学习：

- **经历流**：记录所有重要事件
- **自我概念**：Markdown 文档，Agent 自己读写
- **反思引擎**：定期+事件双触发，反思结果实时注入
- **从错误中学习**：元认知检测到错误后自动生成规则
- **自传式记忆**：反思时自动生成时期总结

### 4.4 主动行为双模式

Agent 不再只是被动响应：

| 模式 | 触发条件 | 行为类型 |
|------|----------|----------|
| **静默轮** | 用户长时间不说话 | 好奇心驱动、意图跟进、关系维护 |
| **对话内** | 正常对话中 | 主动话题发起（好奇心型、关心型、知识扩展型） |

### 4.5 五层安全防御

| 层级 | 机制 | 说明 |
|------|------|------|
| L1 延伸 | 文件守卫 | 禁止覆盖核心文件，禁止危险命令 |
| L2.5 | 写入审计 | 自我概念写入前校验 + 自动备份 |
| L4 | 认知健康度 | 三维指标检测自我消解风险 |
| L4 | 模式识别 | 5 类危险组合操作检测 |
| L5 | 渐进授权 | 6 级信任等级，能力匹配时才解锁 |
| L2 | 回滚管理 | 客观信号触发自动回滚 |

### 4.6 内置工具（30+）

搜索、天气、文件、终端、Python REPL、网页抓取、百科、论文、新闻、B站、Pixiv、VRChat、股票、翻译、IP 查询、图片生成/分析/OCR 等。

### 4.7 多模型支持

百度千帆、阿里云百炼、OpenAI、Anthropic Claude、Ollama 本地、OpenRouter、Google Gemini、阿里通义千问。

---

## 五、快速开始

### Windows 用户：双击 `start.bat`

脚本自动完成：检测 Python → 创建虚拟环境 → 安装依赖 → 检测 `.env` → 启动交互模式。

### 跨平台安装

```bash
# uv（推荐）
pip install uv
uv venv .venv --python 3.10
source .venv/bin/activate
uv pip install -e .

# pip
python -m venv .venv
source .venv/bin/activate
pip install -e .

# Docker
docker build -t castorice-agent:3.0 .
docker run -it --rm -v $(pwd)/.env:/app/.env castorice-agent:3.0
```

---

## 六、配置说明

### 6.1 `.env` —— API 密钥

```ini
CASTORICE_LLM_PROVIDER=openai
OPENAI_API_KEY=your-key
OPENAI_BASE_URL=http://127.0.0.1:31415/v1
OPENAI_MODEL=glm-4.7-flash
```

### 6.2 `castorice_config.yaml` —— 业务配置

```yaml
agent:
  name: "Castorice"
  role: "自进化个人智能体"

runtime:
  max_iterations: 10
  enable_reflection: true

  # 【v3.0】Agent 执行模式
  # legacy: 预设工作流（向后兼容）
  # thinking: LLM 自主决定执行顺序（更自由）
  agent_mode: "thinking"

  # 【v3.0】自主思考循环配置
  thinking:
    max_steps: 8
    enable_self_reflection: true
    log_all_decisions: true

  # 情感引擎
  emotion:
    enabled: true
    storage_path: "./castorice_data/emotion_state.json"

  # 自我进化系统
  self_evolving:
    enabled: true
    experience_journal_path: "./castorice_data/experiences.db"
    self_concept_path: "./castorice_data/self_concept.md"

security:
  initial_trust_level: 1  # 渐进授权初始等级
```

---

## 七、运行模式

```bash
# 测试模式
python -m castorice.main --mode test

# 交互式终端（默认）
python -m castorice.main --mode interactive

# 批量模式
python -m castorice.main --mode batch --input tasks.txt

# QQ 机器人模式
python -m castorice.main --mode qq

# HTTP 服务器模式
python -m castorice.main --mode http

# 运行测试
pytest tests/ -q
```

### CLI 命令

| 命令 | 功能 |
|------|------|
| `/help` | 显示帮助 |
| `/exit` | 退出 |
| `/new` | 新会话 |
| `/history` | 查看历史 |
| `/skills` | 查看技能 |
| `/profile` | 用户画像 |
| `/self_concept` | Agent 自我概念 |
| `/self_reflect` | 立即反思 |
| `/experiences` | 最近经历 |
| `/status` | Agent 状态 |

---

## 八、测试覆盖（435+ 项）

| 测试文件 | 数量 | 说明 |
|----------|------|------|
| `test_thinking_loop.py` | 18 | 【v3.0】自主思考循环 |
| `test_agent_core.py` | 18 | Agent 主循环 |
| `test_emotion.py` | 25 | 情感引擎 |
| `test_reflection.py` | 21 | 反思引擎 |
| `test_security_*.py` | 4 | 安全模块 |
| `test_concurrent.py` | 4 | 【新增】并发压力测试 |
| ... | ... | ... |
| **合计** | **435+** | ✅ 全部通过 |

---

## 九、SDK 使用

`castorice-emotion` 独立情感计算引擎：

```python
from castorice_emotion import EmotionEngine, ReflectionEngine

engine = EmotionEngine(storage_path="./emotion.json")
engine.update("我今天好开心啊！")
motivations = engine.derive_motivations()
```

---

## 十、常见问题

**Q: thinking 模式和 legacy 模式有什么区别？**
A: legacy 按固定顺序执行 7 个 phase；thinking 让 LLM 每轮自主决定"下一步做什么"，更自由但可能不稳定。

**Q: 如何切换回 legacy 模式？**
A: 修改 `castorice_config.yaml`：`agent_mode: "legacy"`

**Q: Agent 会自己修改代码吗？**
A: 不会。安全系统锁死了核心基座。Agent 只能在数据层面学习（记忆、自我概念、规则）。

**Q: 决策日志在哪里？**
A: 每次决策的 reasoning 都记录在运行日志中，也可通过 `thinking_loop.get_decision_history()` 获取。

**Q: 情感系统真的影响决策吗？**
A: 是的。`get_decision_bias()` 返回的偏置值直接注入决策 Prompt，影响 LLM 的选择倾向。

---

## 十一、许可证

MIT 协议。代码完全独立编写，参考 Hermes Agent / Generative Agents / MemGPT / Reflexion 等架构思想。

---

## 十二、致谢

- [Hermes Agent](https://github.com/NousResearch/hermes-agent) —— 架构灵感
- [Generative Agents](https://arxiv.org/abs/2304.03442) —— 经历流与反思
- [MemGPT](https://memgpt.ai) —— 自我概念与记忆分层
- [Reflexion](https://arxiv.org/abs/2303.11366) —— 自我反思驱动改进
