"""
模型适配器测试

使用 pytest 风格（assert + def test_*）。
"""

import pytest

from castorice.model_adapter import ToolCall, ChatMessage, ChatResponse, ModelAdapter


class TestToolCall:
    """ToolCall 数据类测试"""

    def test_default_values(self):
        tc = ToolCall(id="tc_1", name="test_tool", arguments={})
        assert tc.id == "tc_1"
        assert tc.name == "test_tool"
        assert tc.arguments == {}

    def test_to_dict(self):
        tc = ToolCall(id="tc_1", name="search", arguments={"query": "test"})
        d = tc.to_dict()
        assert d["id"] == "tc_1"
        assert d["type"] == "function"
        assert d["function"]["name"] == "search"
        assert d["function"]["arguments"] == '{"query": "test"}'


class TestChatMessage:
    """ChatMessage 消息结构测试"""

    def test_basic_message(self):
        msg = ChatMessage(role="user", content="hello")
        assert msg.role == "user"
        assert msg.content == "hello"
        assert msg.tool_calls == []
        assert msg.image_urls == []

    def test_to_dict_basic(self):
        msg = ChatMessage(role="system", content="prompt")
        d = msg.to_dict()
        assert d == {"role": "system", "content": "prompt"}

    def test_to_dict_with_tool_calls(self):
        tc = ToolCall(id="tc_1", name="search", arguments={"q": "a"})
        msg = ChatMessage(role="assistant", content="", tool_calls=[tc])
        d = msg.to_dict()
        assert d["role"] == "assistant"
        assert d["tool_calls"][0]["id"] == "tc_1"

    def test_to_dict_tool_result(self):
        msg = ChatMessage(role="tool", content="result", tool_call_id="tc_1", name="search")
        d = msg.to_dict()
        assert d["role"] == "tool"
        assert d["tool_call_id"] == "tc_1"
        assert d["name"] == "search"

    def test_to_dict_multimodal(self):
        msg = ChatMessage(role="user", content="看图", image_urls=["http://example.com/a.jpg"])
        d = msg.to_dict()
        assert isinstance(d["content"], list)
        assert d["content"][0]["type"] == "text"
        assert d["content"][1]["type"] == "image_url"

    def test_to_anthropic_dict_basic(self):
        msg = ChatMessage(role="user", content="hello")
        d = msg.to_anthropic_dict()
        assert d["role"] == "user"
        assert d["content"] == "hello"

    def test_to_anthropic_dict_tool_result(self):
        msg = ChatMessage(role="tool", content="result", tool_call_id="tc_1")
        d = msg.to_anthropic_dict()
        assert d["role"] == "user"
        assert d["content"][0]["type"] == "tool_result"

    def test_to_anthropic_dict_tool_calls(self):
        tc = ToolCall(id="tc_1", name="search", arguments={"q": "a"})
        msg = ChatMessage(role="assistant", tool_calls=[tc])
        d = msg.to_anthropic_dict()
        assert d["role"] == "assistant"
        assert d["content"][0]["type"] == "tool_use"


class TestChatResponse:
    """ChatResponse 回复结构测试"""

    def test_default_values(self):
        resp = ChatResponse()
        assert resp.content == ""
        assert resp.usage == {}
        assert resp.tool_calls == []
        assert resp.has_tool_calls is False

    def test_with_tool_calls(self):
        tc = ToolCall(id="tc_1", name="search", arguments={"q": "a"})
        resp = ChatResponse(content="", tool_calls=[tc])
        assert resp.has_tool_calls is True


class TestModelAdapter:
    """ModelAdapter 配置测试"""

    def test_default_config(self):
        adapter = ModelAdapter({})
        assert adapter.provider == "openai"
        assert adapter.temperature == 0.7
        assert adapter.max_tokens == 4096
        assert adapter.timeout == 60
        assert adapter.max_retries == 3
        assert adapter.retry_delay == 1.0
        assert adapter.tool_choice == "auto"

    def test_custom_config(self):
        cfg = {
            "provider": "anthropic",
            "temperature": 0.5,
            "max_tokens": 2048,
            "timeout": 30,
            "max_retries": 5,
            "tool_choice": "required",
        }
        adapter = ModelAdapter(cfg)
        assert adapter.provider == "anthropic"
        assert adapter.temperature == 0.5
        assert adapter.max_tokens == 2048
        assert adapter.timeout == 30
        assert adapter.max_retries == 5
        assert adapter.tool_choice == "required"

    def test_provider_configs(self):
        cfg = {
            "openai": {"model": "gpt-4"},
            "anthropic": {"model": "claude-3"},
            "gemini": {"model": "gemini-pro"},
        }
        adapter = ModelAdapter(cfg)
        assert adapter.openai_cfg == {"model": "gpt-4"}
        assert adapter.anthropic_cfg == {"model": "claude-3"}
        assert adapter.gemini_cfg == {"model": "gemini-pro"}

    def test_stats_initial(self):
        adapter = ModelAdapter({})
        assert adapter.total_prompt_tokens == 0
        assert adapter.total_completion_tokens == 0
        assert adapter.total_calls == 0
