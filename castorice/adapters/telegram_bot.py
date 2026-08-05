"""
Telegram Bot 适配器 (TelegramBotAdapter)

基于 Telegram Bot API (httpx 直连) 实现的轻量适配器，
不依赖 python-telegram-bot 等第三方库。

功能特性：
- Long Polling 接收消息
- 支持私聊 / 群组 / 超级群组
- 支持 Markdown 和 HTML 格式
- 自动重试 + 指数退避
- 消息去重缓存
"""

import asyncio
import json
import logging
import threading
import time
from typing import Any, Callable, Dict, List, Optional

import httpx

logger = logging.getLogger("Castorice.TelegramBot")


class TelegramBotConfig:
    """Telegram Bot 配置"""

    def __init__(
        self,
        bot_token: str,
        allowed_chat_ids: Optional[List[int]] = None,
        allowed_usernames: Optional[List[str]] = None,
        polling_interval: float = 1.0,
        parse_mode: str = "Markdown",
    ):
        self.bot_token = bot_token
        self.allowed_chat_ids = allowed_chat_ids
        self.allowed_usernames = allowed_usernames
        self.polling_interval = polling_interval
        self.parse_mode = parse_mode

    @property
    def api_base_url(self) -> str:
        return f"https://api.telegram.org/bot{self.bot_token}"


class TelegramBotAdapter:
    """
    Telegram Bot 适配器

    使用示例：
    >>> config = TelegramBotConfig(bot_token="123456:ABC-DEF")
    >>> bot = TelegramBotAdapter(config, engine=castorice_engine)
    >>> bot.start_in_thread()
    """

    MAX_MESSAGE_LENGTH = 4096

    def __init__(self, config: TelegramBotConfig, engine: Any = None):
        self.config = config
        self.engine = engine
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._last_update_id = 0
        self._client = httpx.AsyncClient(timeout=30.0)
        self._sync_client = httpx.Client(timeout=30.0)
        self._processed_ids: set = set()
        self._max_processed = 1000

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------
    def start_in_thread(self) -> None:
        """后台线程启动"""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run_polling, daemon=True, name="TelegramBot")
        self._thread.start()
        logger.info("Telegram Bot 已启动（后台线程）")

    def stop(self) -> None:
        self._running = False
        try:
            self._sync_client.close()
        except Exception:
            pass
        logger.info("Telegram Bot 已停止")

    def _run_polling(self) -> None:
        """主轮询循环（线程入口）"""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._polling_loop())
        except Exception as e:
            logger.error(f"Telegram Bot 轮询异常: {e}")
        finally:
            loop.close()

    async def _polling_loop(self) -> None:
        backoff = 1.0
        while self._running:
            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    while self._running:
                        resp = await client.get(
                            f"{self.config.api_base_url}/getUpdates",
                            params={
                                "offset": self._last_update_id + 1,
                                "timeout": 20,
                                "allowed_updates": json.dumps(["message"]),
                            },
                        )
                        if resp.status_code != 200:
                            logger.warning(f"Telegram getUpdates 状态码: {resp.status_code}")
                            await asyncio.sleep(backoff)
                            backoff = min(backoff * 2, 30)
                            continue

                        data = resp.json()
                        backoff = 1.0

                        if not data.get("ok"):
                            logger.warning(f"Telegram API 错误: {data}")
                            await asyncio.sleep(1)
                            continue

                        for update in data.get("result", []):
                            self._last_update_id = max(self._last_update_id, update["update_id"])
                            await self._handle_update(update)

                        await asyncio.sleep(self.config.polling_interval)
            except Exception as e:
                logger.error(f"Telegram 轮询断开，{backoff:.0f}s 后重连: {e}")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30)

    # ------------------------------------------------------------------
    # 消息处理
    # ------------------------------------------------------------------
    async def _handle_update(self, update: Dict[str, Any]) -> None:
        message = update.get("message")
        if not message:
            return

        msg_id = message.get("message_id")
        if msg_id and msg_id in self._processed_ids:
            return
        self._processed_ids.add(msg_id)
        if len(self._processed_ids) > self._max_processed:
            # 清理老的
            to_remove = sorted(self._processed_ids)[: self._max_processed // 2]
            for i in to_remove:
                self._processed_ids.discard(i)

        chat = message.get("chat", {})
        chat_id = chat.get("id")
        chat_type = chat.get("type", "private")

        # 权限校验
        if not self._is_allowed(chat, message.get("from", {})):
            logger.debug(f"拒绝未授权消息: chat_id={chat_id}")
            return

        text = message.get("text", "")
        if not text:
            return

        # 构造 Castorice session_id（每个 chat 一个独立会话）
        session_id = f"telegram_{chat_id}"

        try:
            if self.engine and hasattr(self.engine, "chat"):
                reply = self.engine.chat(text, session_id=session_id)
            else:
                reply = f"收到: {text[:50]}"
        except Exception as e:
            logger.error(f"处理 Telegram 消息失败: {e}")
            reply = "抱歉，处理失败了，请稍后再试。"

        await self._send_message(chat_id, reply)

    def _is_allowed(self, chat: Dict[str, Any], sender: Dict[str, Any]) -> bool:
        chat_id = chat.get("id")
        username = sender.get("username")

        # 如果没有任何白名单，放行所有私聊
        if not self.config.allowed_chat_ids and not self.config.allowed_usernames:
            return chat.get("type") == "private"

        if self.config.allowed_chat_ids and chat_id in self.config.allowed_chat_ids:
            return True
        if self.config.allowed_usernames and username and username in self.config.allowed_usernames:
            return True
        return False

    # ------------------------------------------------------------------
    # 发送
    # ------------------------------------------------------------------
    async def _send_message(self, chat_id: int, text: str) -> None:
        if not text:
            return
        # 超长分片
        chunks = []
        remaining = text
        while len(remaining) > self.MAX_MESSAGE_LENGTH:
            split_at = remaining[: self.MAX_MESSAGE_LENGTH].rfind("\n")
            if split_at == -1:
                split_at = self.MAX_MESSAGE_LENGTH
            chunks.append(remaining[:split_at])
            remaining = remaining[split_at:].lstrip()
        chunks.append(remaining)

        async with httpx.AsyncClient(timeout=30.0) as client:
            for chunk in chunks:
                try:
                    await client.post(
                        f"{self.config.api_base_url}/sendMessage",
                        json={
                            "chat_id": chat_id,
                            "text": chunk,
                            "parse_mode": self.config.parse_mode,
                            "disable_web_page_preview": True,
                        },
                    )
                except Exception as e:
                    logger.error(f"Telegram 发送消息失败: {e}")
                    # 格式可能不兼容，退化成纯文本
                    try:
                        await client.post(
                            f"{self.config.api_base_url}/sendMessage",
                            json={"chat_id": chat_id, "text": chunk},
                        )
                    except Exception as e2:
                        logger.error(f"Telegram 纯文本发送也失败: {e2}")

    # ------------------------------------------------------------------
    # 工具：获取 bot 信息
    # ------------------------------------------------------------------
    def get_me(self) -> Optional[Dict[str, Any]]:
        try:
            resp = self._sync_client.get(f"{self.config.api_base_url}/getMe")
            if resp.status_code == 200:
                data = resp.json()
                if data.get("ok"):
                    return data["result"]
        except Exception as e:
            logger.error(f"获取 Telegram Bot 信息失败: {e}")
        return None
