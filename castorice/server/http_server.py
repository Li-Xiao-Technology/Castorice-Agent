"""
HttpServer - HTTP 服务器

对 castorice.adapters.http_server.HTTPServerAdapter 的薄封装，
保持向后兼容的同时消除重复实现。
"""
import logging
import threading

from castorice.adapters.http_server import HTTPServerAdapter


class HttpServer(HTTPServerAdapter):
    """HTTP 服务器（兼容旧接口的薄封装）

    直接继承 HTTPServerAdapter，额外提供：
    - is_running() / get_status_info() 兼容接口
    - 从 engine.config 自动读取配置的 __init__
    """

    def __init__(self, engine):
        http_cfg = engine.config.http_server if hasattr(engine.config, "http_server") else {}
        if not isinstance(http_cfg, dict):
            http_cfg = {}

        host = http_cfg.get("host", "0.0.0.0")
        port = int(http_cfg.get("port", 8000))
        api_keys = http_cfg.get("api_keys", [])
        cors_origins = http_cfg.get("cors_origins", ["*"])
        require_auth = http_cfg.get("require_auth", True)

        super().__init__(
            engine,
            host=host,
            port=port,
            api_keys=api_keys,
            cors_origins=cors_origins,
            require_auth=require_auth,
        )
        self.engine = engine
        self.logger = logging.getLogger("Castorice.HTTP")
        self._host = host
        self._port = port
        self._running = False
        self._ready = False
        self._stop_event = threading.Event()

    def is_running(self) -> bool:
        """检查 HTTP 服务器是否正在运行"""
        return self._running and self._ready

    def get_status_info(self) -> dict:
        """获取状态详情"""
        return {
            "running": self._running,
            "ready": self._ready,
            "error": self.get_error(),
            "host": self._host,
            "port": self._port,
        }

    def run(self) -> None:
        """启动 HTTP 服务器（阻塞模式，由调用方在后台线程中运行）"""
        self._running = True
        self._stop_event.clear()
        try:
            thread = self.start_in_thread()

            import time
            for _ in range(20):
                time.sleep(0.1)
                if not thread.is_alive():
                    adapter_error = self.get_error()
                    if adapter_error:
                        self.logger.error(f"启动 HTTP 服务器失败: {adapter_error}")
                    self._running = False
                    return

            self._ready = True

            self.logger.info("═══════════════════════════════════════")
            self.logger.info("  HTTP 服务器已启动")
            self.logger.info(f"  地址: http://{self._host}:{self._port}")
            self.logger.info(f"  API 文档: http://{self._host}:{self._port}/docs")
            self.logger.info(f"  WebSocket: ws://{self._host}:{self._port}/ws")
            if self.api_keys:
                self.logger.info(f"  API Key 认证: 已启用 ({len(self.api_keys)} 个密钥)")
            else:
                self.logger.info(f"  API Key 认证: 未启用（开放访问）")
            if self.cors_origins:
                self.logger.info(
                    f"  CORS 来源: {', '.join(self.cors_origins) if len(self.cors_origins) <= 3 else str(len(self.cors_origins)) + ' 个'}"
                )
            self.logger.info("═══════════════════════════════════════")

            while self._running and thread and thread.is_alive():
                self._stop_event.wait(1)

            self.logger.info("HTTP 服务器主循环退出")
        except Exception as e:
            self.logger.error(f"启动 HTTP 服务器失败: {e}")
        finally:
            self._running = False
            self._ready = False

    def stop(self) -> bool:
        """停止 HTTP 服务器"""
        self._running = False
        self._stop_event.set()
        try:
            super().stop()
            self.logger.info("HTTP 服务器已停止")
            return True
        except Exception as e:
            self.logger.error(f"停止 HTTP 服务器失败: {e}")
            return False
