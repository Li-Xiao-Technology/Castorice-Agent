"""
自研 Agent 主循环 (CastoriceAgent)

复刻 Hermes Agent 架构，彻底移除 LangGraph：
- 手写主循环：阶段化执行
- LLM 驱动工具调用：让模型决定用哪个工具、传什么参数
- 状态对象：State 数据类管理运行时数据
"""

import asyncio
import json
import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from castorice.model_adapter import ChatMessage, ModelAdapter, ToolCall
from castorice.config import set_config
from castorice.metacognition import Metacognition as _BuiltinMetacognition
from castorice.self_awareness import SelfAwareness
from castorice.self_organization import (
    TaskPlanner, TaskPlan, SubTask,
    DynamicWorkflowSelector, ErrorRecoveryStrategy,
    TaskExecutor, ThinkingStrategySelector, DialogueStrategy,
)
from castorice.utils import extract_json
from castorice.metrics import Timer, get_metrics
from castorice.state_persistence import StatePersistence
from .common import logger, _get_alert_manager
from .prompt_builder import PromptBuilderMixin
from .tool_loop import ToolLoopMixin
from .memory_ops import MemoryOpsMixin
from .postprocessing import PostprocessingMixin
from .workflow_steps import WorkflowStepsMixin
from .silent_round import SilentRoundMixin
from .system_layers import (SystemLayers, CognitiveLayer, PlanningLayer,
                             MemoryLayer, EvolutionLayer)

# 自我进化系统
from castorice.experience_journal import ExperienceJournal, set_experience_journal
from castorice.self_concept import SelfConcept, set_self_concept
from castorice.emotion import EmotionEngine
from castorice.reflection import ReflectionEngine, ActionQueue

# 安全系统
from castorice.security.authorization import ProgressiveAuthorization, set_authorization
from castorice.security.self_protection import SelfProtectionSystem, set_self_protection
from castorice.security.file_guard import FileWriteGuard, set_file_guard
from castorice.security.pattern_detector import PatternDetector, set_pattern_detector
from castorice.security.rollback import RollbackManager, set_rollback_manager
from castorice.security.audit_log import AuditLogger, set_audit_logger
from castorice.experimental.sandbox import ExperimentalSandbox

# 记忆系统
from castorice.memory.intent_tracker import IntentTracker
from castorice.memory.unified_recall import UnifiedMemoryRecall
from castorice.memory.autobiographical import AutobiographicalMemory

# 工具学习与动机
from castorice.tool_learning import ToolCallMemory, set_tool_memory
from castorice.motivation import IntrinsicMotivation

# 社交关系
from castorice.social_relation import SocialRelationManager

# 任务3.4: 优先使用独立 SDK 包（castorice-emotion），未安装时回退内置实现
# SDK 安装后可享受独立更新，无需升级主项目
try:
    from castorice_emotion import EmotionEngine as _SdkEmotionEngine
    from castorice_emotion import Metacognition as _SdkMetacognition
    _USING_EMOTION_SDK = True
    logger_emotion_source = "castorice-emotion SDK"
except ImportError:
    _USING_EMOTION_SDK = False
    logger_emotion_source = "内置实现"


@dataclass
class State:
    """Agent 运行时状态（替代 LangGraph 状态传递）"""
    user_input: str = ""
    session_id: str = ""

    # 意图与规划
    intent_type: str = ""              # chat / task
    confidence: float = 1.0
    matched_skill_id: Optional[str] = None
    execution_plan: str = ""
    task_plan: Optional[Any] = None  # 任务规划结果（子任务列表）
    task_complexity: str = "medium"    # 任务复杂度：easy / medium / hard

    # 工具执行
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    current_observation: str = ""

    # 结果
    final_answer: str = ""
    success: bool = False
    errors: List[str] = field(default_factory=list)

    # 反思
    reflection_summary: str = ""
    improvement_suggestions: List[str] = field(default_factory=list)
    skill_to_generate: Optional[Dict[str, Any]] = None

    # 上下文
    user_profile_context: str = ""
    relevant_history: str = ""           # 长期记忆（跨会话）
    # 短期记忆已通过 history_messages 注入，不再使用独立的 context 字段
    history_messages: List[Any] = field(default_factory=list)  # P0-1: 原始历史消息（ChatMessage 列表，用于多轮上下文注入）
    relevant_experiences: str = ""       # P1.1: 经历流实时注入（与当前话题相关的历史经历）
    available_tools_desc: str = ""

    # 自组织/元认知增强
    thinking_strategy: str = "analytical"  # 思维策略
    thinking_strategy_prompt: str = ""     # 思维策略提示词
    dialogue_adjustment: str = ""          # 对话风格调整
    metacognition_result: Optional[Dict[str, Any]] = None  # 元认知反思结果
    previous_answers: List[str] = field(default_factory=list)  # 历史回答（用于一致性检测）

    # 情感引擎（L1+L2+L3+L4）
    emotion_state_prompt: str = ""  # L2 当前情绪状态提示（注入到 system prompt）
    emotion_care_hint: str = ""     # L4 主动关心提示（检测到近期负面事件时注入）
    emotion_detection: Optional[Dict[str, Any]] = None  # 当前轮用户情绪检测结果
    # L3: 情绪决策偏置——真正影响 Agent 的决策风格和行为方式
    emotion_decision_bias: Dict[str, float] = field(default_factory=dict)

    # P1.2: 反思信号（最近一次反思的结论，影响当前决策）
    recent_reflection_signal: str = ""
    # P1.3: 动机信号（由情感推导的当前意图列表）
    current_motivations: List[str] = field(default_factory=list)
    # P2: 相似历史会话（跨会话记忆迁移）
    similar_sessions: List[Dict[str, Any]] = field(default_factory=list)
    # P2.5: 主动话题（正常对话中主动发起的延续话题）
    initiated_topic: str = ""


