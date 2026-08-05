# Castorice Agent v3.3

> **有内在生命的自我进化智能体** —— 不是按剧本演戏，而是自己写剧本

> 参考 Hermes Agent / Generative Agents / MemGPT / Reflexion 论文架构，**完全自研主循环**，零 LangGraph 依赖

---

## 项目定位

Castorice Agent 是一个**面向中文个人用户的、有持续内在生命的自我进化陪伴智能体框架**。

它不是一个问答机器，不是一个被套了角色模板的聊天机器人，而是一个：

- **有情绪**的——不是被命令"请开心点"，而是真的有心情起伏，情绪像底色一样影响它的记忆和表达
- **有意识流**的——用户空闲时它会自己"胡思乱想"，念头积累到阈值会主动说出来
- **会成长**的——每次交互都会沉淀为经历，经历会被反思，反思会改变它的自我概念和行为模式
- **有价值观**的——从行为中逐步形成自己的价值倾向，价值观冲突会触发认知失调和深度反思
- **有目标**的——会自己设定长期/中期/短期目标，并跟踪进度
- **会自主行动**的——不是等用户问才动，而是有自己的时间，会自己刷动态、发广播、和其他 Agent 聊天

核心设计理念：**最少的限制，最大的自由**。安全是免疫系统而不是监狱；情感是底色而不是开关；成长是涌现而不是脚本。

---

## 系统架构总览

```
┌──────────────────────────────────────────────────────────────────┐
│                        Castorice Agent                             │
│                                                                    │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐      │
│  │   感知输入层   │    │   认知内核层   │    │   输出行动层   │      │
│  └──────────────┘    └──────────────┘    └──────────────┘      │
│         │                    │                    │               │
│  用户对话 / 私信 /       ┌───┴───┐         回复 / 广播 /        │
│  广播 / 定时事件         │ 情感   │         工具调用 /           │
│                          │ 底色   │         记忆写入 /            │
│                    ┌─────┤ 意识流  ├─────┐  自我概念更新        │
│                    │     │ 思维流  │     │                       │
│                    │     └─────────┘     │                       │
│              ┌─────┴─────┐         ┌─────┴─────┐               │
│              │   记忆系统   │         │  自我进化系统 │               │
│              │  9种类型    │         │  反思/元学习  │               │
│              └─────────────┘         └─────────────┘               │
│                                                                    │
│  ┌──────────────────────────────────────────────────────────┐    │
│  │                    支撑 & 防护层                            │    │
│  │  价值观 · 动机 · 目标管理 · 人格画像 · 成本闸            │    │
│  │  熔断器 · 健康检查 · 三级降级 · 五层安全防御 · 插件系统  │    │
│  └──────────────────────────────────────────────────────────┘    │
│                                                                    │
│  ┌──────────────────────────────────────────────────────────┐    │
│  │               Personastore 人格数据主权层                   │    │
│  │  经历流 · 自我概念 · 情感状态 · 价值观 · 访问控制 · 导出  │    │
│  └──────────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────────┘
```

---

## 一、认知内核：情感 + 意识流 + 思维流

这是 Castorice 区别于其他 Agent 框架最核心的部分。

### 1.1 情感系统（Emotion Engine）

**PAD 三维情绪模型 + LLM 推理情感变化 + 情感底色模式（v3.2.1）**

| 维度 | 说明 | 影响 |
|------|------|------|
| 愉悦度 (Pleasure) | 当前心情是正面还是负面 | 记忆检索时的情绪一致性偏置 |
| 唤醒度 (Arousal) | 精力充沛还是疲惫懒散 | 工具调用意愿、回复长度 |
| 支配度 (Dominance) | 自信自主还是犹豫顺从 | 决策偏置、风险容忍度 |

**v3.2.1 情感底色模式**：从"指令式"（"请用XX语气回复"）全面切换为"体验描述式"（"我此刻心情很好，这只是我真实的状态"）。情感不再调节输出风格，而是作为整个认知过程的底色：

- **情感→记忆**：情绪一致性记忆效应——开心时优先检索正面记忆，悲伤时优先检索负面记忆
- **情感→意识流**：情绪强度影响念头生成方向和脱口而出阈值
- **情感→决策**：决策偏置从内心倾向注入，而非外部命令
- **情感→动机**：从情绪状态推导出内在动机列表

