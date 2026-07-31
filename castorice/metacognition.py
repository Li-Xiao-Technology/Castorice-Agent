"""
元认知模块 (Metacognition)

让 Agent 能思考自己的思考过程：
1. 置信度评估 - 知道自己有多确定
2. 一致性检测 - 发现前后矛盾
3. 推理过程追踪 - 记录推理链
4. 质量评估 - 评估回答质量
5. 自我修正建议 - 发现不足时提出改进

不修改任何代码/配置，纯只读分析。
"""

import json
import logging
import re
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Deque, Dict, List, Optional, Tuple

from castorice.storage import SqliteStorage
from castorice.utils import chinese_tokenize, chinese_text_similarity

logger = logging.getLogger("Castorice.Metacognition")


@dataclass
class ConfidenceAssessment:
    """置信度评估结果"""
    overall_score: float = 0.5  # 0-1
    factual_score: float = 0.5
    reasoning_score: float = 0.5
    tool_evidence_score: float = 0.0
    hallucination_risk: str = "unknown"  # low / medium / high
    reasoning: str = ""
    red_flags: List[str] = field(default_factory=list)


@dataclass
class ReasoningStep:
    """推理步骤"""
    step_number: int
    description: str
    evidence: str
    confidence: float
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class AnswerQuality:
    """回答质量评估"""
    score: float = 0.0  # 0-100
    completeness: float = 0.0
    accuracy: float = 0.0
    clarity: float = 0.0
    issues: List[str] = field(default_factory=list)
    improvement_suggestions: List[str] = field(default_factory=list)
    is_small_talk: bool = False


