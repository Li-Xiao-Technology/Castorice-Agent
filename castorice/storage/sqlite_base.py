"""
SQLite 连接管理基类

提供线程本地的 SQLite 连接管理，统一各模块重复的连接创建逻辑：
- 线程单例连接（每个线程一个连接，避免 SQLite 多线程锁冲突）
- WAL 模式 + synchronous=NORMAL（多读单写不阻塞）
- 类级 atexit 清理（进程退出时关闭所有连接）
- 定期 WAL checkpoint（防止 WAL 文件无限增长）

子类只需继承此类并设置 self.db_path 即可使用 self._get_conn()。
"""

import atexit
import logging
import os
import sqlite3
import threading
import time
from contextlib import contextmanager

logger = logging.getLogger("Castorice.SqliteStorage")


class SqliteStorage:
    """SQLite 线程本地连接管理基类。

    所有使用 SQLite 持久化的模块应继承此类，获取统一的连接管理能力。

    Usage::

        from castorice.storage import SqliteStorage

        class MyModule(SqliteStorage):
            def __init__(self, db_path: str = "./data/my_module.db"):
                super().__init__(db_path)
                self._init_db()

            def _init_db(self):
                conn = self._get_conn()
                conn.executescript("CREATE TABLE IF NOT EXISTS ...")
    """

    _all_connections_lock = threading.Lock()
    _all_connections: set = set()
    _atexit_registered = False

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._local = threading.local()
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)

        self._last_checkpoint: float = 0.0
        self._checkpoint_interval: float = 300.0

        with SqliteStorage._all_connections_lock:
            if not SqliteStorage._atexit_registered:
                atexit.register(SqliteStorage._cleanup_all_connections)
                SqliteStorage._atexit_registered = True

    def _get_conn(self) -> sqlite3.Connection:
        """获取当前线程的 SQLite 连接（线程单例，启用 WAL 模式）。"""
        if not hasattr(self._local, "conn") or self._local.conn is None:
            conn = sqlite3.connect(self.db_path, timeout=30.0)
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA synchronous=NORMAL;")
            conn.execute("PRAGMA foreign_keys=ON;")
            conn.execute("PRAGMA cache_size=-8000;")
            self._local.conn = conn

            with SqliteStorage._all_connections_lock:
                SqliteStorage._all_connections.add(conn)

        return self._local.conn

    def maybe_checkpoint(self) -> None:
        """定期执行 WAL checkpoint，防止 WAL 文件无限增长。

        应由 CronScheduler 或后台线程定期调用，不应在 _get_conn() 中执行
        以避免阻塞连接获取路径。
        """
        now = time.time()
        if now - self._last_checkpoint <= self._checkpoint_interval:
            return
        conn = getattr(self._local, "conn", None)
        if conn is None:
            return
        try:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
            self._last_checkpoint = now
        except Exception as e:
            logger.debug(f"WAL checkpoint 失败: {e}")

    @contextmanager
    def transaction(self):
        """显式事务管理器：自动 commit / rollback。

        Usage::

            with storage.transaction() as conn:
                conn.execute("INSERT INTO ...")
        """
        conn = self._get_conn()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    def close(self) -> None:
        """关闭当前线程的 SQLite 连接并从跟踪集合移除。"""
        if hasattr(self._local, "conn") and self._local.conn is not None:
            conn = self._local.conn
            self._local.conn = None
            with SqliteStorage._all_connections_lock:
                SqliteStorage._all_connections.discard(conn)
            try:
                conn.close()
            except Exception:
                pass

    @classmethod
    def _cleanup_all_connections(cls) -> None:
        """atexit 回调：关闭所有线程的 SQLite 连接。"""
        with cls._all_connections_lock:
            for conn in cls._all_connections:
                try:
                    conn.close()
                except Exception:
                    pass
            cls._all_connections.clear()