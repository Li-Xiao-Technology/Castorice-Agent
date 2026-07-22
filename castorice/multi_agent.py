"""
多 Agent 协作框架

支持多个 Castorice Agent 之间的协同工作：
- 任务分发与负载均衡
- 消息传递与通信
- 角色分工（分析师/规划师/执行者/总结者）
- 对话路由与转发
"""

import json
import logging
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Callable

logger = logging.getLogger("Castorice.MultiAgent")


class AgentRole(Enum):
    ANALYST = "analyst"
    PLANNER = "planner"
    EXECUTOR = "executor"
    SUMMARIZER = "summarizer"
    COORDINATOR = "coordinator"
    GENERALIST = "generalist"


@dataclass
class AgentInfo:
    agent_id: str
    role: AgentRole
    name: str
    status: str = "idle"
    last_active: float = 0.0
    task_count: int = 0


@dataclass
class CollaborationTask:
    task_id: str
    type: str
    payload: Dict[str, Any]
    priority: int = 0
    assigned_to: Optional[str] = None
    status: str = "pending"
    created_at: float = field(default_factory=lambda: time.time())
    updated_at: float = field(default_factory=lambda: time.time())


class MultiAgentCoordinator:
    """多 Agent 协作协调器"""

    def __init__(self):
        self._agents: Dict[str, AgentInfo] = {}
        self._tasks: Dict[str, CollaborationTask] = {}
        self._message_queue: List[Dict[str, Any]] = []
        self._lock = threading.Lock()
        self._task_counter = 0

    def register_agent(self, agent_id: str, role: AgentRole, name: str = "") -> None:
        """注册一个 Agent"""
        with self._lock:
            self._agents[agent_id] = AgentInfo(
                agent_id=agent_id,
                role=role,
                name=name or agent_id,
                status="idle",
                last_active=time.time(),
            )
        logger.info(f"Agent 注册: {agent_id} ({role.value})")

    def unregister_agent(self, agent_id: str) -> None:
        """注销一个 Agent"""
        with self._lock:
            if agent_id in self._agents:
                del self._agents[agent_id]
        logger.info(f"Agent 注销: {agent_id}")

    def get_agents_by_role(self, role: AgentRole) -> List[AgentInfo]:
        """按角色获取 Agent 列表"""
        with self._lock:
            return [a for a in self._agents.values() if a.role == role]

    def get_available_agents(self) -> List[AgentInfo]:
        """获取可用的 Agent 列表"""
        with self._lock:
            return [a for a in self._agents.values() if a.status == "idle"]

    def create_task(
        self,
        task_type: str,
        payload: Dict[str, Any],
        priority: int = 0,
        target_role: Optional[AgentRole] = None,
    ) -> str:
        """创建协作任务"""
        with self._lock:
            self._task_counter += 1
            task_id = f"task_{self._task_counter}_{int(time.time())}"

            task = CollaborationTask(
                task_id=task_id,
                type=task_type,
                payload=payload,
                priority=priority,
                status="pending",
            )
            self._tasks[task_id] = task

        # 修复：不在持锁状态下调用 get_agents_by_role，避免死锁
        if target_role:
            agents = [a for a in self._agents.values() if a.role == target_role]
            if agents:
                with self._lock:
                    agent = min(agents, key=lambda a: a.task_count)
                    task.assigned_to = agent.agent_id
                    task.status = "in_progress"
                    agent.status = "busy"
                    agent.task_count += 1

        logger.info(f"任务创建: {task_id} ({task_type})")
        return task_id

    def assign_task(self, task_id: str, agent_id: str) -> bool:
        """分配任务给指定 Agent"""
        with self._lock:
            if task_id not in self._tasks:
                return False
            if agent_id not in self._agents:
                return False
            
            task = self._tasks[task_id]
            agent = self._agents[agent_id]
            
            if task.status != "pending":
                return False
            if agent.status != "idle":
                return False
            
            task.assigned_to = agent_id
            task.status = "in_progress"
            agent.status = "busy"
            agent.task_count += 1
            task.updated_at = time.time()
        
        return True

    def complete_task(self, task_id: str, result: Dict[str, Any]) -> None:
        """标记任务完成"""
        with self._lock:
            if task_id not in self._tasks:
                return
            
            task = self._tasks[task_id]
            task.status = "completed"
            task.payload["result"] = result
            task.updated_at = time.time()
            
            if task.assigned_to and task.assigned_to in self._agents:
                agent = self._agents[task.assigned_to]
                agent.status = "idle"
                agent.last_active = time.time()
        
        logger.info(f"任务完成: {task_id}")

    def get_pending_tasks(self) -> List[CollaborationTask]:
        """获取待处理任务"""
        with self._lock:
            return [t for t in self._tasks.values() if t.status == "pending"]

    def send_message(self, sender_id: str, receiver_id: str, message: Dict[str, Any]) -> None:
        """发送消息给另一个 Agent"""
        with self._lock:
            self._message_queue.append({
                "sender_id": sender_id,
                "receiver_id": receiver_id,
                "message": message,
                "timestamp": time.time(),
            })
        
        logger.debug(f"消息发送: {sender_id} -> {receiver_id}")

    def receive_messages(self, agent_id: str) -> List[Dict[str, Any]]:
        """接收发给指定 Agent 的消息"""
        with self._lock:
            messages = [m for m in self._message_queue if m["receiver_id"] == agent_id]
            self._message_queue = [m for m in self._message_queue if m["receiver_id"] != agent_id]
        
        return messages

    def broadcast(self, sender_id: str, message: Dict[str, Any], exclude_self: bool = True) -> None:
        """广播消息给所有 Agent"""
        with self._lock:
            for agent_id in self._agents:
                if exclude_self and agent_id == sender_id:
                    continue
                self._message_queue.append({
                    "sender_id": sender_id,
                    "receiver_id": agent_id,
                    "message": message,
                    "timestamp": time.time(),
                })

    def get_status(self) -> Dict[str, Any]:
        """获取协作框架状态"""
        with self._lock:
            return {
                "agents": {k: {
                    "role": v.role.value,
                    "name": v.name,
                    "status": v.status,
                    "task_count": v.task_count,
                } for k, v in self._agents.items()},
                "tasks": {k: {
                    "type": v.type,
                    "status": v.status,
                    "assigned_to": v.assigned_to,
                    "priority": v.priority,
                } for k, v in self._tasks.items()},
                "pending_messages": len(self._message_queue),
            }


