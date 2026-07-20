import glob
import json
import logging
import os
import re
import threading
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler

logger = logging.getLogger("Castorice.AuditLog")

_audit_logger = None
_audit_lock = threading.Lock()


def get_audit_logger(log_dir=None):
    """获取审计日志单例（P0-8: 双重检查锁保证线程安全）"""
    global _audit_logger
    if _audit_logger is None:
        with _audit_lock:
            if _audit_logger is None:
                if log_dir is None:
                    log_dir = "./castorice_data/audit_logs"
                _audit_logger = AuditLogger(log_dir)
    return _audit_logger


# P0-7: 敏感字段名（用于脱敏匹配）
_SENSITIVE_KEY_PATTERNS = re.compile(
    r"(api[_-]?key|password|passwd|token|secret|credential|smtp[_-]?password|webhook[_-]?url|auth[_-]?header)",
    re.IGNORECASE,
)
_MASKED_VALUE = "***REDACTED***"


def _redact_sensitive(obj):
    """递归脱敏字典/字符串中的敏感字段（P0-7）"""
    if isinstance(obj, dict):
        return {
            k: (_MASKED_VALUE if _SENSITIVE_KEY_PATTERNS.search(str(k)) else _redact_sensitive(v))
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [_redact_sensitive(item) for item in obj]
    if isinstance(obj, str) and len(obj) > 200:
        # 长字符串截断（避免日志爆炸）
        return obj[:200] + "...[truncated]"
    return obj


class AuditLogger:
    """审计日志记录器（P0-7: 敏感字段脱敏 / P2-5: 按天清理 / P2-6: 大小轮转）"""

    # P2-6: 单文件最大 50MB，保留 30 个文件
    _MAX_FILE_BYTES = 50 * 1024 * 1024
    _MAX_FILES = 30

    def __init__(self, log_dir: str, max_files: int = 30):
        self.log_dir = log_dir
        self.max_files = max_files
        os.makedirs(self.log_dir, exist_ok=True)
        # P2-5: 记录上次清理日期，避免每次写日志都 glob
        self._last_cleanup_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        self._write_lock = threading.Lock()
        self._cleanup_old_files()

    def _get_current_log_file(self) -> str:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return os.path.join(self.log_dir, f"audit_{today}.log")

    def _cleanup_old_files(self):
        """清理过期的日志文件，保留最近 max_files 个"""
        pattern = os.path.join(self.log_dir, "audit_*.log")
        files = sorted(glob.glob(pattern))
        if len(files) > self.max_files:
            files_to_delete = files[:len(files) - self.max_files]
            for file_path in files_to_delete:
                try:
                    os.remove(file_path)
                except OSError as e:
                    logger.warning(f"清理旧审计日志失败 {file_path}: {e}")

    def _maybe_cleanup(self):
        """P2-5: 按天触发一次清理，避免每次写日志都 glob"""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if today != self._last_cleanup_date:
            self._last_cleanup_date = today
            self._cleanup_old_files()

    def _write_log(self, event_type: str, user_id: str, session_id: str,
                   details: dict, risk_level: str):
        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event_type": event_type,
            "user_id": user_id,
            "session_id": session_id,
            # P0-7: 写入前脱敏
            "details": _redact_sensitive(details),
            "risk_level": risk_level,
        }
        log_file = self._get_current_log_file()
        with self._write_lock:
            # P2-6: 检查文件大小，超过阈值则轮转
            try:
                if os.path.exists(log_file) and os.path.getsize(log_file) > self._MAX_FILE_BYTES:
                    # 轮转：重命名为带时间戳的归档文件
                    archive_name = log_file.replace(".log", f"_archived_{int(datetime.now(timezone.utc).timestamp())}.log")
                    try:
                        os.rename(log_file, archive_name)
                    except OSError:
                        pass
            except OSError:
                pass
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")
        self._maybe_cleanup()

    def log_tool_call(self, user_id: str, session_id: str, tool_name: str,
                      args: dict, result: str, risk_level: str = "low"):
        details = {
            "tool_name": tool_name,
            "args": args,
            "result": result,
        }
        self._write_log("tool_call", user_id, session_id, details, risk_level)

    def log_security_event(self, user_id: str, session_id: str, event_type: str,
                           details: dict, risk_level: str = "high"):
        self._write_log(event_type, user_id, session_id, details, risk_level)

    def get_recent_logs(self, limit: int = 100) -> list:
        logs = []
        pattern = os.path.join(self.log_dir, "audit_*.log")
        files = sorted(glob.glob(pattern), reverse=True)

        for file_path in files:
            try:
                # P2-6: 逐行读取避免大文件 OOM
                with open(file_path, "r", encoding="utf-8") as f:
                    # 先读末尾部分（最新的在末尾）
                    lines = f.readlines()
            except OSError as e:
                logger.warning(f"读取审计日志失败 {file_path}: {e}")
                continue
            for line in reversed(lines):
                line = line.strip()
                if not line:
                    continue
                try:
                    log_entry = json.loads(line)
                    logs.append(log_entry)
                    if len(logs) >= limit:
                        return logs
                except json.JSONDecodeError:
                    continue
            if len(logs) >= limit:
                break

        return logs
