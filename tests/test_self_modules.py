"""
自感知、自组织、元认知模块测试（无需 pytest，可直接运行）
"""

import sys
import traceback

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


def assert_true(condition, msg):
    if not condition:
        raise AssertionError(msg)


def test_self_awareness():
    print("\n=== 自感知模块测试 ===")

    # 初始状态
    sa = SelfAwareness()
    stats = sa.get_stats()
    assert_true(stats["agent"]["total_calls"] == 0, "初始调用次数应为0")
    assert_true(stats["agent"]["total_tasks"] == 0, "初始任务数应为0")
    print("1. 初始状态 - PASS")

    # 记录 LLM 调用
    sa.record_llm_call(prompt_tokens=10, completion_tokens=5, latency_ms=100)
    stats = sa.get_stats()
    assert_true(stats["agent"]["total_calls"] == 1, "调用次数记录错误")
    assert_true(stats["agent"]["prompt_tokens"] == 10, "prompt tokens 记录错误")
    assert_true(stats["agent"]["completion_tokens"] == 5, "completion tokens 记录错误")
    print("2. LLM 调用记录 - PASS")

    # 记录工具调用
    sa.record_tool_call("web_search", success=True, latency_ms=200)
    sa.record_tool_call("web_search", success=False, error_msg="timeout")
    stats = sa.get_stats()
    assert_true(stats["tools"]["web_search"]["call_count"] == 2, "工具调用次数错误")
    assert_true(stats["tools"]["web_search"]["success_rate"] == 0.5, "工具成功率错误")
    print("3. 工具调用记录 - PASS")

    # 健康检查
    health = sa.health_check()
    assert_true(health["status"] == "healthy", "初始健康状态应为 healthy")
    assert_true(health["score"] == 100, "初始健康评分应为100")
    print("4. 健康检查 - PASS")

    # 能力边界
    can_handle, confidence, reason = sa.can_handle("你好")
    assert_true(can_handle is True, "简单闲聊应可处理")
    assert_true(confidence >= 0.8, "简单闲聊置信度应高")
    print("5. 能力边界判断 - PASS")

    # 资源感知
    sa2 = SelfAwareness(model_name="gpt-4o")
    sa2.record_llm_call(prompt_tokens=1000, completion_tokens=500)
    resource = sa2.get_resource_state()
    assert_true(resource["context_limit"] == 128000, "gpt-4o 上下文限制错误")
    assert_true(resource["current_total_tokens"] == 1500, "token 统计错误")
    print("6. 资源感知 - PASS")

    # 能力画像
    profile = CapabilityProfile()
    profile.record_task("搜索最新新闻", success=True, elapsed_ms=1000)
    profile.record_task("今天天气怎么样", success=True, elapsed_ms=500)
    profile.record_task("搜索股票", success=False, elapsed_ms=2000)
    p = profile.get_profile()
    assert_true("search" in p, "应识别为 search 类型")
    assert_true(p["search"]["count"] == 2, "search 计数错误")
    print("7. 能力画像 - PASS")

    # 状态模型
    sm = StateModel()
    sm.record_call(error=False)
    sm.record_call(error=True)
    state = sm.get_state()
    assert_true(state["consecutive_errors"] == 1, "连续错误计数错误")
    assert_true(state["recent_error_rate"] == 0.5, "近期错误率错误")
    print("8. 状态模型 - PASS")


