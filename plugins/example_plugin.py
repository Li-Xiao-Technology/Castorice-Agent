"""
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
