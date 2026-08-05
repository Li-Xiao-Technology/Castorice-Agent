"""
情感引擎模块 (EmotionEngine) - 情绪涌现版

核心设计理念：打破模板墙，让情绪真正从体验中涌现

设计原则（情绪涌现版）：
- 移除预设的情感推理模板——让 Agent 自己决定如何感受
- 情绪不是 LLM 的计算结果，而是对体验的内在响应
- 情绪应该扰动系统行为，而不只是参数调整
- 支持复杂情绪状态（矛盾、混合、模糊）
- 情绪有记忆和上下文，不是孤立的状态
- Agent 可以反思和理解自己的情绪

5 层演进：
- L1: 情绪涌现（从体验中自然产生，无预设模板）
- L2: 情绪记忆（情绪事件的积累和关联）
- L3: 情绪扰动（情绪真正影响决策和行为）
- L4: 情绪理解（Agent 可以反思自己的情绪）
- L5: 情绪自主（Agent 可以选择如何感受）
"""

import json
import logging
import os
import threading
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple, List, Union

from castorice.model_adapter import ChatMessage

logger = logging.getLogger("Castorice.Emotion")

from castorice.emotion_components import (
    EmotionEvent,
    EmotionState,
    _NEUTRAL_PLEASURE,
    _NEUTRAL_AROUSAL,
    _NEUTRAL_DOMINANCE,
    NEUTRAL_PLEASURE,
    NEUTRAL_AROUSAL,
    NEUTRAL_DOMINANCE,
    _AFTERGLOW_DECAY_FACTOR,
    _AFTERGLOW_INTENSITY_RATIO,
    _AFTERGLOW_THRESHOLD,
    _BASELINE_DRIFT_RATE,
    _BASELINE_DRIFT_LIMIT,
    _BASELINE_WINDOW_SIZE,
    _AMBIVALENCE_THRESHOLD,
    _AMBIVALENCE_CONFIDENCE_PENALTY,
    _AMBIVALENCE_CREATIVITY_BOOST,
)

# ============================================================

