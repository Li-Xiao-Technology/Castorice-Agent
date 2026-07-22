"""
CLIHandler - 命令行处理器

处理交互式终端、批量任务和斜杠指令。
"""
import os
import sys
import asyncio
import logging


class CLIHandler:
    """命令行处理器"""

    def __init__(self, engine):
        self.engine = engine
        self.logger = logging.getLogger("Castorice.CLI")

    def run_interactive(self) -> None:
        """运行交互式终端模式"""
        self.logger.info("=" * 60)
        self.logger.info("Castorice Agent 交互式终端")
        self.logger.info("输入 /help 查看可用指令，/exit 退出")
        self.logger.info("=" * 60)

        session_id = self.engine.short_term.create_session()
        self.engine.user_profile.record_interaction()

        while True:
            try:
                user_input = input("\n[You] ").strip()
            except (EOFError, KeyboardInterrupt):
                self.logger.info("\n再见！")
                break

            if not user_input:
                continue

            if user_input.startswith("/"):
                if self._handle_command(user_input, session_id):
                    break
                continue

            try:
                print("\n[Castorice] ", end="", flush=True)
                state = self.engine.agent.run(user_input, session_id=session_id,
                                              stream_callback=lambda chunk: (print(chunk, end="", flush=True)))
                print()

                if state.errors:
                    print(f"\n[警告] 本轮有 {len(state.errors)} 个错误")
            except Exception as e:
                self.logger.exception(f"任务执行异常: {e}")
                print(f"\n[错误] {e}")

    def run_batch(self, input_path: str) -> None:
        """运行批量任务模式"""
        if not os.path.exists(input_path):
            self.logger.error(f"输入文件不存在: {input_path}")
            return

        session_id = self.engine.short_term.create_session()
        with open(input_path, "r", encoding="utf-8") as f:
            tasks = [line.strip() for line in f if line.strip() and not line.startswith("#")]

        self.logger.info(f"批量模式: 共 {len(tasks)} 个任务")
        for i, task in enumerate(tasks, 1):
            self.logger.info(f"\n--- 任务 {i}/{len(tasks)} ---")
            self.logger.info(f"任务: {task}")
            try:
                state = self.engine.agent.run(task, session_id=session_id)
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
  /status     - 查看系统状态面板
  /reload_tools - 热更新工具列表（无需重启）
  /plugins    - 查看已加载的插件
  /self_concept - 查看 Agent 当前的自我概念
  /self_reflect - 立即触发一次自我反思
  /experiences - 查看最近的经历记录
  /clear_memory - 清空长期记忆

[后台服务管理]
  /qq_start   - 启动 QQ 机器人（后台运行）
  /qq_stop    - 停止 QQ 机器人
  /http_start - 启动 HTTP 服务器（后台运行）
  /http_stop  - 停止 HTTP 服务器
  /cron_start - 启动定时任务调度器（后台运行）
  /cron_stop  - 停止定时任务调度器
  /services   - 查看所有后台服务状态

  /exit       - 退出程序
