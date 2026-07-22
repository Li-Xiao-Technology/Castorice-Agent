"""
P2 多 Agent 协作框架测试
"""
import pytest
from castorice.multi_agent import (
    AgentRole,
    AgentInfo,
    CollaborationTask,
    MultiAgentCoordinator,
    RoleBasedCoordinator,
    get_multi_agent_coordinator,
)


class TestAgentRole:
    def test_roles_exist(self):
        """测试所有预定义角色存在"""
        assert AgentRole.ANALYST.value == "analyst"
        assert AgentRole.PLANNER.value == "planner"
        assert AgentRole.EXECUTOR.value == "executor"
        assert AgentRole.SUMMARIZER.value == "summarizer"
        assert AgentRole.COORDINATOR.value == "coordinator"
        assert AgentRole.GENERALIST.value == "generalist"


class TestAgentInfo:
    def test_default_values(self):
        """测试默认值"""
        info = AgentInfo(agent_id="a1", role=AgentRole.ANALYST, name="分析师")
        assert info.status == "idle"
        assert info.task_count == 0
        assert info.last_active == 0.0


class TestMultiAgentCoordinator:
    def test_register_agent(self):
        """测试注册 Agent"""
        coord = MultiAgentCoordinator()
        coord.register_agent("a1", AgentRole.ANALYST, "分析师")
        assert "a1" in coord._agents
        assert coord._agents["a1"].role == AgentRole.ANALYST

    def test_register_duplicate_id_overwrites(self):
        """测试重复 ID 覆盖"""
        coord = MultiAgentCoordinator()
        coord.register_agent("a1", AgentRole.ANALYST, "旧名")
        coord.register_agent("a1", AgentRole.PLANNER, "新名")
        assert coord._agents["a1"].role == AgentRole.PLANNER

    def test_unregister_agent(self):
        """测试注销 Agent"""
        coord = MultiAgentCoordinator()
        coord.register_agent("a1", AgentRole.ANALYST, "分析师")
        coord.unregister_agent("a1")
        assert "a1" not in coord._agents

    def test_create_task(self):
        """测试创建任务"""
        coord = MultiAgentCoordinator()
        coord.register_agent("a1", AgentRole.ANALYST, "分析师")
        task_id = coord.create_task("analysis", {"data": "x"}, target_role=AgentRole.ANALYST)
        assert task_id is not None
        assert task_id in coord._tasks
        task = coord._tasks[task_id]
        assert task.type == "analysis"
        # 应自动分配到匹配的 Agent
        assert task.assigned_to == "a1"
        assert task.status == "in_progress"

    def test_create_task_without_target(self):
        """测试无目标角色创建任务"""
        coord = MultiAgentCoordinator()
        task_id = coord.create_task("general", {"x": 1})
        assert coord._tasks[task_id].status == "pending"
        assert coord._tasks[task_id].assigned_to is None

    def test_send_and_receive_messages(self):
        """测试消息发送与接收"""
        coord = MultiAgentCoordinator()
        coord.register_agent("a1", AgentRole.ANALYST, "分析师")
        coord.register_agent("a2", AgentRole.PLANNER, "规划师")
        coord.send_message("a1", "a2", {"type": "request", "data": "hello"})
        msgs = coord.receive_messages("a2")
        assert len(msgs) == 1
        assert msgs[0]["message"]["data"] == "hello"

    def test_broadcast(self):
        """测试广播消息"""
        coord = MultiAgentCoordinator()
        coord.register_agent("a1", AgentRole.ANALYST, "分析师")
        coord.register_agent("a2", AgentRole.PLANNER, "规划师")
        coord.register_agent("a3", AgentRole.EXECUTOR, "执行者")
        coord.broadcast("a1", {"data": "广播消息"}, exclude_self=True)
        msgs_a2 = coord.receive_messages("a2")
        msgs_a3 = coord.receive_messages("a3")
        assert len(msgs_a2) == 1
        assert len(msgs_a3) == 1

    def test_assign_task(self):
        """测试任务分配"""
        coord = MultiAgentCoordinator()
        coord.register_agent("a1", AgentRole.ANALYST, "分析师")
        task_id = coord.create_task("test", {})  # 不自动分配
        result = coord.assign_task(task_id, "a1")
        assert result is True
        assert coord._tasks[task_id].status == "in_progress"

    def test_complete_task(self):
        """测试完成任务"""
        coord = MultiAgentCoordinator()
        coord.register_agent("a1", AgentRole.ANALYST, "分析师")
        task_id = coord.create_task("test", {}, target_role=AgentRole.ANALYST)
        coord.complete_task(task_id, {"result": "ok"})
        assert coord._tasks[task_id].status == "completed"
        assert coord._agents["a1"].status == "idle"

    def test_get_agents_by_role(self):
        """测试按角色获取 Agent"""
        coord = MultiAgentCoordinator()
        coord.register_agent("a1", AgentRole.ANALYST, "A1")
        coord.register_agent("a2", AgentRole.ANALYST, "A2")
        coord.register_agent("a3", AgentRole.PLANNER, "P1")
        analysts = coord.get_agents_by_role(AgentRole.ANALYST)
        assert len(analysts) == 2

    def test_get_available_agents(self):
        """测试获取可用 Agent"""
        coord = MultiAgentCoordinator()
        coord.register_agent("a1", AgentRole.ANALYST, "A1")
        agents = coord.get_available_agents()
        assert len(agents) == 1
        assert agents[0].status == "idle"

    def test_get_pending_tasks(self):
        """测试获取待处理任务"""
        coord = MultiAgentCoordinator()
        coord.register_agent("a1", AgentRole.ANALYST, "A1")
        coord.create_task("test1", {})  # 无目标角色 -> pending
        coord.create_task("test2", {}, target_role=AgentRole.ANALYST)  # 自动分配
        pending = coord.get_pending_tasks()
        assert len(pending) >= 1

    def test_get_status(self):
        """测试获取状态"""
        coord = MultiAgentCoordinator()
        coord.register_agent("a1", AgentRole.ANALYST, "分析师")
        status = coord.get_status()
        assert "agents" in status
        assert "tasks" in status
        assert "pending_messages" in status
        assert "a1" in status["agents"]


