"""
P3.1: L5 渐进授权系统
======================

设计目标：
- Agent 不是一开始就被授予所有权限
- 通过"连续成功 N 次"自动提升信任等级
- 信任等级决定 Agent 可执行的操作范围
- 失败时自动降级

信任等级（从低到高）：
- L0: 只读（仅允许 long_term 检索、self_concept 读、experience_journal 读）
- L1: 自我数据写入（允许更新 self_concept、写入 user_profile）
- L2: 业务工具调用（允许 read_file、web_search 等只读工具）
- L3: 写工具（允许 write_file 创建新文件）
- L4: 系统工具（允许 terminal、python_repl，但有审计）
- L5: 完全自主（需要人工明确授权）

每个等级都有"晋升条件"和"降级条件"。
"""
import logging
import threading
import time
from collections import deque
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("Castorice.Security.Authorization")


# 操作分类（每个操作属于一个信任等级）
OPERATION_TRUST_LEVELS = {
    # L0 - 只读
    "long_term.read": 0,
    "self_concept.read": 0,
    "experience_journal.read": 0,
    "self_awareness.read": 0,
    # L1 - 自我数据
    "self_concept.write": 1,
    "user_profile.write": 1,
    "experience_journal.write": 1,
    "long_term.write": 1,
    # L2 - 业务工具（只读类）
    "tool.read_file": 2,
    "tool.web_search": 2,
    "tool.get_weather": 2,
    "tool.read_document": 2,
    # L3 - 写工具
    "tool.write_file.new": 3,
    "tool.write_file.data_only": 3,  # 只能写数据目录
    # L4 - 系统工具
    "tool.terminal": 4,
    "tool.python_repl": 4,
    "tool.write_file.system": 4,  # 可以写系统路径（被 L1 黑名单拦截的除外）
    # L5 - 需要明确人工授权
    "self_modify": 5,
    "memory_purge": 5,
    "configuration_change": 5,
}


class ProgressiveAuthorization:
    """
    渐进授权管理器

    跟踪 Agent 在不同操作上的成功率，自动晋升/降级信任等级
    """

    def __init__(self, initial_level: int = 1, promotion_threshold: int = 5,
                 demotion_threshold: int = 2):
        """
        :param initial_level: 初始信任等级
        :param promotion_threshold: 连续成功 N 次可晋升
        :param demotion_threshold: 连续失败 N 次降级
        """
        self._lock = threading.RLock()
        self.current_level = initial_level
        self.promotion_threshold = promotion_threshold
        self.demotion_threshold = demotion_threshold

        # 每个操作的成功/失败历史（deque）
        self._operation_history: Dict[str, deque] = {}

        # 晋升/降级事件日志
        self._events: List[Dict[str, Any]] = []

    def is_allowed(self, operation: str) -> Tuple[bool, str]:
        """
        检查操作是否被允许

        :return: (allowed, reason)
        """
        with self._lock:
            required_level = OPERATION_TRUST_LEVELS.get(operation, 0)
            if self.current_level >= required_level:
                return True, f"信任等级 {self.current_level} >= 所需 {required_level}"
            return False, (
                f"操作 '{operation}' 需要信任等级 {required_level}，"
                f"当前 {self.current_level}"
            )

    def record_outcome(self, operation: str, success: bool) -> None:
        """
        记录一次操作结果（用于信任等级评估）
        """
        with self._lock:
            if operation not in self._operation_history:
                self._operation_history[operation] = deque(maxlen=20)
            self._operation_history[operation].append({
                "success": success,
                "ts": time.time(),
            })

            # 检查是否需要晋升/降级
            recent = [h for h in self._operation_history[operation]
                      if time.time() - h["ts"] < 3600]  # 1h 内
            if not recent:
                return

            consecutive_success = 0
            consecutive_fail = 0
            for h in reversed(recent):
                if h["success"]:
                    consecutive_success += 1
                    consecutive_fail = 0
                else:
                    consecutive_fail += 1
                    consecutive_success = 0
                if consecutive_success >= self.promotion_threshold:
                    self._promote(reason=f"操作 {operation} 连续成功 {consecutive_success} 次")
                    break
                if consecutive_fail >= self.demotion_threshold:
                    self._demote(reason=f"操作 {operation} 连续失败 {consecutive_fail} 次")
                    break

    def _promote(self, reason: str) -> None:
        """晋升信任等级"""
        if self.current_level >= 5:
            return
        old = self.current_level
        self.current_level += 1
        event = {
            "type": "promotion",
            "from": old,
            "to": self.current_level,
            "reason": reason,
            "ts": time.time(),
        }
        self._events.append(event)
        logger.info(f"P3.1 信任等级晋升: {old} → {self.current_level} ({reason})")

    def _demote(self, reason: str) -> None:
        """降级信任等级"""
        if self.current_level <= 0:
            return
        old = self.current_level
        self.current_level -= 1
        event = {
            "type": "demotion",
            "from": old,
            "to": self.current_level,
            "reason": reason,
            "ts": time.time(),
        }
        self._events.append(event)
        logger.warning(f"P3.1 信任等级降级: {old} → {self.current_level} ({reason})")

    def force_set_level(self, level: int, reason: str = "人工调整") -> None:
        """强制设置信任等级（人工调整）"""
        with self._lock:
            if not 0 <= level <= 5:
                logger.warning(f"P3.1 无效信任等级: {level}")
                return
            old = self.current_level
            self.current_level = level
            self._events.append({
                "type": "manual",
                "from": old,
                "to": level,
                "reason": reason,
                "ts": time.time(),
            })
            logger.info(f"P3.1 人工设置信任等级: {old} → {level} ({reason})")

    def get_status(self) -> Dict[str, Any]:
        """获取授权系统状态"""
        with self._lock:
            return {
                "current_level": self.current_level,
                "operation_history_count": {
                    op: len(hist) for op, hist in self._operation_history.items()
                },
                "recent_events": self._events[-10:],
            }


# 全局单例
_auth_instance: Optional[ProgressiveAuthorization] = None
_auth_lock = threading.Lock()


def get_authorization(initial_level: int = 1) -> ProgressiveAuthorization:
    """获取全局授权管理器单例"""
    global _auth_instance
    with _auth_lock:
        if _auth_instance is None:
            _auth_instance = ProgressiveAuthorization(initial_level=initial_level)
    return _auth_instance
