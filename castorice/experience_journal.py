"""
经历流模块 (Experience Journal)

参考论文：
- Generative Agents: Interactive Simulacra of Human Behavior (Stanford, 2023)
- Memory Streams: 每条记忆有自然语言描述 + 时间戳 + 重要性评分 + 类型

设计原则：
- 经历是 Agent 自我进化的素材
- 所有重要交互都记录，Agent 在反思时从经历中提取模式
- 不预设性格，性格从经历中涌现

记忆类型（参考人类心智）：
- episodic: 情景记忆（具体交互：用户问了什么，我答了什么，结果如何）
- emotional: 情感事件（强烈的情感冲击，影响长期性格）
- reflective: 反思记忆（Agent 自己总结的规律）
- skill: 技能习得（成功完成某类任务后形成的程序性记忆）

数据结构：
    Experience(
        id=str,                      # UUID
        timestamp=str,               # ISO8601
        memory_type=str,             # episodic/emotional/reflective/skill
        content=str,                 # 自然语言描述
        importance=float,            # 0-10 重要性评分
        emotional_valence=float,     # -1.0 到 1.0 情感效价（负=消极/正=积极）
        session_id=str,              # 会话 ID
        metadata=dict,               # 结构化字段（用户意图、工具调用、置信度等）
    )

存储：SQLite + WAL 模式，支持高并发写入
检索：支持按时间/重要性/类型/相似度过滤
"""

import json
import logging
import os
import sqlite3
import threading
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("Castorice.ExperienceJournal")


@dataclass
class Experience:
    """单条经历记录"""
    id: str = ""
    timestamp: str = ""
    memory_type: str = "episodic"  # episodic / emotional / reflective / skill
    content: str = ""              # 自然语言描述（Agent 自己读）
    importance: float = 5.0        # 0-10 重要性
    emotional_valence: float = 0.0  # -1.0(消极) ~ 1.0(积极)
    session_id: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.id:
            self.id = str(uuid.uuid4())
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Experience":
        return cls(
            id=row["id"],
            timestamp=row["timestamp"],
            memory_type=row["memory_type"],
            content=row["content"],
            importance=float(row["importance"]),
            emotional_valence=float(row["emotional_valence"]),
            session_id=row["session_id"] or "",
            metadata=json.loads(row["metadata"] or "{}"),
        )


