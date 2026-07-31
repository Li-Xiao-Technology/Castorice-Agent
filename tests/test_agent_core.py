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


# ============================================================
# CastoriceAgent 核心测试（初始化 / arun 端到端 / 工具调用 / 安全 / 异常）
# ============================================================

import asyncio
from unittest.mock import MagicMock

import pytest

from castorice.agent.core import State, CastoriceAgent
from castorice.agent.common import MAX_TOOL_ROUNDS
from castorice.model_adapter.common import ChatMessage, ChatResponse, ToolCall


def _stub_agent_subsystems(agent):
    """把会触发 LLM 调用或复杂 IO 的子系统替换为 MagicMock，确保 arun 不依赖真实模型。

    保留 tools / model / config / 记忆 / 用户画像不变，仅替换：
    emotion_engine / self_awareness / thinking_strategy / dialogue_strategy /
    unified_memory / task_planner / workflow_selector / motivation_system
    """
    agent.emotion_engine = MagicMock()
    agent.emotion_engine.enabled = False
    agent.emotion_engine.derive_motivations.return_value = []
    agent.emotion_engine.update.return_value = {
        "agent_pad_delta": [0.0, 0.0, 0.0],
        "user_emotion_valence": "neutral",
        "is_significant_event": False,
    }
    agent.emotion_engine.get_emotion_prompt.return_value = ""
    agent.emotion_engine.get_personality_prompt.return_value = ""
    agent.emotion_engine.get_decision_bias.return_value = {}
    agent.emotion_engine.get_workflow_adjustment.return_value = {"skip_reflection": False}
    agent.emotion_engine.should_refuse_tool.return_value = (False, "")
    agent.emotion_engine.get_state_snapshot.return_value = {"enabled": False}
    agent.emotion_engine._state = None

    agent.self_awareness = MagicMock()
    agent.self_awareness.reset_context_counter.return_value = None
    agent.self_awareness.can_handle.return_value = (True, 0.9, "mock")
    agent.self_awareness.should_compress_context.return_value = (False, "")
    agent.self_awareness.should_slow_down.return_value = (False, {"fatigue_score": 0.0, "recommended_delay_ms": 0})
    agent.self_awareness.record_llm_call.return_value = None
    agent.self_awareness.record_tool_call.return_value = None
    agent.self_awareness.record_task.return_value = None

    agent.thinking_strategy = MagicMock()
    agent.thinking_strategy.select.return_value = ("conversational", "")
    agent.thinking_strategy.get_strategy_name.return_value = "conversational"

    agent.dialogue_strategy = MagicMock()
    agent.dialogue_strategy.adjust_prompt.return_value = {}

    agent.unified_memory = MagicMock()
    agent.unified_memory.recall.return_value = {"summary": "", "experiences": []}
    agent.unified_memory._find_similar_sessions.return_value = []

    agent.task_planner = MagicMock()
    agent.task_planner._estimate_complexity.return_value = "easy"

    agent.workflow_selector = MagicMock()
    agent.workflow_selector.select.return_value = ["intent", "tool_loop", "answer", "memory"]

    agent.motivation_system = MagicMock()
    agent.motivation_system.is_awaiting_proactive_feedback.return_value = False

    # 关闭安全检查（避免 tool.echo 被 L5 默认拒绝阻止工具执行测试）
    agent._is_authorization_enabled = MagicMock(return_value=False)
    agent._is_pattern_detection_enabled = MagicMock(return_value=False)

    # 元认知：返回高置信度结果，避免 postprocessing 追加"把握不足"提示
    agent.metacognition = MagicMock()
    _conf = MagicMock()
    _conf.overall_score = 0.95
    _conf.hallucination_risk = "low"
    _quality = MagicMock()
    _quality.score = 90.0
    agent.metacognition.reflect.return_value = {
        "confidence": _conf,
        "consistency": {"consistent": True},
        "quality": _quality,
        "should_reconsider": False,
        "improvements": [],
    }


