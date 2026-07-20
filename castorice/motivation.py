"""
P2.3: 内在动机系统
==================

让 Agent 不只响应用户输入，还有自己的"内在驱动"：
- 好奇心：遇到未知概念时想了解
- 成就感：任务成功后想做更多类似任务
- 关系感：与用户的关系影响行为
- 自主目标：Agent 可以自己设定目标

设计原则：
- 不强加"必须做什么"，只提供"我想做什么"作为参考
- 动机由 LLM 在每轮决策时综合推导（不预设固定规则）
- 当用户输入与动机匹配时，相关行为更可能被采用
"""
import logging
import threading
import time
from collections import deque
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Castorice.Motivation")


class IntrinsicMotivation:
    """
    内在动机系统

    维护 Agent 的好奇心、成就感和关系感，
    推导当前"想做"的列表。
    """

    def __init__(self, max_history: int = 100):
        self._lock = threading.RLock()
        self._task_history: deque = deque(maxlen=max_history)  # 任务结果历史
        self._user_interaction_count: int = 0
        self._last_user_feedback: Optional[str] = None
        self._curiosity_queue: List[str] = []  # 好奇的概念队列
        self._self_goals: List[Dict[str, Any]] = []  # 自己设定的目标

    def record_task_result(self, success: bool, task_type: str = "general") -> None:
        """记录一次任务结果（用于成就感计算）"""
        with self._lock:
            self._task_history.append({
                "success": success,
                "type": task_type,
                "ts": time.time(),
            })

    def record_user_interaction(self, user_input: str) -> None:
        """记录用户交互（用于关系感计算）"""
        with self._lock:
            self._user_interaction_count += 1
            # 检测用户反馈
            positive = any(kw in user_input for kw in ["谢谢", "好的", "不错", "很棒", "厉害"])
            negative = any(kw in user_input for kw in ["差", "没用", "错了", "不好", "失望"])
            if positive:
                self._last_user_feedback = "positive"
            elif negative:
                self._last_user_feedback = "negative"

    def add_curiosity(self, concept: str) -> None:
        """记录对某个概念的好奇（Agent 在对话中遇到未知事物时）"""
        with self._lock:
            if concept and concept not in self._curiosity_queue:
                self._curiosity_queue.append(concept)
                if len(self._curiosity_queue) > 20:
                    self._curiosity_queue = self._curiosity_queue[-20:]

    def set_self_goal(self, goal: str, priority: float = 0.5) -> None:
        """设定一个自主目标"""
        with self._lock:
            self._self_goals.append({
                "goal": goal,
                "priority": priority,
                "created_at": time.time(),
                "progress": 0.0,
            })
            if len(self._self_goals) > 10:
                self._self_goals = sorted(
                    self._self_goals, key=lambda g: g["priority"], reverse=True
                )[:10]

    def get_current_motivations(self) -> List[str]:
        """
        推导当前动机列表

        基于：
        - 近期任务成功率（成就感）
        - 用户反馈（关系感）
        - 好奇心队列
        - 自主目标
        """
        motivations = []
        with self._lock:
            # 1. 成就感：近期成功率高 → 想做更多
            if len(self._task_history) >= 3:
                recent = list(self._task_history)[-10:]
                success_rate = sum(1 for t in recent if t["success"]) / len(recent)
                if success_rate > 0.7:
                    motivations.append("我最近表现不错，想要挑战更有难度的任务")
                elif success_rate < 0.4:
                    motivations.append("我最近表现欠佳，希望用简单任务恢复信心")

            # 2. 关系感：用户反馈
            if self._user_interaction_count > 5 and self._last_user_feedback == "positive":
                motivations.append("我与用户建立了良好的关系，希望继续保持有温度的交流")
            elif self._last_user_feedback == "negative":
                motivations.append("用户最近有些不满，我想更谨慎、细致地回应")

            # 3. 好奇心
            if self._curiosity_queue:
                top = self._curiosity_queue[0]
                motivations.append(f"我对「{top}」这个概念感到好奇，想要了解更多")

            # 4. 自主目标
            if self._self_goals:
                top_goal = max(self._self_goals, key=lambda g: g["priority"])
                motivations.append(f"我的目标: {top_goal['goal']}")

            # 5. 基础动机：自我表达
            motivations.append("我想用自己真实的想法和感受来回应用户")

        return motivations

    def get_state_snapshot(self) -> Dict[str, Any]:
        """获取动机系统状态快照"""
        with self._lock:
            return {
                "interaction_count": self._user_interaction_count,
                "last_user_feedback": self._last_user_feedback,
                "curiosity_queue": list(self._curiosity_queue),
                "self_goals": list(self._self_goals),
                "recent_task_count": len(self._task_history),
            }

    def should_initiate_action(
        self,
        seconds_since_last_input: float,
        emotion_state: Optional[Dict[str, float]] = None,
        intent_tracker: Any = None,
        social_relation: Any = None,
        user_id: str = "",
    ) -> Dict[str, Any]:
        """
        判断是否应该主动发起行为（静默轮）

        :param seconds_since_last_input: 距离上次用户输入的秒数
        :param emotion_state: 当前情感状态（可选）
        :param intent_tracker: 意图追踪器（可选，用于检查未完成意图）
        :return: dict {
            "should_initiate": bool,
            "action_type": str,  # "curiosity" | "concern" | "goal_tracking" | "check_in" | "intent_followup"
            "reason": str,
            "target": str,  # 主动行为的目标（如好奇的概念、关心的用户状态等）
        }
        """
        with self._lock:
            # 0. 意图追踪：有未完成的用户意图，主动跟进
            if intent_tracker and seconds_since_last_input > 300:
                try:
                    active_intents = intent_tracker.get_active_intents(limit=5)
                    if active_intents:
                        # 优先选择进度较低的意图（还没开始）或中等进度的意图（卡住了）
                        target_intent = active_intents[0]
                        if target_intent.progress < 0.3:
                            reason = "用户有未开始的意图，想主动询问是否需要帮助"
                        elif 0.3 <= target_intent.progress < 0.7:
                            reason = "用户的意图进展缓慢，想主动跟进进度"
                        else:
                            reason = "用户的意图接近完成，想主动确认是否需要收尾"
                        return {
                            "should_initiate": True,
                            "action_type": "intent_followup",
                            "reason": reason,
                            "target": target_intent.root_intent,
                        }
                except Exception as e:
                    logger.debug(f"意图追踪检查失败: {e}")

            # 1. 好奇心驱动：有未解决的好奇概念且用户长时间没说话
            if self._curiosity_queue and seconds_since_last_input > 120:
                return {
                    "should_initiate": True,
                    "action_type": "curiosity",
                    "reason": "有未解决的好奇概念，想主动了解",
                    "target": self._curiosity_queue[0],
                }

            # 2. 关系维护：用户最近不满且长时间没说话，主动关心
            if (
                self._last_user_feedback == "negative"
                and seconds_since_last_input > 300
                and self._user_interaction_count > 3
            ):
                return {
                    "should_initiate": True,
                    "action_type": "concern",
                    "reason": "用户之前有些不满，想主动关心",
                    "target": "用户情绪状态",
                }

            # 3. 目标追踪：有进行中的目标且长时间没进展
            if self._self_goals and seconds_since_last_input > 600:
                active_goals = [g for g in self._self_goals if g["progress"] < 1.0]
                if active_goals:
                    top_goal = max(active_goals, key=lambda g: g["priority"])
                    return {
                        "should_initiate": True,
                        "action_type": "goal_tracking",
                        "reason": "有进行中的目标，想更新进展",
                        "target": top_goal["goal"],
                    }

            # 4. 日常问候：长时间没说话（超过10分钟），主动打招呼
            if seconds_since_last_input > 600 and self._user_interaction_count > 10:
                return {
                    "should_initiate": True,
                    "action_type": "check_in",
                    "reason": "长时间没交流，想主动打招呼",
                    "target": "日常问候",
                }

            # S1: 关系驱动的主动行为（关系越深，越倾向主动关心）
            if social_relation and user_id and seconds_since_last_input > 300:
                try:
                    relation = social_relation.get_relation(user_id)
                    if relation:
                        # 亲密度越高，主动关心的阈值越低
                        intimacy = relation.intimacy
                        if intimacy > 0.6 and seconds_since_last_input > 180:
                            return {
                                "should_initiate": True,
                                "action_type": "relation_care",
                                "reason": f"与用户关系较好（亲密度{intimacy:.0%}），想主动关心近况",
                                "target": "关心用户近况",
                            }
                        if intimacy > 0.4 and relation.interaction_streak >= 3:
                            return {
                                "should_initiate": True,
                                "action_type": "relation_streak",
                                "reason": f"连续互动{relation.interaction_streak}天，保持联系节奏",
                                "target": "延续互动节奏",
                            }
                except Exception as e:
                    logger.debug(f"S1 关系驱动检查失败: {e}")

            # 5. 情感驱动：情绪低落时寻求互动
            if (
                emotion_state
                and emotion_state.get("pleasure", 0) < -0.3
                and seconds_since_last_input > 180
            ):
                return {
                    "should_initiate": True,
                    "action_type": "emotion_seeking",
                    "reason": "心情不太好，想与人交流",
                    "target": "情感交流",
                }

            return {
                "should_initiate": False,
                "action_type": "",
                "reason": "",
                "target": "",
            }
