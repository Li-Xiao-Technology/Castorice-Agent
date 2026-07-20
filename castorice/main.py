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

import warnings
# 过滤 sentence_transformers 的 cache_dir 弃用警告（来自 ChromaDB 内部调用）
warnings.filterwarnings(
    "ignore",
    message="The Transformer `cache_dir` argument is deprecated",
    category=UserWarning,
    module="sentence_transformers"
)

import argparse
import logging
import os
import signal
import sys
from datetime import datetime
from typing import List, Optional, Dict, Any

# 自研模块
from castorice.config import get_config
from castorice.model_adapter import ModelAdapter
from castorice.agent import CastoriceAgent
from castorice.tools.base_tools import get_base_tools, Tool
from castorice.memory.short_term import ShortTermMemory, Message
from castorice.memory.skill import SkillMemory
from castorice.memory.user_profile import UserProfile
from castorice.memory.long_term import LongTermMemory
from castorice.alerts import init_alerts_from_config, get_alert_manager
from castorice.self_organization import ErrorRecoveryStrategy


# ============================
# 日志配置
# ============================
class JsonLogFormatter(logging.Formatter):
    """JSON 格式日志格式化器"""
    
    def format(self, record):
        import json
        log_entry = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "line": record.lineno,
        }
        if record.exc_info:
            log_entry["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(log_entry, ensure_ascii=False)


def setup_logging(config: Optional[Dict[str, Any]] = None) -> None:
    """配置根日志器（支持文本/JSON 格式）"""
    os.makedirs("./castorice_data", exist_ok=True)
    
    log_cfg = config.get("logging", {}) if isinstance(config, dict) else {}
    level = log_cfg.get("level", "INFO").upper()
    log_format = log_cfg.get("format", "text").lower()
    log_dir = log_cfg.get("log_dir", "./castorice_data")
    max_size_mb = log_cfg.get("max_size_mb", 10)
    backup_count = log_cfg.get("backup_count", 5)
    
    os.makedirs(log_dir, exist_ok=True)
    file_path = os.path.join(log_dir, "castorice.log")
    
    handlers = []
    
    console_handler = logging.StreamHandler()
    if log_format == "json":
        console_handler.setFormatter(JsonLogFormatter(datefmt="%Y-%m-%d %H:%M:%S"))
    else:
        console_handler.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        ))
    handlers.append(console_handler)
    
    try:
        from logging.handlers import RotatingFileHandler
        file_handler = RotatingFileHandler(
            file_path,
            maxBytes=max_size_mb * 1024 * 1024,
            backupCount=backup_count,
            encoding="utf-8",
        )
        if log_format == "json":
            file_handler.setFormatter(JsonLogFormatter(datefmt="%Y-%m-%d %H:%M:%S"))
        else:
            file_handler.setFormatter(logging.Formatter(
                "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S"
            ))
        handlers.append(file_handler)
    except ImportError:
        file_handler = logging.FileHandler(file_path, encoding="utf-8")
        handlers.append(file_handler)
    
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        handlers=handlers,
    )


