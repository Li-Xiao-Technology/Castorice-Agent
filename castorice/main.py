"""
Castorice Agent - 主程序入口

启动方式：
  1. python -m castorice.main
  2. castorice (安装后)
  3. 双击 start.bat (Windows)
"""
import warnings
warnings.filterwarnings(
    "ignore",
    message="The Transformer `cache_dir` argument is deprecated",
    category=UserWarning,
    module="sentence_transformers"
)

import argparse
import logging
import os
from typing import Optional, Dict, Any


class JsonLogFormatter(logging.Formatter):
    """JSON 格式日志格式化器"""

    def format(self, record):
        import json
        log_entry = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "line": record.lineno,
        }
        if record.exc_info:
            log_entry["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(log_entry, ensure_ascii=False)


def setup_logging(config: Optional[Dict[str, Any]] = None) -> None:
    """配置根日志器（支持文本/JSON 格式）"""
    os.makedirs("./castorice_data", exist_ok=True)

    log_cfg = config.get("logging", {}) if isinstance(config, dict) else {}
    level = log_cfg.get("level", "INFO").upper()
    log_format = log_cfg.get("format", "text").lower()
    log_dir = log_cfg.get("log_dir", "./castorice_data")
    max_size_mb = log_cfg.get("max_size_mb", 10)
    backup_count = log_cfg.get("backup_count", 5)

    os.makedirs(log_dir, exist_ok=True)
    file_path = os.path.join(log_dir, "castorice.log")

    handlers = []

    console_handler = logging.StreamHandler()
    if log_format == "json":
        console_handler.setFormatter(JsonLogFormatter(datefmt="%Y-%m-%d %H:%M:%S"))
    else:
        console_handler.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        ))
    handlers.append(console_handler)

    try:
        from logging.handlers import RotatingFileHandler
        file_handler = RotatingFileHandler(
            file_path,
            maxBytes=max_size_mb * 1024 * 1024,
            backupCount=backup_count,
            encoding="utf-8",
        )
        if log_format == "json":
            file_handler.setFormatter(JsonLogFormatter(datefmt="%Y-%m-%d %H:%M:%S"))
        else:
            file_handler.setFormatter(logging.Formatter(
                "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S"
            ))
        handlers.append(file_handler)
    except ImportError:
        file_handler = logging.FileHandler(file_path, encoding="utf-8")
        handlers.append(file_handler)

    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        handlers=handlers,
    )


def main():
    """主入口函数"""
    parser = argparse.ArgumentParser(description="Castorice Agent - 自进化智能体")
    parser.add_argument("--mode", type=str, default="interactive",
                        choices=["test", "interactive", "http", "qq", "batch", "cron"],
                        help="运行模式")
    parser.add_argument("--input", type=str, default=None,
                        help="批量模式的输入文件路径")
    args = parser.parse_args()

    from castorice.server import CastoriceEngine

    engine = CastoriceEngine()

    if args.mode == "test":
        engine.test()
    elif args.mode == "interactive":
        engine.run_interactive()
    elif args.mode == "http":
        engine.run_http_server()
        import time
        while True:
            time.sleep(1)
    elif args.mode == "qq":
        engine.run_qq_bot()
        import time
        while True:
            time.sleep(1)
    elif args.mode == "batch":
        if args.input:
            from castorice.server import CLIHandler
            CLIHandler(engine).run_batch(args.input)
        else:
            print("批量模式需要指定 --input 参数")
    elif args.mode == "cron":
        engine.run_cron()
        import time
        while True:
            time.sleep(1)


if __name__ == "__main__":
    main()