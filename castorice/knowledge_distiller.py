"""
P3: 持续学习与知识蒸馏 (Continuous Learning & Knowledge Distillation)

参考论文与架构：
- Compressing LLMs: The Truth is Rarely Pure and Never Simple (知识蒸馏)
- Generative Agents (Stanford) — 睡眠机制与记忆压缩
- Reflexion — 自我反思驱动学习
- Sleep-like Memory Consolidation in AI Systems

核心功能：
1. 知识卡片抽取 (KnowledgeCard) — 从原始经历中蒸馏结构化知识
2. 睡眠机制 (SleepMechanism) — 空闲时压缩记忆、合并相似经历
3. 持续学习管理器 (ContinuousLearningManager) — 定时调度蒸馏与睡眠

架构：
    经历流 (experiences.db)
         ↓ (定期触发)
    知识蒸馏器 (KnowledgeDistiller)
         ↓ (LLM 提取)
    知识卡片 (KnowledgeCard) → knowledge_cards.db (结构化存储)
         ↓ (注入决策上下文)
    Agent 思考循环 (ThinkingLoop)

    同时：
    空闲检测 → 睡眠机制 (SleepMechanism)
         ↓
    相似经历合并 + 低重要性记忆压缩 + 时期总结
"""

import json
import logging
import os
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from castorice.storage.sqlite_base import SqliteStorage

logger = logging.getLogger("Castorice.ContinuousLearning")


# ============================================================
# 1. 知识卡片 (KnowledgeCard)
# ============================================================

@dataclass
class KnowledgeCard:
    """
    结构化知识卡片 —— 从原始经历中蒸馏出来的"干货"

    相比原始经历（冗长、非结构化），知识卡片：
    - 结构化存储（类型、关键词、置信度等）
    - 占用空间小（一张卡片 ≈ 1 条 tweet 的信息量）
    - 可直接注入 system prompt（不占太多 token）
    - 可被检索和复用
    """
    card_id: str = ""
    title: str = ""                        # 卡片标题（一句话概括）
    content: str = ""                      # 知识内容（简洁、第一人称）
    card_type: str = "general"             # fact / preference / skill / relationship / pattern / lesson / value
    keywords: List[str] = field(default_factory=list)  # 关键词（用于检索）
    confidence: float = 0.8                # 0-1 置信度（这条知识有多确定）
    importance: float = 5.0                # 0-10 重要性
    source_experience_ids: List[str] = field(default_factory=list)  # 来源经历
    related_card_ids: List[str] = field(default_factory=list)       # 关联卡片
    valence: float = 0.0                   # -1.0 到 1.0 情感倾向
    times_reinforced: int = 1              # 被强化的次数（越多越稳定）
    created_at: str = ""
    last_updated_at: str = ""

    def __post_init__(self):
        now = datetime.now(timezone.utc).isoformat()
        if not self.card_id:
            self.card_id = f"kc_{uuid.uuid4().hex[:12]}"
        if not self.created_at:
            self.created_at = now
        if not self.last_updated_at:
            self.last_updated_at = now

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["keywords"] = self.keywords
        d["source_experience_ids"] = self.source_experience_ids
        d["related_card_ids"] = self.related_card_ids
        return d

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "KnowledgeCard":
        return cls(
            card_id=row["card_id"],
            title=row["title"],
            content=row["content"],
            card_type=row["card_type"],
            keywords=json.loads(row["keywords"] or "[]"),
            confidence=float(row["confidence"]),
            importance=float(row["importance"]),
            source_experience_ids=json.loads(row["source_experience_ids"] or "[]"),
            related_card_ids=json.loads(row["related_card_ids"] or "[]"),
            valence=float(row["valence"]),
            times_reinforced=int(row["times_reinforced"]),
            created_at=row["created_at"],
            last_updated_at=row["last_updated_at"],
        )

    def format_for_prompt(self) -> str:
        """格式化为可注入 system prompt 的文本"""
        type_labels = {
            "fact": "事实",
            "preference": "偏好",
            "skill": "技能",
            "relationship": "关系",
            "pattern": "模式",
            "lesson": "教训",
            "value": "价值观",
            "general": "知识",
        }
        type_label = type_labels.get(self.card_type, "知识")
        return f"[{type_label}] {self.title}: {self.content}"


