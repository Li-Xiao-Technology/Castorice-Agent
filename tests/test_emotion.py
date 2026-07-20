"""
情感引擎测试

使用 pytest 风格（assert + def test_*）。
"""

import json
import os
import tempfile

import pytest

from castorice.emotion import (
    EmotionState,
    EmotionEngine,
    _heuristic_emotion_detection,
    _parse_emotion_json,
    PERSONALITY_PROMPT,
)


class TestEmotionState:
    """EmotionState 数据类测试"""

    def test_default_values(self):
        s = EmotionState()
        assert s.pleasure == 0.6
        assert s.arousal == 0.3
        assert s.dominance == 0.5
        assert s.interaction_count == 0

    def test_clamp(self):
        s = EmotionState(pleasure=1.5, arousal=-1.5, dominance=2.0)
        s.clamp()
        assert s.pleasure == 1.0
        assert s.arousal == -1.0
        assert s.dominance == 1.0

    def test_decay(self):
        s = EmotionState(pleasure=0.8, arousal=0.8, dominance=0.8)
        s.decay(factor=0.5)
        assert s.pleasure < 0.8
        assert s.arousal < 0.8
        assert s.dominance < 0.8

    def test_to_prompt_high_pleasure(self):
        s = EmotionState(pleasure=0.8, arousal=0.0, dominance=0.0)
        prompt = s.to_prompt()
        assert "开心" in prompt

    def test_to_prompt_low_pleasure(self):
        s = EmotionState(pleasure=-0.8, arousal=0.0, dominance=0.0)
        prompt = s.to_prompt()
        assert "难过" in prompt

    def test_to_dict_roundtrip(self):
        s = EmotionState(pleasure=0.1, arousal=0.2, dominance=0.3)
        d = s.to_dict()
        s2 = EmotionState.from_dict(d)
        assert s2.pleasure == pytest.approx(0.1)
        assert s2.arousal == pytest.approx(0.2)
        assert s2.dominance == pytest.approx(0.3)


class TestHeuristicEmotionDetection:
    """启发式情感检测测试"""

    def test_positive_input(self):
        result = _heuristic_emotion_detection("太好了，谢谢！", True)
        assert result["user_emotion_valence"] == "positive"
        assert result["is_significant_event"] is True

    def test_negative_input(self):
        result = _heuristic_emotion_detection("我很失望", True)
        assert result["user_emotion_valence"] == "negative"

    def test_strong_negative(self):
        result = _heuristic_emotion_detection("我崩溃了", True)
        assert result["user_emotion_valence"] == "negative"
        assert result["is_significant_event"] is True
        assert result["agent_pad_delta"][0] == pytest.approx(-0.5)

    def test_task_failure_impact(self):
        result = _heuristic_emotion_detection("普通输入", False)
        assert result["is_significant_event"] is True
        assert result["agent_pad_delta"][2] < 0  # dominance 下降

    def test_neutral_input(self):
        result = _heuristic_emotion_detection("请帮我查一下", True)
        assert result["user_emotion_valence"] == "neutral"
        assert result["is_significant_event"] is False


class TestParseEmotionJson:
    """JSON 解析容错测试"""

    def test_valid_json(self):
        raw = '{"agent_pad_delta": [0.1, 0.2, 0.3]}'
        parsed = _parse_emotion_json(raw)
        assert parsed["agent_pad_delta"] == [0.1, 0.2, 0.3]

    def test_json_block(self):
        raw = '```json\n{"agent_pad_delta": [0.1, 0.2, 0.3]}\n```'
        parsed = _parse_emotion_json(raw)
        assert parsed["agent_pad_delta"] == [0.1, 0.2, 0.3]

    def test_invalid_returns_empty(self):
        parsed = _parse_emotion_json("not json at all")
        assert parsed == {}


class TestEmotionEngine:
    """EmotionEngine 主引擎测试"""

    def test_load_default(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "emotion.json")
            engine = EmotionEngine(storage_path=path, enabled=True)
            state = engine.load()
            assert state.pleasure == 0.6
            assert state.interaction_count == 0

    def test_load_and_save_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "emotion.json")
            engine = EmotionEngine(storage_path=path, enabled=True)
            engine.load()
            engine._state.pleasure = 0.9
            engine.save()

            engine2 = EmotionEngine(storage_path=path, enabled=True)
            state2 = engine2.load()
            # load() 会调用 decay() 导致值衰减，只需验证加载到了接近的值
            assert state2.pleasure > 0.5

    def test_disabled_engine(self):
        engine = EmotionEngine(enabled=False)
        state = engine.load()
        assert state.pleasure == 0.6
        assert engine.get_emotion_prompt() == ""

    def test_update_without_model(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "emotion.json")
            engine = EmotionEngine(storage_path=path, enabled=True)
            result = engine.update("谢谢！", task_success=True)
            assert "agent_pad_delta" in result
            assert engine._state.interaction_count == 1

    def test_update_followup_no_count(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "emotion.json")
            engine = EmotionEngine(storage_path=path, enabled=True)
            engine.update("第一次", task_success=True)
            engine.update("第二次", task_success=True, is_followup=True)
            assert engine._state.interaction_count == 1

    def test_should_refuse_tool_disabled(self):
        engine = EmotionEngine(enabled=False)
        refuse, reason = engine.should_refuse_tool("web_search")
        assert refuse is False
        assert reason == ""

    def test_should_refuse_tool_low_pleasure(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "emotion.json")
            engine = EmotionEngine(storage_path=path, enabled=True)
            engine.load()
            engine._state.pleasure = -0.5
            engine.refuse_tools_when_low = {"web_search"}
            refuse, reason = engine.should_refuse_tool("web_search")
            assert refuse is True
            assert "web_search" in reason

    def test_get_workflow_adjustment(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "emotion.json")
            engine = EmotionEngine(storage_path=path, enabled=True)
            engine.load()
            adj = engine.get_workflow_adjustment()
            assert isinstance(adj, dict)
            assert "skip_reflection" in adj

    def test_get_personality_prompt_fallback(self):
        engine = EmotionEngine(enabled=True)
        prompt = engine.get_personality_prompt()
        assert prompt == PERSONALITY_PROMPT

    def test_get_personality_prompt_from_self_concept(self):
        class FakeSC:
            def load(self):
                return "# 我的自我概念\n\n我是 LinkSphere。"
        engine = EmotionEngine(enabled=True, self_concept=FakeSC())
        prompt = engine.get_personality_prompt()
        assert "LinkSphere" in prompt

    def test_derive_motivations(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "emotion.json")
            engine = EmotionEngine(storage_path=path, enabled=True)
            engine.load()
            motivations = engine.derive_motivations()
            assert isinstance(motivations, list)
