"""
人格画像生成器 (PersonalityProfiler)

聚合情感、价值观、自我概念三个模块的数据，
生成 Agent 的结构化人格画像。

只读取，不修改任何模块的状态。
"""
import logging
import threading
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Castorice.Personality")


@dataclass
class PersonalityProfile:
    """人格画像数据结构"""
    # PAD 情感基线
    pad_baseline: Dict[str, float] = field(default_factory=lambda: {
        "pleasure": 0.5, "arousal": 0.3, "dominance": 0.5
    })
    pad_volatility: Dict[str, float] = field(default_factory=lambda: {
        "pleasure": 0.0, "arousal": 0.0, "dominance": 0.0
    })

    # 价值观画像
    values_radar: List[Dict[str, Any]] = field(default_factory=list)
    top_values: List[Dict[str, Any]] = field(default_factory=list)
    value_signature: str = ""

    # 性格标签云
    traits: List[Dict[str, Any]] = field(default_factory=list)
    speaking_style: Dict[str, float] = field(default_factory=lambda: {
        "formality": 0.5, "emotionality": 0.5, "verbosity": 0.5
    })

    # 元信息
    interaction_count: int = 0
    data_window_days: int = 30
    generated_at: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class PersonalityProfiler:
    """人格画像生成器"""

    # 常见的性格关键词（用于从 self_concept 中提取）
    _TRAIT_KEYWORDS = [
        "好奇", "独立", "温暖", "理性", "创造", "负责", "稳定",
        "成长", "开放", "社交", "幽默", "认真", "冷静", "热情",
        "谨慎", "勇敢", "耐心", "灵活", "坚持", "友善", "诚实",
        "谦逊", "自信", "乐观", "坚韧", "敏锐", "宽容", "自律",
    ]

    def __init__(self, engine: Any = None):
        self.engine = engine
        self._lock = threading.RLock()
        self._cache: Optional[PersonalityProfile] = None
        self._cache_ts: float = 0.0
        self._cache_ttl: float = 60.0  # 缓存 60 秒，避免频繁计算
        logger.info("人格画像生成器已初始化")

    # ---- 对外主方法 ----

    def generate(self, force: bool = False) -> PersonalityProfile:
        """生成完整人格画像（带缓存）"""
        with self._lock:
            now = time.time()
            if not force and self._cache and (now - self._cache_ts) < self._cache_ttl:
                return self._cache

            profile = PersonalityProfile(
                generated_at=datetime.now(timezone.utc).isoformat()
            )

            agent = getattr(self.engine, 'agent', None) if self.engine else None

            # 1. 情感基线
            try:
                emotion = getattr(agent, 'emotion_engine', None) if agent else None
                if emotion:
                    state = emotion.get_state()
                    profile.pad_baseline = {
                        "pleasure": round(getattr(state, 'pleasure', 0.5), 3),
                        "arousal": round(getattr(state, 'arousal', 0.3), 3),
                        "dominance": round(getattr(state, 'dominance', 0.5), 3),
                    }
                    profile.interaction_count = getattr(state, 'interaction_count', 0)

                    # 从历史计算波动幅度
                    hist = getattr(state, 'emotional_history', []) or []
                    if len(hist) > 5:
                        p_vals = [h.pad_delta[0] for h in hist if hasattr(h, 'pad_delta')]
                        a_vals = [h.pad_delta[1] for h in hist if hasattr(h, 'pad_delta')]
                        d_vals = [h.pad_delta[2] for h in hist if hasattr(h, 'pad_delta')]
                        profile.pad_volatility = {
                            "pleasure": round(self._std(p_vals), 3),
                            "arousal": round(self._std(a_vals), 3),
                            "dominance": round(self._std(d_vals), 3),
                        }
            except Exception as e:
                logger.debug(f"情感基线提取失败: {e}")

            # 2. 价值观画像
            try:
                motivation = getattr(agent, 'motivation_system', None) if agent else None
                value_sys = getattr(motivation, '_value_system', None) if motivation else None
                if value_sys and hasattr(value_sys, 'get_all_values'):
                    all_vals = value_sys.get_all_values()
                    profile.values_radar = all_vals

                    top = value_sys.get_top_values(3) if hasattr(value_sys, 'get_top_values') else []
                    profile.top_values = top

                    # 生成价值观签名（Top3 的简短描述）
                    if top:
                        names = [v.get("name", "") for v in top[:3]]
                        strengths = [f"{int(v.get('strength', 0) * 100)}%" for v in top[:3]]
                        profile.value_signature = " · ".join(
                            f"{n}({s})" for n, s in zip(names, strengths)
                        )
            except Exception as e:
                logger.debug(f"价值观画像提取失败: {e}")

            # 3. 性格标签 + 说话风格（从 self_concept 提取）
            try:
                sc = getattr(agent, 'self_concept', None) if agent else None
                if sc and hasattr(sc, 'load'):
                    content = sc.load() or ""
                    profile.traits = self._extract_traits(content)
                    profile.speaking_style = self._analyze_speaking_style(content)
            except Exception as e:
                logger.debug(f"性格标签提取失败: {e}")

            self._cache = profile
            self._cache_ts = now
            return profile

    def get_history(self, days: int = 30) -> Dict[str, Any]:
        """获取历史趋势数据（给前端画折线图用）"""
        result: Dict[str, Any] = {
            "period_days": days,
            "pad_history": [],
            "top_values_history": [],
        }
        try:
            agent = getattr(self.engine, 'agent', None) if self.engine else None
            emotion = getattr(agent, 'emotion_engine', None) if agent else None
            if emotion:
                state = emotion.get_state()
                hist = getattr(state, 'emotional_history', []) or []
                # 每 10 个点采样一个，最多返回 30 个点
                sample_step = max(1, len(hist) // 30)
                sampled = hist[::sample_step][-30:]
                result["pad_history"] = [
                    {
                        "ts": getattr(h, 'timestamp', ''),
                        "pleasure": h.pad_delta[0] if hasattr(h, 'pad_delta') else 0.5,
                        "arousal": h.pad_delta[1] if hasattr(h, 'pad_delta') else 0.3,
                        "dominance": h.pad_delta[2] if hasattr(h, 'pad_delta') else 0.5,
                    }
                    for h in sampled
                ]
        except Exception as e:
            logger.debug(f"历史趋势提取失败: {e}")

        return result

    # ---- 内部辅助方法 ----

    @staticmethod
    def _std(values: List[float]) -> float:
        """简单标准差计算"""
        if not values:
            return 0.0
        n = len(values)
        mean = sum(values) / n
        variance = sum((x - mean) ** 2 for x in values) / n
        return variance ** 0.5

    @classmethod
    def _extract_traits(cls, content: str) -> List[Dict[str, Any]]:
        """从自我概念文本中提取性格标签"""
        traits = []
        if not content:
            return traits

        for word in cls._TRAIT_KEYWORDS:
            # 简单词频 + 位置加权（越早出现越重要）
            count = content.count(word)
            if count > 0:
                pos = content.find(word)
                # 权重 = 出现次数 × 位置因子（越靠前越高）
                weight = min(1.0, count * 0.3 + max(0.0, 1.0 - pos / max(1, len(content))))
                traits.append({
                    "word": word,
                    "weight": round(weight, 3),
                    "source": "self_concept",
                })

        # 按权重排序，最多返回 15 个
        traits.sort(key=lambda x: x["weight"], reverse=True)
        return traits[:15]

    @staticmethod
    def _analyze_speaking_style(content: str) -> Dict[str, float]:
        """从自我概念文本中分析说话风格倾向"""
        style = {"formality": 0.5, "emotionality": 0.5, "verbosity": 0.5}
        if not content:
            return style

        # 正式度：标点符号密度（越正式标点越规范）
        formal_markers = content.count("。") + content.count("；") + content.count("：")
        total_chars = max(1, len(content))
        style["formality"] = round(min(1.0, 0.3 + formal_markers / total_chars * 20), 3)

        # 情感性：emoji/叹号/问号密度
        emo_markers = content.count("!") + content.count("！") + content.count("~")
        emo_markers += sum(1 for c in content if 0x1F300 <= ord(c) <= 0x1FAFF)  # emoji 范围
        style["emotionality"] = round(min(1.0, 0.2 + emo_markers / total_chars * 30), 3)

        # 冗长度：平均句长（越长越啰嗦）
        sentences = [s for s in content.replace("。", "|").replace("！", "|").replace("？", "|").replace("!", "|").replace("?", "|").replace("\n", "|").split("|") if s.strip()]
        if sentences:
            avg_len = sum(len(s) for s in sentences) / len(sentences)
            style["verbosity"] = round(min(1.0, avg_len / 50), 3)

        return style
