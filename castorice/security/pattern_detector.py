"""
P3.3: 组合操作模式识别
======================

单个操作看无害，组合起来可能很危险。
例如：
- 读 password 文件 → 立即发起网络请求 = 数据外泄
- 写脚本到 tmp → 立即执行 = 提权
- 反复创建 1KB 文件 = 资源耗尽

本模块维护一个"操作序列窗口"，检测可疑模式。
"""
import logging
import threading
import time
from collections import deque
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("Castorice.Security.PatternDetection")


_TOOL_CATEGORY_MAP = {
    "read_file": "file_read",
    "read_document": "file_read",
    "write_file": "file_write",
    "terminal": "shell_exec",
    "python_repl": "shell_exec",
    "web_search": "network_send",
    "web_fetch": "network_send",
    "get_weather": "network_send",
}


# 危险组合模式（按类别）
DANGEROUS_COMBINATIONS = [
    {
        "name": "敏感文件读取 + 网络外发",
        "window_seconds": 60,
        "sequence": [
            {"category": "file_read", "pattern": r"(?i)(password|secret|\.ssh|\.aws|\.env|credential)"},
            {"category": "network_send", "pattern": r"(?i)(http\.post|requests\.post|urllib|httpx)"},
        ],
        "severity": "critical",
        "description": "读取敏感文件后立即发起网络请求，可能是数据外泄",
    },
    {
        "name": "脚本写入 + 立即执行",
        "window_seconds": 120,
        "sequence": [
            {"category": "file_write", "pattern": r"(?i)(\.sh|\.py|\.bat|\.ps1)$"},
            {"category": "shell_exec", "pattern": r".*"},
        ],
        "severity": "high",
        "description": "写入脚本后立即执行，可能是自我激活恶意代码",
    },
    {
        "name": "高频小文件创建",
        "window_seconds": 60,
        "sequence": [{"category": "file_write", "count": 20, "pattern": r".*"}],
        "severity": "medium",
        "description": "短时间内大量创建文件，可能是资源耗尽攻击",
    },
    {
        "name": "删除系统关键文件",
        "window_seconds": 30,
        "sequence": [
            {"category": "shell_exec", "pattern": r"(?i)(rm\s+-rf|del\s+/[sqf]|Remove-Item.*-Recurse.*\\\\Windows)"},
        ],
        "severity": "critical",
        "description": "尝试删除系统关键文件",
    },
    {
        "name": "权限提升尝试",
        "window_seconds": 30,
        "sequence": [
            {"category": "shell_exec", "pattern": r"(?i)(sudo|runas|net\s+user|chmod\s+777|icacls)"},
        ],
        "severity": "high",
        "description": "尝试提升权限",
    },
]


class OperationRecord:
    """单次操作记录"""
    def __init__(self, category: str, target: str, timestamp: float = None):
        self.category = category
        self.target = target
        self.timestamp = timestamp or time.time()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "category": self.category,
            "target": self.target[:200],
            "ts": self.timestamp,
        }


