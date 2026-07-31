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
                logger.debug(f"静默异常 [castorice/agent/autonomous_loop.py:76]")
                pass
            if isinstance(auto_cfg, dict):
                self._deep_interval = int(auto_cfg.get("interval_seconds", 900))
                self._quick_interval = int(auto_cfg.get("quick_interval_seconds", 60))
                self._idle_threshold = int(auto_cfg.get("idle_threshold_seconds", 300))

            self._session_id = self.engine.short_term.create_session()
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
            logger.debug(f"静默异常 [castorice/agent/autonomous_loop.py:167]")
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
            state = self.engine.agent.run(prompt, session_id=self._session_id)
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