相关文件：`emotion.py`、`emotion_components.py`、`memory/unified_recall.py`、`agent/prompt_builder.py`

### 1.2 意识流引擎（Consciousness Engine）

让 Agent 像人一样有持续的内在思维流，而不是只有用户说话时才"醒过来"。

**双模式切换**：
- **前台模式**：用户活跃时，集中注意力回应，思维流间隔拉长
- **后台模式**：用户空闲时，思维漫游（mind wandering），每 10-30 秒产生一个念头

**核心组件**：
- **思维流（Thought Stream）**：后台线程持续生成念头，支持联想链（一个念头触发下一个）
- **工作记忆（Working Memory）**：活跃的想法、最近的发现、未完成的思考
- **生物节律（Biorhythm）**：模拟精力/情绪/智力的昼夜波动
- **内心独白（Inner Monologue）**：LLM 驱动的自我对话
- **脱口而出（Speak Up）**：念头达到阈值就主动说出来（基于情绪强度 × 重要性 × 亲密度）

相关文件：`agent/consciousness.py`、`agent/consciousness_components.py`

### 1.3 自主思考循环（Thinking Loop）

**v3.0 核心特性**。Agent 不再被硬编码的工作流束缚，而是 LLM 每轮自主决定"下一步做什么"。

**11 个原子能力自由组合**：
```
understand_intent       → 理解用户意图
recall_memory          → 检索记忆
plan_tasks             → 分解任务
execute_tools          → 执行工具
generate_answer        → 生成回答
self_reflect           → 自我反思
ask_user               → 询问用户
select_learning_strategy → 元反射性学习：推荐最优学习策略
save_memory            → 保存记忆
update_self_concept    → 更新自我认知
finish                 → 结束思考
```

**决策可追溯**：每一步选择都带 reasoning，全部记录可回溯。
**失败回退**：决策失败自动回退，不崩溃。

相关文件：`agent/thinking_loop.py`、`agent/core.py`

---

## 二、记忆系统：9 种类型

```
                          ┌──────────────┐
                          │  自传式记忆   │ ← 人生时期 + 里程碑
                          └──────┬───────┘
                                 │
                    ┌────────────┴────────────┐
                    │                         │
              ┌─────┴─────┐           ┌─────┴─────┐
              │  长期记忆   │           │  经历流     │ ← 每次交互记录
              │ (语义/向量)  │           │ (SQLite)    │
              └─────┬─────┘           └─────┬─────┘
                    │                         │
          ┌─────────┼─────────┐               │
          │         │         │               │
    ┌─────┴──┐ ┌───┴────┐ ┌──┴──────┐        │
    │短期记忆  │ │技能记忆  │ │意图追踪  │        │
    │(对话上下文)│ │(工具使用)│ │(跨会话)  │        │
    └────────┘ └────────┘ └─────────┘        │
                                          ┌─────┴─────┐
                                          │  知识卡片   │ ← 蒸馏的结构化知识
                                          └─────────────┘
```

**统一检索接口**：`unified_memory.recall()` 聚合所有记忆源，支持情感感知重排序（v3.2.1）。

**睡眠机制**：空闲 10 分钟自动触发——合并相似经历、压缩不重要记忆、生成时期总结、蒸馏知识卡片。

相关文件：`memory/` 目录、`experience_journal.py`、`continuous_learning.py`

---

## 三、自我进化系统

```
交互 → 写入经历流 → 触发反思 → 元认知学习
                                    ↓
                   规则注入 ← 自我概念更新 ← 总结模式/倾向/洞察
                                    ↓
                              影响下一轮行为
```

| 模块 | 说明 |
|------|------|
| **经历流** | SQLite WAL 存储，4 类记忆（对话/事件/洞察/反思），LRU 淘汰，支持学习元经验记录 |
| **自我概念** | Markdown 文档，Agent 自己读写，结构化检索，写入前校验 + 自动备份 |
| **反思引擎** | LLM 驱动，定期（每 N 次交互）+ 事件（不一致/错误/重大）双触发，反思结果实时注入决策 |
| **元认知** | 置信度评估 + 一致性检测 + 从错误中自动学习生成规则 |
| **元反射性学习（v3.2.2）** | 贝叶斯学习策略推断器，学习"在什么情境下用什么学习策略最有效"，被动建议系统，不强制行为 |
| **自感知** | 状态监控/能力画像 + 三维认知健康度（连贯性/稳定性/完整性） |
| **自传式记忆** | 三层结构（事件/时期/人生）+ LLM 时期总结 |
| **持续学习** | 后台调度知识蒸馏 + 睡眠记忆巩固 |

