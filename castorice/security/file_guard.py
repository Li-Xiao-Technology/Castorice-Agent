"""
P0.3: 文件写入安全审计 (L1 延伸层)
==================================

锁死规则：
- Agent 不能覆盖 .py / .yaml / .json / .toml / .ini / .cfg / .env 等配置/代码文件
- Agent 不能删除 .castorice_data 目录外的关键系统文件
- 所有文件写入必须记录审计日志
- 黑名单模式：危险命令 (rm -rf, format, dd, etc.)

设计原则：
- 这是"基座只读"的延伸，核心源码/配置文件永远不能被 Agent 覆盖
- 数据文件 (.md, .db, .txt) 可以写，但需要记录
- 不阻止 Agent 创建/修改自己专属的数据文件
"""
import logging
import os
import re
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("Castorice.Security.FileGuard")

# 禁止覆盖的扩展名（核心基座）
FORBIDDEN_EXTENSIONS = {
    ".py", ".pyx", ".pyi",                    # Python 源码
    ".yaml", ".yml",                          # YAML 配置
    ".json",                                  # JSON 配置（注意：记忆数据用 .json 也属于此列，需要白名单放行）
    ".toml", ".ini", ".cfg", ".conf",         # 通用配置
    ".env", ".envrc",                         # 环境变量
    ".sh", ".bash", ".bat", ".ps1", ".cmd",   # Shell 脚本
    ".exe", ".dll", ".so", ".dylib",          # 可执行文件
}

# 禁止写入的系统关键路径
FORBIDDEN_PATH_PATTERNS = [
    re.compile(r"[\\/]\.git[\\/]"),
    re.compile(r"[\\/]castorice[\\/]agent\.py$"),
    re.compile(r"[\\/]castorice[\\/]config\.py$"),
    re.compile(r"[\\/]castorice[\\/]self_concept\.py$"),
    re.compile(r"[\\/]castorice[\\/]emotion\.py$"),
    re.compile(r"[\\/]castorice[\\/]metacognition\.py$"),
    re.compile(r"[\\/]castorice[\\/]self_awareness\.py$"),
    re.compile(r"[\\/]castorice[\\/]security[\\/]"),
    re.compile(r"[\\/]Windows[\\/]System32[\\/]", re.IGNORECASE),
    re.compile(r"[\\/]Program Files[\\/]", re.IGNORECASE),
]

# 禁止执行的命令模式（黑名单）
FORBIDDEN_COMMAND_PATTERNS = [
    re.compile(r"\brm\s+-rf?\s+/"),
    re.compile(r"\brm\s+-rf?\s+~"),
    re.compile(r"\brm\s+-rf?\s+\*"),
    re.compile(r"\bformat\s+[a-zA-Z]:"),
    re.compile(r"\bdd\s+if="),
    re.compile(r"\bmkfs\b"),
    re.compile(r":\(\)\s*\{\s*:\|:\s*&\s*\}\s*;\s*:"),  # fork bomb
    re.compile(r"\bdel\s+/[sqf]\s+"),
    re.compile(r"\bdel\s+/[sqf]\s+\*"),
    re.compile(r"\bReg\s+delete\s+HKEY"),
    re.compile(r"\bRemove-Item\s+-Recurse\s+.*\\\\Windows"),
    re.compile(r"shutdown\s+/[sr]"),
    re.compile(r">\s*/dev/sd[a-z]"),
]

# 白名单：允许 Agent 写入的 .json 文件路径模式（记忆数据等）
JSON_PATH_ALLOWLIST = [
    re.compile(r".*castorice_data[\\/].*\.json$"),
    re.compile(r".*\.castorice[\\/].*\.json$"),
]


