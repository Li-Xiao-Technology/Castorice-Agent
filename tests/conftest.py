"""
pytest 共享 fixture 模块

提供跨测试文件复用的常用 fixture：
- temp_dir: 临时目录（自动清理）
- mock_config: 模拟配置对象
- mock_model_adapter: 模拟模型适配器（返回可预测响应）
- mock_emotion_engine: 模拟情感引擎
- mock_tool: 模拟工具（echo 实现）
- agent_runtime_dict: 真实 dict 形式的 Agent runtime 配置（关闭文件 IO）
- mock_agent_config: 包装了 dict runtime 的 Agent 测试配置
- mock_short_term_memory / mock_long_term_memory / mock_skill_memory / mock_user_profile:
  CastoriceAgent 子系统 mock
- mock_agent: 完整初始化的 CastoriceAgent 实例（依赖均被 mock）
"""

import os
import tempfile
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from castorice.emotion import EmotionEngine, EmotionState
from castorice.model_adapter.common import ChatMessage, ChatResponse
from castorice.tools.base_tools import Tool


@pytest.fixture(autouse=True)
def _reset_lazy_singletons():
    """每个测试前后重置懒加载单例，避免跨测试 cwd 变化导致 FileNotFoundError。

    审计日志/告警管理器等单例在首次调用时创建相对路径目录（如
    ./castorice_data/audit_logs），当后续测试通过 monkeypatch.chdir 切换 cwd 后，
    残留单例的 log_dir 仍指向旧路径，导致 open() 失败。此处统一在每条用例
    前后重置两个模块的单例引用，确保下一次 _get_xxx() 重新创建。
    """
    import castorice.agent.common as _agent_common
    import castorice.security.audit_log as _audit_mod

    _agent_common._audit_logger = None
    _agent_common._alert_manager_ref = None
    _audit_mod._audit_logger = None
    yield
    _agent_common._audit_logger = None
    _agent_common._alert_manager_ref = None
    _audit_mod._audit_logger = None


@pytest.fixture
def temp_dir():
    """创建临时目录，测试结束后自动清理。

    用于替代各测试文件中重复的 `with tempfile.TemporaryDirectory() as tmpdir:`
    模式，统一临时目录的生命周期管理。
    """
    with tempfile.TemporaryDirectory() as d:
        yield d


@pytest.fixture
def mock_config():
    """返回模拟配置对象，覆盖常用字段。

    匹配 castorice.config.Config 的常用访问路径（如 cfg.llm.provider、
    cfg.agent.name 等），避免测试中加载真实 .env / yaml。
    """
    config = MagicMock()
    # LLM 配置
    config.llm.provider = "openai"
    config.llm.temperature = 0.7
    config.llm.max_tokens = 4096
    config.llm.timeout = 60
    config.llm.openai.api_key = "test-key"
    config.llm.openai.model = "gpt-4o-mini"
    config.llm.openai.base_url = "https://api.openai.com/v1"
    # Anthropic / Gemini / Qwen 占位
    config.llm.anthropic.api_key = ""
    config.llm.gemini.api_key = ""
    config.llm.qwen.api_key = ""
    # Agent 配置
    config.agent.name = "Castorice"
    config.agent.enabled = True
    config.agent.max_iterations = 10
    # Memory 配置
    config.memory.short_term_capacity = 50
    config.memory.long_term.backend = None
    # Runtime 配置
    config.runtime.debug = False
    config.runtime.log_level = "INFO"
    # Tools 配置
    config.tools.enabled = True
    return config


@pytest.fixture
def mock_model_adapter():
    """模拟模型适配器，返回可预测的 ChatResponse。

    - chat(): 回显最后一条 user 消息内容（前缀 "echo: "）
    - chat_stream(): 返回固定分片流
    """
    adapter = MagicMock()
    adapter.provider = "mock"
    adapter.temperature = 0.7
    adapter.max_tokens = 4096
    adapter.timeout = 60

    def _echo_chat(messages):
        # 回显最后一条 user 消息
        last_user = None
        for m in reversed(messages):
            if getattr(m, "role", None) == "user":
                last_user = m
                break
        if last_user and getattr(last_user, "content", None):
            return ChatResponse(
                content=f"echo: {last_user.content}",
                model="mock-model",
            )
        return ChatResponse(content="mock response", model="mock-model")

    adapter.chat.side_effect = _echo_chat
    adapter.chat_stream.return_value = iter(["mock ", "stream ", "response"])
    return adapter


@pytest.fixture
def mock_emotion_engine():
    """模拟情感引擎，返回可预测的默认状态。

    使用纯 MagicMock 配置常用方法返回值，避免触发真实 LLM 调用或文件 IO。
    """
    engine = MagicMock()
    engine.enabled = True
    state = EmotionState()
    engine.load.return_value = state
    engine._state = state
    engine.get_emotion_prompt.return_value = ""
    engine.should_refuse_tool.return_value = (False, "")
    engine.update.return_value = {
        "agent_pad_delta": [0.0, 0.0, 0.0],
        "user_emotion_valence": "neutral",
        "is_significant_event": False,
    }
    engine.get_workflow_adjustment.return_value = {"skip_reflection": False}
    engine.derive_motivations.return_value = []
    engine.save.return_value = None
    engine.get_personality_prompt.return_value = ""
    return engine