class ExperienceJournal:
    """
    经历流存储

    - SQLite WAL 模式，线程安全（thread-local 连接）
    - 支持按时间/重要性/类型/会话检索
    - LRU 淘汰：超过 max_experiences 时删除最旧且最不重要的
    - 重要性评分由 Agent 自己在记录时给出（让 Agent 判断什么重要）
    """

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS experiences (
        id TEXT PRIMARY KEY,
        timestamp TEXT NOT NULL,
        memory_type TEXT NOT NULL,
        content TEXT NOT NULL,
        importance REAL NOT NULL,
        emotional_valence REAL NOT NULL,
        session_id TEXT,
        metadata TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_timestamp ON experiences(timestamp);
    CREATE INDEX IF NOT EXISTS idx_importance ON experiences(importance DESC);
    CREATE INDEX IF NOT EXISTS idx_type ON experiences(memory_type);
    CREATE INDEX IF NOT EXISTS idx_session ON experiences(session_id);
    CREATE INDEX IF NOT EXISTS idx_type_time ON experiences(memory_type, timestamp);
    """

    def __init__(
        self,
        db_path: str = "./castorice_data/experiences.db",
        max_experiences: int = 10000,
    ):
        self.db_path = db_path
        self.max_experiences = max_experiences
        self._lock = threading.Lock()
        self._local = threading.local()
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        """thread-local SQLite 连接（WAL 模式）"""
        if not hasattr(self._local, "conn"):
            conn = sqlite3.connect(self.db_path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            # WAL 模式：高并发读写不阻塞
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA foreign_keys=ON")
            self._local.conn = conn
        return self._local.conn

    def _init_db(self) -> None:
        with self._lock:
            conn = self._get_conn()
            conn.executescript(self.SCHEMA)
            conn.commit()

    def close(self) -> None:
        """关闭当前线程的连接（便于测试清理；正常运行不需要调用）"""
        with self._lock:
            conn = getattr(self._local, "conn", None)
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass
                self._local.conn = None

    def add(self, experience: Experience) -> str:
        """添加一条经历"""
        with self._lock:
            conn = self._get_conn()
            conn.execute(
                """INSERT OR REPLACE INTO experiences
                   (id, timestamp, memory_type, content, importance,
                    emotional_valence, session_id, metadata)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    experience.id,
                    experience.timestamp,
                    experience.memory_type,
                    experience.content,
                    experience.importance,
                    experience.emotional_valence,
                    experience.session_id,
                    json.dumps(experience.metadata, ensure_ascii=False),
                ),
            )
            conn.commit()
            # LRU 淘汰（在锁内执行，避免并发写冲突）
            self._evict_if_needed()
        logger.debug(
            f"经历已记录: type={experience.memory_type}, importance={experience.importance:.1f}, "
            f"valence={experience.emotional_valence:+.2f}"
        )
        return experience.id

    def add_simple(
        self,
        content: str,
        memory_type: str = "episodic",
        importance: float = 5.0,
        emotional_valence: float = 0.0,
        session_id: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """便捷添加方法"""
        exp = Experience(
            content=content,
            memory_type=memory_type,
            importance=importance,
            emotional_valence=emotional_valence,
            session_id=session_id,
            metadata=metadata or {},
        )
        return self.add(exp)

    def _evict_if_needed(self) -> None:
        """LRU 淘汰：超出上限时删除最旧且最不重要的"""
        # 注意：此方法在 add() 的锁内调用，不需要额外加锁
        conn = self._get_conn()
        count = conn.execute("SELECT COUNT(*) FROM experiences").fetchone()[0]
        if count <= self.max_experiences:
            return
        # 删除最旧且最不重要的（importance ASC, timestamp ASC）
        to_delete = count - self.max_experiences
        conn.execute(
            """DELETE FROM experiences WHERE id IN (
                   SELECT id FROM experiences
                   ORDER BY importance ASC, timestamp ASC
                   LIMIT ?
               )""",
            (to_delete,),
        )
        conn.commit()
        logger.info(f"经历流 LRU 淘汰: {to_delete} 条")

    def get_recent(self, limit: int = 20, memory_type: Optional[str] = None) -> List[Experience]:
        """获取最近的经历（按时间倒序）"""
        with self._lock:
            conn = self._get_conn()
            if memory_type:
                rows = conn.execute(
                    """SELECT * FROM experiences
                       WHERE memory_type = ?
                       ORDER BY timestamp DESC LIMIT ?""",
                    (memory_type, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """SELECT * FROM experiences
                       ORDER BY timestamp DESC LIMIT ?""",
                    (limit,),
                ).fetchall()
        return [Experience.from_row(r) for r in rows]

    def get_important(self, limit: int = 20, memory_type: Optional[str] = None) -> List[Experience]:
        """获取最重要的经历（按重要性倒序）"""
        with self._lock:
            conn = self._get_conn()
            if memory_type:
                rows = conn.execute(
                    """SELECT * FROM experiences
                       WHERE memory_type = ?
                       ORDER BY importance DESC, timestamp DESC LIMIT ?""",
                    (memory_type, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """SELECT * FROM experiences
                       ORDER BY importance DESC, timestamp DESC LIMIT ?""",
                    (limit,),
                ).fetchall()
        return [Experience.from_row(r) for r in rows]

    def get_by_session(self, session_id: str, limit: int = 50) -> List[Experience]:
        """获取指定会话的经历"""
        with self._lock:
            conn = self._get_conn()
            rows = conn.execute(
                """SELECT * FROM experiences
                   WHERE session_id = ?
                   ORDER BY timestamp ASC LIMIT ?""",
                (session_id, limit),
            ).fetchall()
        return [Experience.from_row(r) for r in rows]

    def get_since(self, since: datetime, limit: int = 100) -> List[Experience]:
        """获取指定时间后的经历（用于反思：'最近 24 小时发生了什么'）"""
        since_iso = since.astimezone(timezone.utc).isoformat()
        with self._lock:
            conn = self._get_conn()
            rows = conn.execute(
                """SELECT * FROM experiences
                   WHERE timestamp >= ?
                   ORDER BY timestamp ASC LIMIT ?""",
                (since_iso, limit),
            ).fetchall()
        return [Experience.from_row(r) for r in rows]

    def search_by_content(self, query: str, limit: int = 10) -> List[Experience]:
        """简单 LIKE 检索（向量检索走 ChromaDB，这里只做兜底）"""
        escaped_query = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        with self._lock:
            conn = self._get_conn()
            rows = conn.execute(
                """SELECT * FROM experiences
                   WHERE content LIKE ? ESCAPE '\\'
                   ORDER BY importance DESC, timestamp DESC LIMIT ?""",
                (f"%{escaped_query}%", limit),
            ).fetchall()
        return [Experience.from_row(r) for r in rows]

    def count(self, memory_type: Optional[str] = None) -> int:
        """获取经历总数"""
        with self._lock:
            conn = self._get_conn()
            if memory_type:
                row = conn.execute(
                    "SELECT COUNT(*) FROM experiences WHERE memory_type = ?",
                    (memory_type,),
                ).fetchone()
            else:
                row = conn.execute("SELECT COUNT(*) FROM experiences").fetchone()
        return int(row[0])

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        with self._lock:
            conn = self._get_conn()
            total = conn.execute("SELECT COUNT(*) FROM experiences").fetchone()[0]
            by_type = conn.execute(
                """SELECT memory_type, COUNT(*) as cnt, AVG(importance) as avg_imp,
                          AVG(emotional_valence) as avg_val
                   FROM experiences GROUP BY memory_type"""
            ).fetchall()
        return {
            "total": total,
            "by_type": {
                r["memory_type"]: {
                    "count": r["cnt"],
                    "avg_importance": round(r["avg_imp"] or 0, 2),
                    "avg_valence": round(r["avg_val"] or 0, 2),
                }
                for r in by_type
            },
        }


# 全局单例
_global_journal: Optional[ExperienceJournal] = None
_global_journal_lock = threading.Lock()


def get_experience_journal(db_path: str = None) -> ExperienceJournal:
    """获取全局经历流单例"""
    global _global_journal
    if _global_journal is None:
        with _global_journal_lock:
            if _global_journal is None:
                if db_path is None:
                    db_path = os.path.join(
                        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "castorice_data", "experiences.db"
                    )
                _global_journal = ExperienceJournal(db_path=db_path)
    return _global_journal
