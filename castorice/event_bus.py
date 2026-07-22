"""
事件总线 (EventBus)

为 Castorice Agent 提供全局事件发布/订阅机制。
用于将 Agent 内部的状态变化（工具调用、情感变化、记忆更新等）
实时推送到前端（WebSocket）。

设计原则：
- 轻量：不依赖外部库，纯 Python 实现
- 线程安全：支持多线程环境下的发布/订阅
- 异步友好：同时支持同步回调和 asyncio 队列
"""

import asyncio
import logging
import threading
import time
from dataclasses import dataclass, field, asdict
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("Castorice.EventBus")


@dataclass
class Event:
    """事件对象"""
    type: str                          # 事件类型：tool_start / tool_end / emotion_change / message_chunk 等
    data: Dict[str, Any] = field(default_factory=dict)  # 事件数据
    session_id: Optional[str] = None   # 关联的会话 ID
    timestamp: float = field(default_factory=time.time)  # 事件时间戳

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class EventBus:
    """
    事件总线 - 发布/订阅模式

    支持两种订阅方式：
    1. 同步回调（sync callback）- 适合在同一线程处理
    2. 异步队列（asyncio.Queue）- 适合 WebSocket 等异步场景
    """

    def __init__(self):
        self._subscribers: Dict[str, List[Callable]] = {}  # type -> [callback]
        self._async_subscribers: Dict[str, List[asyncio.Queue]] = {}  # type -> [queue]
        self._all_subscribers: List[Callable] = []  # 订阅所有事件的回调
        self._all_async_subscribers: List[asyncio.Queue] = []  # 订阅所有事件的队列
        self._lock = threading.Lock()
        self._event_count = 0

    def publish(self, event_type: str, data: Optional[Dict[str, Any]] = None,
                session_id: Optional[str] = None) -> None:
        """
        发布事件（同步，线程安全）

        Args:
            event_type: 事件类型
            data: 事件数据
            session_id: 关联的会话 ID
        """
        event = Event(
            type=event_type,
            data=data or {},
            session_id=session_id,
        )
        self._event_count += 1

        # 同步回调
        with self._lock:
            callbacks = list(self._all_subscribers)
            if event_type in self._subscribers:
                callbacks.extend(self._subscribers[event_type])

        for callback in callbacks:
            try:
                callback(event)
            except Exception as e:
                logger.error(f"事件回调执行失败 type={event_type}: {e}")

        # 异步队列（需要在 event loop 中投递）
        with self._lock:
            queues = list(self._all_async_subscribers)
            if event_type in self._async_subscribers:
                queues.extend(self._async_subscribers[event_type])

        for queue in queues:
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    loop.call_soon_threadsafe(queue.put_nowait, event)
                else:
                    # 没有运行的 loop，直接放队列（调用方会在自己的 loop 里取）
                    queue.put_nowait(event)
            except Exception as e:
                logger.error(f"事件队列投递失败 type={event_type}: {e}")

    def subscribe(self, event_type: str, callback: Callable) -> Callable:
        """
        订阅指定类型的事件（同步回调）

        Args:
            event_type: 事件类型，"*" 表示订阅所有事件
            callback: 回调函数，接收 Event 对象

        Returns:
            取消订阅的函数
        """
        with self._lock:
            if event_type == "*":
                self._all_subscribers.append(callback)
            else:
                if event_type not in self._subscribers:
                    self._subscribers[event_type] = []
                self._subscribers[event_type].append(callback)

        def unsubscribe():
            self._unsubscribe(event_type, callback)

        return unsubscribe

    def subscribe_async(self, event_type: str, queue: asyncio.Queue) -> Callable:
        """
        订阅指定类型的事件（异步队列）

        Args:
            event_type: 事件类型，"*" 表示订阅所有事件
            queue: asyncio.Queue 对象，事件会被 put 进去

        Returns:
            取消订阅的函数
        """
        with self._lock:
            if event_type == "*":
                self._all_async_subscribers.append(queue)
            else:
                if event_type not in self._async_subscribers:
                    self._async_subscribers[event_type] = []
                self._async_subscribers[event_type].append(queue)

        def unsubscribe():
            self._unsubscribe_async(event_type, queue)

        return unsubscribe

    def _unsubscribe(self, event_type: str, callback: Callable) -> None:
        """取消同步订阅"""
        with self._lock:
            try:
                if event_type == "*":
                    self._all_subscribers.remove(callback)
                elif event_type in self._subscribers:
                    self._subscribers[event_type].remove(callback)
            except ValueError:
                pass

    def _unsubscribe_async(self, event_type: str, queue: asyncio.Queue) -> None:
        """取消异步订阅"""
        with self._lock:
            try:
                if event_type == "*":
                    self._all_async_subscribers.remove(queue)
                elif event_type in self._async_subscribers:
                    self._async_subscribers[event_type].remove(queue)
            except ValueError:
                pass

    def get_stats(self) -> Dict[str, Any]:
        """获取事件总线统计信息"""
        with self._lock:
            type_counts = {k: len(v) for k, v in self._subscribers.items()}
            async_type_counts = {k: len(v) for k, v in self._async_subscribers.items()}
            return {
                "total_events_published": self._event_count,
                "sync_subscribers_total": sum(type_counts.values()) + len(self._all_subscribers),
                "async_subscribers_total": sum(async_type_counts.values()) + len(self._all_async_subscribers),
                "event_types": list(type_counts.keys()) + list(async_type_counts.keys()),
            }


# ========== 全局单例 ==========

_global_event_bus: Optional[EventBus] = None
_global_bus_lock = threading.Lock()


def get_event_bus() -> EventBus:
    """获取全局事件总线单例"""
    global _global_event_bus
    if _global_event_bus is None:
        with _global_bus_lock:
            if _global_event_bus is None:
                _global_event_bus = EventBus()
                logger.debug("全局事件总线已初始化")
    return _global_event_bus


def publish_event(event_type: str, data: Optional[Dict[str, Any]] = None,
                  session_id: Optional[str] = None) -> None:
    """便捷函数：发布事件到全局总线"""
    bus = get_event_bus()
    bus.publish(event_type, data, session_id)
