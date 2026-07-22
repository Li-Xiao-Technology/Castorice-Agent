"""
快速功能测试脚本
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_tools():
    print("=== 工具模块测试 ===")
    from castorice.tools.base_tools import (
        _registered_tools, get_base_tools, register_tool, Tool,
        _is_path_safe, _SAFE_BUILTINS, _TERMINAL_WHITELIST,
    )

    # 先触发工具加载，注册外部信息检索工具
    get_base_tools()

    assert len(_registered_tools) >= 25, f"Expected at least 25 tools, got {len(_registered_tools)}"
    print(f"1. 工具注册: {len(_registered_tools)} tools - PASS")

    repl = _registered_tools["python_repl"]

    result = repl.invoke({"code": "print(1+1)"})
    assert "2" in result
    print("2. python_repl 正常代码 - PASS")

    result = repl.invoke({"code": "import os"})
    assert "ImportError" in result or "error" in result.lower()
    print("3. python_repl import 拦截 - PASS")

    result = repl.invoke({"code": "f = open('test.txt', 'w')"})
    assert "NameError" in result or "error" in result.lower() or "安全" in result
    print("4. python_repl open 拦截 - PASS")

    term = _registered_tools["terminal"]
    result = term.invoke({"command": "echo hello_test"})
    assert "BLOCKED" not in result and "hello_test" in result
    print("5. terminal 白名单通过 - PASS")

    result = term.invoke({"command": "rm -rf /"})
    assert "BLOCKED" in result
    print("6. terminal 黑名单拦截 - PASS")

    tmpdir = tempfile.mkdtemp()
    assert _is_path_safe(os.path.join(tmpdir, "test.txt"), [tmpdir])
    print("7. 路径安全-白名单内 - PASS")

    outside = os.path.join(os.path.dirname(tmpdir), "evil.txt")
    assert not _is_path_safe(outside, [tmpdir])
    print("8. 路径安全-白名单外 - PASS")

    env_path = os.path.join(tmpdir, ".env")
    with open(env_path, "w") as f:
        f.write("test")
    assert not _is_path_safe(env_path, [tmpdir])
    print("9. 路径安全-.env 拦截 - PASS")


def test_memory():
    print("\n=== 记忆模块测试 ===")
    tmpdir = tempfile.mkdtemp()

    from castorice.memory.short_term import ShortTermMemory, Message
    db_path = os.path.join(tmpdir, "test.db")
    stm = ShortTermMemory(db_path=db_path, max_turns=20)
    stm.create_session("test1")
    stm.add_message("test1", Message(role="user", content="hello"))
    stm.add_message("test1", Message(role="assistant", content="hi"))
    hist = stm.get_history("test1")
    assert len(hist) == 2
    print("10. 短期记忆增查 - PASS")
    stm.close()

    from castorice.memory.skill import SkillMemory, Skill
    skill_path = os.path.join(tmpdir, "skills.json")
    skm = SkillMemory(storage_path=skill_path)
    skill = Skill(name="测试技能", trigger_keywords=["测试"], description="desc", steps=[])
    skm.add_or_update(skill)
    assert skm.find_by_name("测试技能") is not None
    matches = skm.match("测试一下")
    assert len(matches) > 0
    print("11. 技能记忆增查匹配 - PASS")

    from castorice.memory.user_profile import UserProfile
    prof_path = os.path.join(tmpdir, "profile.json")
    prof = UserProfile(storage_path=prof_path)
    prof.set("preferences.language", "zh")
    assert prof.get("preferences.language") == "zh"
    ctx = prof.to_prompt_context()
    assert isinstance(ctx, str) and len(ctx) > 0
    print("12. 用户画像读写 - PASS")


def test_qq_config():
    print("\n=== QQ 配置测试 ===")
    from castorice.adapters.qq_bot import QQBotConfig
    cfg = QQBotConfig(
        app_id="test", app_secret="test",
        allowed_users=["u1"], allowed_groups=["g1"],
    )
    assert cfg.allowed_users == ["u1"]
    assert cfg.allowed_groups == ["g1"]
    print("13. QQBotConfig 白名单配置 - PASS")


def test_audit_log():
    print("\n=== 审计日志测试 ===")
    tmpdir = tempfile.mkdtemp()
    from castorice.security.audit_log import AuditLogger
    audit_dir = os.path.join(tmpdir, "audit")
    audit = AuditLogger(log_dir=audit_dir, max_files=5)
    audit.log_tool_call("user1", "sess1", "web_search", {"q": "test"}, "res", "low")
    audit.log_security_event("user2", "sess2", "blocked", {"cmd": "rm"}, "high")
    logs = audit.get_recent_logs(10)
    assert len(logs) == 2
    print("14. 审计日志 - PASS")


def test_agent_state():
    print("\n=== Agent State 测试 ===")
    from castorice.agent import State
    s = State(user_input="test", session_id="test")
    assert hasattr(s, "history_messages")
    assert hasattr(s, "relevant_history")
    assert hasattr(s, "user_profile_context")
    print("15. State 字段完整 - PASS")


def test_model_adapter():
    print("\n=== 模型适配器测试 ===")
    from castorice.model_adapter import ModelAdapter, ChatMessage
    cfg = {
        "provider": "openai",
        "openai": {"api_key": "sk-test", "base_url": "http://localhost/v1", "model": "test"},
    }
    adapter = ModelAdapter(cfg)
    assert adapter.provider == "openai"
    assert adapter.max_retries == 3
    assert adapter.retry_delay == 1.0
    assert hasattr(adapter, "get_usage_stats")
    print("16. ModelAdapter 初始化 - PASS")


if __name__ == "__main__":
    test_tools()
    test_memory()
    test_qq_config()
    test_audit_log()
    test_agent_state()
    test_model_adapter()

    # pytest 风格测试文件（统一风格，包含意图追踪、社会关系、自传式记忆、安全层等）
    print("\n" + "=" * 40)
    print("  运行 pytest 风格测试套件")
    print("=" * 40)

    import pytest

    pytest_files = [
        "tests/test_agent_core.py",
        "tests/test_self_modules.py",
        "tests/test_emotion.py",
        "tests/test_reflection.py",
        "tests/test_model_adapter.py",
        "tests/test_intent_tracker.py",
        "tests/test_social_relation.py",
        "tests/test_autobiographical.py",
        "tests/test_memory.py",
        "tests/test_tools.py",
        "tests/test_security_file_guard.py",
        "tests/test_security_pattern_detector.py",
        "tests/test_security_rollback.py",
        "tests/test_security_authorization.py",
    ]

    exit_code = pytest.main(pytest_files + ["-v", "--tb=short"])
    if exit_code != 0:
        sys.exit(exit_code)

    print("\n" + "=" * 40)
    print("  所有测试通过！")
    print("=" * 40)
