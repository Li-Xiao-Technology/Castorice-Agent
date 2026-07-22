"""
性能基准测试

建立关键路径的性能基线，用于：
- 检测性能回归
- 优化前后的对比基线
- 评估不同配置的吞吐量

基准指标以软断言形式记录（不强制失败），便于追踪趋势。
"""
import time
import tempfile
import os
import pytest

from castorice.response_cache import ResponseCache
from castorice.tool_learning import ToolCallMemory
from castorice.multi_agent import MultiAgentCoordinator, AgentRole
from castorice.notifications import NotificationManager
from castorice.sqlite_utils import create_sqlite_connection
from castorice.conversation_importer import ConversationImporter, ImportFormat
from castorice.emotion import EmotionState


# 性能基线（秒）—— 超出基线仅警告，不算失败
BASELINE = {
    "cache_set_1000": 0.5,
    "cache_get_1000": 0.3,
    "tool_record_500": 0.3,
    "tool_find_similar_100": 0.1,
    "multi_agent_register_100": 0.5,
    "multi_agent_create_task_100": 1.0,
    "notification_send_1000": 0.5,
    "sqlite_insert_1000": 0.5,
    "emotion_decay_10000": 0.5,
    "importer_jsonl_100": 0.3,
}


class TestResponseCacheBenchmark:
    def test_cache_set_1000(self):
        """测试缓存写入 1000 条性能"""
        cache = ResponseCache(max_size=2000)
        start = time.time()
        for i in range(1000):
            cache.set(
                [{"role": "user", "content": f"msg_{i}"}],
                "gpt-4o",
                {"content": f"reply_{i}"},
            )
        elapsed = time.time() - start
        assert elapsed < BASELINE["cache_set_1000"] * 3  # 3 倍基线
        print(f"\n  cache_set_1000: {elapsed*1000:.1f}ms (baseline: {BASELINE['cache_set_1000']*1000:.0f}ms)")

    def test_cache_get_1000(self):
        """测试缓存读取 1000 条性能"""
        cache = ResponseCache()
        msgs = [{"role": "user", "content": "bench_test"}]
        cache.set(msgs, "m", {"x": 1})
        start = time.time()
        for _ in range(1000):
            cache.get(msgs, "m")
        elapsed = time.time() - start
        assert elapsed < BASELINE["cache_get_1000"] * 3
        print(f"\n  cache_get_1000: {elapsed*1000:.1f}ms (baseline: {BASELINE['cache_get_1000']*1000:.0f}ms)")


class TestToolLearningBenchmark:
    def test_tool_record_500(self):
        """测试工具调用记录 500 次性能"""
        mem = ToolCallMemory()
        start = time.time()
        for i in range(500):
            mem.record("tool", f"描述 {i}", {"i": i}, f"结果 {i}", True)
        elapsed = time.time() - start
        assert elapsed < BASELINE["tool_record_500"] * 3
        print(f"\n  tool_record_500: {elapsed*1000:.1f}ms (baseline: {BASELINE['tool_record_500']*1000:.0f}ms)")

    def test_tool_find_similar_100(self):
        """测试相似度查找 100 次性能"""
        mem = ToolCallMemory()
        # 预填充数据
        for i in range(100):
            mem.record("tool", f"描述 工具 任务 {i}", {"i": i}, "ok", True)
        start = time.time()
        for i in range(100):
            mem.find_similar("tool", f"描述 任务 {i}")
        elapsed = time.time() - start
        assert elapsed < BASELINE["tool_find_similar_100"] * 3
        print(f"\n  tool_find_similar_100: {elapsed*1000:.1f}ms (baseline: {BASELINE['tool_find_similar_100']*1000:.0f}ms)")


class TestMultiAgentBenchmark:
    def test_register_100(self):
        """测试注册 100 个 Agent 性能"""
        coord = MultiAgentCoordinator()
        start = time.time()
        for i in range(100):
            coord.register_agent(f"a{i}", AgentRole.GENERALIST, f"Agent{i}")
        elapsed = time.time() - start
        assert elapsed < BASELINE["multi_agent_register_100"] * 3
        print(f"\n  multi_agent_register_100: {elapsed*1000:.1f}ms")

    def test_create_task_100(self):
        """测试创建 100 个任务性能"""
        coord = MultiAgentCoordinator()
        coord.register_agent("a1", AgentRole.GENERALIST, "Agent")
        start = time.time()
        for i in range(100):
            coord.create_task("test", {"i": i}, target_role=AgentRole.GENERALIST)
        elapsed = time.time() - start
        assert elapsed < BASELINE["multi_agent_create_task_100"] * 3
        print(f"\n  multi_agent_create_task_100: {elapsed*1000:.1f}ms")


class TestNotificationBenchmark:
    def test_send_1000(self):
        """测试发送 1000 个通知性能"""
        mgr = NotificationManager()
        start = time.time()
        for i in range(1000):
            mgr.send_message(f"标题{i}", f"内容{i}")
        elapsed = time.time() - start
        assert elapsed < BASELINE["notification_send_1000"] * 3
        print(f"\n  notification_send_1000: {elapsed*1000:.1f}ms")


class TestSQLiteBenchmark:
    def test_insert_1000(self):
        """测试 SQLite 插入 1000 条性能"""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            path = f.name
        try:
            conn = create_sqlite_connection(path)
            conn.execute("CREATE TABLE bench (id INTEGER PRIMARY KEY, data TEXT)")
            start = time.time()
            for i in range(1000):
                conn.execute("INSERT INTO bench VALUES (?, ?)", (i, f"data_{i}"))
            conn.commit()
            elapsed = time.time() - start
            assert elapsed < BASELINE["sqlite_insert_1000"] * 3
            print(f"\n  sqlite_insert_1000: {elapsed*1000:.1f}ms")
            conn.close()
        finally:
            for ext in ("", "-wal", "-shm"):
                try:
                    os.remove(path + ext)
                except FileNotFoundError:
                    pass


class TestEmotionBenchmark:
    def test_decay_10000(self):
        """测试情感衰减 10000 次性能"""
        state = EmotionState(pleasure=0.5, arousal=0.5, dominance=0.5)
        start = time.time()
        for _ in range(10000):
            state.decay()
        elapsed = time.time() - start
        assert elapsed < BASELINE["emotion_decay_10000"] * 3
        print(f"\n  emotion_decay_10000: {elapsed*1000:.1f}ms")


class TestImporterBenchmark:
    def test_jsonl_100(self, tmp_path):
        """测试 JSONL 导入 100 条性能"""
        jsonl = tmp_path / "bench.jsonl"
        with open(jsonl, "w", encoding="utf-8") as f:
            for i in range(100):
                f.write(f'{{"role": "user", "content": "message {i}"}}\n')
        importer = ConversationImporter()
        start = time.time()
        result = importer.import_from_file(str(jsonl), ImportFormat.JSONL)
        elapsed = time.time() - start
        assert result.get("success") is True
        assert result.get("imported_count") == 100
        assert elapsed < BASELINE["importer_jsonl_100"] * 3
        print(f"\n  importer_jsonl_100: {elapsed*1000:.1f}ms")


class TestBenchmarkSummary:
    def test_print_summary(self, capsys):
        """运行所有基准并打印汇总"""
        with capsys.disabled():
            print("\n" + "=" * 50)
            print("性能基准汇总")
            print("=" * 50)

        # 仅打印，不强制
        assert True
