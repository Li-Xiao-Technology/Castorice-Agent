"""
插件系统模块

支持动态加载外部工具插件：
- 从目录加载 .py 文件
- 从 URL 加载远程插件
- 插件元数据管理
- 热加载支持
"""

import importlib.util
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Callable, Any

logger = logging.getLogger("Castorice.Plugin")


class PluginInfo:
    """插件元信息"""
    
    def __init__(self, name: str, version: str = "1.0.0", 
                 description: str = "", author: str = "", 
                 tools: List[str] = None):
        self.name = name
        self.version = version
        self.description = description
        self.author = author
        self.tools = tools or []
        self.load_time = time.time()
        self.path = ""


class PluginManager:
    """插件管理器"""
    
    def __init__(self):
        self._plugins: Dict[str, PluginInfo] = {}
        self._loaded_tools: Dict[str, Callable] = {}
        self._plugin_dirs: List[str] = []
    
    def add_plugin_dir(self, dir_path: str) -> None:
        """添加插件目录"""
        if os.path.isdir(dir_path):
            self._plugin_dirs.append(os.path.abspath(dir_path))
            logger.info(f"插件目录已添加: {dir_path}")
    
    # P0-3: 插件沙箱 - 禁用的危险内置函数名单（最小化沙箱）
    _SANDBOX_BLOCKED = {
        "system", "popen", "fork", "spawn", "spawnl", "spawnle",
        "spawnlp", "spawnlpe", "spawnv", "spawnve", "spawnvp", "spawnvpe",
        "execv", "execve", "execvp", "execvpe",
    }

    def load_plugin_from_file(self, file_path: str) -> bool:
        """从文件加载插件（P0-3: 最小化沙箱，限制 os 危险函数访问）"""
        if not os.path.isfile(file_path):
            logger.error(f"插件文件不存在: {file_path}")
            return False

        try:
            module_name = os.path.splitext(os.path.basename(file_path))[0]

            spec = importlib.util.spec_from_file_location(module_name, file_path)
            if spec is None:
                logger.error(f"无法解析插件文件: {file_path}")
                return False

            module = importlib.util.module_from_spec(spec)

            # P0-3: 最小化沙箱 - 包装 os 模块，拦截危险函数
            import os as _os
            class _SandboxedOS:
                def __getattr__(self, name):
                    if name in PluginManager._SANDBOX_BLOCKED:
                        raise PermissionError(f"插件沙箱: os.{name} 被禁用")
                    return getattr(_os, name)
            # 注入沙箱 os 到 module 全局命名空间，不污染全局 sys.modules['os']
            _sandboxed_os = _SandboxedOS()
            module.__dict__['os'] = _sandboxed_os

            # 同时拦截 from os import xxx 的 sys.modules 缓存路径
            _original_os = sys.modules.get('os')
            sys.modules['os'] = _sandboxed_os

            try:
                spec.loader.exec_module(module)
                sys.modules[module_name] = module
            except Exception:
                raise
            finally:
                # 恢复 sys.modules，避免污染全局
                if _original_os is not None:
                    sys.modules['os'] = _original_os
                elif 'os' in sys.modules:
                    del sys.modules['os']

            plugin_info = getattr(module, "__plugin_info__", None)
            if plugin_info and isinstance(plugin_info, dict):
                info = PluginInfo(
                    name=plugin_info.get("name", module_name),
                    version=plugin_info.get("version", "1.0.0"),
                    description=plugin_info.get("description", ""),
                    author=plugin_info.get("author", ""),
                    tools=plugin_info.get("tools", []),
                )
                info.path = file_path
                self._plugins[info.name] = info

                from castorice.tools.base_tools import register_tool

                for tool_name in info.tools:
                    func = getattr(module, tool_name, None)
                    if func and callable(func):
                        desc = getattr(func, "__tool_description__", f"插件工具: {tool_name}")
                        register_tool(name=tool_name, description=desc)(func)
                        self._loaded_tools[tool_name] = func

            logger.info(f"插件加载成功: {module_name}")
            return True
        except Exception as e:
            logger.error(f"插件加载失败 {file_path}: {e}")
            return False
    
    def load_plugins_from_dir(self, dir_path: str = None) -> int:
        """从目录加载所有插件"""
        if dir_path is None:
            dirs = self._plugin_dirs
        else:
            dirs = [dir_path]
        
        loaded_count = 0
        for plugin_dir in dirs:
            if not os.path.isdir(plugin_dir):
                continue
            for filename in os.listdir(plugin_dir):
                if filename.endswith(".py") and not filename.startswith("_"):
                    file_path = os.path.join(plugin_dir, filename)
                    if self.load_plugin_from_file(file_path):
                        loaded_count += 1
        
        return loaded_count
    
    def unload_plugin(self, plugin_name: str) -> bool:
        """卸载插件"""
        if plugin_name not in self._plugins:
            return False
        
        info = self._plugins[plugin_name]
        for tool_name in info.tools:
            if tool_name in self._loaded_tools:
                del self._loaded_tools[tool_name]
            
            from castorice.tools.base_tools import _registered_tools
            if tool_name in _registered_tools:
                del _registered_tools[tool_name]
        
        del self._plugins[plugin_name]
        logger.info(f"插件已卸载: {plugin_name}")
        return True
    
    def list_plugins(self) -> List[PluginInfo]:
        """列出所有已加载的插件"""
        return list(self._plugins.values())
    
    def get_plugin_info(self, plugin_name: str) -> Optional[PluginInfo]:
        """获取插件信息"""
        return self._plugins.get(plugin_name)
    
    def reload_plugin(self, plugin_name: str) -> bool:
        """重新加载插件"""
        info = self._plugins.get(plugin_name)
        if info and info.path:
            self.unload_plugin(plugin_name)
            return self.load_plugin_from_file(info.path)
        return False
    
    def reload_all(self) -> int:
        """重新加载所有插件"""
        paths = [(name, info.path) for name, info in self._plugins.items()]
        for name, _ in paths:
            self.unload_plugin(name)
        return sum(1 for _, path in paths if path and self.load_plugin_from_file(path))


