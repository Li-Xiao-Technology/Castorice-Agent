# Castorice Agent 自由度提升计划（L1: 思考自由）

## 一、目标

在保持现有架构稳定的前提下，让 Agent 在 L1 层级获得**"自主决定下一步做什么"**的能力。

### 核心特性
- ✅ LLM 决定"先做什么后做什么"，而不是被 7 个 phase 牵着走
- ✅ 向后兼容：现有 `agent_mode: legacy` 模式完全保留
- ✅ 安全兜底：自主决策失败时自动回退到原流程
- ✅ 可观测：每次自主决策都有 reasoning 日志

### 不在本次范围
- ❌ 不删除现有 phase 架构
- ❌ 不修改 self_organization.py 的工作流选择器
- ❌ 不重写 _arun_impl
- ❌ 不实现工具创造（L2 阶段）

---

## 二、架构设计

### 整体流程

```
用户输入
   ↓
_arun_impl (现有，未改动)
   ↓
_phase_workflow_execute (轻微改动)
   ↓
   ├─ agent_mode == "legacy"  → 原有 DynamicWorkflowSelector
   └─ agent_mode == "thinking" → ThinkingLoop (新)
                                     ↓
                                  LLM 决定下一步
                                     ↓
                                  执行原子能力
                                     ↓
                                  评估 / 继续 / 结束
```

### 关键组件

**新增文件**：`castorice/agent/thinking_loop.py`

```python
class ThinkingLoop:
    """LLM 驱动的自主思考循环（L1 自由度）"""
    
    # 原子能力列表（与现有 phase 一一对应）
    ATOMIC_ABILITIES = {
        "understand_intent": "理解用户意图",
        "recall_memory": "检索相关记忆",
        "plan_tasks": "分解任务",
        "execute_tools": "执行工具",
        "generate_answer": "生成回答",
        "self_reflect": "自我反思",
        "save_memory": "保存到记忆",
        "ask_user": "向用户询问",
        "finish": "结束并返回结果",
    }
    
    async def run(self, state: State) -> State:
        """
        自主思考循环：
        1. 让 LLM 决定下一步
        2. 执行该能力
        3. 让 LLM 评估是否继续
        4. 达到目标 / 超过 max_steps / 资源耗尽 时结束
        """
        max_steps = self.config.get("max_thinking_steps", 8)
        for step in range(max_steps):
            # 1. LLM 决策
            decision = await self._decide_next(state)
            
            # 2. 解析决策
            ability = decision.get("ability", "finish")
            reasoning = decision.get("reasoning", "")
            
            self._log_decision(step, ability, reasoning)
            
            # 3. 执行
            if ability == "finish":
                state.final_answer = decision.get("answer", state.final_answer)
                return state
            
            result = await self._execute_ability(ability, state, decision)
            
            # 4. 评估是否继续
            if not await self._should_continue(state, result):
                return state
        
        # 超过最大步数，安全兜底
        state.final_answer = state.final_answer or "我思考了很久，还没想出好的方案..."
        return state
```

### 决策 Prompt 设计

```python
THINKING_DECISION_PROMPT = """
你是 Castorice，一个自主思考的 AI。

【当前状态】
- 用户输入: {user_input}
- 已有信息: {current_observations}
- 已执行的步骤: {history}
- 情感倾向: {emotion_bias}

【可选能力】
{abilities_desc}

【决策要求】
1. 选择下一个最该执行的能力
2. 给出 reasoning（为什么选这个）
3. 如果觉得已经可以回答，选 finish 并给出 answer

返回 JSON:
{{
  "reasoning": "我选这个是因为...",
  "ability": "<能力名>",
  "params": {{}},
  "answer": "<仅在 finish 时填写>"
}}
"""
```

---

## 三、具体改动清单

### 1. 新增文件：`castorice/agent/thinking_loop.py`（约 250 行）

| 函数 | 作用 |
|------|------|
| `ThinkingLoop.__init__` | 注入 agent 引用、配置 |
| `ThinkingLoop.run` | 主循环入口 |
| `ThinkingLoop._decide_next` | 调用 LLM 决策 |
| `ThinkingLoop._execute_ability` | 执行原子能力（映射到现有 phase） |
| `ThinkingLoop._should_continue` | 评估是否继续 |
| `ThinkingLoop._log_decision` | 记录决策日志 |

### 2. 修改文件：`castorice/agent/core.py`

**位置**：`CastoriceAgent.__init__` 中

```python
# 改动 1：初始化 ThinkingLoop
self.thinking_loop = ThinkingLoop(self) if config.agent_mode == "thinking" else None

# 改动 2：在 _phase_workflow_execute 中增加分支
async def _phase_workflow_execute(self, state, session_id, workflow_name, stream_callback):
    if self.thinking_loop and workflow_name is None:
        # L1 模式：走自主思考
        return await self.thinking_loop.run(state)
    else:
        # 原有逻辑
        ...
```

### 3. 修改文件：`castorice_config.yaml`

```yaml
# 新增配置项
agent:
  mode: "legacy"  # legacy | thinking
  thinking:
    max_steps: 8
    enable_self_reflection: true
    log_all_decisions: true
```

