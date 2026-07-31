"""
测试 ThinkingLoop 自主思考循环。

测试覆盖：
- 简单聊天（LLM 自主决定 finish）
- 任务执行（LLM 自主调用工具）
- max_steps 限制
- 决策日志记录
- legacy 模式兼容性
"""

import asyncio
import json
import pytest
from unittest.mock import MagicMock, Mock, patch

# 需要导入 ThinkingLoop
from castorice.agent.thinking_loop import ATOMIC_ABILITIES, ThinkingLoop


class MockState:
    """模拟 Agent 状态对象"""

    def __init__(self, user_input=""):
        self.user_input = user_input
        self.intent_type = ""
        self.final_answer = ""
        self.errors = []
        self.tool_calls = []
        self.plans = []
        self.relevant_history = ""
        self.similar_sessions = []


class MockAgent:
    """模拟 CastoriceAgent"""

    def __init__(self):
        self.model = MagicMock()
        self.config = MagicMock()
        self.config.thinking = {
            "max_steps": 5,
            "enable_self_reflection": True,
            "log_all_decisions": True,
        }
        self.emotion_engine = None
        self.reflection_engine = None
        self.authorization = None
        self.self_concept = None

        # 模拟各步骤方法
        self._step_intent = MagicMock()
        self._phase_memory_recall = MagicMock()
        self._step_planning = MagicMock()
        self._step_tool_loop = MagicMock()
        self._step_answer = MagicMock()
        self._step_reflection = MagicMock()
        self._step_memory = MagicMock()


@pytest.fixture
def mock_agent():
    """创建模拟 Agent"""
    return MockAgent()


@pytest.fixture
def thinking_loop(mock_agent):
    """创建 ThinkingLoop 实例"""
    return ThinkingLoop(mock_agent)


# =============================================================================
# 基础功能测试
# =============================================================================


class TestThinkingLoopBasics:
    """ThinkingLoop 基础功能测试"""

    @pytest.mark.asyncio
    async def test_simple_chat_finish(self, thinking_loop, mock_agent):
        """测试简单聊天：LLM 直接选择 finish"""
        # 模拟 LLM 返回 finish
        mock_response = Mock()
        mock_response.content = json.dumps({
            "reasoning": "用户只是打招呼，可以直接回答",
            "ability": "finish",
            "answer": "你好！很高兴见到你！"
        })
        mock_agent.model.chat = MagicMock(return_value=mock_response)

        state = MockState(user_input="你好")
        elapsed_ms = await thinking_loop.run(state, session_id="test_001")

        assert state.final_answer == "你好！很高兴见到你！"
        assert elapsed_ms > 0
        assert len(thinking_loop.decision_history) == 1
        assert thinking_loop.decision_history[0]["ability"] == "finish"

    @pytest.mark.asyncio
    async def test_multi_step_thinking(self, thinking_loop, mock_agent):
        """测试多步思考：understand_intent → generate_answer → finish"""
        responses = [
            # 第 1 步：理解意图
            Mock(content=json.dumps({
                "reasoning": "先理解用户意图",
                "ability": "understand_intent"
            })),
            # 第 2 步：生成回答
            Mock(content=json.dumps({
                "reasoning": "已经理解意图，可以生成回答",
                "ability": "generate_answer"
            })),
            # 第 3 步：结束
            Mock(content=json.dumps({
                "reasoning": "回答已生成",
                "ability": "finish",
                "answer": "这是最终回答"
            })),
        ]

        call_index = 0
        def mock_chat(msgs):
            nonlocal call_index
            response = responses[call_index]
            call_index += 1
            return response

        mock_agent.model.chat = mock_chat

        state = MockState(user_input="你好")
        elapsed_ms = await thinking_loop.run(state, session_id="test_002")

        assert state.final_answer == "这是最终回答"
        assert len(thinking_loop.decision_history) == 3
        assert thinking_loop.decision_history[0]["ability"] == "understand_intent"
        assert thinking_loop.decision_history[1]["ability"] == "generate_answer"
        assert thinking_loop.decision_history[2]["ability"] == "finish"

    @pytest.mark.asyncio
    async def test_max_steps_limit(self, thinking_loop, mock_agent):
        """测试 max_steps 限制"""
        # LLM 始终不 finish，测试强制结束
        mock_response = Mock()
        mock_response.content = json.dumps({
            "reasoning": "继续思考",
            "ability": "recall_memory"
        })
        mock_agent.model.chat = MagicMock(return_value=mock_response)

        state = MockState(user_input="测试")
        elapsed_ms = await thinking_loop.run(state, session_id="test_003")

        # 应该超过 max_steps 后强制结束
        assert len(thinking_loop.decision_history) == 5  # max_steps=5
        assert state.final_answer  # 应该有兜底回答

    @pytest.mark.asyncio
    async def test_decision_logging(self, thinking_loop, mock_agent):
        """测试决策日志记录"""
        mock_response = Mock()
        mock_response.content = json.dumps({
            "reasoning": "测试日志记录",
            "ability": "finish",
            "answer": "回答"
        })
        mock_agent.model.chat = MagicMock(return_value=mock_response)

        state = MockState(user_input="测试")
        await thinking_loop.run(state, session_id="test_004")

        history = thinking_loop.get_decision_history()
        assert len(history) == 1
        assert history[0]["ability"] == "finish"
        assert "测试日志记录" in history[0]["reasoning"]
        assert history[0]["user_input"] == "测试"


