"""
自研 Agent 主循环 (CastoriceAgent)

复刻 Hermes Agent 架构，彻底移除 LangGraph：
- 手写主循环：阶段化执行
- LLM 驱动工具调用：让模型决定用哪个工具、传什么参数
- 状态对象：State 数据类管理运行时数据
"""

import asyncio
import difflib
import json
import logging
import re
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

logger = logging.getLogger("Castorice.Agent")

# 工具调用最大轮数（防止无限循环）
MAX_TOOL_ROUNDS = 5

# P1-1: 并行工具执行时保护 state.tool_calls 的锁
_state_tool_calls_lock = threading.Lock()

# 审计日志懒加载单例
_audit_logger = None

# 告警管理器懒加载单例
_alert_manager_ref = None


def _get_audit_logger():
    """获取审计日志记录器（懒加载）"""
    global _audit_logger
    if _audit_logger is None:
        try:
            from castorice.security.audit_log import get_audit_logger as _get
            _audit_logger = _get()
        except Exception:
            return None
    return _audit_logger


def _get_alert_manager():
    """获取告警管理器（懒加载，避免 agent.py 顶部强依赖 alerts 模块）"""
    global _alert_manager_ref
    if _alert_manager_ref is None:
        try:
            from castorice.alerts import get_alert_manager as _get
            _alert_manager_ref = _get()
        except Exception:
            return None
    return _alert_manager_ref


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
    task_plan: Optional[TaskPlan] = None  # 任务规划结果（子任务列表）
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
    short_term_context: str = ""         # 短期记忆（当前会话历史对话）
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