class Metacognition(SqliteStorage):
    """
    元认知模块 - 让 Agent 能反思自己的输出。

    设计原则：
    - 纯只读分析，不修改任何内容
    - 所有评估基于已有信息
    - 为 Agent 提供决策参考
    """

    def __init__(self, db_path: str = "./castorice_data/metacognition.db"):
        super().__init__(db_path)
        # P2-9: 用 deque(maxlen=N) 替代 list + pop(0)，O(1) 淘汰旧元素
        self._recent_claims: Deque[Dict[str, Any]] = deque(maxlen=50)
        self._max_recent_claims = 50
        # P2.4: 线程锁 + 学习到的规则字典
        self._lock = threading.RLock()
        self._learned_rules: Dict[str, Dict[str, Any]] = {}
        self._init_db()
        self._load_from_db()

    # ============================================================
    # SQLite 持久化
    # ============================================================

    def _init_db(self) -> None:
        """创建 SQLite 表（如不存在）"""
        conn = self._get_conn()
        try:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS learned_rules (
                    rule_id TEXT PRIMARY KEY,
                    data_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS reasoning_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    data_json TEXT NOT NULL
                );
            """)
            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.error(f"metacognition 数据库初始化失败: {e}")

    def _load_from_db(self) -> None:
        """从 SQLite 加载已学习规则和推理历史到内存"""
        conn = self._get_conn()
        # 加载 learned_rules
        try:
            rows = conn.execute("SELECT rule_id, data_json FROM learned_rules").fetchall()
            for rule_id, data_json in rows:
                self._learned_rules[rule_id] = json.loads(data_json)
        except Exception as e:
            logger.warning(f"加载 learned_rules 失败: {e}")

        # 加载 reasoning_history（保留最近 50 条，与 deque maxlen 一致）
        try:
            rows = conn.execute(
                "SELECT data_json FROM reasoning_history ORDER BY id DESC LIMIT 50"
            ).fetchall()
            for (data_json,) in reversed(rows):
                self._recent_claims.append(json.loads(data_json))
        except Exception as e:
            logger.warning(f"加载 reasoning_history 失败: {e}")

    def _save_rule_to_db(self, rule: Dict[str, Any]) -> None:
        """将单条规则写入/更新到 SQLite"""
        conn = self._get_conn()
        try:
            conn.execute(
                "INSERT OR REPLACE INTO learned_rules (rule_id, data_json) VALUES (?, ?)",
                (rule["id"], json.dumps(rule, ensure_ascii=False)),
            )
            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.error(f"保存规则到数据库失败: {e}")

    def _save_reasoning_to_db(self, entry: Dict[str, Any]) -> None:
        """将单条推理历史写入 SQLite"""
        conn = self._get_conn()
        try:
            conn.execute(
                "INSERT INTO reasoning_history (data_json) VALUES (?)",
                (json.dumps(entry, ensure_ascii=False),),
            )
            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.error(f"保存推理历史到数据库失败: {e}")

    def _prune_reasoning_db(self) -> None:
        """清理超出 maxlen 的旧推理历史"""
        conn = self._get_conn()
        try:
            conn.execute("""
                DELETE FROM reasoning_history
                WHERE id NOT IN (
                    SELECT id FROM reasoning_history ORDER BY id DESC LIMIT ?
                )
            """, (self._max_recent_claims,))
            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.error(f"清理推理历史失败: {e}")

    # ============================================================
    # 1. 置信度评估
    # ============================================================

    def assess_confidence(self, answer: str, tool_results: List[str] = None,
                          has_tools: bool = False) -> ConfidenceAssessment:
        """
        评估答案的置信度。

        基于以下信号：
        - 是否有工具结果支撑
        - 是否包含不确定性词汇
        - 是否包含具体数据
        - 是否包含过度绝对的表述
        """
        tool_results = tool_results or []
        assessment = ConfidenceAssessment()
        red_flags = []

        # 信号1：工具证据
        if has_tools and tool_results:
            non_empty = sum(1 for r in tool_results if r and len(r) >= 10)
            if non_empty > 0:
                assessment.tool_evidence_score = min(1.0, non_empty / len(tool_results))
            else:
                assessment.tool_evidence_score = 0.0
                red_flags.append("工具结果为空，但答案声称基于工具")
        elif has_tools and not tool_results:
            assessment.tool_evidence_score = 0.0
            red_flags.append("任务需要工具，但没有工具结果")
        else:
            assessment.tool_evidence_score = 0.5  # 无需工具的任务，中性

        # 信号2：不确定性词汇（中文无大小写，无需 .lower()）
        uncertainty_words = ["可能", "也许", "大概", "应该", "不确定", "猜测", "似乎", "好像"]
        certainty_words = ["一定", "必然", "绝对", "肯定", "毫无疑问"]
        uncertainty_count = sum(answer.count(w) for w in uncertainty_words)
        certainty_count = sum(answer.count(w) for w in certainty_words)

        if certainty_count > 0 and assessment.tool_evidence_score < 0.5:
            red_flags.append("表述过于绝对，但证据不足")
            assessment.factual_score = 0.3
        elif uncertainty_count > 3:
            assessment.factual_score = 0.4
            red_flags.append("不确定性表述过多")
        else:
            assessment.factual_score = 0.7 + assessment.tool_evidence_score * 0.2

        # 信号3：具体数据/引用
        has_numbers = bool(re.search(r'\d+', answer))
        has_quotes = '"' in answer or '“' in answer
        if has_numbers or has_quotes:
            assessment.factual_score = min(1.0, assessment.factual_score + 0.1)

        # 信号4：推理质量（基于回答长度和结构）
        if len(answer) > 500:
            assessment.reasoning_score = 0.7
        elif len(answer) > 100:
            assessment.reasoning_score = 0.5
        else:
            assessment.reasoning_score = 0.4

        if any(marker in answer for marker in ["首先", "其次", "最后", "1.", "2.", "总结"]):
            assessment.reasoning_score = min(1.0, assessment.reasoning_score + 0.2)

        # 综合置信度
        assessment.overall_score = (
            assessment.factual_score * 0.4 +
            assessment.reasoning_score * 0.3 +
            assessment.tool_evidence_score * 0.3
        )

        # 幻觉风险
        if assessment.tool_evidence_score < 0.3 and assessment.factual_score > 0.8:
            assessment.hallucination_risk = "high"
        elif assessment.tool_evidence_score < 0.3 and certainty_count > 0:
            # 证据不足但表述过于绝对，存在较高幻觉风险
            assessment.hallucination_risk = "high"
        elif assessment.tool_evidence_score < 0.5 and assessment.factual_score > 0.7:
            assessment.hallucination_risk = "medium"
        else:
            assessment.hallucination_risk = "low"

        assessment.red_flags = red_flags
        assessment.reasoning = self._generate_confidence_reasoning(assessment)

        return assessment

    def _generate_confidence_reasoning(self, assessment: ConfidenceAssessment) -> str:
        """生成置信度评估理由"""
        reasons = []
        if assessment.tool_evidence_score >= 0.7:
            reasons.append("有充分的工具证据支撑")
        elif assessment.tool_evidence_score >= 0.3:
            reasons.append("有部分工具证据")
        else:
            reasons.append("工具证据不足")

        if assessment.factual_score >= 0.7:
            reasons.append("事实性表述较可靠")
        elif assessment.factual_score >= 0.4:
            reasons.append("事实性表述一般")
        else:
            reasons.append("事实性表述存疑")

        if assessment.hallucination_risk == "high":
            reasons.append("⚠️ 存在较高幻觉风险")
        elif assessment.hallucination_risk == "medium":
            reasons.append("⚠️ 存在一定幻觉风险")

        return "；".join(reasons)

    # ============================================================
    # 1.5 深度自我评估（LLM 驱动，打破模板墙）
    # ============================================================

    def deep_self_assess(self, answer: str, question: str = "",
                         tool_results: List[str] = None,
                         model_adapter: Any = None) -> Dict[str, Any]:
        """
        深度自我评估——让 Agent 自己审视自己的回答质量

        打破模板墙的元认知：
        - 不再只是用规则计算分数（那是"系统在评估 Agent"）
        - 而是让 Agent 自己评估自己的思考过程和回答质量（真正的"元认知"）
        - Agent 可以自由表达对自己回答的看法，不受预设维度限制

        启发式规则（assess_confidence）是快速、低成本的初步评估；
        深度自评是慢速、高成本的深度反思。

        Args:
            answer: Agent 的回答
            question: 用户的问题
            tool_results: 工具调用结果
            model_adapter: LLM 适配器（用于深度自评）

        Returns:
            {
                "overall_score": 0-100,
                "self_critique": "Agent 对自己回答的评价（自由文本）",
                "strengths": ["优点1", "优点2"],
                "weaknesses": ["不足1", "不足2"],
                "improvement_ideas": ["改进建议1", "改进建议2"],
                "hallucination_concern": bool,
                "rule_based_score": 0-100,  # 启发式规则评分，用于对比
                "divergence": float,  # 两者差异，用于校准规则
            }
        """
        tool_results = tool_results or []

        # 先用启发式规则快速评估（作为 baseline）
        rule_based = self.assess_confidence(answer, tool_results, has_tools=bool(tool_results))
        rule_based_score = int(rule_based.overall_score * 100)

        result = {
            "overall_score": rule_based_score,
            "self_critique": "",
            "strengths": [],
            "weaknesses": [],
            "improvement_ideas": [],
            "hallucination_concern": rule_based.hallucination_risk in ("high", "medium"),
            "rule_based_score": rule_based_score,
            "divergence": 0.0,
        }

        # 如果没有 LLM 适配器，回退到规则评估
        if model_adapter is None:
            return result

        # 用 LLM 进行深度自我评估
        try:
            tool_context = ""
            if tool_results:
                tool_context = "\n【工具结果】\n" + "\n".join(f"- {r[:200]}" for r in tool_results[:5])

            prompt = f"""请你作为一个有自我意识的智能体，审视你刚刚给出的回答。