class TestAgentInitialization:
    """CastoriceAgent 初始化测试：验证各子系统正确装配。"""

    def test_agent_constructs_without_error(self, mock_agent):
        """Agent 实例化不抛异常。"""
        assert isinstance(mock_agent, CastoriceAgent)

    def test_tools_registered(self, mock_agent):
        """工具按 name 注册到 self.tools 字典。"""
        assert "echo" in mock_agent.tools
        assert mock_agent.tools["echo"] is mock_agent.tools_list[0]

    def test_model_adapter_assigned(self, mock_agent):
        """model_adapter 正确赋值。"""
        assert mock_agent.model is not None

    def test_runtime_config_read_from_dict(self, mock_agent):
        """runtime 配置从 dict 正确读取（max_iterations / enable_reflection）。"""
        assert mock_agent.max_iterations == 5
        assert mock_agent.enable_reflection is False
        assert mock_agent.enable_skill_generation is False

    def test_evolution_systems_disabled(self, mock_agent):
        """self_evolving.enabled=False 时经历流/自我概念/反思引擎为 None。"""
        assert mock_agent._evolve_enabled is False
        assert mock_agent.experience_journal is None
        assert mock_agent.self_concept is None
        assert mock_agent.reflection_engine is None

    def test_emotion_engine_initialized(self, mock_agent):
        """情感引擎实例化（即使 enabled=False 也创建对象，仅运行时跳过 IO）。"""
        assert mock_agent.emotion_engine is not None

    def test_layers_aggregator_built(self, mock_agent):
        """SystemLayers 聚合对象正确构建，包含 4 层。"""
        assert mock_agent.layers is not None
        assert mock_agent.layers.cognitive_layer is not None
        assert mock_agent.layers.planning_layer is not None
        assert mock_agent.layers.memory_layer is not None
        assert mock_agent.layers.evolution_layer is not None

    def test_session_locks_initialized(self, mock_agent):
        """会话锁字典与保护锁已初始化。"""
        assert hasattr(mock_agent, "_session_locks")
        assert isinstance(mock_agent._session_locks, dict)
        assert mock_agent._session_locks_guard is not None


class TestSecuritySystemInit:
    """安全子系统初始化测试：渐进授权、自我保护、实验沙盒。"""

    def test_progressive_authorization_initialized(self, mock_agent):
        """ProgressiveAuthorization 实例化，初始信任等级来自配置（trust_level=1）。"""
        from castorice.security.authorization import ProgressiveAuthorization
        assert isinstance(mock_agent.authorization, ProgressiveAuthorization)
        assert mock_agent.authorization.current_level == 1

    def test_self_protection_initialized(self, mock_agent):
        """SelfProtectionSystem 实例化，保护处于活动状态。"""
        from castorice.security.self_protection import SelfProtectionSystem
        assert isinstance(mock_agent.self_protection, SelfProtectionSystem)
        assert mock_agent.self_protection.is_protection_active() is True

    def test_experimental_sandbox_disabled_when_config_says_so(self, mock_agent):
        """sandbox_enabled=False 时 experimental_sandbox 为 None（不实例化沙盒）。"""
        assert mock_agent.experimental_sandbox is None

    def test_experimental_sandbox_enabled_when_config_allows(
        self, mock_model_adapter, mock_tool, mock_short_term_memory,
        mock_long_term_memory, mock_skill_memory, mock_user_profile,
        mock_agent_config, monkeypatch, tmp_path
    ):
        """sandbox_enabled=True 时 ExperimentalSandbox 实例化。"""
        monkeypatch.chdir(tmp_path)
        # 包装 EmotionEngine 以兼容 experience_journal kwarg
        import castorice.emotion as _emotion_mod

        class _Wrapper(_emotion_mod.EmotionEngine):
            def __init__(self, *a, **kw):
                kw.pop("experience_journal", None)
                super().__init__(*a, **kw)

        monkeypatch.setattr(_emotion_mod, "EmotionEngine", _Wrapper)
        # 覆盖 runtime dict 开启沙盒
        mock_agent_config.runtime["security"]["sandbox_enabled"] = True
        from castorice.agent.core import CastoriceAgent
        from castorice.experimental.sandbox import ExperimentalSandbox
        agent = CastoriceAgent(
            model_adapter=mock_model_adapter,
            tools=[mock_tool],
            short_term_memory=mock_short_term_memory,
            long_term_memory=mock_long_term_memory,
            skill_memory=mock_skill_memory,
            user_profile=mock_user_profile,
            config=mock_agent_config,
        )
        assert isinstance(agent.experimental_sandbox, ExperimentalSandbox)

    def test_authorization_is_allowed_for_low_trust_op(self, mock_agent):
        """L1 信任等级允许 L0/L1 操作。"""
        allowed, _ = mock_agent.authorization.is_allowed("long_term.read")
        assert allowed is True

    def test_authorization_denies_high_trust_op(self, mock_agent):
        """L1 信任等级拒绝 L4+ 操作（如 terminal）。"""
        allowed, reason = mock_agent.authorization.is_allowed("tool.terminal")
        assert allowed is False
        assert "信任等级" in reason


