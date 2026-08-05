"""
SQLite 工具模块

提供优化的 SQLite 连接管理：
- WAL 模式提升并发性能
- 线程本地连接池（每线程独立连接，避免跨线程共享）
- 统一的连接创建接口
"""

import sqlite3
import threading


def create_sqlite_connection(db_path: str, timeout: float = 30.0) -> sqlite3.Connection:
    """创建 SQLite 连接（带 WAL 模式优化）"""
    conn = sqlite3.connect(db_path, timeout=timeout, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA cache_size=-64000;")
    return conn


class SQLiteConnectionPool:
    """SQLite 连接池（线程本地模式）

    每个线程持有自己的连接，避免跨线程共享连接导致的线程安全问题。
    所有创建过的连接通过全局集合跟踪，便于 close() 统一关闭。
    """

    def __init__(self, db_path: str, max_connections: int = 5):
        self._db_path = db_path
        self._max_connections = max_connections
        self._local = threading.local()
        self._lock = threading.Lock()
        # 跟踪所有线程创建的连接（sqlite3.Connection 不支持弱引用，使用强引用集合）
        self._all_connections: set = set()

    def get_connection(self) -> sqlite3.Connection:
        """获取连接（从线程本地存储获取，没有则创建新连接）"""
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            return conn
        conn = create_sqlite_connection(self._db_path)
        self._local.conn = conn
        with self._lock:
            self._all_connections.add(conn)
        return conn

    def release_connection(self, conn: sqlite3.Connection) -> None:
        """释放连接（在线程本地存储中缓存连接，供下次 get_connection 复用）"""
        self._local.conn = conn

    def close(self) -> None:
        """关闭所有线程的连接"""
        with self._lock:
            for conn in self._all_connections:
                try:
                    conn.close()
                except Exception:
                    pass
            self._all_connections = set()
        # 清理当前线程本地连接引用
        self._local.conn = None