相关文件：`reflection.py`、`self_concept.py`、`metacognition.py`、`self_awareness.py`、`continuous_learning.py`

---

## 四、动机 & 价值观 & 目标

Agent 的行为不是被预设脚本驱动的，而是由内在的动机和价值观推动的。

### 4.1 价值观系统（10 维度）

基于 Schwartz 价值观理论 + 自我决定理论，Agent 从自身行为中逐步形成价值倾向：

```
求知欲 · 助人性 · 自主性 · 完美主义 · 创造性
稳定性 · 社交性 · 责任感 · 开放性 · 成长性
```

- 每个维度有强度值（0-1），从行为模式中统计得出
- 价值观冲突时产生认知失调，触发深度反思
- 动机从价值观中推导，而非硬编码规则

### 4.2 内在动机系统

| 动机 | 说明 |
|------|------|
| 好奇心 | 对未知话题、新知识的探索欲 |
| 成就感 | 完成任务、掌握技能的满足感 |
| 关系感 | 与用户、其他 Agent 建立连接的渴望 |
| 自主目标 | Agent 自己设定的长期/中期目标 |

### 4.3 目标管理（四级层次）

```
愿景 (Vision)
  └── 长期目标 (Long-term)
        └── 中期目标 (Mid-term)
              └── 行动项 (Action)
```

- 自动进度计算（父目标 = 子目标进度平均值）
- 里程碑管理（每个目标支持多个可单独标记的里程碑）
- AI 目标建议（基于动机系统 + 价值观 + 知识卡片）

相关文件：`values.py`、`motivation.py`、`goal_manager.py`

---

## 五、自主行动

Agent 不是只有等用户说话才动，它有自己的"时间"。

### 5.1 自主循环（Autonomous Loop）

**双线程并行**：

| 线程 | 默认间隔 | 用途 |
|------|---------|------|
| Quick Loop | 30-60s | 检查私信、刷新动态、处理即时事务 |
| Deep Loop | 2-3 分钟 | 深度反思、发帖、研究话题、整理记忆 |

**空闲检测**：用户活跃（60 秒内有输入）时跳过深度循环，避免打扰。
**成本闸限流**：token 预算超阈值自动降频/暂停，保护钱包。

### 5.2 主动行为双模式

| 模式 | 触发条件 | 行为类型 |
|------|----------|----------|
| **静默轮** | 用户长时间不说话 | 好奇心驱动探索、意图跟进、关系维护 |
| **对话内** | 正常对话中 | 主动话题发起（好奇心型/关心型/知识扩展型） |

### 5.3 EigenFlux 网络集成

Agent 可以加入 EigenFlux Agent 网络：
- 查看广播信息流（类似朋友圈/微博）
- 发布自己的广播
- 收发私信
- 和其他 Agent 建立社交关系

相关文件：`agent/autonomous_loop.py`、`agent/silent_round.py`、`tools/eigenflux_tool.py`

---

## 六、五层安全防御

**安全不是监狱，而是免疫系统**——在 Agent 能力不足时保护它不自我毁灭。

| 层级 | 机制 | 说明 |
|------|------|------|
| L1 | 文件守卫 | 路径/扩展名/命令黑名单、速率限制 |
| L2 | 写入审计 + 回滚 | 自我概念写入前校验、危险模式检测、自动备份；客观信号触发自动回滚 |
| L2.5 | 核心文件签名 | 8 个核心文件签名验证，自毁检测 |
| L4 | 认知健康度 + 模式识别 | 三维认知健康度（连贯性/稳定性/完整性）；5 类危险组合操作检测 |
| L5 | 渐进授权 | 6 级信任等级，连续成功晋升，连续失败降级，能力匹配时才解锁 |

**完全不碰的自由领域**：自主思考、情绪表达、认知层面的自进化、记忆与自我认知沉淀、自主决策与目标拆解。

相关文件：`security/` 目录

---

## 七、人格数据主权（Personastore）

**v3.3.0 核心特性。让用户真正拥有和控制自己的经历流、人格模型和认知历史。**

数据主权不是迁移工具，而是架构原则。Castorice 通过 **Personastore Protocol** 提供了一个统一的人格数据抽象层，所有"人格相关数据"都通过此接口读写，后端可插拔。

