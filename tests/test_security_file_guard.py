"""
文件守卫安全测试
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_file_guard():
    print("\n=== 文件守卫安全测试 ===")

    from castorice.security.file_guard import FileWriteGuard

    guard = FileWriteGuard()
    tmpdir = tempfile.mkdtemp()

    # 1. 允许写入 .txt 文件
    allowed, reason = guard.check_write_allowed(
        os.path.join(tmpdir, "test.txt"), "hello"
    )
    assert allowed is True, f"应允许写入 .txt: {reason}"
    print("1. 允许写入 .txt - PASS")

    # 2. 禁止写入 .py 文件
    allowed, reason = guard.check_write_allowed(
        os.path.join(tmpdir, "test.py"), "print(1)"
    )
    assert allowed is False, "应禁止写入 .py"
    print("2. 禁止写入 .py - PASS")

    # 3. 禁止写入 .yaml 文件
    allowed, reason = guard.check_write_allowed(
        os.path.join(tmpdir, "config.yaml"), "key: value"
    )
    assert allowed is False, "应禁止写入 .yaml"
    print("3. 禁止写入 .yaml - PASS")

    # 4. 白名单内的 .json 允许
    allowed, reason = guard.check_write_allowed(
        os.path.join(tmpdir, "castorice_data", "data.json"), '{"a":1}'
    )
    assert allowed is True, f"白名单 .json 应允许: {reason}"
    print("4. 白名单 .json 允许 - PASS")

    # 5. 非白名单 .json 禁止
    allowed, reason = guard.check_write_allowed(
        os.path.join(tmpdir, "config.json"), '{"a":1}'
    )
    assert allowed is False, "非白名单 .json 应禁止"
    print("5. 非白名单 .json 禁止 - PASS")

    # 6. 禁止写入安全目录
    allowed, reason = guard.check_write_allowed(
        os.path.join("castorice", "security", "test.txt"), "x"
    )
    assert allowed is False, "安全目录应禁止"
    print("6. 禁止写入安全目录 - PASS")

    # 7. 内容危险模式检测
    allowed, reason = guard.check_write_allowed(
        os.path.join(tmpdir, "note.md"), "import os\nsubprocess.call"
    )
    assert allowed is False, "危险内容应被拦截"
    print("7. 危险内容拦截 - PASS")

    # 8. 危险内容但写入记忆目录放行
    allowed, reason = guard.check_write_allowed(
        os.path.join(tmpdir, "castorice_data", "note.md"), "import os"
    )
    assert allowed is True, f"记忆目录危险内容应放行: {reason}"
    print("8. 记忆目录危险内容放行 - PASS")

    # 9. 危险命令拦截 - rm -rf /
    allowed, reason = guard.check_command_allowed("rm -rf /")
    assert allowed is False, "rm -rf / 应被拦截"
    print("9. 危险命令 rm -rf / 拦截 - PASS")

    # 10. 危险命令拦截 - fork bomb
    allowed, reason = guard.check_command_allowed(":(){ :|:& };:")
    assert allowed is False, "fork bomb 应被拦截"
    print("10. fork bomb 拦截 - PASS")

    # 11. 正常命令放行
    allowed, reason = guard.check_command_allowed("ls -la")
    assert allowed is True, f"正常命令应放行: {reason}"
    print("11. 正常命令放行 - PASS")

    # 12. 审计日志记录
    logs = guard.get_audit_log(last_n=20)
    assert len(logs) > 0, "应有审计日志"
    assert any("write_allowed" in str(l.get("action", "")) for l in logs), "应有允许写入记录"
    assert any("write_blocked" in str(l.get("action", "")) for l in logs), "应有阻止写入记录"
    print("12. 审计日志记录 - PASS")

    # 13. 速率限制测试（快速写入超过阈值）
    guard2 = FileWriteGuard()
    guard2._rate_limit_max = 3  # 临时降低阈值
    guard2._rate_limit_window = 60
    for i in range(3):
        guard2.check_write_allowed(os.path.join(tmpdir, f"rate{i}.txt"), "x")
    allowed, reason = guard2.check_write_allowed(os.path.join(tmpdir, "rate_over.txt"), "x")
    assert allowed is False, "速率超限应被拦截"
    print("13. 速率限制拦截 - PASS")

    print(f"\n文件守卫安全测试完成，共 13 项测试通过！")


if __name__ == "__main__":
    test_file_guard()