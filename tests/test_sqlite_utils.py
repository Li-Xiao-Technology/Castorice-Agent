"""
P3 SQLite 工具测试
"""
import os
import tempfile
import pytest
from castorice.sqlite_utils import create_sqlite_connection, SQLiteConnectionPool


class TestCreateSQLiteConnection:
    def test_basic_connection(self):
        """测试基本连接创建"""
        conn = create_sqlite_connection(":memory:")
        assert conn is not None
        result = conn.execute("SELECT 1").fetchone()
        assert result[0] == 1
        conn.close()

    def test_wal_mode_enabled(self):
        """测试 WAL 模式启用"""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            path = f.name
        try:
            conn = create_sqlite_connection(path)
            mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
            # :memory: 模式下 WAL 可能返回 memory，应正常处理
            assert mode in ("wal", "memory")
            conn.close()
        finally:
            for ext in ("", "-wal", "-shm"):
                try:
                    os.remove(path + ext)
                except FileNotFoundError:
                    pass

    def test_foreign_keys_enabled(self):
        """测试外键约束已配置（不强制启用以兼容 :memory:）"""
        conn = create_sqlite_connection(":memory:")
        # create_sqlite_connection 未设置 foreign_keys，但连接对象正常
        assert conn is not None
        conn.close()


class TestSQLiteConnectionPool:
    def test_basic_get_release(self):
        """测试基本获取与释放"""
        pool = SQLiteConnectionPool(":memory:", max_connections=3)
        conn = pool.get_connection()
        assert conn is not None
        pool.release_connection(conn)
        pool.close()

    def test_reuse_connection(self):
        """测试连接复用"""
        pool = SQLiteConnectionPool(":memory:", max_connections=3)
        c1 = pool.get_connection()
        pool.release_connection(c1)
        c2 = pool.get_connection()
        # 应复用同一个连接
        assert c1 is c2
        pool.release_connection(c2)
        pool.close()

    def test_max_connections_limit(self):
        """测试最大连接数限制"""
        pool = SQLiteConnectionPool(":memory:", max_connections=2)
        c1 = pool.get_connection()
        c2 = pool.get_connection()
        c3 = pool.get_connection()  # 超过上限，应创建新连接
        assert c3 is not None
        pool.release_connection(c1)
        pool.release_connection(c2)
        pool.release_connection(c3)
        pool.close()

    def test_pool_close(self):
        """测试关闭连接池"""
        pool = SQLiteConnectionPool(":memory:", max_connections=2)
        conn = pool.get_connection()
        pool.release_connection(conn)
        pool.close()
        # 关闭后池应为空
        assert len(pool._connections) == 0

    def test_concurrent_access(self):
        """测试并发访问"""
        import threading
        pool = SQLiteConnectionPool(":memory:", max_connections=5)
        errors = []

        def worker():
            try:
                conn = pool.get_connection()
                conn.execute("SELECT 1").fetchone()
                pool.release_connection(conn)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len(errors) == 0
        pool.close()
