"""
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
