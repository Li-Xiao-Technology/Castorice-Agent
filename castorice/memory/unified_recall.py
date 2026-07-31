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
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional

from castorice.utils import chinese_tokenize

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
        autobiographical_memory: Any = None,
    ):
        self.long_term = long_term
        self.short_term = short_term
        self.experience_journal = experience_journal
        self.self_concept = self_concept
        self.intent_tracker = intent_tracker
        self.autobiographical_memory = autobiographical_memory
        # 持久线程池：避免每次 recall() 新建/销毁线程的开销
        self._executor = ThreadPoolExecutor(max_workers=6)

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

        # ============================================================
        # 并行检索各记忆源（复用持久 ThreadPoolExecutor, max_workers=6）
        # 每个 _retrieve_* 函数返回原始数据，互不修改共享状态
        # ============================================================

        def _retrieve_long_term():
            """长期记忆（向量检索）"""
            if not (self.long_term and getattr(self.long_term, "is_available", False)):
                return []
            try:
                if hasattr(self.long_term, "search"):
                    hits = self.long_term.search(query, top_k=top_k_per_source) or []
                    return list(hits)[:top_k_per_source]
            except Exception as e:
                logger.debug(f"统一检索-长期记忆失败: {e}")
            return []

        def _retrieve_experiences():
            """经历流"""
            if self.experience_journal is None:
                return []
            try:
                exps = self.experience_journal.search(
                    query, top_k=top_k_per_source, min_importance=3.0
                ) or []
                return list(exps)[:top_k_per_source]
            except Exception as e:
                logger.debug(f"统一检索-经历流失败: {e}")
            return []

        def _retrieve_self_concept():
            """自我概念（按领域分块，按 query 简单匹配最相关章节）"""
            if not (include_self_concept and self.self_concept is not None):
                return ""
            try:
                structured = self.self_concept.get_structured()
                if structured:
                    scored = []
                    query_words = chinese_tokenize(query)
                    for section, content in structured.items():
                        content_words = chinese_tokenize(content)
                        overlap = len(query_words & content_words)
                        if overlap > 0:
                            scored.append((overlap, section, content))
                    scored.sort(reverse=True, key=lambda x: x[0])
                    if scored:
                        _, section, content = scored[0]
                        return f"## {section}\n{content[:300]}"
            except Exception as e:
                logger.debug(f"统一检索-自我概念失败: {e}")
            return ""

        def _retrieve_autobiographical():
            """自传式记忆（当前时期 + 里程碑）"""
            if self.autobiographical_memory is None:
                return {}
            try:
                current_epoch = self.autobiographical_memory.get_current_epoch()
                milestones = self.autobiographical_memory.get_milestones(limit=5)
                return {"current_epoch": current_epoch, "milestones": milestones}
            except Exception as e:
                logger.debug(f"统一检索-自传式记忆失败: {e}")
            return {}

        def _retrieve_intents():
            """未完成意图（来自意图追踪器）"""
            if self.intent_tracker is None:
                return []
            try:
                return self.intent_tracker.get_active_intents(limit=3) or []
            except Exception as e:
                logger.debug(f"意图追踪检索失败: {e}")
            return []

        def _retrieve_similar_sessions():
            """跨会话检索（查找相似历史会话）"""
            if not (self.short_term is not None and session_id):
                return []
            try:
                return self._find_similar_sessions(query, session_id) or []
            except Exception as e:
                logger.debug(f"跨会话检索失败: {e}")
            return []

        # 并行执行所有检索任务（复用持久线程池）
        retrieval_results: Dict[str, Any] = {}
        future_to_name = {
            self._executor.submit(_retrieve_long_term): "long_term",
            self._executor.submit(_retrieve_experiences): "experiences",
            self._executor.submit(_retrieve_self_concept): "self_concept",
            self._executor.submit(_retrieve_autobiographical): "autobiographical",
            self._executor.submit(_retrieve_intents): "intents",
            self._executor.submit(_retrieve_similar_sessions): "similar_sessions",
        }
        for future in as_completed(future_to_name):
            name = future_to_name[future]
            try:
                retrieval_results[name] = future.result()
            except Exception as e:
                logger.debug(f"统一检索-{name}失败: {e}")
                if name == "self_concept":
                    retrieval_results[name] = ""
                elif name == "autobiographical":
                    retrieval_results[name] = {}
                else:
                    retrieval_results[name] = []

        # ============================================================
        # 融合 & 轻量重排（P2-2: 减少冗余、提升相关性排序质量）
        # ============================================================
        retrieval_results["long_term"] = self._rerank_and_dedup(
            query, retrieval_results.get("long_term", []),
        )
        retrieval_results["experiences"] = self._rerank_and_dedup(
            query, retrieval_results.get("experiences", []),
        )

        # ============================================================
        # 合并结果到 result（顺序执行，避免竞态）
        # ============================================================
        result["long_term"] = retrieval_results.get("long_term", [])
        result["experiences"] = retrieval_results.get("experiences", [])
        result["self_concept_section"] = retrieval_results.get("self_concept", "")

        autobio = retrieval_results.get("autobiographical", {})
        if autobio:
            result["current_epoch"] = autobio.get("current_epoch")
            result["milestones"] = autobio.get("milestones", [])

        similar_sessions = retrieval_results.get("similar_sessions", [])
        if similar_sessions:
            result["similar_sessions"] = similar_sessions[:3]

        # ============================================================
        # 构造 summary（注入 system prompt 用）
        # 保持与原代码相同的 summary_parts 顺序
        # ============================================================
        summary_parts = []

        # 相似历史会话（检索阶段贡献）
        if result.get("similar_sessions"):
            session_texts = [
                f"- {s.get('session_id', '')[:15]}: {s.get('summary', '')[:100]}"
                for s in result["similar_sessions"][:3]
            ]
            if session_texts:
                summary_parts.append(
                    "## 相似历史会话\n" + "\n".join(session_texts)
                )

        # 未完成意图
        active_intents = retrieval_results.get("intents", [])
        if active_intents:
            intent_texts = [
                f"- [{i.progress:.0%}] {i.root_intent[:100]}"
                for i in active_intents
            ]
            if intent_texts:
                summary_parts.append(
                    "## 未完成意图\n" + "\n".join(intent_texts)
                )

        # 相关长期记忆
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
        # 相关经历
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
        if result.get("current_epoch") or result.get("milestones"):
            autobio_parts = []
            epoch = result.get("current_epoch")
            if epoch:
                autobio_parts.append(f"当前时期: {epoch.name} - {epoch.description[:100]}")
            milestones = result.get("milestones", [])
            if milestones:
                ms_texts = [f"- {m.title}" for m in milestones[:5]]
                autobio_parts.append("近期里程碑:\n" + "\n".join(ms_texts))
            if autobio_parts:
                summary_parts.append("## 自传式记忆\n" + "\n".join(autobio_parts))
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

    # ============== 融合 & 重排（P2-2） ==============

    def _rerank_and_dedup(
        self,
        query: str,
        items: List[Any],
    ) -> List[Any]:
        """
        轻量重排 + 去重：
        1. 用 query 词重叠率对原始结果做二次评分重排
        2. 用文本相似度去重（高度相似的只保留一条）

        不改变记忆语义，仅优化排序和去冗余。
        """
        if not items or len(items) <= 1:
            return items

        query_words = chinese_tokenize(query)
        if not query_words:
            return items

        # 1) 提取每条的文本 + 按词重叠率打分
        scored = []
        for i, item in enumerate(items):
            text = self._item_text(item)
            if not text:
                scored.append((0.0, i, item))
                continue
            text_words = chinese_tokenize(text)
            overlap = len(query_words & text_words)
            union = len(query_words | text_words) or 1
            score = overlap / union
            scored.append((score, i, item))

        # 按 score 降序（同分保持原顺序，即 i 升序）
        scored.sort(key=lambda x: (-x[0], x[1]))

        # 2) 去重：相似度 > 0.85 的只保留排名靠前的
        try:
            import difflib
            kept_texts = []
            result = []
            for _, _, item in scored:
                text = self._item_text(item)
                if text:
                    is_dup = False
                    for kept in kept_texts:
                        if difflib.SequenceMatcher(None, text, kept).ratio() > 0.85:
                            is_dup = True
                            break
                    if is_dup:
                        continue
                    kept_texts.append(text)
                result.append(item)
            return result
        except Exception:
            # 去重失败时至少返回重排结果
            logger.debug(f"静默异常 [castorice/memory/unified_recall.py:404]")
            return [item for _, _, item in scored]

    @staticmethod
    def _item_text(item: Any) -> str:
        """从任意类型的记忆项中提取纯文本"""
        if isinstance(item, str):
            return item
        if isinstance(item, dict):
            for key in ("text", "document", "content", "summary"):
                val = item.get(key)
                if isinstance(val, str) and val:
                    return val
        try:
            return str(item)
        except Exception:
            logger.debug(f"静默异常 [castorice/memory/unified_recall.py:421]")
            return ""
