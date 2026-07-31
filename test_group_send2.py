"""测试群消息发送 API - 打印完整错误信息"""
import asyncio
import json
import sys
sys.path.insert(0, r"c:\Users\sheng\Desktop\Castorice Agent trae")

from castorice.adapters.qq_bot import QQBotConfig, QQBotAdapter

async def main():
    import os
    from dotenv import load_dotenv
    load_dotenv(r"c:\Users\sheng\Desktop\Castorice Agent trae\.env")
    
    config = QQBotConfig(
        app_id=os.getenv("QQ_APP_ID", "1905206471"),
        app_secret=os.getenv("QQ_APP_SECRET", ""),
        sandbox=True,
        intent=33559552,
        allowed_users=["2730641729", "1799714098"],
        allowed_groups=["858953672"],
    )
    bot = QQBotAdapter(config)
    
    # 先获取 token
    token = await bot._get_access_token()
    headers = await bot._get_headers()
    print(f"Token: {token[:30]}...")
    
    group_id = "2A8B21D80770F101191A88773E106D45"
    
    # 测试1: 只传 content 和 msg_type
    payload1 = {
        "content": "测试消息1",
        "msg_type": 0,
        "msg_seq": 1,
    }
    print(f"\n=== 测试1: 基础 payload ===")
    print(f"URL: /v2/groups/{group_id}/messages")
    print(f"Payload: {json.dumps(payload1, ensure_ascii=False)}")
    try:
        resp = await bot._http_client.post(
            f"/v2/groups/{group_id}/messages",
            headers=headers,
            json=payload1,
        )
        print(f"Status: {resp.status_code}")
        print(f"Body: {resp.text[:1000]}")
    except Exception as e:
        print(f"Error: {e}")
    
    # 测试2: 带 msg_id（需要真实用户消息ID，先用一个占位符试试）
    print(f"\n=== 测试2: 带 msg_id ===")
    try:
        resp2 = await bot._http_client.post(
            f"/v2/groups/{group_id}/messages",
            headers=headers,
            json={
                "content": "测试消息2",
                "msg_type": 0,
                "msg_seq": 2,
                "msg_id": "test_invalid_id",
            },
        )
        print(f"Status: {resp2.status_code}")
        print(f"Body: {resp2.text[:1000]}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(main())