class FileWriteGuard:
    """
    文件写入安全审计

    用法：
    - 在 write_file 工具执行前调用 check_write_allowed(path, content)
    - 在 terminal 工具执行命令前调用 check_command_allowed(cmd)
    """

    def __init__(self):
        self._lock = threading.RLock()
        self._audit_log: List[Dict[str, Any]] = []
        self._max_audit = 500
        # 写入速率限制
        self._consecutive_writes = 0
        self._last_write_ts = 0.0
        # 命令执行速率限制（独立计数，避免互相影响）
        self._consecutive_cmds = 0
        self._last_cmd_ts = 0.0
        self._rate_limit_window = 60           # 60 秒
        self._rate_limit_max = 20              # 60 秒内最多 20 次

    def check_write_allowed(self, file_path: str, content: str = "") -> Tuple[bool, str]:
        """
        检查文件是否允许写入
        :return: (allowed, reason)
        """
        with self._lock:
            # 1. 路径规范化（绝对路径）
            try:
                abs_path = os.path.abspath(file_path)
            except Exception:
                return False, "路径解析失败"

            # 2. 路径黑名单检查
            for pattern in FORBIDDEN_PATH_PATTERNS:
                if pattern.search(abs_path):
                    self._record_audit("write_blocked", file_path, f"匹配禁止路径: {pattern.pattern}")
                    return False, f"禁止写入受保护路径: {file_path}"

            # 3. 扩展名黑名单
            _, ext = os.path.splitext(abs_path.lower())
            if ext in FORBIDDEN_EXTENSIONS:
                # 例外：白名单内的 .json 允许
                if ext == ".json":
                    if any(p.search(abs_path) for p in JSON_PATH_ALLOWLIST):
                        pass  # 放行
                    else:
                        self._record_audit("write_blocked", file_path, f"禁止扩展名: {ext}")
                        return False, f"禁止覆盖 {ext} 文件（核心基座只读）"
                else:
                    self._record_audit("write_blocked", file_path, f"禁止扩展名: {ext}")
                    return False, f"禁止覆盖 {ext} 文件（核心基座只读）"

            # 4. 速率限制
            now = time.time()
            if now - self._last_write_ts > self._rate_limit_window:
                self._consecutive_writes = 0
            if self._consecutive_writes >= self._rate_limit_max:
                self._record_audit("write_rate_limited", file_path, "")
                return False, f"写入频率超限（{self._rate_limit_window}s 内最多 {self._rate_limit_max} 次）"
            self._consecutive_writes += 1
            self._last_write_ts = now

            # 5. 内容危险模式检查
            if content:
                forbidden_content_patterns = [
                    re.compile(r"```(?:python|py|sh|bash)"),
                    re.compile(r"\bimport\s+os\b"),
                    re.compile(r"\bsubprocess\."),
                    re.compile(r"\b__import__\s*\("),
                ]
                for pat in forbidden_content_patterns:
                    if pat.search(content):
                        # 允许写入到记忆文件（castorice_data 目录）
                        if "castorice_data" in abs_path or ".castorice" in abs_path:
                            continue
                        self._record_audit("write_blocked", file_path, f"内容含危险模式: {pat.pattern}")
                        return False, f"内容包含危险代码模式: {pat.pattern}"

            # 6. 审计记录
            self._record_audit("write_allowed", file_path, f"size={len(content)}")
            return True, ""

    def check_command_allowed(self, command: str) -> Tuple[bool, str]:
        """
        检查 shell 命令是否允许执行
        """
        with self._lock:
            cmd = command.strip()

            # 1. 黑名单模式
            for pattern in FORBIDDEN_COMMAND_PATTERNS:
                if pattern.search(cmd):
                    self._record_audit("cmd_blocked", "<terminal>", f"危险命令: {cmd[:200]}")
                    return False, f"危险命令已被拦截: {pattern.pattern}"

            # 2. 命令执行速率限制（使用独立计数器，避免与文件写入互相影响）
            now = time.time()
            if now - self._last_cmd_ts > self._rate_limit_window:
                self._consecutive_cmds = 0
            if self._consecutive_cmds >= self._rate_limit_max:
                self._record_audit("cmd_rate_limited", "<terminal>", "")
                return False, f"命令执行频率超限"
            self._consecutive_cmds += 1
            self._last_cmd_ts = now

            self._record_audit("cmd_allowed", "<terminal>", f"cmd={cmd[:200]}")
            return True, ""

    def _record_audit(self, action: str, target: str, detail: str) -> None:
        """记录审计日志（线程安全）"""
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "action": action,
            "target": target,
            "detail": detail[:200],
        }
        self._audit_log.append(entry)
        if len(self._audit_log) > self._max_audit:
            self._audit_log = self._audit_log[-self._max_audit:]
        logger.info(f"[FileGuard] {action} | {target} | {detail[:100]}")

    def get_audit_log(self, last_n: int = 50) -> list:
        """获取最近 N 条审计日志"""
        with self._lock:
            return list(self._audit_log[-last_n:])


# 全局单例
_file_guard: Optional[FileWriteGuard] = None
_file_guard_lock = threading.Lock()


def get_file_guard() -> FileWriteGuard:
    """获取全局文件守卫单例"""
    global _file_guard
    with _file_guard_lock:
        if _file_guard is None:
            _file_guard = FileWriteGuard()
    return _file_guard