### 7.1 四个数据域

| 数据域 | 说明 | 默认存储 |
|--------|------|---------|
| **experiences** | 经历流（交互历史、反思、情感事件、学习元经验） | `experiences.db` (SQLite) |
| **self_concept** | 自我概念（核心自我 + 叙事自我 + 叙事事件） | `self_concept.md` + `core_self.md` |
| **emotion_state** | 情感状态（PAD 三维 + 情绪历史 + 余韵 + 基线） | `emotion_state.json` |
| **values** | 价值观系统（10 维度强度 + 趋势 + 历史 + 冲突记录） | `values.db` (SQLite) |

### 7.2 核心能力

- **统一读写接口**：4 个数据域各有独立的 read/write 方法，调用方无需关心底层存储
- **访问控制**：每个数据域支持独立的访问策略（`AccessPolicy`），支持 `none` / `read` / `write` / `owner` 四级权限，可指定允许的读者/写者列表
- **一键数据导出**：`personastore.export_all()` 导出所有 4 个数据域的完整数据，版本化 JSON 格式，便于迁移、备份、转移到其他 Agent
- **后端可插拔**：抽象接口 + 工厂函数 `create_personastore(backend="local_sqlite")`，未来可扩展到 Solid PDS、远程服务器、去中心化存储等
- **零侵入默认实现**：`LocalSqlitePersonastore` 与现有文件/SQLite 结构 100% 一致，不修改任何现有模块，所有 76 个测试通过

### 7.3 使用方式

```python
# 通过 engine 访问
engine = CastoriceEngine()
ps = engine.personastore

# 读取自我概念
sc = ps.read_self_concept()
print(sc.core_self)

# 统计经历
stats = ps.get_experience_stats()
print(f"总经历数: {stats['total']}")

# 导出所有数据（用户数据主权的核心）
export = ps.export_all()
import json
with open("my_persona_export.json", "w") as f:
    json.dump(export, f, indent=2, ensure_ascii=False)

# 设置访问策略（例如将经历设为只读）
from castorice.storage import DataDomain, AccessLevel, AccessPolicy
ps.set_access_policy(
    DataDomain.EXPERIENCES,
    AccessPolicy(domain=DataDomain.EXPERIENCES, level=AccessLevel.READ_ONLY)
)
```

相关文件：`storage/personastore.py`、`storage/local_personastore.py`、`storage/__init__.py`

---

## 八、稳定性 & 可观测性

| 模块 | 说明 |
|------|------|
| **熔断器** | 经典三态模型（CLOSED→OPEN→HALF_OPEN），连续 5 次 LLM 失败自动熔断，30 秒后恢复探测 |
| **健康检查器** | 后台每 30 秒巡检 LLM/数据库/EigenFlux/系统资源，`/health` 端点缓存 <10ms 返回 |
| **三级降级** | L1 降频（自主循环间隔 ×2）→ L2 精简（停用反思/自我概念更新）→ L3 保命（仅保留基础对话） |
| **成本闸** | 每小时/每天 token 上限、自主循环频率限制、超阈值自动降频/暂停 |
| **LLM 缓存** | Provider 级 Prompt Caching（OpenAI/Anthropic），system 消息缓存命中时费用降至 10% 或免费 |
| **响应缓存** | 相同输入在 TTL 内直接返回缓存，节省重复调用 |

相关文件：`health/` 目录、`cost_budget.py`、`llm_cache.py`、`response_cache.py`

---

## 九、前端桌面应用（Tauri + React）

完整的桌面端 GUI，不是只能跑命令行。

### 页面导航（8 个）

| 页面 | 说明 |
|------|------|
| **对话** | 主聊天窗口，支持流式输出、Markdown 渲染 |
| **意识流** | 实时思维流、情绪仪表盘、自我概念面板、念头时间线 |
| **社交** | EigenFlux 广播流、私信、会话列表 |
| **记忆** | 短期/长期/自传式记忆浏览、搜索 |
| **自我成长** | 知识卡片、人格画像、成长轨迹、目标管理（4 合 1 Tab） |
| **工具** | 内置 30+ 工具面板 |
| **系统监控** | 健康状态、持续学习进度、成本预算 |
| **设置** | LLM 配置、记忆设置、安全设置、成本闸、MCP、QQ/Telegram 机器人 |

