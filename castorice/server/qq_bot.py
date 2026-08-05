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

    def get_status(self) -> dict:
        """获取运行时状态（供 HTTP API 调用，含 connected/error 等信息）"""
        status = {
            "running": self._running,
            "ready": self._ready,
            "connected": False,
            "error": self._error,
        }
        if self._bot and hasattr(self._bot, 'get_status'):
            try:
                bot_status = self._bot.get_status()
                if isinstance(bot_status, dict):
                    status.update(bot_status)
            except Exception:
                pass
        return status

    def run(self) -> None:
        """启动 QQ 机器人（阻塞模式，由调用方在后台线程中运行）"""
        self._running = True
        try:
            from castorice.adapters.qq_bot import QQBotConfig, QQBotAdapter

            qq_cfg = self.engine.config.qq_bot if hasattr(self.engine.config, "qq_bot") else {}
            if not isinstance(qq_cfg, dict):
                qq_cfg = {}

            app_id = str(qq_cfg.get("app_id", ""))
            app_secret = str(qq_cfg.get("app_secret", ""))
            sandbox = bool(qq_cfg.get("sandbox", True))
            allowed_users = list(qq_cfg.get("allowed_users", []) or [])
            allowed_groups = list(qq_cfg.get("allowed_groups", []) or [])

            if not app_id or not app_secret:
                self._error = "配置缺失（app_id / app_secret 未设置）"
                self.logger.error(f"QQ 机器人启动失败: {self._error}")
                self._running = False
                return

            # 构建 intent 降级候选列表（从高到低，优先组合型，确保能收到消息）
            intent_raw = qq_cfg.get("intent", "basic")
            if isinstance(intent_raw, str):
                intent_map = {
                    "basic": QQBotConfig.INTENT_BASIC,
                    "with_c2c": QQBotConfig.INTENT_WITH_C2C,
                    "all": QQBotConfig.INTENT_ALL,
                }
                primary_intent = intent_map.get(intent_raw.lower(), QQBotConfig.INTENT_BASIC)
            else:
                primary_intent = intent_raw

            I_AT = QQBotConfig.INTENT_AT_MESSAGE
            I_DM = QQBotConfig.INTENT_DIRECT_MESSAGE
            I_C2C = QQBotConfig.INTENT_C2C_MESSAGE
            I_GROUP = QQBotConfig.INTENT_GROUP_MESSAGE
            I_GUILD = QQBotConfig.INTENT_GUILD

            intent_candidates = []
            for candidate in [
                primary_intent,
                QQBotConfig.INTENT_ALL,                        # 全部
                QQBotConfig.INTENT_WITH_C2C,                   # AT + DM + C2C
                QQBotConfig.INTENT_BASIC,                       # AT + DM
                I_DM | I_C2C | I_GROUP,                         # 私信三件套（频道私信 + C2C + 群）
                I_DM | I_C2C,                                    # 双私信（频道私信 + C2C 好友私聊）
                I_DM | I_GROUP,                                  # 频道私信 + 群消息
                I_C2C | I_GROUP,                                 # C2C + 群消息
                I_AT | I_C2C,                                    # @消息 + C2C
                I_AT | I_DM | I_C2C,                             # AT + DM + C2C
                I_AT | I_DM | I_GROUP,                           # AT + DM + GROUP
                I_DM,                                             # 频道私信
                I_C2C,                                            # C2C 好友私聊（沙箱可用！）
                I_GROUP,                                          # 群消息（正式可用！）
                I_AT,                                             # 频道@消息
                I_AT | I_GUILD,                                   # 频道基础 + @消息
                I_GUILD,                                          # 仅频道事件（无消息）
                0,
            ]:
                if candidate not in intent_candidates:
                    intent_candidates.append(candidate)

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

            import time
            connected = False
            for idx, intent in enumerate(intent_candidates):
                if not self._running:
                    return
                if idx > 0:
                    self.logger.warning(f"Intent 降级尝试 ({idx}/{len(intent_candidates)}): 使用 intent={intent}")

                config = QQBotConfig(
                    app_id=app_id,
                    app_secret=app_secret,
                    sandbox=sandbox,
                    intent=intent,
                    allowed_users=allowed_users,
                    allowed_groups=allowed_groups,
                )
                self._bot = QQBotAdapter(config)
                self._bot.on_message(message_handler)
                self._bot_thread = self._bot.start_in_thread()

                # 等待最多 10 秒看是否连接且鉴权成功
                success = True
                for _ in range(100):
                    time.sleep(0.1)
                    if not self._bot_thread.is_alive():
                        success = False
                        break
                    st = self._bot.get_status()
                    if st.get("authenticated"):
                        success = True
                        break

                if success and self._bot_thread.is_alive():
                    connected = True
                    break
                else:
                    # 清理当前 bot，准备下一次尝试
                    try:
                        asyncio.run(self._bot.stop())
                    except Exception:
                        pass
                    self._bot = None
                    self._bot_thread = None

            if not connected:
                self._error = "所有 intent 配置均连接失败，请检查 QQ 开放平台权限配置"
                self.logger.error(f"QQ 机器人启动失败: {self._error}")
                self._running = False
                return

            self._ready = True
            self.logger.info("═══════════════════════════════════════")
            self.logger.info("  QQ 机器人已启动")
            self.logger.info(f"  模式: {'沙箱' if sandbox else '正式'}")
            self.logger.info(f"  App ID: {app_id[:8]}...{app_id[-4:] if len(app_id) > 12 else ''}")
            self.logger.info(f"  当前 Intent: {self._bot.config.intent if self._bot else 'N/A'}")
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