"""
自传式记忆测试
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_autobiographical():
    print("\n=== 自传式记忆测试 ===")
    tmpdir = tempfile.mkdtemp()

    from castorice.memory.autobiographical import AutobiographicalMemory

    db_path = os.path.join(tmpdir, "auto_test.db")
    memory = AutobiographicalMemory(db_path=db_path)

    # 1. 记录交互
    memory.record_interaction()
    assert memory._total_interactions == 1
    print("1. 记录交互 - PASS")

    # 2. 添加里程碑
    milestone = memory.add_milestone(
        "第一次交互",
        "成功完成第一次对话",
        category="first_achievement",
        importance=9.0,
        session_id="test_session_001",
    )
    assert milestone.milestone_id is not None
    assert milestone.title == "第一次交互"
    assert milestone.category == "first_achievement"
    print("2. 添加里程碑 - PASS")

    # 3. 获取里程碑
    milestones = memory.get_milestones(limit=10)
    assert len(milestones) == 1
    assert milestones[0].milestone_id == milestone.milestone_id
    print("3. 获取里程碑 - PASS")

    # 4. 添加重要事件
    event = memory.add_event(
        "学习了新知识",
        "通过对话学习了Python编程",
        event_type="learning",
        intensity=7.0,
        valence=0.8,
        lesson_learned="持续学习很重要",
    )
    assert event.event_id is not None
    assert event.event_type == "learning"
    assert event.lesson_learned == "持续学习很重要"
    print("4. 添加重要事件 - PASS")

    # 5. 获取重要事件
    events = memory.get_events(limit=10)
    assert len(events) == 1
    assert events[0].event_id == event.event_id
    print("5. 获取重要事件 - PASS")

    # 6. 开始新时期
    epoch = memory.start_epoch("探索期", "刚刚开始我的旅程")
    assert epoch.epoch_id is not None
    assert epoch.name == "探索期"
    print("6. 开始新时期 - PASS")

    # 7. 获取当前时期
    current = memory.get_current_epoch()
    assert current is not None
    assert current.name == "探索期"
    print("7. 获取当前时期 - PASS")

    # 8. 时期转换检测
    for _ in range(100):
        memory.record_interaction()
    assert memory._total_interactions >= 100
    print("8. 时期转换检测（累计100+交互）- PASS")

    # 9. 自我叙事生成
    story = memory.generate_life_story(max_milestones=5)
    assert isinstance(story, str)
    assert "我的故事" in story
    assert "第一次交互" in story
    print("9. 自我叙事生成 - PASS")

    # 10. 提示词生成
    prompt = memory.to_prompt(max_milestones=5)
    assert isinstance(prompt, str)
    assert "我的故事" in prompt
    print("10. 提示词生成 - PASS")

    # 11. 获取统计信息
    stats = memory.get_stats()
    assert "total_interactions" in stats
    assert "milestone_count" in stats
    assert "event_count" in stats
    assert "epoch_count" in stats
    print("11. 获取统计信息 - PASS")

    # 12. 按类别获取里程碑
    ach_milestones = memory.get_milestones(limit=10, category="first_achievement")
    assert len(ach_milestones) >= 1
    print("12. 按类别获取里程碑 - PASS")

    # 13. 按类型获取事件
    learn_events = memory.get_events(limit=10, event_type="learning")
    assert len(learn_events) >= 1
    print("13. 按类型获取事件 - PASS")

    print(f"\n自传式记忆测试完成，共 13 项测试通过！")


if __name__ == "__main__":
    test_autobiographical()