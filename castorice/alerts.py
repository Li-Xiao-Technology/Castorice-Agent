"""
告警机制模块

支持多种告警渠道：
- 邮件（SMTP）
- 钉钉机器人
- 飞书机器人
- 企微机器人

告警级别：
- CRITICAL: 系统不可用，需要立即处理
- ERROR: 功能异常，需要关注
- WARNING: 潜在问题，建议处理
- INFO: 信息通知
"""

import json
import logging
import threading
import time
from typing import Any, Dict, Optional, List

logger = logging.getLogger("Castorice.Alerts")


class AlertLevel:
    CRITICAL = "CRITICAL"
    ERROR = "ERROR"
    WARNING = "WARNING"
    INFO = "INFO"


class AlertChannel:
    """告警渠道基类"""

    def send(self, level: str, title: str, message: str, **kwargs) -> bool:
        raise NotImplementedError


class EmailChannel(AlertChannel):
    """邮件告警渠道"""

    def __init__(self, smtp_server: str, smtp_port: int, smtp_user: str,
                 smtp_password: str, to_emails: List[str], use_tls: bool = True):
        self.smtp_server = smtp_server
        self.smtp_port = smtp_port
        self.smtp_user = smtp_user
        self.smtp_password = smtp_password
        self.to_emails = to_emails
        self.use_tls = use_tls

    def send(self, level: str, title: str, message: str, **kwargs) -> bool:
        try:
            import smtplib
            from email.mime.text import MIMEText
            from email.header import Header

            msg = MIMEText(message, 'plain', 'utf-8')
            msg['Subject'] = Header(f"[{level}] {title}", 'utf-8')
            msg['From'] = self.smtp_user
            msg['To'] = ",".join(self.to_emails)

            # P2-8: SMTP 设置超时，避免网络异常时阻塞告警线程
            with smtplib.SMTP(self.smtp_server, self.smtp_port, timeout=10) as server:
                if self.use_tls:
                    server.starttls()
                server.login(self.smtp_user, self.smtp_password)
                server.sendmail(self.smtp_user, self.to_emails, msg.as_string())

            logger.info(f"邮件告警发送成功: {title}")
            return True
        except Exception as e:
            logger.error(f"邮件告警发送失败: {e}")
            return False


# P2-7: 共享 httpx 客户端连接池，避免每次发送告警都重建 TCP 连接
_http_client_lock = threading.Lock()
_shared_http_client = None


def _get_shared_httpx_client():
    """获取共享的 httpx.Client（线程安全，懒加载，双重检查锁）"""
    global _shared_http_client
    with _http_client_lock:
        if _shared_http_client is None:
            try:
                import httpx
                _shared_http_client = httpx.Client(timeout=10)
            except ImportError:
                return None
    return _shared_http_client


def close_alert_http_client() -> None:
    """关闭共享的 httpx.Client（程序退出时调用）"""
    global _shared_http_client
    with _http_client_lock:
        if _shared_http_client is not None:
            try:
                _shared_http_client.close()
            except Exception:
                pass
            _shared_http_client = None


# 程序退出时自动关闭共享连接池
import atexit
atexit.register(close_alert_http_client)


class DingTalkChannel(AlertChannel):
    """钉钉机器人告警渠道"""

    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url

    def send(self, level: str, title: str, message: str, **kwargs) -> bool:
        try:
            client = _get_shared_httpx_client()
            if client is None:
                logger.error("httpx 未安装，钉钉告警不可用")
                return False

            color = {
                AlertLevel.CRITICAL: "#ff0000",
                AlertLevel.ERROR: "#ff6600",
                AlertLevel.WARNING: "#ffcc00",
                AlertLevel.INFO: "#00ccff",
            }.get(level, "#000000")

            payload = {
                "msgtype": "markdown",
                "markdown": {
                    "title": title,
                    "text": f"## {title}\n\n**级别**: {level}\n\n**内容**:\n{message}",
                },
                "at": {"isAtAll": level == AlertLevel.CRITICAL},
            }

            resp = client.post(self.webhook_url, json=payload)
            resp.raise_for_status()
            logger.info(f"钉钉告警发送成功: {title}")
            return True
        except Exception as e:
            logger.error(f"钉钉告警发送失败: {e}")
            return False


class FeishuChannel(AlertChannel):
    """飞书机器人告警渠道"""

    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url

    def send(self, level: str, title: str, message: str, **kwargs) -> bool:
        try:
            client = _get_shared_httpx_client()
            if client is None:
                logger.error("httpx 未安装，飞书告警不可用")
                return False

            payload = {
                "msg_type": "text",
                "content": {
                    "text": f"[{level}] {title}\n\n{message}",
                },
            }

            resp = client.post(self.webhook_url, json=payload)
            resp.raise_for_status()
            logger.info(f"飞书告警发送成功: {title}")
            return True
        except Exception as e:
            logger.error(f"飞书告警发送失败: {e}")
            return False


class WeComChannel(AlertChannel):
    """企业微信机器人告警渠道"""

    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url

    def send(self, level: str, title: str, message: str, **kwargs) -> bool:
        try:
            client = _get_shared_httpx_client()
            if client is None:
                logger.error("httpx 未安装，企微告警不可用")
                return False

            payload = {
                "msgtype": "text",
                "text": {
                    "content": f"[{level}] {title}\n\n{message}",
                    "mentioned_list": ["@all"] if level == AlertLevel.CRITICAL else [],
                },
            }

            resp = client.post(self.webhook_url, json=payload)
            resp.raise_for_status()
            logger.info(f"企微告警发送成功: {title}")
            return True
        except Exception as e:
            logger.error(f"企微告警发送失败: {e}")
            return False


