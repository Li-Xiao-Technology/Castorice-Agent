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
        统一构建系统提示，注入：
        - 基础提示（角色/工具说明）
        - L1 性格设定（静态人格）
        - 当前时间（确保 Agent 知道当前日期）
        - L2 当前情绪状态（动态 PAD 状态）
        - 思维策略
        - 对话风格调整
        - 用户画像
        - 长期记忆（跨会话知识）
        - 短期记忆（当前会话历史对话）
        - L4 主动关心提示（检测到近期负面事件时）

        避免在 _step_tool_loop 和 _step_answer 中重复拼装。
        """
        parts = [base_prompt] if base_prompt else []

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
        now_local = datetime.now()
        now_utc = datetime.now(timezone.utc)
        week_days = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
        parts.append(
            f"## 当前时间\n"
            f"本地时间: {now_local.strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"UTC时间: {now_utc.strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"星期: {week_days[now_local.weekday()]}\n"
            f"年份: {now_local.year}"
        )

        # L2: 注入当前情绪状态
        if state.emotion_state_prompt:
            parts.append(state.emotion_state_prompt)

        # 注入思维策略
        if state.thinking_strategy_prompt:
            parts.append(f"## 思维策略\n{state.thinking_strategy_prompt}")

        # 注入对话风格调整
        if state.dialogue_adjustment:
            parts.append(state.dialogue_adjustment)

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

        # A1: 注入自传式记忆（自我叙事）
        if hasattr(self, 'autobiographical'):
            try:
                story_prompt = self.autobiographical.to_prompt(max_milestones=6)
                if story_prompt:
                    parts.append(story_prompt)
            except Exception as e:
                logger.debug(f"A1 自传式记忆注入失败: {e}")

        # L4: 注入主动关心提示（最后强调，让 LLM 优先处理）
        if state.emotion_care_hint:
            parts.append(state.emotion_care_hint)

        # P1.2: 注入最近反思信号（让 Agent 知道自己上次反思学到了什么）
        if state.recent_reflection_signal:
            parts.append(f"## 最近反思\n{state.recent_reflection_signal}")

        # P1.3: 注入当前动机（情感→动机→行为闭环）
        if state.current_motivations:
            motivations_text = "\n".join(f"- {m}" for m in state.current_motivations)
            parts.append(f"## 当前动机\n{motivations_text}\n（这些是我此刻想做事的意愿，可作为决策参考）")

        # P3.2: 注入工具参数推荐（基于历史成功案例，LLM 智能推断）
        if hasattr(self, 'tool_learning'):
            try:
                tool_suggestions = []
                for tool in self.tools_list:
                    suggested = self.tool_learning.suggest_arguments(
                        tool.name, state.user_input, top_k=3, model_adapter=self.model
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

        return "\n\n".join(parts) if parts else ""

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
