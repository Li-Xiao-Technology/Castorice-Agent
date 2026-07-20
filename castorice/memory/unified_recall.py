"""
P2.2: 统一记忆检索层
====================

把多种异构记忆整合成单一接口：
- 长期记忆（ChromaDB 向量检索）
- 短期记忆（SQLite / 内存）
- 经历流（SQLite）
- 自我概念（Markdown 文件）
- 学习到的规则（自我概念中的特定章节）

设计原则：
- Agent 每次决策时统一调用 recall(query, context)
- 不用关心底层是哪种存储
- 按相关性排序返回综合记忆上下文
"""
import logging
import threading
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Castorice.Memory.Unified")


class UnifiedMemoryRecall:
    """
    统一记忆检索层

    聚合多种记忆源，提供统一接口 recall()
    """

    def __init__(
        self,
        long_term: Any = None,
        short_term: Any = None,
        experience_journal: Any = None,
        self_concept: Any = None,
        intent_tracker: Any = None,
    ):
        self.long_term = long_term
        self.short_term = short_term
        self.experience_journal = experience_journal
        self.self_concept = self_concept
        self.intent_tracker = intent_tracker
        self._lock = threading.RLock()

    def recall(
        self,
        query: str,
        session_id: str = "",
        top_k_per_source: int = 3,
        include_self_concept: bool = True,
    ) -> Dict[str, Any]:
        """
        统一检索：返回与 query 相关的所有记忆

        :param query: 检索 query
        :param session_id: 会话 ID
        :param top_k_per_source: 每个来源最多取多少条
        :param include_self_concept: 是否包含自我概念
        :return: dict {
            "long_term": [...],          # 长期记忆
            "experiences": [...],        # 经历流
            "self_concept_section": "...",# 自我概念相关章节
            "summary": "...",            # 整体摘要（用于注入 system prompt）
        }
        """
        result = {
            "long_term": [],
            "experiences": [],
            "self_concept_section": "",
            "summary": "",
        }

        with self._lock:
            # 1. 长期记忆（向量检索）
            if self.long_term and getattr(self.long_term, "is_available", False):
                try:
                    if hasattr(self.long_term, "search"):
                        hits = self.long_term.search(query, top_k=top_k_per_source) or []
                        result["long_term"] = list(hits)[:top_k_per_source]
                except Exception as e:
                    logger.debug(f"统一检索-长期记忆失败: {e}")

            # 2. 经历流
            if self.experience_journal is not None:
                try:
                    exps = self.experience_journal.search(
                        query, top_k=top_k_per_source, min_importance=3.0
                    ) or []
                    result["experiences"] = list(exps)[:top_k_per_source]
                except Exception as e:
                    logger.debug(f"统一检索-经历流失败: {e}")

            # 3. 自我概念（按领域分块，按 query 简单匹配最相关章节）
            if include_self_concept and self.self_concept is not None:
                try:
                    structured = self.self_concept.get_structured()
                    if structured:
                        # 简单匹配：哪个章节的关键词最匹配 query
                        scored = []
                        query_words = set(query.lower().split())
                        for section, content in structured.items():
                            content_words = set(content.lower().split())
                            overlap = len(query_words & content_words)
                            if overlap > 0:
                                scored.append((overlap, section, content))
                        scored.sort(reverse=True, key=lambda x: x[0])
                        if scored:
                            _, section, content = scored[0]
                            # 截取前 300 字符
                            result["self_concept_section"] = (
                                f"## {section}\n{content[:300]}"
                            )
                except Exception as e:
                    logger.debug(f"统一检索-自我概念失败: {e}")

            # 提前初始化 summary_parts，避免第128/144行 NameError
            summary_parts = []

            # 4. 跨会话检索（查找相似历史会话）
            if self.short_term is not None and session_id:
                try:
                    similar_sessions = self._find_similar_sessions(query, session_id)
                    if similar_sessions:
                        result["similar_sessions"] = similar_sessions[:3]
                        session_texts = [
                            f"- {s.get('session_id', '')[:15]}: {s.get('summary', '')[:100]}"
                            for s in similar_sessions[:3]
                        ]
                        if session_texts:
                            summary_parts.append(
                                "## 相似历史会话\n" + "\n".join(session_texts)
                            )
                except Exception as e:
                    logger.debug(f"跨会话检索失败: {e}")

            # 5. 未完成意图（来自意图追踪器）
            if self.intent_tracker is not None:
                try:
                    active_intents = self.intent_tracker.get_active_intents(limit=3)
                    if active_intents:
                        intent_texts = [
                            f"- [{i.progress:.0%}] {i.root_intent[:100]}"
                            for i in active_intents
                        ]
                        if intent_texts:
                            summary_parts.append(
                                "## 未完成意图\n" + "\n".join(intent_texts)
                            )
                except Exception as e:
                    logger.debug(f"意图追踪检索失败: {e}")

            # 6. 构造 summary（注入 system prompt 用）
            # summary_parts 已在第118行初始化
            if result["long_term"]:
                long_texts = []
                for item in result["long_term"]:
                    if isinstance(item, dict):
                        text = item.get("text", item.get("document", ""))
                    else:
                        text = str(item)
                    if text:
                        long_texts.append(text[:200])
                if long_texts:
                    summary_parts.append(
                        "## 相关长期记忆\n" + "\n---\n".join(long_texts)
                    )
            if result["experiences"]:
                exp_texts = []
                for exp in result["experiences"]:
                    content = exp.get("content", "") if isinstance(exp, dict) else str(exp)
                    if content:
                        exp_texts.append(content[:200])
                if exp_texts:
                    summary_parts.append(
                        "## 相关经历\n" + "\n".join(f"- {t}" for t in exp_texts)
                    )
            if result["self_concept_section"]:
                summary_parts.append(result["self_concept_section"])
            if result.get("similar_sessions"):
                session_texts = [
                    f"- {s.get('session_id', '')[:15]}: {s.get('summary', '')[:100]}"
                    for s in result["similar_sessions"]
                ]
                if session_texts:
                    summary_parts.append(
                        "## 相似历史会话\n" + "\n".join(session_texts)
                    )

            result["summary"] = "\n\n".join(summary_parts)

        return result

    def _find_similar_sessions(
        self,
        query: str,
        current_session_id: str,
        limit: int = 5,
    ) -> List[Dict[str, Any]]:
        """
        查找与当前 query 相似的历史会话

        :param query: 当前查询文本
        :param current_session_id: 当前会话 ID
        :param limit: 返回数量限制
        :return: 相似会话列表，按相似度排序
        """
        if self.short_term is None:
            return []

        try:
            import difflib

            sessions = self.short_term.list_sessions(archived=None, limit=20)
            if not sessions:
                return []

            similar = []
            query_lower = query.lower()

            for session in sessions:
                sid = session.get("session_id", "")
                if sid == current_session_id:
                    continue

                summary = session.get("summary", "")
                if not summary:
                    continue

                similarity = difflib.SequenceMatcher(
                    None, query_lower, summary.lower()
                ).ratio()

                if similarity > 0.3:
                    similar.append({
                        "session_id": sid,
                        "summary": summary,
                        "similarity": similarity,
                        "created_at": session.get("created_at", ""),
                        "updated_at": session.get("updated_at", ""),
                    })

            similar.sort(key=lambda x: x["similarity"], reverse=True)
            return similar[:limit]

        except Exception as e:
            logger.debug(f"查找相似会话失败: {e}")
            return []