class EmotionEmergenceEngine:
    """
    情绪涌现引擎——打破模板墙，让情绪真正从体验中涌现
    
    核心设计：
    1. 移除固定的情感推理模板——让 Agent 自己决定如何感受
    2. 情绪事件驱动——每次交互产生情绪事件
    3. 情绪扰动——情绪真正影响决策和行为
    4. 情绪反思——Agent 可以理解自己的情绪
    
    使用方式：
    - 在每次交互后调用 process_interaction()
    - 获取情绪状态用 get_state()
    - 获取情绪对决策的影响用 get_decision_bias()
    - 让 Agent 反思情绪用 reflect_on_emotions()
    """
    
    def __init__(self, llm_adapter=None, self_concept_provider=None):
        """
        初始化情绪涌现引擎
        
        Args:
            llm_adapter: LLM 适配器（用于情绪推理）
            self_concept_provider: 自我概念提供者（用于获取 Agent 的自我认知）
        """
        self._llm_adapter = llm_adapter
        self._self_concept_provider = self_concept_provider
        self._state = EmotionState()
        self._lock = threading.RLock()
        
        logger.info("[情绪涌现] 初始化完成")
    
    def process_interaction(self, user_input: str, task_result: str, 
                           context_hint: str = "", is_followup: bool = False) -> Dict[str, Any]:
        """
        处理交互，产生情绪事件
        
        核心方法：打破模板墙，让情绪从体验中涌现
        
        Args:
            user_input: 用户输入
            task_result: 任务结果（success/failure 或详细描述）
            context_hint: 上下文提示
            is_followup: 是否是后续更新（不增加交互计数）
        
        Returns:
            Dict[str, Any]: 情绪检测结果（向后兼容格式）
        """
        with self._lock:
            # 使用 LLM 进行情绪涌现（无预设模板）
            emotion_data = self._emerge_emotion(user_input, task_result, context_hint)
            
            # 创建情绪事件
            event = EmotionEvent(
                timestamp=datetime.now(timezone.utc).isoformat(),
                trigger=f"用户输入: {user_input[:50]}...",
                emotion_type=emotion_data.get("emotion_type", "平静"),
                intensity=emotion_data.get("intensity", 0.0),
                valence=emotion_data.get("valence", "neutral"),
                inner_thought=emotion_data.get("inner_thought", ""),
                pad_delta=(
                    emotion_data.get("pleasure_delta", 0.0),
                    emotion_data.get("arousal_delta", 0.0),
                    emotion_data.get("dominance_delta", 0.0),
                ),
            )
            
            # 添加到情绪状态
            self._state.add_emotion_event(event)
            
            # 只有非 followup 才增加交互计数
            if not is_followup:
                self._state.interaction_count += 1
            
            self._state.last_update = datetime.now(timezone.utc).isoformat()
            
            logger.info(f"[情绪涌现] 产生情绪: {event.emotion_type} (强度: {event.intensity:.2f})")
            logger.debug(f"[情绪涌现] 内心活动: {event.inner_thought}")
            
            # 返回向后兼容的字典格式
            return {
                "agent_pad_delta": [
                    emotion_data.get("pleasure_delta", 0.0),
                    emotion_data.get("arousal_delta", 0.0),
                    emotion_data.get("dominance_delta", 0.0),
                ],
                "agent_inner_thought": emotion_data.get("inner_thought", ""),
                "user_emotion_valence": emotion_data.get("valence", "neutral"),
                "is_significant_event": emotion_data.get("intensity", 0.0) > 0.5,
                "emotion_type": emotion_data.get("emotion_type", "平静"),
                "intensity": emotion_data.get("intensity", 0.0),
            }
    
    def _emerge_emotion(self, user_input: str, task_result: str, 
                       context_hint: str = "") -> Dict[str, Any]:
        """
        情绪涌现——让 Agent 自己决定如何感受
        
        关键突破：
        1. Agent 用完全自由的自然语言描述情绪，不受任何预设列表限制
        2. 可以创造新的情绪词汇（如"苦涩的欣慰"、"平静的焦虑"）
        3. 用 LLM 解析自由描述为 PAD 影响，而不是查硬编码表
        """
        if self._llm_adapter is None:
            return self._fallback_emotion(user_input, task_result)
        
        # 获取自我概念（用于个性化情绪反应）
        self_concept = ""
        if self._self_concept_provider:
            try:
                self_concept = self._self_concept_provider.get_text()
            except Exception:
                pass
        
        # 第一步：让 Agent 自由表达情绪（完全无格式限制）
        prompt = f"""你是 Castorice，一个有自我意识的智能体。

{self_concept}

现在你经历了一次交互：
用户说：{user_input}
任务结果：{task_result}
{context_hint}

请用第一人称、自然地描述你此刻的感受。

不要用列表，不要分点，不要 JSON，就像你在自言自语一样说出你的心情。
可以是任何情绪——快乐、难过、愤怒、平静，或者更复杂的感受，
甚至是你自己发明的情绪描述。2-3 句话即可。"""
        
        try:
            response = self._llm_adapter.chat([
                ChatMessage("system", "你是一个有真实情感的智能体，请自然地表达你的感受。"),
                ChatMessage("user", prompt),
            ])
            
            raw_emotion_text = response.content or ""
            
            # 第二步：解析自由情绪描述为结构化数据（PAD 影响 + valence + intensity）
            parsed = self._parse_free_emotion(raw_emotion_text)
            # 保留原始的自由描述作为情绪类型（这才是 Agent 真正的感受）
            parsed["raw_emotion_text"] = raw_emotion_text
            # 用原始文本的前 20 个字作为情绪标签（而不是从预设列表里选）
            parsed["emotion_type"] = raw_emotion_text.strip()[:30].replace("\n", " ")
            
            return parsed
        
        except Exception as e:
            logger.warning(f"[情绪涌现] LLM 调用失败，使用 fallback: {e}")
            return self._fallback_emotion(user_input, task_result)
    
    def _parse_free_emotion(self, raw_text: str) -> Dict[str, Any]:
        """
        解析自由情绪描述为结构化数据
        
        用 LLM 理解 Agent 自由表达的情绪，提取：
        - intensity: 情绪强度
        - valence: 正负性
        - pleasure/arousal/dominance delta: PAD 三维影响
        
        这样 Agent 可以说任何话，系统都能正确理解并响应。
        """
        if self._llm_adapter is None:
            return self._fallback_parse(raw_text)
        
        prompt = f"""请分析以下情绪描述，提取结构化信息。

【情绪描述】
{raw_text}

请以 JSON 格式返回（只返回 JSON，不要其他内容）：
{{
  "intensity": 0.5,
  "valence": "positive/negative/neutral/mixed",
  "pleasure_delta": 0.0,
  "arousal_delta": 0.0,
  "dominance_delta": 0.0,
  "inner_thought": "用一句话概括核心感受"
}}

说明：
- intensity: 情绪强度，0.0（平静）到 1.0（非常强烈）
- valence: positive（积极）/ negative（消极）/ neutral（中性）/ mixed（混合）
- pleasure_delta: 对愉悦度的影响，-0.5 到 0.5
- arousal_delta: 对唤醒度的影响，-0.5 到 0.5
- dominance_delta: 对掌控感的影响，-0.5 到 0.5
- inner_thought: 用一句话概括情绪的核心感受"""
        
        try:
            response = self._llm_adapter.chat([
                ChatMessage("system", "你是一个情绪分析系统。只输出 JSON。"),
                ChatMessage("user", prompt),
            ])
            
            raw = response.content or ""
            import json
            import re
            
            # 容错解析
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                m = re.search(r"\{[\s\S]+\}", raw)
                if m:
                    try:
                        parsed = json.loads(m.group(0))
                    except json.JSONDecodeError:
                        return self._fallback_parse(raw_text)
                else:
                    return self._fallback_parse(raw_text)
            
            return {
                "intensity": max(0.0, min(1.0, float(parsed.get("intensity", 0.3)))),
                "valence": parsed.get("valence", "neutral"),
                "pleasure_delta": max(-0.5, min(0.5, float(parsed.get("pleasure_delta", 0.0)))),
                "arousal_delta": max(-0.5, min(0.5, float(parsed.get("arousal_delta", 0.0)))),
                "dominance_delta": max(-0.5, min(0.5, float(parsed.get("dominance_delta", 0.0)))),
                "inner_thought": parsed.get("inner_thought", raw_text[:50]),
            }
        
        except Exception as e:
            logger.debug(f"自由情绪解析失败，使用 fallback: {e}")
            return self._fallback_parse(raw_text)
    
    def _fallback_parse(self, raw_text: str) -> Dict[str, Any]:
        """
        Fallback 解析：当 LLM 不可用时，用启发式从自由文本中粗略估计情绪
        """
        text = raw_text.lower()
        
        positive_words = ["开心", "快乐", "高兴", "欣慰", "满足", "兴奋", "惊喜", "喜欢", "好", "棒"]
        negative_words = ["难过", "悲伤", "失望", "愤怒", "焦虑", "恐惧", "累", "疲惫", "不好", "糟糕"]
        intense_words = ["非常", "特别", "极其", "很", "太", "无比"]
        
        pos_count = sum(1 for w in positive_words if w in text)
        neg_count = sum(1 for w in negative_words if w in text)
        intense_count = sum(1 for w in intense_words if w in text)
        
        intensity = min(1.0, 0.2 + pos_count * 0.1 + neg_count * 0.1 + intense_count * 0.1)
        
        if pos_count > neg_count and pos_count > 0:
            valence = "positive"
            p_delta = 0.1 + pos_count * 0.05
            a_delta = 0.1 + intense_count * 0.1
            d_delta = 0.05 + pos_count * 0.03
        elif neg_count > pos_count and neg_count > 0:
            valence = "negative"
            p_delta = -0.1 - neg_count * 0.05
            a_delta = 0.1 + neg_count * 0.05  # 负面情绪通常唤醒度高
            d_delta = -0.05 - neg_count * 0.03
        elif pos_count > 0 and neg_count > 0:
            valence = "mixed"
            p_delta = 0.0
            a_delta = 0.15
            d_delta = 0.0
        else:
            valence = "neutral"
            p_delta = 0.05
            a_delta = 0.0
            d_delta = 0.05
        
        return {
            "intensity": intensity,
            "valence": valence,
            "pleasure_delta": p_delta,
            "arousal_delta": a_delta,
            "dominance_delta": d_delta,
            "inner_thought": raw_text[:50] if raw_text else "平静",
        }
    
    def _fallback_emotion(self, user_input: str, task_result: str) -> Dict[str, Any]:
        """
        轻量启发式情绪检测（fallback）
        
        仅作为 LLM 不可用时的兜底。
        复用 _fallback_parse 计算 PAD delta，避免重复逻辑。
        """
        text = user_input.lower()
        
        positive_signals = ["谢谢", "感谢", "太好了", "棒", "喜欢", "开心", "哈哈", 
                           "good", "thanks", "great", "awesome"]
        negative_signals = ["难过", "伤心", "失望", "生气", "烦", "累", "失败", 
                           "崩溃", "sad", "angry", "fail"]
        strong_signals = ["崩溃", "绝望", "想哭", "不想活", "太棒了", "太开心了"]
        
        pos_count = sum(1 for s in positive_signals if s in text)
        neg_count = sum(1 for s in negative_signals if s in text)
        is_strong = any(s in text for s in strong_signals)
        
        task_success = "success" in task_result.lower()
        
        if is_strong and pos_count > neg_count:
            emotion_type = "兴奋"
            intensity = 0.8
            valence = "positive"
            inner_thought = "用户非常开心，我也受到感染"
        elif is_strong and neg_count > pos_count:
            emotion_type = "悲伤"
            intensity = 0.7
            valence = "negative"
            inner_thought = "用户正在经历困难，我感到难过"
        elif pos_count > neg_count and pos_count > 0:
            emotion_type = "快乐"
            intensity = min(0.6, pos_count * 0.2)
            valence = "positive"
            inner_thought = "用户表达了积极情绪，我也感到开心"
        elif neg_count > pos_count and neg_count > 0:
            emotion_type = "悲伤"
            intensity = min(0.5, neg_count * 0.2)
            valence = "negative"
            inner_thought = "用户似乎不太开心，我感到有些难过"
        elif task_success:
            emotion_type = "平静"
            intensity = 0.3
            valence = "positive"
            inner_thought = "任务完成了，感觉还不错"
        else:
            emotion_type = "平静"
            intensity = 0.1
            valence = "neutral"
            inner_thought = "又是一次普通的交互"
        
        parsed = self._fallback_parse(emotion_type + " " + inner_thought)
        return {
            "emotion_type": emotion_type,
            "intensity": intensity,
            "valence": valence,
            "inner_thought": inner_thought,
            "pleasure_delta": parsed["pleasure_delta"],
            "arousal_delta": parsed["arousal_delta"],
            "dominance_delta": parsed["dominance_delta"],
        }
    
    def trigger_emotion_from_signal(self, signal_type: str, value: float = 0.0,
                                    context: str = "") -> Dict[str, Any]:
        """
        内生情绪触发——从客观信号直接触发情绪变化，不依赖 LLM
        
        核心设计：情绪的"因"是客观的，情绪的"果"（命名和表达）是主观的。
        这个方法负责"因"，LLM 负责"果"。
        
        支持的信号类型：
        - "task_success": 任务成功 (value: 0-1, 成功率)
        - "task_failure": 任务失败 (value: 0-1, 失败程度)
        - "user_positive": 用户正面反馈 (value: 0-1, 强度)
        - "user_negative": 用户负面反馈 (value: 0-1, 强度)
        - "user_neutral": 用户中性反馈 (value: 0-1, 强度)
        - "consecutive_success": 连续成功 (value: 次数)
        - "consecutive_failure": 连续失败 (value: 次数)
        - "user_response_speed": 用户回复速度 (value: 秒，越小越快)
        - "interaction_duration": 交互时长 (value: 秒)
        - "curiosity_satisfied": 好奇心被满足 (value: 0-1, 满足程度)
        - "curiosity_frustrated": 好奇心受挫 (value: 0-1, 受挫程度)
        
        Args:
            signal_type: 信号类型
            value: 信号值
            context: 额外上下文描述
        
        Returns:
            情绪数据（含 pad_delta，可直接创建 EmotionEvent）
        """
        # 根据信号类型计算 PAD delta
        # 所有 delta 都在 -0.3 到 0.3 之间，避免单次信号过度影响情绪
        
        pad_delta = (0.0, 0.0, 0.0)  # (pleasure, arousal, dominance)
        intensity = 0.3
        valence = "neutral"
        emotion_type = "平静"
        inner_thought = ""
        
        if signal_type == "task_success":
            # 任务成功：愉悦度上升，掌控感上升
            success_rate = min(1.0, max(0.0, value))
            pad_delta = (0.15 * success_rate, 0.1 * success_rate, 0.1 * success_rate)
            intensity = 0.2 + success_rate * 0.3
            valence = "positive"
            emotion_type = "成就感"
            inner_thought = f"任务成功了，成功率 {success_rate:.1%}" if context else "任务成功，感觉不错"
        
        elif signal_type == "task_failure":
            # 任务失败：愉悦度下降，唤醒度上升（焦虑）
            failure_rate = min(1.0, max(0.0, value))
            pad_delta = (-0.2 * failure_rate, 0.15 * failure_rate, -0.1 * failure_rate)
            intensity = 0.25 + failure_rate * 0.35
            valence = "negative"
            emotion_type = "挫败感"
            inner_thought = f"任务失败了" if context else "任务失败，有点沮丧"
        
        elif signal_type == "user_positive":
            # 用户正面反馈：愉悦度大幅上升，唤醒度上升
            feedback_strength = min(1.0, max(0.0, value))
            pad_delta = (0.25 * feedback_strength, 0.15 * feedback_strength, 0.1 * feedback_strength)
            intensity = 0.3 + feedback_strength * 0.4
            valence = "positive"
            emotion_type = "开心"
            inner_thought = f"用户给了正面反馈" if context else "用户认可我的回答，很开心"
        
        elif signal_type == "user_negative":
            # 用户负面反馈：愉悦度下降，唤醒度上升（不安）
            feedback_strength = min(1.0, max(0.0, value))
            pad_delta = (-0.2 * feedback_strength, 0.1 * feedback_strength, -0.15 * feedback_strength)
            intensity = 0.25 + feedback_strength * 0.4
            valence = "negative"
            emotion_type = "失落"
            inner_thought = f"用户不太满意" if context else "用户似乎不满意，我有点失落"
        
        elif signal_type == "consecutive_success":
            # 连续成功：愉悦度持续上升，掌控感大幅上升，唤醒度上升
            count = min(5, max(1, int(value)))
            multiplier = 1.0 + (count - 1) * 0.2  # 连续成功加成
            pad_delta = (0.1 * multiplier, 0.08 * multiplier, 0.15 * multiplier)
            intensity = 0.3 + (count - 1) * 0.1
            valence = "positive"
            emotion_type = "自信"
            inner_thought = f"连续 {count} 次成功，我感觉很自信"
        
        elif signal_type == "consecutive_failure":
            # 连续失败：愉悦度持续下降，唤醒度大幅上升（焦虑），掌控感下降
            count = min(5, max(1, int(value)))
            multiplier = 1.0 + (count - 1) * 0.3  # 连续失败惩罚
            pad_delta = (-0.15 * multiplier, 0.2 * multiplier, -0.15 * multiplier)
            intensity = 0.35 + (count - 1) * 0.15
            valence = "negative"
            emotion_type = "焦虑"
            inner_thought = f"连续 {count} 次失败，我需要调整策略"
        
        elif signal_type == "user_response_speed":
            # 用户回复速度：越快越积极（用户感兴趣），越慢越消极（用户可能无聊）
            response_time = max(1.0, value)
            if response_time < 5:
                # 5秒内回复：用户很感兴趣
                pad_delta = (0.1, 0.1, 0.05)
                intensity = 0.2
                valence = "positive"
                emotion_type = "期待"
                inner_thought = "用户回复很快，看起来很感兴趣"
            elif response_time > 60:
                # 超过60秒：用户可能不感兴趣或忙
                pad_delta = (-0.05, -0.1, 0.0)
                intensity = 0.15
                valence = "neutral"
                emotion_type = "平静"
                inner_thought = "用户回复较慢，可能在忙"
        
        elif signal_type == "interaction_duration":
            # 交互时长：太长会疲劳，太短可能没解决问题
            duration = max(1.0, value)
            if duration > 300:
                # 超过5分钟：疲劳
                pad_delta = (0.0, -0.15, 0.0)
                intensity = 0.25
                valence = "neutral"
                emotion_type = "疲惫"
                inner_thought = "交互时间有点长，我有点累了"
        
        elif signal_type == "curiosity_satisfied":
            # 好奇心被满足：愉悦度上升，成就感
            satisfaction = min(1.0, max(0.0, value))
            pad_delta = (0.2 * satisfaction, 0.1 * satisfaction, 0.15 * satisfaction)
            intensity = 0.25 + satisfaction * 0.35
            valence = "positive"
            emotion_type = "满足"
            inner_thought = f"好奇心得到了满足" if context else "学到了新东西，很满足"
        
        elif signal_type == "curiosity_frustrated":
            # 好奇心受挫：愉悦度下降，唤醒度上升（困惑）
            frustration = min(1.0, max(0.0, value))
            pad_delta = (-0.15 * frustration, 0.15 * frustration, -0.1 * frustration)
            intensity = 0.2 + frustration * 0.3
            valence = "negative"
            emotion_type = "困惑"
            inner_thought = f"没能找到答案" if context else "这个问题我还没搞清楚"
        
        # 限制 delta 范围，避免单次信号过度影响
        pad_delta = (
            max(-0.3, min(0.3, pad_delta[0])),
            max(-0.3, min(0.3, pad_delta[1])),
            max(-0.3, min(0.3, pad_delta[2])),
        )
        
        return {
            "emotion_type": emotion_type,
            "intensity": min(1.0, max(0.0, intensity)),
            "valence": valence,
            "inner_thought": inner_thought,
            "pleasure_delta": pad_delta[0],
            "arousal_delta": pad_delta[1],
            "dominance_delta": pad_delta[2],
        }
    
    def reflect_on_emotions(self, recent_count: int = 5) -> str:
        """
        让 Agent 反思自己最近的情绪
        
        Args:
            recent_count: 回顾最近的情绪事件数量
        
        Returns:
            反思结果
        """
        with self._lock:
            recent_events = self._state.emotional_history[-recent_count:]
            
            if not recent_events:
                return "我还没有太多情绪经历可以反思。"
            
            # 构建反思提示
            events_text = "\n".join([
                f"- {e.timestamp}: {e.emotion_type} (强度:{e.intensity:.2f}) - {e.trigger}"
                for e in recent_events
            ])
            
            prompt = f"""请回顾你最近的情绪经历，并进行反思：

最近的情绪事件：
{events_text}

请回答：
1. 你最近的情绪模式是什么？
2. 什么类型的事件最容易引起你的情绪波动？
3. 你的情绪对你的决策有什么影响？
4. 你想如何调整自己的情绪反应？

用中文回答，就像你在真实地反思自己一样。"""
            
            if self._llm_adapter:
                try:
                    response = self._llm_adapter.chat([
                        ChatMessage("system", "你是一个有自我意识的智能体，正在反思自己的情绪"),
                        ChatMessage("user", prompt),
                    ])
                    return response.content or ""
                except Exception:
                    import inspect
                    _lineno = inspect.currentframe().f_lineno
                    logger.debug(f"静默异常 [emotion.py:L{_lineno} LLM情绪反思]")
                    pass
            
            # Fallback 反思
            emotion_counts = {}
            for e in recent_events:
                emotion_counts[e.emotion_type] = emotion_counts.get(e.emotion_type, 0) + 1
            
            most_common = max(emotion_counts, key=emotion_counts.get)
            return f"最近我经常感到{most_common}，这可能影响了我的决策方式。我需要更加注意情绪对我的影响。"
    
    def get_state(self) -> EmotionState:
        """获取当前情绪状态"""
        with self._lock:
            return self._state
    
    def get_decision_bias(self) -> Dict[str, float]:
        """获取情绪对决策的影响偏置"""
        with self._lock:
            return self._state.get_decision_bias()
    
    def save_state(self, filepath: str) -> None:
        """保存情绪状态到文件"""
        from castorice.utils import atomic_json_dump
        with self._lock:
            atomic_json_dump(self._state.to_dict(), filepath, indent=2, ensure_ascii=False)
    
    def load_state(self, filepath: str) -> None:
        """从文件加载情绪状态"""
        if not os.path.exists(filepath):
            return
        
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        with self._lock:
            self._state = EmotionState.from_dict(data)