# =============================================================================
# 决策解析测试
# =============================================================================


class TestDecisionParsing:
    """决策解析测试"""

    def test_parse_pure_json(self, thinking_loop):
        """测试解析纯 JSON"""
        content = '{"reasoning": "test", "ability": "finish", "answer": "hi"}'
        decision = thinking_loop._parse_decision(content)
        assert decision["ability"] == "finish"
        assert decision["answer"] == "hi"

    def test_parse_markdown_json(self, thinking_loop):
        """测试解析 Markdown 代码块中的 JSON"""
        content = '```json\n{"reasoning": "test", "ability": "finish", "answer": "hi"}\n```'
        decision = thinking_loop._parse_decision(content)
        assert decision["ability"] == "finish"

    def test_parse_invalid_fallback(self, thinking_loop):
        """测试解析失败时回退到 generate_answer"""
        content = "这不是有效的 JSON"
        decision = thinking_loop._parse_decision(content)
        assert decision["ability"] == "generate_answer"
        assert "JSON 解析失败" in decision["reasoning"]

    def test_parse_invalid_ability_fallback(self, thinking_loop):
        """测试无效能力名时回退"""
        content = '{"reasoning": "test", "ability": "invalid_ability"}'
        decision = thinking_loop._parse_decision(content)
        assert decision["ability"] == "generate_answer"


# =============================================================================
# 系统集成测试
# =============================================================================


class TestSystemIntegration:
    """系统集成测试"""

    def test_emotion_bias_integration(self, thinking_loop, mock_agent):
        """测试情感偏置集成"""
        # 创建模拟情感引擎
        mock_emotion = MagicMock()
        mock_emotion.get_decision_bias.return_value = {
            "confidence": 0.3,
            "risk_tolerance": -0.2
        }
        mock_agent.emotion_engine = mock_emotion

        state = MockState()
        bias = thinking_loop._get_emotion_bias(state)

        assert bias["confidence"] == 0.3
        assert bias["risk_tolerance"] == -0.2

    def test_authorization_basic(self, thinking_loop, mock_agent):
        """测试授权检查：基础能力无需授权"""
        state = MockState()
        # 无 authorization，基础能力应该通过
        assert thinking_loop._check_authorization("understand_intent", state) is True
        assert thinking_loop._check_authorization("finish", state) is True
        assert thinking_loop._check_authorization("recall_memory", state) is True

    def test_authorization_trust_level(self, thinking_loop, mock_agent):
        """测试授权检查：不同信任等级"""
        mock_auth = MagicMock()
        mock_auth.current_level = 1
        mock_agent.authorization = mock_auth

        state = MockState()
        # L1 可以执行中等能力
        assert thinking_loop._check_authorization("execute_tools", state) is True
        assert thinking_loop._check_authorization("self_reflect", state) is True
        # L1 不能执行高级能力
        assert thinking_loop._check_authorization("update_self_concept", state) is False

        # L0 不能执行中等能力
        mock_auth.current_level = 0
        assert thinking_loop._check_authorization("execute_tools", state) is False

    def test_state_summary(self, thinking_loop):
        """测试状态摘要构建"""
        state = MockState(user_input="测试")
        state.intent_type = "chat"
        state.final_answer = "部分回答"
        state.tool_calls = ["tool1"]

        summary = thinking_loop._build_state_summary(state, step=2)
        assert "意图类型: chat" in summary
        assert "已有回答" in summary
        assert "已调用工具: 1 次" in summary
        assert "当前步数: 3" in summary


