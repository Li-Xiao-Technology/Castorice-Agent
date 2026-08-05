"""
CastoriceEngine - 引擎工厂

统一管理 Agent 各组件的初始化和清理。
"""
import logging
import os
import signal
import threading
from typing import Any, Dict, List, Optional

from castorice.config import get_config
from castorice.model_adapter import ModelAdapter
from castorice.agent import CastoriceAgent
from castorice.tools.base_tools import Tool, get_base_tools, _registered_tools
from castorice.memory.short_term import ShortTermMemory
from castorice.memory.skill import SkillMemory
from castorice.memory.user_profile import UserProfile
from castorice.memory.long_term import LongTermMemory
from castorice.alerts import init_alerts_from_config
from castorice.cost_budget import CostBudget, BudgetConfig
from castorice.storage import create_personastore, Personastore


class CastoriceEngine:
    """Castorice Agent 引擎工厂类，统一管理各组件"""

    def __init__(self):
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
        """实际初始化逻辑"""
        self.config = get_config()

        llm_cfg = self.config.llm if hasattr(self.config, "llm") else {}
        self.model_adapter = ModelAdapter(llm_cfg)
        self.logger.info(f"模型适配器: {self.model_adapter.provider}")

        # P1-4: 成本闸初始化
        try:
            raw_cfg = self.config.raw()
            budget_raw = (raw_cfg.get("runtime", {}) or {}).get("cost_budget", {}) or {}
            budget_cfg = BudgetConfig()
            for k, v in budget_raw.items():
                if hasattr(budget_cfg, k) and v is not None:
                    try:
                        setattr(budget_cfg, k, type(getattr(budget_cfg, k))(v))
                    except (TypeError, ValueError):
                        pass
            self.cost_budget = CostBudget(budget_cfg)
        except Exception as e:
            self.logger.warning(f"成本闸初始化失败（将使用无限制默认值）: {e}")
            self.cost_budget = CostBudget()

        # 把成本闸挂到 model_adapter 上，每次 LLM 调用自动记录
        self.model_adapter.cost_budget = self.cost_budget

        tools_raw_cfg = self.config.raw().get("tools", {})
        self.tools: List[Tool] = get_base_tools(tools_raw_cfg)

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

        try:
            from castorice.plugin import get_plugin_manager
            self.plugin_manager = get_plugin_manager()
            plugins_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "plugins")
            if not os.path.exists(plugins_dir):
                self._init_plugins_dir(plugins_dir)
            loaded = self.plugin_manager.load_plugins_from_dir(plugins_dir)
            if loaded > 0:
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

        try:
            yaml_tool_names = set()
            tools_cfg_dict = self.config.raw().get("tools", {}) or {}
            for k, v in tools_cfg_dict.items():
                if isinstance(v, dict) and v.get("enabled", False):
                    yaml_tool_names.add(k)
            actual_tool_names = set(_registered_tools.keys())
            missing_in_yaml = actual_tool_names - yaml_tool_names
            extra_in_yaml = yaml_tool_names - actual_tool_names
            if missing_in_yaml:
                self.logger.info(
                    f"工具同步: YAML 缺失 {len(missing_in_yaml)} 个工具配置 "
                    f"(已自动启用): {sorted(missing_in_yaml)[:10]}{'...' if len(missing_in_yaml) > 10 else ''}"
                )
            if extra_in_yaml:
                self.logger.warning(
                    f"工具同步: YAML 配置了但未注册的工具: {sorted(extra_in_yaml)}"
                )
        except Exception as e:
            self.logger.debug(f"工具同步检查失败: {e}")

        mem_cfg = self.config.memory if hasattr(self.config, "memory") else {}
        short_cfg = mem_cfg.get("short_term", {}) if isinstance(mem_cfg, dict) else {}
        long_cfg = mem_cfg.get("long_term", {}) if isinstance(mem_cfg, dict) else {}
        skill_cfg = mem_cfg.get("skill", {}) if isinstance(mem_cfg, dict) else {}

        self.short_term = ShortTermMemory(
            db_path=short_cfg.get("db_path", "./castorice_data/sessions.db"),
            max_turns=short_cfg.get("max_turns", 20),
        )
        self.long_term = None
        self._long_term_ready = threading.Event()
        self._init_long_term_async(long_cfg)
        self.skill_memory = SkillMemory(
            storage_path=skill_cfg.get("storage_path", "./castorice_data/skill_library.json"),
        )

        profile_cfg = self.config.user_profile if hasattr(self.config, "user_profile") else {}
        profile_path = profile_cfg.get("storage_path", "./castorice_data/user_profile.json") if isinstance(profile_cfg, dict) else "./castorice_data/user_profile.json"
        self.user_profile = UserProfile(storage_path=profile_path)

        self.alert_manager = init_alerts_from_config(self.config.raw())
        channel_count = len(self.alert_manager._channels)
        if channel_count > 0:
            self.logger.info(f"告警系统已初始化: {channel_count} 个渠道")

        # P5: 去中心化人格数据主权（Personastore）
        self.personastore: Optional[Personastore] = None
        try:
            raw_cfg = self.config.raw()
            ps_raw = ((raw_cfg.get("runtime", {}) or {}).get("personastore", {})) or {}
            if ps_raw.get("enabled", True):
                backend = ps_raw.get("backend", "local_sqlite")
                data_dir = ps_raw.get("data_dir", "./castorice_data")
                max_exp = int(ps_raw.get("max_experiences", 10000))
                self.personastore = create_personastore(
                    backend=backend,
                    data_dir=data_dir,
                    max_experiences=max_exp,
                )
                self.logger.info(
                    f"Personastore 已初始化: backend={backend}, data_dir={data_dir}"
                )
            else:
                self.logger.info("Personastore 未启用（配置中 disabled）")
        except Exception as e:
            self.logger.warning(f"Personastore 初始化失败（不影响主流程）: {e}")
            self.personastore = None

        self.agent = CastoriceAgent(
            model_adapter=self.model_adapter,
            tools=self.tools,
            short_term_memory=self.short_term,
            long_term_memory=self.long_term,
            skill_memory=self.skill_memory,
            user_profile=self.user_profile,
            config=self.config,
        )

        # P4: 人格画像生成器
        try:
            from castorice.personality_profile import PersonalityProfiler
            self.personality_profiler = PersonalityProfiler(engine=self)
            self.logger.info("人格画像生成器已初始化")
        except Exception as e:
            self.logger.warning(f"人格画像生成器初始化失败: {e}")
            self.personality_profiler = None

        # P4: 目标管理器
        try:
            from castorice.goal_manager import GoalManager
            self.goal_manager = GoalManager(
                db_path="./castorice_data/goals.db",
                engine=self,
            )
            self.logger.info("目标管理器已初始化")
        except Exception as e:
            self.logger.warning(f"目标管理器初始化失败: {e}")
            self.goal_manager = None

        # P4: MCP 客户端
        try:
            from castorice.mcp_client import MCPClient, MCPServerConfig
            self.mcp_client = MCPClient()
            # 从配置加载 MCP 服务器
            mcp_cfg = getattr(self.config, 'mcp_servers', None) or []
            if isinstance(mcp_cfg, list):
                for s in mcp_cfg:
                    if isinstance(s, dict) and s.get("name") and s.get("command"):
                        try:
                            self.mcp_client.add_server(MCPServerConfig(
                                name=s["name"],
                                command=s["command"],
                                args=s.get("args", []),
                                env=s.get("env", {}),
                                cwd=s.get("cwd"),
                            ))
                        except Exception as e:
                            self.logger.warning(f"加载 MCP 服务器 {s.get('name')} 失败: {e}")
        except Exception as e:
            self.logger.warning(f"MCP 客户端初始化失败: {e}")
            self.mcp_client = None

        self.logger.info("CastoriceEngine 初始化完成")

        signal.signal(signal.SIGINT, self._signal_handler)
        try:
            signal.signal(signal.SIGTERM, self._signal_handler)
        except (AttributeError, ValueError):
            pass

        self._bg_services = {}
        self._bg_threads = {}

        self._init_eigenflux()

    def _init_eigenflux(self) -> None:
        """初始化 EigenFlux 集成分支"""
        self.eigenflux = {"available": False, "path": None, "authenticated": False, "version": None}
        self._eigenflux_last_check = 0.0
        try:
            from castorice.tools.eigenflux_tool import _find_eigenflux
            import subprocess
            import json
            import time

            exe = _find_eigenflux()
            if not exe:
                self.logger.info("EigenFlux: 未安装，跳过集成")
                return

            self.eigenflux["path"] = exe
            self.eigenflux["available"] = True

            # 1. 用 doctor 检测版本
            try:
                result = subprocess.run(
                    [exe, "doctor", "--format", "json"],
                    capture_output=True, text=True, timeout=15,
                    encoding="utf-8", errors="replace",
                )
                if result.returncode == 0 and result.stdout.strip():
                    info = json.loads(result.stdout.strip())
                    self.eigenflux["version"] = info.get("cli_version")
            except Exception:
                pass

            # 2. 用 profile show 检测认证状态（比 doctor 更准确）
            try:
                result2 = subprocess.run(
                    [exe, "profile", "show", "--format", "json", "--no-interactive"],
                    capture_output=True, text=True, timeout=15,
                    encoding="utf-8", errors="replace",
                )
                if result2.returncode == 0 and result2.stdout.strip():
                    info2 = json.loads(result2.stdout.strip())
                    if isinstance(info2, dict) and info2.get("profile"):
                        self.eigenflux["authenticated"] = True
            except Exception:
                pass

            self._eigenflux_last_check = time.time()

            self.logger.info(
                f"EigenFlux: 已就绪 (v{self.eigenflux['version'] or '?'}, "
                f"auth={'是' if self.eigenflux['authenticated'] else '否'})"
            )
        except Exception as e:
            self.logger.debug(f"EigenFlux 初始化失败: {e}")

    def _init_long_term_async(self, long_cfg: Dict[str, Any]) -> None:
        """异步初始化长期记忆（ChromaDB 可能很慢，不阻塞 HTTP 服务启动）"""
        def _init():
            try:
                self.logger.info("长期记忆初始化中（后台线程，不阻塞服务启动）...")
                self.long_term = LongTermMemory(
                    persist_directory=long_cfg.get("persist_directory", "./castorice_data/chroma_db"),
                    collection_name=long_cfg.get("collection_name", "castorice_long_term"),
                )
                if getattr(self.long_term, "_available", False):
                    self.logger.info("长期记忆初始化完成")
                else:
                    self.logger.warning("长期记忆初始化失败，相关功能将不可用")
            except Exception as e:
                self.logger.warning(f"长期记忆初始化异常: {e}")
            finally:
                self._long_term_ready.set()

        t = threading.Thread(target=_init, name="LongTermMemoryInit", daemon=True)
        t.start()

    def _refresh_eigenflux_auth(self) -> None:
        """刷新 EigenFlux 认证状态（带缓存，避免频繁调用）"""
        import time
        if not self.eigenflux.get("available"):
            return
        now = time.time()
        if now - self._eigenflux_last_check < 60:
            return
        self._eigenflux_last_check = now
        try:
            import subprocess
            import json
            exe = self.eigenflux.get("path")
            if not exe:
                return
            result = subprocess.run(
                [exe, "profile", "show", "--format", "json", "--no-interactive"],
                capture_output=True, text=True, timeout=10,
                encoding="utf-8", errors="replace",
            )
            if result.returncode == 0 and result.stdout.strip():
                info = json.loads(result.stdout.strip())
                if isinstance(info, dict) and info.get("profile"):
                    self.eigenflux["authenticated"] = True
                else:
                    self.eigenflux["authenticated"] = False
            else:
                self.eigenflux["authenticated"] = False
        except Exception:
            pass

    def get_eigenflux_status(self) -> Dict[str, Any]:
        """获取 EigenFlux 状态（会定期刷新认证状态）"""
        if not hasattr(self, "eigenflux"):
            return {"available": False}
        self._refresh_eigenflux_auth()
        return dict(self.eigenflux)

    def _init_plugins_dir(self, plugins_dir: str) -> None:
        """初始化默认插件目录 + 示例插件"""
        try:
            os.makedirs(plugins_dir, exist_ok=True)
            init_path = os.path.join(plugins_dir, "__init__.py")
            if not os.path.exists(init_path):
                with open(init_path, "w", encoding="utf-8") as f:
                    f.write("# Castorice Agent 插件目录\n# 在此放置 .py 文件即可被自动加载\n")

            example_path = os.path.join(plugins_dir, "example_plugin.py")
            if not os.path.exists(example_path):
                with open(example_path, "w", encoding="utf-8") as f:
                    f.write('''"""
示例插件 - 演示如何为 Castorice Agent 编写插件
"""
from castorice.plugin import register_plugin_tool

@register_plugin_tool("plugin_example", "示例插件工具：返回问候语")
def plugin_example(name: str = "世界") -> str:
    return f"你好，{name}！这是一个示例插件工具。"

__plugin_info__ = {
    "name": "example_plugin",
    "version": "1.0.0",
    "description": "示例插件",
    "tools": ["plugin_example"],
}
''')
        except Exception as e:
            self.logger.warning(f"初始化插件目录失败: {e}")

    def _signal_handler(self, sig, frame) -> None:
        """信号处理器"""
        self.logger.info(f"收到信号 {sig}，正在优雅退出...")
        self.cleanup()
        import sys
        sys.exit(0)

    def cleanup(self) -> None:
        """清理资源"""
        if hasattr(self, 'personastore') and self.personastore is not None:
            try:
                self.personastore.close()
            except Exception:
                pass
        if hasattr(self, 'short_term'):
            try:
                self.short_term.close()
            except Exception:
                pass
        if hasattr(self, 'long_term'):
            try:
                self.long_term.close()
            except Exception:
                pass
        if hasattr(self, 'model_adapter'):
            try:
                self.model_adapter.close()
            except Exception:
                pass
        if hasattr(self, 'agent'):
            for attr_name in ('autobiographical', 'action_queue', 'social_relation',
                              'experience_journal', 'intent_tracker'):
                obj = getattr(self.agent, attr_name, None)
                if obj is not None and hasattr(obj, 'close'):
                    try:
                        obj.close()
                    except Exception:
                        pass
        self.logger.info("资源清理完成")

    def run_interactive(self) -> None:
        """运行交互式模式"""
        from .cli_handler import CLIHandler
        CLIHandler(self).run_interactive()

    def run_http_server(self) -> None:
        """运行 HTTP 服务"""
        from .http_server import HttpServer

        # 启动后台服务（意识引擎、自主循环等）
        self.start_service("consciousness")
        self.start_service("auto")

        http_cfg = {}
        if hasattr(self.config, 'http_server'):
            http_cfg = self.config.http_server or {}
        host = http_cfg.get("host", "127.0.0.1") if isinstance(http_cfg, dict) else "127.0.0.1"
        port = int(http_cfg.get("port", 5477)) if isinstance(http_cfg, dict) else 5477
        require_auth = bool(http_cfg.get("require_auth", False)) if isinstance(http_cfg, dict) else False
        cors_origins = http_cfg.get("cors_origins") if isinstance(http_cfg, dict) else None
        api_keys = http_cfg.get("api_keys") if isinstance(http_cfg, dict) else None

        server = HttpServer(self)
        self.logger.info(f"HTTP 服务器配置: host={host}, port={port}, auth={require_auth}")
        server.run()

    def run_qq_bot(self) -> None:
        """运行 QQ 机器人"""
        from .qq_bot import QQBot
        QQBot(self).run()

    def run_cron(self) -> None:
        """运行定时任务"""
        from .cron_scheduler import CronScheduler
        CronScheduler(self).run()

    def start_service(self, service_name: str) -> bool:
        """在后台线程启动服务

        Args:
            service_name: "qq", "http", "cron" 之一

        Returns:
            True 表示成功启动，False 表示已运行或启动失败
        """
        if service_name in self._bg_services:
            self.logger.warning(f"服务 {service_name} 已在运行")
            return False

        try:
            if service_name == "qq":
                from .qq_bot import QQBot
                service = QQBot(self)
                self._bg_services["qq"] = service
                thread = threading.Thread(target=service.run, daemon=True, name="QQBot")
                thread.start()
                self._bg_threads["qq"] = thread
                self.logger.info("QQ 机器人已在后台启动")
                return True
            elif service_name == "http":
                from .http_server import HttpServer
                http_cfg = {}
                if hasattr(self.config, 'http_server'):
                    http_cfg = self.config.http_server or {}
                host = http_cfg.get("host", "127.0.0.1") if isinstance(http_cfg, dict) else "127.0.0.1"
                port = int(http_cfg.get("port", 5477)) if isinstance(http_cfg, dict) else 5477
                require_auth = bool(http_cfg.get("require_auth", False)) if isinstance(http_cfg, dict) else False
                cors_origins = http_cfg.get("cors_origins") if isinstance(http_cfg, dict) else None
                api_keys = http_cfg.get("api_keys") if isinstance(http_cfg, dict) else None
                service = HttpServer(self)
                self._bg_services["http"] = service
                thread = threading.Thread(target=service.run, daemon=True, name="HttpServer")
                thread.start()
                self._bg_threads["http"] = thread
                self.logger.info(f"HTTP 服务器已在后台启动 (port={port})")
                return True
            elif service_name == "cron":
                from .cron_scheduler import CronScheduler
                service = CronScheduler(self)
                self._bg_services["cron"] = service
                thread = threading.Thread(target=service.run, daemon=True, name="CronScheduler")
                thread.start()
                self._bg_threads["cron"] = thread
                self.logger.info("定时任务调度器已在后台启动")
                return True
            elif service_name == "auto":
                from castorice.agent.autonomous_loop import AutonomousLoop
                service = AutonomousLoop(self)
                self._bg_services["auto"] = service
                thread = threading.Thread(target=service.run, daemon=True, name="AutonomousLoop")
                thread.start()
                self._bg_threads["auto"] = thread
                self.logger.info("自主循环已在后台启动")
                return True
            elif service_name == "consciousness":
                from castorice.agent.consciousness import ConsciousnessEngine
                service = ConsciousnessEngine(self)
                self._bg_services["consciousness"] = service
                self.consciousness = service
                if hasattr(self, "agent") and self.agent:
                    self.agent.consciousness = service
                thread = threading.Thread(target=service.run, daemon=True, name="ConsciousnessEngine")
                thread.start()
                self._bg_threads["consciousness"] = thread
                self.logger.info("意识引擎已在后台启动")
                return True
            elif service_name == "telegram":
                from castorice.adapters.telegram_bot import TelegramBotAdapter, TelegramBotConfig
                tg_cfg = getattr(self.config, 'telegram', None) or {}
                if isinstance(tg_cfg, dict) and tg_cfg.get("bot_token"):
                    config = TelegramBotConfig(
                        bot_token=tg_cfg["bot_token"],
                        allowed_chat_ids=tg_cfg.get("allowed_chat_ids"),
                        allowed_usernames=tg_cfg.get("allowed_usernames"),
                    )
                    service = TelegramBotAdapter(config, engine=self)
                    self._bg_services["telegram"] = service
                    self.telegram_bot = service
                    thread = threading.Thread(target=service.start_in_thread, daemon=True, name="TelegramBot")
                    thread.start()
                    self._bg_threads["telegram"] = thread
                    self.logger.info("Telegram Bot 已在后台启动")
                    return True
                else:
                    self.logger.warning("Telegram Bot 未配置 bot_token，无法启动")
                    return False
            else:
                self.logger.warning(f"未知服务: {service_name}")
                return False
        except Exception as e:
            self.logger.error(f"启动服务 {service_name} 失败: {e}")
            self._bg_services.pop(service_name, None)
            self._bg_threads.pop(service_name, None)
            return False

    def stop_service(self, service_name: str) -> bool:
        """停止后台服务

        Args:
            service_name: "qq", "http", "cron" 之一

        Returns:
            True 表示成功停止，False 表示未运行或停止失败
        """
        if service_name not in self._bg_services:
            self.logger.warning(f"服务 {service_name} 未运行")
            return False

        try:
            service = self._bg_services[service_name]
            if hasattr(service, 'stop'):
                service.stop()
            self._bg_services.pop(service_name)
            thread = self._bg_threads.pop(service_name, None)
            if thread and thread.is_alive():
                thread.join(timeout=5)
            self.logger.info(f"服务 {service_name} 已停止")
            return True
        except Exception as e:
            self.logger.error(f"停止服务 {service_name} 失败: {e}")
            return False

    def stop_all_services(self) -> None:
        """停止所有后台服务"""
        for name in list(self._bg_services.keys()):
            self.stop_service(name)

    def get_service_status(self) -> Dict[str, Any]:
        """获取所有后台服务状态"""
        status = {}
        for name in ["qq", "http", "cron", "auto", "consciousness"]:
            service = self._bg_services.get(name)
            if service and hasattr(service, 'is_running') and callable(service.is_running):
                running = service.is_running()
            else:
                thread = self._bg_threads.get(name)
                running = thread is not None and thread.is_alive()
            info = {"status": "running" if running else "stopped"}
            if service and hasattr(service, 'get_status_info') and callable(service.get_status_info):
                info.update(service.get_status_info())
            status[name] = info
        return status