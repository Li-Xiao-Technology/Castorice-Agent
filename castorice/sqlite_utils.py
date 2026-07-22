"""
SQLite 工具模块

提供优化的 SQLite 连接管理：
- WAL 模式提升并发性能
- 线程安全连接池
- 统一的连接创建接口
"""

import sqlite3
import threading
from typing import Optional


def create_sqlite_connection(db_path: str, timeout: float = 30.0) -> sqlite3.Connection:
    """创建 SQLite 连接（带 WAL 模式优化）"""
    conn = sqlite3.connect(db_path, timeout=timeout, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA cache_size=-64000;")
    return conn


class SQLiteConnectionPool:
    """SQLite 连接池"""

    def __init__(self, db_path: str, max_connections: int = 5):
        self._db_path = db_path
        self._max_connections = max_connections
        self._connections = []
        self._lock = threading.Lock()

    def get_connection(self) -> sqlite3.Connection:
        """获取连接"""
        with self._lock:
            if self._connections:
                return self._connections.pop()
            if len(self._connections) < self._max_connections:
                conn = create_sqlite_connection(self._db_path)
                self._connections.append(conn)
                return self._connections.pop()
        return create_sqlite_connection(self._db_path)

    def release_connection(self, conn: sqlite3.Connection) -> None:
        """释放连接"""
        with self._lock:
            if len(self._connections) < self._max_connections:
                self._connections.append(conn)

    def close(self) -> None:
        """关闭所有连接"""
        with self._lock:
            for conn in self._connections:
                try:
                    conn.close()
                except Exception:
                    pass
            self._connections = []
