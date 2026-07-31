"""测试群消息发送 API"""
import asyncio
import sys
sys.path.insert(0, r"c:\Users\sheng\Desktop\Castorice Agent trae")

from castorice.adapters.qq_bot import QQBotConfig, QQBotAdapter

async def main():
    config = QQBotConfig(
        app_id="1905206471",
        app_secret="",  # 不需要，因为会从环境变量读取
        sandbox=True,
        intent=33559552,
        allowed_users=["2730641729", "1799714098"],
        allowed_groups=["858953672"],
    )
    bot = QQBotAdapter(config)
    
    group_id = "2A8B21D80770F101191A88773E106D45"
    result = await bot.send_group_message(group_id, "测试消息：群消息发送 API 测试成功！")
    print(f"发送结果: {result}")

if __name__ == "__main__":
    asyncio.run(main())
