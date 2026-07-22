"""
P3 LLM 响应缓存测试
"""
import time
import pytest
from castorice.response_cache import (
    ResponseCache,
    FileResponseCache,
    get_response_cache,
)


class TestResponseCache:
    def test_set_and_get(self):
        """测试基本存取"""
        cache = ResponseCache()
        msgs = [{"role": "user", "content": "hello"}]
        cache.set(msgs, "gpt-4o", {"content": "hi"})
        result = cache.get(msgs, "gpt-4o")
        assert result == {"content": "hi"}

    def test_get_miss(self):
        """测试缓存未命中"""
        cache = ResponseCache()
        result = cache.get([{"role": "user", "content": "x"}], "gpt-4o")
        assert result is None

    def test_different_model_different_cache(self):
        """不同模型缓存独立"""
        cache = ResponseCache()
        msgs = [{"role": "user", "content": "test"}]
        cache.set(msgs, "gpt-4o", {"content": "from gpt"})
        cache.set(msgs, "claude", {"content": "from claude"})
        assert cache.get(msgs, "gpt-4o") == {"content": "from gpt"}
        assert cache.get(msgs, "claude") == {"content": "from claude"}

    def test_ttl_expired(self):
        """测试 TTL 过期"""
        cache = ResponseCache(ttl_seconds=0.1)
        msgs = [{"role": "user", "content": "ttl_test"}]
        cache.set(msgs, "m", {"content": "v"})
        assert cache.get(msgs, "m") is not None
        time.sleep(0.2)
        assert cache.get(msgs, "m") is None

    def test_max_size_lru(self):
        """测试容量上限"""
        cache = ResponseCache(max_size=3)
        for i in range(5):
            cache.set([{"role": "user", "content": f"msg{i}"}], "m", {"i": i})
        # 超过容量，最早的应被淘汰
        assert cache.get([{"role": "user", "content": "msg0"}], "m") is None
        assert cache.get([{"role": "user", "content": "msg4"}], "m") is not None

    def test_stats(self):
        """测试统计信息"""
        cache = ResponseCache()
        msgs = [{"role": "user", "content": "stats"}]
        cache.set(msgs, "m", {"x": 1})
        cache.get(msgs, "m")  # hit
        cache.get([{"role": "user", "content": "miss"}], "m")  # miss
        stats = cache.get_stats()
        assert stats["hit_count"] >= 1
        assert stats["miss_count"] >= 1

    def test_clear(self):
        """测试清空"""
        cache = ResponseCache()
        msgs = [{"role": "user", "content": "clear_test"}]
        cache.set(msgs, "m", {"x": 1})
        cache.clear()
        assert cache.get(msgs, "m") is None
        assert cache.get_stats()["hit_count"] == 0

    def test_kwargs_in_key(self):
        """测试 kwargs 影响缓存键"""
        cache = ResponseCache()
        msgs = [{"role": "user", "content": "kwarg_test"}]
        cache.set(msgs, "m", {"x": 1}, temperature=0.5)
        cache.set(msgs, "m", {"x": 2}, temperature=0.9)
        # 不同 temperature 应独立缓存
        assert cache.get(msgs, "m", temperature=0.5) == {"x": 1}
        assert cache.get(msgs, "m", temperature=0.9) == {"x": 2}


class TestFileResponseCache:
    def test_set_and_get(self, tmp_path):
        """测试文件缓存基本存取"""
        cache_file = tmp_path / "cache.json"
        cache = FileResponseCache(str(cache_file))
        msgs = [{"role": "user", "content": "file_test"}]
        cache.set(msgs, "m", {"x": "y"})
        result = cache.get(msgs, "m")
        assert result == {"x": "y"}


class TestResponseCacheSingleton:
    def test_singleton(self):
        """测试全局单例"""
        c1 = get_response_cache()
        c2 = get_response_cache()
        assert c1 is c2
