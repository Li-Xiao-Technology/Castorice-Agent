"""
短时记忆模块 - 基于 SQLite 实现单轮会话上下文存储
（从原 castorice_memory.short_term_memory 迁移，去除冗余导入）
"""

import json
import sqlite3
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import List, Optional, Dict, Any


@dataclass
class Message:
    """单条对话消息结构"""
    role: str       # 'user' / 'assistant' / 'system' / 'tool'
    content: str
    tool_calls: Optional[List[Dict[str, Any]]] = None
    tool_call_id: Optional[str] = None
    timestamp: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.utcnow().isoformat()
        if self.metadata is None:
            self.metadata = {}

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Message":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


class ShortTermMemory:
    """短时记忆管理器（SQLite 持久化）"""

    def __init__(self, db_path: str = "./castorice_data/sessions.db", max_turns: int = 20):
        self.db_path = db_path
        self.max_turns = max_turns
        self._init_db()

    def _init_db(self) -> None:
        """初始化 SQLite 表结构"""
        import os
        os.makedirs(os.path.dirname(self.db_path) or ".", exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                archived INTEGER DEFAULT 0,
                summary TEXT
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                tool_calls TEXT,
                tool_call_id TEXT,
                timestamp TEXT NOT NULL,
                metadata TEXT,
                FOREIGN KEY (session_id) REFERENCES sessions(session_id)
            )
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_messages_session
            ON messages(session_id, timestamp)
        """)
        conn.commit()
        conn.close()

    def create_session(self, session_id: Optional[str] = None) -> str:
        if session_id is None:
            session_id = datetime.utcnow().strftime("%Y%m%d_%H%M%S_%f")
        now = datetime.utcnow().isoformat()
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT OR IGNORE INTO sessions (session_id, created_at, updated_at) VALUES (?, ?, ?)",
            (session_id, now, now),
        )
        conn.commit()
        conn.close()
        return session_id

    def add_message(self, session_id: str, message: Message) -> None:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            """INSERT INTO messages (session_id, role, content, tool_calls, tool_call_id, timestamp, metadata)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                session_id, message.role, message.content,
                json.dumps(message.tool_calls) if message.tool_calls else None,
                message.tool_call_id, message.timestamp,
                json.dumps(message.metadata) if message.metadata else None,
            ),
        )
        cursor.execute(
            "UPDATE sessions SET updated_at = ? WHERE session_id = ?",
            (datetime.utcnow().isoformat(), session_id),
        )
        conn.commit()
        conn.close()
        self._truncate_session(session_id)

    def get_history(
        self, session_id: str, limit: Optional[int] = None, include_tool_calls: bool = True
    ) -> List[Message]:
        if limit is None:
            limit = self.max_turns * 2
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            """SELECT role, content, tool_calls, tool_call_id, timestamp, metadata
               FROM messages WHERE session_id = ? ORDER BY timestamp DESC LIMIT ?""",
            (session_id, limit),
        )
        rows = cursor.fetchall()
        conn.close()

        messages = []
        for row in reversed(rows):
            role, content, tool_calls_str, tool_call_id, timestamp, metadata_str = row
            msg = Message(
                role=role, content=content,
                tool_calls=json.loads(tool_calls_str) if tool_calls_str else None,
                tool_call_id=tool_call_id, timestamp=timestamp,
                metadata=json.loads(metadata_str) if metadata_str else {},
            )
            if not include_tool_calls and role == "tool":
                continue
            messages.append(msg)
        return messages

    def _truncate_session(self, session_id: str) -> None:
        keep = self.max_turns * 2
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            """DELETE FROM messages WHERE session_id = ?
               AND id NOT IN (SELECT id FROM messages WHERE session_id = ?
                              ORDER BY timestamp DESC LIMIT ?)""",
            (session_id, session_id, keep),
        )
        conn.commit()
        conn.close()

    def clear_session(self, session_id: str) -> None:
        conn = sqlite3.connect(self.db_path)
        conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
        conn.commit()
        conn.close()

    def delete_session(self, session_id: str) -> None:
        conn = sqlite3.connect(self.db_path)
        conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
        conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
        conn.commit()
        conn.close()

    def list_sessions(self, archived: Optional[bool] = None) -> List[Dict[str, Any]]:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        if archived is None:
            cursor.execute("SELECT session_id, created_at, updated_at, archived, summary FROM sessions ORDER BY updated_at DESC")
        else:
            cursor.execute(
                "SELECT session_id, created_at, updated_at, archived, summary FROM sessions WHERE archived = ? ORDER BY updated_at DESC",
                (1 if archived else 0,),
            )
        rows = cursor.fetchall()
        conn.close()
        return [
            {"session_id": r[0], "created_at": r[1], "updated_at": r[2], "archived": bool(r[3]), "summary": r[4]}
            for r in rows
        ]

    def mark_archived(self, session_id: str, summary: Optional[str] = None) -> None:
        conn = sqlite3.connect(self.db_path)
        conn.execute("UPDATE sessions SET archived = 1, summary = ? WHERE session_id = ?", (summary, session_id))
        conn.commit()
        conn.close()

    def update_summary(self, session_id: str, summary: str) -> None:
        conn = sqlite3.connect(self.db_path)
        conn.execute("UPDATE sessions SET summary = ? WHERE session_id = ?", (summary, session_id))
        conn.commit()
        conn.close()
