"""
LocalSqlitePersonastore - 本地 SQLite + 文件系统后端

与现有行为100%一致的 Personastore 实现：
- 经历流：SQLite (experiences.db) - 与 ExperienceJournal 完全一致
- 自我概念：文件系统 (self_concept.md + core_self.md) - 与 SelfConcept 完全一致
- 情感状态：文件系统 (emotion_state.json) - 与 EmotionEngine 完全一致
- 价值观：SQLite (values.db) - 与 ValueSystem 完全一致

这是默认后端，确保零侵入性——不改变任何现有行为。
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from castorice.storage.personastore import (
    DataDomain,
    Personastore,
    StoredEmotionState,
    StoredExperience,
    StoredSelfConcept,
    StoredValueState,
    StoredValues,
)
from castorice.storage.sqlite_base import SqliteStorage

logger = logging.getLogger("Castorice.Personastore.Local")


class _ExperienceSqliteBackend(SqliteStorage):
    """经历流 SQLite 后端（与 ExperienceJournal 行为100%一致）"""

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

    def __init__(self, db_path: str, max_experiences: int = 10000):
        super().__init__(db_path)
        self.max_experiences = max_experiences
        self._lock = threading.Lock()
        self._init_db()

    def _init_db(self) -> None:
        with self._lock:
            conn = self._get_conn()
            conn.executescript(self.SCHEMA)
            conn.commit()

    def _get_conn(self) -> sqlite3.Connection:
        conn = super()._get_conn()
        if conn.row_factory is None:
            conn.row_factory = sqlite3.Row
        return conn


class _ValuesSqliteBackend(SqliteStorage):
    """价值观 SQLite 后端（与 ValueSystem 行为100%一致）"""

    def __init__(self, db_path: str):
        super().__init__(db_path)
        self._lock = threading.RLock()
        self._init_db()

    def _init_db(self) -> None:
        conn = self._get_conn()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS value_states (
                dimension_id TEXT PRIMARY KEY,
                data_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS value_conflicts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                data_json TEXT NOT NULL
            );
        """)
        conn.commit()


