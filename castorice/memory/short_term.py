"""
短时记忆模块 - 基于 SQLite 实现单轮会话上下文存储
（从原 castorice_memory.short_term_memory 迁移，去除冗余导入）
"""

import json
import logging
import sqlite3
from dataclasses import dataclass, asdict
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Dict, Any

from castorice.storage import SqliteStorage
from castorice.memory.interface import ShortTermMemoryInterface

logger = logging.getLogger("Castorice.ShortTermMemory")


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
            self.timestamp = datetime.now(timezone.utc).isoformat()
        if self.metadata is None:
            self.metadata = {}

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Message":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


class ShortTermMemory(SqliteStorage, ShortTermMemoryInterface):
    """短时记忆管理器（SQLite 持久化）"""

    def __init__(self, db_path: str = "./castorice_data/sessions.db", max_turns: int = 20,
                 session_ttl_days: int = 30):
        super().__init__(db_path)
        self.max_turns = max_turns
        self.session_ttl_days = session_ttl_days
        self._init_db()
        try:
            self.cleanup_old_sessions()
        except Exception as e:
            logger.warning(f"P1-21: 启动清理老会话失败: {e}")

    def cleanup_old_sessions(self, days: Optional[int] = None) -> int:
        """
        P1-21: 清理超过指定天数未更新的非归档会话及其消息。

        :param days: 超过该天数未活动的会话将被删除，默认使用 self.session_ttl_days
        :return: 删除的会话数
        """
        ttl = days if days is not None else self.session_ttl_days
        if ttl <= 0:
            return 0
        cutoff = (datetime.now(timezone.utc) - timedelta(days=ttl)).isoformat()
        conn = self._get_conn()
        cursor = conn.cursor()
        try:
            # 先删消息（外键依赖），再删会话
            cursor.execute(
                "DELETE FROM messages WHERE session_id IN "
                "(SELECT session_id FROM sessions WHERE updated_at < ? AND archived = 0)",
                (cutoff,),
            )
            cursor.execute(
                "DELETE FROM sessions WHERE updated_at < ? AND archived = 0",
                (cutoff,),
            )
            deleted = cursor.rowcount
            conn.commit()
            if deleted > 0:
                logger.info(f"P1-21: 清理了 {deleted} 个超过 {ttl} 天的非活跃会话")
            return deleted
        except Exception as e:
            conn.rollback()
            logger.error(f"清理老会话失败: {e}")
            return 0

    def _init_db(self) -> None:
        """初始化 SQLite 表结构"""
        conn = self._get_conn()
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

    def create_session(self, session_id: Optional[str] = None) -> str:
        if session_id is None:
            session_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
        now = datetime.now(timezone.utc).isoformat()
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT OR IGNORE INTO sessions (session_id, created_at, updated_at) VALUES (?, ?, ?)",
            (session_id, now, now),
        )
        conn.commit()
        return session_id

    def add_message(self, session_id: str, message: Message) -> None:
        conn = self._get_conn()
        cursor = conn.cursor()
        # 先确保 session 存在（FOREIGN KEY 约束要求 sessions 表中有对应记录）
        # INSERT OR IGNORE 避免重复插入冲突
        now = datetime.now(timezone.utc).isoformat()
        cursor.execute(
            "INSERT OR IGNORE INTO sessions (session_id, created_at, updated_at) VALUES (?, ?, ?)",
            (session_id, now, now),
        )
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
            (now, session_id),
        )
        conn.commit()
        self._truncate_session(session_id)

    def get_history(
        self, session_id: str, limit: Optional[int] = None, include_tool_calls: bool = True
    ) -> List[Message]:
        if limit is None:
            limit = self.max_turns * 2
        conn = self._get_conn()
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(
            """SELECT role, content, tool_calls, tool_call_id, timestamp, metadata
               FROM messages WHERE session_id = ? ORDER BY timestamp DESC LIMIT ?""",
            (session_id, limit),
        )
        rows = cursor.fetchall()

        messages = []
        for row in reversed(rows):
            msg = Message(
                role=row["role"], content=row["content"],
                tool_calls=json.loads(row["tool_calls"]) if row["tool_calls"] else None,
                tool_call_id=row["tool_call_id"], timestamp=row["timestamp"],
                metadata=json.loads(row["metadata"]) if row["metadata"] else {},
            )
            if not include_tool_calls and row["role"] == "tool":
                continue
            messages.append(msg)
        return messages

    def _truncate_session(self, session_id: str) -> None:
        keep = self.max_turns * 2
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute(
            """DELETE FROM messages WHERE session_id = ?
               AND id NOT IN (SELECT id FROM messages WHERE session_id = ?
                              ORDER BY timestamp DESC LIMIT ?)""",
            (session_id, session_id, keep),
        )
        conn.commit()

    def clear_session(self, session_id: str) -> None:
        conn = self._get_conn()
        conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
        conn.commit()

    def delete_session(self, session_id: str) -> None:
        conn = self._get_conn()
        conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
        conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
        conn.commit()

    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT session_id, created_at, updated_at, archived, summary FROM sessions WHERE session_id = ?", (session_id,))
        row = cursor.fetchone()
        if row:
            return {"session_id": row[0], "created_at": row[1], "updated_at": row[2], "archived": bool(row[3]), "summary": row[4]}
        return None

    def list_sessions(self, archived: Optional[bool] = None, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        conn = self._get_conn()
        cursor = conn.cursor()
        if archived is None:
            query = "SELECT session_id, created_at, updated_at, archived, summary FROM sessions ORDER BY updated_at DESC"
            params = ()
        else:
            query = "SELECT session_id, created_at, updated_at, archived, summary FROM sessions WHERE archived = ? ORDER BY updated_at DESC"
            params = (1 if archived else 0,)
        
        if limit is not None:
            query += " LIMIT ?"
            params = params + (limit,)
        
        cursor.execute(query, params)
        rows = cursor.fetchall()
        return [
            {"session_id": r[0], "created_at": r[1], "updated_at": r[2], "archived": bool(r[3]), "summary": r[4]}
            for r in rows
        ]

    def mark_archived(self, session_id: str, summary: Optional[str] = None) -> None:
        conn = self._get_conn()
        conn.execute("UPDATE sessions SET archived = 1, summary = ? WHERE session_id = ?", (summary, session_id))
        conn.commit()

    def update_summary(self, session_id: str, summary: str) -> None:
        conn = self._get_conn()
        conn.execute("UPDATE sessions SET summary = ? WHERE session_id = ?", (summary, session_id))
        conn.commit()

    def generate_summary(
        self,
        session_id: str,
        model_adapter: Any = None,
        max_messages: int = 50,
    ) -> str:
        """
        使用 LLM 生成会话摘要

        :param session_id: 会话 ID
        :param model_adapter: 模型适配器（用于生成摘要）
        :param max_messages: 最多使用多少条消息生成摘要
        :return: 会话摘要文本
        """
        messages = self.get_history(session_id, limit=max_messages)
        if not messages:
            return ""

        if model_adapter is None:
            return self._simple_summary(messages)

        try:
            from castorice.model_adapter import ChatMessage

            conversation_text = "\n".join(
                f"{m.role}: {m.content[:500]}"
                for m in messages[-30:]
            )

            prompt = f"""请为以下对话生成一个简明扼要的摘要（50-100字）。

【对话内容】
{conversation_text}

【摘要要求】
1. 概括用户的主要问题和需求
2. 概括 Agent 的关键回答和行动
3. 提取对话中的关键主题和结论
4. 使用中文，保持简洁

请直接返回摘要，不要其他内容。"""

            response = model_adapter.chat([
                ChatMessage("system", "你是对话摘要专家，只输出摘要内容。"),
                ChatMessage("user", prompt),
            ])
            summary = response.content if hasattr(response, "content") else str(response)
            self.update_summary(session_id, summary)
            return summary.strip()

        except Exception as e:
            logger.warning(f"LLM 生成摘要失败，使用简单摘要: {e}")
            return self._simple_summary(messages)

    def _simple_summary(self, messages: List[Message]) -> str:
        """简单摘要（不使用 LLM）"""
        user_messages = [m for m in messages if m.role == "user"]
        if not user_messages:
            return ""

        # 提取用户最后几条消息的关键词
        recent_user = user_messages[-3:]
        topics = []
        for msg in recent_user:
            content = msg.content[:100]
            if content not in topics:
                topics.append(content)

        return f"对话主题: {'; '.join(topics)}"
