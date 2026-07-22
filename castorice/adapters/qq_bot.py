"""
QQ 机器人适配器 (QQBotAdapter)

基于 QQ 开放平台 API 实现的 QQ 频道/群机器人适配器，
支持使用 AppID + AppSecret 接入 QQ 机器人。

功能特性：
- 支持 QQ 频道消息接收与回复
- 支持 C2C 私聊消息
- 支持群聊消息（需群机器人权限）
- 自动鉴权与 token 刷新
- WebSocket 长连接 + 事件回调
- 自动重连机制
- 消息去重缓存
"""

import asyncio
import base64
import json
import logging
import threading
import time
from collections import OrderedDict
from typing import Any, Callable, Dict, List, Optional, Set

try:
    import websockets
except ImportError:
    websockets = None

import httpx

logger = logging.getLogger("Castorice.QQBot")

# P1-5: 模块级单调递增的消息序号计数器（线程安全）
# 解决 msg_id 毫秒时间戳同毫秒冲突 + msg_seq 跨调用不递增导致 QQ API 去重的问题
_msg_seq_counter = 0
_msg_seq_counter_lock = threading.Lock()


def _next_msg_seq() -> int:
    """获取下一个单调递增的 msg_seq（线程安全）"""
    global _msg_seq_counter
    with _msg_seq_counter_lock:
        _msg_seq_counter += 1
        return _msg_seq_counter


def _gen_msg_id() -> str:
    """生成唯一 msg_id（毫秒时间戳 + 序号，避免同毫秒冲突）"""
    return f"{int(time.time() * 1000)}_{_next_msg_seq()}"


class QQBotConfig:
    """QQ 机器人配置"""

    # QQ 开放平台 Intent 常量
    INTENT_GUILD = 1 << 0              # 频道相关
    INTENT_GUILD_MEMBERS = 1 << 1      # 频道成员
    INTENT_AT_MESSAGE = 1 << 9         # 频道 @消息
    INTENT_DIRECT_MESSAGE = 1 << 10    # 频道私信
    INTENT_GROUP_MESSAGE = 1 << 12     # 群消息
    INTENT_C2C_MESSAGE = 1 << 25       # C2C 消息

    # 预设 Intent 组合
    INTENT_BASIC = INTENT_AT_MESSAGE | INTENT_DIRECT_MESSAGE           # 1536
    INTENT_WITH_C2C = INTENT_AT_MESSAGE | INTENT_DIRECT_MESSAGE | INTENT_C2C_MESSAGE
    INTENT_ALL = INTENT_GUILD | INTENT_GUILD_MEMBERS | INTENT_AT_MESSAGE | INTENT_DIRECT_MESSAGE | INTENT_GROUP_MESSAGE | INTENT_C2C_MESSAGE

    def __init__(
        self,
        app_id: str,
        app_secret: str,
        sandbox: bool = False,
        intent: int = None,
        allowed_users: List[str] = None,
        allowed_groups: List[str] = None,
    ):
        self.app_id = app_id
        self.app_secret = app_secret
        self.sandbox = sandbox
        # 默认订阅频道@消息 + 频道私信 + C2C私聊（需要在开放平台申请权限）
        self.intent = intent if intent is not None else self.INTENT_WITH_C2C
        self.allowed_users = allowed_users
        self.allowed_groups = allowed_groups

    @property
    def api_base_url(self) -> str:
        """API 基础地址"""
        if self.sandbox:
            return "https://sandbox.api.sgroup.qq.com"
        return "https://api.sgroup.qq.com"


