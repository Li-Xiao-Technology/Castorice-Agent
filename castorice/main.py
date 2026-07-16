"""
Castorice Agent - 主程序入口（精简版）

复刻 Hermes Agent 架构设计：
- 自研主循环（无 LangGraph 依赖）
- 原生 SDK 对接多模型
- 统一的 .env + yaml 配置加载
- 三种运行模式：test / interactive / batch

启动方式：
  1. python -m castorice.main
  2. castorice (安装后)
  3. 双击 start.bat (Windows)
"""

import argparse
import logging
import os
import sys
from datetime import datetime
from typing import List, Optional

# 自研模块
from castorice.config import get_config
from castorice.model_adapter import ModelAdapter
from castorice.agent import CastoriceAgent
from castorice.tools.base_tools import get_base_tools, Tool
from castorice.memory.short_term import ShortTermMemory, Message
from castorice.memory.skill import SkillMemory
from castorice.memory.user_profile import UserProfile
from castorice.memory.long_term import LongTermMemory


# ============================
# 日志配置
# ============================
def setup_logging(level: str = "INFO") -> None:
    """配置根日志器"""
    os.makedirs("./castorice_data", exist_ok=True)
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler("./castorice_data/castorice.log", encoding="utf-8"),
        ],
    )


# ============================
# Engine 工厂
# ============================
class CastoriceEngine:
    """Castorice Agent 引擎工厂类，统一管理各组件"""

    def __init__(self):
        setup_logging()
        self.logger = logging.getLogger("CastoriceEngine")

        # 1. 加载配置（.env + yaml）
        self.config = get_config()
        self.logger.info("配置加载完成")

        # 2. 初始化模型适配器
        llm_cfg = self.config.llm if hasattr(self.config, "llm") else {}
        self.model_adapter = ModelAdapter(llm_cfg)
        self.logger.info(f"模型适配器: {self.model_adapter.provider}")

        # 3. 初始化基础工具
        self.tools: List[Tool] = get_base_tools()
        self.logger.info(f"已加载工具: {[t.name for t in self.tools]}")

        # 4. 初始化记忆系统
        mem_cfg = self.config.memory if hasattr(self.config, "memory") else {}
        short_cfg = mem_cfg.get("short_term", {}) if isinstance(mem_cfg, dict) else {}
        long_cfg = mem_cfg.get("long_term", {}) if isinstance(mem_cfg, dict) else {}
        skill_cfg = mem_cfg.get("skill", {}) if isinstance(mem_cfg, dict) else {}

        self.short_term = ShortTermMemory(
            db_path=short_cfg.get("db_path", "./castorice_data/sessions.db"),
            max_turns=short_cfg.get("max_turns", 20),
        )
        self.long_term = LongTermMemory(
            persist_directory=long_cfg.get("persist_directory", "./castorice_data/chroma_db"),
            collection_name=long_cfg.get("collection_name", "castorice_long_term"),
        )
        self.skill_memory = SkillMemory(
            storage_path=skill_cfg.get("storage_path", "./castorice_data/skill_library.json"),
        )

        # 5. 用户画像
        profile_cfg = self.config.user_profile if hasattr(self.config, "user_profile") else {}
        profile_path = profile_cfg.get("storage_path", "./castorice_data/user_profile.json") if isinstance(profile_cfg, dict) else "./castorice_data/user_profile.json"
        self.user_profile = UserProfile(storage_path=profile_path)

        # 6. 构造 Agent（自研主循环）
        self.agent = CastoriceAgent(
            model_adapter=self.model_adapter,
            tools=self.tools,
            short_term_memory=self.short_term,
            long_term_memory=self.long_term,
            skill_memory=self.skill_memory,
            user_profile=self.user_profile,
            config=self.config,
        )
        self.logger.info("CastoriceEngine 初始化完成")

    def test(self) -> None:
        """测试模式：验证 LLM 连接"""
        self.logger.info("=" * 60)
        self.logger.info("Castorice Agent 测试模式")
        self.logger.info("=" * 60)
        result = self.model_adapter.test_connection()
        if result["success"]:
            self.logger.info(f"✓ 模型连接成功: {result['provider']} / {result['model']}")
            self.logger.info(f"  响应预览: {result['response_preview']}")
        else:
            self.logger.error(f"✗ 连接失败: {result.get('error', 'N/A')}")

        # 显示各组件状态
        self.logger.info(f"工具数: {len(self.tools)}")
        self.logger.info(f"技能数: {len(self.skill_memory.skills)}")
        self.logger.info(f"长期记忆可用: {self.long_term.is_available}")
        self.logger.info(f"用户交互次数: {self.user_profile.get('stats.total_interactions', 0)}")

    def interactive(self) -> None:
        """交互式终端模式"""
        self.logger.info("=" * 60)
        self.logger.info("Castorice Agent 交互式终端")
        self.logger.info("输入 /help 查看可用指令，/exit 退出")
        self.logger.info("=" * 60)

        session_id = self.short_term.create_session()
        self.user_profile.record_interaction()

        while True:
            try:
                user_input = input("\n[You] ").strip()
            except (EOFError, KeyboardInterrupt):
                self.logger.info("\n再见！")
                break

            if not user_input:
                continue

            # 系统指令
            if user_input.startswith("/"):
                if self._handle_command(user_input, session_id):
                    break
                continue

            # 普通对话
            try:
                state = self.agent.run(user_input, session_id=session_id)
                print(f"\n[Castorice] {state.final_answer}")

                if state.errors:
                    print(f"\n[警告] 本轮有 {len(state.errors)} 个错误")
            except Exception as e:
                self.logger.exception(f"任务执行异常: {e}")
                print(f"\n[错误] {e}")

    def batch(self, input_path: str) -> None:
        """批量任务模式：从文件逐行读取任务并执行"""
        if not os.path.exists(input_path):
            self.logger.error(f"输入文件不存在: {input_path}")
            return

        session_id = self.short_term.create_session()
        with open(input_path, "r", encoding="utf-8") as f:
            tasks = [line.strip() for line in f if line.strip() and not line.startswith("#")]

        self.logger.info(f"批量模式: 共 {len(tasks)} 个任务")
        for i, task in enumerate(tasks, 1):
            self.logger.info(f"\n--- 任务 {i}/{len(tasks)} ---")
            self.logger.info(f"任务: {task}")
            try:
                state = self.agent.run(task, session_id=session_id)
                self.logger.info(f"结果: {state.final_answer[:200]}")
            except Exception as e:
                self.logger.exception(f"任务失败: {e}")

    def _handle_command(self, cmd: str, session_id: str) -> bool:
        """处理斜杠指令，返回 True 表示退出"""
        parts = cmd.split()
        op = parts[0].lower()

        if op in ("/exit", "/quit"):
            print("再见！")
            return True
        if op == "/help":
            print("""
可用指令：
  /new        - 开启新会话
  /history    - 查看当前会话历史
  /skills     - 查看已学会的技能
  /profile    - 查看用户画像
  /clear_memory - 清空长期记忆
  /exit       - 退出程序
""")
        elif op == "/new":
            session_id = self.short_term.create_session()
            print(f"新会话: {session_id}")
        elif op == "/history":
            history = self.short_term.get_history(session_id)
            for m in history:
                print(f"[{m.role}] {m.content[:200]}")
        elif op == "/skills":
            for s in self.skill_memory.list_all():
                print(f"- {s.name} v{s.version}: {s.description}")
        elif op == "/profile":
            print(self.user_profile.to_prompt_context() or "(空)")
        elif op == "/clear_memory":
            self.long_term.clear()
            print("长期记忆已清空")
        else:
            print(f"未知指令: {op}，输入 /help 查看帮助")
        return False


# ============================
# CLI 入口
# ============================
def main() -> int:
    """主入口：解析命令行参数并运行"""
    parser = argparse.ArgumentParser(
        description="Castorice Agent - 自进化智能体（复刻 Hermes Agent 架构）",
    )
    parser.add_argument(
        "--mode", "-m",
        choices=["test", "interactive", "batch"],
        default="interactive",
        help="运行模式: test=测试连接, interactive=交互对话, batch=批量任务",
    )
    parser.add_argument(
        "--input", "-i",
        help="批量模式下的任务文件路径（每行一个任务）",
    )
    args = parser.parse_args()

    try:
        engine = CastoriceEngine()
    except Exception as e:
        print(f"[启动失败] {e}", file=sys.stderr)
        return 1

    if args.mode == "test":
        engine.test()
    elif args.mode == "batch":
        if not args.input:
            print("批量模式需要 --input 参数", file=sys.stderr)
            return 1
        engine.batch(args.input)
    else:
        engine.interactive()

    return 0


if __name__ == "__main__":
    sys.exit(main())
