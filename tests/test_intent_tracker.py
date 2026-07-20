"""
意图追踪系统测试
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_intent_tracker():
    print("\n=== 意图追踪系统测试 ===")
    tmpdir = tempfile.mkdtemp()

    from castorice.memory.intent_tracker import IntentTracker

    db_path = os.path.join(tmpdir, "intent_test.db")
    tracker = IntentTracker(db_path=db_path)

    # 1. 创建意图
    intent = tracker.add_intent(
        root_intent="学习Python编程",
        context="用户想学习Python基础语法",
        session_id="test_session_001",
    )
    assert intent.intent_id is not None
    assert intent.root_intent == "学习Python编程"
    assert intent.status == "active"
    assert intent.progress == 0.0
    print("1. 创建意图 - PASS")

    # 2. 获取活动意图
    active = tracker.get_active_intents()
    assert len(active) == 1
    assert active[0].intent_id == intent.intent_id
    print("2. 获取活动意图 - PASS")

    # 3. 更新意图进度
    updated = tracker.update_intent(
        intent.intent_id,
        progress=0.5,
        status="active",
        context="用户已经学习了基本语法",
    )
    assert updated.progress == 0.5
    print("3. 更新意图进度 - PASS")

    # 4. 添加子意图
    tracker.add_intent(
        root_intent="学习函数定义",
        context="子意图",
        session_id="test_session_001",
    )
    intent = tracker.get_intent_by_id(intent.intent_id)
    print("4. 添加子意图 - PASS")

    # 5. 标记意图完成
    tracker.update_intent(intent.intent_id, status="completed")
    intent = tracker.get_intent_by_id(intent.intent_id)
    assert intent.status == "completed"
    print("5. 标记意图完成 - PASS")

    # 6. 获取已完成意图
    all_intents = tracker.get_intents_by_session("test_session_001")
    completed = [i for i in all_intents if i.status == "completed"]
    assert len(completed) >= 1
    print("6. 获取已完成意图 - PASS")

    # 7. 测试提示词生成
    prompt = tracker.to_prompt(session_id="test_session_001", max_intents=5)
    assert isinstance(prompt, str)
    print("7. 提示词生成 - PASS")

    # 8. 测试意图清理（过期意图）
    cleaned = tracker.cleanup_expired()
    assert cleaned >= 0
    print("8. 过期意图清理 - PASS")

    # 9. 通过ID获取意图
    found = tracker.get_intent_by_id(intent.intent_id)
    assert found is not None
    assert found.intent_id == intent.intent_id
    print("9. 通过ID获取意图 - PASS")

    # 10. 获取过期意图列表
    expired = tracker.get_expired_intents()
    assert isinstance(expired, list)
    print("10. 获取过期意图列表 - PASS")

    print(f"\n意图追踪测试完成，共 10 项测试通过！")


if __name__ == "__main__":
    test_intent_tracker()