def test_self_organization():
    print("\n=== 自组织模块测试 ===")

    # 任务规划依赖
    plan = TaskPlan(original_task="并行测试", subtasks=[
        SubTask(id=1, description="A"),
        SubTask(id=2, description="B"),
        SubTask(id=3, description="C", depends_on=[1, 2]),
    ])
    ready = plan.get_ready_subtasks()
    assert_true(len(ready) == 2, "初始可执行任务数错误")
    ready[0].status = "completed"
    ready[1].status = "completed"
    ready2 = plan.get_ready_subtasks()
    assert_true(len(ready2) == 1, "依赖满足后可执行任务数错误")
    assert_true(ready2[0].id == 3, "依赖任务 id 错误")
    print("1. 任务规划依赖 - PASS")

    # 串行执行
    tools = {"dummy": DummyTool("dummy")}
    executor = TaskExecutor(tools=tools, max_workers=2)
    plan = TaskPlan(original_task="测试", subtasks=[
        SubTask(id=1, description="执行A", tool="dummy"),
        SubTask(id=2, description="执行B", tool="dummy", depends_on=[1]),
    ])
    result = executor.execute(plan, parallel=False)
    assert_true(result.subtasks[0].status == "completed", "串行子任务1应完成")
    assert_true(result.subtasks[1].status == "completed", "串行子任务2应完成")
    print("2. 串行任务执行 - PASS")

    # 并行执行
    plan2 = TaskPlan(original_task="并行测试", subtasks=[
        SubTask(id=1, description="A", tool="dummy"),
        SubTask(id=2, description="B", tool="dummy"),
    ])
    result2 = executor.execute(plan2, parallel=True)
    assert_true(all(s.status == "completed" for s in result2.subtasks), "并行子任务应全部完成")
    print("3. 并行任务执行 - PASS")

    # 思维策略
    key, prompt = ThinkingStrategySelector.select("分析一下这个问题的原因")
    assert_true(key == "analytical", "应选分析型思维")
    assert_true("分析" in prompt, "提示词应包含分析")
    key2, _ = ThinkingStrategySelector.select("推荐哪个方案更好")
    assert_true(key2 == "decision", "应选决策型思维")
    print("4. 思维策略选择 - PASS")

    # 对话策略
    class FakeProfile:
        data = {"stats": {"total_interactions": 2}}

    adj = DialogueStrategy.adjust_prompt("详细说明一下", FakeProfile(), 3)
    assert_true("详细" in adj, "对话策略应识别详细要求")
    print("5. 对话策略调整 - PASS")

    # 错误恢复
    assert_true(ErrorRecoveryStrategy.should_retry("web_search", 1) is True, "web_search 应允许重试1次")
    assert_true(ErrorRecoveryStrategy.should_retry("web_search", 5) is False, "web_search 超过重试次数")
    assert_true(ErrorRecoveryStrategy.get_retry_delay("web_search", 1) == 2.0, "重试延迟计算错误")
    print("6. 错误恢复策略 - PASS")

    # 动态工作流
    selector = DynamicWorkflowSelector()
    steps = selector.select("hard", "task", has_tool_calls=True)
    assert_true("intent" in steps, "工作流应包含 intent")
    assert_true("answer" in steps, "工作流应包含 answer")
    print("7. 动态工作流选择 - PASS")


def test_metacognition():
    print("\n=== 元认知模块测试 ===")

    meta = Metacognition()

    # 置信度评估（有工具证据）
    assessment = meta.assess_confidence(
        answer="今天的天气是25度",
        tool_results=["北京今天晴，25°C"],
        has_tools=True,
    )
    assert_true(assessment.overall_score > 0.5, "有工具证据时置信度应较高")
    print("1. 置信度评估（有证据） - PASS")

    # 幻觉风险
    assessment2 = meta.assess_confidence(
        answer="这个数字一定是100%，毫无疑问",
        tool_results=[],
        has_tools=True,
    )
    assert_true(assessment2.hallucination_risk == "high", "应识别高幻觉风险")
    print("2. 幻觉风险检测 - PASS")

    # 一致性
    result = meta.check_consistency("答案是25", ["答案是25"])
    assert_true(result["consistent"] is True, "一致回答应判断为一致")
    print("3. 一致性检测 - PASS")

    # 回答质量
    quality = meta.assess_quality("这是回答。\n1. 第一点\n2. 第二点", "请分析", tool_results=["data"])
    assert_true(quality.score >= 50, "结构化回答质量分应较高")
    print("4. 回答质量评估 - PASS")

    # 综合反思
    result = meta.reflect("今天天气如何？", "今天北京晴，25度", tool_results=["北京晴 25°C"])
    assert_true("confidence" in result, "反思结果应包含 confidence")
    assert_true("quality" in result, "反思结果应包含 quality")
    assert_true("consistency" in result, "反思结果应包含 consistency")
    print("5. 综合反思 - PASS")


def main():
    tests = [test_self_awareness, test_self_organization, test_metacognition]
    passed = 0
    failed = 0
    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            failed += 1
            print(f"\n[FAIL] {test.__name__}: {e}")
            traceback.print_exc()

    print("\n" + "=" * 40)
    print(f"  通过: {passed}, 失败: {failed}")
    print("=" * 40)
    return failed == 0


if __name__ == "__main__":
    ok = main()
    sys.exit(0 if ok else 1)
