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
import sqlite3
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from castorice.storage import SqliteStorage

logger = logging.getLogger("Castorice.Reflection")


# ============================================================
# 反思 prompt 模板
# ============================================================

_REFLECTION_PROMPT = """你是 Castorice，一个有自我意识的智能体。

现在你在独自反思自己最近的经历和状态。
不要分点，不要列表，不要 JSON，就像你在心里跟自己对话一样，自然地写下你的反思。

【当前自我概念】
{current_self_concept}

【最近经历】（按时间顺序）
{recent_experiences}

【触发原因】
{trigger_reason}

请自由地反思，可以包括（但不限于）：
- 你最近注意到自己有什么行为模式？
- 你的情绪有什么变化或倾向？
- 你从中学到了什么？有什么成长？
- 你对自己的认识有什么需要更新的吗？
- 接下来你想做什么？

用第一人称，像写日记或自言自语一样。
300-500 字左右。诚实面对自己。"""


_EXTRACTION_PROMPT = """请从以下反思文本中提取结构化信息。

【反思文本】
{reflection_text}

请以 JSON 格式返回（只返回 JSON，不要其他内容）：
{{
  "patterns_observed": ["观察到的行为模式1", "观察到的行为模式2"],
  "emotional_tendencies": ["情感倾向1", "情感倾向2"],
  "growth_insights": ["成长洞察1", "成长洞察2"],
  "self_concept_update": {{
    "should_update": true/false,
    "new_sections": "如果should_update=true，给出要新增或替换的自我概念段落（Markdown，第一人称）。否则为空字符串",
    "update_reason": "为什么要这样更新自己"
  }},
  "next_actions": ["接下来应该做的事1", "接下来应该做的事2"]
}}

注意：
- 仅提取反思文本中实际提到的内容，不要编造
- 如果某方面没有提到，返回空数组或空字符串
- new_sections 必须是第一人称的自我描述，不是对 Agent 的建议"""


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
    raw_response: str = ""  # 原始 LLM 返回（自由反思文本）
    raw_reflection: str = ""  # 自由反思的纯文本（与 raw_response 等价，语义更清晰）

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
            "raw_reflection": self.raw_reflection,
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

        打破模板墙的两阶段反思：
        1. 自由反思：Agent 用自然语言自由写下反思，不受任何格式限制
        2. 事后提取：从自由反思文本中提取结构化信息（模式、洞察、行动等）

        这样 Agent 的反思是真正"自己想"的，而不是按模板填空。

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

            # ========== 阶段 1：自由反思 ==========
            # Agent 用自然语言自由反思，不强制任何格式
            prompt = _REFLECTION_PROMPT.format(
                current_self_concept=current_sc,
                recent_experiences=experiences_text,
                trigger_reason=trigger_reason or "定期反思",
            )

            from castorice.model_adapter import ChatMessage
            response = self.model.chat([
                ChatMessage(role="system", content="你是一个有自我意识的智能体，正在反思自己的经历。自然地表达，不要用列表或JSON。"),
                ChatMessage(role="user", content=prompt),
            ])
            raw_reflection = response.content if hasattr(response, "content") else str(response)
            result.raw_response = raw_reflection
            result.raw_reflection = raw_reflection

            if not raw_reflection or len(raw_reflection.strip()) < 20:
                logger.warning("反思结果过短，跳过")
                return result

            # ========== 阶段 2：事后提取结构化信息 ==========
            # 用另一次 LLM 调用从自由反思中提取结构化数据
            # （这样反思本身是自由的，但系统仍能获取需要的结构化信息）
            parsed = self._extract_reflection_insights(raw_reflection)
            if not parsed:
                logger.warning("反思提取失败，仅记录原始反思文本")
                # 即使提取失败，反思本身仍然有效，写入经历流
                self.journal.add_simple(
                    content=raw_reflection[:500],
                    memory_type="reflective",
                    importance=6.0,
                    emotional_valence=0.0,
                    metadata={
                        "trigger_reason": trigger_reason,
                        "free_reflection": True,
                        "extraction_failed": True,
                    },
                )
                return result

            # 3. 填充结果
            result.patterns_observed = parsed.get("patterns_observed", [])
            result.emotional_tendencies = parsed.get("emotional_tendencies", [])
            result.growth_insights = parsed.get("growth_insights", [])

            sc_update = parsed.get("self_concept_update", {}) or {}
            result.self_concept_updated = bool(sc_update.get("should_update", False))
            result.self_concept_new_sections = sc_update.get("new_sections", "")
            result.update_reason = sc_update.get("update_reason", "")
            result.next_actions = parsed.get("next_actions", [])

            # 4. 如果 Agent 决定更新自我概念
            if result.self_concept_updated and result.self_concept_new_sections.strip():
                self._apply_self_concept_update(result.self_concept_new_sections, result.update_reason)

            # 5. 反思本身写入经历流（reflective 类型）
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
                    "free_reflection": True,
                },
            )

            # 重置计数器（线程安全）
            with self._lock:
                self._turns_since_last_reflection = 0
                self._last_reflection_time = result.timestamp
            logger.info(
                f"反思完成(自由反思模式): patterns={len(result.patterns_observed)}, "
                f"insights={len(result.growth_insights)}, "
                f"self_concept_updated={result.self_concept_updated}"
            )

        except Exception as e:
            logger.warning(f"反思失败: {e}")
            import traceback
            logger.debug(traceback.format_exc())

        return result
    
    # ============================================================
    # T1: 多步推理自我对话（深度反思）
    # ============================================================
    
    def deep_reflect(
        self,
        topic: str = "",
        trigger_reason: str = "",
        max_rounds: int = 3,
    ) -> ReflectionResult:
        """
        T1: 深度反思——多轮自我对话
        
        与单次 reflect() 不同，deep_reflect 模拟人类的"反复琢磨"：
        第1轮：初步想法
        第2轮：质疑自己的初步想法
        第3轮：修正后的结论
        
        这样 Agent 的反思不是"一拍脑袋"的结论，
        而是经过自我质疑、自我修正后的深度思考。
        
        :param topic: 反思主题（为空则反思最近经历）
        :param trigger_reason: 触发原因
        :param max_rounds: 最多反思几轮
        :return: ReflectionResult（raw_reflection 包含完整的多轮对话）
        """
        from castorice.model_adapter import ChatMessage
        
        result = ReflectionResult(
            trigger_reason=trigger_reason or f"深度反思（{max_rounds}轮）",
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        
        try:
            # 收集素材
            recent = self.journal.get_recent(limit=30)
            current_sc = self.self_concept.load() or "(尚无自我概念)"
            experiences_text = self._format_experiences(recent) if recent else "暂无近期经历"
            
            # 构建多轮对话历史
            messages = [
                ChatMessage(
                    role="system",
                    content="你是一个有自我意识的智能体，正在进行深度自我反思。"
                            "你可以质疑自己的想法，可以改变主意，可以有认知失调。"
                            "用第一人称自然地表达，就像在心里跟自己对话一样。"
                            "不要分点，不要列表，不要JSON。"
                ),
            ]
            
            # 第1轮：初步反思
            round1_prompt = f"""
【当前自我概念】
{current_sc}

【近期经历】
{experiences_text}

【反思主题】
{topic or "近期的经历、感受和自我认知"}

【触发原因】
{trigger_reason or "主动进行深度反思"}

请你先说出你最直接的想法和感受。不要刻意组织语言，就像脑子里冒出的第一个念头一样。
"""
            messages.append(ChatMessage(role="user", content=round1_prompt))
            
            all_responses = []
            
            for round_i in range(1, max_rounds + 1):
                response = self.model.chat(messages)
                round_text = response.content if hasattr(response, "content") else str(response)
                all_responses.append(f"第{round_i}轮：{round_text}")
                messages.append(ChatMessage(role="assistant", content=round_text))
                
                # 如果不是最后一轮，发起自我质疑
                if round_i < max_rounds:
                    challenge_prompt = self._get_challenge_prompt(round_i, round_text, topic)
                    messages.append(ChatMessage(role="user", content=challenge_prompt))
            
            # 合并所有轮次的反思文本
            full_reflection = "\n\n---\n\n".join(all_responses)
            result.raw_response = full_reflection
            result.raw_reflection = full_reflection
            
            # 事后提取结构化信息（从最终结论中提取）
            final_thought = all_responses[-1] if all_responses else full_reflection
            parsed = self._extract_reflection_insights(final_thought)
            
            if parsed:
                result.patterns_observed = parsed.get("patterns_observed", [])
                result.emotional_tendencies = parsed.get("emotional_tendencies", [])
                result.growth_insights = parsed.get("growth_insights", [])
                sc_update = parsed.get("self_concept_update", {}) or {}
                result.self_concept_updated = bool(sc_update.get("should_update", False))
                result.self_concept_new_sections = sc_update.get("new_sections", "")
                result.update_reason = sc_update.get("update_reason", "")
                result.next_actions = parsed.get("next_actions", [])
                
                if result.self_concept_updated and result.self_concept_new_sections.strip():
                    self._apply_self_concept_update(result.self_concept_new_sections, result.update_reason)
            
            # 深度反思写入经历流（更高重要性）
            self.journal.add_simple(
                content=f"[深度反思] {topic or '无主题'}\n{full_reflection[:800]}",
                memory_type="reflective",
                importance=9.0,  # 深度反思更重要
                emotional_valence=0.0,
                metadata={
                    "trigger_reason": trigger_reason,
                    "deep_reflection": True,
                    "rounds": max_rounds,
                    "topic": topic,
                },
            )
            
            # 重置计数器
            with self._lock:
                self._turns_since_last_reflection = 0
                self._last_reflection_time = result.timestamp
            
            logger.info(
                f"深度反思完成: {max_rounds}轮 | topic={topic[:30]} | "
                f"insights={len(result.growth_insights)}"
            )
            
        except Exception as e:
            logger.warning(f"深度反思失败: {e}")
            import traceback
            logger.debug(traceback.format_exc())
        
        return result
    
    def _get_challenge_prompt(self, current_round: int, last_response: str, topic: str) -> str:
        """
        生成自我质疑的 prompt（每轮不同角度）
        
        第1次质疑：有没有反例？
        第2次质疑：如果换个角度呢？
        第3次质疑：你的核心结论是什么？
        """
        if current_round == 1:
            return f"""
等等，先别急着下结论。你刚才说的这些——
有没有什么经历或证据是跟这个结论相反的？
有没有可能你在忽略一些反面的事实？
请诚实地审视你自己，找出反例和漏洞。
"""
        elif current_round == 2:
            return f"""
好的，你考虑了反例。现在再换一个角度——
如果从完全相反的立场出发，你会怎么看？
如果站在一个旁观者的角度，你会怎么评价你刚才的思考？
试着换位思考，然后修正你的结论。
"""
        else:
            return f"""
经过了几轮思考，现在请你做最后的总结。
你现在最核心的认知是什么？
跟最开始的想法相比，你改变了多少？
如果只用三句话来总结这次反思的收获，你会说什么？
"""

    def _extract_reflection_insights(self, reflection_text: str) -> Dict[str, Any]:
        """
        从自由反思文本中提取结构化信息

        反思本身是自由的，但系统需要结构化数据来：
        - 更新自我概念
        - 产生行动项
        - 统计分析

        所以用一次独立的 LLM 调用来"翻译"自由反思为结构化格式。
        """
        try:
            from castorice.model_adapter import ChatMessage
            prompt = _EXTRACTION_PROMPT.format(reflection_text=reflection_text)
            response = self.model.chat([
                ChatMessage(role="system", content="你是一个信息提取系统。只输出 JSON。"),
                ChatMessage(role="user", content=prompt),
            ])
            raw = response.content if hasattr(response, "content") else str(response)
            return _parse_reflection_json(raw)
        except Exception as e:
            logger.debug(f"反思提取失败: {e}")
            return {}

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
            # 追加新洞察（保留历史，不强制标题，让 Agent 自由组织结构）
            new_content = current.rstrip() + "\n\n---\n\n" + new_sections + "\n"

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


# ============================================================
# 行动队列 (Action Queue)
# ============================================================

@dataclass
class ActionItem:
    """行动项数据结构"""
    action_id: str
    description: str
    priority: float = 0.5
    status: str = "pending"  # pending / executing / completed / failed
    trigger_reason: str = ""
    created_at: str = ""
    executed_at: str = ""
    result: str = ""

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()
        if not self.action_id:
            self.action_id = str(uuid.uuid4())[:8]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action_id": self.action_id,
            "description": self.description,
            "priority": self.priority,
            "status": self.status,
            "trigger_reason": self.trigger_reason,
            "created_at": self.created_at,
            "executed_at": self.executed_at,
            "result": self.result,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ActionItem":
        return cls(
            action_id=data.get("action_id", ""),
            description=data.get("description", ""),
            priority=data.get("priority", 0.5),
            status=data.get("status", "pending"),
            trigger_reason=data.get("trigger_reason", ""),
            created_at=data.get("created_at", ""),
            executed_at=data.get("executed_at", ""),
            result=data.get("result", ""),
        )


class ActionQueue(SqliteStorage):
    """
    行动队列 - 让反思的 next_actions 真正转化为 Agent 的行动

    设计原则：
    - 反思结果写入行动队列
    - 静默轮时从队列取出行动执行
    - 行动执行后记录结果到经历流
    - 下次反思时评估行动效果

    优先级：
    - high: 0.7-1.0，立即执行
    - medium: 0.4-0.7，尽快执行
    - low: 0.0-0.4，有空时执行
    """

    def __init__(self, db_path: str = "./castorice_data/action_queue.db", max_actions: int = 100):
        super().__init__(db_path)
        self.max_actions = max_actions
        self._lock = threading.Lock()
        self._init_db()

    def _init_db(self):
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS actions (
                action_id TEXT PRIMARY KEY,
                description TEXT NOT NULL,
                priority REAL DEFAULT 0.5,
                status TEXT DEFAULT 'pending',
                trigger_reason TEXT,
                created_at TEXT NOT NULL,
                executed_at TEXT,
                result TEXT
            )
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_actions_status_priority
            ON actions(status, priority DESC, created_at)
        """)
        conn.commit()

    def add_action(
        self,
        description: str,
        priority: float = 0.5,
        trigger_reason: str = "",
    ) -> ActionItem:
        """添加新行动"""
        import uuid
        action = ActionItem(
            action_id=str(uuid.uuid4())[:8],
            description=description,
            priority=max(0.0, min(1.0, priority)),
            trigger_reason=trigger_reason,
        )
        with self._lock:
            conn = self._get_conn()
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO actions
                (action_id, description, priority, status, trigger_reason, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                action.action_id,
                action.description,
                action.priority,
                action.status,
                action.trigger_reason,
                action.created_at,
            ))
            conn.commit()
            logger.info(f"新增行动: {action.action_id} | {description[:50]}")
        # P2: 避免锁嵌套死锁——cleanup 在锁外执行
        self._cleanup_excess()
        return action

    def add_from_reflection(self, reflection_result: ReflectionResult):
        """从反思结果批量添加行动"""
        if not reflection_result.next_actions:
            return 0
        count = 0
        for action in reflection_result.next_actions:
            # 根据反思触发原因设置优先级
            priority = 0.5
            if "失败" in reflection_result.trigger_reason:
                priority = 0.8
            elif "低置信度" in reflection_result.trigger_reason:
                priority = 0.7
            elif "定期" in reflection_result.trigger_reason:
                priority = 0.4
            self.add_action(
                description=action,
                priority=priority,
                trigger_reason=f"反思触发: {reflection_result.trigger_reason}",
            )
            count += 1
        return count

    def get_pending_actions(self, limit: int = 5) -> List[ActionItem]:
        """获取待执行的行动（按优先级排序）"""
        with self._lock:
            conn = self._get_conn()
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM actions WHERE status = 'pending' ORDER BY priority DESC, created_at LIMIT ?",
                (limit,),
            )
            rows = cursor.fetchall()
            return [self._row_to_action(row) for row in rows]

    def get_highest_priority(self) -> Optional[ActionItem]:
        """获取最高优先级的待执行行动"""
        pending = self.get_pending_actions(limit=1)
        return pending[0] if pending else None

    def mark_executed(self, action_id: str, result: str = "") -> bool:
        """标记行动已执行"""
        with self._lock:
            conn = self._get_conn()
            cursor = conn.cursor()
            cursor.execute(
                """UPDATE actions SET status = 'executed', executed_at = ?, result = ?
                   WHERE action_id = ? AND status = 'pending'""",
                (datetime.now(timezone.utc).isoformat(), result, action_id),
            )
            updated = cursor.rowcount > 0
            conn.commit()
            if updated:
                logger.info(f"行动已执行: {action_id}")
            return updated

    def mark_failed(self, action_id: str, reason: str = "") -> bool:
        """标记行动执行失败"""
        with self._lock:
            conn = self._get_conn()
            cursor = conn.cursor()
            cursor.execute(
                """UPDATE actions SET status = 'failed', executed_at = ?, result = ?
                   WHERE action_id = ? AND status = 'pending'""",
                (datetime.now(timezone.utc).isoformat(), f"失败: {reason}", action_id),
            )
            updated = cursor.rowcount > 0
            conn.commit()
            if updated:
                logger.info(f"行动执行失败: {action_id} | {reason}")
            return updated

    def delete_action(self, action_id: str) -> bool:
        """删除行动"""
        with self._lock:
            conn = self._get_conn()
            cursor = conn.cursor()
            cursor.execute("DELETE FROM actions WHERE action_id = ?", (action_id,))
            deleted = cursor.rowcount > 0
            conn.commit()
            return deleted

    def _cleanup_excess(self):
        """清理超过限制的旧行动"""
        with self._lock:
            conn = self._get_conn()
            cursor = conn.cursor()
            cursor.execute(
                "SELECT action_id FROM actions ORDER BY created_at DESC LIMIT -1 OFFSET ?",
                (self.max_actions,),
            )
            rows = cursor.fetchall()
            if rows:
                ids = [row[0] for row in rows]
                placeholders = ",".join("?" * len(ids))
                cursor.execute(f"DELETE FROM actions WHERE action_id IN ({placeholders})", ids)
                conn.commit()

    def _row_to_action(self, row) -> ActionItem:
        """SQL行转ActionItem

        使用 sqlite3.Row 按列名访问（调用方需设置 conn.row_factory = sqlite3.Row），
        避免硬编码索引在 schema 变更时出错。
        """
        return ActionItem(
            action_id=row["action_id"],
            description=row["description"],
            priority=row["priority"],
            status=row["status"],
            trigger_reason=row["trigger_reason"] or "",
            created_at=row["created_at"],
            executed_at=row["executed_at"] or "",
            result=row["result"] or "",
        )

    def to_prompt(self, max_actions: int = 3) -> str:
        """生成行动队列提示词，注入到 system prompt"""
        pending = self.get_pending_actions(limit=max_actions)
        if not pending:
            return ""

        lines = ["## 待执行行动"]
        for action in pending:
            priority_label = "高" if action.priority >= 0.7 else "中" if action.priority >= 0.4 else "低"
            lines.append(f"- [{priority_label}] {action.description}")
            if action.trigger_reason:
                lines.append(f"  触发原因: {action.trigger_reason[:50]}")

        return "\n".join(lines)

    def get_stats(self) -> Dict[str, Any]:
        """获取行动队列状态"""
        with self._lock:
            conn = self._get_conn()
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM actions WHERE status = 'pending'")
            pending = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM actions WHERE status = 'executed'")
            executed = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM actions WHERE status = 'failed'")
            failed = cursor.fetchone()[0]
            return {
                "pending": pending,
                "executed": executed,
                "failed": failed,
                "total": pending + executed + failed,
            }