class TestRoleBasedCoordinator:
    def test_analyze(self):
        """测试分析任务分配"""
        coord = MultiAgentCoordinator()
        coord.register_agent("a1", AgentRole.ANALYST, "分析师")
        rbc = RoleBasedCoordinator(coord)
        result = rbc.analyze("分析此问题", {"context": "test"})
        assert "task_id" in result
        assert result["status"] == "analyzing"

    def test_analyze_no_analyst(self):
        """测试无分析师时的处理"""
        coord = MultiAgentCoordinator()
        rbc = RoleBasedCoordinator(coord)
        result = rbc.analyze("分析问题")
        assert "error" in result

    def test_plan(self):
        """测试规划任务分配"""
        coord = MultiAgentCoordinator()
        coord.register_agent("p1", AgentRole.PLANNER, "规划师")
        rbc = RoleBasedCoordinator(coord)
        result = rbc.plan("实现目标X")
        assert "task_id" in result
        assert result["status"] == "planning"

    def test_execute(self):
        """测试执行任务分配"""
        coord = MultiAgentCoordinator()
        coord.register_agent("e1", AgentRole.EXECUTOR, "执行者")
        rbc = RoleBasedCoordinator(coord)
        result = rbc.execute({"steps": [1, 2, 3]})
        assert "task_id" in result
        assert result["status"] == "executing"


class TestMultiAgentSingleton:
    def test_singleton(self):
        """测试全局单例"""
        c1 = get_multi_agent_coordinator()
        c2 = get_multi_agent_coordinator()
        assert c1 is c2
