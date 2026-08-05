"""
P0-1: 熔断器 (Circuit Breaker)

经典熔断器三态模型：
- CLOSED:   正常状态，所有请求通过
- OPEN:     熔断状态，所有请求快速失败
- HALF_OPEN: 半开状态，放少量请求试探

使用方式：
    cb = CircuitBreaker("llm_freellmapi", failure_threshold=5, recovery_timeout=30)
    try:
        with cb:
            result = llm_call(...)
    except CircuitOpenError:
        # 熔断了，走降级
        result = fallback(...)
"""
import logging
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger("Castorice.CircuitBreaker")


class CircuitState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitOpenError(Exception):
    """熔断器处于 OPEN 状态，请求被拒绝"""
    pass


@dataclass
class CircuitStats:
    """熔断器统计"""
    state: str = "closed"
    total_calls: int = 0
    total_failures: int = 0
    total_successes: int = 0
    consecutive_failures: int = 0
    consecutive_successes: int = 0
    last_failure_ts: float = 0.0
    last_success_ts: float = 0.0
    last_state_change_ts: float = 0.0
    open_count: int = 0  # 历史熔断总次数


class CircuitBreaker:
    """
    线程安全的熔断器实现

    参数：
    - name:               熔断器名称（用于日志和指标）
    - failure_threshold:   连续失败多少次后熔断（默认 5）
    - recovery_timeout:    熔断后多少秒进入半开状态（默认 30 秒）
    - half_open_successes: 半开状态需要连续成功多少次才恢复闭合（默认 2）
    - exception_predicate: 哪些异常算"失败"（默认所有异常都算）
    """

    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
        half_open_successes: int = 2,
        exception_predicate: Optional[Callable[[Exception], bool]] = None,
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_successes = half_open_successes
        self.exception_predicate = exception_predicate or (lambda e: True)

        self._lock = threading.RLock()
        self._state = CircuitState.CLOSED
        self._stats = CircuitStats(last_state_change_ts=time.time())

        logger.info(
            f"熔断器 [{name}] 初始化: "
            f"failure_threshold={failure_threshold}, "
            f"recovery_timeout={recovery_timeout}s"
        )

    # ============== 状态查询 ==============

    @property
    def state(self) -> CircuitState:
        with self._lock:
            self._maybe_transition_to_half_open()
            return self._state

    def is_available(self) -> bool:
        """是否允许请求通过（非 OPEN 状态）"""
        return self.state != CircuitState.OPEN

    def get_stats(self) -> Dict[str, Any]:
        """获取统计快照"""
        with self._lock:
            return {
                "name": self.name,
                "state": self._stats.state,
                "total_calls": self._stats.total_calls,
                "total_failures": self._stats.total_failures,
                "total_successes": self._stats.total_successes,
                "consecutive_failures": self._stats.consecutive_failures,
                "consecutive_successes": self._stats.consecutive_successes,
                "last_failure_seconds_ago": round(time.time() - self._stats.last_failure_ts, 1) if self._stats.last_failure_ts > 0 else None,
                "last_success_seconds_ago": round(time.time() - self._stats.last_success_ts, 1) if self._stats.last_success_ts > 0 else None,
                "open_count": self._stats.open_count,
                "thresholds": {
                    "failure_threshold": self.failure_threshold,
                    "recovery_timeout": self.recovery_timeout,
                    "half_open_successes": self.half_open_successes,
                },
            }

    # ============== 上下文管理器 ==============

    def __enter__(self):
        with self._lock:
            self._maybe_transition_to_half_open()
            if self._state == CircuitState.OPEN:
                raise CircuitOpenError(
                    f"熔断器 [{self.name}] 处于 OPEN 状态，"
                    f"{self.recovery_timeout}s 后恢复"
                )
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        with self._lock:
            self._stats.total_calls += 1
            if exc_type is not None and self.exception_predicate(exc_val):
                self._on_failure_locked()
            else:
                self._on_success_locked()
        return False  # 不吞异常

    # ============== 装饰器模式 ==============

    def __call__(self, func):
        """支持作为装饰器使用"""
        import functools

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            with self:
                return func(*args, **kwargs)
        return wrapper

    # ============== 内部状态转换 ==============

    def _maybe_transition_to_half_open(self) -> None:
        """（需在锁内）检查是否应该从 OPEN 转为 HALF_OPEN"""
        if self._state == CircuitState.OPEN:
            elapsed = time.time() - self._stats.last_state_change_ts
            if elapsed >= self.recovery_timeout:
                self._set_state_locked(CircuitState.HALF_OPEN)
                logger.info(
                    f"熔断器 [{self.name}] 从 OPEN -> HALF_OPEN "
                    f"（等待了 {elapsed:.1f}s）"
                )

    def _on_success_locked(self) -> None:
        """（需在锁内）记录成功"""
        now = time.time()
        self._stats.total_successes += 1
        self._stats.consecutive_successes += 1
        self._stats.consecutive_failures = 0
        self._stats.last_success_ts = now

        if self._state == CircuitState.HALF_OPEN:
            if self._stats.consecutive_successes >= self.half_open_successes:
                self._set_state_locked(CircuitState.CLOSED)
                logger.info(
                    f"熔断器 [{self.name}] 从 HALF_OPEN -> CLOSED "
                    f"（连续成功 {self._stats.consecutive_successes} 次）"
                )

    def _on_failure_locked(self) -> None:
        """（需在锁内）记录失败"""
        now = time.time()
        self._stats.total_failures += 1
        self._stats.consecutive_failures += 1
        self._stats.consecutive_successes = 0
        self._stats.last_failure_ts = now

        if self._state == CircuitState.CLOSED:
            if self._stats.consecutive_failures >= self.failure_threshold:
                self._set_state_locked(CircuitState.OPEN)
                self._stats.open_count += 1
                logger.warning(
                    f"🛑 熔断器 [{self.name}] 从 CLOSED -> OPEN "
                    f"（连续失败 {self._stats.consecutive_failures} 次，"
                    f"{self.recovery_timeout}s 后恢复）"
                )
        elif self._state == CircuitState.HALF_OPEN:
            self._set_state_locked(CircuitState.OPEN)
            self._stats.open_count += 1
            logger.warning(
                f"🛑 熔断器 [{self.name}] 从 HALF_OPEN -> OPEN "
                f"（半开状态失败，再等 {self.recovery_timeout}s）"
            )

    def _set_state_locked(self, new_state: CircuitState) -> None:
        self._state = new_state
        self._stats.state = new_state.value
        self._stats.last_state_change_ts = time.time()

    # ============== 手动控制 ==============

    def reset(self) -> None:
        """手动重置熔断器（恢复 CLOSED 状态，不清统计）"""
        with self._lock:
            self._set_state_locked(CircuitState.CLOSED)
            self._stats.consecutive_failures = 0
            self._stats.consecutive_successes = 0
            logger.info(f"熔断器 [{self.name}] 被手动重置为 CLOSED")

    def force_open(self) -> None:
        """手动强制熔断（用于紧急情况）"""
        with self._lock:
            self._set_state_locked(CircuitState.OPEN)
            logger.warning(f"🛑 熔断器 [{self.name}] 被手动强制 OPEN")