# ============================
# Engine 工厂
# ============================
class CastoriceEngine:
    """Castorice Agent 引擎工厂类，统一管理各组件"""

    def __init__(self):
        # P1-31: 提前设置 logger，确保异常时 cleanup 可用
        self.logger = logging.getLogger("CastoriceEngine")
        try:
            self._init_internal()
        except Exception:
            self.logger.exception("CastoriceEngine 初始化失败，正在清理已初始化的资源")
            try:
                self.cleanup()
            except Exception as cleanup_err:
                self.logger.warning(f"清理资源时再次失败: {cleanup_err}")
            raise

    def _init_internal(self) -> None:
        """实际初始化逻辑（P1-31: 与 __init__ 分离，便于异常时统一清理）"""
        # 1. 加载配置（.env + yaml）
        self.config = get_config()

        # 2. 配置日志（从yaml读取配置）
        setup_logging(self.config.raw())
        self.logger.info("配置加载完成")

        # 2. 初始化模型适配器
        llm_cfg = self.config.llm if hasattr(self.config, "llm") else {}
        self.model_adapter = ModelAdapter(llm_cfg)
        self.logger.info(f"模型适配器: {self.model_adapter.provider}")

        # 3. 初始化基础工具（传入配置使 enabled/allowed_paths 生效）
        tools_raw_cfg = self.config.raw().get("tools", {})
        self.tools: List[Tool] = get_base_tools(tools_raw_cfg)

        # 加载 LangChain 生态工具（根据配置）
        tools_cfg = self.config.tools if hasattr(self.config, "tools") else {}
        lc_cfg = tools_cfg.get("langchain_tools", {}) if isinstance(tools_cfg, dict) else {}
        if isinstance(lc_cfg, dict) and lc_cfg.get("enabled", False):
            try:
                from castorice.adapters import ToolFactory
                lc_tool_names = lc_cfg.get("tools", [])
                if lc_tool_names:
                    lc_tools = ToolFactory.get_langchain_tools(lc_tool_names)
                    if lc_tools:
                        self.tools.extend(lc_tools)
                        self.logger.info(f"已加载 LangChain 工具: {[t.name for t in lc_tools]}")
            except Exception as e:
                self.logger.warning(f"加载 LangChain 工具失败: {e}")

        # P1-3: 加载外部插件（从 plugins/ 目录）
        try:
            from castorice.plugin import get_plugin_manager
            self.plugin_manager = get_plugin_manager()
            plugins_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "plugins")
            if not os.path.exists(plugins_dir):
                # 创建默认插件目录 + 示例插件
                self._init_plugins_dir(plugins_dir)
            loaded = self.plugin_manager.load_plugins_from_dir(plugins_dir)
            if loaded > 0:
                # 把插件注册的工具 merge 进 self.tools
                from castorice.tools.base_tools import _registered_tools
                plugin_tool_names = set()
                for pinfo in self.plugin_manager.list_plugins():
                    plugin_tool_names.update(pinfo.tools)
                for tname in plugin_tool_names:
                    if tname in _registered_tools and tname not in {t.name for t in self.tools}:
                        self.tools.append(_registered_tools[tname])
                self.logger.info(f"已加载 {loaded} 个插件，新增工具: {sorted(plugin_tool_names)}")
        except Exception as e:
            self.logger.warning(f"插件系统加载失败: {e}")

        self.logger.info(f"已加载工具总数: {[t.name for t in self.tools]}")

        # P2-4: YAML 工具列表与实际注册工具同步检查
        try:
            from castorice.tools.base_tools import _registered_tools
            yaml_tool_names = set()
            tools_cfg_dict = self.config.raw().get("tools", {}) or {}
            for k, v in tools_cfg_dict.items():
                if isinstance(v, dict) and v.get("enabled", False):
                    yaml_tool_names.add(k)
            actual_tool_names = set(_registered_tools.keys())
            # 缺失：注册了但 YAML 没配置
            missing_in_yaml = actual_tool_names - yaml_tool_names
            # 多余：YAML 配置了但实际没注册
            extra_in_yaml = yaml_tool_names - actual_tool_names
            if missing_in_yaml:
                self.logger.info(
                    f"P2-4 工具同步: YAML 缺失 {len(missing_in_yaml)} 个工具配置 "
                    f"(已自动启用): {sorted(missing_in_yaml)[:10]}{'...' if len(missing_in_yaml) > 10 else ''}"
                )
            if extra_in_yaml:
                self.logger.warning(
                    f"P2-4 工具同步: YAML 配置了但未注册的工具: {sorted(extra_in_yaml)}"
                )
        except Exception as e:
            self.logger.debug(f"工具同步检查失败: {e}")

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

        # P1-33: 告警系统提前到 Agent 之前初始化，确保 Agent 构造失败时可触发告警
        self.alert_manager = init_alerts_from_config(self.config.raw())
        channel_count = len(self.alert_manager._channels)
        if channel_count > 0:
            self.logger.info(f"告警系统已初始化: {channel_count} 个渠道")

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

        # 注册信号处理器，支持优雅退出
        signal.signal(signal.SIGINT, self._signal_handler)
        try:
            signal.signal(signal.SIGTERM, self._signal_handler)
        except (AttributeError, ValueError):
            pass  # Windows 可能不支持 SIGTERM

        # 启动工具文件监控器（自动热更新）
        self._tool_watcher = None
        self._start_tool_watcher()

    def _init_plugins_dir(self, plugins_dir: str) -> None:
        """P1-3: 初始化默认插件目录 + 示例插件"""
        try:
            os.makedirs(plugins_dir, exist_ok=True)
            # 创建 __init__.py（空文件，标记为 Python 包）
            init_path = os.path.join(plugins_dir, "__init__.py")
            if not os.path.exists(init_path):
                with open(init_path, "w", encoding="utf-8") as f:
                    f.write("# Castorice Agent 插件目录\n# 在此放置 .py 文件即可被自动加载\n")

            # 创建示例插件
            example_path = os.path.join(plugins_dir, "example_plugin.py")
            if not os.path.exists(example_path):
                with open(example_path, "w", encoding="utf-8") as f:
                    f.write('''"""
示例插件 - 演示如何为 Castorice Agent 编写插件

每个插件需要：
1. 定义工具函数（用 @register_plugin_tool 装饰）
2. 定义 __plugin_info__ 字典声明插件元信息和工具列表
3. 文件名以 .py 结尾，不以 _ 开头（_ 开头的文件会被跳过）
"""

from castorice.plugin import register_plugin_tool


@register_plugin_tool("plugin_example", "示例插件工具：返回问候语")
def plugin_example(name: str = "世界") -> str:
    """
    生成问候语

    :param name: 要问候的对象名称
    :return: 问候语字符串
    """
    return f"你好，{name}！这是来自插件的问候 (´• ω •`)"


__plugin_info__ = {
    "name": "example_plugin",
    "version": "1.0.0",
    "description": "示例插件，展示插件系统用法",
    "author": "Castorice",
    "tools": ["plugin_example"],
}
''')
            self.logger.info(f"插件目录已初始化: {plugins_dir}")
        except Exception as e:
            self.logger.warning(f"插件目录初始化失败: {e}")

    def _start_tool_watcher(self) -> None:
        """启动工具文件监控器，自动检测文件变化并热更新"""
        try:
            from watchdog.observers import Observer
            from watchdog.events import FileSystemEventHandler

            class ToolFileHandler(FileSystemEventHandler):
                def __init__(self, callback):
                    self.callback = callback
                    self.last_modified = {}

                def on_modified(self, event):
                    if event.is_directory:
                        return
                    if event.src_path.endswith(".py") and "tools" in event.src_path:
                        import time
                        current_time = time.time()
                        if event.src_path in self.last_modified:
                            if current_time - self.last_modified[event.src_path] < 2:
                                return
                        self.last_modified[event.src_path] = current_time
                        print(f"\n[工具热更新] 检测到文件变化: {event.src_path}")
                        self.callback()

            tools_dir = os.path.join(os.path.dirname(__file__), "tools")
            if not os.path.exists(tools_dir):
                return

            event_handler = ToolFileHandler(self._reload_tools)
            self._tool_watcher = Observer()
            self._tool_watcher.schedule(event_handler, tools_dir, recursive=True)
            self._tool_watcher.start()
            self.logger.info(f"工具文件监控器已启动，监控目录: {tools_dir}")
        except ImportError:
            self.logger.info("watchdog 未安装，跳过自动热更新监控器")
        except Exception as e:
            self.logger.error(f"启动文件监控器失败: {e}")

    def cleanup(self) -> None:
        """清理资源：关闭记忆模块、停止 QQ 机器人、停止 HTTP 服务器"""
        self.logger.info("正在清理资源...")
        # 停止文件监控器
        if hasattr(self, "_tool_watcher") and self._tool_watcher:
            try:
                self._tool_watcher.stop()
                self._tool_watcher.join()
            except Exception as e:
                self.logger.warning(f"停止文件监控器失败: {e}")
        # 停止 QQ 机器人
        if hasattr(self, "_qq_bot") and self._qq_bot:
            try:
                self._stop_qq_bot()
            except Exception as e:
                self.logger.warning(f"停止 QQ 机器人失败: {e}")
        # 停止 HTTP 服务器
        if hasattr(self, "_http_server") and self._http_server:
            try:
                self._stop_http_server()
            except Exception as e:
                self.logger.warning(f"停止 HTTP 服务器失败: {e}")
        # 关闭短期记忆连接
        if hasattr(self, "short_term") and self.short_term:
            try:
                self.short_term.close()
            except Exception as e:
                self.logger.warning(f"关闭短期记忆连接失败: {e}")
        self.logger.info("资源清理完成")

    def _signal_handler(self, signum, frame) -> None:
        """信号处理回调（Windows 兼容）"""
        self.logger.info(f"收到退出信号 ({signum})，准备清理...")
        try:
            self.cleanup()
        except Exception as e:
            self.logger.error(f"清理过程中发生错误: {e}")
        sys.exit(0)

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
                print("\n[Castorice] ", end="", flush=True)
                state = self.agent.run(user_input, session_id=session_id, 
                                      stream_callback=lambda chunk: (print(chunk, end="", flush=True)))
                print()

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
  /status     - 查看系统状态面板
  /reload_tools - 热更新工具列表（无需重启）
  /plugins    - 查看已加载的插件
  /self_concept - 查看 Agent 当前的自我概念
  /self_reflect - 立即触发一次自我反思
  /experiences - 查看最近的经历记录
  /clear_memory - 清空长期记忆
  /qq_start   - 启动 QQ 机器人
  /qq_stop    - 停止 QQ 机器人
  /http_start - 启动 HTTP 服务器
  /http_stop  - 停止 HTTP 服务器
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
        elif op == "/status":
            self._show_status()
        elif op == "/reload_tools":
            self._reload_tools()
        elif op == "/self_concept":
            sc = getattr(self.agent, "self_concept", None)
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
            engine = getattr(self.agent, "reflection_engine", None)
            if engine is None:
                print("反思引擎未启用")
            else:
                print("正在触发自我反思（可能需要几秒）...")
                import asyncio
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
            journal = getattr(self.agent, "experience_journal", None)
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
            if hasattr(self, "plugin_manager"):
                plugins = self.plugin_manager.list_plugins()
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
            self.long_term.clear()
            print("长期记忆已清空")
        elif op == "/qq_start":
            if self._start_qq_bot():
                print("QQ 机器人已启动")
            else:
                print("QQ 机器人启动失败，请检查配置")
        elif op == "/qq_stop":
            if self._stop_qq_bot():
                print("QQ 机器人已停止")
            else:
                print("QQ 机器人未运行")
        elif op == "/http_start":
            if self._start_http_server():
                print("HTTP 服务器已启动")
            else:
                print("HTTP 服务器启动失败，请安装 fastapi 和 uvicorn")
        elif op == "/http_stop":
            if self._stop_http_server():
                print("HTTP 服务器已停止")
            else:
                print("HTTP 服务器未运行")
        else:
            print(f"未知指令: {op}，输入 /help 查看帮助")
        return False

    # ============================================================
    # QQ 机器人
    # ============================================================
    def _start_qq_bot(self) -> bool:
        """启动 QQ 机器人"""
        try:
            from castorice.adapters.qq_bot import QQBotConfig, QQBotAdapter

            qq_cfg = self.config.qq_bot if hasattr(self.config, "qq_bot") else {}
            if not isinstance(qq_cfg, dict):
                qq_cfg = {}

            app_id = qq_cfg.get("app_id", "")
            app_secret = qq_cfg.get("app_secret", "")
            sandbox = qq_cfg.get("sandbox", True)
            intent = qq_cfg.get("intent_value")  # 使用解析后的 intent 值

            if not app_id or not app_secret:
                self.logger.error("QQ 机器人配置缺失：请在 .env 中设置 QQ_BOT_APP_ID 和 QQ_BOT_APP_SECRET")
                return False

            config = QQBotConfig(app_id=app_id, app_secret=app_secret, sandbox=sandbox, intent=intent)
            self._qq_bot = QQBotAdapter(config)

            def message_handler(content: str, context: dict) -> str:
                try:
                    self.logger.info(f"[QQ] 收到消息: {content[:100]} | 类型: {context.get('message_type')} | 用户: {context.get('user_id')}")
                    user_id = context.get("user_id", "qq_user")
                    session_id = f"qq_{user_id}"
                    state = self.agent.run(content, session_id=session_id)
                    reply = state.final_answer
                    self.logger.info(f"[QQ] 回复内容: {reply[:100] if reply else '(空)'}")
                    if not reply:
                        reply = "抱歉，我没有生成有效的回复"
                    reply_prefix = qq_cfg.get("reply_prefix", "")
                    if reply_prefix:
                        reply = f"{reply_prefix}\n{reply}"
                    return reply
                except Exception as e:
                    self.logger.error(f"QQ 消息处理失败: {e}")
                    return "抱歉，处理消息时出错了"

            self._qq_bot.on_message(message_handler)
            self._qq_bot_thread = self._qq_bot.start_in_thread()
            return True
        except Exception as e:
            self.logger.error(f"启动 QQ 机器人失败: {e}")
            return False

    def _start_http_server(self) -> bool:
        """启动 HTTP 服务器"""
        try:
            from castorice.adapters.http_server import HTTPServerAdapter
            
            http_cfg = self.config.http_server if hasattr(self.config, "http_server") else {}
            if not isinstance(http_cfg, dict):
                http_cfg = {}
            
            host = http_cfg.get("host", "0.0.0.0")
            port = http_cfg.get("port", 8000)
            
            self._http_server = HTTPServerAdapter(self, host=host, port=port)
            self._http_server_thread = self._http_server.start_in_thread()
            return True
        except ImportError as e:
            self.logger.error(f"启动 HTTP 服务器失败: {e}")
            return False
        except Exception as e:
            self.logger.error(f"启动 HTTP 服务器失败: {e}")
            return False

    def _stop_http_server(self) -> bool:
        """停止 HTTP 服务器"""
        if hasattr(self, "_http_server") and self._http_server:
            try:
                self._http_server.stop()
                self._http_server = None
                self._http_server_thread = None
                return True
            except Exception as e:
                self.logger.error(f"停止 HTTP 服务器失败: {e}")
                return False
        return False

    def _stop_qq_bot(self) -> bool:
        """停止 QQ 机器人"""
        if hasattr(self, "_qq_bot") and self._qq_bot:
            try:
                import asyncio
                asyncio.run(self._qq_bot.stop())
                self._qq_bot = None
                self._qq_bot_thread = None
                return True
            except Exception as e:
                self.logger.error(f"停止 QQ 机器人失败: {e}")
                return False
        return False

    def _show_status(self) -> None:
        """显示系统状态面板"""
        print("=" * 60)
        print("Castorice Agent 系统状态")
        print("=" * 60)
        
        print(f"\n[模型适配器]")
        print(f"  供应商: {self.model_adapter.provider}")
        print(f"  模型: {self.model_adapter.openai_cfg.get('model', self.model_adapter.anthropic_cfg.get('model', self.model_adapter.gemini_cfg.get('model', 'unknown')))}")
        usage = self.model_adapter.get_usage_stats()
        print(f"  总调用次数: {usage['total_calls']}")
        print(f"  Prompt Tokens: {usage['total_prompt_tokens']:,}")
        print(f"  Completion Tokens: {usage['total_completion_tokens']:,}")
        print(f"  总 Tokens: {usage['total_tokens']:,}")
        
        print(f"\n[工具系统]")
        print(f"  已加载工具数: {len(self.tools)}")
        for t in self.tools:
            status = "✓" if hasattr(t, 'enabled') and t.enabled else "✓"
            print(f"    {status} {t.name}: {t.description[:30]}...")
        
        print(f"\n[记忆系统]")
        print(f"  短期记忆 (SQLite): {len(self.short_term.list_sessions())} 个会话")
        print(f"  长期记忆 (Chroma): {'可用' if self.long_term.is_available else '不可用'}, {self.long_term.count()} 条记录")
        print(f"  技能库: {len(self.skill_memory.list_all())} 个技能")

        # 自感知状态
        if hasattr(self.agent, 'self_awareness') and self.agent.self_awareness:
            sa = self.agent.self_awareness
            sa_stats = sa.get_stats()
            health = sa.health_check()
            diagnosis = sa.get_diagnosis()

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
            print(f"  运行时长: {agent_stats['uptime_seconds']:.0f}s")

            tool_stats = sa_stats.get("tools", {})
            if tool_stats:
                print(f"  工具统计:")
                for name, ts in tool_stats.items():
                    icon = "✅" if ts["success_rate"] >= 0.8 else "⚠️" if ts["success_rate"] >= 0.5 else "❌"
                    print(f"    {icon} {name}: {ts['call_count']}次, 成功率{ts['success_rate']:.0%}, 平均{ts['avg_time_ms']:.0f}ms")

            # 资源感知
            resource = sa_stats.get("resource", {})
            if resource:
                res_icon = "✅" if resource["status"] == "ok" else "⚠️" if resource["status"] == "warning" else "🔴"
                print(f"  上下文窗口: {res_icon} {resource['current_total_tokens']:,}/{resource['context_limit']:,} "
                      f"({resource['usage_ratio']:.1%})")

            # 状态模型
            state_model = sa_stats.get("state_model", {})
            if state_model:
                print(f"  疲劳度: {state_model['fatigue_score']:.2f}, "
                      f"连续错误: {state_model['consecutive_errors']}, "
                      f"建议延迟: {state_model['recommended_delay_ms']}ms")

            # 能力画像
            profile = sa_stats.get("capability_profile", {})
            if profile:
                print(f"  能力画像:")
                for task_type, ps in profile.items():
                    icon = "✅" if ps["proficiency"] in ("expert", "proficient") else "⚠️" if ps["proficiency"] == "learning" else "❌"
                    print(f"    {icon} {task_type}: {ps['count']}次, 成功率{ps['success_rate']:.0%}, "
                          f"熟练度={ps['proficiency']}")

            if diagnosis:
                print(f"  诊断建议:")
                for d in diagnosis:
                    print(f"    {d}")

        # 自组织状态
        if hasattr(self.agent, 'thinking_strategy') and self.agent.thinking_strategy:
            print(f"\n[自组织模块]")
            print(f"  思维策略: {self.agent.thinking_strategy.get_strategy_name('analytical')} 等 {len(self.agent.thinking_strategy.STRATEGIES)} 种")
            print(f"  工作流预设: {len(self.agent.workflow_selector.WORKFLOW_PRESETS)} 种")
            print(f"  任务执行器: 就绪 (最大并发={self.agent.task_executor.max_workers})")
            print(f"  错误恢复策略: {len(ErrorRecoveryStrategy.STRATEGIES)} 种工具策略")

        # 元认知状态
        if hasattr(self.agent, 'metacognition') and self.agent.metacognition:
            print(f"\n[元认知模块]")
            print(f"  置信度评估: 就绪")
            print(f"  一致性检测: 就绪")
            print(f"  回答质量评估: 就绪")
            print(f"  推理链记录: {len(self.agent.metacognition.get_reasoning_chain())} 条")

        # P2-6: 情感引擎状态
        if hasattr(self.agent, 'emotion_engine') and self.agent.emotion_engine:
            snap = self.agent.emotion_engine.get_state_snapshot()
            if snap.get("enabled"):
                p = snap["pleasure"]
                a = snap["arousal"]
                d = snap["dominance"]
                # 简易心情标签
                if p > 0.3:
                    mood = "开心"
                elif p < -0.3:
                    mood = "低落"
                elif a > 0.5:
                    mood = "兴奋"
                elif a < -0.3:
                    mood = "平静"
                else:
                    mood = "中性"
                print(f"\n[情感引擎]")
                print(f"  当前心情: {mood}")
                print(f"  PAD: P={p:+.2f} A={a:+.2f} D={d:+.2f}")
                print(f"  交互次数: {snap['interaction_count']}")
            else:
                print(f"\n[情感引擎] 已禁用")

        print(f"\n[QQ 机器人]")
        qq_running = hasattr(self, "_qq_bot") and self._qq_bot and hasattr(self, "_qq_bot_thread") and self._qq_bot_thread.is_alive()
        print(f"  状态: {'运行中' if qq_running else '已停止'}")
        if qq_running and hasattr(self, "_qq_bot"):
            try:
                qq_status = self._qq_bot.get_status()
                print(f"  连接状态: {'已连接' if qq_status['connected'] else '未连接'}")
                print(f"  Session ID: {qq_status['session_id'] or '无'}")
                print(f"  消息序号: {qq_status['seq']}")
                print(f"  Intent: {qq_status['intent']}")
                print(f"  沙箱模式: {'是' if qq_status['sandbox'] else '否'}")
                print(f"  已处理消息数: {qq_status['processed_messages']}")
                print(f"  重连延迟: {qq_status['reconnect_delay']}s")
            except Exception as e:
                self.logger.warning(f"QQ 状态展示失败: {e}")
        
        print(f"\n[用户画像]")
        stats = self.user_profile.get("stats", {})
        print(f"  交互次数: {stats.get('total_interactions', 0)}")
        
        print("\n" + "=" * 60)

    def _reload_tools(self) -> None:
        """热更新工具列表"""
        try:
            self.logger.info("开始热更新工具...")
            
            import importlib
            import castorice.tools.base_tools as base_tools
            import castorice.tools.web_tools as web_tools
            
            importlib.reload(base_tools)
            importlib.reload(web_tools)
            
            tools_raw_cfg = self.config.raw().get("tools", {})
            new_tools = base_tools.get_base_tools(tools_raw_cfg)
            
            if hasattr(self, 'agent') and self.agent:
                result = self.agent.reload_tools(new_tools)
                
                self.tools = new_tools
                
                print("工具热更新完成！")
                print(f"  新增: {len(result['added'])} 个")
                if result['added']:
                    print(f"    - {', '.join(result['added'])}")
                print(f"  删除: {len(result['removed'])} 个")
                if result['removed']:
                    print(f"    - {', '.join(result['removed'])}")
                print(f"  保留: {result['kept']} 个")
                print(f"  总数: {result['total']} 个")
            else:
                self.tools = new_tools
                print(f"工具已重新加载，总数: {len(self.tools)} 个")
            
            self.logger.info(f"工具热更新完成: {len(self.tools)} 个工具")
            
        except Exception as e:
            self.logger.error(f"工具热更新失败: {e}")
            print(f"工具热更新失败: {e}")

    def qq_bot_mode(self) -> None:
        """QQ 机器人模式：启动并持续运行"""
        self.logger.info("=" * 60)
        self.logger.info("Castorice Agent - QQ 机器人模式")
        self.logger.info("=" * 60)

        if not self._start_qq_bot():
            self.logger.error("QQ 机器人启动失败")
            return

        self.logger.info("QQ 机器人已启动，按 Ctrl+C 退出")
        try:
            import time
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            self.logger.info("\n正在停止 QQ 机器人...")
        finally:
            self.cleanup()


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
        choices=["test", "interactive", "batch", "qq"],
        default="interactive",
        help="运行模式: test=测试连接, interactive=交互对话, batch=批量任务, qq=QQ机器人",
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

    try:
        if args.mode == "test":
            engine.test()
        elif args.mode == "batch":
            if not args.input:
                print("批量模式需要 --input 参数", file=sys.stderr)
                return 1
            engine.batch(args.input)
        elif args.mode == "qq":
            engine.qq_bot_mode()
        else:
            engine.interactive()
    finally:
        engine.cleanup()

    return 0


if __name__ == "__main__":
    sys.exit(main())
