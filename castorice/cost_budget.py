"""
成本预算与速率限制（CostBudget）

防止 LLM 调用失控：
- 每小时 / 每天 token 硬上限
- ThinkingLoop 每会话步数上限
- AutonomousLoop 空闲反思频率硬上限
- 超阈值自动降频 / 暂停自主活动
"""
import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, Optional, Tuple

logger = logging.getLogger("Castorice.CostBudget")


@dataclass
class BudgetConfig:
    """成本预算配置（软闸，仅降频/暂停自主活动，不阻断用户主动对话）

    默认值为保守的软上限：足够日常重度使用，但防止 token 爆炸。
    所有值设为 0 表示不限制。
    """
    # Token 预算
    hourly_token_limit: int = 500_000     # 每小时 token 软上限（≈500K）
    daily_token_limit: int = 5_000_000    # 每天 token 软上限（≈5M）
    # 调用频率
    hourly_call_limit: int = 1000          # 每小时调用次数软上限
    # 每会话步数
    per_session_thinking_steps: int = 16   # ThinkingLoop 每会话最大步数
    # AutonomousLoop 频率（秒）
    autonomous_quick_min_interval: int = 30     # 快速循环最小间隔
    autonomous_deep_min_interval: int = 180      # 深度循环最小间隔
    # 降频阈值（0-1，达到预算比例时开始降频）
    throttle_threshold: float = 0.85
    # 暂停阈值（0-1，达到预算比例时暂停自主活动）
    pause_threshold: float = 0.98
    # 总开关（False 时完全禁用成本闸，所有检查直接通过）
    enabled: bool = True


@dataclass
class _TokenWindow:
    """滑动窗口 token 统计"""
    tokens: int = 0
    calls: int = 0
    start_ts: float = field(default_factory=time.time)


