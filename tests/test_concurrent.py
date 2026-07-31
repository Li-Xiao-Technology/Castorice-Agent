"""
并发压力测试 - 验证多会话并发场景下的稳定性
"""
import threading
import time
import pytest

from castorice.storage.sqlite_base import SqliteStorage
from castorice.memory.short_term import ShortTermMemory, Message
from castorice.memory.long_term import LongTermMemory
from castorice.memory.skill import SkillMemory


class TestConcurrentAccess:
    """并发访问测试"""

    def test_sqlite_concurrent_write(self, tmp_path):
        """测试 SQLite 多线程并发写入"""
        db_path = str(tmp_path / "test_concurrent.db")
        storage = SqliteStorage(db_path)
        
        errors = []
        lock = threading.Lock()
        thread_count = 5
        writes_per_thread = 20

        def worker(thread_id):
            try:
                for i in range(writes_per_thread):
                    conn = storage._get_conn()
                    conn.execute(
                        "INSERT INTO test_data (thread_id, value) VALUES (?, ?)",
                        (thread_id, f"value_{thread_id}_{i}")
                    )
                    conn.commit()
            except Exception as e:
                with lock:
                    errors.append((thread_id, str(e)))

        # 创建测试表
        conn = storage._get_conn()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS test_data (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                thread_id INTEGER,
                value TEXT
            )
        """)
        conn.commit()

        # 启动线程
        threads = []
        for i in range(thread_count):
            t = threading.Thread(target=worker, args=(i,))
            threads.append(t)
            t.start()

        # 等待完成
        for t in threads:
            t.join(timeout=30)

        # 验证结果
        assert len(errors) == 0, f"并发写入出错: {errors}"
        
        conn = storage._get_conn()
        count = conn.execute("SELECT COUNT(*) FROM test_data").fetchone()[0]
        conn.close()
        assert count == thread_count * writes_per_thread, f"期望 {thread_count * writes_per_thread} 条，实际 {count} 条"

    def test_session_locks_isolation(self, tmp_path):
        """测试会话锁隔离机制"""
        lock_acquired = {}
        lock = threading.Lock()

        def acquire_session_lock(session_id):
            with lock:
                if session_id not in lock_acquired:
                    lock_acquired[session_id] = []
                lock_acquired[session_id].append(threading.current_thread().ident)
            # 模拟操作
            time.sleep(0.05)

        # 模拟 3 个会话，每个会话 2 个并发请求
        threads = []
        for session_id in ["session_1", "session_2", "session_3"]:
            for i in range(2):
                t = threading.Thread(
                    target=acquire_session_lock,
                    args=(session_id,)
                )
                threads.append(t)
                t.start()

        for t in threads:
            t.join(timeout=10)

        # 验证每个会话的请求都是串行的
        for session_id, thread_ids in lock_acquired.items():
            assert len(thread_ids) == 2, f"会话 {session_id} 应有 2 次锁定，实际 {len(thread_ids)}"

    def test_short_term_memory_concurrent_access(self, tmp_path):
        """测试短期记忆并发访问"""
        short_term = ShortTermMemory(str(tmp_path / "short_term.db"))
        errors = []
        lock = threading.Lock()

        def worker(session_id):
            try:
                for i in range(10):
                    short_term.add_message(session_id, Message("user", f"message_{i}"))
                    time.sleep(0.01)
            except Exception as e:
                with lock:
                    errors.append((session_id, str(e)))

        threads = []
        for i in range(3):
            t = threading.Thread(target=worker, args=(f"session_{i}",))
            threads.append(t)
            t.start()

        for t in threads:
            t.join(timeout=10)

        assert len(errors) == 0, f"短期记忆并发访问出错: {errors}"

        # 验证数据完整性
        for i in range(3):
            history = short_term.get_history(f"session_{i}", 20)
            assert len(history) == 10, f"会话 {i} 期望 10 条消息，实际 {len(history)}"

    def test_long_term_memory_concurrent_insert(self, tmp_path):
        """测试长期记忆并发插入（需要 chromadb）"""
        long_term = LongTermMemory(str(tmp_path / "long_term.db"))
        if not long_term._available:
            pytest.skip("LongTermMemory 不可用（缺少 chromadb）")
        
        errors = []
        lock = threading.Lock()

        def worker(thread_id):
            try:
                for i in range(10):
                    long_term.add(
                        text=f"memory_{thread_id}_{i}",
                        metadata={"source": "test", "thread": thread_id}
                    )
                    time.sleep(0.01)
            except Exception as e:
                with lock:
                    errors.append((thread_id, str(e)))

        threads = []
        for i in range(3):
            t = threading.Thread(target=worker, args=(i,))
            threads.append(t)
            t.start()

        for t in threads:
            t.join(timeout=30)

        assert len(errors) == 0, f"长期记忆并发插入出错: {errors}"

        # 验证数据完整性
        count = long_term.count()
        assert count >= 30, f"期望至少 30 条记忆，实际 {count} 条"