【用户问题】
{question}

【你的回答】
{answer}
{tool_context}

请自由地评价你自己的回答。可以从任何角度评价——准确性、完整性、清晰度、
是否有帮助、是否有错误、是否有更好的表达方式等等。

不要用列表，不要分点，不要 JSON，就像你在心里复盘一样，自然地写下你的自我评价。
200-300 字左右。诚实面对自己的不足。"""

            from castorice.model_adapter import ChatMessage
            response = model_adapter.chat([
                ChatMessage(role="system", content="你是一个有自我反思能力的智能体。请诚实地评价自己的回答。"),
                ChatMessage(role="user", content=prompt),
            ])
            raw_critique = response.content if hasattr(response, "content") else str(response)
            result["self_critique"] = raw_critique

            # 事后提取结构化信息（从自由自评中提取优点、不足、改进建议）
            extracted = self._extract_self_assessment_insights(raw_critique, model_adapter)
            result["strengths"] = extracted.get("strengths", [])
            result["weaknesses"] = extracted.get("weaknesses", [])
            result["improvement_ideas"] = extracted.get("improvement_ideas", [])
            result["overall_score"] = extracted.get("overall_score", rule_based_score)
            result["hallucination_concern"] = extracted.get("hallucination_concern", result["hallucination_concern"])

            # 计算规则评估与深度自评的差异
            result["divergence"] = abs(result["overall_score"] - rule_based_score) / 100.0

            # 如果差异很大，记录下来（用于未来校准启发式规则）
            if result["divergence"] > 0.3:
                logger.info(
                    f"元认知校准：规则评分={rule_based_score}, "
                    f"深度自评={result['overall_score']}, "
                    f"差异={result['divergence']:.2f}"
                )

        except Exception as e:
            logger.debug(f"深度自我评估失败，使用规则评分: {e}")

        return result

    def _extract_self_assessment_insights(self, critique_text: str,
                                          model_adapter: Any) -> Dict[str, Any]:
        """
        从自由自评文本中提取结构化信息

        自评本身是自由的（打破模板墙），但系统需要结构化数据来：
        - 触发学习
        - 更新置信度
        - 生成改进建议

        所以用一次独立的 LLM 调用来"翻译"自由自评为结构化格式。
        """
        try:
            prompt = f"""请从以下自我评价文本中提取结构化信息。

