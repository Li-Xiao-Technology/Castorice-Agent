"""
自动生成的 Mixin：PostprocessingMixin
从 core.py 中拆分出来，与 CastoriceAgent 组合使用
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from castorice.model_adapter import ChatMessage
from castorice.utils import extract_json
from .common import logger, _get_alert_manager
logger = logging.getLogger(__name__)

class PostprocessingMemoryMixin:
    """后处理子 Mixin：_postprocess_emotion / _postprocess_experience / _postprocess_self_concept / _postprocess_social / _check_self_concept_consistency
    与其他子 Mixin 组合成 PostprocessingMixin。
    """
    async def _postprocess_emotion(self, state: State) -> None:
        """情绪更新：根据任务结果二次更新情感状态，归档情感事件"""
        user_input = state.user_input
        session_id = state.session_id

        # 情感引擎：根据任务结果二次更新 + 保存状态（L2 持久化）
        try:
            # 用任务成功状态再更新一次情感（影响 dominance/pleasure）
            # P2-bug: is_followup=True 避免重复增加 interaction_count
            # P0-4: 传入用户输入摘要+任务结果，让 LLM 能基于真实语境推理
            if state.emotion_detection is not None:
                result_hint = "成功" if state.success else f"失败({'; '.join(state.errors[:1]) if state.errors else '未知'})"
                await asyncio.to_thread(
                    self.emotion_engine.update,
                    user_input=f"[任务结果反馈] 用户: {user_input[:100]} | 结果: {result_hint}",
                    task_success=state.success,
                    is_followup=True,
                    context_hint="",
                )
            # P1-2: emotion_engine.save() 是同步阻塞的磁盘写入，用 to_thread 避免阻塞事件循环
            await asyncio.to_thread(self.emotion_engine.save)
        except (OSError, ValueError, RuntimeError) as e:
            logger.warning(f"情感状态保存失败: {e}")

        # L4: 情感事件归档到长期记忆（兼容旧字段名）
        try:
            if (
                state.emotion_detection
                and state.emotion_detection.get("is_significant_event")
                and self.long_term is not None
            ):
                event_summary = state.emotion_detection.get("event_summary", "情感事件")
                # P1-2: long_term.add() 是同步阻塞（ChromaDB 写入），用 to_thread 避免阻塞
                await asyncio.to_thread(
                    self.long_term.add,
                    event_summary + f" | 用户原话: {user_input[:100]}",
                    {
                        "type": "emotion_event",
                        "valence": state.emotion_detection.get("user_emotion_valence",
                                    state.emotion_detection.get("valence", "neutral")),
                        "inner_thought": state.emotion_detection.get("agent_inner_thought", ""),
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "session_id": session_id,
                    },
                )
                logger.info(f"L4: 情感事件已归档 ({event_summary})")
        except (OSError, IOError, PermissionError, ValueError, AttributeError) as e:
            logger.warning(f"L4 情感事件归档失败: {e}")

    async def _postprocess_experience(self, state: State) -> None:
        """经历流和记忆写入：本轮交互写入经历流、写入短时记忆"""
        user_input = state.user_input
        session_id = state.session_id

        # 自我进化：本轮交互写入经历流（episodic 类型）
        if self.experience_journal is not None:
            try:
                logger.debug("开始写入经历流...")
                # 重要性评分：基于情感强度 + 任务结果 + 是否有反思事件
                importance = 5.0
                emotional_valence = 0.0
                if state.emotion_detection:
                    dp = state.emotion_detection.get("agent_pad_delta", (0, 0, 0))[0]
                    emotional_valence = max(-1.0, min(1.0, dp * 2))
                    if state.emotion_detection.get("is_significant_event"):
                        importance = 7.0
                if not state.success:
                    importance = max(importance, 6.0)

                # 经历内容：自然语言描述本轮交互
                content_parts = [f"用户: {user_input[:200]}"]
                if state.final_answer:
                    content_parts.append(f"我: {state.final_answer[:200]}")
                if not state.success:
                    content_parts.append(f"结果: 失败 ({'; '.join(state.errors[:2]) if state.errors else '未知错误'})")
                else:
                    content_parts.append("结果: 成功")
                if state.emotion_detection and state.emotion_detection.get("agent_inner_thought"):
                    content_parts.append(f"内心: {state.emotion_detection['agent_inner_thought']}")

                logger.debug("调用 experience_journal.add_simple...")
                await asyncio.to_thread(
                    self.experience_journal.add_simple,
                    " | ".join(content_parts),
                    "episodic",
                    importance,
                    emotional_valence,
                    session_id,
                    {
                        "intent": state.intent_type,
                        "success": state.success,
                        "tool_count": len(state.tool_calls),
                        "inner_thought": state.emotion_detection.get("agent_inner_thought", "") if state.emotion_detection else "",
                    },
                )
                logger.debug("经历流写入完成")
            except (OSError, IOError, PermissionError, ValueError, RuntimeError) as e:
                logger.warning(f"经历流写入失败: {e}")

        # 写入短时记忆
        try:
            logger.debug("开始写入短时记忆...")
            from castorice.memory.short_term import Message
            await asyncio.to_thread(
                self.short_term.add_message, session_id, Message(role="user", content=user_input)
            )
            await asyncio.to_thread(
                self.short_term.add_message,
                session_id,
                Message(role="assistant", content=state.final_answer,
                        metadata={"intent": state.intent_type, "success": state.success}),
            )
            logger.debug("短时记忆写入完成")
        except (OSError, IOError, PermissionError, ValueError) as e:
            logger.warning(f"短时记忆写入失败: {e}")

    async def _postprocess_self_concept(self, state: State) -> None:
        """自我概念一致性检测：检测 Agent 行为是否与自我概念一致"""
        user_input = state.user_input

        # ============================================================
        # 自我概念→行为闭环：行为一致性检测
        # Agent 说了自己是X，但行为是否真的符合X？不一致时触发反思
        # ============================================================
        if (self.self_concept is not None
            and not self.self_concept.is_empty()
            and state.final_answer):
            try:
                consistency_check = await asyncio.to_thread(
                    self._check_self_concept_consistency,
                    state.final_answer,
                    user_input,
                )
                if consistency_check:
                    is_consistent, inconsistency_reason = consistency_check
                    if not is_consistent:
                        logger.info(f"自我概念一致性检测: 发现不一致 — {inconsistency_reason[:80]}")
                        # P2-2: 通过统一反思调度器触发
                        await self._try_reflection(state, trigger="inconsistency")
            except (OSError, ValueError, RuntimeError) as e:
                logger.debug(f"自我概念一致性检测失败: {e}")

    async def _postprocess_social(self, state: State) -> None:
        """社会关系更新：S1 关系状态、A1 自传式记忆"""
        user_input = state.user_input
        session_id = state.session_id

        # S1: 社会关系更新 - 每轮交互后更新关系状态
        if hasattr(self, 'social_relation'):
            try:
                user_id = getattr(state, 'user_id', session_id)
                interaction_quality = 0.6 if state.success else 0.3
                emotional_intensity = getattr(state, 'emotion_valence', 0.0)
                user_feedback = user_input[-50:] if len(user_input) > 50 else user_input
                await asyncio.to_thread(
                    self.social_relation.update_relation,
                    user_id,
                    interaction_quality,
                    state.success,
                    emotional_intensity,
                    user_feedback,
                    user_input[:200],
                )
            except (OSError, ValueError, RuntimeError) as e:
                logger.warning(f"S1 关系更新失败: {e}")

        # A1: 自传式记忆 - 每轮交互计数 + 时期转换检测
        if hasattr(self, 'autobiographical'):
            try:
                await asyncio.to_thread(self.autobiographical.record_interaction)
                # 检测是否进入新时期
                new_epoch = await asyncio.to_thread(
                    self.autobiographical.check_epoch_transition
                )
                if new_epoch:
                    logger.info(f"A1 进入新时期: {new_epoch.name}")
                    # LLM驱动的时期总结
                    try:
                        milestones = await asyncio.to_thread(
                            self.autobiographical.get_milestones, limit=20
                        )
                        events = await asyncio.to_thread(
                            self.autobiographical.get_events, limit=20
                        )
                        await asyncio.to_thread(
                            self.autobiographical.summarize_epoch_with_llm,
                            new_epoch,
                            self.model,
                            milestones,
                            events,
                        )
                    except (OSError, ValueError, RuntimeError) as e:
                        logger.debug(f"A1 时期LLM总结失败: {e}")
                # 检测首次启动里程碑
                ms_count = len(self.autobiographical.get_milestones(limit=100))
                if not ms_count:
                    await asyncio.to_thread(
                        self.autobiographical.add_milestone,
                        "第一次与用户交互",
                        "第一次成功回应用户输入，标志着我的旅程的开始。",
                        category="first_achievement",
                        importance=9.0,
                        session_id=session_id,
                    )
                # 检测数量里程碑
                total = getattr(self.autobiographical, '_total_interactions', 0)
                if total in [10, 50, 100, 500, 1000]:
                    await asyncio.to_thread(
                        self.autobiographical.add_milestone,
                        f"第 {total} 次交互",
                        f"完成了第 {total} 次交互，又一个里程碑!",
                        category="achievement",
                        importance=7.0 if total >= 100 else 5.0,
                        session_id=session_id,
                    )
            except (OSError, ValueError, RuntimeError) as e:
                logger.warning(f"A1 自传式记忆更新失败: {e}")

    def _check_self_concept_consistency(self, answer: str, user_input: str) -> tuple:
        """
        检查 Agent 的回答是否与自我概念一致
        
        如果 Agent 在自我概念中说自己"耐心"但回答很急躁，
        或者说自己"严谨"但回答很草率，就检测为不一致。
        
        不一致时触发反思，让 Agent 自己面对矛盾。
        
        Args:
            answer: Agent 的最终回答
            user_input: 用户输入
        
        Returns:
            (is_consistent, reason) — 一致为 True，不一致为 False + 原因
        """
        try:
            from castorice.model_adapter import ChatMessage
            
            sc_content = self.self_concept.load()
            if not sc_content.strip():
                return True, ""  # 没有自我概念就不检测
            
            # 取自我概念的前 500 字（避免 prompt 过长）
            sc_brief = sc_content[:500]
            
            prompt = f"""请检查以下回答是否与 Agent 的自我概念一致。

【Agent 的自我概念摘要】
{sc_brief}

【用户输入】
{user_input[:200]}

【Agent 的回答】
{answer[:300]}

请判断回答是否与自我概念中描述的行为模式、性格特征、价值观一致。
以 JSON 格式返回（不要其他内容）：
{{
  "is_consistent": true/false,
  "reason": "如果不一致，说明哪里矛盾；如果一致，简述为什么一致"
}}"""

            response = self.model.chat([
                ChatMessage(role="system", content="你是一个自我意识监测系统，负责检查 Agent 的行为是否与其自我概念一致。只输出 JSON。"),
                ChatMessage(role="user", content=prompt),
            ])
            raw = response.content if hasattr(response, "content") else str(response)
            
            # 解析 JSON
            import json
            import re
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                m = re.search(r'\{[\s\S]+\}', raw)
                if m:
                    try:
                        parsed = json.loads(m.group(0))
                    except json.JSONDecodeError:
                        return True, ""  # 解析失败就不检测
                else:
                    return True, ""
            
            return bool(parsed.get("is_consistent", True)), parsed.get("reason", "")
        except (OSError, ValueError, RuntimeError) as e:
            logger.debug(f"自我概念一致性检测异常: {e}")
            return True, ""  # 出错时不阻断
