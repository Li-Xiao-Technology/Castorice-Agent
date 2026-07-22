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
        self.long_term = LongTermMemory(
            persist_directory=long_cfg.get("persist_directory", "./castorice_data/chroma_db"),
            collection_name=long_cfg.get("collection_name", "castorice_long_term"),
        )
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

        signal.signal(signal.SIGINT, self._signal_handler)
        try:
            signal.signal(signal.SIGTERM, self._signal_handler)
        except (AttributeError, ValueError):
            pass

        self._tool_watcher = None
        self._start_tool_watcher()

        self._bg_services = {}
        self._bg_threads = {}

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

    def _start_tool_watcher(self) -> None:
        """启动工具文件监控器（自动热更新）"""
        try:
            from castorice.tools.watcher import ToolFileWatcher
            tools_dir = os.path.join(os.path.dirname(__file__), "tools")
            if os.path.exists(tools_dir):
                self._tool_watcher = ToolFileWatcher(
                    tools_dir,
                    callback=self._on_tool_changed,
                    poll_interval=5,
                )
                self._tool_watcher.start()
                self.logger.info("工具文件监控器已启动")
        except Exception as e:
            self.logger.debug(f"启动工具文件监控器失败: {e}")

    def _on_tool_changed(self, changed_files: List[str]) -> None:
        """工具文件变更回调"""
        self.logger.info(f"检测到工具文件变更: {changed_files}")
        try:
            from castorice.tools.base_tools import reload_tools
            reload_tools()
            self.tools = get_base_tools(self.config.raw().get("tools", {}))
            self.agent.tools_list = self.tools
            self.agent.available_tools_desc = "\n".join(f"- {t.name}: {t.description}" for t in self.tools)
            self.logger.info("工具已重新加载")
        except Exception as e:
            self.logger.warning(f"重新加载工具失败: {e}")

    def _signal_handler(self, sig, frame) -> None:
        """信号处理器"""
        self.logger.info(f"收到信号 {sig}，正在优雅退出...")
        self.cleanup()
        import sys
        sys.exit(0)

    def cleanup(self) -> None:
        """清理资源"""
        if hasattr(self, '_tool_watcher') and self._tool_watcher:
            try:
                self._tool_watcher.stop()
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
        HttpServer(self).run()

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
                service = HttpServer(self)
                self._bg_services["http"] = service
                thread = threading.Thread(target=service.run, daemon=True, name="HttpServer")
                thread.start()
                self._bg_threads["http"] = thread
                self.logger.info("HTTP 服务器已在后台启动")
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
        for name in ["qq", "http", "cron"]:
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