class AlertManager:
    """告警管理器（P0-8: 冷却 check-then-set 加锁防竞态）"""

    def __init__(self):
        self._channels: List[AlertChannel] = []
        self._alert_history: List[Dict] = []
        self._last_alert_time: Dict[str, float] = {}
        self._alert_cooldown: int = 60
        # P0-8: 保护冷却字典和历史记录的线程安全
        self._lock = threading.Lock()
        # P0-8: 保护渠道列表的并发修改
        self._channels_lock = threading.Lock()

    def add_channel(self, channel: AlertChannel) -> None:
        """添加告警渠道"""
        with self._channels_lock:
            self._channels.append(channel)

    def remove_channel(self, channel_type: type) -> None:
        """移除指定类型的告警渠道"""
        with self._channels_lock:
            self._channels = [c for c in self._channels if not isinstance(c, channel_type)]

    def send_alert(self, level: str, title: str, message: str,
                   cooldown_key: Optional[str] = None) -> bool:
        """发送告警（P0-8: 冷却判定加锁，避免竞态导致重复告警）"""
        if cooldown_key:
            now = time.time()
            # P0-8: check-then-set 必须在同一个临界区内，避免多线程同时通过冷却检查
            with self._lock:
                last_time = self._last_alert_time.get(cooldown_key, 0)
                if now - last_time < self._alert_cooldown:
                    logger.debug(f"告警冷却中: {title}")
                    return False
                self._last_alert_time[cooldown_key] = now

        alert_record = {
            "level": level,
            "title": title,
            "message": message,
            "timestamp": time.time(),
        }
        with self._lock:
            self._alert_history.append(alert_record)
            if len(self._alert_history) > 1000:
                self._alert_history = self._alert_history[-1000:]

        logger.warning(f"[ALERT] [{level}] {title}: {message}")

        # P0-8: 快照渠道列表，避免遍历时被并发修改
        with self._channels_lock:
            channels_snapshot = list(self._channels)

        success = False
        for channel in channels_snapshot:
            try:
                if channel.send(level, title, message):
                    success = True
            except Exception as e:
                logger.error(f"告警渠道发送失败: {e}")

        return success

    def critical(self, title: str, message: str, cooldown_key: Optional[str] = None) -> bool:
        return self.send_alert(AlertLevel.CRITICAL, title, message, cooldown_key)

    def error(self, title: str, message: str, cooldown_key: Optional[str] = None) -> bool:
        return self.send_alert(AlertLevel.ERROR, title, message, cooldown_key)

    def warning(self, title: str, message: str, cooldown_key: Optional[str] = None) -> bool:
        return self.send_alert(AlertLevel.WARNING, title, message, cooldown_key)

    def info(self, title: str, message: str, cooldown_key: Optional[str] = None) -> bool:
        return self.send_alert(AlertLevel.INFO, title, message, cooldown_key)

    def get_alerts(self, limit: int = 50) -> List[Dict]:
        """获取最近的告警记录"""
        with self._lock:
            return list(reversed(self._alert_history))[:limit]

    def get_stats(self) -> Dict[str, int]:
        """获取告警统计"""
        with self._lock:
            stats = {AlertLevel.CRITICAL: 0, AlertLevel.ERROR: 0, AlertLevel.WARNING: 0, AlertLevel.INFO: 0}
            for alert in self._alert_history:
                level = alert.get("level", AlertLevel.INFO)
                if level in stats:
                    stats[level] += 1
            return stats


_alert_manager = None
_alert_manager_lock = threading.Lock()


def get_alert_manager() -> AlertManager:
    """获取全局告警管理器单例（P0-8: 双重检查锁保证线程安全）"""
    global _alert_manager
    if _alert_manager is None:
        with _alert_manager_lock:
            if _alert_manager is None:
                _alert_manager = AlertManager()
    return _alert_manager


def init_alerts_from_config(config: Dict[str, Any]) -> AlertManager:
    """从配置初始化告警渠道"""
    manager = get_alert_manager()

    alert_config = config.get("alerts", {})

    if alert_config.get("email", {}).get("enabled"):
        email_cfg = alert_config["email"]
        manager.add_channel(EmailChannel(
            smtp_server=email_cfg["smtp_server"],
            smtp_port=email_cfg.get("smtp_port", 587),
            smtp_user=email_cfg["smtp_user"],
            smtp_password=email_cfg["smtp_password"],
            to_emails=email_cfg["to_emails"],
            use_tls=email_cfg.get("use_tls", True),
        ))

    if alert_config.get("dingtalk", {}).get("enabled"):
        manager.add_channel(DingTalkChannel(alert_config["dingtalk"]["webhook_url"]))

    if alert_config.get("feishu", {}).get("enabled"):
        manager.add_channel(FeishuChannel(alert_config["feishu"]["webhook_url"]))

    if alert_config.get("wecom", {}).get("enabled"):
        manager.add_channel(WeComChannel(alert_config["wecom"]["webhook_url"]))

    return manager
