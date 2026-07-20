"""
渐进授权系统安全测试
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_authorization():
    print("\n=== 渐进授权系统安全测试 ===")

    from castorice.security.authorization import ProgressiveAuthorization

    # 1. 初始等级检查
    auth = ProgressiveAuthorization(initial_level=1)
    allowed, reason = auth.is_allowed("self_concept.read")
    assert allowed is True, "L0 操作在 L1 应允许"
    print("1. 初始等级 L1 允许 L0 操作 - PASS")

    # 2. 高等级操作被拒绝
    allowed, reason = auth.is_allowed("tool.terminal")
    assert allowed is False, "L4 操作在 L1 应拒绝"
    assert "需要信任等级 4" in reason
    print("2. 低等级拒绝高等级操作 - PASS")

    # 3. 晋升测试（连续成功5次）
    auth2 = ProgressiveAuthorization(initial_level=1, promotion_threshold=3)
    for i in range(3):
        auth2.record_outcome("self_concept.read", success=True)
    status = auth2.get_status()
    assert status["current_level"] == 2, f"应晋升到 L2: {status}"
    print("3. 连续成功晋升 - PASS")

    # 4. 降级测试（连续失败2次）
    auth3 = ProgressiveAuthorization(initial_level=2, demotion_threshold=2)
    auth3.record_outcome("tool.read_file", success=False)
    auth3.record_outcome("tool.read_file", success=False)
    status = auth3.get_status()
    assert status["current_level"] == 1, f"应降级到 L1: {status}"
    print("4. 连续失败降级 - PASS")

    # 5. 最高等级不晋升
    auth4 = ProgressiveAuthorization(initial_level=5)
    for _ in range(10):
        auth4.record_outcome("self_concept.read", success=True)
    assert auth4.get_status()["current_level"] == 5
    print("5. 最高等级不晋升 - PASS")

    # 6. 最低等级不降级
    auth5 = ProgressiveAuthorization(initial_level=0)
    for _ in range(10):
        auth5.record_outcome("self_concept.read", success=False)
    assert auth5.get_status()["current_level"] == 0
    print("6. 最低等级不降级 - PASS")

    # 7. 人工强制设置等级
    auth6 = ProgressiveAuthorization(initial_level=1)
    auth6.force_set_level(4, "测试需要")
    assert auth6.get_status()["current_level"] == 4
    allowed, _ = auth6.is_allowed("tool.terminal")
    assert allowed is True
    print("7. 人工强制设置等级 - PASS")

    # 8. 无效等级拒绝
    auth7 = ProgressiveAuthorization(initial_level=1)
    auth7.force_set_level(99)
    assert auth7.get_status()["current_level"] == 1
    print("8. 无效等级拒绝 - PASS")

    # 9. 事件日志记录
    auth8 = ProgressiveAuthorization(initial_level=1, promotion_threshold=2)
    auth8.record_outcome("tool.web_search", success=True)
    auth8.record_outcome("tool.web_search", success=True)
    status = auth8.get_status()
    events = status["recent_events"]
    assert len(events) > 0
    assert any(e.get("type") == "promotion" for e in events)
    print("9. 事件日志记录 - PASS")

    # 10. 操作历史记录
    auth9 = ProgressiveAuthorization(initial_level=1)
    auth9.record_outcome("tool.read_file", success=True)
    auth9.record_outcome("tool.read_file", success=False)
    status = auth9.get_status()
    assert "tool.read_file" in status["operation_history_count"]
    print("10. 操作历史记录 - PASS")

    print(f"\n渐进授权系统安全测试完成，共 10 项测试通过！")


if __name__ == "__main__":
    test_authorization()