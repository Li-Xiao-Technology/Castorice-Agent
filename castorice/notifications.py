"""
实时通知系统

支持 WebSocket 和 SSE 两种推送方式：
- WebSocket: 双向通信，适合实时聊天和交互
- SSE (Server-Sent Events): 单向推送，适合状态更新和通知

支持的通知类型：
- 消息通知
- 任务状态更新
- 系统警报
- Agent 状态变化
"""

import json
import logging
import threading
import time
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set

logger = logging.getLogger("Castorice.Notifications")


class NotificationType(Enum):
    MESSAGE = "message"
    TASK_UPDATE = "task_update"
    SYSTEM_ALERT = "system_alert"
    AGENT_STATUS = "agent_status"
    MEMORY_UPDATE = "memory_update"
    REFLECTION = "reflection"


class Notification:
    def __init__(
        self,
        notification_type: NotificationType,
        title: str,
        message: str,
        payload: Dict[str, Any] = None,
        timestamp: float = None,
    ):
        self.type = notification_type.value
        self.title = title
        self.message = message
        self.payload = payload or {}
        self.timestamp = timestamp or time.time()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.type,
            "title": self.title,
            "message": self.message,
            "payload": self.payload,
            "timestamp": self.timestamp,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)


class NotificationManager:
    """通知管理器"""

    def __init__(self):
        self._subscribers: Dict[str, Set[Callable]] = {}
        self._lock = threading.Lock()
        self._history: List[Notification] = []
        self._max_history = 100

    def subscribe(self, notification_type: str, callback: Callable) -> None:
        """订阅通知类型"""
        with self._lock:
            if notification_type not in self._subscribers:
                self._subscribers[notification_type] = set()
            self._subscribers[notification_type].add(callback)
        logger.debug(f"订阅通知: {notification_type}")

    def unsubscribe(self, notification_type: str, callback: Callable) -> None:
        """取消订阅"""
        with self._lock:
            if notification_type in self._subscribers:
                self._subscribers[notification_type].discard(callback)

    def publish(self, notification: Notification) -> None:
        """发布通知"""
        with self._lock:
            self._history.append(notification)
            if len(self._history) > self._max_history:
                self._history = self._history[-self._max_history:]

            subscribers = self._subscribers.get(notification.type, set())
            subscribers.update(self._subscribers.get("*", set()))

        for callback in subscribers:
            try:
                callback(notification)
            except Exception as e:
                logger.error(f"通知回调失败: {e}")

    def get_history(self, limit: int = 20) -> List[Dict[str, Any]]:
        """获取通知历史"""
        with self._lock:
            return [n.to_dict() for n in self._history[-limit:]]

    def send_message(self, title: str, message: str, payload: Dict[str, Any] = None):
        """发送消息通知"""
        self.publish(Notification(
            NotificationType.MESSAGE,
            title=title,
            message=message,
            payload=payload or {},
        ))

    def send_task_update(self, task_id: str, status: str, message: str = ""):
        """发送任务状态更新"""
        self.publish(Notification(
            NotificationType.TASK_UPDATE,
            title=f"任务 {task_id}",
            message=message or f"任务状态变为 {status}",
            payload={"task_id": task_id, "status": status},
        ))

    def send_system_alert(self, level: str, message: str):
        """发送系统警报"""
        self.publish(Notification(
            NotificationType.SYSTEM_ALERT,
            title=f"系统警报 ({level.upper()})",
            message=message,
            payload={"level": level},
        ))

    def send_agent_status(self, agent_id: str, status: str):
        """发送 Agent 状态变化"""
        self.publish(Notification(
            NotificationType.AGENT_STATUS,
            title=f"Agent {agent_id}",
            message=f"状态变为 {status}",
            payload={"agent_id": agent_id, "status": status},
        ))


class SSEManager:
    """SSE (Server-Sent Events) 管理器"""

    def __init__(self, notification_manager: NotificationManager):
        self._notification_manager = notification_manager
        self._connections: Set[Any] = set()
        self._lock = threading.Lock()

    def add_connection(self, connection: Any):
        """添加 SSE 连接"""
        with self._lock:
            self._connections.add(connection)
        self._notification_manager.subscribe("*", self._broadcast)

    def remove_connection(self, connection: Any):
        """移除 SSE 连接"""
        with self._lock:
            self._connections.discard(connection)

    def _broadcast(self, notification: Notification):
        """广播通知到所有 SSE 连接"""
        with self._lock:
            closed_connections = set()
            for conn in self._connections:
                try:
                    data = notification.to_json()
                    conn.write(f"data: {data}\n\n")
                    conn.flush()
                except Exception:
                    closed_connections.add(conn)

            self._connections -= closed_connections


_notification_manager = None


def get_notification_manager() -> NotificationManager:
    """获取全局通知管理器单例"""
    global _notification_manager
    if _notification_manager is None:
        _notification_manager = NotificationManager()
    return _notification_manager