""")
        elif op == "/new":
            session_id = self.engine.short_term.create_session()
            print(f"新会话: {session_id}")
        elif op == "/history":
            history = self.engine.short_term.get_history(session_id)
            for m in history:
                print(f"[{m.role}] {m.content[:200]}")
        elif op == "/skills":
            for s in self.engine.skill_memory.list_all():
                print(f"- {s.name} v{s.version}: {s.description}")
        elif op == "/profile":
            print(self.engine.user_profile.to_prompt_context() or "(空)")
        elif op == "/status":
            self._show_status()
        elif op == "/reload_tools":
            self._reload_tools()
        elif op == "/self_concept":
            sc = getattr(self.engine.agent, "self_concept", None)
            if sc is None:
                print("自我进化系统未启用")
            else:
                content = sc.load()
                if not content.strip():
                    print("（Agent 还未形成自我概念，多交互几轮后会自动反思并生成）")
                else:
                    print("=" * 60)
                    print("Agent 的自我概念")
                    print("=" * 60)
                    print(content)
                    print("=" * 60)
                    print(f"共 {sc.get_word_count()} 字符")
        elif op == "/self_reflect":
            engine = getattr(self.engine.agent, "reflection_engine", None)
            if engine is None:
                print("反思引擎未启用")
            else:
                print("正在触发自我反思（可能需要几秒）...")
                result = asyncio.run(engine.reflect(trigger_reason="手动触发"))
                print(f"\n✓ 反思完成")
                if result.patterns_observed:
                    print("\n观察到的行为模式:")
                    for p in result.patterns_observed:
                        print(f"  - {p}")
                if result.emotional_tendencies:
                    print("\n情感倾向:")
                    for e in result.emotional_tendencies:
                        print(f"  - {e}")
                if result.growth_insights:
                    print("\n成长洞察:")
                    for g in result.growth_insights:
                        print(f"  - {g}")
                if result.self_concept_updated:
                    print(f"\n✓ 自我概念已更新: {result.update_reason}")
                else:
                    print("\n自我概念保持不变（无需更新）")
                if result.next_actions:
                    print("\n下一步行动:")
                    for a in result.next_actions:
                        print(f"  - {a}")
        elif op == "/experiences":
            journal = getattr(self.engine.agent, "experience_journal", None)
            if journal is None:
                print("经历流未启用")
            else:
                stats = journal.get_stats()
                print(f"经历流统计: 共 {stats['total']} 条")
                for mtype, info in stats.get("by_type", {}).items():
                    print(f"  - {mtype}: {info['count']} 条, 平均重要性={info['avg_importance']}, 平均情感={info['avg_valence']:+.2f}")
                print()
                print("最近 10 条经历:")
                for exp in journal.get_recent(limit=10):
                    time_str = exp.timestamp[:19].replace("T", " ") if exp.timestamp else ""
                    print(f"  [{time_str}] ({exp.memory_type}, imp={exp.importance:.1f}, val={exp.emotional_valence:+.2f})")
                    print(f"    {exp.content[:150]}")
        elif op == "/plugins":
            if hasattr(self.engine, "plugin_manager"):
                plugins = self.engine.plugin_manager.list_plugins()
                if not plugins:
                    print("未加载任何插件")
                else:
                    for p in plugins:
                        print(f"- {p.name} v{p.version}: {p.description}")
                        if p.tools:
                            print(f"  工具: {', '.join(p.tools)}")
            else:
                print("插件系统未初始化")
        elif op == "/clear_memory":
            self.engine.long_term.clear()
            print("长期记忆已清空")
        elif op == "/qq_start":
            if self.engine.start_service("qq"):
                import time
                time.sleep(0.5)
                status = self.engine.get_service_status().get("qq", {})
                if status.get("error"):
                    print(f"✗ QQ 机器人启动失败: {status['error']}")
                else:
                    print("✓ QQ 机器人已在后台启动（详细日志见控制台输出）")
            else:
                print("✗ QQ 机器人启动失败（可能已在运行）")
        elif op == "/qq_stop":
            if self.engine.stop_service("qq"):
                print("✓ QQ 机器人已停止")
            else:
                print("✗ QQ 机器人未运行")
        elif op == "/http_start":
            if self.engine.start_service("http"):
                import time
                time.sleep(0.5)
                status = self.engine.get_service_status().get("http", {})
                if status.get("error"):
                    print(f"✗ HTTP 服务器启动失败: {status['error']}")
                else:
                    host = status.get("host", "0.0.0.0")
                    port = status.get("port", 8000)
                    print(f"✓ HTTP 服务器已在后台启动: http://{host}:{port}")
                    print(f"  API 文档: http://{host}:{port}/docs")
            else:
                print("✗ HTTP 服务器启动失败（可能已在运行）")
        elif op == "/http_stop":
            if self.engine.stop_service("http"):
                print("✓ HTTP 服务器已停止")
            else:
                print("✗ HTTP 服务器未运行")
        elif op == "/cron_start":
            if self.engine.start_service("cron"):
                import time
                time.sleep(0.5)
                status = self.engine.get_service_status().get("cron", {})
                if status.get("error"):
                    print(f"✗ 定时任务调度器启动失败: {status['error']}")
                else:
                    reflect_min = status.get("reflect_interval", 3600) // 60
                    cleanup_hr = status.get("cleanup_interval", 86400) // 3600
                    print(f"✓ 定时任务调度器已在后台启动")
                    print(f"  反思间隔: {reflect_min} 分钟")
                    print(f"  清理间隔: {cleanup_hr} 小时")
            else:
                print("✗ 定时任务调度器启动失败（可能已在运行）")
        elif op == "/cron_stop":
            if self.engine.stop_service("cron"):
                print("✓ 定时任务调度器已停止")
            else:
                print("✗ 定时任务调度器未运行")
        elif op == "/services":
            status = self.engine.get_service_status()
            print("━" * 50)
            print("  后台服务状态")
            print("━" * 50)

            qq = status.get("qq", {})
            qq_running = qq.get("status") == "running"
            print(f"  QQ 机器人:      {'🟢 运行中' if qq_running else '🔴 已停止'}")
            if qq.get("error"):
                print(f"    错误: {qq['error']}")

            http = status.get("http", {})
            http_running = http.get("status") == "running"
            print(f"  HTTP 服务器:    {'🟢 运行中' if http_running else '🔴 已停止'}")
            if http_running:
                print(f"    地址: http://{http.get('host', '?')}:{http.get('port', '?')}")
            elif http.get("error"):
                print(f"    错误: {http['error']}")

            cron = status.get("cron", {})
            cron_running = cron.get("status") == "running"
            print(f"  定时任务:       {'🟢 运行中' if cron_running else '🔴 已停止'}")
            if cron_running:
                reflect_min = cron.get("reflect_interval", 3600) // 60
                cleanup_hr = cron.get("cleanup_interval", 86400) // 3600
                print(f"    反思: {reflect_min} 分钟 / 清理: {cleanup_hr} 小时")
            elif cron.get("error"):
                print(f"    错误: {cron['error']}")

            print("━" * 50)
        else:
            print(f"未知指令: {op}，输入 /help 查看帮助")
        return False

    def _show_status(self) -> None:
        """显示系统状态面板"""
        print("=" * 60)
        print("Castorice Agent 系统状态")
        print("=" * 60)

        print(f"\n[模型适配器]")
        print(f"  供应商: {self.engine.model_adapter.provider}")
        usage = self.engine.model_adapter.get_usage_stats()
        print(f"  总调用次数: {usage['total_calls']}")
        print(f"  Prompt Tokens: {usage['total_prompt_tokens']:,}")
        print(f"  Completion Tokens: {usage['total_completion_tokens']:,}")
        print(f"  总 Tokens: {usage['total_tokens']:,}")

        print(f"\n[工具系统]")
        print(f"  已加载工具数: {len(self.engine.tools)}")
        for t in self.engine.tools:
            status = "✓" if hasattr(t, 'enabled') and t.enabled else "✓"
            print(f"    {status} {t.name}: {t.description[:30]}...")

        print(f"\n[记忆系统]")
        print(f"  短期记忆 (SQLite): {len(self.engine.short_term.list_sessions())} 个会话")
        print(f"  长期记忆 (Chroma): {'可用' if self.engine.long_term.is_available else '不可用'}, {self.engine.long_term.count()} 条记录")
        print(f"  技能库: {len(self.engine.skill_memory.list_all())} 个技能")

        if hasattr(self.engine.agent, 'self_awareness') and self.engine.agent.self_awareness:
            sa = self.engine.agent.self_awareness
            sa_stats = sa.get_stats()
            health = sa.health_check()

            health_icon = "✅" if health["status"] == "healthy" else "⚠️" if health["status"] == "warning" else "🔴"
            print(f"\n[自感知模块]")
            print(f"  健康状态: {health_icon} {health['status']} (评分: {health['score']}/100)")
            if health["issues"]:
                print(f"  问题:")
                for issue in health["issues"]:
                    print(f"    - {issue}")
            agent_stats = sa_stats["agent"]
            print(f"  总任务数: {agent_stats['total_tasks']}")
            print(f"  任务成功率: {agent_stats['task_success_rate']:.1%}")
            print(f"  LLM错误率: {agent_stats['error_rate']:.1%}")

            tool_stats = sa_stats.get("tools", {})
            if tool_stats:
                print(f"  工具统计:")
                for name, ts in tool_stats.items():
                    icon = "✅" if ts["success_rate"] >= 0.8 else "⚠️" if ts["success_rate"] >= 0.5 else "❌"
                    print(f"    {icon} {name}: {ts['call_count']}次, 成功率{ts['success_rate']:.0%}, 平均{ts['avg_time_ms']:.0f}ms")

        print("\n" + "=" * 60)

    def _reload_tools(self) -> None:
        """热更新工具列表"""
        try:
            from castorice.tools.base_tools import reload_tools
            reload_tools()
            self.engine.tools = self.engine._get_base_tools()
            self.engine.agent.tools_list = self.engine.tools
            self.engine.agent.available_tools_desc = "\n".join(f"- {t.name}: {t.description}" for t in self.engine.tools)
            print("工具已重新加载")
        except Exception as e:
            self.logger.warning(f"重新加载工具失败: {e}")