### 4. 新增测试：`tests/test_thinking_loop.py`

| 测试用例 | 验证点 |
|----------|--------|
| `test_simple_chat` | 简单问候能正确结束 |
| `test_task_execution` | 任务型输入能调用工具 |
| `test_max_steps_limit` | 超过 max_steps 时强制结束 |
| `test_decision_logging` | 决策日志被正确记录 |
| `test_legacy_compatibility` | legacy 模式行为不变 |

---

## 四、关键决策

### 决策 1：原子能力的边界

**问题**：自主决策时，LLM 能选哪些能力？

**方案**：限定为以下 9 个核心能力（与现有 phase 一一对应）
- `understand_intent` ↔ `_step_intent`
- `recall_memory` ↔ `_phase_memory_recall`
- `plan_tasks` ↔ `_step_planning`
- `execute_tools` ↔ `_step_tool_loop`
- `generate_answer` ↔ `_step_answer`
- `self_reflect` ↔ `_step_reflection`
- `save_memory` ↔ `_step_memory`
- `ask_user` ↔ 新增（向用户询问澄清）
- `finish` ↔ 结束

**为什么这样设计**：
- 不破坏现有 phase 抽象
- 9 个能力粒度合适（太少不够自由，太多不稳定）
- 与现有工具链无缝集成

### 决策 2：失败回退策略

**问题**：LLM 决策出错怎么办？

**方案**：三级回退
1. **第一级**：决策解析失败 → 强制 `execute_tools`（最常见的能力）
2. **第二级**：执行原子能力失败 → 记录错误，继续下一步
3. **第三级**：连续 3 次失败 → 回退到 legacy 工作流

```python
async def _decide_next(self, state):
    try:
        response = await self.model.chat([...])
        return self._parse_decision(response.content)
    except Exception as e:
        logger.warning(f"决策失败，回退: {e}")
        return {"ability": "execute_tools", "reasoning": "决策失败，执行默认能力"}
```

### 决策 3：性能影响

**问题**：每次决策都要调 LLM，会不会很慢？

**预估开销**：
- 每次 LLM 决策：~1-2 秒
- 简单任务：1-2 次决策 = 2-4 秒
- 复杂任务：3-5 次决策 = 3-10 秒

**优化措施**：
- 决策结果缓存（相同状态不重复决策）
- 小模型用于决策（如果可用）
- 异步并发执行不相关的步骤

---

## 五、实施步骤

### Step 1: 准备工作（无代码改动）
- [ ] 创建 `plans/` 目录
- [ ] 编写本计划文档
- [ ] 创建任务列表

### Step 2: 实现 ThinkingLoop（核心代码）
- [ ] 新增 `castorice/agent/thinking_loop.py`
- [ ] 实现 `ThinkingLoop` 类
- [ ] 实现 9 个原子能力的映射
- [ ] 实现决策日志

### Step 3: 集成到现有 Agent
- [ ] 修改 `castorice/agent/core.py`
- [ ] 在 `__init__` 中初始化 ThinkingLoop
- [ ] 在 `_phase_workflow_execute` 中增加分支

### Step 4: 配置和开关
- [ ] 修改 `castorice_config.yaml`
- [ ] 添加 `agent.mode` 配置项
- [ ] 添加 thinking 子配置

### Step 5: 测试验证
- [ ] 新增 `tests/test_thinking_loop.py`
- [ ] 验证简单任务
- [ ] 验证复杂任务
- [ ] 验证 legacy 模式不受影响

### Step 6: 文档和清理
- [ ] 更新 README（如有）
- [ ] 清理临时文件

---

## 六、验收标准

### 功能性
- [ ] `agent_mode: "thinking"` 时，Agent 能自主决定执行顺序
- [ ] `agent_mode: "legacy"` 时，行为与现在完全一致
- [ ] 决策失败时能自动回退
- [ ] 超过 max_steps 时强制结束

### 性能
- [ ] 简单任务额外延迟 < 2 秒
- [ ] 决策日志完整可追溯

### 安全性
- [ ] 决策 Prompt 不会泄露系统信息
- [ ] 异常情况下不会让 Agent 进入死循环

---

## 七、风险与缓解

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|----------|
| LLM 决策不稳定 | 中 | 中 | 决策解析 + 回退机制 |
| 性能下降 | 中 | 低 | 决策缓存 + max_steps 限制 |
| 现有测试失败 | 低 | 高 | A/B 开关 + 灰度切换 |
| 决策循环 | 低 | 中 | 强制 max_steps + 检测 |
| Prompt 注入 | 低 | 中 | 严格参数化 prompt |

---

## 八、下一步

完成 L1 后，可以考虑：
- **L2（组合自由）**：LLM 能动态组合多个工具
- **L3（创造自由）**：LLM 能创造新工具
- **L4（反思自由）**：LLM 能质疑并推翻自己的决策

每个 L 阶段都是独立可选项，可以根据实际效果决定是否继续。

---

## 九、任务列表

完成后会按以下顺序更新：
1. ✅ 创建计划文档
2. ⏳ 实现 ThinkingLoop
3. ⏳ 集成到 core.py
4. ⏳ 配置和测试
5. ⏳ 验证和清理