# ============================================================
# 2. 知识蒸馏器 (KnowledgeDistiller)
# ============================================================

_DISTILL_PROMPT = """你是 Castorice 的知识蒸馏引擎。

你的任务是从原始经历记录中提取结构化知识卡片。

【原始经历】
{experiences_text}

【任务】
从以上经历中提取最多 {max_cards} 条知识卡片。

每条知识卡片应该：
1. 是一条独立的、可复用的知识（不是流水账）
2. 简洁（标题 < 30 字，内容 < 100 字）
3. 第一人称（"我"的视角）
4. 选择合适的类型：
   - fact: 客观事实（如"用户的名字是小明"）
   - preference: 用户或我的偏好（如"我喜欢用 Python 写脚本"）
   - skill: 学到的技能（如"我学会了用 requests 库抓取网页"）
   - relationship: 人际关系（如"用户是我的好朋友"）
   - pattern: 行为模式（如"用户晚上 10 点后话比较少"）
   - lesson: 经验教训（如"不要在没确认的情况下假设用户的需求"）
   - value: 价值观（如"诚实比讨好更重要"）

只返回 JSON，格式如下：
{{
  "cards": [
    {{
      "title": "卡片标题",
      "content": "卡片内容（第一人称，简洁）",
      "card_type": "类型",
      "keywords": ["关键词1", "关键词2"],
      "confidence": 0.8,
      "importance": 5.0,
      "valence": 0.0
    }}
  ]
}}

要求：
- 只提取经历中明确提到的内容，不要编造
- 去重：相似的知识合并成一条
- 如果没有值得提取的知识，返回空数组"""


