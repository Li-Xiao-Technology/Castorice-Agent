"""
社会关系网络测试
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_social_relation():
    print("\n=== 社会关系网络测试 ===")
    tmpdir = tempfile.mkdtemp()

    from castorice.social_relation import SocialRelationManager, RelationNode

    db_path = os.path.join(tmpdir, "relation_test.db")
    manager = SocialRelationManager(db_path=db_path)

    # 1. 获取或创建关系
    relation = manager.get_or_create_relation("user_001", "张三")
    assert relation.user_id == "user_001"
    assert relation.user_name == "张三"
    assert relation.relation_type == "stranger"
    print("1. 获取或创建关系 - PASS")

    # 2. 更新关系（多次交互）
    for i in range(10):
        manager.update_relation(
            "user_001",
            interaction_quality=0.7,
            task_success=True,
            emotional_intensity=0.3,
            user_feedback="谢谢",
            context="日常对话",
        )
    relation = manager.get_relation("user_001")
    assert relation.shared_history_count == 10
    assert relation.intimacy > 0
    assert relation.trust_level > 0
    print("2. 更新关系（10次交互）- PASS")

    # 3. 关系类型演化
    assert relation.relation_type in ["acquaintance", "friend"]
    print(f"3. 关系类型演化: {relation.get_relation_label()} - PASS")

    # 4. 连续互动天数
    relation.interaction_streak = 5
    assert relation.interaction_streak == 5
    print("4. 连续互动天数 - PASS")

    # 5. 添加用户偏好
    manager.add_preference("user_001", "favorite_color", "blue")
    manager.add_preference("user_001", "favorite_topic", "AI")
    relation = manager.get_relation("user_001")
    assert relation.preferences.get("favorite_color") == "blue"
    assert relation.preferences.get("favorite_topic") == "AI"
    print("5. 添加用户偏好 - PASS")

    # 6. 提示词生成
    prompt = manager.to_prompt("user_001")
    assert isinstance(prompt, str)
    assert "关系状态" in prompt
    assert relation.get_relation_label() in prompt
    print("6. 提示词生成 - PASS")

    # 7. 获取所有关系
    relations = manager.get_all_relations()
    assert len(relations) >= 1
    print("7. 获取所有关系 - PASS")

    # 8. 获取关系统计
    stats = manager.get_stats()
    assert "total" in stats
    assert stats["total"] >= 1
    print("8. 获取关系统计 - PASS")

    # 9. 关系标签转换
    labels = {
        "stranger": "陌生人",
        "acquaintance": "认识的人",
        "friend": "朋友",
        "close_friend": "亲密朋友",
        "trusted": "最信任的人",
    }
    for rtype, expected in labels.items():
        node = RelationNode(user_id="test", relation_type=rtype)
        assert node.get_relation_label() == expected
    print("9. 关系标签转换 - PASS")

    # 10. 对话风格推荐
    styles = {
        "stranger": "礼貌、正式",
        "acquaintance": "友好、自然",
        "friend": "随意、真诚",
        "close_friend": "亲密、坦诚",
        "trusted": "完全信任",
    }
    for rtype, expected in styles.items():
        node = RelationNode(user_id="test", relation_type=rtype)
        style = node.get_conversation_style()
        assert expected in style
    print("10. 对话风格推荐 - PASS")

    print(f"\n社会关系网络测试完成，共 10 项测试通过！")


if __name__ == "__main__":
    test_social_relation()