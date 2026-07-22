"""
QQBot - QQ 机器人

处理 QQ 消息接收和回复。
"""
import logging
import asyncio
import time


class QQBot:
    """QQ 机器人"""

    def __init__(self, engine):
        self.engine = engine
        self.logger = logging.getLogger("Castorice.QQBot")
        self._bot = None
        self._bot_thread = None
        self._running = False
        self._ready = False
        self._error = None

    def is_running(self) -> bool:
        """检查 QQ 机器人是否正在运行"""
        return self._running and self._ready

    def get_status_info(self) -> dict:
        """获取状态详情"""
        return {
            "running": self._running,
            "ready": self._ready,
            "error": self._error,
        }

    def run(self) -> None:
        """启动 QQ 机器人（阻塞模式，由调用方在后台线程中运行）"""
        self._running = True
        try:
            from castorice.adapters.qq_bot import QQBotConfig, QQBotAdapter

            qq_cfg = self.engine.config.qq_bot if hasattr(self.engine.config, "qq_bot") else {}
            if not isinstance(qq_cfg, dict):
                qq_cfg = {}

            app_id = qq_cfg.get("app_id", "")
            app_secret = qq_cfg.get("app_secret", "")
            sandbox = qq_cfg.get("sandbox", True)
            intent = qq_cfg.get("intent_value")

            if not app_id or not app_secret:
                self._error = "配置缺失（app_id / app_secret 未设置）"
                self.logger.error(f"QQ 机器人启动失败: {self._error}")
                self._running = False
                return

            config = QQBotConfig(app_id=app_id, app_secret=app_secret, sandbox=sandbox, intent=intent)
            self._bot = QQBotAdapter(config)

            def message_handler(content: str, context: dict) -> str:
                try:
                    self.logger.info(f"[QQ] 收到消息: {content[:100]} | 用户: {context.get('user_id')}")
                    user_id = context.get("user_id", "qq_user")
                    session_id = f"qq_{user_id}"
                    state = self.engine.agent.run(content, session_id=session_id)
                    reply = state.final_answer
                    if not reply:
                        reply = "抱歉，我没有生成有效的回复"
                    reply_prefix = qq_cfg.get("reply_prefix", "")
                    if reply_prefix:
                        reply = f"{reply_prefix}\n{reply}"
                    return reply
                except Exception as e:
                    self.logger.error(f"QQ 消息处理失败: {e}")
                    return "抱歉，处理消息时出错了"

            self._bot.on_message(message_handler)
            self._bot_thread = self._bot.start_in_thread()

            import time
            for _ in range(30):
                time.sleep(0.1)
                if not self._bot_thread.is_alive():
                    self._error = "启动失败，线程已退出"
                    self.logger.error(f"QQ 机器人启动失败: {self._error}")
                    self._running = False
                    return

            self._ready = True
            self.logger.info("═══════════════════════════════════════")
            self.logger.info("  QQ 机器人已启动")
            self.logger.info(f"  模式: {'沙箱' if sandbox else '正式'}")
            self.logger.info(f"  App ID: {app_id[:8]}...{app_id[-4:] if len(app_id) > 12 else ''}")
            self.logger.info("═══════════════════════════════════════")

            while self._running and self._bot_thread and self._bot_thread.is_alive():
                time.sleep(1)

            self.logger.info("QQ 机器人主循环退出")
        except Exception as e:
            self._error = str(e)
            self.logger.error(f"启动 QQ 机器人失败: {e}")
        finally:
            self._running = False
            self._ready = False

    def stop(self) -> bool:
        """停止 QQ 机器人"""
        self._running = False
        if self._bot:
            try:
                asyncio.run(self._bot.stop())
                self._bot = None
                self._bot_thread = None
                self.logger.info("QQ 机器人已停止")
                return True
            except Exception as e:
                self.logger.error(f"停止 QQ 机器人失败: {e}")
                return False
        return False