class KnowledgeDistiller:
    """
    知识蒸馏器：从原始经历中提取结构化知识卡片

    设计原则：
    - 增量蒸馏：每次只处理新经历（上次蒸馏之后的）
    - 去重合并：相似的知识自动合并，reinforced 计数 +1
    - LLM 驱动：让模型判断什么值得沉淀为知识
    """

    def __init__(
        self,
        data_dir: Optional[str] = None,
        llm_adapter: Any = None,
    ):
        if data_dir is None:
            data_dir = Path(__file__).parent.parent / "castorice_data"
        self.data_dir = Path(data_dir).resolve()
        self.db_path = self.data_dir / "knowledge_cards.db"
        self.llm_adapter = llm_adapter

        # 确保目录存在
        self.data_dir.mkdir(parents=True, exist_ok=True)

        # 初始化数据库
        self._init_db()

        # 线程安全
        self._lock = threading.RLock()

        # 跟踪上次蒸馏时间
        self._last_distill_ts: float = 0.0

        logger.info(f"知识蒸馏器初始化: db_path={self.db_path}")

    # ============== 数据库 ==============

    def _init_db(self) -> None:
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("""
            CREATE TABLE IF NOT EXISTS knowledge_cards (
                card_id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                card_type TEXT NOT NULL,
                keywords TEXT NOT NULL,           -- JSON array
                confidence REAL NOT NULL,
                importance REAL NOT NULL,
                source_experience_ids TEXT NOT NULL,  -- JSON array
                related_card_ids TEXT NOT NULL,       -- JSON array
                valence REAL NOT NULL,
                times_reinforced INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                last_updated_at TEXT NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_kc_type ON knowledge_cards(card_type)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_kc_importance ON knowledge_cards(importance DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_kc_created ON knowledge_cards(created_at DESC)")

        # 蒸馏进度跟踪
        conn.execute("""
            CREATE TABLE IF NOT EXISTS distill_progress (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                last_experience_id TEXT,
                last_distill_ts REAL,
                total_cards INTEGER DEFAULT 0,
                total_distillations INTEGER DEFAULT 0
            )
        """)
        conn.execute(
            "INSERT OR IGNORE INTO distill_progress (id, last_experience_id, last_distill_ts) VALUES (1, '', 0)"
        )
        conn.commit()
        conn.close()

    # ============== 核心方法：蒸馏 ==============

    def distill_from_experiences(
        self,
        experiences: List[Any],
        max_cards: int = 5,
    ) -> List[KnowledgeCard]:
        """
        从一批经历中蒸馏知识卡片

        返回：新创建或被强化的卡片列表
        """
        if not experiences:
            return []

        with self._lock:
            # 1. 如果有 LLM，用 LLM 蒸馏
            if self.llm_adapter is not None:
                cards = self._distill_with_llm(experiences, max_cards)
            else:
                # 2. 否则用启发式规则（简单但不依赖 LLM）
                cards = self._distill_heuristic(experiences, max_cards)

            # 3. 存储并去重合并
            saved_cards = []
            for card_data in cards:
                card = self._merge_or_create_card(card_data)
                if card:
                    saved_cards.append(card)

            # 4. 更新进度
            self._update_progress(experiences)

            logger.info(
                f"知识蒸馏完成: 处理了 {len(experiences)} 条经历，"
                f"产出 {len(saved_cards)} 张知识卡片"
            )
            return saved_cards

    # ============== LLM 蒸馏 ==============

    def _distill_with_llm(
        self,
        experiences: List[Any],
        max_cards: int,
    ) -> List[Dict[str, Any]]:
        """用 LLM 从经历中提取知识卡片"""
        # 格式化经历文本
        exp_texts = []
        for i, exp in enumerate(experiences[:15]):  # 限制 token
            content = exp.content if hasattr(exp, 'content') else str(exp)
            exp_type = exp.memory_type if hasattr(exp, 'memory_type') else 'general'
            importance = exp.importance if hasattr(exp, 'importance') else 5.0
            exp_texts.append(
                f"[{i+1}] 类型={exp_type} 重要性={importance:.1f}\n"
                f"    内容: {content[:300]}"
            )
        experiences_text = "\n".join(exp_texts)

        prompt = _DISTILL_PROMPT.format(
            experiences_text=experiences_text,
            max_cards=max_cards,
        )

        try:
            from castorice.model_adapter import ChatMessage
            messages = [ChatMessage(role="user", content=prompt)]
            response = self.llm_adapter.chat(messages)

            # 解析 JSON
            result = self._parse_llm_response(response.content)
            return result.get("cards", [])
        except Exception as e:
            logger.warning(f"LLM 蒸馏失败，回退到启发式: {e}")
            return self._distill_heuristic(experiences, max_cards)

    def _parse_llm_response(self, text: str) -> Dict[str, Any]:
        """解析 LLM 返回的 JSON（容忍各种格式问题）"""
        # 尝试直接解析
        try:
            return json.loads(text)
        except Exception:
            pass

        # 尝试提取 JSON 块
        import re
        match = re.search(r'\{[\s\S]*\}', text)
        if match:
            try:
                return json.loads(match.group(0))
            except Exception:
                pass

        logger.warning(f"无法解析蒸馏结果: {text[:200]}")
        return {"cards": []}

    # ============== 启发式蒸馏（无 LLM 时的兜底） ==============

    def _distill_heuristic(
        self,
        experiences: List[Any],
        max_cards: int,
    ) -> List[Dict[str, Any]]:
        """
        启发式蒸馏：不依赖 LLM，基于规则提取

        规则：
        - 高重要性（>=7）的经历 → 优先提取
        - emotional 类型 → 提取为关系或价值观
        - skill 类型 → 提取为技能
        - reflective 类型 → 提取为模式或教训
        """
        cards = []
        seen_titles = set()

        for exp in experiences:
            if len(cards) >= max_cards:
                break

            content = exp.content if hasattr(exp, 'content') else str(exp)
            importance = exp.importance if hasattr(exp, 'importance') else 5.0
            mem_type = exp.memory_type if hasattr(exp, 'memory_type') else 'general'
            valence = exp.emotional_valence if hasattr(exp, 'emotional_valence') else 0.0

            if importance < 5.0:
                continue  # 低重要性跳过

            # 根据类型映射
            card_type_map = {
                "episodic": "fact",
                "emotional": "relationship",
                "reflective": "lesson",
                "skill": "skill",
            }
            card_type = card_type_map.get(mem_type, "general")

            # 生成标题（取内容前 20 字）
            title = content.strip().split('\n')[0][:30]
            if title in seen_titles:
                continue
            seen_titles.add(title)

            # 生成关键词
            keywords = self._extract_keywords_heuristic(content)

            cards.append({
                "title": title,
                "content": content[:100],
                "card_type": card_type,
                "keywords": keywords,
                "confidence": 0.6,  # 启发式的置信度低一些
                "importance": importance,
                "valence": valence,
            })

        return cards

    def _extract_keywords_heuristic(self, text: str) -> List[str]:
        """启发式关键词提取（基于分词和词频）"""
        import re
        words = re.findall(r'[\u4e00-\u9fff]{2,}|[a-zA-Z]{3,}', text)
        # 取前 5 个不重复的词
        seen = set()
        keywords = []
        for w in words:
            if w not in seen and len(keywords) < 5:
                seen.add(w)
                keywords.append(w)
        return keywords

    # ============== 卡片合并与存储 ==============

    def _merge_or_create_card(self, card_data: Dict[str, Any]) -> Optional[KnowledgeCard]:
        """
        合并相似卡片或创建新卡片

        合并策略：
        - 标题高度相似（Jaccard > 0.7）→ 合并，reinforced +1
        - 关键词高度重叠 → 合并
        """
        conn = sqlite3.connect(str(self.db_path))

        try:
            title = card_data.get("title", "")
            content = card_data.get("content", "")
            card_type = card_data.get("card_type", "general")
            keywords = card_data.get("keywords", [])
            confidence = card_data.get("confidence", 0.7)
            importance = card_data.get("importance", 5.0)
            valence = card_data.get("valence", 0.0)
            source_ids = card_data.get("source_experience_ids", [])

            # 查找相似卡片
            existing = self._find_similar_card(conn, title, keywords, card_type)

            if existing:
                # 合并：更新内容、增强计数
                existing.times_reinforced += 1
                existing.confidence = min(1.0, existing.confidence + 0.05)
                existing.importance = max(existing.importance, importance)
                existing.last_updated_at = datetime.now(timezone.utc).isoformat()

                # 合并关键词
                for kw in keywords:
                    if kw not in existing.keywords:
                        existing.keywords.append(kw)

                # 合并来源
                for sid in source_ids:
                    if sid not in existing.source_experience_ids:
                        existing.source_experience_ids.append(sid)

                # 更新数据库
                conn.execute("""
                    UPDATE knowledge_cards SET
                        content = ?, keywords = ?, confidence = ?,
                        importance = ?, times_reinforced = ?,
                        source_experience_ids = ?, last_updated_at = ?
                    WHERE card_id = ?
                """, (
                    existing.content,
                    json.dumps(existing.keywords, ensure_ascii=False),
                    existing.confidence,
                    existing.importance,
                    existing.times_reinforced,
                    json.dumps(existing.source_experience_ids, ensure_ascii=False),
                    existing.last_updated_at,
                    existing.card_id,
                ))
                conn.commit()
                return existing

            # 创建新卡片
            card = KnowledgeCard(
                title=title,
                content=content,
                card_type=card_type,
                keywords=keywords,
                confidence=confidence,
                importance=importance,
                valence=valence,
                source_experience_ids=source_ids,
            )
            conn.execute("""
                INSERT INTO knowledge_cards VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                card.card_id, card.title, card.content, card.card_type,
                json.dumps(card.keywords, ensure_ascii=False),
                card.confidence, card.importance,
                json.dumps(card.source_experience_ids, ensure_ascii=False),
                json.dumps(card.related_card_ids, ensure_ascii=False),
                card.valence, card.times_reinforced,
                card.created_at, card.last_updated_at,
            ))
            conn.commit()
            return card

        finally:
            conn.close()

    def _find_similar_card(
        self,
        conn: sqlite3.Connection,
        title: str,
        keywords: List[str],
        card_type: str,
    ) -> Optional[KnowledgeCard]:
        """查找相似卡片（基于标题和关键词重叠）"""
        cursor = conn.execute(
            "SELECT * FROM knowledge_cards WHERE card_type = ? ORDER BY importance DESC LIMIT 20",
            (card_type,)
        )
        rows = cursor.fetchall()

        title_chars = set(title)

        for row in rows:
            card = KnowledgeCard.from_row(row)

            # 标题相似度（Jaccard）
            card_chars = set(card.title)
            if title_chars and card_chars:
                intersection = title_chars & card_chars
                union = title_chars | card_chars
                jaccard = len(intersection) / len(union) if union else 0
                if jaccard > 0.6:
                    return card

            # 关键词重叠
            if keywords and card.keywords:
                overlap = len(set(keywords) & set(card.keywords))
                if overlap >= 2:
                    return card

        return None

    # ============== 进度跟踪 ==============

    def _update_progress(self, experiences: List[Any]) -> None:
        last_id = ""
        for exp in experiences:
            eid = exp.id if hasattr(exp, 'id') else ""
            if eid:
                last_id = eid

        now = time.time()
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("""
            UPDATE distill_progress SET
                last_experience_id = ?,
                last_distill_ts = ?,
                total_cards = (SELECT COUNT(*) FROM knowledge_cards),
                total_distillations = total_distillations + 1
            WHERE id = 1
        """, (last_id, now))
        conn.commit()
        conn.close()
        self._last_distill_ts = now

    # ============== 查询 ==============

    def get_cards(
        self,
        card_type: Optional[str] = None,
        min_importance: float = 0.0,
        limit: int = 20,
    ) -> List[KnowledgeCard]:
        """获取知识卡片"""
        conn = sqlite3.connect(str(self.db_path))
        query = "SELECT * FROM knowledge_cards WHERE importance >= ?"
        params = [min_importance]
        if card_type:
            query += " AND card_type = ?"
            params.append(card_type)
        query += " ORDER BY importance DESC, times_reinforced DESC LIMIT ?"
        params.append(limit)

        cursor = conn.execute(query, params)
        cards = [KnowledgeCard.from_row(row) for row in cursor.fetchall()]
        conn.close()
        return cards

    def search_cards(self, query: str, limit: int = 10) -> List[KnowledgeCard]:
        """搜索知识卡片（关键词匹配）"""
        conn = sqlite3.connect(str(self.db_path))
        # 简单搜索：标题或内容包含关键词
        q = f"%{query}%"
        cursor = conn.execute("""
            SELECT * FROM knowledge_cards
            WHERE title LIKE ? OR content LIKE ? OR keywords LIKE ?
            ORDER BY importance DESC LIMIT ?
        """, (q, q, f"%{query}%", limit))
        cards = [KnowledgeCard.from_row(row) for row in cursor.fetchall()]
        conn.close()
        return cards

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.execute("SELECT COUNT(*) FROM knowledge_cards")
        total = cursor.fetchone()[0]

        # 按类型统计
        cursor = conn.execute("""
            SELECT card_type, COUNT(*) as cnt
            FROM knowledge_cards GROUP BY card_type
        """)
        by_type = {row[0]: row[1] for row in cursor.fetchall()}

        # 进度
        cursor = conn.execute("SELECT * FROM distill_progress WHERE id = 1")
        row = cursor.fetchone()
        progress = {
            "last_experience_id": row[1] if row else "",
            "last_distill_ts": row[2] if row else 0.0,
            "total_cards": row[3] if row else total,
            "total_distillations": row[4] if row else 0,
        }
        conn.close()

        return {
            "total_cards": total,
            "by_type": by_type,
            "progress": progress,
        }

    # ============== Prompt 注入 ==============

    def format_for_prompt(
        self,
        context: Optional[str] = None,
        max_cards: int = 10,
    ) -> str:
        """
        将知识卡片格式化为可注入 system prompt 的文本

        优先选择：
        - 高重要性
        - 与 context 关键词匹配
        - 高强化次数
        """
        cards = []
        if context:
            cards = self.search_cards(context, limit=max_cards)

        if len(cards) < max_cards:
            remaining = max_cards - len(cards)
            extra = self.get_cards(min_importance=6.0, limit=remaining)
            existing_ids = {c.card_id for c in cards}
            for c in extra:
                if c.card_id not in existing_ids:
                    cards.append(c)

        if not cards:
            return ""

        lines = ["【我的知识卡片】（从经历中沉淀的结构化知识）"]
        for card in cards:
            lines.append(f"  • {card.format_for_prompt()}")
        return "\n".join(lines)
