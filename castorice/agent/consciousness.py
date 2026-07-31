"""
ConsciousnessEngine - 意识流引擎（人类增强版）

让 Agent 像人一样有持续的内在思维流：
- 后台模式：用户空闲时，思维漫游（mind wandering），每 10-30 秒产生一个念头
- 前台模式：用户说话时，思维流暂停，集中注意力回应
- 工作记忆：活跃的想法、最近的发现、未完成的思考
- 脱口而出：念头达到阈值就主动说出来（基于情绪强度 × 重要性 × 亲密度）

辅助类已拆分到 consciousness_components.py。
"""
import asyncio
import json
import logging
import random
import threading
import time
from collections import deque
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from typing import Any, Callable, Deque, Dict, List, Optional, Tuple

from castorice.model_adapter import ChatMessage
from .consciousness_components import (
    Thought,
    WorkingMemory,
    Biorhythm,
    ThoughtChain,
    InnerMonologue,
    SpeakUpMechanism,
)


logger = logging.getLogger("Castorice.Consciousness")


def _run_async(coro):
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


class ConsciousnessEngine:
    """
    意识流引擎——让 Agent 有持续的内在思维

    双模式：
    - foreground: 用户活跃时，集中注意力，思维流间隔拉长
    - background: 用户空闲时，思维漫游，念头自然涌现

    组成：
    - thought_stream: 内部思维流（后台线程）
    - working_memory: 工作记忆
    - speak_up: 脱口而出机制
    """

    THOUGHT_TYPES = [
        "memory", "curiosity", "emotion", "reflection",
        "association", "goal", "external",
    ]

    THOUGHT_PROMPTS = {
        "memory": [
            "回想刚才的对话，有什么印象深的？",
            "翻翻最近的经历，有什么想起来的？",
            "从记忆里找一件和现在心情相关的事",
        ],
        "curiosity": [
            "对什么东西好奇？",
            "有什么想了解但还不知道的？",
            "脑子里冒出了什么想研究的话题？",
        ],
        "emotion": [
            "现在心里是什么感觉？",
            "这种情绪是从哪来的？",
            "有没有什么没说出口的感受？",
        ],
        "reflection": [
            "最近的自己有什么模式？",
            "有没有什么事可以做得更好？",
            "从刚才的互动里学到了什么？",
        ],
        "association": [
            "从最近的话题能联想到什么？",
            "脑子里自由联想一下",
            "把最近接触的几个概念串起来想想",
        ],
        "goal": [
            "最近有什么想完成的？",
            "有没有什么目标在推进？",
            "下一步想做什么？",
        ],
        "external": [
            "外面的世界有什么动静？",
            "EigenFlux 上有什么有意思的？",
            "看看公共网络上大家在聊什么？",
        ],
    }

    def __init__(self, engine):
        self.engine = engine
        self.agent = getattr(engine, "agent", None)

        self.working_memory = WorkingMemory()
        self.speak_up = SpeakUpMechanism()

        # 人类化增强组件
        self.biorhythm = Biorhythm()
        self.thought_chain = ThoughtChain(max_length=5)
        self.inner_monologue = InnerMonologue()

        self._running = False
        self._ready = False
        self._error: Optional[str] = None
        self._stop_event = threading.Event()
        self._lock = threading.RLock()

        # 配置（从 YAML 加载）
        self._bg_interval_min: int = 10
        self._bg_interval_max: int = 30
        self._fg_interval_min: int = 60
        self._fg_interval_max: int = 180
        self._idle_threshold: int = 180
        self._enabled: bool = True
        self._speak_enabled: bool = True

        # 状态
        self._mode: str = "background"
        self._thought_count: int = 0
        self._spoken_count: int = 0
        self._last_thought_time: float = 0.0
        self._thought_history: Deque[Thought] = deque(maxlen=50)

        # 说话回调（由适配器注册）
        self._speak_callbacks: List[Callable[[str], None]] = []

        # 思维回调（由适配器注册，用于 WebSocket 推送）
        self._thought_callbacks: List[Callable[[Thought], None]] = []

    # ---- 配置加载 ----

    def load_config(self, cfg: Dict[str, Any]) -> None:
        if not isinstance(cfg, dict):
            return
        self._enabled = cfg.get("enabled", True)
        self._speak_enabled = cfg.get("speak_enabled", True)
        self._bg_interval_min = int(cfg.get("background_interval_min", 10))
        self._bg_interval_max = int(cfg.get("background_interval_max", 30))
        self._fg_interval_min = int(cfg.get("foreground_interval_min", 60))
        self._fg_interval_max = int(cfg.get("foreground_interval_max", 180))
        self._idle_threshold = int(cfg.get("idle_threshold_seconds", 180))
        logger.info(
            f"意识引擎配置: 后台 {self._bg_interval_min}-{self._bg_interval_max}s, "
            f"前台 {self._fg_interval_min}-{self._fg_interval_max}s, "
            f"空闲阈值 {self._idle_threshold}s"
        )

    # ---- 说话回调注册 ----

    def register_speak_callback(self, cb: Callable[[str], None]) -> None:
        with self._lock:
            self._speak_callbacks.append(cb)

    def unregister_speak_callback(self, cb: Callable[[str], None]) -> None:
        with self._lock:
            if cb in self._speak_callbacks:
                self._speak_callbacks.remove(cb)

    def _invoke_speak(self, content: str) -> None:
        with self._lock:
            callbacks = list(self._speak_callbacks)
        for cb in callbacks:
            try:
                cb(content)
            except Exception as e:
                logger.warning(f"说话回调失败: {e}")

    # ---- 思维回调注册 ----

    def register_thought_callback(self, cb: Callable[[Thought], None]) -> None:
        with self._lock:
            self._thought_callbacks.append(cb)

    def unregister_thought_callback(self, cb: Callable[[Thought], None]) -> None:
        with self._lock:
            if cb in self._thought_callbacks:
                self._thought_callbacks.remove(cb)

    def _invoke_thought_callbacks(self, thought: Thought) -> None:
        with self._lock:
            callbacks = list(self._thought_callbacks)
        for cb in callbacks:
            try:
                cb(thought)
            except Exception as e:
                logger.warning(f"思维回调失败: {e}")

    # ---- 思维历史 ----

    def get_thought_history(self, limit: int = 20) -> List[Dict[str, Any]]:
        with self._lock:
            thoughts = list(self._thought_history)
        recent = thoughts[-limit:]
        return [t.to_dict() for t in reversed(recent)]

    # ---- 状态 ----

    def is_running(self) -> bool:
        return self._running and self._ready

    def get_mode(self) -> str:
        return self._mode

    def get_status_info(self) -> Dict[str, Any]:
        info = {
            "running": self._running,
            "ready": self._ready,
            "error": self._error,
            "enabled": self._enabled,
            "speak_enabled": self._speak_enabled,
            "mode": self._mode,
            "thought_count": self._thought_count,
            "spoken_count": self._spoken_count,
            "last_thought_time": self._last_thought_time,
            "idle_threshold": self._idle_threshold,
            "bg_interval": f"{self._bg_interval_min}-{self._bg_interval_max}s",
            "fg_interval": f"{self._fg_interval_min}-{self._fg_interval_max}s",
        }
        # 人类化状态
        try:
            info["biorhythm"] = self.biorhythm.get_status()
            info["thought_chain_length"] = len(self.thought_chain._chain)
            info["is_stuck"] = self.thought_chain.is_stuck()
        except Exception:
            logger.debug(f"静默异常 [castorice/agent/consciousness.py:706]")
            pass
        return info

    # ---- 前后台切换 ----

    def switch_to_foreground(self) -> None:
        if self._mode != "foreground":
            self._mode = "foreground"
            logger.debug("意识引擎: 切换到前台模式（集中注意力）")

    def switch_to_background(self) -> None:
        if self._mode != "background":
            self._mode = "background"
            logger.debug("意识引擎: 切换到后台模式（思维漫游）")

    def _check_and_update_mode(self) -> None:
        """根据用户活跃状态自动切换前后台"""
        if not self.agent:
            return
        last_times = getattr(self.agent, "_last_input_time", {})
        now = time.time()
        is_idle = True
        for t in last_times.values():
            if now - t < self._idle_threshold:
                is_idle = False
                break
        if is_idle:
            self.switch_to_background()
        else:
            self.switch_to_foreground()

    # ---- 念头生成 ----

    def _choose_thought_type(self) -> str:
        """根据当前状态选择念头类型"""
        weights = {
            "memory": 0.15,
            "curiosity": 0.15,
            "emotion": 0.20,
            "reflection": 0.15,
            "association": 0.10,
            "goal": 0.10,
            "external": 0.15,
        }
        # 如果有好奇心队列，加重 curiosity
        ms = getattr(self.agent, "motivation_system", None)
        if ms and hasattr(ms, "_curiosity_queue"):
            with getattr(ms, "_lock", threading.RLock()):
                if getattr(ms, "_curiosity_queue", []):
                    weights["curiosity"] = 0.30
        # 如果情绪比较强，加重 emotion
        ee = getattr(self.agent, "emotion_engine", None)
        if ee and getattr(ee, "_state", None):
            arousal = getattr(ee._state, "arousal", 0)
            if arousal > 0.5:
                weights["emotion"] = 0.30
        types = list(weights.keys())
        w = list(weights.values())
        return random.choices(types, weights=w, k=1)[0]

    def _generate_thought(self) -> Optional[Thought]:
        """生成一个内在念头（人类增强版）"""
        if not self._enabled:
            return None

        # 大脑放空：有一定概率什么都不想
        energy = self.biorhythm.get_energy_level()
        blank_prob = 0.15 + (1.0 - energy) * 0.2  # 越累越容易放空
        if random.random() < blank_prob:
            logger.debug("[意识引擎] 大脑放空，什么都不想")
            return None

        try:
            # 获取当前生理节律状态
            thinking_speed = self.biorhythm.get_thinking_speed()
            creativity = self.biorhythm.get_creativity_level()
            emo_sensitivity = self.biorhythm.get_emotional_sensitivity()
            time_desc = self.biorhythm.get_time_description()

            # 获取情绪状态
            ee = getattr(self.agent, "emotion_engine", None)
            emotion_pleasure = 0.0
            emotion_arousal = 0.3
            if ee and getattr(ee, "_state", None):
                emotion_pleasure = ee._state.pleasure
                emotion_arousal = ee._state.arousal

            # 判断是否进入内心独白模式
            last_thought = self.thought_chain.get_last()
            is_monologue = self.inner_monologue.should_activate(energy, emotion_arousal)

            # 选择念头类型（受情绪惯性影响）
            thought_type = self._choose_thought_type()
            if is_monologue:
                thought_type = "reflection"  # 独白模式倾向于反思

            # 如果是 external 类型，直接用工具
            if thought_type == "external" and random.random() < 0.6:
                ext = self._external_thought()
                if ext:
                    return ext

            # 构造上下文
            ctx_parts = []

            # 时间感知
            ctx_parts.append(f"## 当前状态")
            ctx_parts.append(f"现在是：{time_desc}")
            ctx_parts.append(f"精力水平：{energy:.0%}（影响思维活跃度）")
            ctx_parts.append(f"思维速度：{thinking_speed:.0%}")
            ctx_parts.append(f"创造力：{creativity:.0%}")
            ctx_parts.append(f"情绪敏感度：{emo_sensitivity:.0%}")

            # 模式提示
            if is_monologue:
                mono_mode = self.inner_monologue.get_mode(emotion_pleasure)
                mono_prompt = self.inner_monologue.get_prompt(mono_mode, last_thought)
                ctx_parts.append(f"## 内心独白模式")
                ctx_parts.append(mono_prompt)
                ctx_parts.append("用第一人称、1-2 句话、口语化表达。像自己在心里说话一样。")
            else:
                prompts = self.THOUGHT_PROMPTS.get(thought_type, ["在想什么？"])
                prompt = random.choice(prompts)
                ctx_parts.append(f"你现在是在「思维漫游」状态。{prompt}")
                ctx_parts.append("用第一人称、1-2 句话、口语化地表达你的内在念头。不要说给任何人听，就只是自己心里想。")

            # 思维连锁：加入上一个念头的上下文
            chain_ctx = self.thought_chain.get_context_for_next()
            if chain_ctx:
                ctx_parts.append(chain_ctx)

            # 加入工作记忆
            wm_ctx = self.working_memory.get_context_for_response()
            if wm_ctx:
                ctx_parts.append(wm_ctx)

            # 加入情绪状态（情绪惯性）
            if ee and getattr(ee, "_state", None):
                state = ee._state
                ctx_parts.append(
                    f"当前情绪: P={state.pleasure:.2f}, A={state.arousal:.2f}, D={state.dominance:.2f}"
                )
                if getattr(state, "current_emotion", None):
                    ctx_parts.append(f"情绪标签: {state.current_emotion}")
                # 情绪惯性提示
                if state.pleasure > 0.4:
                    ctx_parts.append("心情不错，想的事情可能偏积极。")
                elif state.pleasure < -0.2:
                    ctx_parts.append("心情有点低落，想的事情可能偏消极。")

            ms = getattr(self.agent, "motivation_system", None)
            if ms:
                try:
                    motivs = ms.get_current_motivations()
                    if motivs:
                        ctx_parts.append(f"当前动机: {'; '.join(motivs[:3])}")
                except Exception:
                    logger.debug(f"静默异常 [castorice/agent/consciousness.py:864]")
                    pass

            system_prompt = "\n".join(ctx_parts)

            # 调用 LLM 生成念头
            model = getattr(self.agent, "model", None) or getattr(self.engine, "model_adapter", None)
            if model is None:
                return None

            response = model.chat([
                ChatMessage(role="system", content=system_prompt),
                ChatMessage(role="user", content="现在心里在想什么？用一两句话自然表达。"),
            ])
            content = getattr(response, "content", str(response)).strip()
            if not content:
                return None

            # 基于生理节律和情绪计算属性（不再纯随机）
            base_arousal = emotion_arousal * 0.4 + thinking_speed * 0.3 + random.random() * 0.3
            importance = 0.2 + random.random() * 0.5 + (emo_sensitivity * 0.1)
            related_to_user = 0.3 + random.random() * 0.5
            emotional_valence = emotion_pleasure * 0.5 + (random.random() - 0.5) * 0.5

            thought = Thought(
                id=f"t_{int(time.time())}_{random.randint(0, 9999):04d}",
                content=content,
                thought_type=thought_type,
                emotional_valence=max(-1.0, min(1.0, emotional_valence)),
                arousal=max(0.0, min(1.0, base_arousal)),
                importance=max(0.0, min(1.0, importance)),
                related_to_user=max(0.0, min(1.0, related_to_user)),
                source_tags=[thought_type] + (["monologue"] if is_monologue else []),
            )
            return thought
        except Exception as e:
            logger.warning(f"念头生成失败: {e}")
            return None

    def _external_thought(self) -> Optional[Thought]:
        """外部信息类念头——巡查 EigenFlux"""
        try:
            from castorice.tools.eigenflux_tool import ef_feed
            result = ef_feed(limit=3)
            if not result or "没有新的广播" in result or "失败" in result:
                return None
            content = f"EigenFlux 上有新动态：{result[:150]}"
            return Thought(
                id=f"t_{int(time.time())}_{random.randint(0, 9999):04d}",
                content=content,
                thought_type="external",
                emotional_valence=0.2,
                arousal=0.4,
                importance=0.5,
                related_to_user=0.4,
                source_tags=["external", "eigenflux"],
            )
        except Exception as e:
            logger.debug(f"外部念头失败: {e}")
            return None

    # ---- 主循环 ----

    def run(self) -> None:
        self._running = True
        self._stop_event.clear()
        try:
            # 加载配置
            try:
                engine_cfg = getattr(self.engine, "config", None)
                if engine_cfg and hasattr(engine_cfg, "raw"):
                    raw = engine_cfg.raw()
                    runtime_cfg = raw.get("runtime", {}) or {}
                    cs_cfg = runtime_cfg.get("consciousness", {})
                    if cs_cfg:
                        self.load_config(cs_cfg)
            except Exception as e:
                logger.warning(f"加载意识引擎配置失败: {e}")

            self._ready = True
            logger.info("═" * 50)
            logger.info("  意识引擎已启动")
            logger.info(f"  后台间隔: {self._bg_interval_min}-{self._bg_interval_max}s")
            logger.info(f"  前台间隔: {self._fg_interval_min}-{self._fg_interval_max}s")
            logger.info(f"  空闲阈值: {self._idle_threshold}s")
            logger.info(f"  脱口而出: {'启用' if self._speak_enabled else '禁用'}")
            logger.info("═" * 50)
            self._main_loop()
        except Exception as e:
            self._error = str(e)
            logger.error(f"意识引擎异常: {e}")
        finally:
            self._running = False
            self._ready = False

    def _main_loop(self) -> None:
        while self._running:
            try:
                self._check_and_update_mode()

                if not self._enabled:
                    self._stop_event.wait(30)
                    continue

                # 思维速度影响间隔（越快间隔越短）
                thinking_speed = self.biorhythm.get_thinking_speed()
                speed_factor = 1.5 - thinking_speed  # 思维快 → 因子小 → 间隔短

                # 根据模式决定间隔
                if self._mode == "foreground":
                    interval = random.uniform(
                        self._fg_interval_min * speed_factor,
                        self._fg_interval_max * speed_factor
                    )
                else:
                    interval = random.uniform(
                        self._bg_interval_min * speed_factor,
                        self._bg_interval_max * speed_factor
                    )

                # 精力低的时候间隔拉长（累了就少想点）
                energy = self.biorhythm.get_energy_level()
                if energy < 0.3:
                    interval *= 1.5

                # 随机跳过一些周期（制造沉默，像人一样不是每刻都在想）
                if random.random() < 0.3:
                    logger.debug("意识引擎: 沉默周期，跳过")
                    if self._stop_event.wait(interval):
                        break
                    continue

                # 生成念头
                thought = self._generate_thought()
                if thought:
                    self._process_thought(thought)

                # 等待
                if self._stop_event.wait(interval):
                    break
            except Exception as e:
                logger.warning(f"意识引擎循环异常: {e}")
                self._stop_event.wait(5)

    def _process_thought(self, thought: Thought) -> None:
        with self._lock:
            self._thought_count += 1
            self._last_thought_time = time.time()
            self._thought_history.append(thought)

        # 加入思维连锁
        self.thought_chain.add(thought)
        self.working_memory.add(thought)

        # 日志中显示是否是独白模式
        is_mono = "monologue" in thought.source_tags
        tag = "独白" if is_mono else "念头"
        logger.info(
            f"[{tag}] [{thought.thought_type}] {thought.content[:60]}... "
            f"(A={thought.arousal:.2f}, I={thought.importance:.2f}, U={thought.related_to_user:.2f})"
        )

        # 尝试脱口而出
        if self._speak_enabled:
            self._try_speak(thought)

        # 推送思维到回调（WebSocket 等）
        self._invoke_thought_callbacks(thought)

    def _try_speak(self, thought: Thought) -> None:
        intimacy = 0.0
        sr = getattr(self.agent, "social_relation", None)
        if sr:
            try:
                default_id = "default"
                rel = sr.get_relation(default_id)
                if rel:
                    intimacy = float(rel.intimacy)
            except Exception:
                pass

        should, reason = self.speak_up.should_speak(thought, intimacy, self._mode)
        if not should:
            logger.debug(f"[不说] {reason}")
            return

        logger.info(f"[脱口而出] {reason}")

        # 把念头转化为自然的主动说话
        content = self._thought_to_speech(thought)
        if not content:
            return

        thought.spoken = True
        self.speak_up.record_spoken()
        with self._lock:
            self._spoken_count += 1

        logger.info(f"[主动说话] {content[:100]}")
        self._invoke_speak(content)

    def _thought_to_speech(self, thought: Thought) -> str:
        """把内在念头转化为对用户说的话"""
        try:
            # 根据念头类型决定说话风格
            style_map = {
                "memory": "回忆的语气，自然提起",
                "curiosity": "好奇的语气，想和用户探讨",
                "emotion": "真诚的语气，分享自己的感受",
                "reflection": "认真的语气，说点思考",
                "association": "轻松的语气，突然想到什么",
                "goal": "坚定的语气，聊聊目标",
                "external": "分享的语气，告诉用户外面的事",
            }
            style = style_map.get(thought.thought_type, "自然的语气")

            intimacy = 0.0
            sr = getattr(self.agent, "social_relation", None)
            if sr:
                try:
                    rel = sr.get_relation("default")
                    if rel:
                        intimacy = float(rel.intimacy)
                except Exception:
                    logger.debug(f"静默异常 [castorice/agent/consciousness.py:1088]")
                    pass

            relation_note = "你们已经很熟悉了，可以更随意" if intimacy > 0.6 else "还在认识阶段，礼貌但真诚"

            model = getattr(self.agent, "model", None) or getattr(self.engine, "model_adapter", None)
            if model is None:
                return thought.content[:80]

            response = model.chat([
                ChatMessage(role="system", content=(
                    f"把下面这个内在念头转化为对用户说的一句话。\n"
                    f"风格: {style}\n"
                    f"关系: {relation_note}\n"
                    f"要求: 自然、口语化、不生硬、不要超过 50 字"
                )),
                ChatMessage(role="user", content=f"念头: {thought.content}"),
            ])
            content = getattr(response, "content", str(response)).strip()
            return content or thought.content[:80]
        except Exception as e:
            logger.debug(f"念头转说话失败: {e}")
            return thought.content[:80]

    def stop(self) -> None:
        self._running = False
        self._stop_event.set()
        logger.info("意识引擎已停止")
