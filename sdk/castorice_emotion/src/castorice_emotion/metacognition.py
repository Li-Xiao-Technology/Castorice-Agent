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

import logging
import re
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Deque, Dict, List, Optional, Tuple

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


class Metacognition:
    """
    元认知模块 - 让 Agent 能反思自己的输出。

    设计原则：
    - 纯只读分析，不修改任何内容
    - 所有评估基于已有信息
    - 为 Agent 提供决策参考
    """

    def __init__(self):
        # P2-9: 用 deque(maxlen=N) 替代 list + pop(0)，O(1) 淘汰旧元素
        self._recent_claims: Deque[Dict[str, Any]] = deque(maxlen=50)
        self._max_recent_claims = 50

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
        answer_lower = answer.lower()

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

        # 信号2：不确定性词汇
        uncertainty_words = ["可能", "也许", "大概", "应该", "不确定", "猜测", "似乎", "好像"]
        certainty_words = ["一定", "必然", "绝对", "肯定", "毫无疑问"]
        uncertainty_count = sum(answer_lower.count(w) for w in uncertainty_words)
        certainty_count = sum(answer_lower.count(w) for w in certainty_words)

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
                new_chars = set(new_subj)

                for prev_sent in prev_sentences:
                    prev_numbers = re.findall(r'\d+\.?\d*', prev_sent)
                    if not prev_numbers:
                        continue
                    prev_subj = re.sub(r'\d+\.?\d*', '', prev_sent).strip()
                    if len(prev_subj) < 5:
                        continue
                    prev_chars = set(prev_subj)

                    # 字符级 Jaccard 相似度（判断是否讨论同一主语）
                    overlap = len(new_chars & prev_chars) / max(len(new_chars | prev_chars), 1)
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
        self._recent_claims.append({
            "type": "reasoning_step",
            "content": step_description,
            "evidence": evidence,
            "confidence": confidence,
            "timestamp": step.timestamp,
        })
        # P2-9: deque(maxlen=50) 自动淘汰旧元素，无需手动 pop(0)
        return step

    def record_claim(self, claim: str, evidence: str = "", confidence: float = 0.5) -> None:
        """记录一个事实性声明"""
        self._recent_claims.append({
            "type": "claim",
            "content": claim,
            "evidence": evidence,
            "confidence": confidence,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
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

        # 完整性
        if len(answer) < 20:
            quality.completeness = 0.2
            issues.append("回答过短，可能不完整")
            suggestions.append("补充更多细节")
        elif len(answer) < 100:
            quality.completeness = 0.5
        else:
            quality.completeness = 0.8

        # 准确性（基于是否有证据）
        if tool_results and any(tool_results):
            quality.accuracy = 0.8
        else:
            quality.accuracy = 0.5
            if "多少" in user_input or "数据" in user_input or "今天" in user_input:
                issues.append("涉及数据但未使用工具获取")
                suggestions.append("考虑调用工具获取实时数据")

        # 清晰度
        if any(marker in answer for marker in ["\n", "1.", "2.", "- ", "首先"]):
            quality.clarity = 0.8
        else:
            quality.clarity = 0.5
            if len(answer) > 200:
                suggestions.append("可以使用分点或分段提高清晰度")

        # 总分
        quality.score = (quality.completeness + quality.accuracy + quality.clarity) / 3 * 100
        quality.issues = issues
        quality.improvement_suggestions = suggestions

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
                quality.score < 50
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
        if any(phrase in answer.lower() for phrase in ["我不确定", "可能", "也许"]):
            return False, "回答已经表达了不确定性"
        return False, "置信度可接受"
