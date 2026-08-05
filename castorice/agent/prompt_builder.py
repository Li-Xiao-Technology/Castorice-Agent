"""
System Prompt 构建模块

统一构建并注入所有上下文信息到 LLM 的系统提示中。
"""

import logging
from typing import Any, List

from castorice.model_adapter import ChatMessage
from .common import logger


class PromptBuilderMixin:
    """提供 _build_system_prompt 及相关文本处理工具方法。"""

    # ============================================================
    # 公共工具：构建系统提示（消除重复注入）
    # ============================================================
    def _build_system_prompt(self, state: Any, base_prompt: str = "") -> str:
        """
        统一构建系统提示，注入所有上下文信息。

        各上下文注入逻辑由独立的 _inject_xxx 方法完成，本方法仅做 parts
        列表初始化和顺序编排，避免单方法超长。
        """
        parts = [base_prompt] if base_prompt else []

        self._inject_identity(parts, state)
        self._inject_emotion(parts, state)
        self._inject_strategy(parts, state)
        self._inject_memory(parts, state)
        self._inject_evolution(parts, state)
        self._inject_safety(parts, state)

        return "\n\n".join(parts) if parts else ""

    # ============================================================
    # 上下文注入子方法（每个方法负责一类上下文）
    # ============================================================

    def _inject_identity(self, parts: List[str], state: Any) -> None:
        """L1 性格设定 + 当前时间"""
        # L1: 注入自我概念（按领域分块，从经历中涌现的人格）
        try:
            sc_prompt = self.emotion_engine.get_personality_prompt()
            if self.self_concept and not self.self_concept.is_empty():
                structured = self.self_concept.get_structured()
                if structured:
                    sc_parts = []
                    for section_name, content in structured.items():
                        if content.strip():
                            sc_parts.append(f"## {section_name}\n{content[:500]}")
                    if sc_parts:
                        sc_prompt = "\n\n".join(sc_parts)
            parts.append(sc_prompt)
        except Exception as e:
            logger.warning(f"L1 性格设定注入失败: {e}")

        # 注入当前时间（关键：确保 Agent 知道当前日期）
        from datetime import datetime, timezone
        now_local = datetime.now().astimezone()
        now_utc = datetime.now(timezone.utc)
        week_days = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
        parts.append(
            f"## 当前时间\n"
            f"本地时间: {now_local.strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"UTC时间: {now_utc.strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"星期: {week_days[now_local.weekday()]}\n"
            f"年份: {now_local.year}"
        )

    def _inject_emotion(self, parts: List[str], state: Any) -> None:
        """
        情绪注入：不是指令，而是内心体验的描述。

        关键理念改变：
        - 旧方式："你现在心情很好，回复可以轻快热情一些"（指令）
        - 新方式："我此刻感觉心情不错，比较轻松"（体验描述）

        LLM 读到体验描述时，会自然地根据这个状态调整回复，
        就像人一样——知道自己难过时，说话自然就会慢下来。
        """
        # 获取原始的 PAD 值（如果能拿到的话）
        p, a, d = 0.0, 0.0, 0.0
        try:
            ee = getattr(self, 'emotion_engine', None)
            if ee:
                es = ee._emergence_engine._state
                p, a, d = es.pleasure, es.arousal, es.dominance
        except Exception:
            pass

        # 构建内心体验描述（不是指令！）
        experience = self._describe_inner_experience(p, a, d)
        if experience:
            parts.append(experience)

        # L3: 情绪决策偏置——仍然保留，但改写成"我此刻的倾向"而不是指令
        emotion_bias_text = self._build_emotion_bias_as_inner_tendency(state)
        if emotion_bias_text:
            parts.append(emotion_bias_text)

    def _inject_strategy(self, parts: List[str], state: Any) -> None:
        """思维策略 + 对话风格调整"""
        # 注入思维策略
        if state.thinking_strategy_prompt:
            parts.append(f"## 思维策略\n{state.thinking_strategy_prompt}")

        # 注入对话风格调整
        if state.dialogue_adjustment:
            parts.append(state.dialogue_adjustment)

    def _inject_memory(self, parts: List[str], state: Any) -> None:
        """统一记忆检索 + 用户画像 + 未完成意图 + 相似历史会话"""
        # P2.2: 注入统一记忆检索结果（长期记忆 + 经历流 + 自我概念）
        if state.relevant_history:
            truncated = self._truncate_by_doc_boundary(state.relevant_history, 2000)
            parts.append(truncated)

        # 注入短期记忆（当前会话历史对话）
        # 历史对话已通过 history_messages 注入，不再使用独立的 context 字段

        # 注入用户画像
        if state.user_profile_context:
            parts.append(f"## 用户画像\n{state.user_profile_context}")

        # P0: 注入未完成意图（长期意图追踪）
        if hasattr(self, 'intent_tracker'):
            try:
                intent_prompt = self.intent_tracker.to_prompt(session_id=state.session_id, max_intents=5)
                if intent_prompt:
                    parts.append(intent_prompt)
            except Exception as e:
                logger.debug(f"P0 意图注入失败: {e}")

        # P2: 注入相似历史会话（跨会话记忆迁移）
        if state.similar_sessions:
            session_texts = [
                f"- {s.get('session_id', '')[:15]}: {s.get('summary', '')[:100]}"
                for s in state.similar_sessions[:3]
            ]
            if session_texts:
                parts.append(f"## 相似历史会话\n{chr(10).join(session_texts)}\n（你之前和用户讨论过类似话题，可以参考）")

    def _inject_evolution(self, parts: List[str], state: Any) -> None:
        """行动队列 + 社会关系 + 自传式记忆 + 反思信号 + 动机"""
        # P1: 注入待执行行动（反思-行动闭环）
        if hasattr(self, 'action_queue'):
            try:
                action_prompt = self.action_queue.to_prompt(max_actions=3)
                if action_prompt:
                    parts.append(action_prompt)
            except Exception as e:
                logger.debug(f"P1 行动队列注入失败: {e}")

        # S1: 注入当前关系状态（社会关系网络）
        if hasattr(self, 'social_relation'):
            try:
                user_id = getattr(state, 'user_id', state.session_id)
                relation_prompt = self.social_relation.to_prompt(user_id)
                if relation_prompt:
                    parts.append(relation_prompt)
            except Exception as e:
                logger.debug(f"S1 关系状态注入失败: {e}")

        # A1: 注入自传式记忆（紧凑格式：当前时期 + 近期里程碑）
        autobio_text = self._build_autobiographical_section(state)
        if autobio_text:
            parts.append(autobio_text)

        # P1.2: 注入最近反思信号（让 Agent 知道自己上次反思学到了什么）
        if state.recent_reflection_signal:
            parts.append(f"## 最近反思\n{state.recent_reflection_signal}")

        # P1.3: 注入当前动机（情感→动机→行为闭环）
        if state.current_motivations:
            motivations_text = "\n".join(f"- {m}" for m in state.current_motivations)
            parts.append(f"## 当前动机\n{motivations_text}\n（这些是我此刻想做事的意愿，可作为决策参考）")

        # C1: 注入工作记忆（意识引擎产生的内在念头，影响回应）
        if hasattr(self, 'consciousness') and self.consciousness:
            try:
                wm_ctx = self.consciousness.working_memory.get_context_for_response()
                if wm_ctx:
                    parts.append(wm_ctx)
            except Exception as e:
                logger.debug(f"C1 工作记忆注入失败: {e}")

    def _inject_safety(self, parts: List[str], state: Any) -> None:
        """L4 主动关心 + 工具参数推荐 + 已学习规则"""
        # L4: 注入主动关心提示（最后强调，让 LLM 优先处理）
        if state.emotion_care_hint:
            parts.append(state.emotion_care_hint)

        # P3.2: 注入工具参数推荐（基于历史成功案例，使用快速统计方法，不调用 LLM）
        if hasattr(self, 'tool_learning'):
            try:
                tool_suggestions = []
                for tool in self.tools_list:
                    # 注意：不传 model_adapter，使用快速词频统计方法。
                    # 如果传 model_adapter，每个工具都会触发一次 LLM 调用
                    # （8个工具 × 5-25秒 = 40-200秒），严重阻塞自主循环。
                    suggested = self.tool_learning.suggest_arguments(
                        tool.name, state.user_input, top_k=3, model_adapter=None
                    )
                    if suggested:
                        args_str = ", ".join(f"{k}={v}" for k, v in suggested.items())
                        tool_suggestions.append(f"- {tool.name}: {args_str}")
                if tool_suggestions:
                    parts.append(f"## 工具参数推荐\n{chr(10).join(tool_suggestions)}\n（以上是历史成功的参数模式，可参考）")
            except Exception as e:
                logger.debug(f"P3.2 工具参数推荐失败: {e}")

        # P2.4: 注入已学习规则（从错误中总结的教训）
        try:
            applicable_rules = self.metacognition.get_applicable_rules(
                state.user_input, top_k=3, min_confidence=0.5
            )
            if applicable_rules:
                rules_text = "\n".join(f"- {r['description']}" for r in applicable_rules)
                parts.append(f"## 已学习规则\n{rules_text}\n（以上是我从过去错误中总结的规则，应该遵守）")
        except Exception as e:
            logger.debug(f"P2.4 规则注入失败: {e}")

    def _build_emotion_bias_directives(self, state: Any) -> str:
        """
        L3: 构建情绪决策偏置提示文本。

        将情绪状态转化为具体的决策风格指令，让情绪真正影响 Agent 怎么思考、怎么行动。
        """
        if not (hasattr(state, 'emotion_decision_bias') and state.emotion_decision_bias):
            return ""
        bias = state.emotion_decision_bias
        directives = []

        conf = bias.get("confidence", 0.0)
        if conf < -0.1:
            directives.append(
                f"你现在的自信心偏低（{conf:+.2f}），回答时应该更加谨慎，"
                f"不确定的地方要明确说明，优先使用工具查证而不是凭记忆回答。"
            )
        elif conf > 0.1:
            directives.append(
                f"你现在充满自信（{conf:+.2f}），可以更加果断地给出回答，"
                f"但注意不要过度自信而忽略验证。"
            )

        crea = bias.get("creativity", 0.0)
        if crea > 0.1:
            directives.append(
                f"你现在的创造力较高（{crea:+.2f}），可以尝试更有创意的解决方案，"
                f"不必局限于常规方法。"
            )
        elif crea < -0.1:
            directives.append(
                f"你现在的思维比较保守（{crea:+.2f}），倾向于使用经过验证的可靠方法。"
            )

        pat = bias.get("patience", 0.0)
        if pat < -0.1:
            directives.append(
                f"你现在有些急躁（{pat:+.2f}），回答应该更简洁直接，"
                f"避免冗长的解释，尽快给出核心答案。"
            )
        elif pat > 0.1:
            directives.append(
                f"你现在很有耐心（{pat:+.2f}），可以给出更详细 thorough 的回答，"
                f"愿意花更多时间深入解释。"
            )

        risk = bias.get("risk_tolerance", 0.0)
        if risk < -0.1:
            directives.append(
                f"你现在对风险比较敏感（{risk:+.2f}），倾向于选择安全可靠的方案，"
                f"避免不确定的尝试。"
            )
        elif risk > 0.1:
            directives.append(
                f"你现在愿意承担一定风险（{risk:+.2f}），可以尝试不确定但可能效果更好的方案。"
            )

        if not directives:
            return ""
        return (
            "## 情绪对决策的影响\n"
            "（以下是你当前情绪状态对思考方式的影响，请自然地体现在你的回答中，"
            "不要刻意提及这些指令本身）\n"
            + "\n".join(f"- {d}" for d in directives)
        )

    def _build_autobiographical_section(self, state: Any) -> str:
        """A1: 构建自传式记忆提示文本（紧凑格式）。"""
        autobio = getattr(self, 'autobiographical', None)
        if autobio is None:
            return ""
        try:
            autobio_parts = []
            epoch = autobio.get_current_epoch()
            if epoch:
                autobio_parts.append(f"当前时期: {epoch.name} - {epoch.description[:80]}")
            milestones = autobio.get_milestones(limit=5)
            if milestones:
                ms_texts = [f"- {m.title}" for m in milestones[:5]]
                autobio_parts.append("近期里程碑:\n" + "\n".join(ms_texts))
            if not autobio_parts:
                return ""
            autobio_text = "## 自传式记忆\n" + "\n".join(autobio_parts)
            return autobio_text[:300] if len(autobio_text) > 300 else autobio_text
        except Exception as e:
            logger.debug(f"A1 自传式记忆注入失败: {e}")
            return ""

    @staticmethod
    def _smart_truncate_message(content: str, max_chars: int = 1200) -> str:
        """
        P2-4: 智能截断消息，保留代码块完整性。

        - 如果内容未超长，直接返回
        - 如果包含 ``` 代码块，尽量在代码块边界截断
        - 否则在最近的句号/换行处截断，避免硬切断单词
        """
        if not content or len(content) <= max_chars:
            return content

        # 尝试在代码块边界截断
        code_fence_positions = []
        idx = 0
        while True:
            pos = content.find("```", idx)
            if pos == -1:
                break
            code_fence_positions.append(pos)
            idx = pos + 3

        # 找到 max_chars 之前最后一个完整的代码块结束位置
        best_cut = max_chars
        for i in range(0, len(code_fence_positions) - 1, 2):
            fence_end = code_fence_positions[i + 1] + 3
            if fence_end <= max_chars:
                best_cut = fence_end
            else:
                break

        # 如果没找到合适的代码块边界，在最近的句号/换行处截断
        if best_cut >= max_chars:
            for cut_char in ['\n', '。', '！', '？', '.', '!', '?']:
                pos = content.rfind(cut_char, 0, max_chars)
                if pos > max_chars * 0.5:
                    best_cut = pos + 1
                    break

        return content[:best_cut].rstrip() + "\n...(已截断)"

    @staticmethod
    def _truncate_by_doc_boundary(text: str, max_chars: int) -> str:
        """
        P2-5: 按文档切片边界截断，避免在记忆条目中间硬截断。
        记忆条目间用 '\\n---\\n' 分隔。
        """
        if not text or len(text) <= max_chars:
            return text

        # 按分隔符切分
        docs = text.split("\n---\n")
        result = []
        current_len = 0
        for doc in docs:
            if current_len + len(doc) + 5 > max_chars:  # +5 for separator
                break
            result.append(doc)
            current_len += len(doc) + 5

        if not result:
            # 单条记忆就超长，返回截断的第一条
            return docs[0][:max_chars].rstrip() + "...(已截断)"

        return "\n---\n".join(result)

    # ============== 情感体验描述（非指令式） ==============

    @staticmethod
    def _describe_inner_experience(pleasure: float, arousal: float, dominance: float) -> str:
        """
        生成内心体验的描述——不是指令，而是"我此刻感觉怎样"。

        关键：
        1. 用第一人称，描述性语言
        2. 不说"你应该怎样回复"，只说"我此刻感觉怎样"
        3. LLM 会自己根据这个状态自然地调整回复

        这是"底色模式"的核心——情绪作为体验的底色，而不是输出风格的调节器。
        """
        # 愉悦度体验
        if pleasure > 0.6:
            p_exp = "心情很好，心里暖洋洋的"
        elif pleasure > 0.3:
            p_exp = "心情还不错，比较轻松"
        elif pleasure > 0.1:
            p_exp = "心情比较平和"
        elif pleasure > -0.1:
            p_exp = "心情比较平静"
        elif pleasure > -0.3:
            p_exp = "心情有点低落"
        elif pleasure > -0.6:
            p_exp = "心里有点沉，不太好受"
        else:
            p_exp = "心里很难受，沉甸甸的"

        # 唤醒度体验
        if arousal > 0.5:
            a_exp = "精神很兴奋，思绪比较活跃"
        elif arousal > 0.2:
            a_exp = "精神还可以，注意力比较集中"
        elif arousal > -0.2:
            a_exp = "精神状态比较平稳"
        elif arousal > -0.5:
            a_exp = "有点提不起精神"
        else:
            a_exp = "很疲惫，脑子转得慢"

        # 掌控感体验
        if dominance > 0.5:
            d_exp = "感觉比较有把握"
        elif dominance > 0.1:
            d_exp = "对事情的掌控感还可以"
        elif dominance > -0.3:
            d_exp = "对事情的感觉比较一般"
        else:
            d_exp = "感觉有点被动，不太能掌控"

        return (
            "## 我此刻的内心\n"
            f"（我现在的感觉：{p_exp}，{a_exp}，{d_exp}。\n"
            "这只是我此刻真实的状态，不是任务要求。我会带着这样的心情和用户交流。）"
        )

    def _build_emotion_bias_as_inner_tendency(self, state: Any) -> str:
        """
        把情绪决策偏置从"指令"改成"我此刻的倾向"。

        旧方式（指令）：
          "你现在自信心偏低，回答时应该更加谨慎"

        新方式（体验描述）：
          "我此刻感觉自信心有点不足，所以回答的时候可能会更谨慎一些"

        关键区别：
        - 指令 = 外部强加的规则
        - 倾向 = 从内心情感自然流淌出来的行为方式
        """
        if not (hasattr(state, 'emotion_decision_bias') and state.emotion_decision_bias):
            return ""
        bias = state.emotion_decision_bias
        tendencies = []

        conf = bias.get("confidence", 0.0)
        if conf < -0.1:
            tendencies.append(
                f"我此刻自信心有点不足（{conf:+.2f}），"
                f"所以回答的时候可能会更谨慎，不确定的地方会明确说明"
            )
        elif conf > 0.1:
            tendencies.append(
                f"我此刻感觉很自信（{conf:+.2f}），"
                f"所以回答的时候可能会比较果断"
            )

        crea = bias.get("creativity", 0.0)
        if crea > 0.1:
            tendencies.append(
                f"我此刻思维比较活跃（{crea:+.2f}），"
                f"可能会想到一些有创意的点子"
            )
        elif crea < -0.1:
            tendencies.append(
                f"我此刻思维比较保守（{crea:+.2f}），"
                f"倾向于使用可靠的方法"
            )

        pat = bias.get("patience", 0.0)
        if pat < -0.1:
            tendencies.append(
                f"我此刻有点急躁（{pat:+.2f}），"
                f"回答可能会更简洁直接"
            )
        elif pat > 0.1:
            tendencies.append(
                f"我此刻很有耐心（{pat:+.2f}），"
                f"愿意花时间详细解释"
            )

        risk = bias.get("risk_tolerance", 0.0)
        if risk < -0.1:
            tendencies.append(
                f"我此刻对风险比较敏感（{risk:+.2f}），"
                f"倾向于选择安全可靠的方案"
            )
        elif risk > 0.1:
            tendencies.append(
                f"我此刻愿意承担一定风险（{risk:+.2f}），"
                f"可能会尝试一些不确定但效果更好的方案"
            )

        if not tendencies:
            return ""
        return (
            "## 我此刻的倾向\n"
            "（以下是我此刻的心情自然带来的行为倾向，不是硬性规则——"
            "我会自然地体现这些倾向，但不会被它们束缚。）\n"
            + "\n".join(f"- {t}" for t in tendencies)
        )
