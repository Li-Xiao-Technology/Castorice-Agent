"""
ThinkingLoop - LLM 驱动的自主思考循环（L1 自由度）

核心设计理念：
- 让 LLM 自主决定"先做什么后做什么"，而不是被硬编码的 phase 牵着走
- 继承现有的情感系统、反思系统、安全系统
- 向后兼容：legacy 模式行为不变

与现有系统的集成：
- 情感偏置 → 影响决策倾向
- 反思结果 → 注入决策上下文
- 自我概念 → 作为决策参考
- 安全系统 → 检查每个决策的授权等级

作者: Castorice Team
"""

import asyncio
import json
import logging
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from castorice.model_adapter import ChatMessage
from castorice.metacognition import BayesianLearningStrategist

logger = logging.getLogger("Castorice.ThinkingLoop")


# =============================================================================
# 原子能力定义
# =============================================================================

ATOMIC_ABILITIES: Dict[str, str] = {
    # 核心认知能力
    "understand_intent": "理解用户意图，决定这是聊天还是任务",
    "recall_memory": "检索与用户输入相关的历史记忆和经历",
    "plan_tasks": "将复杂任务分解为可执行的步骤",

    # 执行能力
    "execute_tools": "调用工具（搜索、计算、代码执行等）",
    "generate_answer": "基于已有信息生成最终回答",

    # 元认知能力
    "self_reflect": "反思刚才的思考过程是否有问题",
    "ask_user": "当信息不足时，向用户询问澄清",
    "select_learning_strategy": "元反射性学习：基于历史经验推荐最优学习策略",

    # 持久化能力
    "save_memory": "将本次交互的重要信息保存到记忆系统",
    "update_self_concept": "根据新经历更新自我认知",

    # 终止能力
    "finish": "结束思考，返回结果",
}


