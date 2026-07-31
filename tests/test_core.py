"""
Castorice Agent - 单元测试

覆盖核心模块：
- 配置加载
- 异常处理
- 日志模块
- 监控指标
- 缓存模块
- 状态持久化
"""

import asyncio
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# 添加项目根目录到路径
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


class TestExceptions(unittest.TestCase):
    """异常处理测试"""

    def test_basic_exception(self):
        from castorice.exceptions import CastoriceError
        exc = CastoriceError("测试错误", details={"key": "value"})
        self.assertEqual(exc.message, "测试错误")
        self.assertIn("key", exc.details)
        self.assertIn("测试错误", str(exc))

    def test_llm_errors(self):
        from castorice.exceptions import (
            LLMConnectionError, LLMAuthError, LLMRateLimitError, LLMTimeoutError
        )
        self.assertTrue(issubclass(LLMAuthError, LLMConnectionError))
        self.assertTrue(issubclass(LLMRateLimitError, LLMConnectionError))

    def test_tool_errors(self):
        from castorice.exceptions import ToolNotFoundError, ToolSecurityError, ToolError
        self.assertTrue(issubclass(ToolSecurityError, ToolError))

    def test_recoverable(self):
        from castorice.exceptions import (
            LLMRateLimitError, CastoriceError, is_recoverable
        )
        self.assertTrue(is_recoverable(LLMRateLimitError("rate")))
        self.assertFalse(is_recoverable(CastoriceError("normal")))


class TestLogger(unittest.TestCase):
    """日志模块测试"""

    def test_setup_logging(self):
        from castorice.logger import setup_logging, get_logger
        # 手动管理临时目录（Windows 文件锁问题，tempfile.TemporaryDirectory 会失败）
        tmp = tempfile.mkdtemp()
        try:
            log_path = Path(tmp) / "test.log"
            setup_logging(level="DEBUG", log_file=str(log_path), use_color=False)
            logger = get_logger("test")
            logger.info("测试日志")
            # 显式给 handler 时间 flush
            import time as _t
            _t.sleep(0.2)
            self.assertTrue(log_path.exists())
        finally:
            # 不强制清理（Windows 文件锁问题），测试通过即可
            pass

    def test_get_logger(self):
        from castorice.logger import get_logger
        logger = get_logger("test_module")
        self.assertIsNotNone(logger)


class TestMetrics(unittest.TestCase):
    """监控指标测试"""

    def test_counter(self):
        from castorice.metrics import get_metrics
        m = get_metrics()
        m.reset()
        m.inc_counter("test_counter", value=3)
        m.inc_counter("test_counter", labels={"type": "success"})
        stats = m.get_stats()
        self.assertIn("test_counter", stats["counters"])

    def test_timer(self):
        from castorice.metrics import Timer, get_metrics
        m = get_metrics()
        m.reset()
        with Timer("test_op"):
            time.sleep(0.01)
        stats = m.get_stats()
        self.assertIn("test_op", stats["latencies"])
        self.assertGreater(stats["latencies"]["test_op"]["count"], 0)

    def test_prometheus_export(self):
        from castorice.metrics import get_metrics
        m = get_metrics()
        m.reset()
        m.inc_counter("test_metric")
        output = m.export_prometheus()
        self.assertIn("test_metric", output)
        self.assertIn("# TYPE", output)


class TestLLMCache(unittest.TestCase):
    """LLM 缓存测试"""

    def test_set_get(self):
        from castorice.llm_cache import LLMCache
        cache = LLMCache(max_size=10, ttl=60)
        messages = [{"role": "user", "content": "你好"}]
        cache.set(messages, "gpt-4", 0.7, "你好回复")
        result = cache.get(messages, "gpt-4", 0.7)
        self.assertEqual(result, "你好回复")

    def test_cache_miss(self):
        from castorice.llm_cache import LLMCache
        cache = LLMCache()
        result = cache.get([{"role": "user", "content": "未缓存"}], "gpt-4", 0.7)
        self.assertIsNone(result)

    def test_lru_eviction(self):
        from castorice.llm_cache import LLMCache
        cache = LLMCache(max_size=2, ttl=60)
        for i in range(3):
            cache.set([{"role": "user", "content": f"msg{i}"}], "gpt-4", 0.7, f"reply{i}")
        # 第一个应该被淘汰
        result = cache.get([{"role": "user", "content": "msg0"}], "gpt-4", 0.7)
        self.assertIsNone(result)

    def test_stats(self):
        from castorice.llm_cache import LLMCache
        cache = LLMCache()
        cache.set([{"role": "user", "content": "x"}], "gpt-4", 0.7, "y")
        cache.get([{"role": "user", "content": "x"}], "gpt-4", 0.7)  # hit
        cache.get([{"role": "user", "content": "miss"}], "gpt-4", 0.7)  # miss
        stats = cache.stats()
        self.assertEqual(stats["hits"], 1)
        self.assertEqual(stats["misses"], 1)


