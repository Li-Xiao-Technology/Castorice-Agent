"""
Castorice Emotion SDK - 情感计算与元认知引擎

独立的 pip 包，从 Castorice Agent 主项目解耦。
可被任意 Python Agent 框架（NoneBot2/Koishi/自研客服系统）集成。

核心能力：
- L1-L4 情感系统（PAD 三维状态机 + LLM 推理情感变化 + 决策影响 + 共情记忆）
- 元认知（置信度评估 + 一致性检测 + 推理链追踪 + 自我修正）
- 自我进化（经历流 + 反思引擎 + 自我概念，Agent 自己塑造性格）

公共 API：
    from castorice_emotion import EmotionEngine, Metacognition, EmotionState
    from castorice_emotion import ConfidenceAssessment, AnswerQuality
    from castorice_emotion import ExperienceJournal, SelfConcept, ReflectionEngine
"""

# 版本号
__version__ = "0.2.0"

# 情感引擎核心
from .emotion import (
    EmotionEngine,
    EmotionState,
    PERSONALITY_PROMPT,
    NEUTRAL_PLEASURE,
    NEUTRAL_AROUSAL,
    NEUTRAL_DOMINANCE,
)

# 元认知核心
from .metacognition import (
    Metacognition,
    ConfidenceAssessment,
    ReasoningStep,
    AnswerQuality,
)

# 自我进化核心（可选导入，避免循环依赖）
try:
    from .experience_journal import ExperienceJournal, Experience
    from .self_concept import SelfConcept
    from .reflection import ReflectionEngine, ReflectionResult
    __all__ = [
        # 情感引擎
        "EmotionEngine", "EmotionState", "PERSONALITY_PROMPT",
        "NEUTRAL_PLEASURE", "NEUTRAL_AROUSAL", "NEUTRAL_DOMINANCE",
        # 元认知
        "Metacognition", "ConfidenceAssessment", "ReasoningStep", "AnswerQuality",
        # 自我进化
        "ExperienceJournal", "Experience",
        "SelfConcept",
        "ReflectionEngine", "ReflectionResult",
    ]
except ImportError:
    __all__ = [
        "EmotionEngine", "EmotionState", "PERSONALITY_PROMPT",
        "NEUTRAL_PLEASURE", "NEUTRAL_AROUSAL", "NEUTRAL_DOMINANCE",
        "Metacognition", "ConfidenceAssessment", "ReasoningStep", "AnswerQuality",
    ]