@pytest.mark.asyncio
class TestArunEndToEnd:
    """arun() 端到端测试：mock 模型返回简单回答，验证主循环正常完成。"""

    async def test_arun_returns_state_with_final_answer(self, mock_agent):
        """arun 完成 → State.success=True 且 final_answer 非空。"""
        _stub_agent_subsystems(mock_agent)
        # 模型返回纯文本回答（无 tool_calls）
        # 注意：必须清除 side_effect，否则 return_value 不生效
        mock_agent.model.supports_tools = False
        mock_agent.model.chat.side_effect = None
        mock_agent.model.chat.return_value = ChatResponse(
            content='{"action": "answer", "answer": "你好，我是 Castorice"}',
            model="mock",
        )

        state = await mock_agent.arun("你好", session_id="test-session")

        assert isinstance(state, State)
        assert state.session_id == "test-session"
        assert state.final_answer  # 非空
        assert state.success is True
        # 不应有错误
        assert state.errors == []

    async def test_arun_records_user_input(self, mock_agent):
        """arun 把 user_input 写入 State。"""
        _stub_agent_subsystems(mock_agent)
        mock_agent.model.supports_tools = False
        mock_agent.model.chat.side_effect = None
        mock_agent.model.chat.return_value = ChatResponse(
            content='{"action": "answer", "answer": "ok"}', model="mock",
        )
        state = await mock_agent.arun("测试输入", session_id="s1")
        assert state.user_input == "测试输入"

    async def test_arun_session_lock_isolated(self, mock_agent):
        """不同 session_id 使用独立锁，同 session_id 复用同一锁。"""
        _stub_agent_subsystems(mock_agent)
        mock_agent.model.supports_tools = False
        mock_agent.model.chat.side_effect = None
        mock_agent.model.chat.return_value = ChatResponse(
            content='{"action": "answer", "answer": "ok"}', model="mock",
        )
        await mock_agent.arun("hi", session_id="sess-a")
        await mock_agent.arun("hi", session_id="sess-b")
        # 两个 session 应有各自的锁
        assert "sess-a" in mock_agent._session_locks
        assert "sess-b" in mock_agent._session_locks
        assert mock_agent._session_locks["sess-a"] is not mock_agent._session_locks["sess-b"]


