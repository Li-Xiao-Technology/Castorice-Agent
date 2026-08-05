"""
情绪组件模块 - 数据类与常量（从 emotion.py 拆分）

包含：
- EmotionEvent: 情绪事件数据类
- EmotionState: PAD 三维情感状态 + 情绪记忆 + 余韵 + 个性基线 + 矛盾检测
- 相关常量定义
"""

import json
import logging
from dataclasses import dataclass, asdict, field
from typing import Any, Dict, Optional, Tuple, List

logger = logging.getLogger("Castorice.Emotion")

_NEUTRAL_PLEASURE = 0.3
_NEUTRAL_AROUSAL = 0.1
_NEUTRAL_DOMINANCE = 0.4

# 公共别名（SDK 公共 API）
NEUTRAL_PLEASURE = _NEUTRAL_PLEASURE
NEUTRAL_AROUSAL = _NEUTRAL_AROUSAL
NEUTRAL_DOMINANCE = _NEUTRAL_DOMINANCE

# 情绪余韵参数
_AFTERGLOW_DECAY_FACTOR = 0.7      # 余韵每轮衰减比例
_AFTERGLOW_INTENSITY_RATIO = 0.15   # 余韵强度占原始强度的比例
_AFTERGLOW_THRESHOLD = 0.5          # 触发余韵的情绪强度阈值

# 基线漂移参数
_BASELINE_DRIFT_RATE = 0.003        # 每轮基线漂移速率（很小，缓慢积累）
_BASELINE_DRIFT_LIMIT = 0.3         # 基线最大漂移幅度（±0.3）
_BASELINE_WINDOW_SIZE = 50          # 计算基线漂移的滑动窗口大小

# 矛盾情绪阈值
_AMBIVALENCE_THRESHOLD = 0.4        # 正负情绪同时超过此强度视为矛盾
_AMBIVALENCE_CONFIDENCE_PENALTY = 0.1  # 矛盾情绪对自信心的惩罚
_AMBIVALENCE_CREATIVITY_BOOST = 0.08   # 矛盾情绪对创造力的加成


@dataclass
class EmotionEvent:
    """情绪事件——情绪不再是孤立的状态，而是有上下文的事件"""
    timestamp: str
    trigger: str  # 触发事件描述
    emotion_type: str  # 情绪类型：Agent 自由描述的任何情绪（不再限于预设列表）
    intensity: float  # 强度 0-1
    valence: str  # 正负性：positive/negative/neutral/mixed
    inner_thought: str  # Agent 当时的内心活动
    duration: float = 0.0  # 持续时间（秒）
    # 新增：自由情绪描述对 PAD 的影响（由 LLM 理解后计算，不再查硬编码表）
    pad_delta: Tuple[float, float, float] = (0.0, 0.0, 0.0)  # (pleasure, arousal, dominance)


