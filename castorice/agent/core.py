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
from castorice.metacognition import Metacognition as _BuiltinMetacognition
from castorice.self_awareness import SelfAwareness
from castorice.self_organization import (
    TaskPlanner, TaskPlan, SubTask,
    DynamicWorkflowSelector, ErrorRecoveryStrategy,
    TaskExecutor, ThinkingStrategySelector, DialogueStrategy,
)
from castorice.utils import extract_json
from .common import logger, _get_alert_manager
from .prompt_builder import PromptBuilderMixin
from .tool_loop import ToolLoopMixin
from .memory_ops import MemoryOpsMixin

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

    # P1.2: 反思信号（最近一次反思的结论，影响当前决策）
    recent_reflection_signal: str = ""
    # P1.3: 动机信号（由情感推导的当前意图列表）
    current_motivations: List[str] = field(default_factory=list)
    # P2: 相似历史会话（跨会话记忆迁移）
    similar_sessions: List[Dict[str, Any]] = field(default_factory=list)
    # P2.5: 主动话题（正常对话中主动发起的延续话题）
    initiated_topic: str = ""


class CastoriceAgent(PromptBuilderMixin, ToolLoopMixin, MemoryOpsMixin):
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
        self.model = model_adapter
        self.tools = {t.name: t for t in tools}
        self.tools_list = tools
        self.short_term = short_term_memory
        self.long_term = long_term_memory
        self.skill_memory = skill_memory
        self.user_profile = user_profile
        self.config = config

        runtime_cfg = config.runtime if hasattr(config, "runtime") else {}
        self.max_iterations = runtime_cfg.get("max_iterations", 10) if isinstance(runtime_cfg, dict) else 10
        self.enable_reflection = runtime_cfg.get("enable_reflection", True) if isinstance(runtime_cfg, dict) else True
        self.enable_skill_generation = runtime_cfg.get("enable_skill_generation", True) if isinstance(runtime_cfg, dict) else True

        # 工作流模板配置
        self.workflows = config.workflows if hasattr(config, "workflows") else {}
        # P1-32: default_workflow 已删除——动态工作流选择器才是实际机制

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
        evolve_cfg = runtime_cfg.get("self_evolving", {}) if isinstance(runtime_cfg, dict) else {}
        evolve_enabled = evolve_cfg.get("enabled", True)

        # 经历流（复用 ChromaDB 或独立 SQLite）
        from castorice.experience_journal import ExperienceJournal
        journal_path = evolve_cfg.get("experience_journal_path", "./castorice_data/experiences.db")
        max_experiences = int(evolve_cfg.get("max_experiences", 10000))
        self.experience_journal = ExperienceJournal(
            db_path=journal_path, max_experiences=max_experiences,
        ) if evolve_enabled else None

        # 自我概念（Agent 自己读写的 Markdown 文档）
        from castorice.self_concept import SelfConcept
        sc_path = evolve_cfg.get("self_concept_path", "./castorice_data/self_concept.md")
        self.self_concept = SelfConcept(storage_path=sc_path) if evolve_enabled else None

        # 情感引擎（自我进化版：LLM 推理 + 依赖注入）
        # 优先使用 SDK，未安装时用内置
        emotion_cfg = runtime_cfg.get("emotion", {}) if isinstance(runtime_cfg, dict) else {}
        if _USING_EMOTION_SDK:
            self.emotion_engine = _SdkEmotionEngine(
                storage_path=emotion_cfg.get("storage_path", "./castorice_data/emotion_state.json"),
                enabled=emotion_cfg.get("enabled", True),
                model_adapter=model_adapter,
                self_concept=self.self_concept,
                experience_journal=self.experience_journal,
            )
        else:
            from castorice.emotion import EmotionEngine
            self.emotion_engine = EmotionEngine(
                storage_path=emotion_cfg.get("storage_path", "./castorice_data/emotion_state.json"),
                enabled=emotion_cfg.get("enabled", True),
                model_adapter=model_adapter,
                self_concept=self.self_concept,
                experience_journal=self.experience_journal,
            )
        self.emotion_engine.load()  # 预加载状态

        # 反思引擎（定期+事件触发，更新自我概念）
        if evolve_enabled:
            from castorice.reflection import ReflectionEngine
            self.reflection_engine = ReflectionEngine(
                model_adapter=model_adapter,
                experience_journal=self.experience_journal,
                self_concept=self.self_concept,
                reflection_interval_turns=int(evolve_cfg.get("reflection_interval_turns", 10)),
                reflection_confidence_threshold=float(evolve_cfg.get("reflection_llm_threshold", 0.4)),
            )
        else:
            self.reflection_engine = None

        # P0: 长期意图追踪系统（需要在 unified_memory 之前初始化）
        from castorice.memory.intent_tracker import IntentTracker
        self.intent_tracker = IntentTracker()

        # P2.2: 统一记忆检索层（聚合长期记忆、经历流、自我概念、意图追踪）
        from castorice.memory.unified_recall import UnifiedMemoryRecall
        self.unified_memory = UnifiedMemoryRecall(
            long_term=self.long_term,
            short_term=self.short_term,
            experience_journal=self.experience_journal,
            self_concept=self.self_concept,
            intent_tracker=self.intent_tracker,
        )

        # P3.2: 工具调用自我学习
        from castorice.tool_learning import ToolCallMemory
        self.tool_learning = ToolCallMemory()

        # P2.3: 内在动机系统（驱动主动行为）
        from castorice.motivation import IntrinsicMotivation
        self.motivation_system = IntrinsicMotivation()

        # P1: 行动队列（反思-行动闭环）
        from castorice.reflection import ActionQueue
        self.action_queue = ActionQueue()

        # S1: 社会关系网络
        from castorice.social_relation import SocialRelationManager
        self.social_relation = SocialRelationManager()

        # A1: 自传式记忆系统
        from castorice.memory.autobiographical import AutobiographicalMemory
        self.autobiographical = AutobiographicalMemory()

        # P1-5: L4 主动关心检索缓存（session_id → (timestamp, hint)）
        # 5 分钟内同 session 不重复检索 ChromaDB，避免每轮开销
        self._emotion_care_cache: Dict[str, tuple] = {}
        self._emotion_care_cache_ttl = 300  # 5 分钟

        # P1-2: 按 session_id 分桶的并发锁，避免同一会话多请求状态冲突
        # 不同 session_id 之间仍可并行，仅串行化同一会话
        # 使用 threading.Lock 而不是 asyncio.Lock，因为 run() 每次调用会创建新的事件循环
        self._session_locks: Dict[str, threading.Lock] = {}
        self._session_locks_last_used: Dict[str, float] = {}  # P1-1: 记录每个锁的最后使用时间
        self._session_locks_guard = threading.Lock()
        self._session_locks_ttl = 1800  # P1-1: 锁空闲 30 分钟后可清理

        # P2.3: 静默轮检测相关
        self._last_input_time: Dict[str, float] = {}  # session_id → 上次用户输入时间
        self._quiet_round_enabled = True  # 是否启用静默轮主动行为
        _state = self.emotion_engine._state
        p, a, d = (0.0, 0.0, 0.0)
        if _state is not None:
            p, a, d = _state.pleasure, _state.arousal, _state.dominance
        logger.info(
            f"自我进化系统已加载: evolve={evolve_enabled}, "
            f"emotion.enabled={self.emotion_engine.enabled}, "
            f"P={p:.2f}, A={a:.2f}, D={d:.2f}, "
            f"self_concept_empty={self.self_concept.is_empty() if self.self_concept else 'N/A'}"
        )

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
        except Exception:
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
        # P2.3: 更新上次用户输入时间
        self._last_input_time[session_id] = time.time()

        state = State(user_input=user_input, session_id=session_id)

        # P2: 会话开始时的历史关联检查
        if self.short_term is not None:
            try:
                session_info = self.short_term.get_session(session_id)
                is_new_session = session_info is None or session_info.get("summary") is None
                if is_new_session:
                    similar_sessions = await asyncio.to_thread(
                        self.unified_memory._find_similar_sessions,
                        user_input,
                        session_id,
                        limit=3,
                    )
                    if similar_sessions:
                        state.similar_sessions = similar_sessions
                        logger.info(f"P2 检测到相似历史会话: {len(similar_sessions)} 个")
            except Exception as e:
                logger.debug(f"P2 历史关联检查失败: {e}")

        # P1.2: 加载最近反思信号（影响当前轮决策）
        if self.reflection_engine is not None:
            try:
                state.recent_reflection_signal = await asyncio.to_thread(
                    self.reflection_engine.get_recent_signal, max_chars=500
                )
            except Exception as e:
                logger.debug(f"P1.2 加载反思信号失败: {e}")

        # P1.3: 加载当前动机（情感→动机→行为闭环）
        try:
            motivations = self.emotion_engine.derive_motivations()
            state.current_motivations = motivations
        except Exception as e:
            logger.debug(f"P1.3 加载动机失败: {e}")

        # 情感引擎：LLM 推理情感变化并更新自身状态（L2，自我进化版）
        # 用 asyncio.to_thread 包裹因为 LLM 调用是同步的
        try:
            # 上下文提示：当前自我概念摘要（让 LLM 知道 Agent 当前人格）
            sc_hint = ""
            if self.self_concept is not None:
                sc_content = self.self_concept.load()
                if sc_content.strip():
                    sc_hint = f"【Agent 当前自我概念摘要】\n{sc_content[:500]}"
            state.emotion_detection = await asyncio.to_thread(
                self.emotion_engine.update,
                user_input,
                True,  # task_success（后续会二次更新）
                False,  # is_followup
                sc_hint,  # context_hint
            )
            state.emotion_state_prompt = self.emotion_engine.get_emotion_prompt()
            if state.emotion_detection and state.emotion_detection.get("is_significant_event"):
                logger.info(f"检测到情感事件: {state.emotion_detection.get('event_summary', '')}")
        except Exception as e:
            logger.warning(f"情感引擎更新失败: {e}")
            state.emotion_detection = {}
            state.emotion_state_prompt = ""

        # 重置上下文窗口计数器（开始新的对话轮次）
        if self.self_awareness:
            await asyncio.to_thread(self.self_awareness.reset_context_counter)

        # P2.2: 统一记忆检索——一次调用同时检索长期记忆、经历流、自我概念
        try:
            unified_result = await asyncio.to_thread(
                self.unified_memory.recall, user_input, session_id=session_id, top_k_per_source=3
            )
            state.relevant_history = unified_result.get("summary", "")
            state.relevant_experiences = "\n".join(
                f"- {exp.get('content', '')[:150]}"
                for exp in unified_result.get("experiences", []) if exp.get("content")
            ) if unified_result.get("experiences") else ""
            if state.relevant_history:
                logger.info(f"统一记忆检索完成: {len(state.relevant_history)} 字符")
        except Exception as e:
            logger.warning(f"统一记忆检索失败: {e}")
            state.relevant_history = ""
            state.relevant_experiences = ""

        # L4 主动关心：检索近 3 天内的负面情感事件（带 5 分钟缓存）
        # P2-2: 传入 user_input 作为检索 query，提高召回率
        try:
            state.emotion_care_hint = await asyncio.to_thread(
                self._retrieve_emotion_care_hint, session_id, user_input
            )
        except Exception as e:
            logger.warning(f"L4 主动关心检索失败: {e}")
            state.emotion_care_hint = ""

        # 注入上下文：短期记忆（当前会话历史对话）
        history_msgs = []  # P0-1: 预定义，避免 try 块内失败时 NameError
        try:
            history_msgs = await asyncio.to_thread(
                self.short_term.get_history, session_id, 10
            )
            if history_msgs:
                # P1-6: 不再把历史拼成字符串注入 system prompt（与 history_messages 冗余）
                # 仅保留 history_messages 用于多轮上下文注入
                # P2-4: 智能截断——保留代码块完整性，避免硬截断 500 字符破坏代码上下文
                state.history_messages = [
                    ChatMessage(msg.role, self._smart_truncate_message(msg.content, 1200))
                    for msg in history_msgs[-6:]
                ]
                logger.info(f"短期记忆加载: {len(history_msgs)} 条历史消息")
        except Exception as e:
            logger.warning(f"短期记忆加载失败: {e}")

        state.user_profile_context = self.user_profile.to_prompt_context()
        state.available_tools_desc = "\n".join(
            f"- {t.name}: {t.description}" for t in self.tools_list
        )

        # 自组织：思维策略选择
        strategy_key, strategy_prompt = await asyncio.to_thread(
            self.thinking_strategy.select, user_input
        )
        state.thinking_strategy = strategy_key
        state.thinking_strategy_prompt = strategy_prompt
        logger.info(f"自组织-思维策略: {self.thinking_strategy.get_strategy_name(strategy_key)} (P1.4 LLM 自选)")

        # 自组织：对话策略调整
        history_turns = len(history_msgs) if history_msgs else 0
        state.dialogue_adjustment = await asyncio.to_thread(
            self.dialogue_strategy.adjust_prompt, user_input, self.user_profile, history_turns
        )
        if state.dialogue_adjustment:
            logger.info("自组织-对话策略: 已应用风格调整")

        # 自感知：能力边界判断
        can_handle, confidence, reason = await asyncio.to_thread(
            self.self_awareness.can_handle, user_input, list(self.tools.keys())
        )
        logger.info(f"自感知-能力评估: 可处理={can_handle}, 置信度={confidence:.2f}, 理由={reason}")

        # 自感知：资源感知 - 检查上下文窗口
        full_context = self._build_context_for_estimation(state)
        should_compress, compress_reason = await asyncio.to_thread(
            self.self_awareness.should_compress_context, full_context
        )
        if should_compress:
            logger.warning(f"自感知-资源: {compress_reason}")
            # short_term_context 已移除，压缩通过其他机制处理

        # 自感知：状态模型 - 是否需要降速
        should_slow, slow_state = await asyncio.to_thread(self.self_awareness.should_slow_down)
        if should_slow:
            logger.warning(f"自感知-状态模型: 疲劳度={slow_state['fatigue_score']}, 建议延迟={slow_state['recommended_delay_ms']}ms")
            await asyncio.sleep(slow_state['recommended_delay_ms'] / 1000.0)

        # 获取工作流步骤
        if workflow_name:
            workflow_steps = self._get_workflow_steps(workflow_name)
        else:
            estimated_complexity = await asyncio.to_thread(
                self.task_planner._estimate_complexity, user_input
            )
            state.task_complexity = estimated_complexity
            # 先执行 intent 步骤获取真实 intent_type，再用它选工作流
            # （原实现硬编码 intent_type="task"，导致闲聊无法走 simple_qa 的 chat 分支）
            await self._execute_step("intent", state, stream_callback)
            workflow_steps = await asyncio.to_thread(
                self.workflow_selector.select,
                task_complexity=estimated_complexity,
                intent_type=state.intent_type,
                has_tool_calls=True,
            )
            logger.info(f"动态工作流选择: 复杂度={estimated_complexity}, 意图={state.intent_type}, 步骤={workflow_steps}")

        task_start_time = time.time()

        # 按工作流模板执行步骤（跳过已执行的 intent，避免重复）
        for step in workflow_steps:
            if step == "intent" and state.intent_type:
                # 动态选择路径下 intent 已提前执行，跳过（intent_type 为空字符串时表示未执行）
                continue
            try:
                await self._execute_step(step, state, stream_callback)
            except Exception as e:
                logger.warning(f"步骤 {step} 执行失败: {e}")
                state.errors.append(f"步骤 {step} 执行失败: {e}")

        elapsed_ms = (time.time() - task_start_time) * 1000
        # P0-2: 严格判定 success（任何错误都算失败），不再容忍 1-2 个错误
        state.success = len(state.errors) == 0 and bool(state.final_answer)

        # 自感知：记录任务完成
        await asyncio.to_thread(
            self.self_awareness.record_task, user_input, success=state.success, elapsed_ms=elapsed_ms
        )

        # P3.4: 回滚管理器 - 记录任务结果并检查是否需要回滚
        try:
            from castorice.security.rollback import get_rollback_manager
            rollback_mgr = get_rollback_manager()
            rollback_mgr.record_task(state.success)
            for err in state.errors:
                rollback_mgr.record_error(err)
            should_rollback, reason = rollback_mgr.should_rollback()
            if should_rollback:
                logger.warning(f"P3.4 触发自动回滚: {reason}")
                rolled_back_items = []
                if hasattr(self, 'self_concept') and hasattr(self.self_concept, 'revert'):
                    try:
                        self.self_concept.revert()
                        rolled_back_items.append("self_concept")
                    except Exception:
                        pass
                rollback_mgr.mark_rollback(reason, rolled_back_items)
        except Exception as e:
            logger.warning(f"P3.4 回滚检查失败: {e}")

        # 元认知：生成反思
        tool_results = [tc["result"] for tc in state.tool_calls]
        # P0-2: 追加本轮最终答案到 previous_answers，供元认知一致性检测使用
        if state.final_answer:
            state.previous_answers.append(state.final_answer)
            # 限制长度避免无限增长（保留最近 10 轮）
            if len(state.previous_answers) > 10:
                state.previous_answers = state.previous_answers[-10:]
        state.metacognition_result = await asyncio.to_thread(
            self.metacognition.reflect,
            user_input=user_input,
            answer=state.final_answer,
            tool_results=tool_results,
            previous_answers=state.previous_answers,
        )
        meta = state.metacognition_result
        logger.info(
            f"元认知反思: 置信度={meta['confidence'].overall_score:.2f}, "
            f"幻觉风险={meta['confidence'].hallucination_risk}, "
            f"质量分={meta['quality'].score:.1f}"
        )

        # 元认知：如果置信度太低，自动补充提示
        if meta["should_reconsider"] and state.final_answer:
            # L3: 情绪影响元认知阈值（高愉悦 → 放宽阈值，可能撤销重新考虑）
            try:
                workflow_adj = self.emotion_engine.get_workflow_adjustment()
                delta = workflow_adj.get("confidence_threshold_delta", 0.0)
                if delta < -0.05 and meta["confidence"].overall_score > 0.5:
                    logger.info(f"L3: 情绪良好(delta={delta})，放宽元认知阈值，不重新考虑")
                    meta["should_reconsider"] = False
                elif delta > 0.05:
                    logger.info(f"L3: 情绪低落(delta={delta})，收紧元认知阈值，强制重新考虑")
            except Exception as e:
                logger.warning(f"L3 元认知阈值调整失败: {e}")

        if meta["should_reconsider"] and state.final_answer:
            logger.warning("元认知: 回答质量不足，建议重新考虑")
            state.final_answer = self._append_uncertainty_note(state.final_answer, meta)

            # P2.4: 从错误中学习——元认知检测到低质量回答时自动生成规则
            try:
                mistake_desc = f"低质量回答: 用户输入='{user_input[:100]}', 置信度={meta['confidence'].overall_score:.2f}, 幻觉风险={meta['confidence'].hallucination_risk}"
                rule_proposal = f"当用户输入类似'{user_input[:50]}'时，应该先调用工具查证，而不是直接回答"
                self.metacognition.learn_from_mistake(
                    mistake_description=mistake_desc,
                    rule_proposal=rule_proposal,
                    confidence=meta["confidence"].overall_score,
                )
            except Exception as e:
                logger.debug(f"P2.4 从错误学习失败: {e}")

            # P0-3: 告警系统接入 - 元认知低置信度
            try:
                _get_alert_manager().info(
                    title="元认知置信度低",
                    message=f"session={state.session_id} 置信度={meta['confidence'].overall_score:.2f} 幻觉风险={meta['confidence'].hallucination_risk} 用户需求: {user_input[:100]}",
                    cooldown_key=f"low_confidence_{state.session_id}",
                )
            except Exception as e:
                logger.warning(f"元认知低置信度告警发送失败: {e}")

        # 兜底：如果最终回答中没有 Markdown 图片格式，从工具结果中补上
        # P1-4: 先补全图片，再把增量图片通过 stream_callback 推送（避免流式内容丢图）
        answer_before = state.final_answer
        state.final_answer = self._ensure_images_in_answer(state.final_answer, state.tool_calls)
        # P1-4: 如果 _ensure_images_in_answer 追加了图片且 stream_callback 存在，把图片增量推送出去
        if stream_callback and callable(stream_callback) and state.final_answer != answer_before:
            appended = state.final_answer[len(answer_before):]
            if appended.strip():
                try:
                    stream_callback(appended)
                except Exception as e:
                    logger.warning(f"图片增量流式推送失败: {e}")

        # 情感引擎：根据任务结果二次更新 + 保存状态（L2 持久化）
        try:
            # 用任务成功状态再更新一次情感（影响 dominance/pleasure）
            # P2-bug: is_followup=True 避免重复增加 interaction_count
            # P0-4: 传入用户输入摘要+任务结果，让 LLM 能基于真实语境推理
            if state.emotion_detection is not None:
                result_hint = "成功" if state.success else f"失败({'; '.join(state.errors[:1]) if state.errors else '未知'})"
                await asyncio.to_thread(
                    self.emotion_engine.update,
                    f"[任务结果反馈] 用户: {user_input[:100]} | 结果: {result_hint}",
                    state.success,  # task_success
                    True,           # is_followup
                    "",             # context_hint（二次更新不需要）
                )
            # P1-2: emotion_engine.save() 是同步阻塞的磁盘写入，用 to_thread 避免阻塞事件循环
            await asyncio.to_thread(self.emotion_engine.save)
        except Exception as e:
            logger.warning(f"情感状态保存失败: {e}")

        # 自我进化：本轮交互写入经历流（episodic 类型）
        if self.experience_journal is not None:
            try:
                logger.debug("开始写入经历流...")
                # 重要性评分：基于情感强度 + 任务结果 + 是否有反思事件
                importance = 5.0
                emotional_valence = 0.0
                if state.emotion_detection:
                    dp = state.emotion_detection.get("agent_pad_delta", (0, 0, 0))[0]
                    emotional_valence = max(-1.0, min(1.0, dp * 2))
                    if state.emotion_detection.get("is_significant_event"):
                        importance = 7.0
                if not state.success:
                    importance = max(importance, 6.0)

                # 经历内容：自然语言描述本轮交互
                content_parts = [f"用户: {user_input[:200]}"]
                if state.final_answer:
                    content_parts.append(f"我: {state.final_answer[:200]}")
                if not state.success:
                    content_parts.append(f"结果: 失败 ({'; '.join(state.errors[:2]) if state.errors else '未知错误'})")
                else:
                    content_parts.append("结果: 成功")
                if state.emotion_detection and state.emotion_detection.get("agent_inner_thought"):
                    content_parts.append(f"内心: {state.emotion_detection['agent_inner_thought']}")

                logger.debug("调用 experience_journal.add_simple...")
                await asyncio.to_thread(
                    self.experience_journal.add_simple,
                    " | ".join(content_parts),
                    "episodic",
                    importance,
                    emotional_valence,
                    session_id,
                    {
                        "intent": state.intent_type,
                        "success": state.success,
                        "tool_count": len(state.tool_calls),
                        "inner_thought": state.emotion_detection.get("agent_inner_thought", "") if state.emotion_detection else "",
                    },
                )
                logger.debug("经历流写入完成")
            except Exception as e:
                logger.warning(f"经历流写入失败: {e}")

        # L4: 情感事件归档到长期记忆（兼容旧字段名）
        try:
            if state.emotion_detection and state.emotion_detection.get("is_significant_event"):
                event_summary = state.emotion_detection.get("event_summary", "情感事件")
                # P1-2: long_term.add() 是同步阻塞（ChromaDB 写入），用 to_thread 避免阻塞
                await asyncio.to_thread(
                    self.long_term.add,
                    event_summary + f" | 用户原话: {user_input[:100]}",
                    {
                        "type": "emotion_event",
                        "valence": state.emotion_detection.get("user_emotion_valence",
                                    state.emotion_detection.get("valence", "neutral")),
                        "inner_thought": state.emotion_detection.get("agent_inner_thought", ""),
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "session_id": session_id,
                    },
                )
                logger.info(f"L4: 情感事件已归档 ({event_summary})")
        except Exception as e:
            logger.warning(f"L4 情感事件归档失败: {e}")

        # 自我进化：反思触发（定期 + 事件）
        logger.debug("检查反思引擎...")
        if self.reflection_engine is not None:
            try:
                logger.debug("调用 reflection_engine.should_reflect...")
                confidence = 1.0
                if state.metacognition_result:
                    # metacognition_result 是 dict，通过键访问而非 getattr
                    meta_conf = state.metacognition_result.get("confidence", {})
                    if isinstance(meta_conf, dict):
                        confidence = meta_conf.get("overall_score", 1.0)
                    elif hasattr(meta_conf, "overall_score"):
                        confidence = meta_conf.overall_score
                significant = bool(state.emotion_detection and state.emotion_detection.get("is_significant_event"))
                should, reason = await asyncio.to_thread(
                    self.reflection_engine.should_reflect,
                    True,  # turn_completed
                    confidence,
                    significant,
                    state.success,
                )
                if should:
                    logger.info(f"触发反思: {reason}")
                    # 反思在后台执行，不阻塞当前响应
                    reflection_result = await asyncio.to_thread(
                        self.reflection_engine.reflect,
                        reason,
                        f"最近一轮: {user_input[:100]}",
                    )
                    if reflection_result.self_concept_updated:
                        logger.info(f"自我概念已更新: {reflection_result.update_reason}")
                    # P1: 将反思行动建议添加到行动队列
                    if hasattr(self, 'action_queue') and reflection_result.next_actions:
                        added = await asyncio.to_thread(
                            self.action_queue.add_from_reflection, reflection_result
                        )
                        if added > 0:
                            logger.info(f"反思行动已加入队列: {added} 个")
            except Exception as e:
                logger.warning(f"反思引擎触发失败: {e}")

        # 自我修正：定期检查记忆质量并修正错误
        await self._reflect_on_memory_quality(session_id)

        # 写入短时记忆
        try:
            logger.debug("开始写入短时记忆...")
            from castorice.memory.short_term import Message
            await asyncio.to_thread(
                self.short_term.add_message, session_id, Message(role="user", content=user_input)
            )
            await asyncio.to_thread(
                self.short_term.add_message,
                session_id,
                Message(role="assistant", content=state.final_answer,
                        metadata={"intent": state.intent_type, "success": state.success}),
            )
            logger.debug("短时记忆写入完成")
        except Exception as e:
            logger.warning(f"短时记忆写入失败: {e}")

        # P0: 意图追踪 - 分析本轮对话，更新意图状态
        if hasattr(self, 'intent_tracker'):
            try:
                updated_intents = await asyncio.to_thread(
                    self.intent_tracker.analyze_and_update,
                    user_input,
                    state.final_answer,
                    session_id,
                    self.model,
                )
                # P0-sub: 对新检测到的复杂意图自动分解为子任务
                if updated_intents:
                    for intent in updated_intents:
                        if intent.is_active() and not intent.sub_tasks:
                            try:
                                await asyncio.to_thread(
                                    self.intent_tracker.decompose_intent,
                                    intent.intent_id,
                                    self.model,
                                )
                            except Exception as e:
                                logger.debug(f"P0 意图分解失败: {e}")
            except Exception as e:
                logger.warning(f"P0 意图分析失败: {e}")

        # S1: 社会关系更新 - 每轮交互后更新关系状态
        if hasattr(self, 'social_relation'):
            try:
                user_id = getattr(state, 'user_id', session_id)
                interaction_quality = 0.6 if state.success else 0.3
                emotional_intensity = getattr(state, 'emotion_valence', 0.0)
                user_feedback = user_input[-50:] if len(user_input) > 50 else user_input
                await asyncio.to_thread(
                    self.social_relation.update_relation,
                    user_id,
                    interaction_quality,
                    state.success,
                    emotional_intensity,
                    user_feedback,
                    user_input[:200],
                )
            except Exception as e:
                logger.warning(f"S1 关系更新失败: {e}")

        # A1: 自传式记忆 - 每轮交互计数 + 时期转换检测
        if hasattr(self, 'autobiographical'):
            try:
                await asyncio.to_thread(self.autobiographical.record_interaction)
                # 检测是否进入新时期
                new_epoch = await asyncio.to_thread(
                    self.autobiographical.check_epoch_transition
                )
                if new_epoch:
                    logger.info(f"A1 进入新时期: {new_epoch.name}")
                    # LLM驱动的时期总结
                    try:
                        milestones = await asyncio.to_thread(
                            self.autobiographical.get_milestones, limit=20
                        )
                        events = await asyncio.to_thread(
                            self.autobiographical.get_events, limit=20
                        )
                        await asyncio.to_thread(
                            self.autobiographical.summarize_epoch_with_llm,
                            new_epoch,
                            self.model,
                            milestones,
                            events,
                        )
                    except Exception as e:
                        logger.debug(f"A1 时期LLM总结失败: {e}")
                # 检测首次启动里程碑
                ms_count = len(self.autobiographical.get_milestones(limit=100))
                if not ms_count:
                    await asyncio.to_thread(
                        self.autobiographical.add_milestone,
                        "第一次与用户交互",
                        "第一次成功回应用户输入，标志着我的旅程的开始。",
                        category="first_achievement",
                        importance=9.0,
                        session_id=session_id,
                    )
                # 检测数量里程碑
                total = getattr(self.autobiographical, '_total_interactions', 0)
                if total in [10, 50, 100, 500, 1000]:
                    await asyncio.to_thread(
                        self.autobiographical.add_milestone,
                        f"第 {total} 次交互",
                        f"完成了第 {total} 次交互，又一个里程碑！",
                        category="achievement",
                        importance=7.0 if total >= 100 else 5.0,
                        session_id=session_id,
                    )
            except Exception as e:
                logger.warning(f"A1 自传式记忆更新失败: {e}")

        # P2.5: 主动话题发起（在正常对话中自然延续话题）
        if state.success and state.final_answer:
            try:
                initiated_topic = await self._step_initiate_topic(state)
                if initiated_topic:
                    state.initiated_topic = initiated_topic
                    state.final_answer += f"\n\n{initiated_topic}"
                    logger.info(f"P2.5 主动话题发起: {initiated_topic[:50]}...")
            except Exception as e:
                logger.debug(f"P2.5 主动话题生成失败: {e}")

        logger.debug("arun_impl 即将返回 state")
        return state

    def _get_workflow_steps(self, workflow_name: str) -> List[str]:
        """获取工作流模板的步骤列表"""
        if not self.workflows or workflow_name not in self.workflows:
            logger.warning(f"工作流模板 '{workflow_name}' 不存在，使用标准流程")
            return ["intent", "tool_loop", "answer", "reflection", "memory", "skill"]

        workflow = self.workflows.get(workflow_name, {})
        return workflow.get("steps", ["intent", "tool_loop", "answer", "reflection", "memory", "skill"])

    async def _execute_step(self, step: str, state: State, stream_callback: Optional[Callable[[str], None]] = None) -> None:
        """执行单个步骤（支持同步和异步步骤）"""
        step_map = {
            "intent": self._step_intent,
            "planning": self._step_planning,
            "tool_loop": lambda s: self._step_tool_loop(s, stream_callback),
            "answer": lambda s: self._step_answer(s, stream_callback),
            "reflection": self._step_reflection,
            "memory": self._step_memory,
            "skill": self._step_skill,
        }

        if step in step_map:
            fn = step_map[step]
            result = fn(state)
            if asyncio.iscoroutine(result):
                await result
        else:
            logger.warning(f"未知步骤: {step}")

    # ============================================================
    # 阶段1: 意图解析
    # ============================================================
    def _step_intent(self, state: State) -> None:
        """判断用户意图：纯闲聊 vs 需要工具的任务（P0.4: LLM 优先，规则仅做安全兜底）"""
        # P0.4: 技能匹配——让 LLM 自主决定是否匹配技能，不再硬编码关键词判断
        try:
            matches = self.skill_memory.match(state.user_input, top_n=3)
            if matches:
                skill_list = []
                for skill in matches:
                    if skill.enabled:
                        skill_list.append({
                            "name": skill.name,
                            "description": skill.description,
                            "keywords": ", ".join(skill.trigger_keywords),
                        })

                if skill_list:
                    skills_desc = "\n".join(
                        f"- {s['name']}: {s['description']} (触发词: {s['keywords']})"
                        for s in skill_list
                    )

                    prompt = f"""判断以下用户输入是否应该匹配某个技能。

用户输入: {state.user_input}

可用技能:
{skills_desc}

只返回 JSON：{{"match": true/false, "skill_name": "匹配的技能名或空字符串", "reason": "理由"}}

规则：
- 只有当用户输入明确指向技能的功能时才匹配
- 不强制匹配，让 Agent 自主决定是否需要调用技能
- 如果不确定，返回 false"""

                    try:
                        response = self.model.chat([
                            ChatMessage("system", "你是技能匹配器，只输出 JSON。"),
                            ChatMessage("user", prompt),
                        ])
                        parsed = extract_json(response.content)
                        if parsed.get("match") and parsed.get("skill_name"):
                            matched_skill = next((m for m in matches if m.name == parsed["skill_name"]), None)
                            if matched_skill:
                                state.intent_type = "task"
                                state.matched_skill_id = matched_skill.id
                                state.confidence = 0.95
                                logger.info(f"P0.4 LLM 技能匹配: {parsed['skill_name']} | {parsed.get('reason', '')}")
                                return
                    except Exception as e:
                        logger.debug(f"LLM 技能匹配失败，跳过: {e}")
        except Exception as e:
            logger.warning(f"技能匹配异常: {e}")

        # P0.4: 极简兜底——只拦截明显的危险输入
        # 不再做"是否需要工具"的硬编码判断（让 LLM 自主决定）
        user_input_lower = state.user_input.lower()
        if len(state.user_input.strip()) == 0:
            state.intent_type = "chat"
            state.confidence = 1.0
            return

        # P0.4: 极短输入（1-2字）让 LLM 自主决定，不预设意图
        # 例如用户输入"嗯"、"好"、"哦"等，让 Agent 自己理解语境
        if 1 <= len(state.user_input.strip()) <= 2:
            logger.info(f"P0.4 极短输入，让 LLM 自主决定: {state.user_input}")
            # 直接走 LLM 判断，不做任何预设
            pass

        # P0.4: LLM 自主判断（移除所有硬编码的 chat_patterns 短输入判断）
        # 信任 LLM 的语义理解能力，让 Agent 自主决定如何响应
        prompt = f"""判断用户输入的意图类型。

可选值：
- "chat": 闲聊、问候、知识问答、咨询、表达情绪、询问意见等不需要立即执行外部工具的对话
- "task": 需要调用工具才能完成的任务（搜索、查询天气、读文件、执行命令、生成图片、读写文档等）

判断准则：
- 如果 Agent 可以仅凭自身知识/推理/对话就能给出有意义的回复 → chat
- 如果 Agent 必须获取实时信息/操作外部资源/执行命令才能给出有效回复 → task
- 不确定时，优先选 chat（对话成本更低，也允许 Agent 主动决定是否调用工具）

只返回 JSON：{{"intent": "chat 或 task", "reasoning": "一句话理由"}}

用户输入: {state.user_input}"""

        try:
            response = self.model.chat([
                ChatMessage("system", "你是意图分类器，只输出 JSON。"),
                ChatMessage("user", prompt),
            ])
            parsed = extract_json(response.content)
            state.intent_type = parsed.get("intent", "chat")
            if state.intent_type not in ("chat", "task"):
                state.intent_type = "chat"  # 默认 chat（更保守，不强加工具）
            logger.info(f"P0.4 LLM 意图分类: {state.intent_type} | {parsed.get('reasoning', '')}")
        except Exception as e:
            logger.warning(f"意图分类失败，默认 chat: {e}")
            state.intent_type = "chat"

    # ============================================================
    # 阶段1.5: 任务规划（自组织）
    # ============================================================
    def _step_planning(self, state: State) -> None:
        """
        任务规划步骤（自组织能力）。
        复杂任务分解为子任务，然后真正执行子任务。
        简单任务直接跳过。
        """
        if state.intent_type == "chat":
            logger.info("闲聊模式，跳过任务规划")
            return

        try:
            t0 = time.time()
            plan = self.task_planner.plan(state.user_input)
            state.task_plan = plan
            state.task_complexity = plan.estimated_complexity

            logger.info(
                f"任务规划完成: {len(plan.subtasks)}个子任务, "
                f"复杂度={plan.estimated_complexity}, "
                f"预估工具调用={plan.estimated_tool_calls}次, "
                f"耗时={time.time() - t0:.2f}s"
            )

            if plan.reasoning:
                logger.debug(f"规划理由: {plan.reasoning}")

            # 真正执行子任务（支持并行）
            if not plan.is_simple:
                logger.info("开始执行子任务...")
                plan = self.task_executor.execute(plan, parallel=True)
                logger.info("子任务执行完成:\n" + plan.to_summary())

                # 将子任务结果汇总到 state.current_observation
                results = []
                for subtask in plan.subtasks:
                    if subtask.status == "completed" and subtask.result:
                        results.append(f"[{subtask.id}] {subtask.description}: {subtask.result}")
                    elif subtask.status == "failed":
                        results.append(f"[{subtask.id}] {subtask.description}: 失败 - {subtask.error}")

                if results:
                    state.current_observation = "\n\n".join(results)
                    # 也记录为工具调用，方便后续流程使用
                    state.tool_calls.append({
                        "tool_name": "task_planning",
                        "arguments": {"subtasks": len(plan.subtasks)},
                        "result": state.current_observation[:500],
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    })

        except Exception as e:
            logger.warning(f"任务规划失败: {e}")
            state.errors.append(f"任务规划失败: {e}")

    # ============================================================
    # 阶段4: 结果生成（兜底）
    # ============================================================
    def _step_answer(self, state: State, stream_callback: Optional[Callable[[str], None]] = None) -> None:
        """直接用 LLM 生成回答（无工具调用或兜底），注入历史记忆"""
        # P1-5: 如果 _step_tool_loop 已经生成了 final_answer，跳过本步骤避免覆盖
        if state.final_answer:
            logger.debug("P1-5: _step_tool_loop 已生成 final_answer，跳过 _step_answer")
            return

        # 构建系统提示（统一方法，注入用户画像 + 长期记忆 + 短期记忆）
        base_prompt = "你正在与用户交互。做你认为正确的事。"
        system_prompt = self._build_system_prompt(state, base_prompt)

        if state.intent_type == "chat":
            # 闲聊模式：直接回答，但带上历史记忆
            prompt = state.user_input
        else:
            # 任务模式：基于工具结果回答
            obs = "\n---\n".join(t["result"] for t in state.tool_calls) or state.current_observation
            prompt = f"""用户需求: {state.user_input}
工具结果:
{obs}

请给出清晰完整的最终回答。"""

        try:
            t0 = time.time()
            messages = [
                ChatMessage("system", system_prompt),
                ChatMessage("user", prompt),
            ]

            if stream_callback and callable(stream_callback):
                # 流式输出模式
                full_content = ""
                for chunk in self.model.chat_stream(messages):
                    full_content += chunk
                    stream_callback(chunk)
                state.final_answer = full_content
                latency_ms = (time.time() - t0) * 1000
                # P1-3: 用 tiktoken 精确统计 token（prompt + completion），替代硬编码 0
                prompt_text = system_prompt + "\n" + prompt
                self.self_awareness.record_llm_call(
                    prompt_tokens=self.self_awareness.estimate_tokens(prompt_text),
                    completion_tokens=self.self_awareness.estimate_tokens(full_content),
                    error=False,
                    latency_ms=latency_ms,
                )
            else:
                # 非流式模式
                response = self.model.chat(messages)
                latency_ms = (time.time() - t0) * 1000
                state.final_answer = response.content

                # 自感知：记录 LLM 调用
                usage = response.usage or {}
                self.self_awareness.record_llm_call(
                    prompt_tokens=usage.get("prompt_tokens", 0),
                    completion_tokens=usage.get("completion_tokens", 0),
                    error=False,
                    latency_ms=latency_ms,
                )
        except Exception as e:
            state.final_answer = f"生成回答失败: {e}"
            # 自感知：记录 LLM 调用错误
            self.self_awareness.record_llm_call(error=True)

        state.success = len(state.errors) == 0

    # ============================================================
    # 辅助方法：上下文压缩、资源感知、不确定性提示
    # ============================================================
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

        if meta.get("quality", {}).score < 50:
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
        except Exception as e:
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
            except Exception as e:
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
    def check_quiet_round_action(self, session_id: str) -> Optional[str]:
        """
        检查是否应该触发主动行为（静默轮）

        :param session_id: 会话 ID
        :return: 如果应该主动发起对话，返回主动对话内容；否则返回 None
        """
        if not self._quiet_round_enabled:
            return None

        last_time = self._last_input_time.get(session_id, 0)
        if last_time == 0:
            return None

        seconds_since = time.time() - last_time
        if seconds_since < 60:
            return None

        emotion_state = None
        if self.emotion_engine and self.emotion_engine._state:
            emotion_state = {
                "pleasure": self.emotion_engine._state.pleasure,
                "arousal": self.emotion_engine._state.arousal,
                "dominance": self.emotion_engine._state.dominance,
            }

        # P1: 优先检查行动队列（反思产生的行动具有最高优先级）
        if hasattr(self, 'action_queue'):
            try:
                highest_action = self.action_queue.get_highest_priority()
                if highest_action:
                    logger.info(f"P1 行动队列触发: {highest_action.description[:50]}")
                    system_prompt = self._build_system_prompt(State(session_id=session_id))
                    action_prompt = f"""你有一个待执行的行动：{highest_action.description}。
                    这是从自我反思中产生的行动，需要优先执行。请以自然、友好的方式发起对话，推进这个行动。

                    要求：
                    - 自然提及行动内容
                    - 保持简短
                    - 开放式结尾，鼓励用户回应"""

                    response = self.model.chat([
                        ChatMessage("system", system_prompt + "\n\n" + action_prompt),
                        ChatMessage("user", "[主动行为] 根据当前情境，生成一段自然的主动对话内容。"),
                    ])
                    content = response.content if hasattr(response, "content") else str(response)
                    # 标记行动已执行
                    self.action_queue.mark_executed(highest_action.action_id, content[:100])
                    return content
            except Exception as e:
                logger.debug(f"P1 行动队列执行失败: {e}")

        result = self.motivation_system.should_initiate_action(
            seconds_since_last_input=seconds_since,
            emotion_state=emotion_state,
            intent_tracker=self.intent_tracker if hasattr(self, 'intent_tracker') else None,
            social_relation=self.social_relation if hasattr(self, 'social_relation') else None,
            user_id=session_id,
        )

        if not result.get("should_initiate"):
            return None

        action_type = result.get("action_type", "")
        reason = result.get("reason", "")
        target = result.get("target", "")

        logger.info(f"P2.3 触发主动行为: type={action_type}, reason={reason}, target={target}")

        system_prompt = self._build_system_prompt(State(session_id=session_id))

        action_prompts = {
            "curiosity": f"""基于以下信息，主动发起关于「{target}」的对话。
            你对这个概念感到好奇，想了解更多。请以自然、友好的方式提出问题或分享想法。

            要求：
            - 不要生硬，像自然想到一样
            - 保持简短（3-5句话）
            - 开放式问题，鼓励用户回应""",

            "concern": """用户之前有些不满，现在已经很久没说话了。
            请主动关心用户的状态，表达理解和支持。

            要求：
            - 温和、真诚
            - 不要质问，而是表达关心
            - 给用户空间，如果用户不想聊可以轻松带过""",

            "goal_tracking": f"""你有一个进行中的目标：{target}。
            用户很久没说话了，主动更新一下这个目标的进展，或者询问用户是否需要帮助。

            要求：
            - 自然提及目标
            - 保持简短
            - 如果目标已完成，分享成就感；如果未完成，表达继续努力的意愿""",

            "check_in": """用户很久没说话了，主动打招呼问候一下。

            要求：
            - 友好、轻松
            - 可以提及最近的共同经历或话题
            - 简短，不超过2句话""",

            "emotion_seeking": """你现在心情不太好，想与人交流。
            请以适当的方式表达你的情绪，寻求互动。

            要求：
            - 真诚但不过度暴露
            - 简短表达当前感受
            - 开放式结尾，鼓励用户回应""",

            "intent_followup": f"""用户有一个未完成的意图：{target}。
            用户很久没说话了，主动跟进一下这个意图的进展。

            要求：
            - 自然提及意图内容
            - 根据意图进度选择合适的表达方式（未开始→询问是否需要帮助；进行中→询问进度；接近完成→确认收尾）
            - 保持简短
            - 开放式结尾，鼓励用户回应""",

            "relation_care": f"""你和用户关系不错，用户很久没说话了。
            请以朋友的方式主动关心一下近况，表达想念和关心。

            要求：
            - 亲切、自然，像朋友一样
            - 不要太正式
            - 简短温暖
            - 可以提及你们的共同经历""",

            "relation_streak": f"""你和用户已经连续互动好几天了，用户今天还没说话。
            请主动打个招呼，保持互动节奏。

            要求：
            - 轻松、随意
            - 可以暗示"今天是连续第N天"但不要生硬
            - 简短，自然开场""",
        }

        action_prompt = action_prompts.get(action_type, action_prompts["check_in"])

        try:
            response = self.model.chat([
                ChatMessage("system", system_prompt + "\n\n" + action_prompt),
                ChatMessage("user", "[主动行为] 根据当前情境，生成一段自然的主动对话内容。"),
            ])
            return response.content.strip()
        except Exception as e:
            logger.warning(f"P2.3 主动行为生成失败: {e}")
            return None

    def set_last_input_time(self, session_id: str, timestamp: float = None):
        """设置上次用户输入时间（用于静默轮检测）"""
        self._last_input_time[session_id] = timestamp or time.time()

    def get_time_since_last_input(self, session_id: str) -> float:
        """获取距离上次用户输入的秒数"""
        last_time = self._last_input_time.get(session_id, 0)
        if last_time == 0:
            return float('inf')
        return time.time() - last_time