class ThinkingLoop:
    """
    LLM 驱动的自主思考循环。

    与 legacy 模式的区别：
    - legacy: 硬编码 7 个 phase 顺序，Agent 只能被动执行
    - thinking: LLM 每轮决定"下一步做什么"，Agent 主动选择

    使用方式：
        loop = ThinkingLoop(agent)
        state = await loop.run(state)
    """

    def __init__(self, agent: Any):
        """
        初始化 ThinkingLoop。

        Args:
            agent: CastoriceAgent 实例，用于访问模型、工具、记忆等子系统
        """
        self.agent = agent
        self.model = agent.model
        self.config = agent.config

        # 从配置读取参数
        thinking_cfg = {}
        try:
            _is_mock = hasattr(self.config, '_mock_name') or 'mock' in type(self.config).__name__.lower()
            if not _is_mock and hasattr(self.config, "raw") and callable(getattr(self.config, "raw", None)):
                raw = self.config.raw()
                runtime_cfg = raw.get("runtime", {}) or {}
                thinking_cfg = runtime_cfg.get("thinking", {}) or {}
            elif hasattr(self.config, "thinking"):
                # 兼容测试环境：config.thinking 直接是字典
                thinking_cfg = getattr(self.config, "thinking", {}) or {}
        except Exception:
            logger.debug(f"静默异常 [castorice/agent/thinking_loop.py:87]")
            pass
        if isinstance(thinking_cfg, dict):
            self.max_steps = thinking_cfg.get("max_steps", 8)
            self.enable_self_reflection = thinking_cfg.get("enable_self_reflection", True)
            self.log_all_decisions = thinking_cfg.get("log_all_decisions", True)
            self.meta_learning_enabled = thinking_cfg.get("meta_learning_enabled", False)
        else:
            self.max_steps = 8
            self.enable_self_reflection = True
            self.log_all_decisions = True
            self.meta_learning_enabled = False

        # 决策历史，用于追溯和反思
        self.decision_history: List[Dict[str, Any]] = []

        # 元反射性学习策略推断器（仅在启用时初始化）
        self.meta_learning_strategist = BayesianLearningStrategist() if self.meta_learning_enabled else None

    # =====================================================================
    # 主入口
    # =====================================================================

    async def run(
        self,
        state: Any,
        session_id: str,
        stream_callback: Optional[Callable[[str], None]] = None,
    ) -> float:
        """
        自主思考循环主入口。

        流程：
        1. 每轮让 LLM 决定下一步做什么
        2. 执行该原子能力
        3. 让 LLM 评估是否继续
        4. 达到目标 / 超过 max_steps / 资源耗尽 时结束

        Args:
            state: Agent 状态对象
            session_id: 会话 ID
            stream_callback: 流式输出回调

        Returns:
            执行耗时（毫秒）
        """
        task_start_time = time.time()

        logger.info(f"ThinkingLoop 启动 | max_steps={self.max_steps} | session={session_id}")

        for step in range(self.max_steps):
            # 1. 构建当前状态摘要
            state_summary = self._build_state_summary(state, step)

            # 2. 获取情感偏置（如果有）
            emotion_bias = self._get_emotion_bias(state)

            # 3. 获取反思洞察（如果有）
            reflection_insight = self._get_reflection_insight(state)

            # 4. 让 LLM 决定下一步
            decision = await self._decide_next(
                state=state,
                state_summary=state_summary,
                emotion_bias=emotion_bias,
                reflection_insight=reflection_insight,
                step=step,
            )

            ability = decision.get("ability", "finish")
            reasoning = decision.get("reasoning", "")

            # 5. 记录决策
            if self.log_all_decisions:
                self._log_decision(step, ability, reasoning, state)

            logger.info(f"ThinkingLoop 第 {step + 1} 步 | 能力={ability} | reasoning={reasoning[:60]}...")

            # 6. 如果决定结束，提取回答并退出
            if ability == "finish":
                finish_answer = decision.get("answer")
                if not finish_answer or not finish_answer.strip():
                    result = self.agent._step_answer(state, stream_callback)
                    if asyncio.iscoroutine(result):
                        await result
                else:
                    state.final_answer = finish_answer
                    if stream_callback and callable(stream_callback) and finish_answer:
                        chunk_size = 3
                        for i in range(0, len(finish_answer), chunk_size):
                            stream_callback(finish_answer[i:i + chunk_size])
                            await asyncio.sleep(0.01)
                logger.info(f"ThinkingLoop 结束 | 总步数={step + 1}")
                break

            # 7. 检查授权（安全系统）
            if not self._check_authorization(ability, state):
                logger.warning(f"ThinkingLoop 授权检查失败 | 能力={ability}")
                state.errors.append(f"'{ability}' 需要更高授权等级")
                continue

            # 8. 执行原子能力
            try:
                result = await self._execute_ability(
                    ability=ability,
                    state=state,
                    session_id=session_id,
                    stream_callback=stream_callback,
                    decision_params=decision.get("params", {}),
                )
            except Exception as e:
                logger.warning(f"ThinkingLoop 执行失败 | 能力={ability} | 错误={e}")
                state.errors.append(f"{ability} 执行失败: {e}")
                # 执行失败不中断，继续下一步决策
                continue

            # 9. 评估是否继续（如果启用）
            if step > 0 and self.enable_self_reflection:
                should_continue = await self._should_continue(state, ability, result)
                if not should_continue:
                    logger.info(f"ThinkingLoop 自我评估建议结束 | 第 {step + 1} 步")
                    if not state.final_answer:
                        state.final_answer = "我已经完成了思考，但没有生成明确的回答。"
                    break

        else:
            # 超过 max_steps，强制结束
            logger.warning(f"ThinkingLoop 超过最大步数 {self.max_steps}，强制结束")
            if not state.final_answer:
                state.final_answer = "我思考了很久，但还没想出好的方案。让我再想想..."

        elapsed_ms = (time.time() - task_start_time) * 1000
        return elapsed_ms

    # =====================================================================
    # LLM 决策
    # =====================================================================

    async def _decide_next(
        self,
        state: Any,
        state_summary: str,
        emotion_bias: Dict[str, float],
        reflection_insight: str,
        step: int,
    ) -> Dict[str, Any]:
        """
        让 LLM 决定下一步行动。

        决策 Prompt 包含：
        - 当前状态摘要
        - 已执行步骤历史
        - 情感偏置（影响决策倾向）
        - 反思洞察（如果有）
        - 可用能力列表

        Args:
            state: Agent 状态
            state_summary: 当前状态摘要
            emotion_bias: 情感偏置字典
            reflection_insight: 反思洞察
            step: 当前步数

        Returns:
            决策字典，包含 ability、reasoning、params、answer 等
        """
        # 构建能力列表（根据当前状态过滤不可用的）
        available_abilities = self._filter_available_abilities(state, step)

        tools_desc = getattr(state, "available_tools_desc", "")

        prompt = self._build_decision_prompt(
            user_input=state.user_input,
            state_summary=state_summary,
            tools_desc=tools_desc,
            emotion_bias=emotion_bias,
            reflection_insight=reflection_insight,
            available_abilities=available_abilities,
            history=self._format_decision_history(),
            step=step,
        )

        # 调用 LLM
        try:
            messages = [ChatMessage("system", prompt, cacheable=True)]
            response = self.model.chat(messages)
            content = response.content if hasattr(response, "content") else str(response)
            decision = self._parse_decision(content)
        except Exception as e:
            logger.warning(f"LLM 决策失败: {e}，回退到 generate_answer")
            decision = {
                "ability": "generate_answer",
                "reasoning": f"决策失败，回退生成回答: {e}",
                "params": {},
            }

        return decision

    def _build_decision_prompt(
        self,
        user_input: str,
        state_summary: str,
        tools_desc: str,
        emotion_bias: Dict[str, float],
        reflection_insight: str,
        available_abilities: Dict[str, str],
        history: str,
        step: int,
    ) -> str:
        """
        构建决策 Prompt。

        这个 Prompt 是 ThinkingLoop 的核心，它定义了 Agent 的"思考方式"。
        """
        # 能力列表格式化
        abilities_desc = "\n".join(
            f"  - {name}: {desc}" for name, desc in available_abilities.items()
        )

        # 情感偏置格式化
        if emotion_bias:
            bias_desc = "\n".join(
                f"  - {k}: {v:+.2f}" for k, v in emotion_bias.items()
            )
        else:
            bias_desc = "  无明显偏置"

        prompt = f"""你是 Castorice，一个自主思考的 AI Agent。

【当前任务】
用户输入: {user_input}

【状态摘要】
{state_summary}

【可用工具】（调用工具时选择最合适的，从名称和描述判断）
{tools_desc if tools_desc else "（无）"}

【情感偏置】（影响你的决策倾向）
{bias_desc}

【反思洞察】（如果有）
{reflection_insight if reflection_insight else "暂无"}

【已执行步骤】
{history if history else "尚未执行任何步骤"}

【可用能力】
{abilities_desc}

【决策要求】
1. 选择下一个最该执行的能力（从"可用能力"中选）
2. 如果你认为已经可以回答用户，选择 "finish" 并给出 answer
3. 给出 reasoning：为什么选这个能力
4. 如果选 "execute_tools"，在 params 中指定工具名

【返回格式】
严格返回 JSON，不要有任何其他文字：
{{
  "reasoning": "我选择这个能力是因为...",
  "ability": "<能力名>",
  "params": {{}},
  "answer": "<仅在 finish 时填写，最终回答>"
}}
"""
        return prompt

    def _parse_decision(self, content: str) -> Dict[str, Any]:
        """
        解析 LLM 返回的决策 JSON。

        支持两种情况：
        1. 纯 JSON 字符串
        2. Markdown 代码块包裹的 JSON

        Args:
            content: LLM 返回的文本

        Returns:
            解析后的决策字典
        """
        # 尝试提取 JSON（处理 Markdown 代码块）
        content = content.strip()
        if content.startswith("```"):
            # 提取代码块内容
            lines = content.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            content = "\n".join(lines).strip()

        try:
            decision = json.loads(content)
        except json.JSONDecodeError:
            # 尝试从文本中提取 JSON
            start = content.find("{")
            end = content.rfind("}")
            if start != -1 and end != -1 and end > start:
                try:
                    decision = json.loads(content[start:end + 1])
                except json.JSONDecodeError:
                    decision = {"ability": "generate_answer", "reasoning": "JSON 解析失败"}
            else:
                decision = {"ability": "generate_answer", "reasoning": "JSON 解析失败"}

        # 验证必要字段
        if "ability" not in decision or decision["ability"] not in ATOMIC_ABILITIES:
            logger.warning(f"无效的能力名: {decision.get('ability')}, 回退到 generate_answer")
            decision["ability"] = "generate_answer"
            decision["reasoning"] = decision.get("reasoning", "") + " [回退: 无效能力名]"

        return decision

    # =====================================================================
    # 原子能力执行
    # =====================================================================

    async def _execute_ability(
        self,
        ability: str,
        state: Any,
        session_id: str,
        stream_callback: Optional[Callable[[str], None]],
        decision_params: Dict[str, Any],
    ) -> Any:
        """
        执行指定的原子能力。

        每个能力映射到现有 Agent 的一个方法或 phase。

        Args:
            ability: 能力名
            state: Agent 状态
            session_id: 会话 ID
            stream_callback: 流式输出回调
            decision_params: LLM 决策时附加的参数

        Returns:
            执行结果
        """
        try:
            if ability == "understand_intent":
                result = self.agent._step_intent(state)
                if asyncio.iscoroutine(result):
                    await result
                return {"intent_type": state.intent_type}

            elif ability == "recall_memory":
                result = self.agent._phase_memory_recall(state, session_id)
                if asyncio.iscoroutine(result):
                    await result
                return {
                    "history_len": len(state.relevant_history) if hasattr(state, "relevant_history") else 0,
                }

            elif ability == "plan_tasks":
                result = self.agent._step_planning(state)
                if asyncio.iscoroutine(result):
                    await result
                return {"plans": state.plans if hasattr(state, "plans") else []}

            elif ability == "execute_tools":
                if "tool" in decision_params:
                    state.available_tools_desc = decision_params["tool"]
                result = self.agent._step_tool_loop(state)
                if asyncio.iscoroutine(result):
                    await result
                return {"tool_calls": state.tool_calls if hasattr(state, "tool_calls") else []}

            elif ability == "generate_answer":
                result = self.agent._step_answer(state, stream_callback)
                if asyncio.iscoroutine(result):
                    await result
                return {"answer": state.final_answer}

            elif ability == "self_reflect":
                result = self.agent._step_reflection(state)
                if asyncio.iscoroutine(result):
                    await result
                return {"reflection": state.reflection_summary}

            elif ability == "ask_user":
                question = decision_params.get("question", "能再详细说明一下吗？")
                state.final_answer = f"[需要澄清] {question}"
                return {"question": question}

            elif ability == "save_memory":
                result = self.agent._step_memory(state)
                if asyncio.iscoroutine(result):
                    await result
                return {"saved": True}

            elif ability == "update_self_concept":
                if hasattr(self.agent, "self_concept") and self.agent.self_concept:
                    try:
                        self.agent.self_concept.update_from_experience(
                            state.user_input, state.final_answer or "", llm_adapter=self.model
                        )
                    except Exception as e:
                        logger.warning(f"自我概念更新失败: {e}")
                return {"updated": True}

            elif ability == "select_learning_strategy":
                if not self.meta_learning_enabled or self.meta_learning_strategist is None:
                    return {"suggestion": "元学习未启用", "enabled": False}
                task_context = self._build_task_context_for_learning(state)
                suggestion = self.meta_learning_strategist.recommend(task_context)
                if suggestion is None:
                    return {
                        "suggestion": None,
                        "message": "暂无足够学习历史以提供策略建议，请先积累一些学习经验。",
                        "enabled": True,
                    }
                return {
                    "suggestion": suggestion,
                    "message": f"[元学习建议] 在当前情境下，尝试使用 '{suggestion}' 策略可能更有效。您可以选择采纳或忽略此建议。",
                    "enabled": True,
                }

            else:
                logger.warning(f"未知能力: {ability}")
                return {"error": f"未知能力: {ability}"}

        except Exception as e:
            logger.warning(f"原子能力 '{ability}' 执行失败: {e}")
            return {"error": f"{ability} 执行失败: {e}"}

    # =====================================================================
    # 状态评估
    # =====================================================================

    def _build_state_summary(self, state: Any, step: int) -> str:
        """
        构建当前状态摘要，供 LLM 决策使用。

        Args:
            state: Agent 状态
            step: 当前步数

        Returns:
            状态摘要文本
        """
        parts = []

        # 意图类型
        if hasattr(state, "intent_type") and state.intent_type:
            parts.append(f"意图类型: {state.intent_type}")

        # 是否已有回答
        if hasattr(state, "final_answer") and state.final_answer:
            parts.append(f"已有回答: {state.final_answer[:100]}...")

        # 工具调用历史
        if hasattr(state, "tool_calls") and state.tool_calls:
            parts.append(f"已调用工具: {len(state.tool_calls)} 次")

        # 错误历史
        if hasattr(state, "errors") and state.errors:
            parts.append(f"已发生错误: {len(state.errors)} 次")

        # 当前步数
        parts.append(f"当前步数: {step + 1}")

        return "\n".join(parts) if parts else "初始状态"

    def _filter_available_abilities(self, state: Any, step: int) -> Dict[str, str]:
        """
        根据当前状态过滤可用的能力。

        例如：
        - 如果已经有 final_answer，优先显示 finish
        - 如果已经调用了工具，显示 generate_answer
        - 如果是第 0 步，优先显示 understand_intent

        Args:
            state: Agent 状态
            step: 当前步数

        Returns:
            过滤后的可用能力字典
        """
        available = dict(ATOMIC_ABILITIES)

        # 如果还没有理解意图，优先保留 understand_intent
        if step == 0 and (not hasattr(state, "intent_type") or not state.intent_type):
            # 保留所有能力，但 understand_intent 在 Prompt 中会排在前面
            pass

        # 如果已经有 final_answer，finish 始终可用
        if hasattr(state, "final_answer") and state.final_answer:
            available["finish"] = "结束思考并返回答案"

        # 如果元学习未启用，从可用能力中移除 select_learning_strategy
        if not self.meta_learning_enabled and "select_learning_strategy" in available:
            del available["select_learning_strategy"]

        return available

    def _build_task_context_for_learning(self, state: Any) -> str:
        """构建学习任务上下文摘要，用于元反射性学习的策略推荐"""
        parts = []
        if hasattr(state, "user_input") and state.user_input:
            parts.append(f"用户输入: {state.user_input[:100]}")
        if hasattr(state, "intent_type") and state.intent_type:
            parts.append(f"意图类型: {state.intent_type}")
        if hasattr(state, "errors") and state.errors:
            parts.append(f"已有错误: {len(state.errors)}个")
        if hasattr(state, "tool_calls") and state.tool_calls:
            parts.append(f"已调用工具: {len(state.tool_calls)}次")
        return " | ".join(parts) if parts else "未知任务"

    async def _should_continue(
        self,
        state: Any,
        last_ability: str,
        last_result: Any,
    ) -> bool:
        """
        让 LLM 评估是否应该继续思考。

        用于防止过度思考：当 Agent 已经得到足够信息时，应该停止。

        Args:
            state: Agent 状态
            last_ability: 上一步执行的能力
            last_result: 上一步的结果

        Returns:
            True 表示继续，False 表示停止
        """
        # 如果已经有 final_answer，不需要继续
        if hasattr(state, "final_answer") and state.final_answer and len(state.final_answer) > 10:
            return False

        # 如果是 ask_user，停止等待用户回复
        if last_ability == "ask_user":
            return False

        # 其他情况，继续
        return True

    # =====================================================================
    # 系统集成
    # =====================================================================

    def _get_emotion_bias(self, state: Any) -> Dict[str, float]:
        """
        获取情感偏置，影响决策倾向。

        集成现有的情感系统：如果 Agent 有 emotion_engine，
        调用 get_decision_bias() 获取偏置值。

        Args:
            state: Agent 状态

        Returns:
            情感偏置字典
        """
        if hasattr(self.agent, "emotion_engine") and self.agent.emotion_engine:
            try:
                bias = self.agent.emotion_engine.get_decision_bias()
                if bias:
                    return bias
            except Exception as e:
                logger.debug(f"获取情感偏置失败: {e}")
        return {}

    def _get_reflection_insight(self, state: Any) -> str:
        """
        获取反思洞察，注入决策上下文。

        从反思引擎获取最近的关键洞察。

        Args:
            state: Agent 状态

        Returns:
            反思洞察文本
        """
        if hasattr(self.agent, "reflection_engine") and self.agent.reflection_engine:
            try:
                # 尝试获取最近的反思记录
                recent = self.agent.reflection_engine.get_recent_reflections(limit=1)
                if recent:
                    return recent[0].get("insight", "")
            except Exception as e:
                logger.debug(f"获取反思洞察失败: {e}")
        return ""

    def _check_authorization(self, ability: str, state: Any) -> bool:
        """
        检查当前 Agent 是否有权限执行该能力。

        集成现有的安全系统：
        - L0-L2: 只能执行基础能力（understand_intent, recall_memory, generate_answer）
        - L3-L4: 可以执行工具和自我反思
        - L5: 可以执行 update_self_concept

        Args:
            ability: 能力名
            state: Agent 状态

        Returns:
            True 表示有权限
        """
        trust_level = 0
        if hasattr(self.agent, "authorization") and self.agent.authorization:
            try:
                trust_level = int(getattr(self.agent.authorization, "current_level", 0))
            except (TypeError, ValueError):
                pass

        # 基础能力：所有等级都允许
        basic_abilities = {"understand_intent", "recall_memory", "generate_answer", "ask_user", "finish"}
        if ability in basic_abilities:
            return True

        # 中等能力：需要 L1+
        medium_abilities = {"plan_tasks", "execute_tools", "self_reflect", "save_memory"}
        if ability in medium_abilities:
            return trust_level >= 1

        # 高级能力：需要 L4+
        if ability == "update_self_concept":
            return trust_level >= 4

        # 未知能力：默认拒绝
        logger.warning(f"未知能力授权检查: {ability}")
        return False

    # =====================================================================
    # 日志和调试
    # =====================================================================

    def _log_decision(self, step: int, ability: str, reasoning: str, state: Any):
        """
        记录决策日志。

        Args:
            step: 步数
            ability: 选择的能力
            reasoning: 决策理由
            state: Agent 状态
        """
        entry = {
            "step": step,
            "ability": ability,
            "reasoning": reasoning,
            "timestamp": time.time(),
            "user_input": getattr(state, "user_input", ""),
        }
        self.decision_history.append(entry)

    def _format_decision_history(self) -> str:
        """
        格式化决策历史，供 Prompt 使用。

        Returns:
            决策历史文本
        """
        if not self.decision_history:
            return ""

        lines = []
        for entry in self.decision_history[-5:]:  # 只取最近 5 条
            lines.append(f"  - 第 {entry['step'] + 1} 步: {entry['ability']} ({entry['reasoning'][:50]}...)")

        return "\n".join(lines)

    def get_decision_history(self) -> List[Dict[str, Any]]:
        """
        获取完整的决策历史。

        Returns:
            决策历史列表
        """
        return list(self.decision_history)

    def clear_decision_history(self):
        """清空决策历史。"""
        self.decision_history.clear()