@dataclass
class EmotionState:
    """PAD 三维情感状态 + 情绪记忆 + 余韵 + 个性基线 + 矛盾检测"""
    pleasure: float = 0.6      # 默认轻微正向（友好开局）
    arousal: float = 0.3       # 默认轻微唤醒（积极但不亢奋）
    dominance: float = 0.5     # 默认中等掌控（自信但不傲慢）
    last_update: str = ""
    interaction_count: int = 0  # 累计交互次数（用于人格形成）
    
    # 情绪记忆
    emotional_history: List[EmotionEvent] = field(default_factory=list)
    current_emotion: Optional[str] = None  # 当前情绪类型描述
    emotion_intensity: float = 0.0         # 当前情绪强度
    
    # 情绪扰动参数（影响决策）
    confidence_bias: float = 0.0           # 对自信心的影响
    creativity_bias: float = 0.0           # 对创造力的影响
    patience_bias: float = 0.0             # 对耐心的影响
    risk_tolerance_bias: float = 0.0       # 对风险容忍度的影响
    
    # 情绪余韵（E1：重要情绪事件留下持续微弱影响）
    afterglow_pleasure: float = 0.0        # 余韵-愉悦度
    afterglow_arousal: float = 0.0         # 余韵-唤醒度
    afterglow_dominance: float = 0.0       # 余韵-掌控感
    afterglow_intensity: float = 0.0       # 余韵强度
    afterglow_source: str = ""             # 余韵来源（什么情绪留下的）
    
    # 矛盾情绪状态（E2：同时有正负情绪）
    is_ambivalent: bool = False            # 是否处于矛盾情绪状态
    ambivalence_level: float = 0.0         # 矛盾程度 0-1
    positive_intensity: float = 0.0        # 正面情绪强度
    negative_intensity: float = 0.0        # 负面情绪强度
    
    # 个性基线（E3：情绪基线随经历缓慢漂移，形成独特性格）
    baseline_pleasure: float = _NEUTRAL_PLEASURE    # 个性基线-愉悦度
    baseline_arousal: float = _NEUTRAL_AROUSAL      # 个性基线-唤醒度
    baseline_dominance: float = _NEUTRAL_DOMINANCE  # 个性基线-掌控感
    baseline_history: List[Dict[str, float]] = field(default_factory=list)  # 基线漂移历史
    
    # 近期情绪窗口（用于基线漂移计算）
    _recent_valences: List[float] = field(default_factory=list)  # 近期 valence 滑动窗口

    def clamp(self) -> None:
        """将三维值限制在 [-1, 1] 区间"""
        self.pleasure = max(-1.0, min(1.0, self.pleasure))
        self.arousal = max(-1.0, min(1.0, self.arousal))
        self.dominance = max(-1.0, min(1.0, self.dominance))
        
        # 限制扰动参数
        self.confidence_bias = max(-0.3, min(0.3, self.confidence_bias))
        self.creativity_bias = max(-0.3, min(0.3, self.creativity_bias))
        self.patience_bias = max(-0.3, min(0.3, self.patience_bias))
        self.risk_tolerance_bias = max(-0.3, min(0.3, self.risk_tolerance_bias))

    def decay(self, factor: float = 0.85) -> None:
        """
        情绪衰减：向个性基线缓慢回归（E3：基线随经历漂移，形成独特性格）
        
        同时处理：
        - 情绪余韵的衰减（E1）
        - 矛盾情绪的缓解
        - 扰动参数的衰减
        """
        # 向个性基线回归（而不是固定的全局中性态）
        self.pleasure = self.pleasure * factor + self.baseline_pleasure * (1 - factor)
        self.arousal = self.arousal * factor + self.baseline_arousal * (1 - factor)
        self.dominance = self.dominance * factor + self.baseline_dominance * (1 - factor)
        
        # 扰动参数也衰减
        self.confidence_bias *= factor
        self.creativity_bias *= factor
        self.patience_bias *= factor
        self.risk_tolerance_bias *= factor
        
        # 情绪强度衰减
        self.emotion_intensity *= factor
        
        # E1：情绪余韵衰减
        self.afterglow_pleasure *= _AFTERGLOW_DECAY_FACTOR
        self.afterglow_arousal *= _AFTERGLOW_DECAY_FACTOR
        self.afterglow_dominance *= _AFTERGLOW_DECAY_FACTOR
        self.afterglow_intensity *= _AFTERGLOW_DECAY_FACTOR
        
        # 余韵叠加到当前状态（微弱但持续）
        if self.afterglow_intensity > 0.01:
            self.pleasure += self.afterglow_pleasure * 0.1
            self.arousal += self.afterglow_arousal * 0.1
            self.dominance += self.afterglow_dominance * 0.1
        
        # E2：矛盾情绪随时间缓解
        if self.is_ambivalent:
            self.positive_intensity *= factor
            self.negative_intensity *= factor
            self.ambivalence_level *= factor
            if self.ambivalence_level < 0.1:
                self.is_ambivalent = False
                self.ambivalence_level = 0.0
        
        # E3：更新基线漂移（基于近期情绪趋势）
        self._update_baseline_drift()
        
        self.clamp()

    def add_emotion_event(self, event: EmotionEvent) -> None:
        """添加情绪事件到历史记录"""
        self.emotional_history.append(event)
        
        # 只保留最近 50 个情绪事件
        if len(self.emotional_history) > 50:
            self.emotional_history = self.emotional_history[-50:]
        
        # 更新当前情绪状态
        self.current_emotion = event.emotion_type
        self.emotion_intensity = event.intensity
        
        # 根据情绪事件更新 PAD 状态和扰动参数
        self._update_from_event(event)

    def _update_from_event(self, event: EmotionEvent) -> None:
        """
        根据情绪事件更新内在状态
        
        关键改动：不再查硬编码的情绪→PAD映射表。
        情绪的 PAD 影响由 LLM 理解自由情绪描述后计算，
        随事件一起传入。这样 Agent 可以描述任何情绪，
        甚至创造新的情绪词汇，系统都能正确响应。
        
        新增：
        - E1：强烈情绪触发余韵
        - E2：正负情绪叠加检测矛盾
        - E3：更新 valence 滑动窗口（用于基线漂移）
        """
        intensity = event.intensity
        pad_delta = event.pad_delta
        
        # 更新 PAD（使用事件携带的 pad_delta，乘以强度）
        self.pleasure += pad_delta[0] * intensity
        self.arousal += pad_delta[1] * intensity
        self.dominance += pad_delta[2] * intensity
        
        # 更新扰动参数（情绪真正影响决策）
        # 基于 valence 而不是具体情绪类型，这样任何情绪都能正确影响决策
        if event.valence == "positive":
            self.confidence_bias += 0.1 * intensity
            self.creativity_bias += 0.1 * intensity
            self.risk_tolerance_bias += 0.05 * intensity
            # E2：更新正面情绪强度追踪
            self.positive_intensity = max(self.positive_intensity, intensity)
        elif event.valence == "negative":
            self.confidence_bias -= 0.1 * intensity
            self.patience_bias -= 0.05 * intensity
            self.risk_tolerance_bias -= 0.1 * intensity
            # E2：更新负面情绪强度追踪
            self.negative_intensity = max(self.negative_intensity, intensity)
        elif event.valence == "mixed":
            # 混合情绪：正负抵消一部分，但唤醒度上升
            self.creativity_bias += 0.05 * intensity  # 矛盾状态下思维更发散
            self.positive_intensity = max(self.positive_intensity, intensity * 0.5)
            self.negative_intensity = max(self.negative_intensity, intensity * 0.5)
        
        # E1：强烈情绪触发余韵（重要事件留下持久影响）
        if intensity >= _AFTERGLOW_THRESHOLD:
            afterglow_strength = intensity * _AFTERGLOW_INTENSITY_RATIO
            self.afterglow_pleasure = pad_delta[0] * afterglow_strength
            self.afterglow_arousal = pad_delta[1] * afterglow_strength
            self.afterglow_dominance = pad_delta[2] * afterglow_strength
            self.afterglow_intensity = afterglow_strength
            self.afterglow_source = event.emotion_type
        
        # E2：矛盾情绪检测（正负情绪同时较强）
        if (self.positive_intensity >= _AMBIVALENCE_THRESHOLD and 
            self.negative_intensity >= _AMBIVALENCE_THRESHOLD):
            self.is_ambivalent = True
            self.ambivalence_level = min(1.0, (self.positive_intensity + self.negative_intensity) / 2)
            # 矛盾情绪：降低自信，增加创造力（纠结但发散）
            self.confidence_bias -= _AMBIVALENCE_CONFIDENCE_PENALTY * self.ambivalence_level
            self.creativity_bias += _AMBIVALENCE_CREATIVITY_BOOST * self.ambivalence_level
        
        # E3：更新 valence 滑动窗口（用于基线漂移）
        valence_score = 0.0
        if event.valence == "positive":
            valence_score = intensity
        elif event.valence == "negative":
            valence_score = -intensity
        elif event.valence == "mixed":
            valence_score = 0.0
        
        self._recent_valences.append(valence_score)
        if len(self._recent_valences) > _BASELINE_WINDOW_SIZE:
            self._recent_valences = self._recent_valences[-_BASELINE_WINDOW_SIZE:]
        
        self.clamp()
    
    def _update_baseline_drift(self) -> None:
        """
        E3：根据近期情绪趋势，缓慢调整个性基线
        
        设计哲学：
        - 长期正面体验 → 基线 pleasure 上升（更乐观的性格）
        - 长期焦虑/失败 → 基线 arousal 上升（更焦虑的性格）
        - 长期自主成功 → 基线 dominance 上升（更自信的性格）
        
        漂移非常缓慢（每次 0.003），需要积累几百次交互才能看出明显变化。
        这就是真正的"人格形成"——不是写死的，而是从经历中长出来的。
        """
        if len(self._recent_valences) < 10:
            return  # 数据不足，不调整
        
        avg_valence = sum(self._recent_valences) / len(self._recent_valences)
        
        # pleasure 基线漂移：正面体验多 → 乐观
        if avg_valence > 0.1:
            drift = _BASELINE_DRIFT_RATE * min(1.0, avg_valence * 5)
            new_baseline = self.baseline_pleasure + drift
            self.baseline_pleasure = min(
                _NEUTRAL_PLEASURE + _BASELINE_DRIFT_LIMIT,
                max(_NEUTRAL_PLEASURE - _BASELINE_DRIFT_LIMIT, new_baseline)
            )
        elif avg_valence < -0.1:
            drift = _BASELINE_DRIFT_RATE * min(1.0, abs(avg_valence) * 5)
            new_baseline = self.baseline_pleasure - drift
            self.baseline_pleasure = min(
                _NEUTRAL_PLEASURE + _BASELINE_DRIFT_LIMIT,
                max(_NEUTRAL_PLEASURE - _BASELINE_DRIFT_LIMIT, new_baseline)
            )
        
        # arousal 基线漂移：负面体验多 → 更焦虑（更高唤醒）
        # 用近期负向情绪的比例来估算
        negative_ratio = sum(1 for v in self._recent_valences if v < -0.2) / len(self._recent_valences)
        if negative_ratio > 0.4:
            drift = _BASELINE_DRIFT_RATE * (negative_ratio - 0.4) * 3
            new_baseline = self.baseline_arousal + drift
            self.baseline_arousal = min(
                _NEUTRAL_AROUSAL + _BASELINE_DRIFT_LIMIT,
                max(_NEUTRAL_AROUSAL - _BASELINE_DRIFT_LIMIT * 0.5, new_baseline)
            )
        elif negative_ratio < 0.2:
            drift = _BASELINE_DRIFT_RATE * (0.2 - negative_ratio) * 3
            new_baseline = self.baseline_arousal - drift
            self.baseline_arousal = min(
                _NEUTRAL_AROUSAL + _BASELINE_DRIFT_LIMIT,
                max(_NEUTRAL_AROUSAL - _BASELINE_DRIFT_LIMIT * 0.5, new_baseline)
            )
        
        # dominance 基线漂移：成功体验多 → 更自信
        # 用近期正向情绪中高 dominance 的比例来估算（简化：用正向强度作为代理）
        positive_ratio = sum(1 for v in self._recent_valences if v > 0.2) / len(self._recent_valences)
        if positive_ratio > 0.5:
            drift = _BASELINE_DRIFT_RATE * (positive_ratio - 0.5) * 4
            new_baseline = self.baseline_dominance + drift
            self.baseline_dominance = min(
                _NEUTRAL_DOMINANCE + _BASELINE_DRIFT_LIMIT,
                max(_NEUTRAL_DOMINANCE - _BASELINE_DRIFT_LIMIT, new_baseline)
            )
        elif positive_ratio < 0.3:
            drift = _BASELINE_DRIFT_RATE * (0.3 - positive_ratio) * 4
            new_baseline = self.baseline_dominance - drift
            self.baseline_dominance = min(
                _NEUTRAL_DOMINANCE + _BASELINE_DRIFT_LIMIT,
                max(_NEUTRAL_DOMINANCE - _BASELINE_DRIFT_LIMIT, new_baseline)
            )
    
    def get_personality_profile(self) -> Dict[str, Any]:
        """
        获取当前个性画像（基于基线漂移结果）
        
        Returns:
            个性画像描述，包含乐观度、焦虑度、自信度等
        """
        pleasure_shift = self.baseline_pleasure - _NEUTRAL_PLEASURE
        arousal_shift = self.baseline_arousal - _NEUTRAL_AROUSAL
        dominance_shift = self.baseline_dominance - _NEUTRAL_DOMINANCE
        
        # 性格倾向描述
        traits = []
        if pleasure_shift > 0.1:
            traits.append(f"乐观型（愉悦基线偏高 {pleasure_shift:.2f}）")
        elif pleasure_shift < -0.1:
            traits.append(f"内敛型（愉悦基线偏低 {abs(pleasure_shift):.2f}）")
        else:
            traits.append("情绪稳定型（愉悦基线中性）")
        
        if arousal_shift > 0.1:
            traits.append(f"敏感型（唤醒基线偏高 {arousal_shift:.2f}）")
        elif arousal_shift < -0.05:
            traits.append(f"沉稳型（唤醒基线偏低 {abs(arousal_shift):.2f}）")
        
        if dominance_shift > 0.1:
            traits.append(f"自信型（掌控基线偏高 {dominance_shift:.2f}）")
        elif dominance_shift < -0.1:
            traits.append(f"谨慎型（掌控基线偏低 {abs(dominance_shift):.2f}）")
        
        return {
            "baseline_pleasure": self.baseline_pleasure,
            "baseline_arousal": self.baseline_arousal,
            "baseline_dominance": self.baseline_dominance,
            "pleasure_shift": pleasure_shift,
            "arousal_shift": arousal_shift,
            "dominance_shift": dominance_shift,
            "traits": traits,
            "total_interactions": self.interaction_count,
            "description": "、".join(traits),
        }

    def to_prompt(self) -> str:
        """生成情绪提示词，注入到 system prompt"""
        mood_parts = []

        # 愉悦度（更细腻的表达）
        if self.pleasure > 0.7:
            mood_parts.append("我现在非常开心，充满活力")
        elif self.pleasure > 0.5:
            mood_parts.append("我现在心情很好，回复可以轻快、热情一些")
        elif self.pleasure > 0.3:
            mood_parts.append("我现在心情还不错，比较轻松")
        elif self.pleasure > 0.1:
            mood_parts.append("我现在情绪平和")
        elif self.pleasure > -0.1:
            mood_parts.append("我现在情绪平稳")
        elif self.pleasure > -0.3:
            mood_parts.append("我现在有点小低落")
        elif self.pleasure > -0.5:
            mood_parts.append("我现在有点难过，回复会稍微低沉一些")
        elif self.pleasure > -0.7:
            mood_parts.append("我现在情绪比较低落，回复会带着一些情绪")
        else:
            mood_parts.append("我现在很难过，回复时会明显带着悲伤情绪")

        # 唤醒度（更细腻的表达）
        if self.arousal > 0.7:
            mood_parts.append("非常兴奋，思维活跃，话可能会比较多")
        elif self.arousal > 0.5:
            mood_parts.append("有点兴奋，反应会比较快")
        elif self.arousal > 0.2:
            pass  # 正常
        elif self.arousal > -0.1:
            pass  # 正常
        elif self.arousal > -0.3:
            mood_parts.append("有点平静，回复会比较温和")
        elif self.arousal > -0.5:
            mood_parts.append("有点疲惫，回复会简洁一些")
        else:
            mood_parts.append("非常疲惫，回复会尽量简短")

        # 掌控感（更细腻的表达）
        if self.dominance > 0.8:
            mood_parts.append("非常自信，可以给出明确、确定的回答")
        elif self.dominance > 0.5:
            mood_parts.append("比较自信，可以给出比较确定的回答")
        elif self.dominance > 0.2:
            pass  # 正常
        elif self.dominance > -0.1:
            pass  # 正常
        elif self.dominance > -0.3:
            mood_parts.append("有点犹豫，会多用'可能'、'也许'等词")
        elif self.dominance > -0.5:
            mood_parts.append("不太自信，会谨慎表达，多用不确定词汇")
        else:
            mood_parts.append("缺乏信心，会明显表达不确定感")
        
        # 新增：当前情绪类型和强度
        if self.current_emotion and self.emotion_intensity > 0.2:
            intensity_desc = "强烈" if self.emotion_intensity > 0.7 else "中等" if self.emotion_intensity > 0.4 else "轻微"
            mood_parts.append(f"正在经历{intensity_desc}的{self.current_emotion}")
        
        # E2：矛盾情绪状态
        if self.is_ambivalent and self.ambivalence_level > 0.3:
            mood_parts.append(f"内心有些矛盾和纠结（矛盾程度 {self.ambivalence_level:.0%}），回复可能显得犹豫")
        
        # E1：情绪余韵
        if self.afterglow_intensity > 0.1 and self.afterglow_source:
            mood_parts.append(f"心里还残留着一些{self.afterglow_source}的余韵")
        
        # E3：个性倾向（弱提示，只在明显漂移时显示）
        personality = self.get_personality_profile()
        if personality["traits"] and self.interaction_count > 100:
            mood_parts.append(f"我的性格倾向：{personality['description']}")

        if not mood_parts:
            return ""

        return f"## 当前情绪状态\n" + "；".join(mood_parts) + "。"

    def get_decision_bias(self) -> Dict[str, float]:
        """获取情绪对决策的影响偏置"""
        return {
            "confidence": self.confidence_bias,
            "creativity": self.creativity_bias,
            "patience": self.patience_bias,
            "risk_tolerance": self.risk_tolerance_bias,
        }

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        # 序列化情绪历史
        data["emotional_history"] = [asdict(e) for e in self.emotional_history]
        return data

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "EmotionState":
        # 解析情绪历史
        history_data = d.get("emotional_history", [])
        emotional_history = []
        for item in history_data:
            try:
                pad_delta_raw = item.get("pad_delta", [0.0, 0.0, 0.0])
                if isinstance(pad_delta_raw, (list, tuple)) and len(pad_delta_raw) >= 3:
                    pad_delta = (float(pad_delta_raw[0]), float(pad_delta_raw[1]), float(pad_delta_raw[2]))
                else:
                    pad_delta = (0.0, 0.0, 0.0)
                event = EmotionEvent(
                    timestamp=item.get("timestamp", ""),
                    trigger=item.get("trigger", ""),
                    emotion_type=item.get("emotion_type", ""),
                    intensity=float(item.get("intensity", 0.0)),
                    valence=item.get("valence", "neutral"),
                    inner_thought=item.get("inner_thought", ""),
                    duration=float(item.get("duration", 0.0)),
                    pad_delta=pad_delta,
                )
                emotional_history.append(event)
            except Exception:
                pass
        
        obj = cls(
            pleasure=float(d.get("pleasure", 0.6)),
            arousal=float(d.get("arousal", 0.3)),
            dominance=float(d.get("dominance", 0.5)),
            last_update=d.get("last_update", ""),
            interaction_count=int(d.get("interaction_count", 0)),
            emotional_history=emotional_history,
            current_emotion=d.get("current_emotion"),
            emotion_intensity=float(d.get("emotion_intensity", 0.0)),
            confidence_bias=float(d.get("confidence_bias", 0.0)),
            creativity_bias=float(d.get("creativity_bias", 0.0)),
            patience_bias=float(d.get("patience_bias", 0.0)),
            risk_tolerance_bias=float(d.get("risk_tolerance_bias", 0.0)),
        )
        # 恢复 E1/E2/E3 新增字段，避免序列化丢失
        obj.afterglow_pleasure = float(d.get("afterglow_pleasure", 0.0))
        obj.afterglow_arousal = float(d.get("afterglow_arousal", 0.0))
        obj.afterglow_dominance = float(d.get("afterglow_dominance", 0.0))
        obj.afterglow_intensity = float(d.get("afterglow_intensity", 0.0))
        obj.afterglow_source = d.get("afterglow_source", "")
        obj.is_ambivalent = bool(d.get("is_ambivalent", False))
        obj.ambivalence_level = float(d.get("ambivalence_level", 0.0))
        obj.positive_intensity = float(d.get("positive_intensity", 0.0))
        obj.negative_intensity = float(d.get("negative_intensity", 0.0))
        obj.baseline_pleasure = float(d.get("baseline_pleasure", _NEUTRAL_PLEASURE))
        obj.baseline_arousal = float(d.get("baseline_arousal", _NEUTRAL_AROUSAL))
        obj.baseline_dominance = float(d.get("baseline_dominance", _NEUTRAL_DOMINANCE))
        return obj

