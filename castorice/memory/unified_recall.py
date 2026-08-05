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
        emotion_state: Optional[Dict[str, float]] = None,
    ) -> Dict[str, Any]:
        """
        统一检索：返回与 query 相关的所有记忆（情感感知版）

        情感感知：当提供 emotion_state 时，记忆检索会受到当前情绪的"染色"——
        悲伤时更容易想起悲伤的事，开心时更容易想起开心的事。
        这不是模板，而是模拟人类"情绪一致性记忆"的认知现象。

        :param query: 检索 query
        :param session_id: 会话 ID
        :param top_k_per_source: 每个来源最多取多少条
        :param include_self_concept: 是否包含自我概念
        :param emotion_state: 可选，当前情绪状态 {"pleasure": float, "arousal": float, "dominance": float}
        :return: dict {
            "long_term": [...],          # 长期记忆
            "experiences": [...],        # 经历流
            "self_concept_section": "...",# 自我概念相关章节
            "summary": "...",            # 整体摘要（用于注入 system prompt）
            "emotion_coloring": "...",   # 情感染色描述（Agent 能看到自己现在是带着什么情绪在回忆）
        }
        """
        result = {
            "long_term": [],
            "experiences": [],
            "self_concept_section": "",
            "summary": "",
            "emotion_coloring": "",
        }

        # 情感染色：如果提供了情绪状态，生成描述文本（Agent 能"看到"自己现在的情绪底色）
        if emotion_state:
            p = emotion_state.get("pleasure", 0.0)
            a = emotion_state.get("arousal", 0.0)
            d = emotion_state.get("dominance", 0.0)
            result["emotion_coloring"] = self._describe_emotion_coloring(p, a, d)

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
        # + 情感感知重排（情绪一致性记忆效应）
        # ============================================================
        retrieval_results["long_term"] = self._rerank_and_dedup(
            query, retrieval_results.get("long_term", []), emotion_state,
        )
        retrieval_results["experiences"] = self._rerank_and_dedup(
            query, retrieval_results.get("experiences", []), emotion_state,
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

        # 情感染色：放在最前面，因为这是"底色"——Agent 此刻回忆时的情绪基调
        if result.get("emotion_coloring"):
            summary_parts.append(result["emotion_coloring"])

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
        emotion_state: Optional[Dict[str, float]] = None,
    ) -> List[Any]:
        """
        轻量重排 + 去重（情感感知版）：
        1. 用 query 词重叠率对原始结果做二次评分重排
        2. 如果提供了 emotion_state，额外叠加情感一致性权重（情绪一致性记忆效应）
        3. 用文本相似度去重（高度相似的只保留一条）

        核心：悲伤时，带负面情绪的记忆权重提升；开心时，带正面情绪的记忆权重提升。
        这是人类认知的基本规律——心情决定你更容易想起什么。
        """
        if not items or len(items) <= 1:
            return items

        query_words = chinese_tokenize(query)
        if not query_words:
            return items

        # 1) 提取每条的文本 + 按词重叠率打分 + 情感一致性加成
        scored = []
        for i, item in enumerate(items):
            text = self._item_text(item)
            if not text:
                scored.append((0.0, i, item))
                continue
            text_words = chinese_tokenize(text)
            overlap = len(query_words & text_words)
            union = len(query_words | text_words) or 1
            base_score = overlap / union

            # 情感一致性加成（最多 ±0.3，不超过基础相关性的影响）
            emotion_bonus = 0.0
            if emotion_state:
                emotion_bonus = self._emotion_match_score(text, emotion_state)

            final_score = base_score + emotion_bonus
            scored.append((final_score, i, item))

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

    # ============== 情感感知辅助方法 ==============

    @staticmethod
    def _emotion_match_score(text: str, emotion_state: Dict[str, float]) -> float:
        """
        计算记忆文本与当前情绪状态的匹配度（情绪一致性记忆效应）。

        原理：
        - 当前愉悦度高 → 正面词汇的记忆权重提升
        - 当前愉悦度低 → 负面词汇的记忆权重提升
        - 当前唤醒度高 → 激烈情绪词汇的记忆权重提升
        - 当前支配度低 → 悲伤、无力感相关词汇的记忆权重提升

        返回值：-0.3 到 +0.3 之间的加成（不超过基础相关性的影响）
        """
        text_lower = text.lower()

        # 基础情感词库（中英文混合，因为用户可能混用）
        positive_words = [
            "开心", "快乐", "高兴", "欣慰", "满足", "兴奋", "惊喜", "喜欢", "爱",
            "好", "棒", "赞", "成功", "顺利", "美好", "温暖", "希望", "感谢",
            "happy", "glad", "joy", "love", "great", "good", "success", "wonderful",
        ]
        negative_words = [
            "难过", "伤心", "悲伤", "失望", "愤怒", "焦虑", "恐惧", "累", "疲惫",
            "不好", "糟糕", "失败", "痛苦", "孤独", "绝望", "想哭", "压力", "烦",
            "sad", "angry", "tired", "fail", "bad", "terrible", "pain", "lonely",
        ]
        high_arousal_words = [
            "激动", "愤怒", "兴奋", "紧张", "焦虑", "恐慌", "爆发", "激烈",
            "excited", "angry", "nervous", "panic", "intense",
        ]
        low_dominance_words = [
            "无助", "无力", "迷茫", "困惑", "绝望", "被动", "顺从", "压抑",
            "helpless", "confused", "hopeless", "passive",
        ]

        p = emotion_state.get("pleasure", 0.0)
        a = emotion_state.get("arousal", 0.0)
        d = emotion_state.get("dominance", 0.0)

        bonus = 0.0

        # 愉悦度匹配：开心时正面记忆权重↑，悲伤时负面记忆权重↑
        pos_count = sum(1 for w in positive_words if w in text_lower)
        neg_count = sum(1 for w in negative_words if w in text_lower)
        if p > 0.1:
            bonus += pos_count * 0.05 * abs(p)
            bonus -= neg_count * 0.03 * abs(p)
        elif p < -0.1:
            bonus += neg_count * 0.06 * abs(p)
            bonus -= pos_count * 0.03 * abs(p)

        # 唤醒度匹配：激动时激烈情绪记忆权重↑
        arousal_count = sum(1 for w in high_arousal_words if w in text_lower)
        if a > 0.2:
            bonus += arousal_count * 0.05 * a

        # 支配度匹配：低支配时无力感记忆权重↑
        low_dom_count = sum(1 for w in low_dominance_words if w in text_lower)
        if d < -0.1:
            bonus += low_dom_count * 0.05 * abs(d)

        # 限制在 [-0.3, +0.3] 范围内，避免情感压过相关性
        return max(-0.3, min(0.3, bonus))

    @staticmethod
    def _describe_emotion_coloring(pleasure: float, arousal: float, dominance: float) -> str:
        """
        生成情感染色的自然语言描述——不是指令，而是"底色"的描述。

        Agent 读到这段文字时，会感受到"我现在回忆时带着这样的情绪滤镜"，
        而不是被命令"你应该用XX语气说话"。

        关键：用第一人称、描述性语言，像在说自己此刻的心境。
        """
        # 愉悦度描述
        if pleasure > 0.4:
            p_desc = "心情不错，想起的事情都带着一点暖意"
        elif pleasure > 0.15:
            p_desc = "心情还可以，偏积极"
        elif pleasure > -0.15:
            p_desc = "心情比较平静"
        elif pleasure > -0.4:
            p_desc = "心情有点低落，想起的事情可能偏伤感"
        else:
            p_desc = "心情很差，心里沉甸甸的，回忆也带着灰色"

        # 唤醒度描述
        if arousal > 0.4:
            a_desc = "心里有点不平静，思绪比较活跃"
        elif arousal > 0.15:
            a_desc = "精神还可以，注意力比较集中"
        elif arousal > -0.15:
            a_desc = "精神状态比较平稳"
        else:
            a_desc = "有点提不起精神，反应可能慢一些"

        # 支配度描述
        if dominance > 0.3:
            d_desc = "感觉比较有掌控感"
        elif dominance > -0.2:
            d_desc = "对事情的掌控感一般"
        else:
            d_desc = "感觉有点被动，不太能掌控局面"

        return (
            "## 此刻的心境\n"
            f"（我现在是带着这样的心情在回忆：{p_desc}，{a_desc}，{d_desc}。\n"
            "这不是任务要求，只是我此刻真实的状态。）"
        )
