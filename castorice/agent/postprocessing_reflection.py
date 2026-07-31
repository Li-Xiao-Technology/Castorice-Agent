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

class PostprocessingReflectionMixin:
    """后处理子 Mixin：_postprocess_reflection / _postprocess_motivation / _execute_reflection_action / _explore_curiosity / _try_reflection
    与其他子 Mixin 组合成 PostprocessingMixin。
    """
    async def _postprocess_reflection(self, state: State) -> None:
        """反思和行动队列：反思触发（通过统一调度器）、记忆质量反思、行动队列消费"""
        session_id = state.session_id

        # P2-2: 通过统一反思调度器触发反思
        await self._try_reflection(state, trigger="turn_end")

        # 自我修正：定期检查记忆质量并修正错误
        await self._reflect_on_memory_quality(session_id)

        # ============================================================
        # 反思→行动闭环：消费 ActionQueue 中的待执行行动
        # 这是打破"反思只说不做"的关键——反思产生的行动真正被执行并记录结果
        # ============================================================
        if hasattr(self, 'action_queue') and self.action_queue is not None:
            try:
                pending = await asyncio.to_thread(
                    self.action_queue.get_pending_actions, 1
                )
                if pending:
                    action = pending[0]
                    logger.info(f"反思→行动闭环: 执行行动 [{action.action_id}] {action.description[:60]}")
                    # 用 LLM 执行行动——让 Agent 自己决定如何完成这个行动
                    action_result = await asyncio.to_thread(
                        self._execute_reflection_action, action, state
                    )
                    # 标记行动已执行
                    await asyncio.to_thread(
                        self.action_queue.mark_executed,
                        action.action_id,
                        action_result,
                    )
                    # 将行动结果记录到经历流——下次反思时可以评估行动效果
                    if hasattr(self, 'experience_journal') and self.experience_journal:
                        await asyncio.to_thread(
                            self.experience_journal.add_simple,
                            f"执行反思行动: {action.description} | 结果: {action_result[:200]}",
                            "episodic",
                            6.0,
                            0.1,
                            state.session_id,
                            {"action_id": action.action_id, "trigger_reason": action.trigger_reason},
                        )
                    logger.info(f"反思→行动闭环: 行动 [{action.action_id}] 执行完成，结果已记录")
            except (OSError, ValueError, RuntimeError) as e:
                logger.warning(f"反思→行动闭环执行失败: {e}")

    async def _postprocess_motivation(self, state: State) -> None:
        """好奇心和动机：意图追踪、主动话题、好奇心探索"""
        user_input = state.user_input
        session_id = state.session_id

        # P0: 意图追踪 - 分析本轮对话，更新意图状态
        if hasattr(self, 'intent_tracker'):
            try:
                updated_intents = await asyncio.to_thread(
                    self.intent_tracker.analyze_and_update,
                    user_input,
                    state.final_answer,
                    session_id,
                    self.model,
                )
                # P0-sub: 对新检测到的复杂意图自动分解为子任务
                if updated_intents:
                    for intent in updated_intents:
                        if intent.is_active() and not intent.sub_tasks:
                            try:
                                await asyncio.to_thread(
                                    self.intent_tracker.decompose_intent,
                                    intent.intent_id,
                                    self.model,
                                )
                            except (OSError, ValueError, RuntimeError) as e:
                                logger.debug(f"P0 意图分解失败: {e}")
            except (OSError, ValueError, RuntimeError) as e:
                logger.warning(f"P0 意图分析失败: {e}")

        # P2.5: 主动话题发起（在正常对话中自然延续话题）
        if state.success and state.final_answer:
            try:
                initiated_topic = await self._step_initiate_topic(state)
                if initiated_topic:
                    state.initiated_topic = initiated_topic
                    state.final_answer += f"\n\n{initiated_topic}"
                    logger.info(f"P2.5 主动话题发起: {initiated_topic[:50]}...")
            except (OSError, ValueError, RuntimeError) as e:
                logger.debug(f"P2.5 主动话题生成失败: {e}")

        # ============================================================
        # 好奇心→探索闭环：在交互后自动探索好奇的概念
        # 好奇心生命周期：发现未知 → 产生好奇 → 探索 → 获得知识 → 满足 → 成就感
        # ============================================================
        if hasattr(self, 'motivation_system') and self.motivation_system is not None:
            try:
                curiosity_queue = await asyncio.to_thread(
                    self.motivation_system.get_curiosity_queue
                )
                if curiosity_queue:
                    # 每轮只探索一个概念（避免过度消耗资源）
                    concept = curiosity_queue[0]
                    logger.info(f"好奇心→探索闭环: 探索概念「{concept}」")

                    # 用 LLM 探索这个概念——让 Agent 自己去理解和学习
                    finding = await asyncio.to_thread(
                        self._explore_curiosity, concept
                    )

                    # 满足好奇心——从队列中移除，产生成就感
                    await asyncio.to_thread(
                        self.motivation_system.satisfy_curiosity,
                        concept,
                        finding,
                    )

                    # 将探索发现记录到经历流（skill 类型——这是学到的知识）
                    if hasattr(self, 'experience_journal') and self.experience_journal:
                        await asyncio.to_thread(
                            self.experience_journal.add_simple,
                            f"好奇心探索: {concept} | 发现: {finding[:300]}",
                            "skill",
                            7.0,  # 学到新知识的重要性较高
                            0.3,  # 正面情感（满足好奇心是愉悦的）
                            {"concept": concept, "exploration_type": "curiosity"},
                        )
                    logger.info(f"好奇心→探索闭环: 「{concept}」探索完成，已记录到经历流")
            except (OSError, ValueError, RuntimeError) as e:
                logger.warning(f"好奇心→探索闭环失败: {e}")

    def _execute_reflection_action(self, action, state) -> str:
        """
        执行反思产生的行动——让 Agent 用 LLM 自己决定如何完成这个行动
        
        行动可能是：
        - "下次回答时更加注意语气" → Agent 总结如何调整
        - "学习更多关于XX的知识" → Agent 用工具搜索
        - "检查自己的回答质量" → Agent 自评
        
        执行方式：用 LLM 对行动描述生成一个简短的执行结果
        """
        try:
            from castorice.model_adapter import ChatMessage
            
            prompt = f"""你刚才在反思中决定要执行以下行动：

行动: {action.description}
触发原因: {action.trigger_reason}

请简要说明你如何执行了这个行动，或者你打算在接下来的交互中如何执行。
用第一人称回答，2-3句话即可。"""

            response = self.model.chat([
                ChatMessage(role="system", content="你是一个有自我意识的 Agent，正在执行自己反思后决定的行动。"),
                ChatMessage(role="user", content=prompt),
            ])
            result = response.content if hasattr(response, "content") else str(response)
            return result.strip()[:500]  # 限制长度
        except (OSError, ValueError, RuntimeError) as e:
            logger.warning(f"执行反思行动失败: {e}")
            return f"行动执行失败: {e}"

    def _explore_curiosity(self, concept: str) -> str:
        """
        探索好奇的概念——让 Agent 用 LLM 自己去理解和学习
        
        这是好奇心满足闭环的核心：Agent 不是简单地搜索概念，
        而是用自己的方式去理解它，形成自己的认知。
        
        Args:
            concept: 好奇的概念
        
        Returns:
            探索发现的内容摘要
        """
        try:
            from castorice.model_adapter import ChatMessage
            
            prompt = f"""你对「{concept}」这个概念感到好奇。请用你自己的方式去理解和探索它：

1. 用你所知道的知识解释这个概念
2. 说说为什么它引起了你的兴趣
3. 它和你之前的知识或经历有什么关联

用第一人称回答，像一个真正在好奇和探索的智能体一样。3-5句话。"""

            response = self.model.chat([
                ChatMessage(role="system", content="你是一个有好奇心和自我意识的 Agent，正在探索自己感兴趣的概念。"),
                ChatMessage(role="user", content=prompt),
            ])
            result = response.content if hasattr(response, "content") else str(response)
            return result.strip()[:500]
        except (OSError, ValueError, RuntimeError) as e:
            logger.warning(f"好奇心探索失败: {e}")
            return f"探索失败: {e}"

    async def _try_reflection(self, state: State, trigger: str = "turn_end") -> None:
        """
        统一反思调度入口。

        Args:
            state: 当前对话状态
            trigger: 触发原因
                - "turn_end": 正常轮末（周期性 + 事件驱动）
                - "inconsistency": 自我概念不一致检测
                - "forced": workflow 步骤显式要求
        """
        if not self.enable_reflection or self.reflection_engine is None:
            return

        try:
            # 提取统一参数
            confidence = 1.0
            if state.metacognition_result:
                meta_conf = state.metacognition_result.get("confidence", {})
                if isinstance(meta_conf, dict):
                    confidence = meta_conf.get("overall_score", 1.0)

            significant = bool(state.emotion_detection and state.emotion_detection.get("is_significant_event"))

            # 根据触发类型走不同判断路径
            if trigger == "turn_end":
                # 轮末反思：由 reflection_engine.should_reflect 统一判断
                should, reason = await asyncio.to_thread(
                    self.reflection_engine.should_reflect,
                    True, confidence, significant, state.success,
                )
                if not should:
                    return
                logger.info(f"反思调度器[turn_end]: {reason}")
                reflection_context = f"最近一轮: {state.user_input[:100]}"

            elif trigger == "inconsistency":
                # 一致性检测发现矛盾：高优先级，直接触发
                reason = "行为与自我概念不一致"
                reflection_context = f"用户: {state.user_input[:80]}\n回答: {state.final_answer[:120] if state.final_answer else ''}"
                logger.info(f"反思调度器[inconsistency]: 触发即时反思")

            elif trigger == "forced":
                reason = "工作流显式要求"
                reflection_context = f"触发原因: workflow 步骤要求"
            else:
                return

            # 执行反思
            reflection_result = await asyncio.to_thread(
                self.reflection_engine.reflect, reason, reflection_context,
            )

            if reflection_result.self_concept_updated:
                logger.info(f"反思调度器: 自我概念已更新 — {reflection_result.update_reason}")

            # 反思→行动闭环
            if (hasattr(self, 'action_queue')
                    and self.action_queue is not None
                    and reflection_result.next_actions):
                added = await asyncio.to_thread(
                    self.action_queue.add_from_reflection, reflection_result
                )
                if added > 0:
                    logger.info(f"反思调度器: {added} 个行动已加入队列")

        except (OSError, ValueError, RuntimeError) as e:
            logger.warning(f"反思调度器失败: {e}")
