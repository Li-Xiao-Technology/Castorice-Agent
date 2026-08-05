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

class PostprocessingSafetyMixin:
    """后处理子 Mixin：_postprocess_safety / _postprocess_metacognition
    与其他子 Mixin 组合成 PostprocessingMixin。
    """
    async def _postprocess_safety(self, state: State, elapsed_ms: float) -> None:
        """安全检查和回滚管理：记录任务、回滚检查、自我保护、沙盒评估"""
        user_input = state.user_input

        # 自感知：记录任务完成
        await asyncio.to_thread(
            self.self_awareness.record_task, user_input, success=state.success, elapsed_ms=elapsed_ms
        )

        # P3.4: 回滚管理器 - 记录任务结果并检查是否需要回滚
        try:
            rollback_mgr = getattr(self, 'rollback_manager', None)
            if rollback_mgr is None:
                from castorice.security.rollback import get_rollback_manager
                rollback_mgr = get_rollback_manager()
            rollback_mgr.record_task(state.success)
            for err in state.errors:
                rollback_mgr.record_error(err)
            should_rollback, reason = rollback_mgr.should_rollback()
            if should_rollback:
                logger.warning(f"P3.4 触发自动回滚: {reason}")
                rolled_back_items = []
                if hasattr(self, 'self_concept') and hasattr(self.self_concept, 'revert'):
                    try:
                        self.self_concept.revert()
                        rolled_back_items.append("self_concept")
                    except (OSError, ValueError, RuntimeError) as e:
                        logger.debug(f"回滚 self_concept 失败: {e}")
                if hasattr(self, 'emotion_engine') and hasattr(self.emotion_engine, 'reset'):
                    try:
                        self.emotion_engine.reset()
                        rolled_back_items.append("emotion_engine")
                    except (OSError, ValueError, RuntimeError) as e:
                        logger.debug(f"回滚 emotion_engine 失败: {e}")
                if hasattr(self, 'long_term') and hasattr(self.long_term, 'cleanup_old_memories'):
                    try:
                        from datetime import timedelta
                        cutoff = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
                        cleaned = self.long_term.cleanup_old_memories(cutoff)
                        if cleaned > 0:
                            rolled_back_items.append(f"long_term_memory({cleaned})")
                    except (OSError, IOError, PermissionError, ValueError) as e:
                        logger.debug(f"回滚 long_term_memory 失败: {e}")
                if hasattr(self, 'metacognition') and hasattr(self.metacognition, '_learned_rules'):
                    try:
                        removed = 0
                        cutoff = datetime.now(timezone.utc).timestamp() - 600
                        for rule_id in list(self.metacognition._learned_rules.keys()):
                            rule = self.metacognition._learned_rules.get(rule_id, {})
                            created = rule.get('created_at', 0)
                            if isinstance(created, str):
                                try:
                                    created = datetime.fromisoformat(created).timestamp()
                                except (ValueError, TypeError):
                                    created = 0
                            if created > cutoff:
                                del self.metacognition._learned_rules[rule_id]
                                removed += 1
                        if removed > 0:
                            rolled_back_items.append(f"metacognition_rules({removed})")
                    except (OSError, ValueError, RuntimeError) as e:
                        logger.debug(f"回滚 metacognition_rules 失败: {e}")
                rollback_mgr.mark_rollback(reason, rolled_back_items)
        except (OSError, ValueError, RuntimeError) as e:
            logger.warning(f"P3.4 回滚检查失败: {e}")

        # P3.6: 自我保护系统 - 核心文件完整性验证
        try:
            integrity_ok = await asyncio.to_thread(self.self_protection.verify_core_integrity)
            if not integrity_ok:
                logger.warning("P3.6 自我保护: 核心文件完整性验证失败")
                # 触发自动恢复机制
                await asyncio.to_thread(self.self_protection.auto_recover)
            else:
                logger.debug("P3.6 自我保护: 核心文件完整性验证通过")
        except (OSError, ValueError, RuntimeError) as e:
            logger.warning(f"P3.6 自我保护检查失败: {e}")

        # P3.7: 实验沙盒 - 评估正在进行的实验（如果有）
        if self.experimental_sandbox is not None:
            try:
                if self.experimental_sandbox.has_active_experiment():
                    experiment_result = await asyncio.to_thread(
                        self.experimental_sandbox.evaluate_experiment
                    )
                    logger.info(
                        f"P3.7 沙盒实验评估: success={experiment_result.success}, "
                        f"changes={len(experiment_result.changes)}, "
                        f"merged={experiment_result.merged}"
                    )
            except (OSError, ValueError, RuntimeError) as e:
                logger.warning(f"P3.7 沙盒评估失败: {e}")

    async def _postprocess_metacognition(self, state: State, stream_callback: Optional[Callable[[str], None]] = None) -> None:
        """元认知评估：生成反思、低置信度处理、图片补全"""
        user_input = state.user_input

        # 元认知：生成反思
        tool_results = [tc["result"] for tc in state.tool_calls]
        # P0-2: 追加本轮最终答案到 previous_answers，供元认知一致性检测使用
        if state.final_answer:
            state.previous_answers.append(state.final_answer)
            # 限制长度避免无限增长（保留最近 10 轮）
            if len(state.previous_answers) > 10:
                state.previous_answers = state.previous_answers[-10:]
        state.metacognition_result = await asyncio.to_thread(
            self.metacognition.reflect,
            user_input=user_input,
            answer=state.final_answer,
            tool_results=tool_results,
            previous_answers=state.previous_answers,
        )
        meta = state.metacognition_result
        logger.info(
            f"元认知反思: 置信度={meta['confidence'].overall_score:.2f}, "
            f"幻觉风险={meta['confidence'].hallucination_risk}, "
            f"质量分={meta['quality'].score:.1f}"
        )

        # 元认知：如果置信度太低，自动补充提示
        if meta["should_reconsider"] and state.final_answer:
            # L3: 情绪影响元认知阈值（高愉悦 -> 放宽阈值，可能撤销重新考虑）
            try:
                workflow_adj = self.emotion_engine.get_workflow_adjustment()
                delta = workflow_adj.get("confidence_threshold_delta", 0.0)
                if delta < -0.05 and meta["confidence"].overall_score > 0.5:
                    logger.info(f"L3: 情绪良好(delta={delta})，放宽元认知阈值，不重新考虑")
                    meta["should_reconsider"] = False
                elif delta > 0.05:
                    logger.info(f"L3: 情绪低落(delta={delta})，收紧元认知阈值，强制重新考虑")
            except (OSError, ValueError, RuntimeError) as e:
                logger.warning(f"L3 元认知阈值调整失败: {e}")

        if meta["should_reconsider"] and state.final_answer:
            logger.warning("元认知: 回答质量不足，建议重新考虑")
            state.final_answer = self._append_uncertainty_note(state.final_answer, meta)

            # P2.4: 从错误中学习——元认知检测到低质量回答时自动生成规则
            try:
                mistake_desc = f"低质量回答: 用户输入='{user_input[:100]}', 置信度={meta['confidence'].overall_score:.2f}, 幻觉风险={meta['confidence'].hallucination_risk}"
                rule_proposal = f"当用户输入类似'{user_input[:50]}'时，应该先调用工具查证，而不是直接回答"
                self.metacognition.learn_from_mistake(
                    mistake_description=mistake_desc,
                    rule_proposal=rule_proposal,
                    confidence=meta["confidence"].overall_score,
                )
            except (OSError, ValueError, RuntimeError) as e:
                logger.debug(f"P2.4 从错误学习失败: {e}")

            # P0-3: 告警系统接入 - 元认知低置信度
            try:
                _get_alert_manager().info(
                    title="元认知置信度低",
                    message=f"session={state.session_id} 置信度={meta['confidence'].overall_score:.2f} 幻觉风险={meta['confidence'].hallucination_risk} 用户需求: {user_input[:100]}",
                    cooldown_key=f"low_confidence_{state.session_id}",
                )
            except (OSError, ValueError, RuntimeError) as e:
                logger.warning(f"元认知低置信度告警发送失败: {e}")

        # 兜底：如果最终回答中没有 Markdown 图片格式，从工具结果中补上
        # P1-4: 先补全图片，再把增量图片通过 stream_callback 推送（避免流式内容丢图）
        answer_before = state.final_answer
        state.final_answer = self._ensure_images_in_answer(state.final_answer, state.tool_calls)
        # P1-4: 如果 _ensure_images_in_answer 追加了图片且 stream_callback 存在，把图片增量推送出去
        if stream_callback and callable(stream_callback) and state.final_answer != answer_before:
            appended = state.final_answer[len(answer_before):]
            if appended.strip():
                try:
                    stream_callback(appended)
                except (OSError, ValueError, RuntimeError) as e:
                    logger.warning(f"图片增量流式推送失败: {e}")