class CastoriceAgent(PromptBuilderMixin, ToolLoopMixin, MemoryOpsMixin,
                      PostprocessingMixin, WorkflowStepsMixin, SilentRoundMixin):
    """Castorice Agent 主循环"""

    def __init__(
        self,
        model_adapter: ModelAdapter,
        tools: List[Any],
        short_term_memory: Any,
        long_term_memory: Any,
        skill_memory: Any,
        user_profile: Any,
        config: Any,
    ):
        """
        初始化 Castorice Agent 的所有子系统。

        架构说明：
        - 子系统按逻辑分为 4 层，最终聚合到 self.layers (SystemLayers)
        - 同时保留 self.xxx 直接引用以保证向后兼容
        - 新代码推荐通过 self.layers.<layer>.<subsystem> 访问

        层结构：
          cognitive_layer  → 自我感知、元认知、思考策略、对话策略
          planning_layer   → 任务规划、任务执行、工作流选择
          memory_layer     → 短期记忆、长期记忆、统一检索、意图追踪、自传体、技能记忆
          evolution_layer  → 情感引擎、经历日志、自我概念、反思引擎、动机系统、行动队列、社会关系、工具学习
        """
        self.model = model_adapter
        self.tools = {t.name: t for t in tools}
        self.tools_list = tools
        self.short_term = short_term_memory
        self.long_term = long_term_memory
        self.skill_memory = skill_memory
        self.user_profile = user_profile
        self.config = config
        set_config(self.config)

        runtime_cfg = config.runtime if hasattr(config, "runtime") else {}
        self.max_iterations = runtime_cfg.get("max_iterations", 10) if isinstance(runtime_cfg, dict) else 10
        self.enable_reflection = runtime_cfg.get("enable_reflection", True) if isinstance(runtime_cfg, dict) else True
        self.enable_skill_generation = runtime_cfg.get("enable_skill_generation", True) if isinstance(runtime_cfg, dict) else True

        # 工作流模板配置
        self.workflows = config.workflows if hasattr(config, "workflows") else {}
        # P1-32: default_workflow 已删除——动态工作流选择器才是实际机制

        # ============================================================
        # L1: 自主思考循环（ThinkingLoop）
        # 当 agent_mode == "thinking" 时，Agent 自主决定执行顺序
        # ============================================================
        self.agent_mode = runtime_cfg.get("agent_mode", "legacy") if isinstance(runtime_cfg, dict) else "legacy"
        if self.agent_mode == "thinking":
            from .thinking_loop import ThinkingLoop
            self.thinking_loop = ThinkingLoop(self)
            logger.info("Agent 模式: thinking (自主思考)")
        else:
            self.thinking_loop = None
            logger.info("Agent 模式: legacy (预设流程)")

        # 自感知模块
        model_name = self._get_model_name(model_adapter)
        self.self_awareness = SelfAwareness(tools=tools, model_name=model_name)

        # 自组织模块
        self.task_planner = TaskPlanner(model_adapter, tools=tools)
        self.task_executor = TaskExecutor(tools=self.tools, model_adapter=model_adapter)
        self.workflow_selector = DynamicWorkflowSelector(config=config)
        self.thinking_strategy = ThinkingStrategySelector(model_adapter=model_adapter)  # P1.4: 注入 LLM
        self.dialogue_strategy = DialogueStrategy()

        # 元认知模块（任务3.4: 优先使用 SDK，未安装时用内置）
        self.metacognition = _SdkMetacognition() if _USING_EMOTION_SDK else _BuiltinMetacognition()

        # ============================================================
        # 自我进化系统（经历流 + 自我概念 + 反思引擎）
        # 参考 Generative Agents/MemGPT，Agent 自己塑造性格
        # ============================================================
        self._init_evolution_system(model_adapter, runtime_cfg)

        # ============================================================
        # P3: 持续学习与知识蒸馏（Continuous Learning）
        # 知识卡片抽取 + 睡眠机制 + 定时调度
        # ============================================================
        try:
            from castorice.continuous_learning import ContinuousLearningManager
            self.continuous_learning = ContinuousLearningManager(
                engine=self,
                experience_journal=self.experience_journal,
                llm_adapter=model_adapter,
            )
        except Exception as e:
            logger.debug(f"持续学习管理器初始化失败: {e}")
            self.continuous_learning = None

        # P0: 长期意图追踪系统（需要在 unified_memory 之前初始化）
        self.intent_tracker = IntentTracker()

        # P2.2: 统一记忆检索层（聚合长期记忆、经历流、自我概念、意图追踪）
        self.unified_memory = UnifiedMemoryRecall(
            long_term=self.long_term,
            short_term=self.short_term,
            experience_journal=self.experience_journal,
            self_concept=self.self_concept,
            intent_tracker=self.intent_tracker,
        )

        # P3.2: 工具调用自我学习
        self.tool_learning = ToolCallMemory()
        set_tool_memory(self.tool_learning)

        # P2.3: 内在动机系统（驱动主动行为）
        self.motivation_system = IntrinsicMotivation()

        # P1: 行动队列（反思-行动闭环）
        self.action_queue = ActionQueue()

        # S1: 社会关系网络
        self.social_relation = SocialRelationManager()

        # A1: 自传式记忆系统
        self.autobiographical = AutobiographicalMemory()

        # ============================================================
        # 安全系统（P3.5-P3.7）
        # ============================================================
        self._init_security_system(runtime_cfg)

        self.layers = SystemLayers(
            cognitive_layer=CognitiveLayer(
                self_awareness=self.self_awareness,
                metacognition=self.metacognition,
                thinking_strategy=self.thinking_strategy,
                dialogue_strategy=self.dialogue_strategy,
            ),
            planning_layer=PlanningLayer(
                task_planner=self.task_planner,
                task_executor=self.task_executor,
                workflow_selector=self.workflow_selector,
            ),
            memory_layer=MemoryLayer(
                short_term=self.short_term,
                long_term=self.long_term,
                unified_memory=self.unified_memory,
                intent_tracker=self.intent_tracker,
                autobiographical=self.autobiographical,
                skill_memory=self.skill_memory,
            ),
            evolution_layer=EvolutionLayer(
                emotion_engine=self.emotion_engine,
                experience_journal=self.experience_journal,
                self_concept=self.self_concept,
                reflection_engine=self.reflection_engine,
                motivation_system=self.motivation_system,
                action_queue=self.action_queue,
                social_relation=self.social_relation,
                tool_learning=self.tool_learning,
            ),
        )

        self._init_session_management(config, runtime_cfg)

        _state = self.emotion_engine._state
        p, a, d = (0.0, 0.0, 0.0)
        if _state is not None:
            p, a, d = _state.pleasure, _state.arousal, _state.dominance
        logger.info(
            f"自我进化系统已加载: evolve={self._evolve_enabled}, "
            f"emotion.enabled={self.emotion_engine.enabled}, "
            f"P={p:.2f}, A={a:.2f}, D={d:.2f}, "
            f"self_concept_empty={self.self_concept.is_empty() if self.self_concept else 'N/A'}"
        )

    def _init_evolution_system(self, model_adapter, runtime_cfg: dict) -> None:
        """初始化自我进化系统：经历流、自我概念、情感引擎、反思引擎。"""
        evolve_cfg = runtime_cfg.get("self_evolving", {}) if isinstance(runtime_cfg, dict) else {}
        self._evolve_enabled = evolve_cfg.get("enabled", True)
        evolve_enabled = self._evolve_enabled

        # 经历流（复用 ChromaDB 或独立 SQLite）
        journal_path = evolve_cfg.get("experience_journal_path", "./castorice_data/experiences.db")
        max_experiences = int(evolve_cfg.get("max_experiences", 10000))
        self.experience_journal = ExperienceJournal(
            db_path=journal_path, max_experiences=max_experiences,
        ) if evolve_enabled else None
        if self.experience_journal is not None:
            set_experience_journal(self.experience_journal)

        # 自我概念（Agent 自己读写的 Markdown 文档）
        sc_path = evolve_cfg.get("self_concept_path", "./castorice_data/self_concept.md")
        self.self_concept = SelfConcept(storage_path=sc_path) if evolve_enabled else None
        if self.self_concept is not None:
            set_self_concept(self.self_concept)

        # 情感引擎（自我进化版：LLM 推理 + 依赖注入）
        emotion_cfg = runtime_cfg.get("emotion", {}) if isinstance(runtime_cfg, dict) else {}
        if _USING_EMOTION_SDK:
            self.emotion_engine = _SdkEmotionEngine(
                storage_path=emotion_cfg.get("storage_path", "./castorice_data/emotion_state.json"),
                enabled=emotion_cfg.get("enabled", True),
                model_adapter=model_adapter,
                self_concept=self.self_concept,
            )
        else:
            from castorice.emotion import EmotionEngine
            self.emotion_engine = EmotionEngine(
                storage_path=emotion_cfg.get("storage_path", "./castorice_data/emotion_state.json"),
                enabled=emotion_cfg.get("enabled", True),
                model_adapter=model_adapter,
                self_concept=self.self_concept,
            )
        self.emotion_engine.load()

        # 反思引擎（定期+事件触发，更新自我概念）
        if evolve_enabled:
            self.reflection_engine = ReflectionEngine(
                model_adapter=model_adapter,
                experience_journal=self.experience_journal,
                self_concept=self.self_concept,
                reflection_interval_turns=int(evolve_cfg.get("reflection_interval_turns", 10)),
                reflection_confidence_threshold=float(evolve_cfg.get("reflection_llm_threshold", 0.4)),
            )
        else:
            self.reflection_engine = None

    def _init_security_system(self, runtime_cfg: dict) -> None:
        """初始化安全系统：渐进授权、自我保护、实验沙盒。"""
        security_cfg = runtime_cfg.get("security", {}) if isinstance(runtime_cfg, dict) else {}

        # P3.5: 渐进式授权系统（L0-L5 信任等级）
        self.authorization = ProgressiveAuthorization(
            initial_level=int(security_cfg.get("trust_level", 1)),
            promotion_threshold=int(security_cfg.get("promotion_threshold", 5)),
            demotion_threshold=int(security_cfg.get("demotion_threshold", 2)),
        )
        set_authorization(self.authorization)

        # P3.6: 自我保护系统（核心文件完整性验证、自毁检测、自动恢复）
        self.self_protection = SelfProtectionSystem(
            backup_dir=security_cfg.get("backup_dir", "./backups"),
        )
        set_self_protection(self.self_protection)

        # P3.8: 文件守卫（防止危险文件写入）
        self.file_guard = FileWriteGuard()
        set_file_guard(self.file_guard)

        # P3.9: 危险模式检测器（指令注入/越狱检测）
        self.pattern_detector = PatternDetector()
        set_pattern_detector(self.pattern_detector)

        # P3.4: 回滚管理器（任务失败时自动回滚）
        self.rollback_manager = RollbackManager()
        set_rollback_manager(self.rollback_manager)

        # P3.10: 审计日志（记录所有高权限操作）
        self.audit_logger = AuditLogger(
            log_dir=security_cfg.get("audit_log_dir", "./castorice_data/audit_logs"),
        )
        set_audit_logger(self.audit_logger)

        # P3.7: 实验沙盒（安全探索环境）
        sandbox_enabled = security_cfg.get("sandbox_enabled", True)
        if sandbox_enabled:
            self.experimental_sandbox = ExperimentalSandbox(
                main_code_path=security_cfg.get("sandbox_main_code_path", "./castorice"),
            )
        else:
            self.experimental_sandbox = None

        auth_status = self.authorization.get_status()
        logger.info(
            f"安全系统已加载: trust_level={auth_status.get('current_level', 'N/A')}, "
            f"self_protection={self.self_protection.is_protection_active()}, "
            f"sandbox_enabled={sandbox_enabled}"
        )

    def _init_session_management(self, config, runtime_cfg) -> None:
        """初始化会话管理：并发锁、缓存、状态持久化。"""
        # P1-5: L4 主动关心检索缓存
        self._emotion_care_cache: Dict[str, tuple] = {}
        self._emotion_care_cache_ttl = 300  # 5 分钟

        # P1-2: 按 session_id 分桶的并发锁
        self._session_locks: Dict[str, threading.Lock] = {}
        self._session_locks_last_used: Dict[str, float] = {}
        self._session_locks_guard = threading.Lock()
        self._session_locks_ttl = 1800  # 30 分钟

        # P2.3: 静默轮检测相关
        self._last_input_time: Dict[str, float] = {}
        self._quiet_round_enabled = True

        # 状态持久化
        try:
            runtime_cfg_dict = config.runtime if hasattr(config, "runtime") else {}
            state_persist_cfg = runtime_cfg_dict.get("state_persistence", {}) if isinstance(runtime_cfg_dict, dict) else {}
            self.state_persistence = StatePersistence(
                storage_dir=state_persist_cfg.get("storage_dir", "./castorice_data/states"),
                max_snapshots=state_persist_cfg.get("max_snapshots", 5),
            ) if state_persist_cfg.get("enabled", True) else None
        except (OSError, IOError, PermissionError, ValueError) as e:
            logger.warning(f"状态持久化初始化失败: {e}")
            self.state_persistence = None

    def reload_tools(self, tools: List[Any]) -> Dict[str, Any]:
        """
        热更新工具列表
        :param tools: 新的工具列表
        :return: 更新信息（新增、删除、保留的工具数量）
        """
        old_tool_names = set(self.tools.keys())
        new_tool_names = {t.name for t in tools}

        added = new_tool_names - old_tool_names
        removed = old_tool_names - new_tool_names
        kept = old_tool_names & new_tool_names

        self.tools = {t.name: t for t in tools}
        self.tools_list = tools

        if self.self_awareness:
            self.self_awareness.tools = tools

        if self.task_planner:
            self.task_planner.tools = tools

        if self.task_executor:
            self.task_executor.tools = self.tools

        logger.info(f"工具热更新完成 - 新增: {len(added)}, 删除: {len(removed)}, 保留: {len(kept)}")

        return {
            "added": list(added),
            "removed": list(removed),
            "kept": len(kept),
            "total": len(tools)
        }

    def _get_model_name(self, model_adapter: ModelAdapter) -> str:
        """从模型适配器获取模型名称"""
        try:
            cfg = model_adapter._get_provider_config()
            return cfg.get("model", "")
        except (AttributeError, TypeError, KeyError):
            return ""

    # ============================================================
    # 主循环（支持工作流模板）
    # ============================================================
    def run(self, user_input: str, session_id: str, workflow_name: str = None,
            stream_callback: Optional[Callable[[str], None]] = None) -> State:
        """执行一次完整任务闭环（同步版本，兼容原有调用）"""
        return asyncio.run(self.arun(user_input, session_id, workflow_name, stream_callback))

    async def arun(self, user_input: str, session_id: str, workflow_name: str = None,
                   stream_callback: Optional[Callable[[str], None]] = None) -> State:
        """执行一次完整任务闭环（异步版本，支持并发）"""
        # P1-2: 按 session_id 加锁，避免同一会话并发请求导致 PAD 状态/缓存竞态
        # 使用 threading.Lock 因为 run() 每次调用会创建新的事件循环，asyncio.Lock 会绑定到旧事件循环
        with self._session_locks_guard:
            lock = self._session_locks.get(session_id)
            if lock is None:
                lock = threading.Lock()
                self._session_locks[session_id] = lock
            self._session_locks_last_used[session_id] = time.time()
            # P1-1: 顺便清理过期的 session 锁（避免 _session_locks 字典无限膨胀）
            if len(self._session_locks) > 50:
                cutoff = time.time() - self._session_locks_ttl
                expired = [sid for sid, ts in self._session_locks_last_used.items() if ts < cutoff]
                cleaned = 0
                for sid in expired:
                    if sid == session_id:
                        continue
                    if not self._session_locks[sid].locked():
                        self._session_locks.pop(sid, None)
                        self._session_locks_last_used.pop(sid, None)
                        cleaned += 1
                if cleaned > 0:
                    logger.debug(f"P1-1 清理过期 session 锁: {cleaned} 个")
        with lock:
            return await self._arun_impl(user_input, session_id, workflow_name, stream_callback)

    async def _arun_impl(self, user_input: str, session_id: str, workflow_name: str = None,
                         stream_callback: Optional[Callable[[str], None]] = None) -> State:
        """arun 的实际实现（在 session 锁保护下执行）"""
        self._last_input_time[session_id] = time.time()

        # C0: 意识引擎切换到前台模式（用户在说话，集中注意力）
        if hasattr(self, 'consciousness') and self.consciousness:
            try:
                self.consciousness.switch_to_foreground()
            except Exception:
                logger.debug(f"静默异常 [castorice/agent/core.py:510]")
                pass

        state = State(user_input=user_input, session_id=session_id)

        await self._phase_prefetch_context(state, session_id)
        await self._phase_load_signals(state, session_id)
        await self._phase_emotion_update(state, session_id)

        if self.self_awareness:
            await asyncio.to_thread(self.self_awareness.reset_context_counter)

        await self._phase_memory_recall(state, session_id)

        state.user_profile_context = self.user_profile.to_prompt_context()
        state.available_tools_desc = "\n".join(
            f"- {t.name}: {t.description}" for t in self.tools_list
        )

        await self._phase_self_organization(state, session_id)

        elapsed_ms = await self._phase_workflow_execute(state, session_id, workflow_name, stream_callback)
        state.success = len(state.errors) == 0 and bool(state.final_answer)

        await self._phase_metrics_and_persistence(state, session_id, elapsed_ms)

        await self._phase_postprocessing(state, user_input, session_id, elapsed_ms, stream_callback)

        return state

    async def _phase_prefetch_context(self, state: State, session_id: str) -> None:
        """P2: 会话开始时的历史关联检查"""
        if self.short_term is not None:
            try:
                session_info = self.short_term.get_session(session_id)
                is_new_session = session_info is None or session_info.get("summary") is None
                if is_new_session:
                    similar_sessions = await asyncio.to_thread(
                        self.unified_memory._find_similar_sessions,
                        state.user_input,
                        session_id,
                        limit=3,
                    )
                    if similar_sessions:
                        state.similar_sessions = similar_sessions
                        logger.info(f"P2 检测到相似历史会话: {len(similar_sessions)} 个")
            except (OSError, ValueError, RuntimeError) as e:
                logger.debug(f"P2 历史关联检查失败: {e}")

    async def _phase_load_signals(self, state: State, session_id: str) -> None:
        """P1.2: 加载最近反思信号 + P1.3: 加载当前动机 + 主动行为反馈检测"""
        if self.reflection_engine is not None:
            try:
                state.recent_reflection_signal = await asyncio.to_thread(
                    self.reflection_engine.get_recent_signal, max_chars=500
                )
            except (OSError, ValueError, RuntimeError) as e:
                logger.debug(f"P1.2 加载反思信号失败: {e}")

        try:
            motivations = self.emotion_engine.derive_motivations()
            state.current_motivations = motivations
        except (OSError, ValueError, RuntimeError) as e:
            logger.debug(f"P1.3 加载动机失败: {e}")

        if hasattr(self, 'motivation_system') and self.motivation_system:
            try:
                if self.motivation_system.is_awaiting_proactive_feedback():
                    self.motivation_system.record_proactive_feedback(state.user_input)
                    logger.info(f"动机→主动行为闭环: 用户反馈已记录，调整因子={self.motivation_system.get_proactive_adjustment():.2f}")
            except (OSError, ValueError, RuntimeError) as e:
                logger.debug(f"主动行为反馈检测失败: {e}")

    async def _phase_emotion_update(self, state: State, session_id: str) -> None:
        """情感引擎：LLM 推理情感变化并更新自身状态（L2，自我进化版）"""
        try:
            sc_hint = ""
            if self.self_concept is not None:
                sc_content = self.self_concept.load()
                if sc_content.strip():
                    sc_hint = f"【Agent 当前自我概念摘要】\n{sc_content[:500]}"
            state.emotion_detection = await asyncio.to_thread(
                self.emotion_engine.update,
                user_input=state.user_input,
                task_success=True,
                is_followup=False,
                context_hint=sc_hint,
            )
            state.emotion_state_prompt = self.emotion_engine.get_emotion_prompt()
            state.emotion_decision_bias = self.emotion_engine.get_decision_bias()
            if state.emotion_detection and state.emotion_detection.get("is_significant_event"):
                logger.info(f"检测到情感事件: {state.emotion_detection.get('event_summary', '')}")
            if state.emotion_decision_bias:
                bias = state.emotion_decision_bias
                logger.info(
                    f"L3 情绪决策偏置: confidence={bias.get('confidence', 0):+.2f}, "
                    f"creativity={bias.get('creativity', 0):+.2f}, "
                    f"patience={bias.get('patience', 0):+.2f}, "
                    f"risk={bias.get('risk_tolerance', 0):+.2f}"
                )
        except (OSError, ValueError, RuntimeError) as e:
            logger.warning(f"情感引擎更新失败: {e}")
            state.emotion_detection = {}
            state.emotion_state_prompt = ""

    async def _phase_memory_recall(self, state: State, session_id: str) -> None:
        """P2.2: 统一记忆检索 + L4 主动关心 + 短期记忆加载"""
        try:
            # 收集当前情绪状态，用于情感感知的记忆检索（情绪一致性记忆效应）
            emotion_state = None
            try:
                ee_state = self.emotion_engine._emergence_engine._state
                emotion_state = {
                    "pleasure": float(ee_state.pleasure),
                    "arousal": float(ee_state.arousal),
                    "dominance": float(ee_state.dominance),
                }
            except Exception:
                pass

            unified_result = await asyncio.to_thread(
                self.unified_memory.recall,
                state.user_input,
                session_id=session_id,
                top_k_per_source=3,
                emotion_state=emotion_state,
            )
            state.relevant_history = unified_result.get("summary", "")
            
            experiences = unified_result.get("experiences", [])
            exp_lines = []
            for exp in experiences:
                if isinstance(exp, dict):
                    content = exp.get("content", "")
                else:
                    content = getattr(exp, "content", "")
                if content:
                    exp_lines.append(f"- {content[:150]}")
            state.relevant_experiences = "\n".join(exp_lines) if exp_lines else ""
            
            if state.relevant_history:
                logger.info(f"统一记忆检索完成: {len(state.relevant_history)} 字符")
        except Exception as e:
            logger.warning(f"统一记忆检索失败: {e}")
            state.relevant_history = ""
            state.relevant_experiences = ""

        try:
            state.emotion_care_hint = await asyncio.to_thread(
                self._retrieve_emotion_care_hint, session_id, state.user_input
            )
        except (OSError, ValueError, RuntimeError) as e:
            logger.warning(f"L4 主动关心检索失败: {e}")
            state.emotion_care_hint = ""

        history_msgs = []
        try:
            history_msgs = await asyncio.to_thread(
                self.short_term.get_history, session_id, 10
            )
            if history_msgs:
                state.history_messages = [
                    ChatMessage(msg.role, self._smart_truncate_message(msg.content, 1200))
                    for msg in history_msgs[-6:]
                ]
                logger.info(f"短期记忆加载: {len(history_msgs)} 条历史消息")
        except (OSError, ValueError, RuntimeError) as e:
            logger.warning(f"短期记忆加载失败: {e}")

    async def _phase_self_organization(self, state: State, session_id: str) -> None:
        """自组织：思维策略选择 + 对话策略调整 + 能力边界判断 + 资源感知 + 状态模型（并发版）"""
        history_turns = len(state.history_messages) if state.history_messages else 0
        full_context = self._build_context_for_estimation(state)

        # P0-1: 5 个自组织子调用彼此独立，用 asyncio.gather 并发
        # 延迟从"求和"变"取最大"，内省一个不少
        results = await asyncio.gather(
            asyncio.to_thread(self.thinking_strategy.select, state.user_input),
            asyncio.to_thread(self.dialogue_strategy.adjust_prompt, state.user_input, self.user_profile, history_turns),
            asyncio.to_thread(self.self_awareness.can_handle, state.user_input, list(self.tools.keys())),
            asyncio.to_thread(self.self_awareness.should_compress_context, full_context),
            asyncio.to_thread(self.self_awareness.should_slow_down),
            return_exceptions=True,
        )

        # 思维策略
        r = results[0]
        if not isinstance(r, Exception):
            strategy_key, strategy_prompt = r
            state.thinking_strategy = strategy_key
            state.thinking_strategy_prompt = strategy_prompt
            logger.info(f"自组织-思维策略: {self.thinking_strategy.get_strategy_name(strategy_key)} (P1.4 LLM 自选)")
        else:
            logger.warning(f"自组织-思维策略失败: {r}")

        # 对话策略
        r = results[1]
        if not isinstance(r, Exception):
            state.dialogue_adjustment = r
            if state.dialogue_adjustment:
                logger.info("自组织-对话策略: 已应用风格调整")
        else:
            logger.warning(f"自组织-对话策略失败: {r}")

        # 能力评估
        r = results[2]
        if not isinstance(r, Exception):
            can_handle, confidence, reason = r
            logger.info(f"自感知-能力评估: 可处理={can_handle}, 置信度={confidence:.2f}, 理由={reason}")
        else:
            logger.warning(f"自感知-能力评估失败: {r}")

        # 资源感知
        r = results[3]
        if not isinstance(r, Exception):
            should_compress, compress_reason = r
            if should_compress:
                logger.warning(f"自感知-资源: {compress_reason}")
        else:
            logger.warning(f"自感知-资源评估失败: {r}")

        # 状态模型
        r = results[4]
        if not isinstance(r, Exception):
            should_slow, slow_state = r
            if should_slow:
                logger.warning(f"自感知-状态模型: 疲劳度={slow_state['fatigue_score']}, 建议延迟={slow_state['recommended_delay_ms']}ms")
                await asyncio.sleep(slow_state['recommended_delay_ms'] / 1000.0)
        else:
            logger.warning(f"自感知-状态模型评估失败: {r}")

    async def _phase_workflow_execute(self, state: State, session_id: str, workflow_name: str = None,
                                      stream_callback: Optional[Callable[[str], None]] = None) -> float:
        """工作流执行：获取步骤 + 循环执行

        支持两种模式：
        - legacy: 使用预设工作流（硬编码步骤顺序）
        - thinking: 使用 ThinkingLoop（LLM 自主决定执行顺序）
        """
        # L1: 如果启用 thinking 模式，走自主思考循环
        if self.agent_mode == "thinking" and self.thinking_loop is not None and workflow_name is None:
            logger.info("进入 ThinkingLoop 自主思考模式")
            return await self.thinking_loop.run(state, session_id, stream_callback)

        # legacy 模式：原有逻辑不变
        if workflow_name:
            workflow_steps = self._get_workflow_steps(workflow_name)
        else:
            estimated_complexity = await asyncio.to_thread(
                self.task_planner._estimate_complexity, state.user_input
            )
            state.task_complexity = estimated_complexity
            await self._execute_step("intent", state, stream_callback)
            workflow_steps = await asyncio.to_thread(
                self.workflow_selector.select,
                task_complexity=estimated_complexity,
                intent_type=state.intent_type,
                has_tool_calls=True,
            )
            logger.info(f"动态工作流选择: 复杂度={estimated_complexity}, 意图={state.intent_type}, 步骤={workflow_steps}")

        task_start_time = time.time()

        for step in workflow_steps:
            if step == "intent" and state.intent_type:
                continue
            try:
                await self._execute_step(step, state, stream_callback)
            except Exception as e:
                logger.warning(f"步骤 {step} 执行失败: {e}")
                state.errors.append(f"步骤 {step} 执行失败: {e}")

        return (time.time() - task_start_time) * 1000

    async def _phase_metrics_and_persistence(self, state: State, session_id: str, elapsed_ms: float) -> None:
        """P3: 监控指标记录 + 状态持久化"""
        try:
            metrics = get_metrics()
            metrics.inc_counter("agent_runs_total", labels={"success": str(state.success).lower()})
            metrics.record_latency("agent_run_duration_ms", elapsed_ms / 1000.0)
            if state.tool_calls:
                metrics.inc_counter("agent_tool_calls_total", value=len(state.tool_calls))
            if not state.success:
                metrics.inc_error("agent_run_errors")
        except (OSError, ValueError, RuntimeError) as e:
            logger.debug(f"指标记录失败: {e}")

        if self.state_persistence is not None:
            try:
                snapshot = {
                    "user_input": state.user_input,
                    "session_id": state.session_id,
                    "intent_type": state.intent_type,
                    "success": state.success,
                    "final_answer": state.final_answer[:1000] if state.final_answer else "",
                    "errors": state.errors,
                    "tool_calls_count": len(state.tool_calls),
                    "elapsed_ms": elapsed_ms,
                    "timestamp": time.time(),
                }
                self.state_persistence.save(session_id, snapshot)
            except (OSError, IOError, PermissionError, ValueError) as e:
                logger.debug(f"状态持久化保存失败: {e}")

    async def _phase_postprocessing(
        self, state: State, user_input: str, session_id: str,
        elapsed_ms: float, stream_callback: Optional[Callable[[str], None]] = None
    ) -> None:
        """
        Postprocessing phase: record task completion, rollback check, metacognition,
        emotion update, experience journal, memory persistence, and other housekeeping.
        Modifies state in-place.
        """
        # 1. 安全检查和回滚管理
        try:
            await self._postprocess_safety(state, elapsed_ms)
        except (OSError, ValueError, RuntimeError) as e:
            logger.warning(f"_postprocess_safety 失败: {e}")

        # 2. 元认知评估
        try:
            await self._postprocess_metacognition(state, stream_callback)
        except (OSError, ValueError, RuntimeError) as e:
            logger.warning(f"_postprocess_metacognition 失败: {e}")

        # 3. 情绪更新
        try:
            await self._postprocess_emotion(state)
        except (OSError, ValueError, RuntimeError) as e:
            logger.warning(f"_postprocess_emotion 失败: {e}")

        # 4. 经历流和记忆写入
        try:
            await self._postprocess_experience(state)
        except (OSError, ValueError, RuntimeError) as e:
            logger.warning(f"_postprocess_experience 失败: {e}")

        # 5. 自我概念一致性检测
        try:
            await self._postprocess_self_concept(state)
        except (OSError, ValueError, RuntimeError) as e:
            logger.warning(f"_postprocess_self_concept 失败: {e}")

        # 6. 社会关系更新
        try:
            await self._postprocess_social(state)
        except (OSError, ValueError, RuntimeError) as e:
            logger.warning(f"_postprocess_social 失败: {e}")

        # 7. 反思和行动队列
        try:
            await self._postprocess_reflection(state)
        except (OSError, ValueError, RuntimeError) as e:
            logger.warning(f"_postprocess_reflection 失败: {e}")

        # 8. 好奇心和动机
        try:
            await self._postprocess_motivation(state)
        except (OSError, ValueError, RuntimeError) as e:
            logger.warning(f"_postprocess_motivation 失败: {e}")

    def _build_context_for_estimation(self, state: State) -> str:
        """构建用于Token估算的完整上下文文本"""
        parts = [
            state.user_input,
            state.relevant_history,
            state.user_profile_context,
            state.available_tools_desc,
            state.thinking_strategy_prompt,
            state.dialogue_adjustment,
        ]
        return "\n\n".join(p for p in parts if p)

    def _append_uncertainty_note(self, answer: str, meta: Dict[str, Any]) -> str:
        """当元认知判断质量不足时，在回答后附加提示"""
        confidence = meta.get("confidence")
        if not confidence:
            return answer

        note_parts = []
        if confidence.hallucination_risk == "high":
            note_parts.append("⚠️ 以上回答中部分信息缺乏可靠来源，建议你二次核实。")
        elif confidence.hallucination_risk == "medium":
            note_parts.append("⚠️ 以上回答仅供参考，部分细节可能需要确认。")

        # 只有当回答确实涉及知识性问题且质量分很低时才附加"把握不足"提示
        # 问候、闲聊、短对话等不应该出现这个提示
        quality = meta.get("quality")
        if (
            quality
            and getattr(quality, "score", 100) < 40
            and len(answer) > 150
            and not getattr(quality, "is_small_talk", False)
        ):
            note_parts.append("我对这个问题的把握不足，如果你需要更准确的答案，可以补充更多背景信息。")

        if not note_parts:
            return answer

        return answer + "\n\n" + " ".join(note_parts)

    # ============================================================
    # 情感引擎辅助方法（L4 主动关心）
    # ============================================================
    def _retrieve_emotion_care_hint(self, session_id: str = "", user_input: str = "") -> str:
        """
        L4 主动关心：检索近 3 天内的负面情感事件（带缓存）

        P1-5: 同一 session 5 分钟内不重复检索 ChromaDB，避免每轮开销。
        P2-2: 检索 query 改用语义化关键词组合，匹配保存时的 event_summary 文本格式。

        如果检测到近期负面事件，返回主动关心提示词；否则返回空字符串。
        """
        # P1-5: 缓存命中检查
        if session_id:
            cached = self._emotion_care_cache.get(session_id)
            if cached:
                cache_time, cache_hint = cached
                if time.time() - cache_time < self._emotion_care_cache_ttl:
                    logger.debug(f"L4 缓存命中 session={session_id}")
                    return cache_hint

        if not self.long_term or not getattr(self.long_term, "is_available", False):
            return ""

        # P2-2: 用语义化 query 检索，匹配保存时的 event_summary 文本
        # 保存格式: state.emotion_detection["event_summary"] + " | 用户原话: ..."
        # 用当前用户输入作为主 query，再补充情感关键词以提高召回
        query = f"用户原话: {user_input}" if user_input else "用户负面情绪事件 失败 难过 失望 焦虑"
        results = []
        try:
            if hasattr(self.long_term, "search"):
                results = self.long_term.search(query, top_k=10) or []
        except (OSError, ValueError, RuntimeError) as e:
            logger.debug(f"长期记忆情感事件检索失败: {e}")
            return ""

        now = datetime.now(timezone.utc)
        hint = ""
        for ev in results:
            if not isinstance(ev, dict):
                continue
            meta = ev.get("metadata", {}) or {}
            if meta.get("type") != "emotion_event":
                continue
            if meta.get("valence") != "negative":
                continue
            ts_str = meta.get("timestamp", "")
            if not ts_str:
                continue
            try:
                ev_time = datetime.fromisoformat(ts_str)
                if (now - ev_time).days <= 3:
                    text = ev.get("text", ev.get("document", ""))[:120]
                    hint = (
                        "## 主动关心提示\n"
                        f"用户近期有负面情绪事件：{text}\n"
                        "请在回复开始时温和地关心一下用户（如'上次你说到XX，现在怎么样了？'），"
                        "但不要生硬，如果用户当前话题无关则不强制提及。"
                    )
                    break
            except (ValueError, TypeError) as e:
                logger.warning(f"L4 情感事件时间解析失败: {e}")
                continue

        # P1-5: 写入缓存
        if session_id:
            self._emotion_care_cache[session_id] = (time.time(), hint)
            # 清理过期缓存（超过 10 条时清空）
            if len(self._emotion_care_cache) > 10:
                cutoff = time.time() - self._emotion_care_cache_ttl
                self._emotion_care_cache = {
                    k: v for k, v in self._emotion_care_cache.items()
                    if v[0] > cutoff
                }

        return hint

    # ============================================================
    # P2.3: 静默轮主动行为
    # ============================================================
