"""
castorice.storage.sqlite_base 模块单元测试

覆盖：
- 数据库初始化：文件创建 / 目录自动创建 / db_path 存储 / WAL 模式 / 外键
- CRUD：insert / get / list / update / delete / 不存在记录
- 线程本地连接：每线程独立连接 / 同线程复用 / 跨线程数据可见性
- 事务：commit 持久化 / rollback 回滚 / close 释放
- 清理：_cleanup_all_connections 类方法
"""

import os
import threading

import pytest

from castorice.storage.sqlite_base import SqliteStorage


# ============================================================
# 测试用子类：在 SqliteStorage 之上构建一张简单的 items 表
# ============================================================

class _ItemsModule(SqliteStorage):
    """用于测试的 SqliteStorage 子类，提供 items 表的 CRUD 封装"""

    def __init__(self, db_path: str):
        super().__init__(db_path)
        self._init_db()

    def _init_db(self):
        """建表（IF NOT EXISTS 保证幂等）"""
        conn = self._get_conn()
        conn.executescript(
            "CREATE TABLE IF NOT EXISTS items ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "name TEXT NOT NULL, "
            "value INTEGER DEFAULT 0);"
        )
        conn.commit()

    def insert(self, name: str, value: int) -> int:
        conn = self._get_conn()
        cur = conn.execute(
            "INSERT INTO items (name, value) VALUES (?, ?)",
            (name, value),
        )
        conn.commit()
        return cur.lastrowid

    def get(self, item_id: int):
        conn = self._get_conn()
        cur = conn.execute(
            "SELECT id, name, value FROM items WHERE id = ?",
            (item_id,),
        )
        return cur.fetchone()

    def list_all(self):
        conn = self._get_conn()
        cur = conn.execute("SELECT id, name, value FROM items ORDER BY id")
        return cur.fetchall()

    def update(self, item_id: int, value: int) -> int:
        conn = self._get_conn()
        cur = conn.execute(
            "UPDATE items SET value = ? WHERE id = ?",
            (value, item_id),
        )
        conn.commit()
        return cur.rowcount

    def delete(self, item_id: int) -> int:
        conn = self._get_conn()
        cur = conn.execute("DELETE FROM items WHERE id = ?", (item_id,))
        conn.commit()
        return cur.rowcount


@pytest.fixture
def db_module(tmp_path):
    """创建测试用 _ItemsModule 实例，测试结束自动关闭连接"""
    db_path = str(tmp_path / "test.db")
    module = _ItemsModule(db_path)
    yield module
    module.close()


# ============================================================
# 数据库初始化测试
# ============================================================

class TestSqliteStorageInit:
    """数据库初始化测试"""

    def test_db_file_created(self, tmp_path):
        """初始化后数据库文件应存在"""
        db_path = str(tmp_path / "test.db")
        module = _ItemsModule(db_path)
        try:
            module._get_conn()  # 触发实际连接建立
            assert os.path.exists(db_path)
        finally:
            module.close()

    def test_db_path_stored(self, tmp_path):
        """db_path 属性应正确存储"""
        db_path = str(tmp_path / "test.db")
        module = _ItemsModule(db_path)
        try:
            assert module.db_path == db_path
        finally:
            module.close()

    def test_directory_auto_created(self, tmp_path):
        """嵌套目录应自动创建"""
        db_path = str(tmp_path / "sub1" / "sub2" / "test.db")
        module = _ItemsModule(db_path)
        try:
            assert os.path.isdir(str(tmp_path / "sub1" / "sub2"))
        finally:
            module.close()

    def test_wal_mode_enabled(self, db_module):
        """WAL 模式应启用"""
        conn = db_module._get_conn()
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        # 文件型 DB 应为 wal（:memory: 会是 memory，此处为文件路径）
        assert mode in ("wal", "memory")

    def test_foreign_keys_on(self, db_module):
        """外键约束应开启"""
        conn = db_module._get_conn()
        fk = conn.execute("PRAGMA foreign_keys").fetchone()[0]
        assert fk == 1

    def test_table_created(self, db_module):
        """items 表应成功创建"""
        conn = db_module._get_conn()
        # 查询 sqlite_master 验证表存在
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='items'"
        ).fetchone()
        assert row is not None
        assert row[0] == "items"


