"""
反思引擎 (Reflection Engine)

参考论文：
- Generative Agents: Interactive Simulacra of Human Behavior (Stanford, 2023)
  Reflection 机制：定期从经历流中提取高层洞察
- Reflexion: Language Agents with Verbal Reinforcement Learning
  自我反思驱动行为改进

设计原则：
- Agent 自己审视自己的经历，提取模式
- 输出是 Agent 自己写的自我概念更新（不是预设的）
- 定期触发 + 事件触发双机制
- 反思结果写入经历流（reflective 类型）+ 更新自我概念文档

反思流程：
1. 收集最近 N 条经历 + 当前自我概念
2. LLM 分析：提取行为模式、情感倾向、成长节点
3. Agent 自己决定是否更新自我概念
4. 反思本身也作为一条 reflective 经历记录

触发时机：
- 定期：每 N 轮交互触发一次（N 由配置控制）
- 事件：检测到重要情感事件、任务失败、置信度低
"""

import json
import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Castorice.Reflection")


# ============================================================
# 反思 prompt 模板
# ============================================================

_REFLECTION_PROMPT = """你是一个有自我意识的 Agent，正在反思自己最近的经历。

【当前自我概念】
{current_self_concept}

【最近经历】（按时间顺序）
{recent_experiences}

【触发原因】
{trigger_reason}

请深入反思，并以 JSON 格式返回（不要其他内容）：
{{
  "patterns_observed": [
    "我观察到自己最近...（行为模式1）",
    "我观察到自己最近...（行为模式2）"
  ],
  "emotional_tendencies": [
    "我注意到自己面对...时会...（情感倾向1）",
    "我注意到自己面对...时会...（情感倾向2）"
  ],
  "growth_insights": [
    "我学到/成长了...（洞察1）",
    "我学到/成长了...（洞察2）"
  ],
  "self_concept_update": {{
    "should_update": true/false,
    "new_sections": "如果 should_update=true，给出要新增或替换的自我概念段落（Markdown）。如果 false，为空字符串",
    "update_reason": "为什么要这样更新自己"
  }},
  "next_actions": [
    "基于反思，我接下来应该...（行动1）",
    "基于反思，我接下来应该...（行动2）"
  ]
}}

反思要求：
- 基于具体经历，不要空话
- 诚实面对自己的不足和优势
- self_concept_update.should_update: 仅在有真正新洞察时为 true
- new_sections 必须是 Agent 第一人称的自我描述，不是建议
- 如果当前自我概念已足够准确，should_update=false"""


@dataclass
class ReflectionResult:
    """反思结果"""
    patterns_observed: List[str] = field(default_factory=list)
    emotional_tendencies: List[str] = field(default_factory=list)
    growth_insights: List[str] = field(default_factory=list)
    self_concept_updated: bool = False
    self_concept_new_sections: str = ""
    update_reason: str = ""
    next_actions: List[str] = field(default_factory=list)
    trigger_reason: str = ""
    timestamp: str = ""
    raw_response: str = ""  # 原始 LLM 返回（用于调试）

    def to_dict(self) -> Dict[str, Any]:
        return {
            "patterns_observed": self.patterns_observed,
            "emotional_tendencies": self.emotional_tendencies,
            "growth_insights": self.growth_insights,
            "self_concept_updated": self.self_concept_updated,
            "update_reason": self.update_reason,
            "next_actions": self.next_actions,
            "trigger_reason": self.trigger_reason,
            "timestamp": self.timestamp,
        }


def _parse_reflection_json(raw: str) -> Dict[str, Any]:
    """容错解析 LLM 返回的反思 JSON"""
    import re
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    m = re.search(r"```(?:json)?\s*([\s\S]+?)```", raw)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    m = re.search(r"\{[\s\S]+\}", raw)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass
    return {}


