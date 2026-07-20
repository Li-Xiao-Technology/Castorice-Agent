"""
自感知、自组织、元认知模块测试（pytest 风格）
"""

import pytest

from castorice.self_awareness import SelfAwareness, CapabilityProfile, StateModel
from castorice.self_organization import (
    TaskPlanner, TaskPlan, SubTask,
    TaskExecutor, ThinkingStrategySelector, DialogueStrategy,
    ErrorRecoveryStrategy, DynamicWorkflowSelector,
)
from castorice.metacognition import Metacognition


class DummyTool:
    """模拟工具，用于测试"""

    def __init__(self, name: str, description: str = ""):
        self.name = name
        self.description = description or f"dummy tool {name}"

    def invoke(self, args):
        return f"[{self.name}] result for {args}"


class TestSelfAwareness:
    """自感知模块测试"""

    def test_initial_state(self):
        sa = SelfAwareness()
        stats = sa.get_stats()
        assert stats["agent"]["total_calls"] == 0
        assert stats["agent"]["total_tasks"] == 0

    def test_record_llm_call(self):
        sa = SelfAwareness()
        sa.record_llm_call(prompt_tokens=10, completion_tokens=5, latency_ms=100)
        stats = sa.get_stats()
        assert stats["agent"]["total_calls"] == 1
        assert stats["agent"]["prompt_tokens"] == 10
        assert stats["agent"]["completion_tokens"] == 5

    def test_record_tool_call(self):
        sa = SelfAwareness()
        sa.record_tool_call("web_search", success=True, latency_ms=200)
        sa.record_tool_call("web_search", success=False, error_msg="timeout")
        stats = sa.get_stats()
        assert stats["tools"]["web_search"]["call_count"] == 2
        assert stats["tools"]["web_search"]["success_rate"] == pytest.approx(0.5)

    def test_health_check(self):
        sa = SelfAwareness()
        health = sa.health_check()
        assert health["status"] == "healthy"
        assert health["score"] == 100

    def test_can_handle_simple(self):
        sa = SelfAwareness()
        can_handle, confidence, reason = sa.can_handle("你好")
        assert can_handle is True
        assert confidence >= 0.8

    def test_resource_state(self):
        sa = SelfAwareness(model_name="gpt-4o")
        sa.record_llm_call(prompt_tokens=1000, completion_tokens=500)
        resource = sa.get_resource_state()
        assert resource["context_limit"] == 128000
        assert resource["current_total_tokens"] == 1500


class TestCapabilityProfile:
    """能力画像测试"""

    def test_profile(self):
        profile = CapabilityProfile()
        profile.record_task("搜索最新新闻", success=True, elapsed_ms=1000)
        profile.record_task("今天天气怎么样", success=True, elapsed_ms=500)
        profile.record_task("搜索股票", success=False, elapsed_ms=2000)
        p = profile.get_profile()
        assert "search" in p
        assert p["search"]["count"] == 2


class TestStateModel:
    """状态模型测试"""

    def test_state(self):
        sm = StateModel()
        sm.record_call(error=False)
        sm.record_call(error=True)
        state = sm.get_state()
        assert state["consecutive_errors"] == 1
        assert state["recent_error_rate"] == pytest.approx(0.5)


class TestSelfOrganization:
    """自组织模块测试"""

    def test_task_plan_dependencies(self):
        plan = TaskPlan(original_task="并行测试", subtasks=[
            SubTask(id=1, description="A"),
            SubTask(id=2, description="B"),
            SubTask(id=3, description="C", depends_on=[1, 2]),
        ])
        ready = plan.get_ready_subtasks()
        assert len(ready) == 2
        ready[0].status = "completed"
        ready[1].status = "completed"
        ready2 = plan.get_ready_subtasks()
        assert len(ready2) == 1
        assert ready2[0].id == 3

    def test_serial_execution(self):
        tools = {"dummy": DummyTool("dummy")}
        executor = TaskExecutor(tools=tools, max_workers=2)
        plan = TaskPlan(original_task="测试", subtasks=[
            SubTask(id=1, description="执行A", tool="dummy"),
            SubTask(id=2, description="执行B", tool="dummy", depends_on=[1]),
        ])
        result = executor.execute(plan, parallel=False)
        assert result.subtasks[0].status == "completed"
        assert result.subtasks[1].status == "completed"

    def test_parallel_execution(self):
        tools = {"dummy": DummyTool("dummy")}
        executor = TaskExecutor(tools=tools, max_workers=2)
        plan = TaskPlan(original_task="并行测试", subtasks=[
            SubTask(id=1, description="A", tool="dummy"),
            SubTask(id=2, description="B", tool="dummy"),
        ])
        result = executor.execute(plan, parallel=True)
        assert all(s.status == "completed" for s in result.subtasks)

    def test_thinking_strategy(self):
        selector = ThinkingStrategySelector()
        key, prompt = selector.select("分析一下这个问题的原因")
        assert key == "analytical"
        assert "分析" in prompt

    def test_dialogue_strategy(self):
        class FakeProfile:
            data = {"stats": {"total_interactions": 2}}

        adj = DialogueStrategy.adjust_prompt("详细说明一下", FakeProfile(), 3)
        assert "详细" in adj

    def test_error_recovery(self):
        assert ErrorRecoveryStrategy.should_retry("web_search", 1) is True
        assert ErrorRecoveryStrategy.should_retry("web_search", 5) is False
        assert ErrorRecoveryStrategy.get_retry_delay("web_search", 1) == pytest.approx(2.0)

    def test_dynamic_workflow(self):
        selector = DynamicWorkflowSelector()
        steps = selector.select("hard", "task", has_tool_calls=True)
        assert "intent" in steps
        assert "answer" in steps


class TestMetacognition:
    """元认知模块测试"""

    def test_confidence_with_evidence(self):
        meta = Metacognition()
        assessment = meta.assess_confidence(
            answer="今天的天气是25度",
            tool_results=["北京今天晴，25°C"],
            has_tools=True,
        )
        assert assessment.overall_score > 0.5

    def test_hallucination_risk(self):
        meta = Metacognition()
        assessment = meta.assess_confidence(
            answer="这个数字一定是100%，毫无疑问",
            tool_results=[],
            has_tools=True,
        )
        assert assessment.hallucination_risk == "high"

    def test_consistency(self):
        meta = Metacognition()
        result = meta.check_consistency("答案是25", ["答案是25"])
        assert result["consistent"] is True

    def test_quality(self):
        meta = Metacognition()
        quality = meta.assess_quality("这是回答。\n1. 第一点\n2. 第二点", "请分析", tool_results=["data"])
        assert quality.score >= 50

    def test_reflect(self):
        meta = Metacognition()
        result = meta.reflect("今天天气如何？", "今天北京晴，25度", tool_results=["北京晴 25°C"])
        assert "confidence" in result
        assert "quality" in result
        assert "consistency" in result
