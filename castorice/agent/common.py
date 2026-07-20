"""
Agent 模块共享常量和工具函数

避免 core / prompt_builder / tool_loop / memory_ops 之间的循环导入。
"""

import logging
import threading

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
    """获取告警管理器（懒加载，避免顶部强依赖 alerts 模块）"""
    global _alert_manager_ref
    if _alert_manager_ref is None:
        try:
            from castorice.alerts import get_alert_manager as _get
            _alert_manager_ref = _get()
        except Exception:
            return None
    return _alert_manager_ref