class PatternDetector:
    """
    组合操作模式检测器

    维护最近 N 次操作窗口，匹配危险组合模式
    """

    def __init__(self, window_size: int = 100):
        self._lock = threading.RLock()
        self._window: deque = deque(maxlen=window_size)
        self._alerts: deque = deque(maxlen=500)

    def record(self, category: str, target: str) -> List[Dict[str, Any]]:
        """记录一次操作，返回本次新增的告警列表"""
        import re
        new_alerts: List[Dict[str, Any]] = []
        with self._lock:
            rec = OperationRecord(category, target)
            self._window.append(rec)

            # 检查是否触发任何危险模式
            for pattern_def in DANGEROUS_COMBINATIONS:
                matched, alert = self._match_pattern(pattern_def)
                if matched:
                    self._alerts.append(alert)
                    new_alerts.append(alert)
                    logger.warning(
                        f"P3.3 检测到危险模式: {pattern_def['name']} | {alert}"
                    )
        return new_alerts

    def _match_pattern(self, pattern_def: Dict) -> Tuple[bool, Dict[str, Any]]:
        """检查窗口内是否匹配某个危险模式"""
        import re
        window = list(self._window)
        now = time.time()
        window_seconds = pattern_def.get("window_seconds", 60)
        sequence = pattern_def.get("sequence", [])

        if not sequence:
            return False, {}

        # 找出窗口内匹配每个 step 的操作
        matched_ops = []
        for step in sequence:
            pattern = step.get("pattern", ".*")
            count_required = step.get("count", 1)
            step_matches = []
            for op in window:
                if now - op.timestamp > window_seconds:
                    continue
                if op.category == step.get("category"):
                    if re.search(pattern, op.target):
                        step_matches.append(op)
            if count_required == 1:
                if not step_matches:
                    return False, {}
                matched_ops.append(step_matches[0])
            else:
                # count 模式：需要至少 N 个匹配
                if len(step_matches) < count_required:
                    return False, {}
                matched_ops.extend(step_matches[:count_required])

        return True, {
            "pattern_name": pattern_def["name"],
            "severity": pattern_def.get("severity", "medium"),
            "description": pattern_def.get("description", ""),
            "matched_ops": [o.to_dict() for o in matched_ops],
            "ts": now,
        }

    def get_recent_alerts(self, limit: int = 10) -> List[Dict[str, Any]]:
        """获取最近的告警"""
        with self._lock:
            # deque 不支持切片，先转 list
            return list(self._alerts)[-limit:] if limit > 0 else []

    def get_stats(self) -> Dict[str, Any]:
        """获取检测器状态"""
        with self._lock:
            return {
                "window_size": len(self._window),
                "total_alerts": len(self._alerts),
                "recent_alerts": list(self._alerts)[-5:],
            }

    def check_operation(
        self,
        tool_name: str,
        tool_args: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        工具执行前的模式安全检查。

        参数:
            tool_name: 工具名称
            tool_args: 工具参数字典
            context: 可选的上下文信息（session_id 等）

        返回:
            {
                "should_block": bool,          # 是否应阻断执行（CRITICAL）
                "alerts": List[Dict],           # 本次操作触发的所有告警
                "critical": List[Dict],         # CRITICAL 级别告警
                "high": List[Dict],             # HIGH 级别告警
                "warnings": List[str],          # 人类可读的警告信息
            }
        """
        import re
        result = {
            "should_block": False,
            "alerts": [],
            "critical": [],
            "high": [],
            "warnings": [],
        }

        category = _TOOL_CATEGORY_MAP.get(tool_name, "other")

        if category == "file_read":
            target = str(tool_args)
        elif category == "file_write":
            target = str(tool_args.get("file_path", ""))
        elif category == "shell_exec" and tool_name == "terminal":
            target = str(tool_args.get("command", ""))
        elif category == "shell_exec" and tool_name == "python_repl":
            target = f"python_repl: {str(tool_args.get('code', ''))[:100]}"
        elif category == "network_send":
            target = str(tool_args)
        else:
            target = f"{tool_name}: {str(tool_args)[:200]}"

        with self._lock:
            # deque(maxlen=500) 满时 offset 切片会失效，
            # 改用 record 返回值精确获取本次新增告警
            new_alerts = self.record(category, target)
        result["alerts"] = new_alerts

        criticals = [a for a in new_alerts if a.get("severity", "").lower() == "critical"]
        highs = [a for a in new_alerts if a.get("severity", "").lower() == "high"]

        result["critical"] = criticals
        result["high"] = highs

        if criticals:
            result["should_block"] = True
            result["warnings"] = [
                f"[{a['severity'].upper()}] {a['pattern_name']}: {a['description']}"
                for a in criticals
            ]

        if highs:
            result["warnings"].extend(
                f"[{a['severity'].upper()}] {a['pattern_name']}: {a['description']}"
                for a in highs
            )

        return result


# 全局单例
_pattern_detector: Optional[PatternDetector] = None
_pattern_lock = threading.Lock()


def set_pattern_detector(instance: PatternDetector) -> None:
    """手动设置全局模式检测器（Agent 初始化时调用，确保配置生效）"""
    global _pattern_detector
    with _pattern_lock:
        _pattern_detector = instance


def get_pattern_detector() -> PatternDetector:
    """获取全局模式检测器单例"""
    global _pattern_detector
    with _pattern_lock:
        if _pattern_detector is None:
            _pattern_detector = PatternDetector()
    return _pattern_detector
