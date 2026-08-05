"""
Castorice Agent - 统一日志管理

提供：
- 日志轮转（按大小切割）
- 彩色控制台输出
- 异常追踪
- 统一格式
"""

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional


# 日志格式
DEFAULT_FORMAT = (
    "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
    "<level>{level: <8}</level> | "
    "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
    "<level>{message}</level>"
)

FILE_FORMAT = "{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}"


_initialized = False


def _apply_httpx_filter() -> None:
    import re

    _status_extract = re.compile(r'"HTTP/\d+\.\d+"?\s+(\d{3})')

    class _HttpxFilter(logging.Filter):
        def filter(self, record):
            if record.name != "httpx":
                return True
            msg = record.getMessage()
            m = _status_extract.search(msg)
            if m:
                status = int(m.group(1))
                if 200 <= status < 300:
                    return False
            return True

    httpx_logger = logging.getLogger("httpx")
    httpx_logger.addFilter(_HttpxFilter())


def setup_logging(
    level: str = "INFO",
    log_file: Optional[str] = None,
    max_bytes: int = 10 * 1024 * 1024,  # 10MB
    backup_count: int = 5,
    use_color: bool = True,
) -> None:
    """
    配置全局日志

    参数：
        level: 日志级别 (DEBUG/INFO/WARNING/ERROR)
        log_file: 日志文件路径（None 则不写文件）
        max_bytes: 单个日志文件最大字节数
        backup_count: 保留的历史日志文件数
        use_color: 是否使用彩色输出（建议仅控制台）
    """
    global _initialized
    if _initialized and not log_file:
        return

    # 尝试使用 loguru，未安装则回退到标准 logging
    try:
        from loguru import logger as _loguru_logger

        # 移除默认 handler
        _loguru_logger.remove()

        # 控制台 handler
        _loguru_logger.add(
            sys.stderr,
            format=DEFAULT_FORMAT if use_color else FILE_FORMAT,
            level=level,
            colorize=use_color,
            backtrace=True,
            diagnose=False,
        )

        # 文件 handler
        if log_file:
            log_path = Path(log_file)
            log_path.parent.mkdir(parents=True, exist_ok=True)
            _loguru_logger.add(
                str(log_path),
                format=FILE_FORMAT,
                level=level,
                rotation=max_bytes,
                retention=backup_count,
                encoding="utf-8",
                backtrace=True,
                diagnose=False,
            )

        # 提供一个桥接函数，让标准 logging 也能输出到 loguru
        class _InterceptHandler(logging.Handler):
            def emit(self, record):
                try:
                    level = _loguru_logger.level(record.levelname).name
                except ValueError:
                    level = record.levelno
                frame, depth = logging.currentframe(), 2
                while frame.f_code.co_filename == logging.__file__:
                    frame = frame.f_back
                    depth += 1
                _loguru_logger.opt(depth=depth, exception=record.exc_info).log(
                    level, record.getMessage()
                )

        logging.basicConfig(handlers=[_InterceptHandler()], level=0, force=True)

        _apply_httpx_filter()

        _initialized = True
        return

    except ImportError:
        pass

    # 回退到标准 logging
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    # 清除已有 handler
    for h in list(root.handlers):
        root.removeHandler(h)

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s:%(funcName)s:%(lineno)d - %(message)s"
    )

    # 控制台
    console = logging.StreamHandler(sys.stderr)
    console.setFormatter(formatter)
    root.addHandler(console)

    # 文件（带轮转）
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            str(log_path),
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)

    _apply_httpx_filter()

    _initialized = True


def get_logger(name: str) -> logging.Logger:
    """获取 logger（统一入口）

    若调用方未先调用 ``setup_logging``，则自动以默认配置初始化一次，
    保证通过本函数获取的 logger 总是具备统一格式与 handler。
    """
    if not _initialized:
        setup_logging()
    return logging.getLogger(name)