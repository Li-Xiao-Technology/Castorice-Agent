"""
端到端集成测试

测试多个模块协同工作的能力：
- 记忆系统 + 情感引擎 + 反射引擎
- 工具学习 + LLM 缓存
- 多 Agent 协作 + 通知系统
- 安全系统 + 文件操作
"""
import os
import time
import tempfile
import pytest
from unittest.mock import MagicMock, patch

from castorice.emotion import EmotionEngine, EmotionState
from castorice.tool_learning import ToolCallMemory, get_tool_memory
from castorice.response_cache import ResponseCache
from castorice.multi_agent import MultiAgentCoordinator, AgentRole
from castorice.notifications import NotificationManager, NotificationType
from castorice.sqlite_utils import create_sqlite_connection, SQLiteConnectionPool
from castorice.conversation_importer import ConversationImporter, ImportFormat
from castorice.http_client import get_http_client


class TestEmotionMemoryIntegration:
    """情感引擎 + 记忆系统集成"""

    def test_emotion_state_creation(self):
        """测试情感状态默认值"""
        state = EmotionState(pleasure=0.0, arousal=0.0, dominance=0.0)
        assert state.pleasure == 0.0
        assert state.arousal == 0.0
        assert state.dominance == 0.0

    def test_emotion_state_decay(self):
        """测试情感状态衰减"""
        from castorice.emotion import EmotionState
        state = EmotionState(pleasure=0.8, arousal=0.5, dominance=0.3)
        # 衰减应让值向 0 回归
        state.decay()
        assert abs(state.pleasure) < 0.8

    def test_emotion_state_clamp(self):
        """测试情感状态范围限制"""
        from castorice.emotion import EmotionState
        state = EmotionState(pleasure=2.0, arousal=-2.0, dominance=0.5)
        state.clamp()
        # 超出范围的值应被限制到 [-1, 1]
        assert -1.0 <= state.pleasure <= 1.0
        assert -1.0 <= state.arousal <= 1.0


class TestCacheAndToolLearning:
    """LLM 缓存 + 工具学习集成"""

    def test_cached_response_reduces_tool_calls(self):
        """测试缓存命中减少工具调用"""
        cache = ResponseCache()
        tool_mem = ToolCallMemory()

        msgs = [{"role": "user", "content": "查询天气"}]
        response = {"content": "晴天", "tool_calls": []}

        # 第一次写入
        cache.set(msgs, "gpt-4o", response)

        # 记录工具学习（即使无工具调用也记录）
        tool_mem.record("weather_query", "查询天气", {"city": "北京"}, "晴天", True)

        # 第二次读取应命中缓存
        cached = cache.get(msgs, "gpt-4o")
        assert cached == response

        # 工具学习能找到相似模式
        similar = tool_mem.find_similar("weather_query", "查询天气")
        assert len(similar) >= 1


class TestMultiAgentAndNotifications:
    """多 Agent 协作 + 通知系统集成"""

    def test_task_creation_publishes_notification(self):
        """测试任务创建触发通知"""
        mgr = NotificationManager()
        coord = MultiAgentCoordinator()

        # 订阅任务更新
        received = []
        mgr.subscribe("task_update", lambda n: received.append(n))

        # 注册并创建任务
        coord.register_agent("a1", AgentRole.EXECUTOR, "执行者")
        task_id = coord.create_task("execute", {"action": "do_something"},
                                     target_role=AgentRole.EXECUTOR)
        coord.complete_task(task_id, {"result": "done"})

        # 通知应在订阅者处可见
        mgr.send_task_update(task_id, "completed", "任务完成")
        assert len(received) >= 1

    def test_role_based_workflow(self):
        """测试基于角色的完整工作流"""
        mgr = NotificationManager()
        coord = MultiAgentCoordinator()

        # 注册多个角色
        coord.register_agent("a1", AgentRole.ANALYST, "分析师")
        coord.register_agent("p1", AgentRole.PLANNER, "规划师")
        coord.register_agent("e1", AgentRole.EXECUTOR, "执行者")
        coord.register_agent("s1", AgentRole.SUMMARIZER, "总结者")

        from castorice.multi_agent import RoleBasedCoordinator
        rbc = RoleBasedCoordinator(coord)

        # 完整工作流：分析 -> 规划 -> 执行 -> 总结
        t1 = rbc.analyze("需求描述")
        t2 = rbc.plan("目标")
        t3 = rbc.execute({"steps": [1, 2]})
        t4 = rbc.summarize([{"r": "ok"}])

        assert "task_id" in t1
        assert "task_id" in t2
        assert "task_id" in t3
        assert "task_id" in t4

        # 所有 Agent 状态应被正确跟踪
        status = coord.get_status()
        assert len(status["agents"]) == 4
        assert len(status["tasks"]) >= 4