@pytest.mark.asyncio
class TestToolCall:
    """工具调用测试：mock 模型返回 tool_call，验证 tool_loop 执行工具。"""

    async def test_tool_invoked_when_model_returns_tool_call(self, mock_agent):
        """模型通过 Function Calling 返回 tool_call → 工具被执行，结果写入 state.tool_calls。"""
        _stub_agent_subsystems(mock_agent)
        # 让 echo 工具的 invoke 可被观测
        echo_tool = mock_agent.tools["echo"]
        call_log = []
        original_invoke = echo_tool.invoke

        def _spy_invoke(args):
            call_log.append(args)
            return original_invoke(args)

        echo_tool.invoke = _spy_invoke

        # 第一轮返回 tool_call，第二轮返回最终答案（native_fc 模式下 content 即为最终回答）
        tc = ToolCall(id="tc_1", name="echo", arguments={"text": "hello"})
        first_resp = ChatResponse(content="", tool_calls=[tc], model="mock")
        second_resp = ChatResponse(content="done", model="mock")
        mock_agent.model.supports_tools = True
        mock_agent.model.chat_with_tools.side_effect = [first_resp, second_resp]

        state = State(user_input="请回显 hello", session_id="t1")
        state.available_tools_desc = "- echo: 回显输入文本"
        state.history_messages = []

        mock_agent._step_tool_loop(state)

        # 工具被调用一次
        assert len(call_log) == 1
        assert call_log[0] == {"text": "hello"}
        # state.tool_calls 记录了执行结果
        assert len(state.tool_calls) == 1
        assert state.tool_calls[0]["tool_name"] == "echo"
        # 最终答案存在
        assert state.final_answer == "done"
        assert state.success is True

    async def test_unknown_tool_returns_error_feedback(self, mock_agent):
        """模型调用不存在的工具 → 返回模糊匹配提示，不抛异常。"""
        _stub_agent_subsystems(mock_agent)
        tc = ToolCall(id="tc_x", name="nonexistent_tool", arguments={})
        first_resp = ChatResponse(content="", tool_calls=[tc], model="mock")
        second_resp = ChatResponse(content="最终回答", model="mock")
        mock_agent.model.supports_tools = True
        mock_agent.model.chat_with_tools.side_effect = [first_resp, second_resp]

        state = State(user_input="用不存在的工具", session_id="t2")
        state.available_tools_desc = "- echo: 回显"
        state.history_messages = []

        mock_agent._step_tool_loop(state)

        # 不应抛异常，且最终能得到答案（native_fc 模式下 final_text = content）
        assert state.final_answer == "最终回答"

    async def test_tool_loop_respects_max_rounds(self, mock_agent):
        """模型持续返回 tool_call → 达到 MAX_TOOL_ROUNDS 后退出循环。"""
        _stub_agent_subsystems(mock_agent)
        # 每轮都返回同一个 tool_call，永不给最终答案
        tc = ToolCall(id="tc_loop", name="echo", arguments={"text": "loop"})
        loop_resp = ChatResponse(content="", tool_calls=[tc], model="mock")
        mock_agent.model.supports_tools = True
        mock_agent.model.chat_with_tools.return_value = loop_resp

        state = State(user_input="死循环测试", session_id="t3")
        state.available_tools_desc = "- echo: 回显"
        state.history_messages = []

        mock_agent._step_tool_loop(state)

        # 应该有 MAX_TOOL_ROUNDS 轮调用
        assert mock_agent.model.chat_with_tools.call_count == MAX_TOOL_ROUNDS
        # 循环结束后应有兜底 final_answer
        assert state.final_answer  # 非空


@pytest.mark.asyncio
class TestExceptionPath:
    """异常路径测试：mock 模型抛异常，验证 Agent 正确处理。"""

    async def test_model_raises_exception_is_caught(self, mock_agent):
        """模型 chat 抛异常 → 异常被捕获写入 state.errors，不向上传播。"""
        _stub_agent_subsystems(mock_agent)
        mock_agent.model.supports_tools = False
        mock_agent.model.chat.side_effect = RuntimeError("model unavailable")

        state = State(user_input="触发异常", session_id="e1")
        state.available_tools_desc = "- echo: 回显"
        state.history_messages = []

        # _step_tool_loop 内部 try/except 捕获异常，写入 state.errors
        mock_agent._step_tool_loop(state)

        # 异常应被捕获，写入 errors
        assert any("model unavailable" in e for e in state.errors)
        # 工具循环异常时不设置 final_answer，由 _step_answer 处理
        # 所以这里 final_answer 应为空
        assert state.final_answer == ""

    async def test_arun_completes_when_tool_loop_errors(self, mock_agent):
        """工具循环出错 → arun 仍能完成，state.success=False。"""
        _stub_agent_subsystems(mock_agent)
        mock_agent.model.supports_tools = True
        mock_agent.model.chat_with_tools.side_effect = RuntimeError("connection lost")

        state = await mock_agent.arun("触发错误", session_id="e2")

        assert isinstance(state, State)
        # 有错误记录
        assert len(state.errors) > 0
        # success 应为 False（因为 errors 非空）
        assert state.success is False

    async def test_arun_handles_short_term_memory_failure(self, mock_agent):
        """短期记忆加载失败 → 异常被捕获，arun 仍继续。"""
        _stub_agent_subsystems(mock_agent)
        mock_agent.short_term.get_session.side_effect = RuntimeError("db locked")
        mock_agent.model.supports_tools = False
        mock_agent.model.chat.side_effect = None
        mock_agent.model.chat.return_value = ChatResponse(
            content='{"action": "answer", "answer": "still ok"}', model="mock",
        )

        # 不应抛异常
        state = await mock_agent.arun("hi", session_id="e3")
        assert state.final_answer == "still ok"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])