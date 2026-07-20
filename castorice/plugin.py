"""
插件系统模块

支持动态加载外部工具插件：
- 从目录加载 .py 文件
- 从 URL 加载远程插件
- 插件元数据管理
- 热加载支持
"""

import importlib.util
import logging
import os
import sys
import time
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

            try:
                spec.loader.exec_module(module)
                sys.modules[module_name] = module
            except Exception:
                raise

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