class LocalSqlitePersonastore(Personastore):
    """
    本地 SQLite + 文件系统 Personastore 后端。

    与现有实现100%行为兼容：
    - experiences: ./castorice_data/experiences.db (SQLite)
    - self_concept: ./castorice_data/self_concept.md + core_self.md (文件)
    - emotion_state: ./castorice_data/emotion_state.json (文件)
    - values: ./castorice_data/values.db (SQLite)
    """

    def __init__(
        self,
        data_dir: str = "./castorice_data",
        max_experiences: int = 10000,
    ):
        super().__init__()
        self.data_dir = data_dir
        os.makedirs(data_dir, exist_ok=True)

        # 经历流 SQLite 后端
        exp_db = os.path.join(data_dir, "experiences.db")
        self._exp_backend = _ExperienceSqliteBackend(exp_db, max_experiences)

        # 价值观 SQLite 后端
        values_db = os.path.join(data_dir, "values.db")
        self._values_backend = _ValuesSqliteBackend(values_db)

        # 文件路径
        self._self_concept_path = os.path.join(data_dir, "self_concept.md")
        self._core_self_path = os.path.join(data_dir, "core_self.md")
        self._narrative_events_path = os.path.join(data_dir, "self_concept.md.events.json")
        self._emotion_state_path = os.path.join(data_dir, "emotion_state.json")

        self._lock = threading.RLock()
        logger.info(f"LocalSqlitePersonastore 初始化完成，数据目录: {data_dir}")

    # ============================================================
    # 经历流 (Experiences)
    # ============================================================

    def add_experience(self, exp: StoredExperience, actor_id: str = "owner") -> str:
        if not self._check_write(DataDomain.EXPERIENCES, actor_id):
            return ""
        with self._exp_backend._lock:
            conn = self._exp_backend._get_conn()
            conn.execute(
                """INSERT OR REPLACE INTO experiences
                   (id, timestamp, memory_type, content, importance,
                    emotional_valence, session_id, metadata)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    exp.id,
                    exp.timestamp,
                    exp.memory_type,
                    exp.content,
                    exp.importance,
                    exp.emotional_valence,
                    exp.session_id,
                    json.dumps(exp.metadata, ensure_ascii=False),
                ),
            )
            conn.commit()
            self._evict_if_needed()
        logger.debug(
            f"经历已记录: type={exp.memory_type}, importance={exp.importance:.1f}"
        )
        return exp.id

    def _evict_if_needed(self) -> None:
        conn = self._exp_backend._get_conn()
        count = conn.execute("SELECT COUNT(*) FROM experiences").fetchone()[0]
        if count <= self._exp_backend.max_experiences:
            return
        to_delete = count - self._exp_backend.max_experiences
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

    def _row_to_exp(self, row: sqlite3.Row) -> StoredExperience:
        return StoredExperience(
            id=row["id"],
            timestamp=row["timestamp"],
            memory_type=row["memory_type"],
            content=row["content"],
            importance=float(row["importance"]),
            emotional_valence=float(row["emotional_valence"]),
            session_id=row["session_id"] or "",
            metadata=json.loads(row["metadata"] or "{}"),
        )

    def get_recent_experiences(
        self, limit: int = 20, memory_type: Optional[str] = None, actor_id: str = "owner"
    ) -> List[StoredExperience]:
        if not self._check_read(DataDomain.EXPERIENCES, actor_id):
            return []
        with self._exp_backend._lock:
            conn = self._exp_backend._get_conn()
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
        return [self._row_to_exp(r) for r in rows]

    def get_important_experiences(
        self, limit: int = 20, memory_type: Optional[str] = None, actor_id: str = "owner"
    ) -> List[StoredExperience]:
        if not self._check_read(DataDomain.EXPERIENCES, actor_id):
            return []
        with self._exp_backend._lock:
            conn = self._exp_backend._get_conn()
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
        return [self._row_to_exp(r) for r in rows]

    def get_experiences_by_session(
        self, session_id: str, limit: int = 50, actor_id: str = "owner"
    ) -> List[StoredExperience]:
        if not self._check_read(DataDomain.EXPERIENCES, actor_id):
            return []
        with self._exp_backend._lock:
            conn = self._exp_backend._get_conn()
            rows = conn.execute(
                """SELECT * FROM experiences
                   WHERE session_id = ?
                   ORDER BY timestamp ASC LIMIT ?""",
                (session_id, limit),
            ).fetchall()
        return [self._row_to_exp(r) for r in rows]

    def get_experiences_since(
        self, since: datetime, limit: int = 100, actor_id: str = "owner"
    ) -> List[StoredExperience]:
        if not self._check_read(DataDomain.EXPERIENCES, actor_id):
            return []
        since_iso = since.astimezone(timezone.utc).isoformat()
        with self._exp_backend._lock:
            conn = self._exp_backend._get_conn()
            rows = conn.execute(
                """SELECT * FROM experiences
                   WHERE timestamp >= ?
                   ORDER BY timestamp ASC LIMIT ?""",
                (since_iso, limit),
            ).fetchall()
        return [self._row_to_exp(r) for r in rows]

    def search_experiences(
        self, query: str, top_k: int = 10, min_importance: float = 0.0, actor_id: str = "owner"
    ) -> List[StoredExperience]:
        if not self._check_read(DataDomain.EXPERIENCES, actor_id):
            return []
        escaped_query = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        with self._exp_backend._lock:
            conn = self._exp_backend._get_conn()
            rows = conn.execute(
                """SELECT * FROM experiences
                   WHERE content LIKE ? ESCAPE '\\' AND importance >= ?
                   ORDER BY importance DESC, timestamp DESC LIMIT ?""",
                (f"%{escaped_query}%", min_importance, top_k),
            ).fetchall()
        return [self._row_to_exp(r) for r in rows]

    def count_experiences(self, memory_type: Optional[str] = None, actor_id: str = "owner") -> int:
        if not self._check_read(DataDomain.EXPERIENCES, actor_id):
            return 0
        with self._exp_backend._lock:
            conn = self._exp_backend._get_conn()
            if memory_type:
                row = conn.execute(
                    "SELECT COUNT(*) FROM experiences WHERE memory_type = ?",
                    (memory_type,),
                ).fetchone()
            else:
                row = conn.execute("SELECT COUNT(*) FROM experiences").fetchone()
        return int(row[0])

    def get_experience_stats(self, actor_id: str = "owner") -> Dict[str, Any]:
        if not self._check_read(DataDomain.EXPERIENCES, actor_id):
            return {}
        with self._exp_backend._lock:
            conn = self._exp_backend._get_conn()
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

    # ============================================================
    # 自我概念 (Self-Concept)
    # ============================================================

    def read_self_concept(self, actor_id: str = "owner") -> StoredSelfConcept:
        if not self._check_read(DataDomain.SELF_CONCEPT, actor_id):
            return StoredSelfConcept()

        with self._lock:
            # 读取叙事自我
            narrative_self = ""
            if os.path.exists(self._self_concept_path):
                try:
                    with open(self._self_concept_path, "r", encoding="utf-8") as f:
                        narrative_self = f.read()
                except Exception as e:
                    logger.warning(f"读取叙事自我失败: {e}")

            # 读取核心自我
            core_self = ""
            if os.path.exists(self._core_self_path):
                try:
                    with open(self._core_self_path, "r", encoding="utf-8") as f:
                        core_self = f.read()
                except Exception as e:
                    logger.warning(f"读取核心自我失败: {e}")

            # 读取叙事事件
            narrative_events = []
            if os.path.exists(self._narrative_events_path):
                try:
                    with open(self._narrative_events_path, "r", encoding="utf-8") as f:
                        narrative_events = json.load(f)
                except Exception as e:
                    logger.warning(f"读取叙事事件失败: {e}")

        return StoredSelfConcept(
            core_self=core_self,
            narrative_self=narrative_self,
            narrative_events=narrative_events,
        )

    def write_self_concept(self, data: StoredSelfConcept, actor_id: str = "owner") -> bool:
        if not self._check_write(DataDomain.SELF_CONCEPT, actor_id):
            return False

        with self._lock:
            try:
                # 写入叙事自我
                if data.narrative_self:
                    tmp_path = self._self_concept_path + ".tmp"
                    with open(tmp_path, "w", encoding="utf-8") as f:
                        f.write(data.narrative_self)
                    os.replace(tmp_path, self._self_concept_path)

                # 写入核心自我
                if data.core_self:
                    tmp_path = self._core_self_path + ".tmp"
                    with open(tmp_path, "w", encoding="utf-8") as f:
                        f.write(data.core_self)
                    os.replace(tmp_path, self._core_self_path)

                # 写入叙事事件
                if data.narrative_events:
                    tmp_path = self._narrative_events_path + ".tmp"
                    with open(tmp_path, "w", encoding="utf-8") as f:
                        json.dump(data.narrative_events, f, indent=2, ensure_ascii=False)
                    os.replace(tmp_path, self._narrative_events_path)

                return True
            except Exception as e:
                logger.warning(f"写入自我概念失败: {e}")
                return False

    # ============================================================
    # 情感状态 (Emotion State)
    # ============================================================

    def read_emotion_state(self, actor_id: str = "owner") -> StoredEmotionState:
        if not self._check_read(DataDomain.EMOTION_STATE, actor_id):
            return StoredEmotionState()

        if not os.path.exists(self._emotion_state_path):
            return StoredEmotionState()

        with self._lock:
            try:
                with open(self._emotion_state_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return StoredEmotionState(
                    pleasure=float(data.get("pleasure", 0.0)),
                    arousal=float(data.get("arousal", 0.0)),
                    dominance=float(data.get("dominance", 0.0)),
                    interaction_count=int(data.get("interaction_count", 0)),
                    last_update=data.get("last_update", ""),
                    emotional_history=data.get("emotional_history", []),
                    afterglow=data.get("afterglow", {}),
                    baseline=data.get("baseline", {}),
                )
            except Exception as e:
                logger.warning(f"读取情感状态失败: {e}")
                return StoredEmotionState()

    def write_emotion_state(self, data: StoredEmotionState, actor_id: str = "owner") -> bool:
        if not self._check_write(DataDomain.EMOTION_STATE, actor_id):
            return False

        with self._lock:
            try:
                from castorice.utils import atomic_json_dump
                state_dict = {
                    "pleasure": data.pleasure,
                    "arousal": data.arousal,
                    "dominance": data.dominance,
                    "interaction_count": data.interaction_count,
                    "last_update": data.last_update,
                    "emotional_history": data.emotional_history,
                    "afterglow": data.afterglow,
                    "baseline": data.baseline,
                }
                atomic_json_dump(state_dict, self._emotion_state_path, indent=2, ensure_ascii=False)
                return True
            except Exception as e:
                logger.warning(f"写入情感状态失败: {e}")
                return False

    # ============================================================
    # 价值观系统 (Values)
    # ============================================================

    def read_values(self, actor_id: str = "owner") -> StoredValues:
        if not self._check_read(DataDomain.VALUES, actor_id):
            return StoredValues()

        with self._values_backend._lock:
            conn = self._values_backend._get_conn()
            values: Dict[str, StoredValueState] = {}
            conflicts: List[Dict[str, Any]] = []

            try:
                rows = conn.execute("SELECT dimension_id, data_json FROM value_states").fetchall()
                for dimension_id, data_json in rows:
                    data = json.loads(data_json)
                    values[dimension_id] = StoredValueState(
                        dimension_id=data["dimension_id"],
                        strength=data.get("strength", 0.5),
                        trend=data.get("trend", 0.0),
                        history=data.get("history", []),
                    )
            except Exception as e:
                logger.warning(f"加载价值观状态失败: {e}")

            try:
                rows = conn.execute(
                    "SELECT data_json FROM value_conflicts ORDER BY id DESC LIMIT 20"
                ).fetchall()
                for (data_json,) in reversed(rows):
                    conflicts.append(json.loads(data_json))
            except Exception as e:
                logger.warning(f"加载价值观冲突失败: {e}")

        return StoredValues(values=values, conflicts=conflicts)

    def write_values(self, data: StoredValues, actor_id: str = "owner") -> bool:
        if not self._check_write(DataDomain.VALUES, actor_id):
            return False

        with self._values_backend._lock:
            conn = self._values_backend._get_conn()
            try:
                # 保存价值观状态
                for dimension_id, vs in data.values.items():
                    conn.execute(
                        "INSERT OR REPLACE INTO value_states (dimension_id, data_json) VALUES (?, ?)",
                        (dimension_id, json.dumps({
                            "dimension_id": vs.dimension_id,
                            "strength": vs.strength,
                            "trend": vs.trend,
                            "history": vs.history,
                        })),
                    )
                # 保存冲突（只保存最新的，避免重复）
                if data.conflicts:
                    # 清空旧的，重新写入
                    conn.execute("DELETE FROM value_conflicts")
                    for conflict in data.conflicts[-20:]:
                        conn.execute(
                            "INSERT INTO value_conflicts (data_json) VALUES (?)",
                            (json.dumps(conflict),),
                        )
                conn.commit()
                return True
            except Exception as e:
                logger.warning(f"写入价值观失败: {e}")
                conn.rollback()
                return False

    # ============================================================
    # 生命周期管理
    # ============================================================

    def close(self) -> None:
        """关闭所有存储连接"""
        try:
            self._exp_backend.close()
        except Exception:
            pass
        try:
            self._values_backend.close()
        except Exception:
            pass
        logger.info("LocalSqlitePersonastore 已关闭")
