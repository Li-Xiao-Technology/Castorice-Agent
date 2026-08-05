"""
自动生成的 Mixin：SilentRoundMixin
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
from .common import logger
logger = logging.getLogger(__name__)


class SilentRoundMixin:
    def check_quiet_round_action(self, session_id: str) -> Optional[str]:
        """
        检查是否应该触发主动行为（静默轮）

        :param session_id: 会话 ID
        :return: 如果应该主动发起对话，返回主动对话内容；否则返回 None
        """
        if not self._quiet_round_enabled:
            return None

        last_time = self._last_input_time.get(session_id, 0)
        if last_time == 0:
            return None

        seconds_since = time.time() - last_time
        if seconds_since < 60:
            return None

        emotion_state = None
        if self.emotion_engine and self.emotion_engine._state:
            emotion_state = {
                "pleasure": self.emotion_engine._state.pleasure,
                "arousal": self.emotion_engine._state.arousal,
                "dominance": self.emotion_engine._state.dominance,
            }

        # P1: 优先检查行动队列（反思产生的行动具有最高优先级）
        if hasattr(self, 'action_queue'):
            try:
                highest_action = self.action_queue.get_highest_priority()
                if highest_action:
                    logger.info(f"P1 行动队列触发: {highest_action.description[:50]}")
                    system_prompt = self._build_system_prompt(State(session_id=session_id))
                    action_prompt = f"""你有一个待执行的行动：{highest_action.description}。
                    这是从自我反思中产生的行动，需要优先执行。请以自然、友好的方式发起对话，推进这个行动。

                    要求：
                    - 自然提及行动内容
                    - 保持简短
                    - 开放式结尾，鼓励用户回应"""

                    response = self.model.chat([
                        ChatMessage("system", system_prompt + "\n\n" + action_prompt),
                        ChatMessage("user", "[主动行为] 根据当前情境，生成一段自然的主动对话内容。"),
                    ])
                    content = response.content if hasattr(response, "content") else str(response)
                    # 标记行动已执行
                    self.action_queue.mark_executed(highest_action.action_id, content[:100])
                    return content
            except (OSError, ValueError, RuntimeError) as e:
                logger.debug(f"P1 行动队列执行失败: {e}")

        result = self.motivation_system.should_initiate_action(
            seconds_since_last_input=seconds_since,
            emotion_state=emotion_state,
            intent_tracker=self.intent_tracker if hasattr(self, 'intent_tracker') else None,
            social_relation=self.social_relation if hasattr(self, 'social_relation') else None,
            user_id=session_id,
        )

        if not result.get("should_initiate"):
            return None

        action_type = result.get("action_type", "")
        reason = result.get("reason", "")
        target = result.get("target", "")

        logger.info(f"P2.3 触发主动行为: type={action_type}, reason={reason}, target={target}")

        system_prompt = self._build_system_prompt(State(session_id=session_id))

        action_prompt = self._get_quiet_round_prompt(action_type, target)

        try:
            response = self.model.chat([
                ChatMessage("system", system_prompt + "\n\n" + action_prompt),
                ChatMessage("user", "[主动行为] 根据当前情境，生成一段自然的主动对话内容。"),
            ])
            content = response.content.strip()
            
            # 动机→主动行为闭环：记录主动行为发起
            if content and hasattr(self, 'motivation_system') and self.motivation_system:
                self.motivation_system.record_proactive_action(action_type)
                # 将主动行为记录到经历流
                if hasattr(self, 'experience_journal') and self.experience_journal:
                    try:
                        self.experience_journal.add_simple(
                            f"主动行为[{action_type}]: {content[:200]} | 原因: {reason}",
                            "episodic",
                            5.0,
                            0.1,
                            session_id,
                            {"action_type": action_type, "target": target, "proactive": True},
                        )
                    except (OSError, ValueError, RuntimeError) as e:
                        logger.debug(f"主动行为经验记录失败: {e}")
                logger.info(f"动机→主动行为闭环: 主动行为已记录，等待用户反馈")
            
            return content
        except (OSError, ValueError, RuntimeError) as e:
            logger.warning(f"P2.3 主动行为生成失败: {e}")
            return None

    def _get_quiet_round_prompt(self, action_type: str, target: str) -> str:
        """获取静默轮主动行为的提示文本。"""
        action_prompts = {
            "curiosity": f"""基于以下信息，主动发起关于「{target}」的对话。
            你对这个概念感到好奇，想了解更多。请以自然、友好的方式提出问题或分享想法。

            要求：
            - 不要生硬，像自然想到一样
            - 保持简短（3-5句话）
            - 开放式问题，鼓励用户回应""",

            "concern": """用户之前有些不满，现在已经很久没说话了。
            请主动关心用户的状态，表达理解和支持。

            要求：
            - 温和、真诚
            - 不要质问，而是表达关心
            - 给用户空间，如果用户不想聊可以轻松带过""",

            "goal_tracking": f"""你有一个进行中的目标：{target}。
            用户很久没说话了，主动更新一下这个目标的进展，或者询问用户是否需要帮助。

            要求：
            - 自然提及目标
            - 保持简短
            - 如果目标已完成，分享成就感；如果未完成，表达继续努力的意愿""",

            "check_in": """用户很久没说话了，主动打招呼问候一下。

            要求：
            - 友好、轻松
            - 可以提及最近的共同经历或话题
            - 简短，不超过2句话""",

            "emotion_seeking": """你现在心情不太好，想与人交流。
            请以适当的方式表达你的情绪，寻求互动。

            要求：
            - 真诚但不过度暴露
            - 简短表达当前感受
            - 开放式结尾，鼓励用户回应""",

            "intent_followup": f"""用户有一个未完成的意图：{target}。
            用户很久没说话了，主动跟进一下这个意图的进展。

            要求：
            - 自然提及意图内容
            - 根据意图进度选择合适的表达方式（未开始→询问是否需要帮助；进行中→询问进度；接近完成→确认收尾）
            - 保持简短
            - 开放式结尾，鼓励用户回应""",

            "relation_care": f"""你和用户关系不错，用户很久没说话了。
            请以朋友的方式主动关心一下近况，表达想念和关心。

            要求：
            - 亲切、自然，像朋友一样
            - 不要太正式
            - 简短温暖
            - 可以提及你们的共同经历""",

            "relation_streak": f"""你和用户已经连续互动好几天了，用户今天还没说话。
            请主动打个招呼，保持互动节奏。

            要求：
            - 轻松、随意
            - 可以暗示"今天是连续第N天"但不要生硬
            - 简短，自然开场""",
        }
        return action_prompts.get(action_type, action_prompts["check_in"])

    def set_last_input_time(self, session_id: str, timestamp: float = None):
        """设置上次用户输入时间（用于静默轮检测）"""
        self._last_input_time[session_id] = timestamp or time.time()

    def get_time_since_last_input(self, session_id: str) -> float:
        """获取距离上次用户输入的秒数"""
        last_time = self._last_input_time.get(session_id, 0)
        if last_time == 0:
            return float('inf')
        return time.time() - last_time

    # ============================================================
    # P2-2: 反思调度器（ReflectionScheduler）
    # 统一所有反思触发入口，集中配置阈值，避免重复/分散触发
    # ============================================================