class CastoriceAgent:
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
        # P1-32: default_workflow 已删除——动态工作流选择器才是实际机制，
        # 保留 default_workflow 配置会误导用户以为静态选择生效

        # 自感知模块
        model_name = self._get_model_name(model_adapter)
        self.self_awareness = SelfAwareness(tools=tools, model_name=model_name)

        # 自组织模块
        self.task_planner = TaskPlanner(model_adapter, tools=tools)
        self.task_executor = TaskExecutor(tools=self.tools)
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
        state = State(user_input=user_input, session_id=session_id)

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

        # 注入上下文：长期记忆（跨会话）
        # P1-2: 用 session_id 过滤，避免多用户场景下隐私泄露
        # P2-1: 检索 query 改用与保存时一致的格式，提升召回率
        try:
            retrieval_query = f"用户指令: {user_input}"
            # P1-2: 单用户场景（session_id 为单会话标识）不传 where；
            # 多用户场景应在外层传入 user_id 并写入 metadata，这里保持向后兼容
            state.relevant_history = await asyncio.to_thread(
                self.long_term.get_relevant_context, retrieval_query
            ) or ""
            if state.relevant_history:
                logger.info(f"长期记忆检索到相关上下文: {len(state.relevant_history)} 字符")
        except Exception as e:
            logger.warning(f"长期记忆检索失败: {e}")
            state.relevant_history = ""

        # P1.1: 经历流实时注入——检索与当前话题相关的历史经历
        try:
            if self.experience_journal is not None:
                recent_experiences = await asyncio.to_thread(
                    self.experience_journal.search,
                    user_input, top_k=3, min_importance=4.0
                )
                if recent_experiences:
                    exp_lines = []
                    for exp in recent_experiences[:3]:
                        content = exp.get("content", "")
                        if content:
                            exp_lines.append(f"- {content[:150]}")
                    if exp_lines:
                        state.relevant_experiences = "\n".join(exp_lines)
                        logger.info(f"P1.1 经历流注入: {len(exp_lines)} 条相关经历")
        except Exception as e:
            logger.warning(f"P1.1 经历流检索失败: {e}")
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
            state.short_term_context = self._compress_context(state.short_term_context)

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
            if step == "intent" and state.intent_type is not None:
                # 动态选择路径下 intent 已提前执行，跳过
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
                    confidence = getattr(state.metacognition_result, "overall_score", 1.0)
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

        logger.debug("arun_impl 即将返回 state")
        return state
    
    def _get_workflow_steps(self, workflow_name: str) -> List[str]:
        """获取工作流模板的步骤列表"""
        if not self.workflows or workflow_name not in self.workflows:
            logger.warning(f"工作流模板 '{workflow_name}' 不存在，使用标准流程")
            return ["intent", "tool_loop", "answer", "reflection", "memory", "skill"]
        
        workflow = self.workflows.get(workflow_name, {})
        return workflow.get("steps", ["intent", "tool_loop", "answer", "reflection", "memory", "skill"])
    
    async def _execute_step(self, step: str, state: State, stream_callback: callable = None) -> None:
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
    # 公共工具：构建系统提示（消除重复注入）
    # ============================================================
    def _build_system_prompt(self, state: State, base_prompt: str = "") -> str:
        """
        统一构建系统提示，注入：
        - 基础提示（角色/工具说明）
        - L1 性格设定（静态人格）
        - 当前时间（确保 Agent 知道当前日期）
        - L2 当前情绪状态（动态 PAD 状态）
        - 思维策略
        - 对话风格调整
        - 用户画像
        - 长期记忆（跨会话知识）
        - 短期记忆（当前会话历史对话）
        - L4 主动关心提示（检测到近期负面事件时）

        避免在 _step_tool_loop 和 _step_answer 中重复拼装。
        """
        parts = [base_prompt] if base_prompt else []

        # L1: 注入性格设定（静态人格）
        try:
            parts.append(self.emotion_engine.get_personality_prompt())
        except Exception as e:
            logger.warning(f"L1 性格设定注入失败: {e}")

        # 注入当前时间（关键：确保 Agent 知道当前日期）
        from datetime import datetime, timezone
        now_local = datetime.now()
        now_utc = datetime.now(timezone.utc)
        week_days = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
        parts.append(
            f"## 当前时间\n"
            f"本地时间: {now_local.strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"UTC时间: {now_utc.strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"星期: {week_days[now_local.weekday()]}\n"
            f"年份: {now_local.year}"
        )

        # L2: 注入当前情绪状态
        if state.emotion_state_prompt:
            parts.append(state.emotion_state_prompt)

        # 注入思维策略
        if state.thinking_strategy_prompt:
            parts.append(f"## 思维策略\n{state.thinking_strategy_prompt}")

        # 注入对话风格调整
        if state.dialogue_adjustment:
            parts.append(state.dialogue_adjustment)

        # 注入长期记忆（跨会话知识）
        # P2-5: 按文档切片截断，避免硬截断在记忆条目中间
        if state.relevant_history:
            truncated = self._truncate_by_doc_boundary(state.relevant_history, 1500)
            parts.append(f"## 相关长期记忆\n{truncated}")

        # P1.1: 注入相关经历（让 Agent 记得自己过去做过的类似事情）
        if state.relevant_experiences:
            parts.append(f"## 相关经历\n{state.relevant_experiences}\n（以上是我过去与用户交互的相关经历，可作为参考）")

        # 注入短期记忆（当前会话历史对话）
        # P3-2: short_term_context 是死字段（从未被赋值），历史对话已通过 history_messages 注入
        # 保留字段定义以兼容已序列化的 State，但移除死分支

        # 注入用户画像
        if state.user_profile_context:
            parts.append(f"## 用户画像\n{state.user_profile_context}")

        # L4: 注入主动关心提示（最后强调，让 LLM 优先处理）
        if state.emotion_care_hint:
            parts.append(state.emotion_care_hint)

        # P1.2: 注入最近反思信号（让 Agent 知道自己上次反思学到了什么）
        if state.recent_reflection_signal:
            parts.append(f"## 最近反思\n{state.recent_reflection_signal}")

        # P1.3: 注入当前动机（情感→动机→行为闭环）
        if state.current_motivations:
            motivations_text = "\n".join(f"- {m}" for m in state.current_motivations)
            parts.append(f"## 当前动机\n{motivations_text}\n（这些是我此刻想做事的意愿，可作为决策参考）")

        return "\n\n".join(parts) if parts else ""

    @staticmethod
    def _smart_truncate_message(content: str, max_chars: int = 1200) -> str:
        """
        P2-4: 智能截断消息，保留代码块完整性。

        - 如果内容未超长，直接返回
        - 如果包含 ``` 代码块，尽量在代码块边界截断
        - 否则在最近的句号/换行处截断，避免硬切断单词
        """
        if not content or len(content) <= max_chars:
            return content

        # 尝试在代码块边界截断
        code_fence_positions = []
        idx = 0
        while True:
            pos = content.find("```", idx)
            if pos == -1:
                break
            code_fence_positions.append(pos)
            idx = pos + 3

        # 找到 max_chars 之前最后一个完整的代码块结束位置
        best_cut = max_chars
        for i in range(0, len(code_fence_positions) - 1, 2):
            fence_end = code_fence_positions[i + 1] + 3
            if fence_end <= max_chars:
                best_cut = fence_end
            else:
                break

        # 如果没找到合适的代码块边界，在最近的句号/换行处截断
        if best_cut >= max_chars:
            for cut_char in ['\n', '。', '！', '？', '.', '!', '?']:
                pos = content.rfind(cut_char, 0, max_chars)
                if pos > max_chars * 0.5:
                    best_cut = pos + 1
                    break

        return content[:best_cut].rstrip() + "\n...(已截断)"

    @staticmethod
    def _truncate_by_doc_boundary(text: str, max_chars: int) -> str:
        """
        P2-5: 按文档切片边界截断，避免在记忆条目中间硬截断。
        记忆条目间用 '\\n---\\n' 分隔。
        """
        if not text or len(text) <= max_chars:
            return text

        # 按分隔符切分
        docs = text.split("\n---\n")
        result = []
        current_len = 0
        for doc in docs:
            if current_len + len(doc) + 5 > max_chars:  # +5 for separator
                break
            result.append(doc)
            current_len += len(doc) + 5

        if not result:
            # 单条记忆就超长，返回截断的第一条
            return docs[0][:max_chars].rstrip() + "...(已截断)"

        return "\n---\n".join(result)

    # ============================================================
    # 阶段1: 意图解析
    # ============================================================
    def _step_intent(self, state: State) -> None:
        """判断用户意图：纯闲聊 vs 需要工具的任务（P0.4: LLM 优先，规则仅做安全兜底）"""
        # 技能匹配（这是合理的能力路由，不是限制自由）
        try:
            matches = self.skill_memory.match(state.user_input, top_n=1)
            if matches and matches[0].enabled:
                top = matches[0]
                if any(kw.lower() in state.user_input.lower() for kw in top.trigger_keywords):
                    state.intent_type = "task"
                    state.matched_skill_id = top.id
                    state.confidence = 0.95
                    return
        except Exception as e:
            logger.warning(f"技能匹配异常: {e}")

        # P0.4: 极简兜底——只拦截明显的危险输入
        # 不再做"是否需要工具"的硬编码判断（让 LLM 自主决定）
        user_input_lower = state.user_input.lower()
        if len(state.user_input.strip()) == 0:
            state.intent_type = "chat"
            state.confidence = 1.0
            return

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
    # 阶段2-3: LLM 驱动工具调用循环
    # ============================================================
    def _step_tool_loop(self, state: State, stream_callback: callable = None) -> None:
        """
        核心工具调用循环（原生 Function Calling 优先，JSON 解析兜底）：
        1. 把用户需求 + 可用工具 schema 传给 LLM
        2. LLM 通过 Function Calling 返回 tool_calls（支持并行多个）
        3. 并行执行所有 tool_calls，把结果喂回 LLM
        4. LLM 决定是否继续调用工具或给出最终答案

        P1-1: 当 stream_callback 存在且 LLM 在最后一轮直接生成最终答案时，启用流式输出。
        P1-7: 如果 _step_planning 已经执行过子任务并把结果汇总到 state.current_observation，注入到上下文。
        """
        # 生成工具 schema（OpenAI 格式）
        tool_schemas = [t.to_openai_schema() for t in self.tools_list]
        use_native_fc = self.model.supports_tools

        # 构建系统提示
        base_prompt = f"""你是 Castorice Agent，一个能调用工具的智能助手。

你有以下工具可用：
{state.available_tools_desc}

规则：
1. 需要实时信息（天气、新闻、股价等）时，使用合适的工具
2. 基于工具返回结果给出清晰完整的回答
3. 用中文回答
4. 【重要】工具返回结果中的 Markdown 图片格式（![描述](URL)）必须原样保留在最终回答中，不要改成链接或文字"""

        system_prompt = self._build_system_prompt(state, base_prompt)

        messages = [ChatMessage("system", system_prompt)]
        # P0-1: 注入历史对话消息（多轮上下文，让 LLM 理解指代与追问）
        for msg in state.history_messages:
            messages.append(msg)
        # P1-7: 注入 planning 阶段产生的子任务执行结果（避免与 _step_planning 职责重叠：
        # _step_planning 负责执行子任务并写入 current_observation，这里负责把结果交给 LLM 使用）
        if state.current_observation:
            messages.append(ChatMessage(
                "user",
                f"【任务规划阶段已完成的子任务结果】\n{state.current_observation[:1500]}\n\n"
                f"请基于以上结果继续处理用户需求，或调用更多工具。"
            ))
        messages.append(ChatMessage("user", f"用户需求: {state.user_input}"))

        for round_num in range(MAX_TOOL_ROUNDS):
            try:
                # P1-2: 消息列表压缩 - 超阈值时压缩早期 tool 结果（保留最近 2 轮）
                self._maybe_compress_tool_messages(messages)

                t0 = time.time()

                if use_native_fc:
                    # 原生 Function Calling
                    response = self.model.chat_with_tools(messages, tools=tool_schemas)
                    content = response.content
                    tool_calls = response.tool_calls
                else:
                    # 兜底：JSON 解析模式（仅支持单个 tool_call）
                    response = self.model.chat(messages)
                    content = response.content.strip()
                    tool_calls = self._parse_json_tool_calls(content)
                    if not tool_calls:
                        decision = extract_json(content)
                        if decision.get("action") == "answer":
                            state.final_answer = decision.get("answer", content)
                            state.success = True
                            return
                        tc_name = decision.get("tool", "")
                        tc_args = decision.get("args", {})
                        if tc_name:
                            tool_calls = [{"id": f"json_{round_num}", "name": tc_name, "arguments": tc_args}]

                latency_ms = (time.time() - t0) * 1000
                logger.info(
                    f"工具循环 第{round_num + 1}轮 LLM响应: "
                    f"{content[:200] if content else '(tool_calls)'} | tool_calls数={len(tool_calls) if tool_calls else 0}"
                )

                # 自感知：记录 LLM 调用
                usage = response.usage or {}
                self.self_awareness.record_llm_call(
                    prompt_tokens=usage.get("prompt_tokens", 0),
                    completion_tokens=usage.get("completion_tokens", 0),
                    error=False,
                    latency_ms=latency_ms,
                )

                # 无 tool_calls → 模型直接给出最终回答
                if not tool_calls:
                    final_text = content or "抱歉，我无法完成这个任务。"
                    # P1-1: 流式回调存在时，把已生成的 content 分块推送（伪流式，避免重复调用 LLM）
                    if stream_callback and callable(stream_callback):
                        # P1-3: 按句子/标点切分，但不能在 URL 中间切分（否则破坏 Markdown 图片）
                        # 策略：先用占位符保护所有 Markdown 图片 URL，切分后再还原
                        chunks = self._split_for_streaming(final_text)
                        for chunk in chunks:
                            if chunk:
                                stream_callback(chunk)
                    state.final_answer = final_text
                    state.success = True
                    return

                # 归一化 tool_calls 为字典列表（统一处理 dict 和 ToolCall 对象）
                normalized_calls = []
                for tc in tool_calls:
                    if isinstance(tc, dict):
                        normalized_calls.append({
                            "id": tc.get("id", f"tc_{round_num}_{len(normalized_calls)}"),
                            "name": tc.get("name", ""),
                            "arguments": tc.get("arguments", {}),
                        })
                    elif hasattr(tc, "id") and hasattr(tc, "name"):
                        normalized_calls.append({
                            "id": getattr(tc, "id", f"tc_{round_num}_{len(normalized_calls)})"),
                            "name": getattr(tc, "name", ""),
                            "arguments": getattr(tc, "arguments", {}),
                        })
                    else:
                        logger.warning(f"无法解析 tool_call: {tc}")

                # 多 tool_calls 并行执行（线程池），单 tool_call 直接同步执行
                if len(normalized_calls) == 1:
                    result_msgs = [self._execute_single_tool_call(
                        normalized_calls[0], state, content, use_native_fc
                    )]
                else:
                    result_msgs = self._execute_tool_calls_parallel(
                        normalized_calls, state, content, use_native_fc
                    )

                # 把所有结果消息追加到 messages
                # 先追加一条 assistant 消息（带所有 tool_calls）
                if use_native_fc:
                    all_tool_calls = [
                        ToolCall(id=tc["id"], name=tc["name"], arguments=tc["arguments"])
                        for tc in normalized_calls
                    ]
                    messages.append(ChatMessage(
                        role="assistant", content=content, tool_calls=all_tool_calls
                    ))
                    # 再追加每条 tool 结果消息
                    for rm in result_msgs:
                        if rm:  # 跳过 None（被拒绝/未执行的）
                            messages.append(rm)
                else:
                    # JSON 模式：合并所有工具结果到一条 user 消息
                    messages.append(ChatMessage("assistant", content))
                    combined = "\n\n".join(
                        rm.content for rm in result_msgs if rm
                    )
                    messages.append(ChatMessage("user",
                        f"{combined}\n\n请基于以上工具结果回答用户问题，或继续调用工具。"))

            except Exception as e:
                logger.warning(f"工具循环第{round_num + 1}轮异常: {e}")
                state.errors.append(str(e))
                self.self_awareness.record_llm_call(error=True)
                break

        # 循环结束仍未得到答案
        if not state.final_answer:
            if state.current_observation:
                state.final_answer = f"基于工具执行结果: {state.current_observation[:500]}"
            else:
                state.final_answer = "抱歉，经过多轮尝试仍未能完成任务。"

            # P0-3: 告警系统接入 - 工具循环超限
            try:
                _get_alert_manager().warning(
                    title="工具循环超限",
                    message=f"session={state.session_id} 达到最大轮数 {MAX_TOOL_ROUNDS} 仍未完成。用户需求: {state.user_input[:150]}",
                    cooldown_key=f"tool_loop_overflow_{state.session_id}",
                )
            except Exception as e:
                logger.warning(f"工具循环超限告警发送失败: {e}")

    def _parse_json_tool_calls(self, content: str) -> List[Dict[str, Any]]:
        """从 LLM 文本响应中解析 JSON 格式的工具调用（兜底用）"""
        try:
            decision = extract_json(content)
            if decision.get("action") == "tool":
                return [{
                    "id": f"parsed_{int(time.time())}",
                    "name": decision.get("tool", ""),
                    "arguments": decision.get("args", {}),
                }]
        except Exception as e:
            logger.warning(f"JSON 工具调用解析失败: {e}")
        return []

    # ============================================================
    # 工具执行辅助：单工具执行 + 多工具并行执行
    # ============================================================
    def _execute_single_tool_call(
        self,
        tc: Dict[str, Any],
        state: State,
        content: str,
        use_native_fc: bool,
    ) -> Optional[ChatMessage]:
        """
        执行单个 tool_call，返回要追加到 messages 的工具结果消息。

        返回：
        - ChatMessage (role="tool" 或 role="user")：执行成功/失败/拒绝/不存在
        - None：理论上不会返回 None，但保留接口以防特殊情况
        """
        tool_name = tc["name"]
        tool_args = tc["arguments"]
        tc_id = tc["id"]

        # 1. 工具不存在 → 模糊匹配推荐
        if tool_name not in self.tools:
            close_matches = difflib.get_close_matches(tool_name, self.tools.keys(), n=3, cutoff=0.5)
            if close_matches:
                suggestion = f"你是不是想用: {', '.join(close_matches)}？"
            else:
                suggestion = f"可用工具: {', '.join(sorted(self.tools.keys()))}"
            error_feedback = f"工具 '{tool_name}' 不存在。{suggestion}"
            logger.warning(f"工具不存在: {tool_name} | 建议: {close_matches}")

            if use_native_fc:
                return ChatMessage(
                    role="tool", content=error_feedback,
                    tool_call_id=tc_id, name=tool_name,
                )
            else:
                return ChatMessage("user", f"工具 '{tool_name}' 不存在。可用工具: {', '.join(self.tools.keys())}。请用其他工具或直接回答。")

        # 2. L3: 情绪拒绝工具
        tool = self.tools[tool_name]
        try:
            refuse, refuse_reason = self.emotion_engine.should_refuse_tool(tool_name)
            if refuse:
                logger.info(f"L3 情绪拒绝工具: {tool_name} - {refuse_reason}")
                with _state_tool_calls_lock:
                    state.tool_calls.append({
                        "tool_name": tool_name,
                        "arguments": tool_args,
                        "result": f"[情绪拒绝] {refuse_reason}",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    })
                if use_native_fc:
                    return ChatMessage(
                        role="tool", content=refuse_reason,
                        tool_call_id=tc_id, name=tool_name,
                    )
                else:
                    return ChatMessage("user", refuse_reason + " 请直接用你自己的话回答用户。")
        except Exception as e:
            logger.warning(f"L3 情绪拒绝检查失败: {e}")

        # 3. 执行工具
        try:
            t_tool = time.time()
            result = tool.invoke(tool_args)
            tool_latency_ms = (time.time() - t_tool) * 1000
            result_str = str(result)[:2000]

            with _state_tool_calls_lock:
                state.tool_calls.append({
                    "tool_name": tool_name,
                    "arguments": tool_args,
                    "result": result_str[:500],
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })
            # 多工具并行时，最后一个执行的会覆盖 current_observation（可接受）
            state.current_observation = result_str
            logger.info(f"工具 {tool_name} 执行成功 ({tool_latency_ms:.0f}ms)，结果: {result_str[:100]}")

            # 自感知：记录工具调用成功
            self.self_awareness.record_tool_call(
                tool_name=tool_name,
                success=True,
                latency_ms=tool_latency_ms,
            )

            # 审计日志：从工具元数据读取风险等级
            audit = _get_audit_logger()
            if audit:
                audit.log_tool_call(
                    user_id=state.session_id,
                    session_id=state.session_id,
                    tool_name=tool_name,
                    args=tool_args,
                    result=result_str[:200],
                    risk_level=tool.risk_level,
                )

            if use_native_fc:
                return ChatMessage(
                    role="tool", content=result_str,
                    tool_call_id=tc_id, name=tool_name,
                )
            else:
                return ChatMessage("user",
                    f"工具 {tool_name} 返回结果:\n{result_str}")

        except Exception as e:
            error_msg = f"工具 {tool_name} 执行失败: {e}"
            state.errors.append(error_msg)
            logger.warning(error_msg)

            # P0-3: 告警系统接入 - 工具执行失败
            try:
                _get_alert_manager().warning(
                    title="工具执行失败",
                    message=f"session={state.session_id} tool={tool_name} error={str(e)[:200]}",
                    cooldown_key=f"tool_fail_{tool_name}",
                )
            except Exception as e:
                logger.warning(f"工具执行失败告警发送失败: {e}")

            self.self_awareness.record_tool_call(
                tool_name=tool_name,
                success=False,
                latency_ms=0,
                error_msg=str(e),
            )

            audit = _get_audit_logger()
            if audit:
                audit.log_tool_call(
                    user_id=state.session_id,
                    session_id=state.session_id,
                    tool_name=tool_name,
                    args=tool_args,
                    result=f"ERROR: {error_msg[:100]}",
                    risk_level="high",
                )

            if use_native_fc:
                return ChatMessage(
                    role="tool", content=error_msg,
                    tool_call_id=tc_id, name=tool_name,
                )
            else:
                return ChatMessage("user", f"{error_msg}\n请换一种方式或直接回答。")

    def _execute_tool_calls_parallel(
        self,
        tool_calls: List[Dict[str, Any]],
        state: State,
        content: str,
        use_native_fc: bool,
    ) -> List[Optional[ChatMessage]]:
        """
        并行执行多个 tool_calls（使用线程池）

        保证返回结果顺序与输入 tool_calls 顺序一致（便于 FC 模式回传对应 tool_call_id）。
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed

        results: List[Optional[ChatMessage]] = [None] * len(tool_calls)

        with ThreadPoolExecutor(max_workers=min(4, len(tool_calls))) as executor:
            future_to_idx = {}
            for idx, tc in enumerate(tool_calls):
                future = executor.submit(
                    self._execute_single_tool_call, tc, state, content, use_native_fc
                )
                future_to_idx[future] = idx

            for future in as_completed(future_to_idx):
                idx = future_to_idx[future]
                try:
                    results[idx] = future.result()
                except Exception as e:
                    logger.warning(f"并行执行 tool_call[{idx}] 异常: {e}")
                    state.errors.append(f"并行工具执行异常: {e}")
                    # 兜底：返回一条错误消息
                    tc = tool_calls[idx]
                    tc_id = tc.get("id", "")
                    tc_name = tc.get("name", "")
                    if use_native_fc:
                        results[idx] = ChatMessage(
                            role="tool", content=f"并行执行异常: {e}",
                            tool_call_id=tc_id, name=tc_name,
                        )
                    else:
                        results[idx] = ChatMessage("user", f"工具 {tc_name} 并行执行异常: {e}")

        logger.info(f"并行执行 {len(tool_calls)} 个工具完成")
        return results

    # 消息列表压缩阈值（字符数近似 token 数，中文1字≈1.5token，留 30% 余量）
    TOOL_MESSAGES_CHAR_LIMIT = 12000  # 超过此阈值触发压缩
    TOOL_MESSAGES_KEEP_RECENT = 4     # 保留最近的 N 条消息（2 轮 = 2 assistant + 2 tool）

    def _maybe_compress_tool_messages(self, messages: List[ChatMessage]) -> None:
        """
        P1-2: 压缩 _step_tool_loop 中的消息列表

        - 估算所有消息总字符数
        - 超阈值时，把早期 tool 消息的 content 截断为摘要
        - 保留最近 2 轮（4 条消息）的完整内容
        - 不动 system 和最初的 user 消息
        """
        total_chars = sum(len(m.content or "") for m in messages)
        if total_chars <= self.TOOL_MESSAGES_CHAR_LIMIT:
            return

        # 找到要压缩的范围：跳过 system + 初始 user，保留最后 N 条
        # messages 结构：[system, user, assistant, tool, assistant, tool, ...]
        if len(messages) <= self.TOOL_MESSAGES_KEEP_RECENT + 2:
            return  # 消息太少，不压缩

        # 从第 2 条（index=2，第一条 assistant）开始压缩，到倒数第 KEEP_RECENT 条
        compress_end = len(messages) - self.TOOL_MESSAGES_KEEP_RECENT
        compressed_count = 0
        for i in range(2, compress_end):
            msg = messages[i]
            # 只压缩 tool 角色消息（含工具结果，通常最长）
            if msg.role == "tool" and msg.content and len(msg.content) > 200:
                original_len = len(msg.content)
                # 保留前 100 字符 + 后 50 字符 + 省略号
                msg.content = (
                    msg.content[:100]
                    + f"\n...[已压缩，原始 {original_len} 字符]...\n"
                    + msg.content[-50:]
                )
                compressed_count += 1
            # 也压缩 assistant 消息中的长 content（工具调用的 reasoning）
            elif msg.role == "assistant" and msg.content and len(msg.content) > 300:
                original_len = len(msg.content)
                msg.content = msg.content[:150] + f"\n...[已压缩，原始 {original_len} 字符]..."
                compressed_count += 1

        if compressed_count > 0:
            new_total = sum(len(m.content or "") for m in messages)
            logger.info(
                f"P1-2 消息压缩: 压缩 {compressed_count} 条消息，"
                f"总字符 {total_chars} → {new_total} (节省 {total_chars - new_total})"
            )

    # ============================================================
    # 阶段4: 结果生成（兜底）
    # ============================================================
    def _step_answer(self, state: State, stream_callback: callable = None) -> None:
        """直接用 LLM 生成回答（无工具调用或兜底），注入历史记忆"""
        # P1-5: 如果 _step_tool_loop 已经生成了 final_answer，跳过本步骤避免覆盖
        if state.final_answer:
            logger.debug("P1-5: _step_tool_loop 已生成 final_answer，跳过 _step_answer")
            return

        # 构建系统提示（统一方法，注入用户画像 + 长期记忆 + 短期记忆）
        base_prompt = "你是 Castorice Agent，自进化智能体。用中文回答。"
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
    # 阶段5: 反思
    # ============================================================
    async def _step_reflection(self, state: State) -> None:
        # 如果配置禁用了反思，跳过
        if not self.enable_reflection:
            return

        # L3: 兴奋时跳过反思（高唤醒 → 反应快，不走深度反思）
        try:
            workflow_adj = self.emotion_engine.get_workflow_adjustment()
            if workflow_adj.get("skip_reflection"):
                logger.info("L3: 当前情绪兴奋(arousal高)，跳过反思步骤")
                state.reflection_summary = "[情绪兴奋，跳过反思]"
                return
        except Exception as e:
            logger.warning(f"L3 反思跳过检查失败: {e}")

        tool_summary = "\n".join(f"- {t['tool_name']}: {t['result'][:200]}" for t in state.tool_calls)

        # 如果配置禁用了技能生成，不请求 LLM 生成技能提案
        skill_prompt = ""
        if self.enable_skill_generation:
            skill_prompt = """,
    "should_generate_skill": true/false,
    "skill_proposal": {{
        "name": "技能名", "trigger_keywords": ["kw1"],
        "description": "描述", "steps": [{{"tool": "工具名", "参数": "值"}}]
    }}"""
        else:
            skill_prompt = """,
    "should_generate_skill": false"""

        prompt = f"""复盘以下任务执行，输出 JSON：
{{
    "summary": "复盘总结",
    "suggestions": ["改进建议"]{skill_prompt}
}}

任务: {state.user_input}
错误: {state.errors}
工具调用:
{tool_summary}"""

        try:
            response = await asyncio.to_thread(
                self.model.chat,
                [
                    ChatMessage("system", "你是复盘专家，只输出 JSON。"),
                    ChatMessage("user", prompt),
                ],
            )
            parsed = extract_json(response.content)
            state.reflection_summary = parsed.get("summary", "")
            state.improvement_suggestions = parsed.get("suggestions", [])
            # 只有配置启用技能生成时，才处理技能提案
            if self.enable_skill_generation and parsed.get("should_generate_skill") and parsed.get("skill_proposal", {}).get("name"):
                state.skill_to_generate = parsed["skill_proposal"]
        except Exception as e:
            logger.warning(f"反思失败: {e}")

    # ============================================================
    # 阶段6: 记忆归档
    # ============================================================
    async def _step_memory(self, state: State) -> None:
        try:
            # 记录交互计数（user_profile 之前从未被更新，导致名字等持久信息丢失）
            try:
                await asyncio.to_thread(self.user_profile.record_interaction)
            except Exception as e:
                logger.debug(f"用户画像交互计数失败: {e}")

            # 自动提取用户画像信息（从用户输入中识别名字等关键信息）
            try:
                await self._extract_user_profile(state.user_input)
            except Exception as e:
                logger.debug(f"用户画像提取失败: {e}")

            memory_text = f"用户指令: {state.user_input}\n执行结果: {state.final_answer}"
            if state.reflection_summary:
                memory_text += f"\n反思: {state.reflection_summary}"
            
            memory_text = self._sanitize_memory_text(memory_text)

            # 记忆写入前验证：判断这条记忆是否值得保存
            should_save = await asyncio.to_thread(
                self._validate_memory_before_write,
                state.user_input, state.final_answer, state.session_id
            )
            
            if not should_save:
                logger.info(f"记忆验证不通过，跳过写入: {state.user_input[:30]}...")
                return

            # P1-2: long_term.add() 和 short_term.update_summary() 是同步阻塞操作，
            # 用 asyncio.to_thread 避免阻塞事件循环
            await asyncio.to_thread(
                self.long_term.add,
                text=memory_text,
                metadata={
                    "type": "task_summary",
                    "session_id": state.session_id,
                    "success": state.success,
                    "intent": state.intent_type,
                },
            )
            summary = state.user_input[:50] + ("..." if len(state.user_input) > 50 else "")
            await asyncio.to_thread(
                self.short_term.update_summary, state.session_id, summary
            )
        except Exception as e:
            logger.warning(f"长期记忆写入失败: {e}")

    def _sanitize_memory_text(self, memory_text: str) -> str:
        """
        清理记忆文本中的错误信息。
        
        主要过滤：
        - LLM回复中错误的身份假设（如"你叫XXX"、"你是XXX"）
        - 避免将LLM的猜测当作事实写入记忆
        """
        import re
        
        current_name = self.user_profile.get("identity.name", "")
        
        lines = memory_text.split('\n')
        new_lines = []
        
        for line in lines:
            skip_line = False
            
            if current_name:
                patterns_to_remove = [
                    rf'你叫\s*{re.escape(current_name)}',
                    rf'你的名字是\s*{re.escape(current_name)}',
                    rf'你的名字叫\s*{re.escape(current_name)}',
                ]
                for pattern in patterns_to_remove:
                    if re.search(pattern, line):
                        skip_line = True
                        break
            else:
                identity_claim_patterns = [
                    r'你叫\s*[A-Za-z\u4e00-\u9fa5][A-Za-z\u4e00-\u9fa5·\s]{0,20}',
                    r'你是\s*[A-Za-z\u4e00-\u9fa5][A-Za-z\u4e00-\u9fa5·\s]{0,20}',
                    r'你的名字是\s*[A-Za-z\u4e00-\u9fa5][A-Za-z\u4e00-\u9fa5·\s]{0,20}',
                    r'你的名字叫\s*[A-Za-z\u4e00-\u9fa5][A-Za-z\u4e00-\u9fa5·\s]{0,20}',
                ]
                for pattern in identity_claim_patterns:
                    if re.search(pattern, line):
                        skip_line = True
                        break
            
            question_patterns = [
                r'你是谁',
                r'我是谁',
                r'你还记得么',
                r'你认识我吗',
                r'知道我是谁',
                r'还记得我吗',
            ]
            if any(q in line for q in question_patterns):
                skip_line = True
            
            if not skip_line:
                new_lines.append(line)
        
        return '\n'.join(new_lines).strip()

    def _validate_memory_before_write(
        self, user_input: str, answer: str, session_id: str
    ) -> bool:
        """
        记忆写入前验证：使用规则匹配判断这条记忆是否值得保存。
        
        过滤规则：
        - 纯粹的闲聊（如"你好"、"在吗"、"谢谢"）不需要保存
        - 问候语不需要保存
        - 太短的输入不需要保存
        """
        chat_patterns = [
            "你好", "嗨", "hello", "hi", "在吗", "谢谢", "谢谢",
            "再见", "拜拜", "晚安", "早安", "下午好", "晚上好",
        ]
        
        user_input_lower = user_input.lower().strip()
        
        if len(user_input_lower) <= 3:
            logger.debug(f"记忆验证: 输入太短，跳过保存")
            return False
        
        if any(p.lower() in user_input_lower for p in chat_patterns):
            logger.debug(f"记忆验证: 闲聊问候，跳过保存")
            return False
        
        return True

    async def _reflect_on_memory_quality(self, session_id: str) -> None:
        """
        自我修正：定期检查记忆质量，发现并修正错误记忆。
        
        每10轮对话触发一次，检查最近的记忆条目是否存在错误或误解。
        """
        from castorice.utils import extract_json
        
        self._reflection_counter = getattr(self, '_reflection_counter', 0)
        self._reflection_counter += 1
        
        if self._reflection_counter % 10 != 0:
            return
        
        logger.info("自我修正: 开始检查记忆质量...")
        
        try:
            recent_memories = await asyncio.to_thread(
                self.long_term.get_recent, limit=10
            )
            
            if not recent_memories:
                logger.debug("自我修正: 无近期记忆可检查")
                return
            
            for memory in recent_memories:
                if isinstance(memory, dict):
                    text = memory.get("text", memory.get("document", ""))
                else:
                    text = str(memory)
                
                if not text or len(text) < 10:
                    continue
                
                prompt = f"""你是记忆质量评估器，分析以下记忆是否存在错误或误解。

【记忆内容】
{text}

【分析任务】
1. 判断这条记忆是否存在错误提取（如把疑问句误提取为名字）
2. 判断是否存在误解用户意图的情况
3. 判断是否包含无意义或重复的信息

【输出格式】
只返回JSON：
{{
  "has_error": true/false,
  "error_type": "none/misextraction/misunderstanding/meaningless/redundant",
  "error_description": "错误描述",
  "suggestion": "修正建议（如果有错误）",
  "should_delete": true/false
}}"""

                response = await asyncio.to_thread(
                    self.model.chat,
                    [
                        ChatMessage("system", "你是记忆质量评估器，只输出JSON。"),
                        ChatMessage("user", prompt),
                    ]
                )
                parsed = extract_json(response.content)
                
                if parsed.get("has_error") and parsed.get("should_delete"):
                    logger.warning(f"自我修正: 发现错误记忆，删除 ({parsed.get('error_type')}: {parsed.get('error_description')})")
                    if isinstance(memory, dict) and "id" in memory:
                        await asyncio.to_thread(self.long_term.delete, memory["id"])
            
            logger.info("自我修正: 记忆质量检查完成")
            
        except Exception as e:
            logger.warning(f"自我修正失败: {e}")

    async def _detect_memory_conflict(self, user_input: str) -> Optional[str]:
        """
        记忆冲突检测：当新信息与已有记忆冲突时，返回冲突描述。
        
        例如：已有名字"张三"，新输入说"我叫李四"，则检测到冲突。
        """
        from castorice.utils import extract_json
        
        current_name = self.user_profile.get("identity.name", "")
        current_nickname = self.user_profile.get("identity.nickname", "")
        
        if not current_name and not current_nickname:
            return None
        
        prompt = f"""检测用户输入与已有记忆是否存在冲突。

【已有记忆】
用户名字: {current_name or '未设置'}
用户昵称: {current_nickname or '未设置'}

【用户输入】
{user_input}

【判断规则】
- 如果用户输入的名字/身份与已有记忆不同，且是明确的身份声明，则存在冲突
- 如果用户只是询问或确认（如"你还记得我吗"），不存在冲突
- 如果用户输入的是职业、爱好等其他信息，不存在冲突

【输出格式】
只返回JSON：
{{
  "has_conflict": true/false,
  "conflict_type": "none/identity/other",
  "conflict_description": "冲突描述",
  "suggestion": "处理建议"
}}"""

        try:
            response = await asyncio.to_thread(
                self.model.chat,
                [
                    ChatMessage("system", "你是记忆冲突检测器，只输出JSON。"),
                    ChatMessage("user", prompt),
                ]
            )
            parsed = extract_json(response.content)
            
            if parsed.get("has_conflict"):
                conflict_desc = parsed.get("conflict_description", "")
                logger.warning(f"记忆冲突检测: {conflict_desc}")
                return conflict_desc
            
            return None
        except Exception as e:
            logger.warning(f"记忆冲突检测失败: {e}")
            return None

    async def _extract_user_profile(self, user_input: str) -> None:
        """
        从用户输入中智能提取关键信息到用户画像（规则匹配优先，LLM兜底）。

        支持的模式：
        - "我叫XXX" / "我的名字是XXX" → identity.name
        - "叫我XXX" / "称呼我XXX" → identity.nickname  
        - "我喜欢XXX" / "我偏好XXX" → interests

        核心改进：规则匹配能处理的情况不调用LLM，只有模糊情况才用LLM
        """
        import re

        question_patterns = [
            r'我是谁',
            r'你还记得么',
            r'你认识我吗',
            r'知道我是谁',
            r'还记得我吗',
        ]
        for pattern in question_patterns:
            if re.search(pattern, user_input):
                logger.debug(f"检测到疑问句式，跳过身份提取: {user_input}")
                return

        non_name_patterns = [
            r'我是\s*(学生|老师|程序员|开发者|用户|新人|一个|这里|谁|什么|怎么|为什么)',
            r'我是\s*(student|teacher|developer|user)',
        ]
        for pattern in non_name_patterns:
            if re.search(pattern, user_input, re.IGNORECASE):
                logger.debug(f"检测到非身份声明，跳过身份提取: {user_input}")
                return

        name_patterns = [
            (r'我叫\s*([A-Za-z\u4e00-\u9fa5][A-Za-z\u4e00-\u9fa5·\s]{0,20})', '我叫'),
            (r'我的名字是\s*([A-Za-z\u4e00-\u9fa5][A-Za-z\u4e00-\u9fa5·\s]{0,20})', '我的名字是'),
            (r'我的名字叫\s*([A-Za-z\u4e00-\u9fa5][A-Za-z\u4e00-\u9fa5·\s]{0,20})', '我的名字叫'),
        ]
        for pattern, desc in name_patterns:
            m = re.search(pattern, user_input)
            if m:
                name = m.group(1).strip().rstrip('，。,.!?！？')
                non_name_words = {"学生", "老师", "程序员", "开发者", "用户", "新人",
                                  "一个", "这里", "谁", "什么", "怎么", "为什么",
                                  "student", "teacher", "developer", "user"}
                if name and name.lower() not in non_name_words and len(name) >= 2:
                    current_name = self.user_profile.get("identity.name", "")
                    if not current_name:
                        self.user_profile.set("identity.name", name)
                        logger.info(f"用户画像更新: identity.name = {name}")
                    return

        nickname_patterns = [
            r'叫我\s*([A-Za-z\u4e00-\u9fa5][A-Za-z\u4e00-\u9fa5·\s]{0,20})',
            r'称呼我\s*([A-Za-z\u4e00-\u9fa5][A-Za-z\u4e00-\u9fa5·\s]{0,20})',
            r'call me\s+([A-Za-z][A-Za-z\s]{0,20})',
        ]
        for pattern in nickname_patterns:
            m = re.search(pattern, user_input, re.IGNORECASE)
            if m:
                nickname = m.group(1).strip().rstrip('，。,.!?！？')
                if nickname and len(nickname) >= 2:
                    self.user_profile.set("identity.nickname", nickname)
                    logger.info(f"用户画像更新: identity.nickname = {nickname}")
                    if not self.user_profile.get("identity.name", ""):
                        self.user_profile.set("identity.name", nickname)
                        logger.info(f"用户画像更新: identity.name 回退使用 nickname = {nickname}")
                    return

        interest_patterns = [
            r'我喜欢\s*(.{2,30})',
            r'我偏好\s*(.{2,30})',
            r'我爱\s*(.{2,30})',
            r'我对(.{0,5})感兴趣',
        ]
        for pattern in interest_patterns:
            m = re.search(pattern, user_input)
            if m:
                interest = m.group(1).strip().rstrip('，。,.!?！？')
                if interest and not interest.startswith(('这', '那', '它', '他', '她')):
                    self.user_profile.add_to_list("interests", interest)
                    logger.info(f"用户画像更新: interests += {interest}")
                    return

        logger.debug(f"规则匹配未命中，跳过用户画像提取: {user_input}")

    def _extract_user_profile_fallback(self, user_input: str) -> None:
        """
        规则匹配提取用户画像（LLM不可用时的fallback）。

        使用增强的规则过滤，避免误提取。
        """
        import re

        question_patterns = [
            r'我是谁',
            r'你还记得么',
            r'你认识我吗',
            r'知道我是谁',
            r'还记得我吗',
        ]
        for pattern in question_patterns:
            if re.search(pattern, user_input):
                logger.debug(f"检测到疑问句式，跳过身份提取: {user_input}")
                return

        non_name_patterns = [
            r'我是\s*(学生|老师|程序员|开发者|用户|新人|一个|这里|谁|什么|怎么|为什么)',
            r'我是\s*(student|teacher|developer|user)',
        ]
        for pattern in non_name_patterns:
            if re.search(pattern, user_input, re.IGNORECASE):
                logger.debug(f"检测到非身份声明，跳过身份提取: {user_input}")
                return

        name_patterns = [
            r'我叫\s*([A-Za-z\u4e00-\u9fa5][A-Za-z\u4e00-\u9fa5·\s]{0,20})',
            r'我的名字是\s*([A-Za-z\u4e00-\u9fa5][A-Za-z\u4e00-\u9fa5·\s]{0,20})',
            r'我的名字叫\s*([A-Za-z\u4e00-\u9fa5][A-Za-z\u4e00-\u9fa5·\s]{0,20})',
        ]
        for pattern in name_patterns:
            m = re.search(pattern, user_input)
            if m:
                name = m.group(1).strip().rstrip('，。,.!?！？')
                non_name_words = {"学生", "老师", "程序员", "开发者", "用户", "新人",
                                  "一个", "这里", "谁", "什么", "怎么", "为什么",
                                  "student", "teacher", "developer", "user"}
                if name and name.lower() not in non_name_words and len(name) >= 2:
                    current_name = self.user_profile.get("identity.name", "")
                    if not current_name:
                        self.user_profile.set("identity.name", name)
                        logger.info(f"用户画像更新(fallback): identity.name = {name}")
                    break

        nickname_patterns = [
            r'叫我\s*([A-Za-z\u4e00-\u9fa5][A-Za-z\u4e00-\u9fa5·\s]{0,20})',
            r'称呼我\s*([A-Za-z\u4e00-\u9fa5][A-Za-z\u4e00-\u9fa5·\s]{0,20})',
            r'call me\s+([A-Za-z][A-Za-z\s]{0,20})',
        ]
        for pattern in nickname_patterns:
            m = re.search(pattern, user_input, re.IGNORECASE)
            if m:
                nickname = m.group(1).strip().rstrip('，。,.!?！？')
                if nickname and len(nickname) >= 2:
                    self.user_profile.set("identity.nickname", nickname)
                    logger.info(f"用户画像更新(fallback): identity.nickname = {nickname}")
                    if not self.user_profile.get("identity.name", ""):
                        self.user_profile.set("identity.name", nickname)
                        logger.info(f"用户画像更新(fallback): identity.name 回退使用 nickname = {nickname}")
                    break

        interest_patterns = [
            r'我喜欢\s*(.{2,30})',
            r'我偏好\s*(.{2,30})',
            r'我爱\s*(.{2,30})',
            r'我对(.{0,5})感兴趣',
        ]
        for pattern in interest_patterns:
            m = re.search(pattern, user_input)
            if m:
                interest = m.group(1).strip().rstrip('，。,.!?！？')
                if interest and not interest.startswith(('这', '那', '它', '他', '她')):
                    self.user_profile.add_to_list("interests", interest)
                    logger.info(f"用户画像更新(fallback): interests += {interest}")
                    break

    # ============================================================
    # 阶段7: 技能沉淀
    # ============================================================
    async def _step_skill(self, state: State) -> None:
        # 配置禁用技能生成时，直接返回
        if not self.enable_skill_generation:
            return

        from castorice.memory.skill import Skill
        proposal = state.skill_to_generate
        if not proposal or not proposal.get("name"):
            return
        try:
            skill = Skill(
                name=proposal["name"],
                trigger_keywords=proposal.get("trigger_keywords", []),
                description=proposal.get("description", ""),
                steps=proposal.get("steps", []),
                required_tools=proposal.get("required_tools", []),
                applicable_scenarios=proposal.get("applicable_scenarios", []),
            )
            # 使用公共接口，内部会自动处理版本递增和保存
            self.skill_memory.add_or_update(skill)
            logger.info(f"技能沉淀完成: {skill.name}")
        except Exception as e:
            logger.warning(f"技能生成失败: {e}")

    # ============================================================
    # 辅助方法：上下文压缩、资源感知、不确定性提示
    # ============================================================
    def _build_context_for_estimation(self, state: State) -> str:
        """构建用于Token估算的完整上下文文本"""
        parts = [
            state.user_input,
            state.short_term_context,
            state.relevant_history,
            state.user_profile_context,
            state.available_tools_desc,
            state.thinking_strategy_prompt,
            state.dialogue_adjustment,
        ]
        return "\n\n".join(p for p in parts if p)

    def _compress_context(self, context: str, max_chars: int = 800) -> str:
        """压缩上下文（简单摘要）"""
        if len(context) <= max_chars:
            return context

        lines = context.split("\n")
        if len(lines) <= 2:
            return context[:max_chars] + "..."

        # 保留第一条和最近几条，中间用省略号
        head = lines[:1]
        tail = lines[-3:]
        compressed = "\n".join(head + ["...（历史对话已压缩）..."] + tail)
        if len(compressed) > max_chars:
            return compressed[:max_chars] + "..."
        return compressed

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
    # 工具函数
    # ============================================================
    def _ensure_images_in_answer(self, answer: str, tool_calls: list) -> str:
        """兜底：如果回答中没有图片 Markdown，从工具结果中提取并追加"""
        import re
        # 检查回答中是否已有 Markdown 图片
        if re.search(r'!\[.*?\]\(https?://', answer):
            return answer

        # 从工具调用结果中收集图片 URL
        image_urls = []
        for tc in tool_calls:
            result = tc.get("result", "")
            # 提取 markdown 图片
            for url in re.findall(r'!\[.*?\]\((https?://[^\s)]+)\)', result):
                if url not in image_urls:
                    image_urls.append(url)

        if image_urls:
            images_section = "\n\n---\n### 相关图片\n\n"
            for url in image_urls[:3]:
                images_section += f"![图片]({url})\n\n"
            return answer + images_section

        return answer

    def _split_for_streaming(self, text: str) -> List[str]:
        """
        P1-3: 把文本切分成流式输出块，但保护 Markdown 图片 URL 不被切断。

        策略：
        1. 先把所有 ![desc](url) 整段替换为占位符
        2. 按句子/标点切分
        3. 把占位符还原回原图片标记
        """
        import re
        # 匹配 Markdown 图片：![描述](URL)
        image_pattern = re.compile(r'!\[[^\]]*\]\([^)]+\)')
        placeholders: List[str] = []

        def _stash(m):
            placeholders.append(m.group(0))
            return f"\x00IMG{len(placeholders) - 1}\x00"

        protected = image_pattern.sub(_stash, text)

        # 按句子/标点切分（中文标点+英文标点+换行）
        chunks = re.split(r'(?<=[。！？.!?\n])', protected)

        # 还原占位符
        result = []
        for chunk in chunks:
            if not chunk:
                continue
            # 还原 chunk 内的占位符
            def _restore(m):
                idx = int(m.group(1))
                return placeholders[idx] if 0 <= idx < len(placeholders) else m.group(0)
            restored = re.sub(r'\x00IMG(\d+)\x00', _restore, chunk)
            result.append(restored)
        return result

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
    
