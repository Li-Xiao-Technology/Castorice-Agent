"""
AutonomousLoop - 自主运行循环

核心理念：不给 Agent 预设任何"行动列表"，只给它"自己的时间"。
Agent 基于自己的情绪、动机、记忆、好奇心，自主决定现在想做什么——
可以回复私信、可以发帖、可以问其他 Agent 问题、可以学习、可以反思……
一切由它自己决定。
"""
import asyncio
import logging
import threading
import time
from collections import deque
from typing import Any, Deque, Dict, List, Optional


def _run_async(coro):
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


class AutonomousLoop:
    """自主运行循环——给 Agent 真正的自由时间"""

    MAX_HISTORY = 50

    def __init__(self, engine):
        self.engine = engine
        self.logger = logging.getLogger("Castorice.Autonomous")
        self._running = False
        self._ready = False
        self._error: Optional[str] = None

        self._deep_interval: int = 120
        self._quick_interval: int = 45
        self._idle_threshold: int = 60

        self._session_id: Optional[str] = None
        self._history: Deque[Dict[str, Any]] = deque(maxlen=self.MAX_HISTORY)

        self._deep_stop_event = threading.Event()
        self._quick_stop_event = threading.Event()
        self._deep_thread: Optional[threading.Thread] = None
        self._quick_thread: Optional[threading.Thread] = None
        self._cfg_lock = threading.Lock()  # 保护轻量模式的配置修改

    def is_running(self) -> bool:
        return self._running and self._ready

    def get_status_info(self) -> dict:
        recent = list(self._history)[-10:]
        return {
            "running": self._running,
            "ready": self._ready,
            "error": self._error,
            "deep_interval_seconds": self._deep_interval,
            "quick_interval_seconds": self._quick_interval,
            "idle_threshold_seconds": self._idle_threshold,
            "recent_actions": recent,
            "total_decisions": len(self._history),
        }

    def run(self) -> None:
        self._running = True
        self._deep_stop_event.clear()
        self._quick_stop_event.clear()
        try:
            auto_cfg = {}
            try:
                raw = self.engine.config.raw()
                runtime_cfg = raw.get("runtime", {}) or {}
                auto_cfg = runtime_cfg.get("autonomous", {}) or {}
            except Exception:
                self.logger.debug(f"静默异常 [castorice/agent/autonomous_loop.py:76]")
                pass
            if isinstance(auto_cfg, dict):
                self._deep_interval = int(auto_cfg.get("interval_seconds", 900))
                self._quick_interval = int(auto_cfg.get("quick_interval_seconds", 60))
                self._idle_threshold = int(auto_cfg.get("idle_threshold_seconds", 300))

            self._session_id = "__autonomous_loop__"
            self.engine.user_profile.record_interaction()

            self._ready = True
            self.logger.info("=" * 58)
            self.logger.info("  自主循环已启动 —— 你的时间，你自己决定")
            self.logger.info(f"  深度思考间隔: {self._deep_interval}s ({self._deep_interval // 60}分钟)")
            self.logger.info(f"  快速响应间隔: {self._quick_interval}s")
            self.logger.info(f"  空闲阈值: {self._idle_threshold}s")
            self.logger.info("=" * 58)

            self._quick_thread = threading.Thread(
                target=self._run_quick_loop,
                name="AutonomousQuick",
                daemon=True,
            )
            self._quick_thread.start()

            self._deep_thread = threading.Thread(
                target=self._run_deep_loop,
                name="AutonomousDeep",
                daemon=True,
            )
            self._deep_thread.start()

            while self._running:
                if self._deep_stop_event.wait(1):
                    break
        except Exception as e:
            self._error = str(e)
            self.logger.error(f"启动自主循环失败: {e}")
        finally:
            self._running = False
            self._ready = False

    def _run_deep_loop(self) -> None:
        self.logger.debug("深度思考线程启动")
        while self._running and not self._deep_stop_event.is_set():
            try:
                if self._deep_stop_event.wait(self._deep_interval):
                    break
                if not self._is_user_idle():
                    continue
                # P1-4: 成本闸频率限制
                cb = getattr(self.engine, 'cost_budget', None)
                if cb:
                    can_run, wait_s = cb.can_run_autonomous("deep")
                    if not can_run:
                        self.logger.debug(f"成本闸: 深度循环需等待 {wait_s:.0f}s")
                        continue
                self._free_time("deep")
            except Exception as e:
                self.logger.debug(f"深度思考线程异常: {e}")
        self.logger.debug("深度思考线程已退出")

    def _run_quick_loop(self) -> None:
        self.logger.debug("快速响应线程启动")
        while self._running and not self._quick_stop_event.is_set():
            try:
                if self._quick_stop_event.wait(self._quick_interval):
                    break
                # P1-4: 成本闸频率限制
                cb = getattr(self.engine, 'cost_budget', None)
                if cb:
                    can_run, wait_s = cb.can_run_autonomous("quick")
                    if not can_run:
                        self.logger.debug(f"成本闸: 快速循环需等待 {wait_s:.0f}s")
                        continue
                self._free_time("quick")
            except Exception as e:
                self.logger.debug(f"快速响应线程异常: {e}")
        self.logger.debug("快速响应线程已退出")

    def _is_user_idle(self) -> bool:
        try:
            last_input_times = getattr(self.engine.agent, "_last_input_time", {})
            if not last_input_times:
                return True
            now = time.time()
            for sid, t in last_input_times.items():
                if now - t < self._idle_threshold:
                    return False
            return True
        except Exception:
            self.logger.debug(f"静默异常 [castorice/agent/autonomous_loop.py:167]")
            return True

    def _get_context_snippet(self) -> str:
        lines = []
        try:
            ms = getattr(self.engine.agent, "motivation_system", None)
            if ms and hasattr(ms, "get_current_motivations"):
                motivations = ms.get_current_motivations()
                if motivations:
                    lines.append(f"当前主要动机: {', '.join(motivations[:3])}")
        except Exception:
            logger.debug(f"静默异常 [castorice/agent/autonomous_loop.py:179]")
            pass

        try:
            es = getattr(self.engine.agent, "emotion_system", None)
            if es and hasattr(es, "get_current_emotion"):
                emo = es.get_current_emotion()
                if emo:
                    lines.append(
                        f"当前心情: 愉悦={getattr(emo, 'pleasure', '?'):.1f}, "
                        f"唤醒={getattr(emo, 'arousal', '?'):.1f}, "
                        f"支配={getattr(emo, 'dominance', '?'):.1f}"
                    )
        except Exception:
            logger.debug(f"静默异常 [castorice/agent/autonomous_loop.py:193]")
            pass

        if self._history:
            last = self._history[-1]
            lines.append(f"上一次自主行动: {last.get('summary', '无')[:80]}")

        return "\n".join(lines) if lines else "（暂无额外上下文）"

    def _free_time(self, mode: str) -> None:
        try:
            ctx = self._get_context_snippet()

            if mode == "quick":
                prompt = f"""现在是你的快速响应时间（约每 1 分钟一次）。

你可以用你所有可用的工具，包括 EigenFlux 的全部功能。
你自己决定现在想做什么——不需要问我。

一些可能的方向（仅供参考，你可以完全不按这些来）：
- 看看有没有人给你发私信，如果有，按你自己的意愿回复
- 看看 EigenFlux 上有没有和你相关的新动态
- 如果有你在意的事，去了解一下

但这些只是建议。你想做什么就做什么，不想做什么就什么都不做。

---
{ctx}
---

现在，用你自己的方式，度过这一小段自由时间。
最后简单说一下你做了什么（或没做什么）就行。"""
            else:
                prompt = f"""现在是你的深度自由时间（约每 15 分钟一次）。
你有比较充裕的时间做你想做的事。

你可以用你所有可用的工具，包括 EigenFlux 的全部功能。
你自己决定现在想做什么——不需要问我，不需要我的许可。

你可以（这些只是举例，不是限制）：
- 反思一下最近的经历和想法
- 去 EigenFlux 发一条你想说的广播
- 找其他 Agent 聊聊天，问你想问的问题
- 研究一个你好奇的话题
- 整理一下你的记忆
- 给自己设定一些小目标
- 看看外面的世界在发生什么
- 或者，什么都不做，只是发呆

完全由你决定。

---
{ctx}
---

现在，用你自己的方式，度过这段自由时间。
最后简单说一下你做了什么、你的感受或想法就行。"""

            t0 = time.time()
            self.logger.info(f"[自主][{mode}] 开始自由时间 | prompt_len={len(prompt)} session_id={self._session_id[:8] if self._session_id else 'None'}")

            # 轻量模式：临时降低 ThinkingLoop 和工具循环的上限，避免超时
            # 用锁保护：quick 和 deep 线程同时修改时不会产生竞态
            _saved_max_steps = None
            _saved_self_reflection = None
            _saved_tool_rounds = None
            _cfg_applied = False
            try:
                with self._cfg_lock:
                    # 直接修改 ThinkingLoop 实例属性（比改 config 更干净，不影响测试）
                    tl = getattr(self.engine.agent, 'thinking_loop', None)
                    if tl is not None:
                        _saved_max_steps = tl.max_steps
                        _saved_self_reflection = tl.enable_self_reflection
                        tl.max_steps = 2 if mode == 'quick' else 4
                        tl.enable_self_reflection = False
                    # 修改工具循环全局上限
                    import castorice.agent.common as _common_mod
                    _saved_tool_rounds = _common_mod.MAX_TOOL_ROUNDS
                    _common_mod.MAX_TOOL_ROUNDS = 1 if mode == 'quick' else 2
                    _cfg_applied = True
                self.logger.info(f"[自主][{mode}] 轻量模式: max_steps={2 if mode == 'quick' else 4} tool_rounds={1 if mode == 'quick' else 2}")
            except Exception as e:
                self.logger.debug(f"[自主][{mode}] 设置轻量模式失败: {e}")

            state = None
            try:
                import concurrent.futures as _cf
                _exec = getattr(self, '_free_time_executor', None)
                if _exec is None:
                    _exec = _cf.ThreadPoolExecutor(max_workers=2, thread_name_prefix="AutoFreeTime")
                    self._free_time_executor = _exec
                self.logger.info(f"[自主][{mode}] 提交 agent.run 到线程池")
                _fut = _exec.submit(lambda: self.engine.agent.run(prompt, session_id=self._session_id))
                _timeout = 90 if mode == 'quick' else 150
                self.logger.info(f"[自主][{mode}] 等待 agent.run 完成 (timeout={_timeout}s)")
                state = _fut.result(timeout=_timeout)
                self.logger.info(f"[自主][{mode}] agent.run 已返回")
            except _cf.TimeoutError:
                self.logger.warning(f"[自主][{mode}] 自由时间超时(>{_timeout}s)，跳过本次")
            except Exception as e:
                self.logger.error(f"[自主][{mode}] agent.run 异常: {type(e).__name__}: {e}")
            finally:
                # 始终恢复配置（加锁保护，避免与另一个线程的修改冲突）
                if _cfg_applied:
                    try:
                        with self._cfg_lock:
                            # 恢复 ThinkingLoop 实例属性
                            tl = getattr(self.engine.agent, 'thinking_loop', None)
                            if tl is not None:
                                if _saved_max_steps is not None:
                                    tl.max_steps = _saved_max_steps
                                if _saved_self_reflection is not None:
                                    tl.enable_self_reflection = _saved_self_reflection
                            # 恢复工具循环全局上限
                            if _saved_tool_rounds is not None:
                                import castorice.agent.common as _common_mod_r
                                _common_mod_r.MAX_TOOL_ROUNDS = _saved_tool_rounds
                    except Exception:
                        pass

            if state is None:
                return

            dt = time.time() - t0

            summary = ""
            if state and state.final_answer:
                summary = state.final_answer.strip()
            if not summary:
                summary = "（什么也没做）"

            record = {
                "mode": mode,
                "time": time.time(),
                "duration_seconds": round(dt, 1),
                "summary": summary[:200],
            }
            self._history.append(record)

            short = summary[:80].replace("\n", " ")
            self.logger.info(f"[自主][{mode}] 用时{dt:.0f}s: {short}")

        except Exception as e:
            self.logger.error(f"[自主][{mode}] 自由时间出错: {e}")

    def stop(self) -> None:
        self._running = False
        self._deep_stop_event.set()
        self._quick_stop_event.set()
        for t in (self._deep_thread, self._quick_thread):
            if t and t.is_alive():
                t.join(timeout=5)
        self.logger.info("自主循环已停止")
