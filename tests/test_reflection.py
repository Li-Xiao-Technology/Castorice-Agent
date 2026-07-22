"""
反思引擎测试

使用 pytest 风格（assert + def test_*）。
"""

import os
import tempfile

import pytest

from castorice.reflection import (
    ReflectionResult,
    ReflectionEngine,
    ActionItem,
    ActionQueue,
    _parse_reflection_json,
)


class TestParseReflectionJson:
    """JSON 解析容错测试"""

    def test_valid_json(self):
        raw = '{"patterns_observed": ["p1"], "growth_insights": ["i1"]}'
        parsed = _parse_reflection_json(raw)
        assert parsed["patterns_observed"] == ["p1"]

    def test_json_block(self):
        raw = '```json\n{"patterns_observed": ["p1"]}\n```'
        parsed = _parse_reflection_json(raw)
        assert parsed["patterns_observed"] == ["p1"]

    def test_invalid_returns_empty(self):
        parsed = _parse_reflection_json("not json")
        assert parsed == {}


class TestReflectionResult:
    """ReflectionResult 数据类测试"""

    def test_default_values(self):
        r = ReflectionResult()
        assert r.patterns_observed == []
        assert r.self_concept_updated is False
        assert r.next_actions == []

    def test_to_dict(self):
        r = ReflectionResult(
            patterns_observed=["p1"],
            self_concept_updated=True,
            update_reason="test",
        )
        d = r.to_dict()
        assert d["patterns_observed"] == ["p1"]
        assert d["self_concept_updated"] is True


class FakeExperience:
    """模拟经历条目"""
    def __init__(self, content="", memory_type="episodic", importance=5.0,
                 emotional_valence=0.0, timestamp="", metadata=None):
        self.content = content
        self.memory_type = memory_type
        self.importance = importance
        self.emotional_valence = emotional_valence
        self.timestamp = timestamp
        self.metadata = metadata or {}


class FakeJournal:
    """模拟经历流"""
    def __init__(self, experiences=None):
        self.experiences = experiences or []

    def get_recent(self, limit=30):
        return self.experiences[:limit]

    def add_simple(self, **kwargs):
        self.experiences.append(FakeExperience(content=kwargs.get("content", "")))


class FakeSelfConcept:
    """模拟自我概念"""
    def __init__(self, content=""):
        self._content = content

    def load(self):
        return self._content

    def update(self, content, reason=""):
        self._content = content


class FakeModelAdapter:
    """模拟模型适配器"""
    def __init__(self, response_content="{}"):
        self._response = response_content

    def chat(self, messages):
        class FakeResponse:
            content = self._response
        return FakeResponse()