class QQBotAdapter:
    """
    QQ 机器人适配器

    使用示例：
    >>> config = QQBotConfig(app_id="xxx", app_secret="xxx")
    >>> bot = QQBotAdapter(config)
    >>> bot.on_message = lambda content: f"收到: {content}"
    >>> bot.run()
    """

    # 消息长度限制（QQ API 限制）
    MAX_MESSAGE_LENGTH = 2000

    def __init__(self, config: QQBotConfig):
        self.config = config
        self._access_token: Optional[str] = None
        self._token_expires_at: float = 0
        self._ws = None
        self._running = False
        self._session_id: Optional[str] = None
        self._seq: int = 0
        self._heartbeat_interval: float = 30
        self._message_handler: Optional[Callable[[str, Dict[str, Any]], str]] = None
        self._reconnect_delay: float = 5.0

        # 消息去重缓存（LRU 淘汰，保留最近 1000 条消息 ID）
        self._processed_messages: OrderedDict = OrderedDict()
        self._max_cache_size = 1000

        self._http_client = httpx.AsyncClient(
            base_url=config.api_base_url,
            timeout=30,
        )

    def get_status(self) -> Dict[str, Any]:
        """获取机器人状态"""
        return {
            "running": self._running,
            "connected": self._is_ws_open(),
            "session_id": self._session_id,
            "seq": self._seq,
            "intent": self.config.intent,
            "sandbox": self.config.sandbox,
            "reconnect_delay": self._reconnect_delay,
            "processed_messages": len(self._processed_messages),
        }

    def _truncate_message(self, content: str) -> str:
        """截断消息长度，适配 QQ API 限制"""
        if len(content) > self.MAX_MESSAGE_LENGTH:
            truncated = content[:self.MAX_MESSAGE_LENGTH - 3] + "..."
            logger.warning(f"消息过长，已截断: {len(content)} -> {len(truncated)} 字符")
            return truncated
        return content

    def _add_message_cache(self, message_id: str) -> None:
        """添加消息到去重缓存（LRU 淘汰）"""
        if message_id in self._processed_messages:
            del self._processed_messages[message_id]
        if len(self._processed_messages) >= self._max_cache_size:
            self._processed_messages.popitem(last=False)
        self._processed_messages[message_id] = None

    def _is_message_processed(self, message_id: str) -> bool:
        """检查消息是否已处理"""
        return message_id in self._processed_messages

    # ============================================================
    # 鉴权相关
    # ============================================================
    async def _get_access_token(self) -> str:
        """获取 access_token（带缓存）"""
        if self._access_token and time.time() < self._token_expires_at - 300:
            return self._access_token

        if self._http_client is None:
            # 降级路径下创建新客户端也要带上 base_url，避免后续 /gateway 等相对路径请求失败
            self._http_client = httpx.AsyncClient(
                base_url=self.config.api_base_url,
                timeout=30,
            )

        try:
            resp = await self._http_client.post(
                "https://bots.qq.com/app/getAppAccessToken",
                json={
                    "appId": self.config.app_id,
                    "clientSecret": self.config.app_secret,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            self._access_token = data.get("access_token", "")
            expires_in = int(data.get("expires_in", 7200))
            self._token_expires_at = time.time() + expires_in
            logger.info(f"QQ 机器人 access_token 获取成功，有效期 {expires_in} 秒")
            return self._access_token
        except Exception as e:
            logger.error(f"获取 QQ access_token 失败: {e}")
            raise

    async def _get_headers(self) -> Dict[str, str]:
        """获取鉴权请求头"""
        token = await self._get_access_token()
        return {
            "Authorization": f"QQBot {token}",
            "Content-Type": "application/json",
        }

    async def _get_gateway_url(self) -> str:
        """通过 API 动态获取 WebSocket 网关地址"""
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(
                base_url=self.config.api_base_url,
                timeout=30,
            )

        try:
            headers = await self._get_headers()
            resp = await self._http_client.get(
                "/gateway",
                headers=headers,
            )
            resp.raise_for_status()
            data = resp.json()
            url = data.get("url", "")
            if url:
                logger.info(f"获取到 WebSocket 网关地址: {url}")
                return url
            logger.error(f"网关地址为空，响应: {data}")
        except Exception as e:
            logger.error(f"获取 WebSocket 网关地址失败: {e}")
        return None

    # ============================================================
    # 消息发送
    # ============================================================
    def _extract_image_urls(self, content: str) -> List[str]:
        """从消息内容中提取 Markdown 图片 URL"""
        import re
        # 匹配 Markdown 图片格式 ![alt](url)
        md_images = re.findall(r'!\[.*?\]\((https?://[^\s)]+)\)', content)
        # 匹配普通 URL 结尾为图片格式
        url_images = re.findall(r'(https?://[^\s]+\.(?:png|jpg|jpeg|gif|webp))', content, re.IGNORECASE)
        # 去重，保持顺序
        seen = set()
        result = []
        for url in md_images + url_images:
            if url not in seen:
                seen.add(url)
                result.append(url)
        return result

    async def _download_image_base64(self, img_url: str, max_retries: int = 3) -> Optional[str]:
        """
        下载图片并转为 base64 编码

        P1-8/P1-15: 加入重试机制（指数退避），避免瞬时网络抖动导致图片丢失。
        重试在下载层完成，外层 send_c2c_message 不再重复下载。
        """
        last_error = None
        for attempt in range(max_retries):
            try:
                img_resp = await self._http_client.get(
                    img_url,
                    headers={
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                        "Referer": "https://www.pixiv.net/",
                    },
                    follow_redirects=True,
                    timeout=15,
                )
                img_resp.raise_for_status()

                content_type = img_resp.headers.get("content-type", "")
                if not content_type.startswith("image/"):
                    logger.warning(f"URL 返回的不是图片: {img_url}, content-type={content_type}")
                    return None

                # 限制图片大小 20MB（QQ 图片消息上限）
                if len(img_resp.content) > 20 * 1024 * 1024:
                    logger.warning(f"图片过大，跳过: {img_url}, size={len(img_resp.content)}")
                    return None

                img_base64 = base64.b64encode(img_resp.content).decode("utf-8")
                logger.info(f"图片下载并编码成功: {img_url}, size={len(img_resp.content)} bytes, attempt={attempt + 1}")
                return img_base64
            except Exception as e:
                last_error = e
                if attempt < max_retries - 1:
                    delay = 1.0 * (2 ** attempt)
                    logger.warning(f"下载图片失败 (尝试 {attempt + 1}/{max_retries}), {delay}s 后重试: {img_url}, error={e}")
                    await asyncio.sleep(delay)
                    continue
        logger.warning(f"下载图片最终失败: {img_url}, error={last_error}")
        return None

    async def send_channel_message(self, channel_id: str, content: str, max_retries: int = 3) -> Dict[str, Any]:
        """
        发送频道消息（带重试）

        参数：
            channel_id: 子频道 ID
            content: 消息内容
            max_retries: 最大重试次数
        """
        content = self._truncate_message(content)
        last_error = None
        
        for attempt in range(max_retries):
            try:
                headers = await self._get_headers()
                resp = await self._http_client.post(
                    f"/channels/{channel_id}/messages",
                    headers=headers,
                    json={"content": content},
                )
                resp.raise_for_status()
                logger.info(f"发送频道消息成功: channel_id={channel_id}, length={len(content)}")
                return resp.json()
            except Exception as e:
                last_error = e
                logger.warning(f"发送频道消息失败 (尝试 {attempt + 1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(1.0 * (2 ** attempt))
        
        logger.error(f"发送频道消息最终失败: channel_id={channel_id}, error={last_error}")
        return {"error": str(last_error)}

    async def send_dm_message(self, guild_id: str, content: str, max_retries: int = 3) -> Dict[str, Any]:
        """
        发送频道私信消息（带重试）

        参数：
            guild_id: 私信会话 ID
            content: 消息内容
            max_retries: 最大重试次数
        """
        content = self._truncate_message(content)
        last_error = None
        
        for attempt in range(max_retries):
            try:
                headers = await self._get_headers()
                resp = await self._http_client.post(
                    f"/dms/{guild_id}/messages",
                    headers=headers,
                    json={"content": content},
                )
                resp.raise_for_status()
                logger.info(f"发送频道私信成功: guild_id={guild_id}, length={len(content)}")
                return resp.json()
            except Exception as e:
                last_error = e
                logger.warning(f"发送频道私信失败 (尝试 {attempt + 1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(1.0 * (2 ** attempt))
        
        logger.error(f"发送频道私信最终失败: guild_id={guild_id}, error={last_error}")
        return {"error": str(last_error)}

    async def send_c2c_message(self, user_id: str, content: str, max_retries: int = 3,
                               msg_id: str = None, event_id: str = None) -> Dict[str, Any]:
        """
        发送 C2C 私聊消息（带重试）
        支持自动检测并发送图片消息（下载→base64 编码→QQ 图片消息）

        参数：
            user_id: 用户 openid
            content: 消息内容
            max_retries: 最大重试次数
            msg_id: 被动回复时传入用户消息的 id（60 分钟内有效，最多 4 次）。
                    QQ 官方 API 要求：msg_id 必须是真实收到的用户消息 ID，
                    自生成随机 ID 会被拒绝（400 Bad Request）。
            event_id: 被动回复时传入事件 ID（与 msg_id 互斥，二选一）

        P1-8: 图片下载移到 retry 循环外（下载已有自己的重试），外层 retry 只重试发送，
              避免重复下载浪费带宽。
        """
        content = self._truncate_message(content)
        last_error = None

        # 检测消息中的图片URL
        image_urls = self._extract_image_urls(content)

        # P1-8: 图片下载在 retry 循环外完成（下载层有自己的重试）
        downloaded_images = []
        if image_urls:
            for img_url in image_urls[:3]:  # 最多发3张图
                img_base64 = await self._download_image_base64(img_url)
                if img_base64:
                    downloaded_images.append((img_url, img_base64))

        for attempt in range(max_retries):
            try:
                headers = await self._get_headers()

                # 如果有图片，发送图片消息
                for img_url, img_base64 in downloaded_images:
                    try:
                        img_payload = {
                            "msg_type": 7,
                            "media": {
                                "file_info": img_base64,
                            },
                            "msg_seq": _next_msg_seq(),  # 模块级单调递增
                        }
                        # 被动回复时携带 msg_id/event_id（必须为真实用户消息 ID）
                        if msg_id:
                            img_payload["msg_id"] = msg_id
                        elif event_id:
                            img_payload["event_id"] = event_id
                        img_resp = await self._http_client.post(
                            f"/v2/users/{user_id}/messages",
                            headers=headers,
                            json=img_payload,
                        )
                        if img_resp.status_code == 200:
                            logger.info(f"发送 C2C 图片消息成功: user_id={user_id}, url={img_url[:60]}")
                        else:
                            logger.warning(f"发送 C2C 图片消息失败: status={img_resp.status_code}, body={img_resp.text[:200]}")
                    except Exception as img_e:
                        logger.warning(f"发送图片消息异常: {img_e}")

                # 发送文本消息
                # QQ 官方 API：msg_type 必填（0=文本）；被动回复时 msg_id 为真实用户消息 ID
                text_payload = {
                    "content": content,
                    "msg_type": 0,  # 文本消息类型（QQ API 必填字段）
                    "msg_seq": _next_msg_seq(),  # 模块级单调递增
                }
                # 被动回复时携带 msg_id/event_id（必须为真实用户消息 ID）
                # 自生成随机 msg_id 会被 QQ API 拒绝（400 Bad Request）
                if msg_id:
                    text_payload["msg_id"] = msg_id
                elif event_id:
                    text_payload["event_id"] = event_id
                resp = await self._http_client.post(
                    f"/v2/users/{user_id}/messages",
                    headers=headers,
                    json=text_payload,
                )
                resp.raise_for_status()
                logger.info(f"发送 C2C 消息成功: user_id={user_id}, length={len(content)}")
                return resp.json()
            except Exception as e:
                last_error = e
                logger.warning(f"发送 C2C 消息失败 (尝试 {attempt + 1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(1.0 * (2 ** attempt))

        logger.error(f"发送 C2C 消息最终失败: user_id={user_id}, error={last_error}")
        return {"error": str(last_error)}

    async def send_group_message(self, group_id: str, content: str, max_retries: int = 3,
                                 msg_id: str = None) -> Dict[str, Any]:
        """
        发送群消息（带重试）

        参数：
            group_id: 群 ID
            content: 消息内容
            max_retries: 最大重试次数
            msg_id: 被动回复时传入用户消息的 id（5 分钟内有效，最多 5 次）
        """
        content = self._truncate_message(content)
        last_error = None

        for attempt in range(max_retries):
            try:
                headers = await self._get_headers()
                # QQ 官方 API：msg_type 必填（0=文本）；被动回复时 msg_id 为真实用户消息 ID
                payload = {
                    "content": content,
                    "msg_type": 0,  # 文本消息类型（QQ API 必填字段）
                    "msg_seq": _next_msg_seq(),  # 模块级单调递增
                }
                if msg_id:
                    payload["msg_id"] = msg_id
                resp = await self._http_client.post(
                    f"/groups/{group_id}/messages",
                    headers=headers,
                    json=payload,
                )
                resp.raise_for_status()
                logger.info(f"发送群消息成功: group_id={group_id}, length={len(content)}")
                return resp.json()
            except Exception as e:
                last_error = e
                logger.warning(f"发送群消息失败 (尝试 {attempt + 1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(1.0 * (2 ** attempt))

        logger.error(f"发送群消息最终失败: group_id={group_id}, error={last_error}")
        return {"error": str(last_error)}

    # ============================================================
    # 消息处理
    # ============================================================
    def on_message(self, handler: Callable[[str, Dict[str, Any]], str]) -> None:
        """
        注册消息处理函数

        handler 签名: (content: str, context: dict) -> reply: str
        context 包含: message_id, author_id, channel_id, guild_id, message_type 等
        """
        self._message_handler = handler

    async def _handle_message_event(self, event_data: Dict[str, Any]) -> None:
        """处理收到的消息事件"""
        if not self._message_handler:
            logger.warning("未注册消息处理函数")
            return

        try:
            event_type = event_data.get("t", "")
            d = event_data.get("d", {})

            # 提取消息内容
            content = d.get("content", "").strip()
            if not content:
                logger.debug(f"空消息内容，event_type={event_type}")
                return

            # 提取上下文信息
            message_id = d.get("id", "")
            author = d.get("author", {})
            author_id = author.get("id", "")
            guild_id = d.get("guild_id", "") or d.get("src_guild_id", "") or d.get("source_guild_id", "")
            channel_id = d.get("channel_id", "")
            group_id = d.get("group_id", "")
            user_id = d.get("user_id", "") or d.get("openid", "") or author_id

            # 消息鉴权（白名单检查）
            allowed_users = self.config.allowed_users
            allowed_groups = self.config.allowed_groups

            # 检查用户白名单
            if allowed_users:
                if user_id not in allowed_users:
                    logger.debug(f"用户不在白名单中，跳过: user_id={user_id}")
                    return

            # 检查群组白名单（仅对群消息生效）
            if allowed_groups and group_id:
                if group_id not in allowed_groups:
                    logger.debug(f"群不在白名单中，跳过: group_id={group_id}")
                    return

            # 消息去重
            if message_id and self._is_message_processed(message_id):
                logger.debug(f"消息已处理，跳过: message_id={message_id}")
                return
            if message_id:
                self._add_message_cache(message_id)

            # 判断消息类型
            message_type = "unknown"
            if event_type in ("MESSAGE_CREATE", "AT_MESSAGE_CREATE"):
                message_type = "channel"  # 频道消息（含@消息）
            elif event_type == "DIRECT_MESSAGE_CREATE":
                message_type = "direct"  # 频道私信
            elif event_type in ("GROUP_MESSAGE", "GROUP_AT_MESSAGE_CREATE"):
                message_type = "group"  # 群消息（含@消息）
            elif event_type == "C2C_MESSAGE_CREATE":
                message_type = "c2c"  # C2C 消息

            context = {
                "message_id": message_id,
                "author_id": author_id,
                "user_id": user_id,
                "guild_id": guild_id,
                "channel_id": channel_id,
                "group_id": group_id,
                "message_type": message_type,
                "event_type": event_type,
            }

            logger.info(f"收到 {message_type} 消息 [event={event_type}]: user={user_id[:10] if user_id else 'N/A'}, content={content[:100]}")
            logger.debug(f"消息完整上下文: {json.dumps(context, ensure_ascii=False)}")

            # 在线程池中调用消息处理函数（避免阻塞 asyncio 事件循环）
            # message_handler 是同步函数，内部会调用 LLM API，可能耗时数秒
            try:
                logger.debug(f"在线程池中调用消息处理函数，content={content[:50]}")
                reply = await asyncio.to_thread(self._message_handler, content, context)
                logger.debug(f"消息处理完成，reply_length={len(reply) if reply else 0}")
            except Exception as e:
                logger.error(f"消息处理函数执行失败: {e}", exc_info=True)
                reply = "抱歉，处理消息时出错了"

            # 回复消息
            if reply:
                logger.debug(f"准备回复消息，type={message_type}")
                if message_type == "channel" and channel_id:
                    await self.send_channel_message(channel_id, reply)
                elif message_type == "direct" and guild_id:
                    await self.send_dm_message(guild_id, reply)
                elif message_type == "group" and group_id:
                    # 群消息回复：传 msg_id 作为被动回复标识
                    await self.send_group_message(group_id, reply, msg_id=message_id)
                elif message_type == "c2c" and user_id:
                    # C2C 消息回复：必须传真实用户消息 ID 作为 msg_id
                    # QQ 官方 API：自生成随机 msg_id 会被拒绝（400 Bad Request）
                    await self.send_c2c_message(user_id, reply, msg_id=message_id)
                else:
                    logger.error(f"无法回复消息: message_type={message_type}, channel_id={channel_id}, guild_id={guild_id}, group_id={group_id}, user_id={user_id}")
            else:
                logger.warning(f"消息处理函数返回空回复: content={content[:50]}")

        except Exception as e:
            logger.error(f"处理消息事件失败: {e}", exc_info=True)

    # ============================================================
    # WebSocket 连接
    # ============================================================
    async def _connect_ws(self) -> None:
        """建立 WebSocket 连接（单次连接，支持 RESUME 恢复会话）"""
        if websockets is None:
            raise ImportError("请安装 websockets: pip install websockets")

        # 动态获取 WebSocket 网关地址
        url = await self._get_gateway_url()
        if not url:
            url = "wss://api.sgroup.qq.com/websocket"
            logger.warning(f"无法获取动态网关地址，使用默认: {url}")
        logger.info(f"正在连接 QQ 机器人 WebSocket: {url}")

        async with websockets.connect(
            url,
            # P1-12: 设置 ping_interval/ping_timeout，避免连接假死
            ping_interval=20,
            ping_timeout=20,
            close_timeout=10,
        ) as ws:
            self._ws = ws
            self._running = True
            self._reconnect_delay = 5.0  # 重置重连延迟

            # 等待 Hello 包
            hello_msg = await ws.recv()
            hello_data = json.loads(hello_msg)
            logger.info(f"收到 Hello 包: op={hello_data.get('op')}, 数据: {json.dumps(hello_data, ensure_ascii=False)[:200]}")

            if hello_data.get("op") == 10:
                self._heartbeat_interval = (hello_data.get("d") or {}).get("heartbeat_interval", 30000) / 1000
                logger.info(f"心跳间隔: {self._heartbeat_interval} 秒")

            # 判断是 RESUME 恢复会话还是全新鉴权
            if self._session_id and self._seq:
                # 发送 RESUME 包（恢复之前的会话，避免消息丢失）
                token = await self._get_access_token()
                resume_payload = {
                    "op": 6,
                    "d": {
                        "token": f"QQBot {token}",
                        "session_id": self._session_id,
                        "seq": self._seq,
                    },
                }
                await ws.send(json.dumps(resume_payload))
                logger.info(f"已发送 RESUME 包: session_id={self._session_id}, seq={self._seq}")
            else:
                # 全新鉴权
                token = await self._get_access_token()
                auth_payload = {
                    "op": 2,
                    "d": {
                        "token": f"QQBot {token}",
                        "intents": self.config.intent,
                        "shard": [0, 1],
                        "properties": {
                            "$os": "windows",
                            "$browser": "castorice-agent",
                            "$device": "castorice-agent",
                        },
                    },
                }
                await ws.send(json.dumps(auth_payload))
                logger.info(f"已发送鉴权包，订阅 intents: {self.config.intent}")

            # 启动心跳协程
            heartbeat_task = asyncio.create_task(self._heartbeat_loop())

            # 消息循环
            try:
                async for message in ws:
                    try:
                        data = json.loads(message)
                        logger.debug(f"收到 WebSocket 原始消息: {json.dumps(data, ensure_ascii=False)[:300]}")
                        await self._handle_ws_message(data)
                    except Exception as e:
                        logger.error(f"解析 WebSocket 消息失败: {e}, 原始: {message[:200]}")
            finally:
                heartbeat_task.cancel()
                logger.info("WebSocket 连接已断开")

    async def _connect_with_reconnect(self) -> None:
        """建立 WebSocket 连接（带自动重连）"""
        reconnect_count = 0
        while self._running:
            try:
                await self._connect_ws()
                # 连接成功，重置重连计数和延迟
                reconnect_count = 0
                self._reconnect_delay = 5.0
            except Exception as e:
                reconnect_count += 1
                error_str = str(e)
                logger.error(f"WebSocket 连接失败 (第 {reconnect_count} 次): {e}")

                # 4014: disallowed intents - 不应重试，需要用户修改配置
                if "4014" in error_str or "disallowed intents" in error_str:
                    logger.error("=" * 60)
                    logger.error("4014 错误：当前 Intent 配置不被平台允许！")
                    logger.error("请在 castorice_config.yaml 中将 intent 改为 'basic'")
                    logger.error("如果需要 C2C 私聊功能，请先在 QQ 开放平台申请相关权限")
                    logger.error("=" * 60)
                    self._running = False
                    return

                # 4009: Session timed out - 清除 session，下次全新鉴权
                if "4009" in error_str or "Session timed out" in error_str:
                    logger.warning("会话超时，下次连接将使用全新鉴权")
                    self._session_id = None
                    self._seq = 0

            if self._running:
                # 如果有 session_id，说明是服务端要求重连，快速重连
                if self._session_id and reconnect_count == 1:
                    self._reconnect_delay = 1.0  # 快速重连
                logger.info(f"第 {reconnect_count} 次重连将在 {self._reconnect_delay:.1f} 秒后进行...")
                await asyncio.sleep(self._reconnect_delay)

                # 指数退避（但不超过 60 秒）
                self._reconnect_delay = min(self._reconnect_delay * 2, 60)

    async def _handle_ws_message(self, data: Dict[str, Any]) -> None:
        """处理 WebSocket 消息"""
        op = data.get("op", -1)
        seq = data.get("s")
        if seq:
            self._seq = seq

        if op == 0:  # Dispatch
            event_type = data.get("t", "")
            event_data = data.get("d", {})

            if event_type in ("READY", "RESUMED"):
                self._session_id = event_data.get("session_id", "")
                if event_type == "RESUMED":
                    logger.info(f"会话已恢复: session_id={self._session_id}, seq={self._seq}")
                else:
                    logger.info(f"机器人已就绪: session_id={self._session_id}")
                    logger.info(f"READY 事件数据: {json.dumps(event_data, ensure_ascii=False)[:500]}")
                    user = event_data.get("user", {})
                    if user:
                        logger.info(f"机器人身份: id={user.get('id')}, username={user.get('username')}, bot={user.get('bot')}")
                    shard = event_data.get("shard", [])
                    if shard:
                        logger.info(f"分片信息: {shard}")
            elif event_type in ("MESSAGE_CREATE", "AT_MESSAGE_CREATE", "DIRECT_MESSAGE_CREATE",
                                "C2C_MESSAGE_CREATE", "GROUP_MESSAGE", "GROUP_AT_MESSAGE_CREATE"):
                logger.info(f"收到消息事件: {event_type}, seq={seq}")
                await self._handle_message_event(data)
            else:
                logger.info(f"收到事件: {event_type}, seq={seq}, 数据: {json.dumps(event_data, ensure_ascii=False)[:200]}")

        elif op == 11:  # Heartbeat ACK
            logger.debug("心跳确认")

        elif op == 7:  # Reconnect - 服务端要求重连，保持 session_id 以便 RESUME
            logger.warning("服务端要求重连，将尝试 RESUME 恢复会话...")
            # 不清除 session_id，重连时使用 RESUME 恢复
            # 关闭当前连接，触发重连
            if self._ws:
                try:
                    await self._ws.close()
                except Exception as e:
                    logger.warning(f"WebSocket 关闭失败: {e}")

        elif op == 9:  # Invalid Session - 需要重新鉴权
            logger.error("无效会话，需要重新鉴权")
            # 清除 session_id，下次连接使用全新鉴权
            self._session_id = None
            self._seq = 0

        else:
            logger.info(f"收到未知 op={op} 消息: {json.dumps(data, ensure_ascii=False)[:200]}")

    def _is_ws_open(self) -> bool:
        """检查 WebSocket 是否连接（兼容不同 websockets 版本）"""
        if not self._ws:
            return False
        try:
            # websockets >= 11.0
            from websockets.protocol import State
            return self._ws.state == State.OPEN
        except ImportError:
            try:
                # websockets < 11.0
                return self._ws.open
            except AttributeError:
                return False

    async def _heartbeat_loop(self) -> None:
        """心跳循环"""
        while self._running:
            try:
                await asyncio.sleep(self._heartbeat_interval)
                if self._is_ws_open():
                    heartbeat = {
                        "op": 1,
                        "d": self._seq if self._seq else None,
                    }
                    await self._ws.send(json.dumps(heartbeat))
                    logger.debug("已发送心跳")
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"心跳发送失败: {e}")

    # ============================================================
    # 启动与停止
    # ============================================================
    async def start(self) -> None:
        """启动机器人（异步，带自动重连）"""
        logger.info("正在启动 QQ 机器人...")
        logger.info(f"Intent 配置: {self.config.intent}")
        logger.info(f"Intent 含义: AT_MESSAGE={bool(self.config.intent & QQBotConfig.INTENT_AT_MESSAGE)}, DIRECT_MESSAGE={bool(self.config.intent & QQBotConfig.INTENT_DIRECT_MESSAGE)}, C2C_MESSAGE={bool(self.config.intent & QQBotConfig.INTENT_C2C_MESSAGE)}, GROUP_MESSAGE={bool(self.config.intent & QQBotConfig.INTENT_GROUP_MESSAGE)}")
        
        self._running = True
        try:
            await self._connect_with_reconnect()
        except Exception as e:
            logger.error(f"QQ 机器人启动失败: {e}")
            raise

    def run(self) -> None:
        """启动机器人（同步阻塞）"""
        asyncio.run(self.start())

    def start_in_thread(self) -> threading.Thread:
        """在后台线程中启动机器人"""
        thread = threading.Thread(target=self.run, daemon=True)
        thread.start()
        logger.info("QQ 机器人已在后台线程启动")
        return thread

    async def stop(self) -> None:
        """停止机器人"""
        logger.info("正在停止 QQ 机器人...")
        self._running = False
        if self._ws:
            try:
                await self._ws.close()
            except Exception as e:
                logger.warning(f"关闭 WebSocket 失败: {e}")
            self._ws = None  # P1-9: 清除引用，避免误判连接状态
        # P1-9: 关闭后置 None，避免后续误用已关闭的客户端
        if self._http_client is not None:
            try:
                await self._http_client.aclose()
            except Exception as e:
                logger.warning(f"关闭 HTTP 客户端失败: {e}")
            self._http_client = None
        logger.info("QQ 机器人已停止")


# ============================================================
# 便捷工厂函数
# ============================================================
def create_qq_bot(
    app_id: str,
    app_secret: str,
    sandbox: bool = False,
    message_handler: Optional[Callable[[str, Dict[str, Any]], str]] = None,
) -> QQBotAdapter:
    """
    便捷创建 QQ 机器人实例

    参数：
        app_id: 应用 ID
        app_secret: 应用密钥
        sandbox: 是否使用沙箱环境
        message_handler: 消息处理函数

    返回：
        QQBotAdapter 实例
    """
    config = QQBotConfig(app_id=app_id, app_secret=app_secret, sandbox=sandbox)
    bot = QQBotAdapter(config)
    if message_handler:
        bot.on_message(message_handler)
    return bot