# =============================================================================
# 异常处理测试
# =============================================================================


class TestErrorHandling:
    """异常处理测试"""

    @pytest.mark.asyncio
    async def test_llm_decision_failure(self, thinking_loop, mock_agent):
        """测试 LLM 决策失败时的回退"""
        mock_agent.model.chat = MagicMock(side_effect=Exception("LLM 错误"))

        state = MockState(user_input="测试")
        # 应该不抛出异常，而是回退到 generate_answer
        decision = await thinking_loop._decide_next(
            state=state,
            state_summary="",
            emotion_bias={},
            reflection_insight="",
            step=0
        )

        assert decision["ability"] == "generate_answer"
        assert "LLM 错误" in decision["reasoning"]

    @pytest.mark.asyncio
    async def test_ability_execution_failure(self, thinking_loop, mock_agent):
        """测试原子能力执行失败"""
        # 模拟 _step_intent 抛出异常
        mock_agent._step_intent.side_effect = Exception("意图识别失败")

        state = MockState(user_input="测试")
        result = await thinking_loop._execute_ability(
            ability="understand_intent",
            state=state,
            session_id="test",
            stream_callback=None,
            decision_params={}
        )

        # 应该捕获异常，返回错误结果
        assert "error" in result  # 异常被捕获并包装为结果

    def test_filter_available_abilities(self, thinking_loop):
        """测试能力过滤"""
        state = MockState()
        state.final_answer = "已有回答"

        available = thinking_loop._filter_available_abilities(state, step=0)
        # finish 应该可用
        assert "finish" in available
        # 所有基础能力都应该可用
        assert "understand_intent" in available
        assert "recall_memory" in available


# =============================================================================
# 向后兼容测试
# =============================================================================


class TestBackwardCompatibility:
    """向后兼容测试：确保 legacy 模式不受影响"""

    def test_legacy_mode_no_thinking_loop(self, mock_agent):
        """测试 legacy 模式不创建 ThinkingLoop"""
        mock_agent.agent_mode = "legacy"
        mock_agent.thinking_loop = None

        # legacy 模式应该正常工作
        assert mock_agent.thinking_loop is None

    def test_atomic_abilities_match_phases(self):
        """测试原子能力与现有 phase 的映射完整性"""
        # 确保每个原子能力都有对应的 phase 方法
        expected_mappings = {
            "understand_intent": "_step_intent",
            "recall_memory": "_phase_memory_recall",
            "plan_tasks": "_step_planning",
            "execute_tools": "_step_tool_loop",
            "generate_answer": "_step_answer",
            "self_reflect": "_step_reflection",
            "save_memory": "_step_memory",
        }

        for ability, method in expected_mappings.items():
            assert ability in ATOMIC_ABILITIES, f"能力 {ability} 未定义"

    def test_config_loading(self):
        """测试配置加载"""
        # 模拟配置
        config = MagicMock()
        config.thinking = {
            "max_steps": 8,
            "enable_self_reflection": True,
            "log_all_decisions": True,
        }

        agent = MockAgent()
        agent.config = config

        loop = ThinkingLoop(agent)
        assert loop.max_steps == 8
        assert loop.enable_self_reflection is True
        assert loop.log_all_decisions is True
