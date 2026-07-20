"""
回滚管理器安全测试
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_rollback_manager():
    print("\n=== 回滚管理器安全测试 ===")

    from castorice.security.rollback import RollbackManager

    mgr = RollbackManager(baseline_window=50)

    # 1. 记录成功任务
    mgr.record_task(success=True)
    status = mgr.get_status()
    assert status["consecutive_failures"] == 0
    print("1. 记录成功任务 - PASS")

    # 2. 记录失败任务
    mgr.record_task(success=False)
    status = mgr.get_status()
    assert status["consecutive_failures"] == 1
    print("2. 记录失败任务 - PASS")

    # 3. 连续失败触发回滚条件
    mgr2 = RollbackManager(baseline_window=50)
    for _ in range(3):
        mgr2.record_task(success=False)
    should, reason = mgr2.should_rollback()
    assert should is True, f"连续3次失败应触发回滚: {reason}"
    assert "连续失败" in reason
    print("3. 连续失败触发回滚 - PASS")

    # 4. 成功率下降触发回滚
    mgr3 = RollbackManager(baseline_window=50)
    # 前10个100%成功
    for _ in range(10):
        mgr3.record_task(success=True)
    # 后10个100%失败（下降100% > 40%阈值）
    for _ in range(10):
        mgr3.record_task(success=False)
    should, reason = mgr3.should_rollback()
    assert should is True, f"成功率大幅下降应触发回滚: {reason}"
    print("4. 成功率下降触发回滚 - PASS")

    # 5. 正常状态不回滚
    mgr4 = RollbackManager(baseline_window=50)
    for _ in range(5):
        mgr4.record_task(success=True)
    should, reason = mgr4.should_rollback()
    assert should is False, "正常状态不应回滚"
    print("5. 正常状态不回滚 - PASS")

    # 6. 错误率飙升触发回滚
    mgr5 = RollbackManager(baseline_window=50)
    for _ in range(5):
        mgr5.record_error("connection timeout")
    should, reason = mgr5.should_rollback()
    assert should is True, f"错误率飙升应触发回滚: {reason}"
    print("6. 错误率飙升触发回滚 - PASS")

    # 7. 回滚冷却期
    mgr6 = RollbackManager(baseline_window=50)
    for _ in range(3):
        mgr6.record_task(success=False)
    mgr6.mark_rollback("test", ["item1"])
    should, reason = mgr6.should_rollback()
    assert should is False, "冷却期不应再次回滚"
    assert "冷却" in reason
    print("7. 回滚冷却期 - PASS")

    # 8. 标记回滚事件
    mgr7 = RollbackManager(baseline_window=50)
    mgr7.mark_rollback("认知健康度下降", ["self_concept.md", "emotion_state.json"])
    status = mgr7.get_status()
    assert status["rollback_count"] == 1
    assert status["last_rollback"] is not None
    print("8. 标记回滚事件 - PASS")

    # 9. 成功率计算
    mgr8 = RollbackManager(baseline_window=50)
    for _ in range(5):
        mgr8.record_task(success=True)
    for _ in range(5):
        mgr8.record_task(success=False)
    status = mgr8.get_status()
    assert status["recent_success_rate"] == 0.5
    print("9. 成功率计算 - PASS")

    # 10. 连续失败重置（成功后）
    mgr9 = RollbackManager(baseline_window=50)
    mgr9.record_task(success=False)
    mgr9.record_task(success=False)
    assert mgr9.get_status()["consecutive_failures"] == 2
    mgr9.record_task(success=True)
    assert mgr9.get_status()["consecutive_failures"] == 0
    print("10. 连续失败重置 - PASS")

    print(f"\n回滚管理器安全测试完成，共 10 项测试通过！")


if __name__ == "__main__":
    test_rollback_manager()