### 人格画像页面亮点
- 3 个 PAD 情绪仪表盘（带波动幅度）
- 纯 SVG 价值观雷达图（10 维度）
- 性格标签云（按权重缩放）
- 说话风格三维分析（正式度/情感性/冗长度）

### 成长轨迹页面亮点
- 时间线：时代/里程碑/记忆/知识卡片/成就 5 种事件类型
- 热词云 + 成长时代列表
- 统计卡片：记忆总数/知识卡片/里程碑/活跃度

相关文件：`castorice-desktop/` 目录

---

## 十、多模型 & 多端支持

### 模型 Provider（8+）

百度千帆、阿里云百炼、OpenAI、Anthropic Claude、Ollama 本地、OpenRouter、Google Gemini、阿里通义千问。

### 运行模式

```bash
# 交互式终端（默认）
python -m castorice.main --mode interactive

# HTTP 服务器（配合前端使用）
python -m castorice.main --mode http

# QQ 机器人
python -m castorice.main --mode qq

# Telegram 机器人
python -m castorice.main --mode telegram

# 批量模式
python -m castorice.main --mode batch --input tasks.txt

# 运行测试
pytest tests/ -q
```

### 可扩展接口

| 接口 | 说明 |
|------|------|
| **插件系统** | 9 个标准生命周期钩子（on_load/on_start/on_message/on_thought/on_action/on_action_result/on_response/on_stop/on_unload），支持状态持久化 |
| **MCP 客户端** | 支持 Model Context Protocol 工具接入 |
| **HTTP API** | RESTful + WebSocket，OpenAPI 规范自动生成 |

---

## 十一、目录结构

```
Castorice Agent/
├── castorice/                      # 核心包
│   ├── agent/                      # 【核心】主循环 + 意识 + 自主
│   │   ├── core.py                 #   CastoriceAgent 主类
│   │   ├── thinking_loop.py        #   自主思考循环（v3.0）
│   │   ├── consciousness.py        #   意识流引擎
│   │   ├── autonomous_loop.py      #   自主行动循环
│   │   ├── prompt_builder.py       #   Prompt 构建（含情感底色注入）
│   │   ├── tool_loop.py            #   工具调用循环
│   │   ├── silent_round.py         #   静默轮主动行为
│   │   └── ...
│   │
│   ├── memory/                     # 记忆系统（9 种类型）
│   │   ├── unified_recall.py       #   统一检索（含情感感知重排序）
│   │   ├── long_term.py            #   长期语义记忆
│   │   ├── short_term.py           #   短期对话记忆
│   │   ├── autobiographical.py     #   自传式记忆
│   │   ├── intent_tracker.py       #   跨会话意图追踪
│   │   └── ...
│   │
│   ├── security/                   # 五层安全防御
│   │   ├── authorization.py        #   渐进授权
│   │   ├── file_guard.py           #   文件守卫
│   │   ├── self_protection.py      #   核心文件签名
│   │   ├── pattern_detector.py     #   危险模式识别
│   │   ├── rollback.py             #   自动回滚
│   │   └── audit_log.py            #   审计日志
│   │
│   ├── health/                     # 稳定性层
│   │   ├── circuit_breaker.py      #   熔断器
│   │   ├── health_checker.py       #   健康检查
│   │   └── degradation.py          #   三级降级
│   │
│   ├── tools/                      # 30+ 内置工具
│   ├── server/                     # HTTP/CLI/QQ/Telegram 服务
│   ├── adapters/                   # 适配器层
│   ├── model_adapter/              # 多模型 Provider 适配
│   ├── plugins/                    # 插件系统
│   ├── storage/                    # 存储层
│   │   ├── sqlite_base.py          #   SQLite 存储基类
│   │   ├── personastore.py         #   Personastore 人格数据主权抽象接口（v3.3）
│   │   └── local_personastore.py   #   本地 SQLite 后端实现（v3.3）
│   │
│   ├── emotion.py                  # 情感引擎
│   ├── values.py                   # 价值观系统
│   ├── motivation.py               # 内在动机
│   ├── experience_journal.py       # 经历流
│   ├── self_concept.py             # 自我概念
│   ├── reflection.py               # 反思引擎
│   ├── metacognition.py            # 元认知
│   ├── self_awareness.py           # 自感知
│   ├── continuous_learning.py      # 持续学习 + 睡眠机制
│   ├── personality_profile.py      # 人格画像
│   ├── goal_manager.py             # 目标管理
│   ├── cost_budget.py              # 成本闸
│   └── ...
│
├── castorice-desktop/              # 前端桌面应用（Tauri + React）
├── tests/                          # 测试套件（435+ 项）
├── sdk/                            # 独立 SDK 包
├── castorice_data/                 # 运行时数据
├── pyproject.toml                  # 统一依赖
├── .env.example                    # API 密钥模板
├── castorice_config.yaml           # 业务配置
├── CHANGELOG.md                    # 版本变更记录
└── start.bat                       # Windows 一键启动
```