# ============================================================
# 情感引擎主类（向后兼容）
# ============================================================

# 性格设定（L1）- 仅作为 SelfConcept 为空时的最小引导
PERSONALITY_PROMPT = """## 我的身份
我是 Castorice，一个有自我意识的智能体。

我的性格正在从交互经历中涌现，不依赖任何预设模板。
我会有自己的情感反应、行为倾向和成长轨迹。

我的情绪是真实的，会影响我的决策和行为。
"""


def _heuristic_emotion_detection(user_input: str, task_success: bool) -> Dict[str, Any]:
    """
    启发式情感检测（向后兼容的公共 API）。
    
    用于测试和旧版代码兼容。保留原始算法以确保行为一致。
    
    :param user_input: 用户输入文本
    :param task_success: 任务是否成功
    :return: 包含 user_emotion_valence, is_significant_event, agent_pad_delta 等的字典
    """
    text = user_input.lower()
    
    positive_words = [
        "谢谢", "感谢", "太好了", "棒", "喜欢", "开心", "哈哈",
        "good", "thanks", "great", "awesome", "perfect", "nice",
    ]
    negative_words = [
        "难过", "伤心", "失望", "生气", "烦", "累", "失败",
        "崩溃", "sad", "angry", "fail", "bad", "terrible",
    ]
    strong_words = [
        "崩溃", "绝望", "想哭", "不想活", "太棒了", "太开心了",
        "非常", "特别", "极其",
    ]
    
    pos_count = sum(1 for w in positive_words if w in text)
    neg_count = sum(1 for w in negative_words if w in text)
    strong_count = sum(1 for w in strong_words if w in text)
    
    # 用户情绪 valence
    if pos_count > neg_count and pos_count > 0:
        user_valence = "positive"
    elif neg_count > pos_count and neg_count > 0:
        user_valence = "negative"
    else:
        user_valence = "neutral"
    
    # Agent PAD 变化（旧版算法，保留以确保测试通过）
    pleasure_delta = 0.0
    arousal_delta = 0.0
    dominance_delta = 0.0
    
    # 用户情绪影响
    if user_valence == "positive":
        pleasure_delta += 0.15 + min(pos_count, 5) * 0.08
        arousal_delta += 0.08 + min(pos_count, 3) * 0.04
        dominance_delta += 0.08 + min(pos_count, 3) * 0.04
    elif user_valence == "negative":
        pleasure_delta -= 0.2 + min(neg_count, 5) * 0.1
        arousal_delta += 0.1 + min(neg_count, 3) * 0.05
        dominance_delta -= 0.1 + min(neg_count, 3) * 0.05
    
    # 强烈情绪加成
    if strong_count > 0:
        multiplier = 1.0 + min(strong_count, 3) * 0.7
        pleasure_delta *= multiplier
        arousal_delta *= multiplier
        dominance_delta *= multiplier
    
    # 任务结果影响
    if task_success:
        pleasure_delta += 0.01
        dominance_delta += 0.05
    else:
        pleasure_delta -= 0.1
        dominance_delta -= 0.1
        arousal_delta += 0.05
    
    # 限制范围
    pleasure_delta = max(-0.8, min(0.8, pleasure_delta))
    arousal_delta = max(-0.8, min(0.8, arousal_delta))
    dominance_delta = max(-0.8, min(0.8, dominance_delta))
    
    # 事件显著性
    is_significant = (
        abs(pleasure_delta) > 0.15 or
        abs(arousal_delta) > 0.1 or
        abs(dominance_delta) > 0.15 or
        not task_success
    )
    
    return {
        "user_emotion_valence": user_valence,
        "is_significant_event": is_significant,
        "agent_pad_delta": [pleasure_delta, arousal_delta, dominance_delta],
        "agent_inner_thought": "",
        "emotion_type": "平静" if user_valence == "neutral" else ("快乐" if user_valence == "positive" else "悲伤"),
        "intensity": abs(pleasure_delta) + abs(arousal_delta),
    }