_plugin_manager = None



def set_plugin_manager(instance: PluginManager) -> None:
    """手动设置全局 PluginManager 实例（Agent 初始化时调用，确保配置生效）"""
    global _plugin_manager
    _plugin_manager = instance
def get_plugin_manager() -> PluginManager:
    """获取全局插件管理器单例"""
    global _plugin_manager
    if _plugin_manager is None:
        _plugin_manager = PluginManager()
    return _plugin_manager


def register_plugin_tool(name: str, description: str):
    """
    插件工具注册装饰器
    
    使用示例：
    >>> @register_plugin_tool("my_tool", "我的自定义工具")
    >>> def my_tool(query: str) -> str:
    >>>     return f"处理: {query}"
    
    >>> __plugin_info__ = {
    >>>     "name": "my_plugin",
    >>>     "version": "1.0.0",
    >>>     "description": "我的插件",
    >>>     "author": "me",
    >>>     "tools": ["my_tool"],
    >>> }
    """
    def decorator(func):
        func.__tool_description__ = description
        return func
    return decorator


# ============================================================
# P2-1: 插件生命周期钩子标准接口 (PluginBase)
# ============================================================

class PluginBase:
    """
    插件基类：提供标准生命周期钩子

    插件作者继承此类，按需重写钩子方法即可。

    生命周期钩子（按调用顺序）：
    1. on_load()          —— 插件被加载时
    2. on_start()          —— Agent 启动时
    3. on_message()        —— 收到用户消息时（可修改消息）
    4. on_thought()        —— Agent 产生念头时
    5. on_action()         —— Agent 执行工具前
    6. on_action_result()  —— Agent 工具执行后
    7. on_response()       —— Agent 生成回复后（可修改回复）
    8. on_stop()           —— Agent 停止时
    9. on_unload()         —— 插件被卸载时

    使用示例：
        class MyPlugin(PluginBase):
            def on_load(self):
                self.logger.info("我的插件加载了")

            def on_message(self, message: str, context: dict) -> str:
                # 在用户消息前加前缀
                return f"[我的插件] {message}"

            def on_response(self, response: str, context: dict) -> str:
                return response + "\n\n—— 由我的插件处理"
    """

    def __init__(self):
        self.name = getattr(self, "name", self.__class__.__name__)
        self.version = getattr(self, "version", "1.0.0")
        self.logger = logging.getLogger(f"Castorice.Plugin.{self.name}")

    # ============== 生命周期钩子 ==============

    def on_load(self) -> None:
        """插件被加载时调用（一次）"""
        pass

    def on_start(self, engine: Any = None) -> None:
        """Agent 启动时调用"""
        pass

    def on_message(self, message: str, context: Optional[dict] = None) -> Optional[str]:
        """
        收到用户消息时调用

        返回值：
        - None: 不修改消息
        - str:  修改后的消息（替换原始消息）
        """
        return None

    def on_thought(self, thought: Any, context: Optional[dict] = None) -> None:
        """Agent 产生念头时调用"""
        pass

    def on_action(self, action_name: str, action_params: dict, context: Optional[dict] = None) -> Optional[bool]:
        """
        Agent 执行工具前调用

        返回值：
        - None: 不干预
        - True: 允许执行（默认）
        - False: 阻止执行
        """
        return None

    def on_action_result(
        self, action_name: str, action_params: dict, result: Any, context: Optional[dict] = None
    ) -> Optional[Any]:
        """
        Agent 工具执行后调用

        返回值：
        - None: 不修改结果
        - Any:  修改后的结果
        """
        return None

    def on_response(self, response: str, context: Optional[dict] = None) -> Optional[str]:
        """
        Agent 生成回复后调用

        返回值：
        - None: 不修改回复
        - str:  修改后的回复
        """
        return None

    def on_stop(self) -> None:
        """Agent 停止时调用"""
        pass

    def on_unload(self) -> None:
        """插件被卸载时调用"""
        pass

    # ============== 工具方法 ==============

    def register_tool(self, name: str, description: str, func: Callable) -> None:
        """插件注册工具"""
        from castorice.tools.base_tools import register_tool
        register_tool(name=name, description=description)(func)

    def get_state(self, key: str, default: Any = None) -> Any:
        """获取插件状态（持久化）"""
        state_path = Path(os.environ.get("CASTORICE_DATA_DIR", "./castorice_data")) / "plugin_states" / f"{self.name}.json"
        if state_path.exists():
            try:
                with open(state_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return data.get(key, default)
            except Exception:
                pass
        return default

    def set_state(self, key: str, value: Any) -> None:
        """设置插件状态（持久化）"""
        state_dir = Path(os.environ.get("CASTORICE_DATA_DIR", "./castorice_data")) / "plugin_states"
        state_dir.mkdir(parents=True, exist_ok=True)
        state_path = state_dir / f"{self.name}.json"
        data = {}
        if state_path.exists():
            try:
                with open(state_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                pass
        data[key] = value
        with open(state_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)


# ============== 扩展 PluginManager 支持生命周期钩子 ==============

def _patch_plugin_manager() -> None:
    """
    扩展 PluginManager：支持基于 PluginBase 的生命周期插件
    """
    original_load = PluginManager.load_plugin_from_file

    def enhanced_load(self, file_path: str) -> bool:
        success = original_load(self, file_path)
        if not success:
            return False

        # 检查模块中是否有 PluginBase 子类实例
        module_name = os.path.splitext(os.path.basename(file_path))[0]
        module = sys.modules.get(module_name)
        if module is None:
            return success

        for attr_name in dir(module):
            attr = getattr(module, attr_name)
            if (isinstance(attr, type)
                    and issubclass(attr, PluginBase)
                    and attr is not PluginBase):
                try:
                    instance = attr()
                    instance.on_load()
                    # 存储实例
                    if not hasattr(self, "_plugin_instances"):
                        self._plugin_instances = []
                    self._plugin_instances.append(instance)
                    logger.info(f"生命周期插件已加载: {instance.name} v{instance.version}")
                except Exception as e:
                    logger.error(f"生命周期插件初始化失败 {attr_name}: {e}")

        return success

    PluginManager.load_plugin_from_file = enhanced_load

    # 添加触发钩子的方法
    def trigger_hook(self, hook_name: str, *args, **kwargs) -> List[Any]:
        """触发所有插件的某个钩子，返回所有非 None 的返回值"""
        results = []
        instances = getattr(self, "_plugin_instances", [])
        for inst in instances:
            try:
                hook = getattr(inst, hook_name, None)
                if hook and callable(hook):
                    result = hook(*args, **kwargs)
                    if result is not None:
                        results.append(result)
            except Exception as e:
                logger.warning(f"插件钩子 {inst.name}.{hook_name} 执行失败: {e}")
        return results

    PluginManager.trigger_hook = trigger_hook


# 应用补丁
try:
    _patch_plugin_manager()
except Exception as e:
    logger.debug(f"PluginManager 补丁应用失败: {e}")
