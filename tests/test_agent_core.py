"""
核心主循环单元测试
==================

测试 CastoriceAgent 的 State 数据类、初始化、工作流选择等核心逻辑。
"""
import pytest
from castorice.agent.core import State, CastoriceAgent
from castorice.agent.common import MAX_TOOL_ROUNDS


class TestStateDataclass:
    """State 数据类测试"""

    def test_state_default_values(self):
        """测试 State 默认值"""
        state = State(user_input="测试输入")
        assert state.user_input == "测试输入"
        assert state.session_id == ""
        assert state.intent_type == ""
        assert state.final_answer == ""
        assert state.success is False  # 默认为 False，执行成功后设为 True
        assert state.history_messages == []
        assert state.initiated_topic == ""
        assert state.confidence == 1.0

    def test_state_with_all_fields(self):
        """测试 State 完整字段赋值"""
        state = State(
            user_input="你好",
            session_id="test-session-123",
            intent_type="chat",
            final_answer="你好！",
            success=True,
            history_messages=[],
            relevant_history="历史记录",
            current_motivations=["好奇心"],
        )
        assert state.session_id == "test-session-123"
        assert state.intent_type == "chat"
        assert state.current_motivations == ["好奇心"]

    def test_state_tool_calls_list(self):
        """测试 tool_calls 列表字段"""
        state = State(user_input="test")
        assert state.tool_calls == []
        state.tool_calls.append({"name": "web_search", "args": {"q": "test"}})
        assert len(state.tool_calls) == 1

    def test_state_success_flag(self):
        """测试 success 标志位"""
        state = State(user_input="test")
        assert state.success is False  # 默认为 False
        state.success = True
        assert state.success is True

    def test_state_history_messages(self):
        """测试 history_messages 列表"""
        state = State(user_input="test")
        assert state.history_messages == []
        # 模拟添加历史消息
        from castorice.model_adapter import ChatMessage
        state.history_messages.append(ChatMessage("user", "你好"))
        assert len(state.history_messages) == 1

    def test_state_errors_list(self):
        """测试 errors 列表"""
        state = State(user_input="test")
        assert state.errors == []
        state.errors.append("错误1")
        assert len(state.errors) == 1


class TestCommonConstants:
    """common.py 常量测试"""

    def test_max_tool_rounds(self):
        """测试最大工具调用轮数"""
        assert MAX_TOOL_ROUNDS == 5
        assert isinstance(MAX_TOOL_ROUNDS, int)


class TestWorkflowSelection:
    """工作流选择逻辑测试"""

    def test_intent_type_empty_string_is_falsy(self):
        """测试空字符串 intent_type 为 falsy"""
        state = State(user_input="test")
        assert state.intent_type == ""
        assert not state.intent_type  # 空字符串是 falsy

    def test_intent_type_non_empty_is_truthy(self):
        """测试非空 intent_type 为 truthy"""
        state = State(user_input="test", intent_type="chat")
        assert state.intent_type == "chat"
        assert state.intent_type  # 非空字符串是 truthy


class TestMetacognitionResultHandling:
    """元认知结果处理测试"""

    def test_metacognition_result_default_none(self):
        """测试 metacognition_result 默认为 None"""
        state = State(user_input="test")
        assert state.metacognition_result is None

    def test_metacognition_result_dict_access(self):
        """测试 metacognition_result 字典访问"""
        state = State(user_input="test")
        # 模拟设置元认知结果
        state.metacognition_result = {"confidence": {"overall_score": 0.85}}
        assert state.metacognition_result is not None
        assert state.metacognition_result.get("confidence", {}).get("overall_score", 1.0) == 0.85

    def test_metacognition_result_empty_dict(self):
        """测试空的 metacognition_result"""
        state = State(user_input="test")
        state.metacognition_result = {}
        # 空字典应该返回默认值
        confidence = state.metacognition_result.get("confidence", {})
        overall_score = confidence.get("overall_score", 1.0) if isinstance(confidence, dict) else 1.0
        assert overall_score == 1.0


class TestInitiatedTopic:
    """主动话题字段测试"""

    def test_initiated_topic_default_empty(self):
        """测试 initiated_topic 默认为空"""
        state = State(user_input="test")
        assert state.initiated_topic == ""

    def test_initiated_topic_can_be_set(self):
        """测试 initiated_topic 可赋值"""
        state = State(user_input="test")
        state.initiated_topic = "你提到的量子计算，我很好奇..."
        assert state.initiated_topic == "你提到的量子计算，我很好奇..."


class TestRelevantHistory:
    """相关历史字段测试"""

    def test_relevant_history_default_empty(self):
        """测试 relevant_history 默认为空"""
        state = State(user_input="test")
        assert state.relevant_history == ""

    def test_relevant_history_can_be_set(self):
        """测试 relevant_history 可赋值"""
        state = State(user_input="test")
        state.relevant_history = "用户之前问过类似的问题..."
        assert "类似的问题" in state.relevant_history


class TestCurrentMotivations:
    """当前动机字段测试"""

    def test_current_motivations_default_empty(self):
        """测试 current_motivations 默认为空列表"""
        state = State(user_input="test")
        assert state.current_motivations == []

    def test_current_motivations_can_be_set(self):
        """测试 current_motivations 可赋值"""
        state = State(user_input="test")
        state.current_motivations = ["好奇心驱动", "关系维护"]
        assert len(state.current_motivations) == 2
        assert "好奇心驱动" in state.current_motivations


if __name__ == "__main__":
    pytest.main([__file__, "-v"])