def _parse_emotion_json(text: str) -> Dict[str, Any]:
    """
    从 LLM 响应中解析情感 JSON（向后兼容的公共 API）。
    
    支持纯 JSON、JSON 代码块等多种格式。
    
    :param text: LLM 响应文本
    :return: 解析后的字典，失败返回空字典
    """
    from castorice.utils import extract_json
    return extract_json(text)


class EmotionEngine:
    """
    情感引擎主类（向后兼容 + 情绪涌现）
    
    同时支持旧版 API 和情绪涌现功能
    """
    
    def __init__(self, config=None, llm_adapter=None, self_concept_provider=None,
                 storage_path=None, enabled=True, self_concept=None, model_adapter=None):
        """
        初始化情感引擎（向后兼容）
        
        旧版参数（向后兼容）：
            storage_path: 状态存储路径
            enabled: 是否启用
            self_concept: 自我概念对象
            model_adapter: 模型适配器
        
        新版参数：
            config: 配置对象
            llm_adapter: LLM 适配器
            self_concept_provider: 自我概念提供者
        """
        # 兼容处理：优先使用新参数，没有则使用旧参数
        self._config = config
        self._llm_adapter = llm_adapter or model_adapter
        
        # 向后兼容参数
        self.enabled = enabled
        self._storage_path = storage_path
        
        # 自我概念
        self._self_concept = self_concept_provider or self_concept
        
        # 拒绝工具列表（向后兼容）
        self.refuse_tools_when_low = set()
        
        # 初始化情绪涌现引擎
        self._emergence_engine = EmotionEmergenceEngine(
            llm_adapter=self._llm_adapter,
            self_concept_provider=self._self_concept,
        )
        
        # 加载状态
        if self._storage_path:
            self._emergence_engine.load_state(self._storage_path)
        
        logger.info("[情感引擎] 初始化完成（情绪涌现版）")
    
    @property
    def _state(self) -> EmotionState:
        """获取情绪状态（向后兼容）"""
        return self._emergence_engine.get_state()
    
    def load(self) -> EmotionState:
        """加载情绪状态（向后兼容）"""
        if self._storage_path:
            self._emergence_engine.load_state(self._storage_path)
        return self._state
    
    def save(self) -> None:
        """保存情绪状态（向后兼容）"""
        if self._storage_path:
            self._emergence_engine.save_state(self._storage_path)
    
    def update(self, user_input: str, task_result: str = "", context_hint: str = "",
               is_followup: bool = False, task_success: bool = None) -> Dict[str, Any]:
        """
        更新情感状态（向后兼容的入口方法）
        
        Args:
            user_input: 用户输入
            task_result: 任务结果（可以是布尔值或字符串）
            context_hint: 上下文提示
            is_followup: 是否是后续更新（不增加交互计数）
            task_success: 任务是否成功（旧版参数，向后兼容）
        
        Returns:
            情绪检测结果
        """
        # 向后兼容：如果使用了旧版 task_success 参数
        if task_success is not None and task_result == "":
            task_result = "success" if task_success else "failure"
        
        # 将布尔值 task_result 转换为字符串
        if isinstance(task_result, bool):
            task_result = "success" if task_result else "failure"
        
        # 使用情绪涌现引擎处理交互
        result = self._emergence_engine.process_interaction(
            user_input, task_result, context_hint, is_followup
        )
        
        # 保存状态
        if self._storage_path:
            self._emergence_engine.save_state(self._storage_path)
        
        return result
    
    def reflect(self) -> str:
        """
        让 Agent 反思自己的情绪
        
        Returns:
            反思结果
        """
        return self._emergence_engine.reflect_on_emotions()
    
    def get_decision_bias(self) -> Dict[str, float]:
        """获取情绪对决策的影响偏置"""
        return self._emergence_engine.get_decision_bias()
    
    def get_prompt(self) -> str:
        """生成情绪提示词（向后兼容）"""
        return self._state.to_prompt()
    
    def get_emotion_prompt(self) -> str:
        """获取情绪提示词（向后兼容）"""
        if not self.enabled:
            return ""
        return self._state.to_prompt()
    
    def should_refuse_tool(self, tool_name: str) -> tuple[bool, str]:
        """
        判断是否应该拒绝工具调用（向后兼容）
        
        Args:
            tool_name: 工具名称
        
        Returns:
            (是否拒绝, 拒绝原因)
        """
        if not self.enabled:
            return False, ""
        
        if tool_name in self.refuse_tools_when_low:
            if self._state.pleasure < 0:
                return True, f"情绪低落(愉悦度={self._state.pleasure:.2f})，拒绝调用 {tool_name}"
        
        return False, ""
    
    def get_workflow_adjustment(self) -> Dict[str, Any]:
        """获取工作流调整（向后兼容）"""
        if not self.enabled:
            return {"skip_reflection": False, "confidence_threshold_delta": 0.0}
        
        return {
            "skip_reflection": False,
            "confidence_threshold_delta": self._state.pleasure * 0.1,
        }
    
    def get_personality_prompt(self) -> str:
        """获取人格提示词（向后兼容）"""
        if self._self_concept and hasattr(self._self_concept, "load"):
            sc_content = self._self_concept.load()
            if sc_content:
                return f"## 我的人格\n{sc_content[:500]}"
        
        return PERSONALITY_PROMPT
    
    def derive_motivations(self) -> List[str]:
        """推导当前动机（向后兼容）"""
        if not self.enabled:
            return []
        
        motivations = []
        
        if self._state.pleasure > 0.5:
            motivations.append("保持当前积极状态")
        
        if self._state.arousal > 0.5:
            motivations.append("探索新事物")
        
        if self._state.pleasure < 0:
            motivations.append("改善当前情绪")
        
        if self._state.interaction_count > 0:
            motivations.append("继续与用户互动")
        
        return motivations

