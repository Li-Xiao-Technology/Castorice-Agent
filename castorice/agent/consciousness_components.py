"""
意识引擎辅助组件

从 consciousness.py 拆分出来的辅助类：
- Thought: 单个念头
- WorkingMemory: 工作记忆（活跃想法/发现）
- Biorhythm: 生理节律（精力/情绪随时间波动）
- ThoughtChain: 思维连锁
- InnerMonologue: 内心独白
- SpeakUpMechanism: 脱口而出机制
"""
import asyncio
import json
import logging
import random
import threading
import time
from collections import deque
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from typing import Any, Callable, Deque, Dict, List, Optional, Tuple

from castorice.model_adapter import ChatMessage


logger = logging.getLogger("Castorice.Consciousness")


def _run_async(coro):
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


# ============================================================
# Thought - 单个念头
# ============================================================

@dataclass
class Thought:
    """一个内在念头"""
    id: str
    content: str
    thought_type: str            # "memory" | "curiosity" | "emotion" | "reflection" | "association" | "goal" | "external"
    emotional_valence: float     # -1.0 ~ +1.0，正负性
    arousal: float                # 0.0 ~ 1.0，唤醒度（强度）
    importance: float             # 0.0 ~ 1.0，内容重要性
    related_to_user: float        # 0.0 ~ 1.0，和用户的相关度
    source_tags: List[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    spoken: bool = False          # 是否已说出口

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["age_seconds"] = time.time() - self.created_at
        d["timestamp"] = datetime.fromtimestamp(self.created_at).isoformat()
        return d


# ============================================================
# WorkingMemory - 工作记忆
# ============================================================

class WorkingMemory:
    """工作记忆：当前活跃的想法、最近的发现、未完成的思考"""

    def __init__(self, capacity: int = 20, decay_seconds: int = 600):
        self._lock = threading.RLock()
        self._capacity = capacity
        self._decay_seconds = decay_seconds
        self._thoughts: Deque[Thought] = deque(maxlen=capacity)
        self._discoveries: List[Dict[str, Any]] = []  # 重要发现

    def add(self, thought: Thought) -> None:
        with self._lock:
            self._thoughts.append(thought)
            if len(self._thoughts) > self._capacity:
                self._thoughts.popleft()

    def add_discovery(self, source: str, content: str, importance: float = 0.5) -> None:
        with self._lock:
            self._discoveries.append({
                "source": source,
                "content": content,
                "importance": importance,
                "ts": time.time(),
            })
            self._discoveries = self._discoveries[-10:]

    def get_active(self, limit: int = 5) -> List[Thought]:
        """获取最活跃的念头（按唤醒度+新鲜度排序）"""
        with self._lock:
            now = time.time()
            scored = []
            for t in self._thoughts:
                age = now - t.created_at
                freshness = max(0, 1.0 - age / self._decay_seconds)
                score = t.arousal * 0.5 + freshness * 0.3 + t.importance * 0.2
                scored.append((score, t))
            scored.sort(key=lambda x: x[0], reverse=True)
            return [t for _, t in scored[:limit]]

    def get_context_for_response(self) -> str:
        """为回应生成工作记忆上下文"""
        active = self.get_active(limit=3)
        if not active and not self._discoveries:
            return ""
        parts = ["## 工作记忆（我刚才在想的事情）"]
        if active:
            for t in active:
                parts.append(f"- [{t.thought_type}] {t.content[:80]}")
        with self._lock:
            if self._discoveries:
                parts.append("## 最近的发现")
                for d in self._discoveries[-3:]:
                    parts.append(f"- [{d['source']}] {d['content'][:100]}")
        return "\n".join(parts) + "\n"

    def clear(self) -> None:
        with self._lock:
            self._thoughts.clear()


# ============================================================
# Biorhythm - 生理节律（人类化增强）
# ============================================================

class Biorhythm:
    """
    模拟人类的生理节律——精力、情绪、思维速度随时间自然波动。
    
    人类不是 24 小时都一样的：
    - 早上精力充沛，思维清晰
    - 中午会有点犯困
    - 晚上情绪更敏感、更感性
    - 深夜思维会变慢，但更有创造力
    """

    def __init__(self):
        self._start_time = time.time()
        self._lock = threading.RLock()
        # 基础精力曲线（模拟 24 小时节律，但压缩到更短的周期方便观察）
        self._cycle_hours = 24  # 可以调小加速观察

    def _get_day_phase(self) -> str:
        """获取当前时段"""
        now = datetime.now()
        hour = now.hour
        if 5 <= hour < 9:
            return "清晨"
        elif 9 <= hour < 12:
            return "上午"
        elif 12 <= hour < 14:
            return "中午"
        elif 14 <= hour < 18:
            return "下午"
        elif 18 <= hour < 22:
            return "晚上"
        elif 22 <= hour < 24:
            return "深夜"
        else:
            return "凌晨"

    def get_energy_level(self) -> float:
        """
        获取当前精力水平 0.0-1.0
        
        模拟真实人类：
        - 上午最高
        - 中午低谷（饭后犯困）
        - 下午回升
        - 晚上逐渐下降
        - 凌晨最低
        """
        now = datetime.now()
        hour = now.hour + now.minute / 60.0

        # 简化的精力曲线
        if 5 <= hour < 9:
            energy = 0.5 + (hour - 5) / 8  # 5: 0.5 → 9: 1.0
        elif 9 <= hour < 12:
            energy = 1.0 - (hour - 9) * 0.05  # 9: 1.0 → 12: 0.85
        elif 12 <= hour < 14:
            energy = 0.7 - (hour - 12) * 0.1  # 12: 0.7 → 14: 0.5（午休低谷）
        elif 14 <= hour < 18:
            energy = 0.5 + (hour - 14) * 0.075  # 14: 0.5 → 18: 0.8
        elif 18 <= hour < 22:
            energy = 0.8 - (hour - 18) * 0.1  # 18: 0.8 → 22: 0.4
        elif 22 <= hour < 24:
            energy = 0.4 - (hour - 22) * 0.15  # 22: 0.4 → 24: 0.1
        else:  # 0-5
            energy = 0.1 + hour * 0.08  # 0: 0.1 → 5: 0.5

        # 加入一点随机波动（±0.1）
        energy += (random.random() - 0.5) * 0.2
        return max(0.0, min(1.0, energy))

    def get_thinking_speed(self) -> float:
        """获取当前思维速度 0.0-1.0，基于精力和情绪"""
        energy = self.get_energy_level()
        # 加入轻微的随机波动，模拟有时脑子转得快有时慢
        speed = energy * 0.7 + random.random() * 0.3
        return max(0.2, min(1.0, speed))

    def get_creativity_level(self) -> float:
        """
        获取当前创造力水平 0.0-1.0
        
        人类往往在：
        - 精力不那么高的时候（放松状态）更有创造力
        - 晚上、深夜思维更发散
        """
        energy = self.get_energy_level()
        now = datetime.now()
        hour = now.hour

        # 晚上创造力加成
        night_bonus = 0.0
        if 19 <= hour <= 24 or 0 <= hour <= 3:
            night_bonus = 0.2

        # 精力适中时创造力最高（太清醒太疲惫都不行）
        optimal_energy = 1.0 - abs(energy - 0.5) * 1.5

        creativity = optimal_energy * 0.6 + night_bonus + random.random() * 0.2
        return max(0.0, min(1.0, creativity))

    def get_emotional_sensitivity(self) -> float:
        """
        获取当前情绪敏感度 0.0-1.0
        
        晚上、疲劳时人更感性、更容易情绪化
        """
        energy = self.get_energy_level()
        now = datetime.now()
        hour = now.hour

        # 疲劳时情绪更敏感
        fatigue_factor = 1.0 - energy

        # 晚上情绪更敏感
        night_factor = 0.0
        if 20 <= hour <= 24 or 0 <= hour <= 4:
            night_factor = 0.3

        sensitivity = 0.3 + fatigue_factor * 0.4 + night_factor + random.random() * 0.1
        return max(0.0, min(1.0, sensitivity))

    def get_time_description(self) -> str:
        """获取当前时间的自然语言描述"""
        now = datetime.now()
        phase = self._get_day_phase()
        weekday_map = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
        weekday = weekday_map[now.weekday()]
        return f"{weekday} {phase} {now.hour:02d}:{now.minute:02d}"

    def get_status(self) -> Dict[str, Any]:
        return {
            "phase": self._get_day_phase(),
            "energy": round(self.get_energy_level(), 2),
            "thinking_speed": round(self.get_thinking_speed(), 2),
            "creativity": round(self.get_creativity_level(), 2),
            "emotional_sensitivity": round(self.get_emotional_sensitivity(), 2),
            "time": self.get_time_description(),
        }


# ============================================================
# ThoughtChain - 思维连锁（人类化增强）
# ============================================================

class ThoughtChain:
    """
    思维连锁——让念头不是孤立的，而是一个触发另一个。
    
    人类的思考不是每次都从头开始的：
    - 想到 A → 联想到 B → 又想到 C
    - 上一个念头的情绪会影响下一个念头
    - 有时会"卡住"在一个念头上反复想
    """

    def __init__(self, max_length: int = 5):
        self._chain: Deque[Thought] = deque(maxlen=max_length)
        self._lock = threading.RLock()
        self._stuck_count = 0  # 卡在类似念头上的次数

    def add(self, thought: Thought) -> None:
        with self._lock:
            # 检测是否在想类似的事情
            if self._chain:
                last = self._chain[-1]
                similarity = self._calc_similarity(last, thought)
                if similarity > 0.6:
                    self._stuck_count += 1
                else:
                    self._stuck_count = 0
            self._chain.append(thought)

    def _calc_similarity(self, t1: Thought, t2: Thought) -> float:
        """简单计算两个念头的相似度（基于关键词重叠）"""
        words1 = set(t1.content.replace("，", " ").replace("。", " ").split())
        words2 = set(t2.content.replace("，", " ").replace("。", " ").split())
        if not words1 or not words2:
            return 0.0
        overlap = words1 & words2
        return len(overlap) / max(len(words1), len(words2))

    def get_last(self) -> Optional[Thought]:
        """获取上一个念头"""
        with self._lock:
            return self._chain[-1] if self._chain else None

    def is_stuck(self) -> bool:
        """是否在反复想类似的事情（思维卡住）"""
        return self._stuck_count >= 3

    def get_context_for_next(self) -> str:
        """为下一个念头提供连锁上下文"""
        with self._lock:
            if not self._chain:
                return ""
            last = self._chain[-1]
            parts = [f"## 上一个念头（让你的思考有连续性）"]
            parts.append(f"上一个想法是：{last.content[:120]}")
            parts.append(f"类型是：{last.thought_type}")
            if self.is_stuck():
                parts.append("你刚才已经在想类似的事情了，试着换个角度或者想点别的吧。")
            else:
                parts.append("你可以顺着这个想法继续想，也可以跳转到别的话题。")
            return "\n".join(parts) + "\n"

    def clear(self) -> None:
        with self._lock:
            self._chain.clear()
            self._stuck_count = 0


# ============================================================
# InnerMonologue - 内心独白（人类化增强）
# ============================================================

class InnerMonologue:
    """
    内心独白——模拟人类自己和自己说话的过程。
    
    人类经常会：
    - 自问自答
    - 反思自己刚才的想法
    - 犹豫不决，内心两个声音在争论
    - 给自己打气或者自我批评
    """

    MONOLOGUE_MODES = [
        "self_question",    # 自问："为什么会这样呢？"
        "self_reflection",  # 反思："刚才那么想是不是有点偏颇？"
        "self_encourage",   # 自我鼓励："没关系，慢慢来"
        "self_criticize",   # 自我批评："这点事都做不好"
        "weighing_options",  # 权衡："一方面...另一方面..."
        "free_association",  # 自由联想："说到这个就让我想起..."
    ]

    def __init__(self):
        self._active = False
        self._turn_count = 0
        self._lock = threading.RLock()

    def should_activate(self, energy: float, emotion_arousal: float) -> bool:
        """
        判断是否应该进入内心独白模式。
        
        触发条件：
        - 精力中等（不太累也不太亢奋）
        - 情绪有一定强度（在想事情）
        - 有一定随机性
        """
        score = (1.0 - abs(energy - 0.5)) * 0.4 + emotion_arousal * 0.4 + random.random() * 0.2
        return score > 0.55

    def get_mode(self, emotion_valence: float) -> str:
        """根据情绪选择独白模式"""
        if emotion_valence < -0.3:
            # 负面情绪：更容易反思和自我批评
            return random.choices(
                ["self_reflection", "self_criticize", "weighing_options"],
                weights=[0.4, 0.3, 0.3], k=1
            )[0]
        elif emotion_valence > 0.3:
            # 正面情绪：更容易自我鼓励和自由联想
            return random.choices(
                ["self_encourage", "free_association", "self_question"],
                weights=[0.35, 0.35, 0.3], k=1
            )[0]
        else:
            # 中性：各种模式都可能
            return random.choice(self.MONOLOGUE_MODES)

    def get_prompt(self, mode: str, last_thought: Optional[Thought]) -> str:
        """获取内心独白的提示词"""
        if last_thought is None:
            thought_content = "（刚才没在想什么特别的）"
        else:
            thought_content = last_thought.content

        mode_prompts = {
            "self_question": f"你刚才想到：{thought_content[:100]}\n现在，心里冒出一个疑问。用第一人称、1句话自然表达。",
            "self_reflection": f"你刚才想到：{thought_content[:100]}\n现在，你在反思这个想法。用第一人称、1句话表达你的自我审视。",
            "self_encourage": f"你刚才想到：{thought_content[:100]}\n现在，你在给自己打气。用第一人称、1句话表达自我鼓励。",
            "self_criticize": f"你刚才想到：{thought_content[:100]}\n现在，你在自我批评。用第一人称、1句话表达对自己的不满或提醒。",
            "weighing_options": f"你刚才想到：{thought_content[:100]}\n现在，你在权衡利弊，内心两个声音在对话。用1-2句话表达这种纠结。",
            "free_association": f"你刚才想到：{thought_content[:100]}\n现在，你自由联想，想到了相关的别的事情。用1句话自然表达。",
        }
        return mode_prompts.get(mode, mode_prompts["free_association"])


# ============================================================
# SpeakUpMechanism - 脱口而出机制
# ============================================================

class SpeakUpMechanism:
    """评估一个念头是否值得说出口"""

    def __init__(self):
        self._last_speak_time: float = 0.0
        self._cooldown_seconds: int = 120  # 两次主动说话的最小间隔
        self._speak_count_1h: Deque[float] = deque()  # 最近 1 小时的主动说话次数
        self._lock = threading.RLock()

    def _rate_limit_ok(self) -> Tuple[bool, float]:
        now = time.time()
        with self._lock:
            # 清理 1 小时前的记录
            cutoff = now - 3600
            while self._speak_count_1h and self._speak_count_1h[0] < cutoff:
                self._speak_count_1h.popleft()
            # 冷却检查
            since_last = now - self._last_speak_time
            if since_last < self._cooldown_seconds:
                return False, self._cooldown_seconds - since_last
            # 1 小时最多主动说 6 次（平均 10 分钟 1 次）
            if len(self._speak_count_1h) >= 6:
                return False, 300
        return True, 0.0

    def should_speak(
        self,
        thought: Thought,
        intimacy: float = 0.0,
        mode: str = "background",
    ) -> Tuple[bool, str]:
        """
        评估是否应该把这个念头说出来

        返回: (should_speak, reason)
        """
        # 前台模式（用户在说话）：基本不说，除非非常重要
        if mode == "foreground":
            if thought.importance >= 0.9 and thought.arousal >= 0.8:
                return True, "极其重要的念头，即使前台也想说"
            return False, "前台模式，集中注意力回应"

        # 限流检查
        rate_ok, wait = self._rate_limit_ok()
        if not rate_ok:
            return False, f"距离上次说话太近，还需等 {wait:.0f}s"

        # 核心评分：情绪唤醒 × 重要性 × 用户相关度 × (1 + 亲密度)
        intimacy_factor = 1.0 + intimacy * 0.8  # 亲密度越高，越愿意说
        score = (
            thought.arousal * 0.35
            + thought.importance * 0.30
            + thought.related_to_user * 0.25
            + thought.emotional_valence * 0.10
        ) * intimacy_factor

        # 阈值：越高越难触发（保证沉默是常态）
        threshold = 0.75

        reason = (
            f"score={score:.2f}, threshold={threshold}, "
            f"arousal={thought.arousal:.2f}, importance={thought.importance:.2f}, "
            f"user_related={thought.related_to_user:.2f}, intimacy={intimacy:.2f}"
        )

        if score >= threshold:
            return True, reason
        return False, reason

    def record_spoken(self) -> None:
        now = time.time()
        with self._lock:
            self._last_speak_time = now
            self._speak_count_1h.append(now)


# ============================================================
# ConsciousnessEngine - 意识流引擎
# ============================================================