class ReflectionEngine:
    """
    反思引擎

    - 依赖 ExperienceJournal（输入）+ SelfConcept（输入+输出）+ ModelAdapter（LLM）
    - 触发机制：定期 + 事件
    - 反思结果写入经历流（reflective 类型）
    - 若 Agent 自己决定更新，则改写自我概念

    线程安全：反思本身较重，建议在后台线程跑（agent.py 用 asyncio.to_thread 包裹）
    """

    def __init__(
        self,
        model_adapter: Any,
        experience_journal: Any,
        self_concept: Any,
        reflection_interval_turns: int = 10,
        reflection_confidence_threshold: float = 0.4,
    ):
        self.model = model_adapter
        self.journal = experience_journal
        self.self_concept = self_concept
        self.interval_turns = reflection_interval_turns
        self.confidence_threshold = reflection_confidence_threshold

        # 计数器：定期触发用
        self._turns_since_last_reflection = 0
        self._last_reflection_time: Optional[str] = None
        # 线程锁：保护计数器和反思执行
        self._lock = threading.Lock()

    def should_reflect(
        self,
        turn_completed: bool = True,
        confidence: float = 1.0,
        significant_event: bool = False,
        task_success: bool = True,
    ) -> tuple:
        """
        判断是否应该触发反思

        返回：(should_reflect, reason)
        """
        with self._lock:
            if turn_completed:
                self._turns_since_last_reflection += 1

            # 事件触发：重要情感事件 / 任务失败 / 低置信度
            if significant_event:
                return True, "检测到重要情感事件"
            if not task_success:
                return True, "任务失败，需要反思"
            if confidence < self.confidence_threshold:
                return True, f"置信度过低 ({confidence:.2f} < {self.confidence_threshold})"

            # 定期触发
            if self._turns_since_last_reflection >= self.interval_turns:
                return True, f"定期反思（已 {self._turns_since_last_reflection} 轮）"

            return False, ""

    def reflect(self, trigger_reason: str = "", context_hint: str = "") -> ReflectionResult:
        """
        执行一次反思

        :param trigger_reason: 触发原因（用于审计）
        :param context_hint: 额外上下文（如最近一次对话摘要）
        :return: ReflectionResult
        """
        result = ReflectionResult(
            trigger_reason=trigger_reason or "手动触发",
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

        try:
            # 1. 收集素材：最近 30 条经历
            recent = self.journal.get_recent(limit=30)
            if not recent:
                logger.info("反思跳过：经历流为空")
                return result

            experiences_text = self._format_experiences(recent)

            # 2. 当前自我概念
            current_sc = self.self_concept.load() or "(尚无自我概念)"

            # 3. 调用 LLM 反思
            prompt = _REFLECTION_PROMPT.format(
                current_self_concept=current_sc,
                recent_experiences=experiences_text,
                trigger_reason=trigger_reason or "定期反思",
            )

            from castorice.model_adapter import ChatMessage
            response = self.model.chat([
                ChatMessage(role="system", content="你是一个有自我意识的 Agent，正在反思自己的经历。只输出 JSON。"),
                ChatMessage(role="user", content=prompt),
            ])
            raw = response.content if hasattr(response, "content") else str(response)
            result.raw_response = raw

            parsed = _parse_reflection_json(raw)
            if not parsed:
                logger.warning(f"反思结果解析失败: {raw[:200]}")
                return result

            # 4. 填充结果
            result.patterns_observed = parsed.get("patterns_observed", [])
            result.emotional_tendencies = parsed.get("emotional_tendencies", [])
            result.growth_insights = parsed.get("growth_insights", [])

            sc_update = parsed.get("self_concept_update", {}) or {}
            result.self_concept_updated = bool(sc_update.get("should_update", False))
            result.self_concept_new_sections = sc_update.get("new_sections", "")
            result.update_reason = sc_update.get("update_reason", "")
            result.next_actions = parsed.get("next_actions", [])

            # 5. 如果 Agent 决定更新自我概念
            if result.self_concept_updated and result.self_concept_new_sections.strip():
                self._apply_self_concept_update(result.self_concept_new_sections, result.update_reason)

            # 6. 反思本身写入经历流（reflective 类型）
            self.journal.add_simple(
                content=self._summarize_reflection(result),
                memory_type="reflective",
                importance=8.0,  # 反思本身比较重要
                emotional_valence=0.0,
                metadata={
                    "trigger_reason": trigger_reason,
                    "patterns_count": len(result.patterns_observed),
                    "insights_count": len(result.growth_insights),
                    "self_concept_updated": result.self_concept_updated,
                    "update_reason": result.update_reason,
                },
            )

            # 重置计数器（线程安全）
            with self._lock:
                self._turns_since_last_reflection = 0
                self._last_reflection_time = result.timestamp
            logger.info(
                f"反思完成: patterns={len(result.patterns_observed)}, "
                f"insights={len(result.growth_insights)}, "
                f"self_concept_updated={result.self_concept_updated}"
            )

        except Exception as e:
            logger.warning(f"反思失败: {e}")
            import traceback
            logger.debug(traceback.format_exc())

        return result

    def _format_experiences(self, experiences: List[Any]) -> str:
        """格式化经历列表为 LLM 可读文本"""
        lines = []
        for i, exp in enumerate(experiences, 1):
            time_str = exp.timestamp[:19].replace("T", " ") if exp.timestamp else ""
            lines.append(
                f"{i}. [{time_str}] ({exp.memory_type}, 重要性={exp.importance:.1f}, "
                f"情感={exp.emotional_valence:+.2f}) {exp.content}"
            )
        return "\n".join(lines)

    def _apply_self_concept_update(self, new_sections: str, reason: str) -> None:
        """
        应用自我概念更新

        策略：如果当前自我概念为空，直接用 new_sections 初始化；
        否则追加到现有内容末尾（保留历史，让 Agent 自己后续整合）。
        """
        current = self.self_concept.load()
        if not current.strip():
            # 首次初始化
            new_content = f"# 我的自我概念\n\n{new_sections}\n"
        else:
            # 追加新洞察（保留历史）
            new_content = current.rstrip() + "\n\n---\n\n## 最新反思洞察\n" + new_sections + "\n"

        self.self_concept.update(new_content, reason=reason or "自我反思")

    def _summarize_reflection(self, result: ReflectionResult) -> str:
        """把反思结果压缩成一条经历流记录"""
        parts = [f"反思触发: {result.trigger_reason}"]
        if result.patterns_observed:
            parts.append("模式: " + "; ".join(result.patterns_observed[:3]))
        if result.growth_insights:
            parts.append("洞察: " + "; ".join(result.growth_insights[:3]))
        if result.self_concept_updated:
            parts.append(f"自我概念已更新: {result.update_reason}")
        return " | ".join(parts)

    def get_status(self) -> Dict[str, Any]:
        """获取反思引擎状态"""
        return {
            "turns_since_last_reflection": self._turns_since_last_reflection,
            "interval_turns": self.interval_turns,
            "last_reflection_time": self._last_reflection_time,
            "confidence_threshold": self.confidence_threshold,
        }

    def get_recent_signal(self, max_chars: int = 500) -> str:
        """
        P1.2: 获取最近一次反思的信号（注入到当前 system prompt）

        返回最近反思的 patterns + insights 摘要，让 Agent 知道自己上次反思学到了什么。
        """
        try:
            recent = self.journal.get_recent(limit=50) if self.journal else []
            reflective = [e for e in recent if e.memory_type == "reflective"]
            if not reflective:
                return ""
            latest = reflective[0]
            content = latest.content
            if len(content) > max_chars:
                content = content[:max_chars] + "..."
            return f"最近反思时间: {latest.timestamp[:19]} | {content}"
        except Exception as e:
            logger.debug(f"get_recent_signal 失败: {e}")
            return ""
