"""测试群消息发送 API - 直接用 .env"""
import asyncio
import json
import sys
import os

sys.path.insert(0, r"c:\Users\sheng\Desktop\Castorice Agent trae")
os.chdir(r"c:\Users\sheng\Desktop\Castorice Agent trae")

from dotenv import load_dotenv
load_dotenv()

async def main():
    from castorice.adapters.qq_bot import QQBotConfig, QQBotAdapter
    
    config = QQBotConfig(
        app_id=os.getenv("QQ_BOT_APP_ID", os.getenv("QQ_APP_ID", "1905206471")),
        app_secret=os.getenv("QQ_BOT_APP_SECRET", os.getenv("QQ_APP_SECRET", "")),
        sandbox=True,
        intent=33559552,
        allowed_users=["2730641729", "1799714098"],
        allowed_groups=["858953672"],
    )
    bot = QQBotAdapter(config)
    
    token = await bot._get_access_token()
    headers = await bot._get_headers()
    print(f"Token OK: {len(token)} chars")
    
    group_id = "2A8B21D80770F101191A88773E106D45"
    
    tests = [
        ("基础: content+msg_type+msg_seq", {
            "content": "测试1 基础",
            "msg_type": 0,
            "msg_seq": 101,
        }),
        ("不带msg_seq", {
            "content": "测试2 无msg_seq",
            "msg_type": 0,
        }),
        ("不带msg_type", {
            "content": "测试3 无msg_type",
            "msg_seq": 103,
        }),
        ("仅content", {
            "content": "测试4 仅content",
        }),
    ]
    
    for name, payload in tests:
        print(f"\n=== {name} ===")
        print(f"Payload: {json.dumps(payload, ensure_ascii=False)}")
        try:
            resp = await bot._http_client.post(
                f"/v2/groups/{group_id}/messages",
                headers=headers,
                json=payload,
            )
            print(f"Status: {resp.status_code}")
            print(f"Body: {resp.text[:800]}")
            if resp.status_code == 200:
                print("*** 成功！ ***")
                break
        except Exception as e:
            print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(main())