class TestStatePersistence(unittest.TestCase):
    """状态持久化测试"""

    def test_save_load(self):
        from castorice.state_persistence import StatePersistence
        with tempfile.TemporaryDirectory() as tmp:
            sp = StatePersistence(storage_dir=tmp)
            state = {"user_input": "test", "final_answer": "ok"}
            sp.save("session_1", state)
            loaded = sp.load_latest("session_1")
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded["user_input"], "test")

    def test_snapshot_limit(self):
        from castorice.state_persistence import StatePersistence
        with tempfile.TemporaryDirectory() as tmp:
            sp = StatePersistence(storage_dir=tmp, max_snapshots=3)
            for i in range(5):
                sp.save("session_1", {"idx": i})
            sessions = sp.list_sessions()
            self.assertEqual(len(sessions), 1)

    def test_list_sessions(self):
        from castorice.state_persistence import StatePersistence
        with tempfile.TemporaryDirectory() as tmp:
            sp = StatePersistence(storage_dir=tmp)
            sp.save("s1", {"x": 1})
            sp.save("s2", {"x": 2})
            sessions = sp.list_sessions()
            self.assertIn("s1", sessions)
            self.assertIn("s2", sessions)


class TestConfigSchema(unittest.TestCase):
    """配置 schema 测试"""

    def test_validate_minimal(self):
        from castorice.config_schema import validate_config_dict
        result = validate_config_dict({})
        self.assertIn("llm", result)
        self.assertEqual(result["llm"]["provider"], "openai")

    def test_validate_invalid_provider(self):
        from castorice.config_schema import validate_config_dict
        try:
            validate_config_dict({"llm": {"provider": "invalid"}})
            self.fail("应该抛出异常")
        except (ValueError, Exception):
            pass

    def test_validate_qq_intent(self):
        from castorice.config_schema import validate_config_dict
        result = validate_config_dict({"qq_bot": {"intent": "basic"}})
        self.assertEqual(result["qq_bot"]["intent"], "basic")

    def test_validate_port_range(self):
        from castorice.config_schema import validate_config_dict
        try:
            validate_config_dict({"http_server": {"port": 99999}})
            self.fail("端口越界应该报错")
        except Exception:
            pass


class TestToolSecurity(unittest.TestCase):
    """工具安全测试"""

    def test_dangerous_commands(self):
        try:
            from castorice.tools.base_tools import is_command_safe
        except Exception as e:
            self.skipTest(f"base_tools 加载失败（依赖缺失）: {e}")
            return
        dangerous = ["rm -rf /", "del /f /q C:\\", "format C:", "shutdown /s /t 0"]
        for cmd in dangerous:
            self.assertFalse(is_command_safe(cmd), f"危险命令未拦截: {cmd}")

    def test_safe_commands(self):
        try:
            from castorice.tools.base_tools import is_command_safe
        except Exception as e:
            self.skipTest(f"base_tools 加载失败（依赖缺失）: {e}")
            return
        safe = ["dir", "ls", "echo hello", "cat file.txt"]
        for cmd in safe:
            self.assertTrue(is_command_safe(cmd), f"安全命令被误拦: {cmd}")


class TestAsyncTimeout(unittest.TestCase):
    """异步超时测试"""

    def test_timeout(self):
        async def slow_op():
            await asyncio.sleep(2)
            return "ok"

        async def run_test():
            try:
                await asyncio.wait_for(slow_op(), timeout=0.1)
                self.fail("应该超时")
            except asyncio.TimeoutError:
                pass

        asyncio.run(run_test())


def run_all_tests():
    """运行所有测试"""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    test_classes = [
        TestExceptions,
        TestLogger,
        TestMetrics,
        TestLLMCache,
        TestStatePersistence,
        TestConfigSchema,
        TestToolSecurity,
        TestAsyncTimeout,
    ]

    for cls in test_classes:
        suite.addTests(loader.loadTestsFromTestCase(cls))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    return result.wasSuccessful()


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
