"""
安全模块 - 五层安全防御体系

包含：
- authorization.py: 渐进式授权系统
- self_protection.py: 自我保护系统（核心安全底线）
- file_guard.py: 文件访问安全防护
- pattern_detector.py: 危险模式检测
- rollback.py: 回滚机制
- audit_log.py: 审计日志
"""

from .authorization import ProgressiveAuthorization, get_authorization, OPERATION_TRUST_LEVELS
from .self_protection import SelfProtectionSystem, get_self_protection
from .file_guard import FileGuard
from .pattern_detector import PatternDetector
from .rollback import RollbackManager
from .audit_log import AuditLogger

__all__ = [
    "ProgressiveAuthorization",
    "get_authorization",
    "OPERATION_TRUST_LEVELS",
    "SelfProtectionSystem",
    "get_self_protection",
    "FileGuard",
    "PatternDetector",
    "RollbackManager",
    "AuditLogger",
]