class CostBudget:
    """成本预算管理器（线程安全）"""

    def __init__(self, config: Optional[BudgetConfig] = None):
        self._config = config or BudgetConfig()
        self._lock = threading.RLock()

        # 滑动窗口统计
        self._hourly = _TokenWindow()
        self._daily = _TokenWindow()

        # 每会话步数计数
        self._session_steps: Dict[str, int] = {}
        self._session_last_reset: Dict[str, float] = {}

        # AutonomousLoop 上次执行时间
        self._last_quick: float = 0
        self._last_deep: float = 0

        # 告警标志
        self._throttled: bool = False
        self._paused: bool = False

        logger.info(
            f"成本闸已初始化: hourly_tokens={self._config.hourly_token_limit or '∞'}, "
            f"daily_tokens={self._config.daily_token_limit or '∞'}, "
            f"session_steps={self._config.per_session_thinking_steps}"
        )

    # ============== 配置更新 ==============

    def update_config(self, updates: Dict[str, Any]) -> Dict[str, Any]:
        """运行时更新预算配置"""
        applied = {}
        with self._lock:
            for key, val in updates.items():
                if hasattr(self._config, key) and val is not None:
                    try:
                        target_type = type(getattr(self._config, key))
                        if target_type is bool:
                            # 特殊处理布尔：支持 bool/字符串 "true"/"false"/"1"/"0"/数字 0/1
                            if isinstance(val, bool):
                                converted = val
                            elif isinstance(val, str):
                                converted = val.lower() in ("true", "1", "yes", "on")
                            else:
                                converted = bool(val)
                        else:
                            converted = target_type(val)
                        setattr(self._config, key, converted)
                        applied[key] = getattr(self._config, key)
                    except (TypeError, ValueError):
                        pass
        if applied:
            logger.info(f"成本闸配置已更新: {applied}")
        return applied

    def get_config(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "enabled": self._config.enabled,
                "hourly_token_limit": self._config.hourly_token_limit,
                "daily_token_limit": self._config.daily_token_limit,
                "hourly_call_limit": self._config.hourly_call_limit,
                "per_session_thinking_steps": self._config.per_session_thinking_steps,
                "autonomous_quick_min_interval": self._config.autonomous_quick_min_interval,
                "autonomous_deep_min_interval": self._config.autonomous_deep_min_interval,
                "throttle_threshold": self._config.throttle_threshold,
                "pause_threshold": self._config.pause_threshold,
            }

    # ============== Token 统计 ==============

    def record_usage(self, prompt_tokens: int, completion_tokens: int) -> None:
        """记录一次 LLM 调用的 token 用量"""
        if not self._config.enabled:
            return
        total = prompt_tokens + completion_tokens
        now = time.time()
        with self._lock:
            # 重置过期窗口
            if now - self._hourly.start_ts > 3600:
                self._hourly = _TokenWindow(start_ts=now)
            if now - self._daily.start_ts > 86400:
                self._daily = _TokenWindow(start_ts=now)

            self._hourly.tokens += total
            self._hourly.calls += 1
            self._daily.tokens += total
            self._daily.calls += 1

            self._check_limits_locked(now)

    def _check_limits_locked(self, now: float) -> None:
        """（需在锁内）检查预算状态并更新标志"""
        hour_ratio = 0.0
        day_ratio = 0.0
        call_ratio = 0.0

        if self._config.hourly_token_limit > 0:
            hour_ratio = self._hourly.tokens / self._config.hourly_token_limit
        if self._config.daily_token_limit > 0:
            day_ratio = self._daily.tokens / self._config.daily_token_limit
        if self._config.hourly_call_limit > 0:
            call_ratio = self._hourly.calls / self._config.hourly_call_limit

        max_ratio = max(hour_ratio, day_ratio, call_ratio)

        was_throttled = self._throttled
        was_paused = self._paused

        self._throttled = max_ratio >= self._config.throttle_threshold
        self._paused = max_ratio >= self._config.pause_threshold

        if self._throttled and not was_throttled:
            logger.warning(
                f"⚠️  成本闸: 已进入降频模式（预算使用率 {max_ratio:.0%}）。"
                f"自主活动频率将降低。"
            )
        if self._paused and not was_paused:
            logger.error(
                f"🛑 成本闸: 已暂停自主活动（预算使用率 {max_ratio:.0%}）。"
                f"请关注 token 消耗，或调整预算上限。"
            )
        if not self._throttled and was_throttled:
            logger.info("✅ 成本闸: 降频模式已解除")
        if not self._paused and was_paused:
            logger.info("✅ 成本闸: 自主活动已恢复")

    # ============== ThinkingLoop 步数限制 ==============

    def can_take_step(self, session_id: str) -> bool:
        """检查该会话是否还允许继续 ThinkingLoop 步数"""
        if not self._config.enabled:
            return True
        if self._config.per_session_thinking_steps <= 0:
            return True
        with self._lock:
            # 每 24 小时重置一次步数计数
            last_reset = self._session_last_reset.get(session_id, 0)
            now = time.time()
            if now - last_reset > 86400:
                self._session_steps[session_id] = 0
                self._session_last_reset[session_id] = now

            steps = self._session_steps.get(session_id, 0)
            if steps >= self._config.per_session_thinking_steps:
                logger.warning(
                    f"成本闸: 会话 {session_id[:8]} 已达 ThinkingLoop 步数上限 "
                    f"({self._config.per_session_thinking_steps} 步/天)"
                )
                return False
            self._session_steps[session_id] = steps + 1
            return True

    # ============== AutonomousLoop 频率限制 ==============

    def can_run_autonomous(self, mode: str) -> Tuple[bool, float]:
        """
        检查自主循环是否可以运行。
        返回: (是否允许, 需要等待的秒数)
        """
        if not self._config.enabled:
            return True, 0
        if self._paused:
            return False, 300  # 暂停状态 5 分钟后再检查

        with self._lock:
            now = time.time()
            if mode == "quick":
                min_interval = self._config.autonomous_quick_min_interval
                # 降频模式下间隔加倍
                if self._throttled:
                    min_interval *= 2
                elapsed = now - self._last_quick
                if elapsed < min_interval:
                    return False, min_interval - elapsed
                self._last_quick = now
                return True, 0
            elif mode == "deep":
                min_interval = self._config.autonomous_deep_min_interval
                if self._throttled:
                    min_interval *= 2
                elapsed = now - self._last_deep
                if elapsed < min_interval:
                    return False, min_interval - elapsed
                self._last_deep = now
                return True, 0
            return True, 0

    # ============== 状态查询 ==============

    def get_status(self) -> Dict[str, Any]:
        """获取当前预算使用状态"""
        now = time.time()
        with self._lock:
            hour_elapsed = now - self._hourly.start_ts
            day_elapsed = now - self._daily.start_ts

            hour_ttl = max(0, 3600 - hour_elapsed) if self._hourly.tokens > 0 else 0
            day_ttl = max(0, 86400 - day_elapsed) if self._daily.tokens > 0 else 0

            hour_used_pct = (
                self._hourly.tokens / self._config.hourly_token_limit * 100
                if self._config.hourly_token_limit > 0 else 0
            )
            day_used_pct = (
                self._daily.tokens / self._config.daily_token_limit * 100
                if self._config.daily_token_limit > 0 else 0
            )

            return {
                "enabled": self._config.enabled,
                "throttled": self._throttled,
                "paused": self._paused,
                "hourly": {
                    "tokens": self._hourly.tokens,
                    "calls": self._hourly.calls,
                    "limit": self._config.hourly_token_limit,
                    "used_pct": round(hour_used_pct, 1),
                    "ttl_seconds": round(hour_ttl),
                },
                "daily": {
                    "tokens": self._daily.tokens,
                    "calls": self._daily.calls,
                    "limit": self._config.daily_token_limit,
                    "used_pct": round(day_used_pct, 1),
                    "ttl_seconds": round(day_ttl),
                },
                "config": {
                    "enabled": self._config.enabled,
                    "hourly_token_limit": self._config.hourly_token_limit,
                    "daily_token_limit": self._config.daily_token_limit,
                    "hourly_call_limit": self._config.hourly_call_limit,
                    "per_session_thinking_steps": self._config.per_session_thinking_steps,
                    "autonomous_quick_min_interval": self._config.autonomous_quick_min_interval,
                    "autonomous_deep_min_interval": self._config.autonomous_deep_min_interval,
                    "throttle_threshold": self._config.throttle_threshold,
                    "pause_threshold": self._config.pause_threshold,
                },
            }