# ============================================================
# CRUD 操作测试
# ============================================================

class TestCRUD:
    """CRUD 操作测试"""

    def test_insert_and_get(self, db_module):
        """插入后应能按 id 查询"""
        item_id = db_module.insert("foo", 42)
        row = db_module.get(item_id)
        assert row is not None
        assert row[0] == item_id
        assert row[1] == "foo"
        assert row[2] == 42

    def test_list_all_empty(self, db_module):
        """空表应返回空列表"""
        rows = db_module.list_all()
        assert rows == []

    def test_list_all_multiple(self, db_module):
        """多条记录应按 id 排序"""
        db_module.insert("a", 1)
        db_module.insert("b", 2)
        db_module.insert("c", 3)
        rows = db_module.list_all()
        assert len(rows) == 3
        # 按 id 升序
        assert rows[0][1] == "a"
        assert rows[2][1] == "c"

    def test_update(self, db_module):
        """更新已存在记录"""
        item_id = db_module.insert("foo", 1)
        affected = db_module.update(item_id, 99)
        assert affected == 1
        row = db_module.get(item_id)
        assert row[2] == 99

    def test_update_nonexistent(self, db_module):
        """更新不存在的记录应返回 0 受影响行"""
        affected = db_module.update(9999, 99)
        assert affected == 0

    def test_delete(self, db_module):
        """删除已存在记录"""
        item_id = db_module.insert("foo", 1)
        affected = db_module.delete(item_id)
        assert affected == 1
        assert db_module.get(item_id) is None

    def test_delete_nonexistent(self, db_module):
        """删除不存在的记录应返回 0 受影响行"""
        affected = db_module.delete(9999)
        assert affected == 0

    def test_get_nonexistent(self, db_module):
        """查询不存在的 id 应返回 None"""
        assert db_module.get(9999) is None

    def test_chinese_name_roundtrip(self, db_module):
        """中文名称应正确读写（UTF-8）"""
        item_id = db_module.insert("测试条目", 100)
        row = db_module.get(item_id)
        assert row[1] == "测试条目"

    @pytest.mark.parametrize("name,value", [
        ("alice", 100),
        ("bob", 200),
        ("中文条目", 300),
        ("emoji", 0),
    ])
    def test_parametrized_insert_and_get(self, db_module, name, value):
        """参数化：批量验证 insert + get 往返"""
        item_id = db_module.insert(name, value)
        row = db_module.get(item_id)
        assert row is not None
        assert row[1] == name
        assert row[2] == value


# ============================================================
# 线程本地连接测试
# ============================================================

class TestThreadLocal:
    """线程本地连接行为测试"""

    def test_same_thread_returns_same_conn(self, db_module):
        """同一线程多次获取应返回同一连接"""
        c1 = db_module._get_conn()
        c2 = db_module._get_conn()
        assert c1 is c2

    def test_each_thread_gets_own_connection(self, db_module):
        """不同线程应获得不同连接"""
        main_conn = db_module._get_conn()
        results = {}

        def worker():
            t_conn = db_module._get_conn()
            results["same_as_main"] = (t_conn is main_conn)
            results["thread_conn"] = t_conn

        t = threading.Thread(target=worker)
        t.start()
        t.join()

        assert results["same_as_main"] is False
        assert results["thread_conn"] is not None

    def test_data_visible_across_threads(self, db_module):
        """WAL 模式下，已提交数据应跨线程可见"""
        item_id = db_module.insert("shared", 1)
        errors = []

        def worker():
            try:
                conn = db_module._get_conn()
                row = conn.execute(
                    "SELECT id, name, value FROM items WHERE id = ?",
                    (item_id,),
                ).fetchone()
                assert row is not None
                assert row[1] == "shared"
            except Exception as e:
                errors.append(e)

        t = threading.Thread(target=worker)
        t.start()
        t.join()
        assert len(errors) == 0

    def test_concurrent_inserts_no_error(self, db_module):
        """并发插入不应产生错误（每个线程独立连接）"""
        errors = []

        def worker(idx):
            try:
                for i in range(5):
                    db_module.insert(f"thread-{idx}-item-{i}", i)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        # 应有 4 线程 * 5 条 = 20 条记录
        rows = db_module.list_all()
        assert len(rows) == 20


