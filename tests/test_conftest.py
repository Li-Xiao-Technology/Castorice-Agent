"""
conftest.py 共享 fixture 可用性验证

本文件不测试任何业务模块，仅验证 tests/conftest.py 中定义的 fixture
能够正常工作（创建/返回正确的对象、清理副作用等）。
"""

import os

import pytest

from castorice.emotion import EmotionState
from castorice.model_adapter.common import ChatMessage, ChatResponse


# ============================================================
# temp_dir
# ============================================================

class TestTempDirFixture:
    """temp_dir fixture 验证"""

    def test_directory_exists(self, temp_dir):
        """temp_dir 应为存在的目录"""
        assert os.path.isdir(temp_dir)

    def test_directory_writable(self, temp_dir):
        """temp_dir 应可写入文件"""
        path = os.path.join(temp_dir, "test.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write("hello")
        assert os.path.exists(path)
        with open(path, "r", encoding="utf-8") as f:
            assert f.read() == "hello"

    def test_isolated_per_test(self, temp_dir):
        """每个测试应获得独立的临时目录（无残留文件）"""
        files = os.listdir(temp_dir)
        assert files == []


# ============================================================
# mock_config
# ============================================================

class TestMockConfigFixture:
    """mock_config fixture 验证"""

    def test_llm_provider(self, mock_config):
        """llm.provider 字段应可用"""
        assert mock_config.llm.provider == "openai"

    def test_llm_openai_model(self, mock_config):
        """llm.openai.model 字段应可用"""
        assert mock_config.llm.openai.model == "gpt-4o-mini"

    def test_agent_name(self, mock_config):
        """agent.name 字段应可用"""
        assert mock_config.agent.name == "Castorice"

    def test_memory_capacity(self, mock_config):
        """memory.short_term_capacity 字段应可用"""
        assert mock_config.memory.short_term_capacity == 50

    def test_runtime_debug(self, mock_config):
        """runtime.debug 字段应可用"""
        assert mock_config.runtime.debug is False


# ============================================================
# mock_model_adapter
# ============================================================

class TestMockModelAdapterFixture:
    """mock_model_adapter fixture 验证"""

    def test_chat_returns_chat_response(self, mock_model_adapter):
        """chat() 应返回 ChatResponse 实例"""
        msgs = [ChatMessage(role="user", content="hello")]
        resp = mock_model_adapter.chat(msgs)
        assert isinstance(resp, ChatResponse)

    def test_chat_echoes_user_content(self, mock_model_adapter):
        """chat() 应回显最后一条 user 消息"""
        msgs = [ChatMessage(role="user", content="ping")]
        resp = mock_model_adapter.chat(msgs)
        assert "ping" in resp.content

    def test_chat_with_assistant_first(self, mock_model_adapter):
        """chat() 应跳过 assistant 消息，回显 user 消息"""
        msgs = [
            ChatMessage(role="assistant", content="hi"),
            ChatMessage(role="user", content="world"),
        ]
        resp = mock_model_adapter.chat(msgs)
        assert "world" in resp.content

    def test_chat_no_user_message(self, mock_model_adapter):
        """无 user 消息时应返回默认 mock 响应"""
        msgs = [ChatMessage(role="assistant", content="only assistant")]
        resp = mock_model_adapter.chat(msgs)
        assert resp.content == "mock response"

    def test_provider_attribute(self, mock_model_adapter):
        """provider 属性应可用"""
        assert mock_model_adapter.provider == "mock"


# ============================================================
# mock_emotion_engine
# ============================================================

class TestMockEmotionEngineFixture:
    """mock_emotion_engine fixture 验证"""

    def test_load_returns_emotion_state(self, mock_emotion_engine):
        """load() 应返回 EmotionState 实例"""
        state = mock_emotion_engine.load()
        assert isinstance(state, EmotionState)

    def test_default_state_values(self, mock_emotion_engine):
        """默认 EmotionState 值应在合理范围"""
        state = mock_emotion_engine.load()
        assert 0 <= state.pleasure <= 1
        assert 0 <= state.arousal <= 1

    def test_get_emotion_prompt_empty(self, mock_emotion_engine):
        """get_emotion_prompt() 应返回空字符串"""
        assert mock_emotion_engine.get_emotion_prompt() == ""

    def test_should_refuse_tool_returns_tuple(self, mock_emotion_engine):
        """should_refuse_tool() 应返回 (bool, str) 元组"""
        refuse, reason = mock_emotion_engine.should_refuse_tool("web_search")
        assert refuse is False
        assert reason == ""

    def test_update_returns_dict(self, mock_emotion_engine):
        """update() 应返回包含 agent_pad_delta 的字典"""
        result = mock_emotion_engine.update("test", task_result="")
        assert "agent_pad_delta" in result


# ============================================================
# mock_tool
# ============================================================

class TestMockToolFixture:
    """mock_tool fixture 验证"""

    def test_invoke_echoes_text(self, mock_tool):
        """invoke 应回显输入文本"""
        result = mock_tool.invoke({"text": "hello"})
        assert result == "hello"

    def test_tool_name(self, mock_tool):
        """工具名应为 echo"""
        assert mock_tool.name == "echo"

    def test_tool_description_nonempty(self, mock_tool):
        """工具描述应非空"""
        assert mock_tool.description

    def test_invoke_with_empty_string(self, mock_tool):
        """空字符串输入应返回空字符串"""
        assert mock_tool.invoke({"text": ""}) == ""

    def test_risk_level_default(self, mock_tool):
        """默认风险等级应为 low"""
        assert mock_tool.risk_level == "low"
