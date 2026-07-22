"""
HttpServer - HTTP 服务器

提供 REST API 接口。
"""
import logging
import time


class HttpServer:
    """HTTP 服务器"""

    def __init__(self, engine):
        self.engine = engine
        self.logger = logging.getLogger("Castorice.HTTP")
        self._server = None
        self._server_thread = None
        self._running = False
        self._ready = False
        self._error = None
        self._host = ""
        self._port = 0

    def is_running(self) -> bool:
        """检查 HTTP 服务器是否正在运行"""
        return self._running and self._ready

    def get_status_info(self) -> dict:
        """获取状态详情"""
        return {
            "running": self._running,
            "ready": self._ready,
            "error": self._error,
            "host": self._host,
            "port": self._port,
        }

    def run(self) -> None:
        """启动 HTTP 服务器（阻塞模式，由调用方在后台线程中运行）"""
        self._running = True
        try:
            from castorice.adapters.http_server import HTTPServerAdapter

            http_cfg = self.engine.config.http_server if hasattr(self.engine.config, "http_server") else {}
            if not isinstance(http_cfg, dict):
                http_cfg = {}

            self._host = http_cfg.get("host", "0.0.0.0")
            self._port = http_cfg.get("port", 8000)
            api_keys = http_cfg.get("api_keys", [])
            cors_origins = http_cfg.get("cors_origins", ["*"])

            try:
                self._server = HTTPServerAdapter(self.engine, host=self._host, port=self._port)
            except ImportError as e:
                self._error = f"依赖缺失: {e}"
                self.logger.error(f"启动 HTTP 服务器失败 - {self._error}")
                self._running = False
                return
            except Exception as e:
                self._error = str(e)
                self.logger.error(f"启动 HTTP 服务器失败: {e}")
                self._running = False
                return

            self._server_thread = self._server.start_in_thread()

            import time
            for _ in range(20):
                time.sleep(0.1)
                if not self._server_thread.is_alive():
                    adapter_error = self._server.get_error() if hasattr(self._server, 'get_error') else None
                    if adapter_error:
                        self._error = adapter_error
                    else:
                        self._error = "启动失败，线程已退出"
                    self.logger.error(f"启动 HTTP 服务器失败: {self._error}")
                    self._running = False
                    return

            self._ready = True

            self.logger.info("═══════════════════════════════════════")
            self.logger.info("  HTTP 服务器已启动")
            self.logger.info(f"  地址: http://{self._host}:{self._port}")
            self.logger.info(f"  API 文档: http://{self._host}:{self._port}/docs")
            self.logger.info(f"  WebSocket: ws://{self._host}:{self._port}/ws")
            if api_keys:
                self.logger.info(f"  API Key 认证: 已启用 ({len(api_keys)} 个密钥)")
            else:
                self.logger.info(f"  API Key 认证: 未启用（开放访问）")
            if cors_origins:
                self.logger.info(f"  CORS 来源: {', '.join(cors_origins) if len(cors_origins) <= 3 else str(len(cors_origins)) + ' 个'}")
            self.logger.info("═══════════════════════════════════════")

            while self._running and self._server_thread and self._server_thread.is_alive():
                time.sleep(1)

            self.logger.info("HTTP 服务器主循环退出")
        except ImportError as e:
            self._error = str(e)
            self.logger.error(f"启动 HTTP 服务器失败: {e}")
        except Exception as e:
            self._error = str(e)
            self.logger.error(f"启动 HTTP 服务器失败: {e}")
        finally:
            self._running = False
            self._ready = False

    def stop(self) -> bool:
        """停止 HTTP 服务器"""
        self._running = False
        if self._server:
            try:
                self._server.stop()
                self._server = None
                self._server_thread = None
                self.logger.info("HTTP 服务器已停止")
                return True
            except Exception as e:
                self.logger.error(f"停止 HTTP 服务器失败: {e}")
                return False
        return False