# ============================================================
# 事务测试
# ============================================================

class TestTransaction:
    """事务 commit / rollback 测试"""

    def test_commit_persists_data(self, db_module):
        """commit 后数据应持久化"""
        conn = db_module._get_conn()
        conn.execute(
            "INSERT INTO items (name, value) VALUES (?, ?)",
            ("committed", 1),
        )
        conn.commit()
        row = conn.execute(
            "SELECT name, value FROM items WHERE name = ?",
            ("committed",),
        ).fetchone()
        assert row is not None
        assert row[0] == "committed"

    def test_rollback_discards_data(self, db_module):
        """rollback 后未提交的数据应被丢弃"""
        conn = db_module._get_conn()
        conn.execute(
            "INSERT INTO items (name, value) VALUES (?, ?)",
            ("rollback", 1),
        )
        conn.rollback()
        row = conn.execute(
            "SELECT name FROM items WHERE name = ?",
            ("rollback",),
        ).fetchone()
        assert row is None

    def test_rollback_does_not_affect_committed(self, db_module):
        """rollback 不应影响已提交的数据"""
        conn = db_module._get_conn()
        # 先提交一条
        db_module.insert("keep", 1)
        # 再插入一条不提交并回滚
        conn.execute(
            "INSERT INTO items (name, value) VALUES (?, ?)",
            ("discard", 2),
        )
        conn.rollback()
        # 已提交的应保留
        assert db_module.get(1) is not None
        # 未提交的应被丢弃
        row = conn.execute(
            "SELECT name FROM items WHERE name = ?", ("discard",)
        ).fetchone()
        assert row is None

    def test_close_releases_connection(self, tmp_path):
        """close 后线程本地连接应被清空"""
        db_path = str(tmp_path / "test.db")
        module = _ItemsModule(db_path)
        module._get_conn()  # 建立连接
        module.close()
        # close 后 _local.conn 应为 None
        assert getattr(module._local, "conn", None) is None

    def test_close_idempotent(self, tmp_path):
        """多次 close 不应报错"""
        db_path = str(tmp_path / "test.db")
        module = _ItemsModule(db_path)
        module._get_conn()
        module.close()
        module.close()  # 再次调用应无副作用


# ============================================================
# 清理逻辑测试
# ============================================================

class TestCleanup:
    """清理逻辑测试"""

    def test_connection_tracked_in_all_connections(self, db_module):
        """新连接应加入 _all_connections 集合"""
        conn = db_module._get_conn()
        assert conn in SqliteStorage._all_connections

    def test_close_removes_from_tracking(self, tmp_path):
        """close 后连接应从 _all_connections 移除"""
        db_path = str(tmp_path / "test.db")
        module = _ItemsModule(db_path)
        conn = module._get_conn()
        assert conn in SqliteStorage._all_connections
        module.close()
        assert conn not in SqliteStorage._all_connections

    def test_cleanup_all_connections_classmethod(self, tmp_path):
        """_cleanup_all_connections 应关闭并清空所有跟踪的连接"""
        db_path = str(tmp_path / "test.db")
        module = _ItemsModule(db_path)
        conn = module._get_conn()
        assert conn in SqliteStorage._all_connections

        # 调用类方法清理
        SqliteStorage._cleanup_all_connections()

        # 集合应被清空
        assert len(SqliteStorage._all_connections) == 0

        # 清理后 close 不应报错（连接已被关闭，discard 也不报错）
        module.close()
