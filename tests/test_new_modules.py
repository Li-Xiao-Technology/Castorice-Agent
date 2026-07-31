"""
P2-4: 新增模块测试 —— 成本闸（CostBudget）+ Prompt Caching
"""

import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_cost_budget_basic():
    """成本闸基本功能测试"""
    from castorice.cost_budget import CostBudget, BudgetConfig
    cb = CostBudget()

    # 记录 token
    cb.record_usage(100, 50)
    cb.record_usage(200, 100)
    status = cb.get_status()
    assert status["hourly"]["tokens"] == 450
    assert status["hourly"]["calls"] == 2
    print("[OK] test_cost_budget_basic: token 记录正确")


def test_cost_budget_thinking_steps():
    """成本闸 ThinkingLoop 步数限制测试"""
    from castorice.cost_budget import CostBudget, BudgetConfig
    cfg = BudgetConfig(per_session_thinking_steps=3)
    cb = CostBudget(cfg)

    # 前 3 步应允许
    for i in range(3):
        assert cb.can_take_step("session-a") == True, f"Step {i} should be allowed"

    # 第 4 步应被拒绝
    assert cb.can_take_step("session-a") == False, "Step 4 should be denied"

    # 另一个会话不受影响
    assert cb.can_take_step("session-b") == True, "Other session should be independent"
    print("[OK] test_cost_budget_thinking_steps: 步数限制正确")


def test_cost_budget_autonomous_frequency():
    """成本闸自主循环频率限制测试"""
    from castorice.cost_budget import CostBudget, BudgetConfig
    cfg = BudgetConfig(autonomous_quick_min_interval=2, autonomous_deep_min_interval=5)
    cb = CostBudget(cfg)

    # 第一次应允许
    can, wait = cb.can_run_autonomous("quick")
    assert can == True, "First quick should be allowed"

    # 立即第二次应被拒绝
    can, wait = cb.can_run_autonomous("quick")
    assert can == False, "Immediate second quick should be denied"
    assert wait > 0, "Should have wait time"
    print("[OK] test_cost_budget_autonomous_frequency: 频率限制正确")


def test_cost_budget_config_update():
    """成本闸运行时配置更新测试"""
    from castorice.cost_budget import CostBudget
    cb = CostBudget()

    applied = cb.update_config({
        "hourly_token_limit": 50000,
        "daily_token_limit": 500000,
        "autonomous_quick_min_interval": 120,
    })
    assert applied.get("hourly_token_limit") == 50000
    assert applied.get("daily_token_limit") == 500000
    assert applied.get("autonomous_quick_min_interval") == 120

    cfg = cb.get_config()
    assert cfg["hourly_token_limit"] == 50000
    print("[OK] test_cost_budget_config_update: 配置更新正确")


def test_cost_budget_throttle_and_pause():
    """成本闸降频/暂停状态测试"""
    from castorice.cost_budget import CostBudget, BudgetConfig
    cfg = BudgetConfig(
        hourly_token_limit=1000,
        throttle_threshold=0.5,
        pause_threshold=0.9,
    )
    cb = CostBudget(cfg)

    # 用掉 400 token（40%，正常）
    cb.record_usage(300, 100)
    status = cb.get_status()
    assert status["throttled"] == False
    assert status["paused"] == False

    # 再用 300 token（累计 70%，触发降频）
    cb.record_usage(500, 200)
    status = cb.get_status()
    assert status["throttled"] == True
    assert status["paused"] == False

    # 自主循环在降频模式下间隔应加倍
    can, wait = cb.can_run_autonomous("quick")
    assert can == True  # 第一次可以
    can, wait = cb.can_run_autonomous("quick")
    # 降频模式下 quick 间隔 = 60*2 = 120s
    assert wait > 100, f"Throttled quick interval should be doubled, got wait={wait}"
    print("[OK] test_cost_budget_throttle_and_pause: 降频/暂停状态正确")


def test_chatmessage_cacheable_flag():
    """ChatMessage cacheable 标记测试（P1-1 Prompt Caching）"""
    from castorice.model_adapter.common import ChatMessage

    # 默认不可缓存
    msg = ChatMessage("user", "hello")
    assert getattr(msg, "cacheable", False) == False

    # 可缓存标记
    msg2 = ChatMessage("system", "long system prompt", cacheable=True)
    assert msg2.cacheable == True

    # to_dict 不受影响（保持兼容）
    d = msg2.to_dict()
    assert d["role"] == "system"
    assert d["content"] == "long system prompt"
    print("[OK] test_chatmessage_cacheable_flag: cacheable 标记正确")


def test_self_concept_seed():
    """身份种子层测试（P1-2）"""
    from castorice.self_concept import SelfConcept
    import tempfile, shutil

    tmpdir = tempfile.mkdtemp()
    try:
        storage = os.path.join(tmpdir, "self_concept.md")
        seed_path = os.path.join(tmpdir, "self_concept.seed.md")

        # 写种子
        seed_content = "我是一个喜欢安静的 Agent，偏好简洁回答。"
        with open(seed_path, "w", encoding="utf-8") as f:
            f.write(seed_content)

        sc = SelfConcept(storage_path=storage)
        content = sc.load()

        # 种子应被加载
        assert seed_content in content, "Seed content should be loaded"
        # 正式文件应被写入
        assert os.path.exists(storage), "self_concept.md should be created from seed"
        print("[OK] test_self_concept_seed: 身份种子层正确")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    tests = [
        test_cost_budget_basic,
        test_cost_budget_thinking_steps,
        test_cost_budget_autonomous_frequency,
        test_cost_budget_config_update,
        test_cost_budget_throttle_and_pause,
        test_chatmessage_cacheable_flag,
    ]
    passed = 0
    for t in tests:
        try:
            t()
            passed += 1
        except AssertionError as e:
            print(f"[FAIL] {t.__name__}: {e}")
        except Exception as e:
            print(f"[ERROR] {t.__name__}: {e}")
    print(f"\n✅ {passed}/{len(tests)} tests passed")
