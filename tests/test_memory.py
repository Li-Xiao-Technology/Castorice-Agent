"""
记忆模块单元测试
"""

import os
import tempfile
import pytest
from castorice.memory.short_term import ShortTermMemory, Message
from castorice.memory.skill import SkillMemory, Skill
from castorice.memory.user_profile import UserProfile


class TestShortTermMemory:
    """短期记忆（SQLite）测试"""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "test.db")
        self.memory = ShortTermMemory(db_path=self.db_path, max_turns=20)

    def teardown_method(self):
        self.memory.close()

    def test_create_session(self):
        self.memory.create_session("test_sess_1")
        session = self.memory.get_session("test_sess_1")
        assert session is not None
        assert session.get("session_id") == "test_sess_1"

    def test_add_and_get_messages(self):
        self.memory.create_session("test_sess_2")
        self.memory.add_message("test_sess_2", Message(role="user", content="你好"))
        self.memory.add_message("test_sess_2", Message(role="assistant", content="你好！"))
        history = self.memory.get_history("test_sess_2")
        assert len(history) == 2
        assert history[0].role == "user"
        assert history[0].content == "你好"
        assert history[1].role == "assistant"
        assert history[1].content == "你好！"

    def test_max_turns_truncation(self):
        self.memory.max_turns = 2
        self.memory.create_session("test_sess_3")
        for i in range(10):
            self.memory.add_message("test_sess_3", Message(role="user", content=f"msg{i}"))
            self.memory.add_message("test_sess_3", Message(role="assistant", content=f"reply{i}"))
        history = self.memory.get_history("test_sess_3")
        assert len(history) == 4  # max_turns * 2 = 4

    def test_update_summary(self):
        self.memory.create_session("test_sess_4")
        self.memory.update_summary("test_sess_4", "测试摘要")
        session = self.memory.get_session("test_sess_4")
        assert session.get("summary") == "测试摘要"

    def test_list_sessions(self):
        self.memory.create_session("sess_a")
        self.memory.create_session("sess_b")
        sessions = self.memory.list_sessions(limit=10)
        assert len(sessions) >= 2


class TestSkillMemory:
    """技能记忆测试"""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.storage_path = os.path.join(self.tmpdir, "skills.json")
        self.memory = SkillMemory(storage_path=self.storage_path)

    def test_add_skill(self):
        skill = Skill(
            name="测试技能",
            trigger_keywords=["测试"],
            description="一个测试技能",
            steps=[{"tool": "web_search", "args": {"query": "test"}}],
        )
        self.memory.add_or_update(skill)
        found = self.memory.find_by_name("测试技能")
        assert found is not None
        assert found.name == "测试技能"

    def test_match_skill(self):
        skill = Skill(
            name="天气查询",
            trigger_keywords=["天气", "气温"],
            description="查询天气",
            steps=[],
        )
        self.memory.add_or_update(skill)
        matches = self.memory.match("今天天气怎么样")
        assert len(matches) > 0
        assert matches[0].name == "天气查询"

    def test_version_bump(self):
        skill = Skill(name="版本测试", trigger_keywords=["版本"], description="v1", steps=[])
        self.memory.add_or_update(skill)
        v1 = self.memory.find_by_name("版本测试").version
        skill2 = Skill(name="版本测试", trigger_keywords=["版本", "ver"], description="v2", steps=[])
        self.memory.add_or_update(skill2)
        v2 = self.memory.find_by_name("版本测试").version
        assert v2 > v1

    def test_delete_skill(self):
        skill = Skill(name="待删除", trigger_keywords=["del"], description="delete", steps=[])
        self.memory.add_or_update(skill)
        assert self.memory.find_by_name("待删除") is not None
        # delete 方法需要传入 skill_id 而非 name
        self.memory.delete(skill.id)
        assert self.memory.find_by_name("待删除") is None


class TestUserProfile:
    """用户画像测试"""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.storage_path = os.path.join(self.tmpdir, "profile.json")
        self.profile = UserProfile(storage_path=self.storage_path)

    def test_set_and_get(self):
        self.profile.set("preferences.language", "zh")
        assert self.profile.get("preferences.language") == "zh"

    def test_nested_get(self):
        self.profile.set("user.name", "测试用户")
        self.profile.set("user.age", 25)
        assert self.profile.get("user.name") == "测试用户"
        assert self.profile.get("user.age") == 25

    def test_default_value(self):
        assert self.profile.get("nonexistent.key", "默认值") == "默认值"

    def test_increment_interactions(self):
        initial = self.profile.get("stats.total_interactions", 0)
        self.profile.increment_interactions()
        assert self.profile.get("stats.total_interactions", 0) == initial + 1

    def test_to_prompt_context(self):
        self.profile.set("preferences.language", "zh")
        self.profile.set("preferences.tone", "友好")
        ctx = self.profile.to_prompt_context()
        assert isinstance(ctx, str)
        assert len(ctx) > 0
