"""
短时记忆模块 - 基于 SQLite 实现单轮会话上下文存储
（从原 castorice_memory.short_term_memory 迁移，去除冗余导入）
"""

import atexit
import json
import logging
import sqlite3
import threading
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Dict, Any

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


class ShortTermMemory:
    """短时记忆管理器（SQLite 持久化）"""

    # P1-22: 类级连接跟踪，用于 atexit 时关闭所有线程的连接
    _all_connections_lock = threading.Lock()
    _all_connections: set = set()
    _atexit_registered = False

    def __init__(self, db_path: str = "./castorice_data/sessions.db", max_turns: int = 20,
                 session_ttl_days: int = 30):
        self.db_path = db_path
        self.max_turns = max_turns
        self.session_ttl_days = session_ttl_days
        self._local = threading.local()
        # P1-20: WAL checkpoint 时间戳与间隔（5 分钟）
        self._last_checkpoint: float = 0.0
        self._checkpoint_interval: float = 300.0
        self._init_db()
        # P1-22: 注册 atexit 清理（只注册一次）
        with ShortTermMemory._all_connections_lock:
            if not ShortTermMemory._atexit_registered:
                atexit.register(ShortTermMemory._cleanup_all_connections)
                ShortTermMemory._atexit_registered = True
        # P1-21: 启动时清理老会话
        try:
            self.cleanup_old_sessions()
        except Exception as e:
            logger.warning(f"P1-21: 启动清理老会话失败: {e}")

    def _get_conn(self) -> sqlite3.Connection:
        """获取当前线程的 SQLite 连接（线程单例，启用 WAL 模式避免多线程锁冲突）"""
        if not hasattr(self._local, "conn") or self._local.conn is None:
            import os
            os.makedirs(os.path.dirname(self.db_path) or ".", exist_ok=True)
            conn = sqlite3.connect(self.db_path, timeout=30.0)
            # P1-4: 启用 WAL 模式 + 调整同步策略
            # WAL: 多读单写不阻塞，HTTP Server + QQ Bot + Agent 主线程并发写时不再 database is locked
            # synchronous=NORMAL: WAL 模式下兼顾性能与安全（事务提交时才 fsync）
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA synchronous=NORMAL;")
            conn.execute("PRAGMA foreign_keys=ON;")
            # 行缓存大小提升读性能
            conn.execute("PRAGMA cache_size=-8000;")  # 8MB
            self._local.conn = conn
            # P1-22: 跟踪连接用于 atexit 清理
            with ShortTermMemory._all_connections_lock:
                ShortTermMemory._all_connections.add(conn)
        # P1-20: 定期执行 WAL checkpoint，防止 WAL 文件无限增长
        now = time.time()
        if now - self._last_checkpoint > self._checkpoint_interval:
            try:
                self._local.conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
                self._last_checkpoint = now
            except Exception as e:
                logger.debug(f"P1-20: WAL checkpoint 失败: {e}")
        return self._local.conn

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

    @classmethod
    def _cleanup_all_connections(cls) -> None:
        """P1-22: atexit 时关闭所有线程的 SQLite 连接，防止连接泄漏"""
        with cls._all_connections_lock:
            for conn in cls._all_connections:
                try:
                    conn.close()
                except Exception:
                    pass
            cls._all_connections.clear()

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
        cursor = conn.cursor()
        cursor.execute(
            """SELECT role, content, tool_calls, tool_call_id, timestamp, metadata
               FROM messages WHERE session_id = ? ORDER BY timestamp DESC LIMIT ?""",
            (session_id, limit),
        )
        rows = cursor.fetchall()

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

    def close(self) -> None:
        """关闭当前线程的 SQLite 连接"""
        if hasattr(self._local, "conn") and self._local.conn is not None:
            conn = self._local.conn
            self._local.conn = None
            # P1-22: 从跟踪集合移除
            with ShortTermMemory._all_connections_lock:
                ShortTermMemory._all_connections.discard(conn)
            try:
                conn.close()
            except Exception:
                pass

    def __del__(self):
        """析构时尝试关闭连接"""
        try:
            self.close()
        except Exception as e:
            logger.warning(f"短时记忆析构关闭失败: {e}")
