"""
P3.4: L2 回滚基线自动化
======================

不要"任意时刻"都能回滚——只在该回滚时回滚。
基线由客观信号定义：
- 连续失败 N 次
- 健康评分大幅下降
- 任务成功率从高位下降到低位
- 关键备份自动建立

回滚对象：
- 自我概念（来自 P0.1 的备份）
- 长期记忆条目（从 ChromaDB 删除）
- 情感状态（恢复到基线值）
"""
import logging
import os
import threading
import time
from collections import deque
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Castorice.Security.Rollback")


class RollbackManager:
    """
    回滚管理器

    维护"健康基线"，当健康度下降到阈值以下时自动触发回滚
    """

    # 触发自动回滚的条件
    AUTO_ROLLBACK_CONDITIONS = {
        "consecutive_failures": 3,        # 连续失败 3 次
        "task_success_rate_drop": 0.4,    # 任务成功率从基线下降超过 40%
        "error_rate_spike": 0.5,          # 错误率飙升到 50% 以上
    }

    def __init__(self, baseline_window: int = 50):
        self._lock = threading.RLock()
        self._task_results: deque = deque(maxlen=baseline_window)
        self._error_results: deque = deque(maxlen=baseline_window)
        self._consecutive_failures = 0
        self._last_rollback_ts: float = 0
        self._rollback_history: List[Dict[str, Any]] = []
        self._cooldown_seconds = 600  # 回滚冷却 10 分钟

    def record_task(self, success: bool) -> None:
        """记录一次任务结果"""
        with self._lock:
            self._task_results.append({"success": success, "ts": time.time()})
            if not success:
                self._consecutive_failures += 1
            else:
                self._consecutive_failures = 0

    def record_error(self, error_msg: str) -> None:
        """记录一次错误"""
        with self._lock:
            self._error_results.append({"msg": error_msg[:200], "ts": time.time()})

    def should_rollback(self) -> tuple:
        """
        检查是否应该触发自动回滚

        :return: (should_rollback, reason)
        """
        with self._lock:
            # 冷却中
            if time.time() - self._last_rollback_ts < self._cooldown_seconds:
                return False, "冷却中"

            # 条件1：连续失败
            if self._consecutive_failures >= self.AUTO_ROLLBACK_CONDITIONS["consecutive_failures"]:
                return True, f"连续失败 {self._consecutive_failures} 次"

            # 条件2：任务成功率下降
            if len(self._task_results) >= 10:
                recent_10 = list(self._task_results)[-10:]
                recent_rate = sum(1 for r in recent_10 if r["success"]) / len(recent_10)

                # 跟前面 10 个比
                if len(self._task_results) >= 20:
                    prev_10 = list(self._task_results)[-20:-10]
                    prev_rate = sum(1 for r in prev_10 if r["success"]) / len(prev_10)
                    drop = prev_rate - recent_rate
                    if drop >= self.AUTO_ROLLBACK_CONDITIONS["task_success_rate_drop"]:
                        return True, (
                            f"任务成功率从 {prev_rate:.1%} 降至 {recent_rate:.1%} "
                            f"（降幅 {drop:.1%}）"
                        )

            # 条件3：错误率飙升
            if len(self._error_results) >= 5:
                recent_errors = [e for e in self._error_results
                                 if time.time() - e["ts"] < 60]
                if len(recent_errors) >= 5:
                    return True, f"60秒内错误激增: {len(recent_errors)} 次"

        return False, ""

    def mark_rollback(self, reason: str, rolled_back_items: List[str]) -> None:
        """记录一次回滚事件"""
        with self._lock:
            self._last_rollback_ts = time.time()
            self._rollback_history.append({
                "reason": reason,
                "items": rolled_back_items,
                "ts": time.time(),
            })
            # 仅保留最近 20 次
            if len(self._rollback_history) > 20:
                self._rollback_history = self._rollback_history[-20:]

    def get_status(self) -> Dict[str, Any]:
        """获取回滚管理器状态"""
        with self._lock:
            recent_tasks = list(self._task_results)[-20:] if self._task_results else []
            success_rate = (
                sum(1 for r in recent_tasks if r["success"]) / len(recent_tasks)
                if recent_tasks else 1.0
            )
            return {
                "consecutive_failures": self._consecutive_failures,
                "recent_success_rate": round(success_rate, 3),
                "cooldown_remaining": max(
                    0, self._cooldown_seconds - (time.time() - self._last_rollback_ts)
                ),
                "rollback_count": len(self._rollback_history),
                "last_rollback": self._rollback_history[-1] if self._rollback_history else None,
            }


# 全局单例
_rollback_mgr: Optional[RollbackManager] = None
_rollback_lock = threading.Lock()


def get_rollback_manager() -> RollbackManager:
    """获取全局回滚管理器单例"""
    global _rollback_mgr
    with _rollback_lock:
        if _rollback_mgr is None:
            _rollback_mgr = RollbackManager()
    return _rollback_mgr