class RoleBasedCoordinator:
    """基于角色的协作协调器"""

    def __init__(self, coordinator: MultiAgentCoordinator):
        self.coordinator = coordinator

    def analyze(self, query: str, context: Dict[str, Any] = None) -> Dict[str, Any]:
        """交给分析师 Agent 分析"""
        analysts = self.coordinator.get_agents_by_role(AgentRole.ANALYST)
        if not analysts:
            return {"error": "没有可用的分析师 Agent"}

        task_id = self.coordinator.create_task(
            task_type="analyze",
            payload={"query": query, "context": context or {}},
            priority=1,
            target_role=AgentRole.ANALYST,
        )
        return {"task_id": task_id, "status": "analyzing"}

    def plan(self, goal: str, constraints: Dict[str, Any] = None) -> Dict[str, Any]:
        """交给规划师 Agent 制定计划"""
        planners = self.coordinator.get_agents_by_role(AgentRole.PLANNER)
        if not planners:
            return {"error": "没有可用的规划师 Agent"}

        task_id = self.coordinator.create_task(
            task_type="plan",
            payload={"goal": goal, "constraints": constraints or {}},
            priority=2,
            target_role=AgentRole.PLANNER,
        )
        return {"task_id": task_id, "status": "planning"}

    def execute(self, plan: Dict[str, Any]) -> Dict[str, Any]:
        """交给执行者 Agent 执行"""
        executors = self.coordinator.get_agents_by_role(AgentRole.EXECUTOR)
        if not executors:
            return {"error": "没有可用的执行者 Agent"}

        task_id = self.coordinator.create_task(
            task_type="execute",
            payload={"plan": plan},
            priority=3,
            target_role=AgentRole.EXECUTOR,
        )
        return {"task_id": task_id, "status": "executing"}

    def summarize(self, results: List[Dict[str, Any]], context: Dict[str, Any] = None) -> Dict[str, Any]:
        """交给总结者 Agent 总结"""
        summarizers = self.coordinator.get_agents_by_role(AgentRole.SUMMARIZER)
        if not summarizers:
            return {"error": "没有可用的总结者 Agent"}

        task_id = self.coordinator.create_task(
            task_type="summarize",
            payload={"results": results, "context": context or {}},
            priority=1,
            target_role=AgentRole.SUMMARIZER,
        )
        return {"task_id": task_id, "status": "summarizing"}


_multi_agent_coordinator = None


def get_multi_agent_coordinator() -> MultiAgentCoordinator:
    """获取全局多 Agent 协作协调器单例"""
    global _multi_agent_coordinator
    if _multi_agent_coordinator is None:
        _multi_agent_coordinator = MultiAgentCoordinator()
    return _multi_agent_coordinator
