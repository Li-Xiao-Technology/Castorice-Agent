"""
P3.2 工具学习测试
"""
import pytest
from castorice.tool_learning import ToolCallMemory, get_tool_memory


class TestToolCallMemory:
    def test_record_basic(self):
        """测试基本记录功能"""
        mem = ToolCallMemory()
        mem.record("web_search", "搜索Python教程", {"query": "Python"}, "找到10条结果", True)
        assert "web_search" in mem._records
        assert len(mem._records["web_search"]) == 1

    def test_find_similar_jaccard(self):
        """测试 Jaccard 相似度查找"""
        mem = ToolCallMemory()
        # 输入完全相同，相似度应为 1.0
        mem.record("web_search", "搜索Python教程", {"query": "Python"}, "结果A", True)
        mem.record("web_search", "搜索Java教程", {"query": "Java"}, "结果B", True)
        mem.record("web_search", "查询天气", {"city": "北京"}, "结果C", True)

        # 输入和第一条完全相同，相似度最高
        similar = mem.find_similar("web_search", "搜索Python教程", top_k=2)
        assert len(similar) >= 1
        assert similar[0]["desc"] == "搜索Python教程"

    def test_find_similar_filters_failures(self):
        """测试失败案例不参与推荐"""
        mem = ToolCallMemory()
        mem.record("web_search", "搜索 Python 教程", {"query": "Python"}, "成功", True)
        mem.record("web_search", "搜索 Python 教程", {"query": "python"}, "失败", False)

        similar = mem.find_similar("web_search", "搜索 Python 入门")
        # 只剩成功案例
        assert len(similar) == 1
        assert similar[0]["result_summary"] == "成功"

    def test_find_similar_empty(self):
        """测试空记录时返回空列表"""
        mem = ToolCallMemory()
        assert mem.find_similar("unknown_tool", "任何描述") == []

    def test_suggest_arguments_threshold(self):
        """测试参数推荐阈值"""
        mem = ToolCallMemory()
        # 3 条相同输入和参数记录
        mem.record("calc", "搜索Python教程", {"op": "add", "a": 1}, "ok", True)
        mem.record("calc", "搜索Python教程", {"op": "add", "a": 2}, "ok", True)
        mem.record("calc", "搜索Python教程", {"op": "add", "a": 3}, "ok", True)

        suggested = mem.suggest_arguments("calc", "搜索Python教程")
        assert suggested is not None
        assert suggested.get("op") == "add"

    def test_suggest_arguments_no_match(self):
        """测试无相似记录时返回 None"""
        mem = ToolCallMemory()
        result = mem.suggest_arguments("nonexistent_tool", "搜索Python教程")
        assert result is None

    def test_max_records_limit(self):
        """测试每工具最大记录数限制"""
        mem = ToolCallMemory(max_records_per_tool=3)
        for i in range(5):
            mem.record("tool", f"描述{i}", {"i": i}, "ok", True)
        assert len(mem._records["tool"]) == 3

    def test_singleton(self):
        """测试全局单例"""
        m1 = get_tool_memory()
        m2 = get_tool_memory()
        assert m1 is m2


class TestToolCallMemoryThreadSafe:
    def test_concurrent_record(self):
        """测试并发记录安全"""
        import threading
        mem = ToolCallMemory()
        errors = []

        def worker(i):
            try:
                for j in range(10):
                    mem.record("tool", f"desc{i}_{j}", {"i": i}, "ok", True)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len(errors) == 0