class TestReflectionEngine:
    """ReflectionEngine 测试"""

    def test_should_reflect_significant_event(self):
        engine = ReflectionEngine(
            model_adapter=FakeModelAdapter(),
            experience_journal=FakeJournal(),
            self_concept=FakeSelfConcept(),
        )
        should, reason = engine.should_reflect(significant_event=True)
        assert should is True
        assert "重要情感事件" in reason

    def test_should_reflect_task_failure(self):
        engine = ReflectionEngine(
            model_adapter=FakeModelAdapter(),
            experience_journal=FakeJournal(),
            self_concept=FakeSelfConcept(),
        )
        should, reason = engine.should_reflect(task_success=False)
        assert should is True
        assert "任务失败" in reason

    def test_should_reflect_low_confidence(self):
        engine = ReflectionEngine(
            model_adapter=FakeModelAdapter(),
            experience_journal=FakeJournal(),
            self_concept=FakeSelfConcept(),
            reflection_confidence_threshold=0.5,
        )
        should, reason = engine.should_reflect(confidence=0.3)
        assert should is True
        assert "置信度过低" in reason

    def test_should_not_reflect(self):
        engine = ReflectionEngine(
            model_adapter=FakeModelAdapter(),
            experience_journal=FakeJournal(),
            self_concept=FakeSelfConcept(),
        )
        should, reason = engine.should_reflect(
            turn_completed=True, confidence=1.0, significant_event=False, task_success=True
        )
        assert should is False
        assert reason == ""

    def test_reflect_empty_journal(self):
        engine = ReflectionEngine(
            model_adapter=FakeModelAdapter(),
            experience_journal=FakeJournal(),
            self_concept=FakeSelfConcept(),
        )
        result = engine.reflect()
        assert result.patterns_observed == []

    def test_reflect_with_llm_response(self):
        # 注意：JSON 字符串值中不能包含未转义的换行符，使用 \\n 作为 JSON 转义
        raw_response = (
            '{"patterns_observed": ["用户经常询问技术问题"], '
            '"emotional_tendencies": ["保持冷静"], '
            '"growth_insights": ["需要提高技术深度"], '
            '"self_concept_update": {"should_update": true, "new_sections": "# 我的技术能力\\n\\n我擅长回答编程问题。", "update_reason": "test"}, '
            '"next_actions": ["学习更多技术知识"]}'
        )
        engine = ReflectionEngine(
            model_adapter=FakeModelAdapter(response_content=raw_response),
            experience_journal=FakeJournal([FakeExperience(content="test")]),
            self_concept=FakeSelfConcept(),
        )
        result = engine.reflect()
        assert result.patterns_observed == ["用户经常询问技术问题"]
        assert result.self_concept_updated is True
        assert "学习更多技术知识" in result.next_actions

    def test_get_status(self):
        engine = ReflectionEngine(
            model_adapter=FakeModelAdapter(),
            experience_journal=FakeJournal(),
            self_concept=FakeSelfConcept(),
        )
        status = engine.get_status()
        assert status["turns_since_last_reflection"] == 0
        assert status["interval_turns"] == 10

    def test_get_recent_signal_empty(self):
        engine = ReflectionEngine(
            model_adapter=FakeModelAdapter(),
            experience_journal=FakeJournal(),
            self_concept=FakeSelfConcept(),
        )
        signal = engine.get_recent_signal()
        assert signal == ""

    def test_get_recent_signal_with_reflective(self):
        journal = FakeJournal([
            FakeExperience(content="反思: 学到了很多", memory_type="reflective", timestamp="2024-01-01T00:00:00"),
        ])
        engine = ReflectionEngine(
            model_adapter=FakeModelAdapter(),
            experience_journal=journal,
            self_concept=FakeSelfConcept(),
        )
        signal = engine.get_recent_signal()
        assert "反思" in signal


class TestActionQueue:
    """ActionQueue 测试"""

    def test_add_and_get_highest(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "actions.db")
            queue = ActionQueue(db_path=path)
            queue.add_action("测试行动", priority=0.9, trigger_reason="test")
            item = queue.get_highest_priority()
            assert item is not None
            assert item.description == "测试行动"
            assert item.priority == pytest.approx(0.9)
            queue.close()

    def test_mark_executed(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "actions.db")
            queue = ActionQueue(db_path=path)
            queue.add_action("行动A", priority=0.9)
            queue.add_action("行动B", priority=0.5)
            item = queue.get_highest_priority()
            queue.mark_executed(item.action_id, "执行成功")
            # 标记完成后，最高优先级应变为行动B
            next_item = queue.get_highest_priority()
            assert next_item is not None
            assert next_item.description == "行动B"
            queue.close()

    def test_to_prompt(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "actions.db")
            queue = ActionQueue(db_path=path)
            queue.add_action("行动1", priority=0.8)
            queue.add_action("行动2", priority=0.5)
            prompt = queue.to_prompt(max_actions=3)
            assert "行动1" in prompt
            assert "行动2" in prompt
            queue.close()

    def test_add_from_reflection(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "actions.db")
            queue = ActionQueue(db_path=path)
            result = ReflectionResult(
                next_actions=["行动A", "行动B"],
                trigger_reason="反思触发",
            )
            added = queue.add_from_reflection(result)
            assert added == 2
            item = queue.get_highest_priority()
            assert item.description == "行动A"
            queue.close()

    def test_get_highest_priority_empty(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "actions.db")
            queue = ActionQueue(db_path=path)
            item = queue.get_highest_priority()
            assert item is None
            queue.close()

    def test_action_item_to_dict(self):
        item = ActionItem(action_id="test1", description="desc", priority=0.7)
        d = item.to_dict()
        assert d["action_id"] == "test1"
        assert d["description"] == "desc"
        assert d["priority"] == pytest.approx(0.7)

    def test_action_item_from_dict(self):
        d = {
            "action_id": "test1",
            "description": "desc",
            "priority": 0.7,
            "status": "pending",
            "trigger_reason": "test",
            "created_at": "",
            "executed_at": "",
            "result": "",
        }
        item = ActionItem.from_dict(d)
        assert item.action_id == "test1"
        assert item.status == "pending"
