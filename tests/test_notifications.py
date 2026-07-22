"""
P2 通知系统测试
"""
import pytest
from castorice.notifications import (
    NotificationType,
    Notification,
    NotificationManager,
    get_notification_manager,
)


class TestNotificationType:
    def test_types_exist(self):
        """测试所有通知类型存在"""
        assert NotificationType.MESSAGE.value == "message"
        assert NotificationType.TASK_UPDATE.value == "task_update"
        assert NotificationType.SYSTEM_ALERT.value == "system_alert"
        assert NotificationType.AGENT_STATUS.value == "agent_status"
        assert NotificationType.MEMORY_UPDATE.value == "memory_update"
        assert NotificationType.REFLECTION.value == "reflection"


class TestNotification:
    def test_create_basic(self):
        """测试基本创建"""
        n = Notification(
            notification_type=NotificationType.MESSAGE,
            title="测试",
            message="内容",
        )
        assert n.title == "测试"
        assert n.message == "内容"
        assert n.type == "message"
        assert n.timestamp > 0

    def test_to_dict(self):
        """测试转字典"""
        n = Notification(
            notification_type=NotificationType.SYSTEM_ALERT,
            title="警报",
            message="出错了",
            payload={"level": "high"},
        )
        d = n.to_dict()
        assert d["title"] == "警报"
        assert d["message"] == "出错了"
        assert d["type"] == "system_alert"
        assert d["payload"] == {"level": "high"}

    def test_to_json(self):
        """测试转 JSON"""
        n = Notification(
            notification_type=NotificationType.MESSAGE,
            title="t",
            message="m",
        )
        j = n.to_json()
        assert "t" in j and "m" in j


class TestNotificationManager:
    def test_send_message(self):
        """测试发送消息通知"""
        mgr = NotificationManager()
        mgr.send_message("标题", "内容")
        history = mgr.get_history(5)
        assert len(history) >= 1
        assert history[-1]["type"] == "message"

    def test_send_task_update(self):
        """测试发送任务更新通知"""
        mgr = NotificationManager()
        mgr.send_task_update("task1", "running", "任务执行中")
        history = mgr.get_history(5)
        assert any(n["type"] == "task_update" for n in history)

    def test_send_system_alert(self):
        """测试发送系统警报"""
        mgr = NotificationManager()
        mgr.send_system_alert("critical", "系统异常")
        history = mgr.get_history(5)
        assert any(n["type"] == "system_alert" for n in history)

    def test_publish_to_subscribers(self):
        """测试发布到订阅者"""
        mgr = NotificationManager()
        received = []
        mgr.subscribe("message", lambda n: received.append(n))
        mgr.send_message("t", "m")
        assert len(received) == 1
        assert received[0].title == "t"

    def test_wildcard_subscribe(self):
        """测试通配符订阅"""
        mgr = NotificationManager()
        received = []
        mgr.subscribe("*", lambda n: received.append(n))
        mgr.send_message("t1", "m1")
        mgr.send_task_update("t2", "done")
        assert len(received) == 2

    def test_unsubscribe(self):
        """测试取消订阅"""
        mgr = NotificationManager()
        received = []
        cb = lambda n: received.append(n)
        mgr.subscribe("message", cb)
        mgr.unsubscribe("message", cb)
        mgr.send_message("t", "m")
        assert len(received) == 0

    def test_history_limit(self):
        """测试历史记录上限"""
        mgr = NotificationManager()
        for i in range(150):
            mgr.send_message(f"t{i}", f"c{i}")
        history = mgr.get_history(200)
        # 历史应被限制在 100
        assert len(history) == 100

    def test_history_get_limit(self):
        """测试 get_history 的 limit 参数"""
        mgr = NotificationManager()
        for i in range(20):
            mgr.send_message(f"t{i}", f"c{i}")
        history = mgr.get_history(5)
        assert len(history) == 5


class TestNotificationSingleton:
    def test_singleton(self):
        """测试全局单例"""
        m1 = get_notification_manager()
        m2 = get_notification_manager()
        assert m1 is m2