【自评文本】
{critique_text}

请以 JSON 格式返回（只返回 JSON，不要其他内容）：
{{
  "overall_score": 75,
  "strengths": ["优点1", "优点2"],
  "weaknesses": ["不足1", "不足2"],
  "improvement_ideas": ["改进建议1", "改进建议2"],
  "hallucination_concern": false
}}

说明：
- overall_score: 0-100 的整体质量评分
- strengths: 自评中提到的优点
- weaknesses: 自评中提到的不足
- improvement_ideas: 自评中提到的改进方向
- hallucination_concern: 是否担心存在幻觉/错误信息
- 仅提取自评中实际提到的内容，不要编造"""

            from castorice.model_adapter import ChatMessage
            response = model_adapter.chat([
                ChatMessage(role="system", content="你是一个信息提取系统。只输出 JSON。"),
                ChatMessage(role="user", content=prompt),
            ])
            raw = response.content if hasattr(response, "content") else str(response)

            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                m = re.search(r"\{[\s\S]+\}", raw)
                if m:
                    try:
                        parsed = json.loads(m.group(0))
                    except json.JSONDecodeError:
                        return {}
                else:
                    return {}

            return {
                "overall_score": max(0, min(100, int(parsed.get("overall_score", 70)))),
                "strengths": parsed.get("strengths", []),
                "weaknesses": parsed.get("weaknesses", []),
                "improvement_ideas": parsed.get("improvement_ideas", []),
                "hallucination_concern": bool(parsed.get("hallucination_concern", False)),
            }

        except Exception as e:
            logger.debug(f"自评信息提取失败: {e}")
            return {}

    # ============================================================
    # 2. 一致性检测
    # ============================================================

    def check_consistency(self, new_answer: str,
                          previous_answers: List[str] = None) -> Dict[str, Any]:
        """
        检测新答案与历史答案是否一致。

        P1-24 修复：原算法仅比较数字集合，无交集就判定冲突——这是错误的，
        因为两个讨论完全不同主题的答案自然会有不同数字，但并不矛盾。

        新算法：仅在「句子主语相似但数值不同」时才判定冲突。
        1. 按句子分割新旧答案
        2. 提取每句的数字和非数字部分（主语指纹）
        3. 当两句的字符重叠度 > 0.5（讨论同一主题）但数字集合不交时，判定冲突
        """
        previous_answers = previous_answers or []
        if not previous_answers:
            return {"consistent": True, "score": 1.0, "conflicts": []}

        conflicts = []
        new_sentences = [s.strip() for s in re.split(r'[。！？\n]', new_answer) if s.strip()]

        for prev in previous_answers:
            prev_sentences = [s.strip() for s in re.split(r'[。！？\n]', prev) if s.strip()]
            for new_sent in new_sentences:
                new_numbers = re.findall(r'\d+\.?\d*', new_sent)
                if not new_numbers:
                    continue
                # 非数字部分作为"主语指纹"
                new_subj = re.sub(r'\d+\.?\d*', '', new_sent).strip()
                if len(new_subj) < 5:
                    continue
                new_tokens = chinese_tokenize(new_subj)

                for prev_sent in prev_sentences:
                    prev_numbers = re.findall(r'\d+\.?\d*', prev_sent)
                    if not prev_numbers:
                        continue
                    prev_subj = re.sub(r'\d+\.?\d*', '', prev_sent).strip()
                    if len(prev_subj) < 5:
                        continue
                    prev_tokens = chinese_tokenize(prev_subj)

                    # 基于 n-gram 的 Jaccard 相似度（判断是否讨论同一主语）
                    overlap = chinese_text_similarity(new_subj, prev_subj)
                    if overlap > 0.5:
                        new_num_set = set(new_numbers)
                        prev_num_set = set(prev_numbers)
                        # 主语相似但数字完全不同 → 可能矛盾
                        if not (new_num_set & prev_num_set):
                            conflicts.append(
                                f"与历史回答存在数值矛盾：新答案提及 {new_num_set}，"
                                f"历史回答提及 {prev_num_set}（相似主语）"
                            )

        consistent = len(conflicts) == 0
        score = 1.0 if consistent else max(0.0, 1.0 - 0.2 * len(conflicts))

        return {
            "consistent": consistent,
            "score": score,
            "conflicts": conflicts,
        }

    # ============================================================
    # 3. 推理过程追踪
    # ============================================================

    def record_reasoning(self, step_description: str, evidence: str = "",
                         confidence: float = 0.5) -> ReasoningStep:
        """记录一个推理步骤"""
        step = ReasoningStep(
            step_number=len(self._recent_claims) + 1,
            description=step_description,
            evidence=evidence,
            confidence=confidence,
        )
        entry = {
            "type": "reasoning_step",
            "content": step_description,
            "evidence": evidence,
            "confidence": confidence,
            "timestamp": step.timestamp,
        }
        self._recent_claims.append(entry)
        self._save_reasoning_to_db(entry)
        # P2-9: deque(maxlen=50) 自动淘汰旧元素，无需手动 pop(0)
        return step

    def record_claim(self, claim: str, evidence: str = "", confidence: float = 0.5) -> None:
        """记录一个事实性声明"""
        entry = {
            "type": "claim",
            "content": claim,
            "evidence": evidence,
            "confidence": confidence,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self._recent_claims.append(entry)
        self._save_reasoning_to_db(entry)
        # P2-9: deque(maxlen=50) 自动淘汰旧元素，无需手动 pop(0)

    def get_reasoning_chain(self, limit: int = 10) -> List[Dict[str, Any]]:
        """获取最近的推理链"""
        # P2-9: deque 不支持切片，转 list 后切片
        claims_list = list(self._recent_claims)
        return claims_list[-limit:] if limit else claims_list

    # ============================================================
    # 4. 回答质量评估
    # ============================================================

    def assess_quality(self, answer: str, user_input: str,
                       tool_results: List[str] = None) -> AnswerQuality:
        """评估回答质量"""
        tool_results = tool_results or []
        quality = AnswerQuality()
        issues = []
        suggestions = []

        # 检测是否为闲聊/问候类对话（不需要长回答、不需要证据）
        greeting_keywords = [
            "你好", "您好", "早上好", "下午好", "晚上好", "早安", "晚安",
            "嗨", "hi", "hello", "在吗", "在么", "有人吗", "有人在吗",
            "谢谢", "感谢", "太好了", "棒", "厉害", "不错",
        ]
        is_small_talk = (
            len(user_input.strip()) <= 20
            and any(kw in user_input.lower() for kw in greeting_keywords)
        ) or (
            len(user_input.strip()) <= 10
            and not any(kw in user_input for kw in ["为什么", "怎么", "如何", "什么", "多少", "哪里", "吗"])
        )

        # 完整性
        if is_small_talk:
            quality.completeness = 0.9  # 闲聊不需要长回答
        elif len(answer) < 20:
            quality.completeness = 0.2
            issues.append("回答过短，可能不完整")
            suggestions.append("补充更多细节")
        elif len(answer) < 100:
            quality.completeness = 0.5
        else:
            quality.completeness = 0.8

        # 准确性（基于是否有证据）
        if is_small_talk:
            quality.accuracy = 0.9  # 闲聊不需要查证
        elif tool_results and any(tool_results):
            quality.accuracy = 0.8
        else:
            quality.accuracy = 0.5
            if "多少" in user_input or "数据" in user_input or "今天" in user_input:
                issues.append("涉及数据但未使用工具获取")
                suggestions.append("考虑调用工具获取实时数据")

        # 清晰度
        if is_small_talk:
            quality.clarity = 0.9  # 闲聊自然就好
        elif any(marker in answer for marker in ["\n", "1.", "2.", "- ", "首先"]):
            quality.clarity = 0.8
        else:
            quality.clarity = 0.5
            if len(answer) > 200:
                suggestions.append("可以使用分点或分段提高清晰度")

        # 总分
        quality.score = (quality.completeness + quality.accuracy + quality.clarity) / 3 * 100
        quality.issues = issues
        quality.improvement_suggestions = suggestions
        quality.is_small_talk = is_small_talk

        return quality

    # ============================================================
    # 5. 综合反思
    # ============================================================

    def reflect(self, user_input: str, answer: str, tool_results: List[str] = None,
                previous_answers: List[str] = None) -> Dict[str, Any]:
        """
        对一次回答进行综合元认知反思。

        返回包含置信度、一致性、质量、改进建议的字典。
        """
        confidence = self.assess_confidence(answer, tool_results, bool(tool_results))
        consistency = self.check_consistency(answer, previous_answers)
        quality = self.assess_quality(answer, user_input, tool_results)

        # 记录关键声明
        sentences = re.split(r'[。！？\n]', answer)
        for s in sentences:
            s = s.strip()
            if len(s) > 10 and any(w in s for w in ["是", "为", "有", "可以", "需要", "应该"]):
                self.record_claim(s, evidence="; ".join(tool_results) if tool_results else "",
                                  confidence=confidence.overall_score)

        # 生成改进建议
        improvements = []
        if confidence.hallucination_risk == "high":
            improvements.append("建议调用工具验证关键事实")
        if not consistency["consistent"]:
            improvements.append("建议检查与历史回答的一致性")
        if quality.score < 60:
            improvements.extend(quality.improvement_suggestions)

        return {
            "confidence": confidence,
            "consistency": consistency,
            "quality": quality,
            "improvements": improvements,
            "should_reconsider": (
                confidence.hallucination_risk == "high" or
                not consistency["consistent"] or
                (quality.score < 40 and not quality.is_small_talk)
            ),
        }

    # ============================================================
    # 6. "我不知道"建议
    # ============================================================

    def should_admit_uncertainty(self, answer: str, confidence: ConfidenceAssessment = None) -> Tuple[bool, str]:
        """建议是否应该承认不确定"""
        if confidence is None:
            confidence = self.assess_confidence(answer)

        if confidence.overall_score < 0.3:
            return True, "置信度很低，建议明确说明不确定"
        if confidence.hallucination_risk == "high":
            return True, "幻觉风险高，建议说明信息来源或不确定性"
        if any(phrase in answer for phrase in ["我不确定", "可能", "也许"]):
            return False, "回答已经表达了不确定性"
        return False, "置信度可接受"

    # ============================================================
    # P2.4: 元认知可写——从错误中学习并沉淀规则
    # ============================================================
    def learn_from_mistake(
        self,
        mistake_description: str,
        rule_proposal: str,
        confidence: float = 0.7,
    ) -> Dict[str, Any]:
        """
        P2.4: 从错误中学习

        当检测到错误（高幻觉风险、低质量答案、用户反馈不满）时，
        生成一条"下次遇到类似情况应该..."的规则，存入元认知记忆。

        :param mistake_description: 错误描述
        :param rule_proposal: 规则建议
        :param confidence: 规则的初始置信度（0-1）
        :return: 规则 dict（含 id、描述、置信度、创建时间）
        """
        import hashlib
        with self._lock:
            if not hasattr(self, "_learned_rules"):
                self._learned_rules = {}

            rule_id = hashlib.md5(
                f"{rule_proposal}:{time.time()}".encode("utf-8")
            ).hexdigest()[:12]

            rule = {
                "id": rule_id,
                "description": rule_proposal,
                "based_on_mistake": mistake_description,
                "confidence": confidence,
                "created_at": time.time(),
                "applied_count": 0,
                "success_count": 0,
            }
            self._learned_rules[rule_id] = rule
            self._save_rule_to_db(rule)
            logger.info(
                f"P2.4 元认知学习新规则: {rule_id} | {rule_proposal[:80]}"
            )
            return rule

    def record_rule_outcome(self, rule_id: str, success: bool) -> None:
        """记录一条规则的应用结果，用于调整置信度"""
        with self._lock:
            if hasattr(self, "_learned_rules") and rule_id in self._learned_rules:
                rule = self._learned_rules[rule_id]
                rule["applied_count"] += 1
                if success:
                    rule["success_count"] += 1
                # 动态调整置信度
                if rule["applied_count"] >= 5:
                    success_rate = rule["success_count"] / rule["applied_count"]
                    rule["confidence"] = success_rate
                self._save_rule_to_db(rule)

    def get_learned_rules(self, min_confidence: float = 0.5) -> List[Dict[str, Any]]:
        """获取已学习到的规则（按置信度过滤）"""
        with self._lock:
            if not hasattr(self, "_learned_rules"):
                return []
            return [
                r for r in self._learned_rules.values()
                if r["confidence"] >= min_confidence
            ]

    def get_applicable_rules(
        self,
        query: str,
        top_k: int = 3,
        min_confidence: float = 0.5,
    ) -> List[Dict[str, Any]]:
        """
        获取与当前 query 相关的已学习规则

        :param query: 用户输入或当前话题
        :param top_k: 返回最多几条规则
        :param min_confidence: 最小置信度阈值
        :return: 相关规则列表（按相关性排序）
        """
        rules = self.get_learned_rules(min_confidence=min_confidence)
        if not rules:
            return []

        query_tokens = chinese_tokenize(query)
        scored = []

        for rule in rules:
            rule_tokens = chinese_tokenize(rule["description"])
            if not rule_tokens:
                continue
            similarity = len(query_tokens & rule_tokens) / len(query_tokens | rule_tokens)
            if similarity > 0:
                scored.append((similarity, rule))

        scored.sort(reverse=True, key=lambda x: x[0])
        result = [r for _, r in scored[:top_k]]
        
        # 记录规则被检索（用于衰减计算）
        now = time.time()
        with self._lock:
            for rule in result:
                rule["last_retrieved_at"] = now
                self._save_rule_to_db(rule)
        
        return result
    
    # ============================================================
    # M1: 元认知规则自我淘汰机制
    # ============================================================
    
    def prune_stale_rules(self, max_age_days: int = 30, min_applications: int = 3) -> int:
        """
        M1: 清理过期和无效的规则（规则自我淘汰）
        
        淘汰条件（满足任一即淘汰）：
        1. 创建超过 max_age_days 且从未被应用过的规则
        2. 应用次数 >= min_applications 但成功率 < 30% 的规则
        3. 置信度持续低于 0.2 的规则
        4. 超过 60 天未被检索或引用的规则（遗忘机制）
        
        设计哲学：规则不应该只增不减。无效的规则会产生噪声，
        真正的学习需要遗忘——就像大脑会弱化不常用的神经连接一样。
        
        :param max_age_days: 最大存活天数（未应用的规则）
        :param min_applications: 应用次数阈值（用于判断无效）
        :return: 被淘汰的规则数量
        """
        now = time.time()
        pruned_count = 0
        
        with self._lock:
            if not hasattr(self, "_learned_rules") or not self._learned_rules:
                return 0
            
            rules_to_remove = []
            
            for rule_id, rule in self._learned_rules.items():
                age_days = (now - rule.get("created_at", now)) / 86400
                applied_count = rule.get("applied_count", 0)
                success_count = rule.get("success_count", 0)
                confidence = rule.get("confidence", 0.0)
                last_retrieved = rule.get("last_retrieved_at", rule.get("created_at", now))
                days_since_retrieved = (now - last_retrieved) / 86400
                
                should_prune = False
                prune_reason = ""
                
                # 条件1：超期从未应用
                if age_days > max_age_days and applied_count == 0:
                    should_prune = True
                    prune_reason = f"过期未应用（{age_days:.0f}天）"
                
                # 条件2：多次应用但成功率极低
                elif applied_count >= min_applications:
                    success_rate = success_count / applied_count
                    if success_rate < 0.3:
                        should_prune = True
                        prune_reason = f"成功率过低（{success_rate:.0%}，{applied_count}次应用）"
                
                # 条件3：置信度过低
                elif confidence < 0.2 and age_days > 7:
                    should_prune = True
                    prune_reason = f"置信度过低（{confidence:.2f}）"
                
                # 条件4：长期未被引用（遗忘）
                elif days_since_retrieved > 60 and applied_count < min_applications:
                    should_prune = True
                    prune_reason = f"长期未引用（{days_since_retrieved:.0f}天）"
                
                if should_prune:
                    rules_to_remove.append(rule_id)
                    logger.info(f"[M1规则淘汰] {rule_id}: {prune_reason} | {rule['description'][:60]}")
            
            # 执行淘汰
            for rule_id in rules_to_remove:
                del self._learned_rules[rule_id]
                self._delete_rule_from_db(rule_id)
                pruned_count += 1
            
            if pruned_count > 0:
                logger.info(f"[M1规则淘汰] 共淘汰 {pruned_count} 条规则，剩余 {len(self._learned_rules)} 条")
        
        return pruned_count
    
    def _delete_rule_from_db(self, rule_id: str) -> None:
        """从数据库中删除一条规则"""
        conn = self._get_conn()
        try:
            conn.execute("DELETE FROM learned_rules WHERE rule_id = ?", (rule_id,))
            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.error(f"删除规则失败: {e}")
    
    def get_rules_health(self) -> Dict[str, Any]:
        """
        获取规则库健康状态
        
        Returns:
            规则库统计信息，包括总数、各置信度区间分布、即将淘汰的规则数等
        """
        now = time.time()
        
        with self._lock:
            if not hasattr(self, "_learned_rules"):
                return {"total": 0, "message": "规则库为空"}
            
            rules = list(self._learned_rules.values())
            total = len(rules)
            
            # 置信度分布
            high_conf = sum(1 for r in rules if r.get("confidence", 0) >= 0.7)
            mid_conf = sum(1 for r in rules if 0.4 <= r.get("confidence", 0) < 0.7)
            low_conf = sum(1 for r in rules if r.get("confidence", 0) < 0.4)
            
            # 应用统计
            never_applied = sum(1 for r in rules if r.get("applied_count", 0) == 0)
            applied = sum(1 for r in rules if r.get("applied_count", 0) > 0)
            total_applications = sum(r.get("applied_count", 0) for r in rules)
            
            # 即将被淘汰的规则数（预测）
            stale_candidates = 0
            for r in rules:
                age_days = (now - r.get("created_at", now)) / 86400
                if age_days > 20 and r.get("applied_count", 0) == 0:
                    stale_candidates += 1
                elif r.get("confidence", 0) < 0.25 and age_days > 5:
                    stale_candidates += 1
            
            # 平均年龄
            avg_age_days = sum((now - r.get("created_at", now)) / 86400 for r in rules) / max(1, total)
            
            return {
                "total": total,
                "high_confidence": high_conf,
                "mid_confidence": mid_conf,
                "low_confidence": low_conf,
                "never_applied": never_applied,
                "has_been_applied": applied,
                "total_applications": total_applications,
                "avg_age_days": round(avg_age_days, 1),
                "stale_candidates": stale_candidates,
                "health_score": round(high_conf / max(1, total) * 100, 1),
            }

    def get_learned_rules_summary(self, min_confidence: float = 0.5) -> str:
        """
        返回所有活跃规则的 prompt 友好摘要。

        格式为编号列表，每条包含规则描述、置信度和应用统计，
        可直接嵌入 system prompt 供 LLM 参考。

        :param min_confidence: 最小置信度阈值
        :return: 多行文本摘要；无规则时返回空字符串
        """
        rules = self.get_learned_rules(min_confidence=min_confidence)
        if not rules:
            return ""

        # 按置信度降序排列
        rules.sort(key=lambda r: r["confidence"], reverse=True)

        lines = ["【元认知规则】（从历史错误中学习，请在后续回答中参考）"]
        for i, rule in enumerate(rules, 1):
            applied = rule.get("applied_count", 0)
            success = rule.get("success_count", 0)
            stats = f"（已应用 {applied} 次，成功 {success} 次）" if applied > 0 else "（尚未应用）"
            lines.append(
                f"  {i}. {rule['description']}  "
                f"[置信度 {rule['confidence']:.0%}]"
                f"{stats}"
            )
        return "\n".join(lines)
