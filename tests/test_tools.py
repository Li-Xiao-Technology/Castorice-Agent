"""
工具模块单元测试
"""

import os
import tempfile
import pytest
from castorice.tools.base_tools import (
    _registered_tools,
    get_base_tools,
    register_tool,
    Tool,
    _is_path_safe,
    _SAFE_BUILTINS,
    _TERMINAL_WHITELIST,
)


class TestToolRegistry:
    """工具注册机制测试"""

    def test_registered_tools_count(self):
        # 先调用 get_base_tools 触发 web_tools 的自动导入
        get_base_tools()
        # 基础工具 8 个 + 外部信息检索工具 17 个 = 25 个
        assert len(_registered_tools) >= 25

    def test_registered_tools_names(self):
        # 先调用 get_base_tools 触发 web_tools 的自动导入
        get_base_tools()
        expected = {"web_search", "get_weather", "read_file", "write_file",
                    "terminal", "python_repl", "read_document", "get_current_time",
                    "web_fetch", "wikipedia_search", "arxiv_search", "news_search",
                    "github_search", "youtube_search", "bilibili_search",
                    "ip_info", "stock_price", "translate_text",
                    "anime_search", "anime_season",
                    "vrchat_search", "vrchat_popular_worlds",
                    "vrchat_user_status", "vrchat_world_info",
                    "generate_image"}
        assert expected.issubset(set(_registered_tools.keys()))

    def test_get_base_tools_returns_list(self):
        tools = get_base_tools()
        assert isinstance(tools, list)
        assert len(tools) >= 25
        assert all(isinstance(t, Tool) for t in tools)

    def test_register_tool_decorator(self):
        @register_tool(name="test_tool", description="test")
        def test_func(a: int, b: int) -> str:
            return str(a + b)

        assert "test_tool" in _registered_tools
        result = _registered_tools["test_tool"].invoke({"a": 1, "b": 2})
        assert result == "3"


class TestPythonReplSandbox:
    """Python REPL 沙箱安全测试"""

    def setup_method(self):
        self.repl = _registered_tools["python_repl"]

    def test_safe_arithmetic(self):
        result = self.repl.invoke({"code": "print(1 + 1)"})
        assert "2" in result

    def test_safe_string_ops(self):
        result = self.repl.invoke({"code": "s = 'hello world'\nprint(s.upper())"})
        assert "HELLO WORLD" in result

    def test_safe_list_ops(self):
        result = self.repl.invoke({"code": "nums = [3,1,2]\nprint(sorted(nums))"})
        assert "[1, 2, 3]" in result

    def test_import_os_blocked(self):
        result = self.repl.invoke({"code": "import os"})
        assert "ImportError" in result or "error" in result.lower() or "安全拦截" in result

    def test_import_subprocess_blocked(self):
        result = self.repl.invoke({"code": "import subprocess"})
        assert "ImportError" in result or "error" in result.lower() or "安全拦截" in result

    def test_open_blocked(self):
        result = self.repl.invoke({"code": "f = open('test.txt', 'w')"})
        assert "NameError" in result or "error" in result.lower() or "安全拦截" in result

    def test_exec_blocked(self):
        result = self.repl.invoke({"code": "exec('print(1)')"})
        assert "NameError" in result or "error" in result.lower() or "安全拦截" in result

    def test_eval_blocked(self):
        result = self.repl.invoke({"code": "eval('1 + 1')"})
        assert "NameError" in result or "error" in result.lower() or "安全拦截" in result

    def test_safe_builtins_present(self):
        """确保白名单中的内置函数可用"""
        for func_name in ["print", "len", "range", "str", "int", "list", "dict"]:
            assert func_name in _SAFE_BUILTINS


class TestTerminalWhitelist:
    """Terminal 白名单测试"""

    def setup_method(self):
        self.terminal = _registered_tools["terminal"]

    def test_whitelist_command_allowed(self):
        result = self.terminal.invoke({"command": "echo hello_test"})
        assert "BLOCKED" not in result
        assert "hello_test" in result

    def test_rm_blocked(self):
        result = self.terminal.invoke({"command": "rm -rf /"})
        assert "BLOCKED" in result

    def test_format_blocked(self):
        result = self.terminal.invoke({"command": "format c:"})
        assert "BLOCKED" in result

    def test_whitelist_has_common_commands(self):
        common = {"echo", "python", "pip", "git", "ls", "dir", "cat", "grep"}
        assert common.issubset(_TERMINAL_WHITELIST)


class TestFileIOSafety:
    """文件读写安全测试"""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.read_tool = _registered_tools["read_file"]
        self.write_tool = _registered_tools["write_file"]

    def test_is_path_safe_within_allowed(self):
        assert _is_path_safe(os.path.join(self.tmpdir, "test.txt"), [self.tmpdir])

    def test_is_path_safe_outside_allowed(self):
        outside = os.path.join(os.path.dirname(self.tmpdir), "evil.txt")
        assert not _is_path_safe(outside, [self.tmpdir])

    def test_sensitive_env_blocked(self):
        with tempfile.NamedTemporaryFile(suffix=".env", delete=False) as f:
            f.write(b"test")
            f.flush()
            name = f.name
        try:
            assert not _is_path_safe(name, [os.path.dirname(name)])
        finally:
            os.unlink(name)

    def test_sensitive_id_rsa_blocked(self):
        with tempfile.NamedTemporaryFile(prefix="id_rsa_", delete=False) as f:
            f.write(b"test")
            f.flush()
            name = f.name
        try:
            assert not _is_path_safe(name, [os.path.dirname(name)])
        finally:
            os.unlink(name)

    def test_no_allowed_paths_means_no_restriction(self):
        path = os.path.join(self.tmpdir, "test.txt")
        assert _is_path_safe(path, None)
        assert _is_path_safe(path, [])

    def test_write_and_read(self):
        path = os.path.join(self.tmpdir, "test.txt")
        result = self.write_tool.invoke({
            "file_path": path,
            "content": "hello world",
            "allowed_paths": [self.tmpdir],
        })
        assert "已写入" in result
        result = self.read_tool.invoke({
            "file_path": path,
            "allowed_paths": [self.tmpdir],
        })
        assert "hello world" in result