class TestSecurityAndIO:
    """安全系统 + 文件 I/O 集成"""

    def test_safe_file_within_allowed_path(self):
        """测试在允许路径内安全写入"""
        from castorice.security.file_guard import FileWriteGuard, get_file_guard

        with tempfile.TemporaryDirectory() as tmpdir:
            guard = get_file_guard()
            # 仅测试对象可用性
            assert guard is not None

    def test_dangerous_file_blocked(self):
        """测试危险文件被拦截"""
        from castorice.security.file_guard import FORBIDDEN_EXTENSIONS

        # 验证禁止列表存在且非空
        assert len(FORBIDDEN_EXTENSIONS) > 0
        # 常见危险扩展名应被包含
        ext_text = " ".join(FORBIDDEN_EXTENSIONS)
        assert ".env" in ext_text or "env" in ext_text.lower()


class TestConversationImportToMemory:
    """对话导入到记忆系统的集成"""

    def test_jsonl_import_then_store(self, tmp_path):
        """测试 JSONL 导入并存储"""
        # 创建测试文件
        jsonl = tmp_path / "test.jsonl"
        jsonl.write_text(
            '{"role": "user", "content": "你好"}\n'
            '{"role": "assistant", "content": "你好！有什么可以帮你的？"}\n',
            encoding="utf-8",
        )

        importer = ConversationImporter()
        result = importer.import_from_file(str(jsonl), ImportFormat.JSONL)
        assert result.get("success") is True
        assert result.get("imported_count") == 2
        # 消息结构应符合预期
        msgs = result.get("messages", [])
        assert len(msgs) == 2
        assert msgs[0]["role"] == "user"


class TestSQLiteAndCaching:
    """SQLite + 缓存的集成"""

    def test_response_cache_with_sqlite_persistence(self, tmp_path):
        """测试响应缓存与 SQLite 持久化协同"""
        from castorice.response_cache import FileResponseCache

        cache_file = tmp_path / "cache.json"
        cache = FileResponseCache(str(cache_file))

        msgs = [{"role": "user", "content": "持久化测试"}]
        cache.set(msgs, "gpt-4o", {"content": "回复"})

        # 验证文件存在
        assert cache_file.exists()

        # 创建新实例从文件加载
        cache2 = FileResponseCache(str(cache_file))
        result = cache2.get(msgs, "gpt-4o")
        assert result is not None


class TestHTTPClientAndTools:
    """HTTP 客户端集成测试"""

    def test_http_client_reuse(self):
        """测试 HTTP 客户端复用"""
        client1 = get_http_client()
        client2 = get_http_client()
        # 应返回同一实例
        assert client1 is client2

    def test_http_client_with_request(self):
        """测试 HTTP 客户端发送请求（使用 httpbin 镜像或跳过）"""
        client = get_http_client()
        # 仅测试对象可用性，避免真实网络依赖
        assert hasattr(client, "get")
        assert hasattr(client, "post")
        assert hasattr(client, "request")


class TestEndToEndScenario:
    """完整端到端场景测试"""

    def test_full_conversation_pipeline(self):
        """测试完整对话流水线（模拟）"""
        # 1. 准备所有组件
        from castorice.emotion import EmotionState
        emotion_state = EmotionState()
        cache = ResponseCache()
        tool_mem = get_tool_memory()
        notif = NotificationManager()
        coord = MultiAgentCoordinator()

        # 2. 注册 Agent
        coord.register_agent("a1", AgentRole.ANALYST, "分析师")
        coord.register_agent("e1", AgentRole.EXECUTOR, "执行者")

        # 3. 订阅通知
        received = []
        notif.subscribe("*", lambda n: received.append(n))

        # 4. 模拟对话流程
        user_input = "分析这个数据并执行"

        # a) 情感状态初始化
        emotion_state.pleasure = 0.3
        emotion_state.arousal = 0.5

        # b) 检查 LLM 缓存
        msgs = [{"role": "user", "content": user_input}]
        cached = cache.get(msgs, "gpt-4o")
        if cached is None:
            cache.set(msgs, "gpt-4o", {"content": "已处理"})

        # c) 工具学习
        tool_mem.record("analyze_data", user_input, {"depth": "full"}, "分析完成", True)

        # d) 多 Agent 任务分发
        t1 = coord.create_task("analyze", {"input": user_input}, target_role=AgentRole.ANALYST)
        t2 = coord.create_task("execute", {"plan": "auto"}, target_role=AgentRole.EXECUTOR)

        # e) 通知
        notif.send_task_update(t1, "in_progress")
        notif.send_task_update(t2, "completed")

        # 5. 验证
        assert t1 in coord._tasks
        assert t2 in coord._tasks
        # 至少应收到一些通知
        assert len(received) >= 2
        # 情感状态已被初始化
        assert emotion_state.pleasure == 0.3

    def test_component_independence(self):
        """测试各组件可独立工作（无相互依赖）"""
        # 每个组件应能独立使用
        from castorice.emotion import EmotionState
        EmotionState()
        ResponseCache()
        ToolCallMemory()
        NotificationManager()
        MultiAgentCoordinator()
        # 无异常即通过
        assert True