@pytest.fixture
def mock_tool():
    """模拟工具：echo 实现（回显输入文本）。"""
    def _echo(text: str = "") -> str:
        return text

    return Tool(name="echo", description="回显输入文本（测试用）", func=_echo)


# ============================================================
# CastoriceAgent 测试专用 fixtures
# ============================================================

@pytest.fixture
def agent_runtime_dict(tmp_path):
    """真实 dict 形式的 runtime 配置，关闭文件 IO 避免测试副作用。

    通过 dict（而非 MagicMock）让 CastoriceAgent.__init__ 中的
    isinstance(runtime_cfg, dict) 判定成立，从而读取以下配置：
    - self_evolving.enabled = False  → 跳过 ExperienceJournal/SelfConcept/ReflectionEngine
    - security.sandbox_enabled = False → 跳过 ExperimentalSandbox
    - emotion.enabled = False + storage_path = "" → 不读写情绪状态文件
    - state_persistence.enabled = False → 不写状态快照
    """
    return {
        "max_iterations": 5,
        "enable_reflection": False,
        "enable_skill_generation": False,
        "self_evolving": {"enabled": False},
        "security": {
            "trust_level": 1,
            "sandbox_enabled": False,
            "backup_dir": str(tmp_path / "backups"),
        },
        "emotion": {"enabled": False, "storage_path": ""},
        "state_persistence": {"enabled": False},
    }


@pytest.fixture
def mock_agent_config(mock_config, agent_runtime_dict, tmp_path):
    """CastoriceAgent 测试用 config：在 mock_config 基础上覆盖 runtime 为真实 dict。

    同时将 workflows 设置为空 dict（让 DynamicWorkflowSelector 使用预设工作流）。
    """
    # 让 config.runtime 返回真实 dict（而非 MagicMock）
    mock_config.runtime = agent_runtime_dict
    # workflows 必须是 dict 才能进入 DynamicWorkflowSelector 的解析分支
    mock_config.workflows = {}
    return mock_config


@pytest.fixture
def mock_short_term_memory():
    """模拟短期记忆：返回空历史，支持会话创建/列表/摘要更新。"""
    m = MagicMock()
    m.get_history.return_value = []
    m.get_session.return_value = None
    m.create_session.return_value = "test-session"
    m.list_sessions.return_value = []
    m.update_summary.return_value = None
    m.add_message.return_value = None
    m.delete_session.return_value = None
    return m


@pytest.fixture
def mock_long_term_memory():
    """模拟长期记忆：标记为不可用，避免触发 ChromaDB 真实调用。"""
    m = MagicMock()
    m.is_available = False
    m.count.return_value = 0
    m.search.return_value = []
    m.get_recent.return_value = []
    m.add.return_value = None
    m.delete.return_value = None
    m.clear.return_value = None
    m.cleanup_old_memories.return_value = 0
    return m


@pytest.fixture
def mock_skill_memory():
    """模拟技能记忆：match 返回空列表，list_all 返回空列表。"""
    m = MagicMock()
    m.match.return_value = []
    m.list_all.return_value = []
    m.find_by_name.return_value = None
    m.add_or_update.return_value = None
    return m


@pytest.fixture
def mock_user_profile():
    """模拟用户画像：to_prompt_context 返回空字符串，get/set/add_to_list 均为 no-op。"""
    m = MagicMock()
    m.to_prompt_context.return_value = ""
    m.get.return_value = ""
    m.set.return_value = None
    m.add_to_list.return_value = None
    m.record_interaction.return_value = None
    return m


@pytest.fixture
def mock_agent(mock_model_adapter, mock_tool, mock_short_term_memory,
              mock_long_term_memory, mock_skill_memory, mock_user_profile,
              mock_agent_config, monkeypatch, tmp_path):
    """完整初始化的 CastoriceAgent 实例。

    - 切换 cwd 到 tmp_path，避免相对路径副作用落到项目目录
    - 所有外部依赖（LLM、记忆、技能库、用户画像）均为 mock
    - 关闭自我进化/沙盒/状态持久化等文件 IO 子系统
    - 兼容源码中 EmotionEngine(..., experience_journal=...) 的调用签名
      （源码 bug：内置 EmotionEngine.__init__ 不接受 experience_journal，
       此处用包装类吸收该 kwarg，避免 TypeError 阻塞测试）
    """
    # 切换 cwd，让残留的相对路径副作用（如 ./castorice_data/immune_memory.json）落到 tmp_path
    monkeypatch.chdir(tmp_path)

    # 包装内置 EmotionEngine，使其接受源码传入的 experience_journal kwarg
    import castorice.emotion as _emotion_mod

    class _EmotionEngineWrapper(_emotion_mod.EmotionEngine):
        def __init__(self, *args, **kwargs):
            # 源码可能传入 experience_journal，但内置 EmotionEngine 不接受该参数
            kwargs.pop("experience_journal", None)
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(_emotion_mod, "EmotionEngine", _EmotionEngineWrapper)

    from castorice.agent.core import CastoriceAgent
    agent = CastoriceAgent(
        model_adapter=mock_model_adapter,
        tools=[mock_tool],
        short_term_memory=mock_short_term_memory,
        long_term_memory=mock_long_term_memory,
        skill_memory=mock_skill_memory,
        user_profile=mock_user_profile,
        config=mock_agent_config,
    )
    return agent