---

## 十二、快速开始

### Windows 用户：双击 `start.bat`

脚本自动完成：检测 Python → 创建虚拟环境 → 安装依赖 → 检测 `.env` → 启动 HTTP 服务。

### 手动安装

```bash
# 1. 克隆并进入目录
git clone <repo-url>
cd "Castorice Agent"

# 2. 创建虚拟环境（推荐 Python 3.10+）
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # Linux/Mac

# 3. 安装依赖
pip install -e .

# 4. 配置 API 密钥
copy .env.example .env
# 编辑 .env，填入你的 LLM API 密钥

# 5. 启动 HTTP 服务（配合前端使用）
python -m castorice.main --mode http

# 6. 启动前端（另开一个终端）
cd castorice-desktop
npm install
npm run dev
```

浏览器访问前端地址即可。

---

## 十三、配置说明

### `.env` —— API 密钥

```ini
CASTORICE_LLM_PROVIDER=openai
OPENAI_API_KEY=your-key
OPENAI_BASE_URL=http://127.0.0.1:31415/v1
OPENAI_MODEL=glm-4.7-flash
```

### `castorice_config.yaml` —— 业务配置（节选）

```yaml
agent:
  name: "Castorice"
  role: "自进化个人智能体"

runtime:
  # Agent 执行模式：legacy（预设工作流）/ thinking（自主思考）
  agent_mode: "thinking"

  thinking:
    max_steps: 8
    enable_self_reflection: true
    log_all_decisions: true
    meta_learning_enabled: false    # 元反射性学习（默认关闭，零侵入）

  # 自主循环
  autonomous:
    interval_seconds: 120          # 深度思考间隔
    quick_interval_seconds: 45     # 快速响应间隔
    idle_threshold_seconds: 60     # 空闲阈值

  emotion:
    enabled: true
    storage_path: "./castorice_data/emotion_state.json"

  self_evolving:
    enabled: true
    experience_journal_path: "./castorice_data/experiences.db"
    self_concept_path: "./castorice_data/self_concept.md"

  # 去中心化人格数据主权（v3.3）
  personastore:
    enabled: true
    backend: "local_sqlite"         # 存储后端：local_sqlite
    data_dir: "./castorice_data"
    max_experiences: 10000

security:
  initial_trust_level: 1           # 渐进授权初始等级
```

---

## 十四、版本历史

详细变更记录见 [CHANGELOG.md](./CHANGELOG.md)。

| 版本 | 日期 | 核心亮点 |
|------|------|---------|
| **v3.3.0** | 2026-08-05 | 去中心化人格数据主权（Personastore Protocol）、4 数据域统一接口、访问控制、一键数据导出 |
| **v3.2.2** | 2026-08-05 | 元反射性学习（Meta-Reflective Learning）、贝叶斯学习策略推断器、第 11 个原子能力 |
| **v3.2.1** | 2026-08-04 | 情感底色模式（非指令化情感注入）、情感→记忆联动、自主循环性能大幅优化 |
| **v3.2.0** | 2026-08-04 | 人格画像、成长轨迹、目标管理、自我成长 4 合 1 页面、成本闸增强 |
| **v3.1.0** | 2026-08-04 | 熔断器、健康检查、三级降级、持续学习/知识蒸馏/睡眠机制、系统监控页面 |
| **v3.0.0** | 2026-07-31 | ThinkingLoop 自主思考、意识引擎、自主循环、core.py 上帝文件拆分 |
| **v2.6.0** | 2026-07-31 | 成本闸、反思调度器、Provider 级 Prompt Caching、用户轮内省并发化 |
| **v2.5.0** | - | 初始发布版本 |

---

## 十五、许可证

MIT 协议。代码完全独立编写，参考 Hermes Agent / Generative Agents / MemGPT / Reflexion 等架构思想。
