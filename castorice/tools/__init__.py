"""
工具层 - 精简版，不依赖 LangChain BaseTool
提供 6 个基础工具：web_search / read_file / write_file / terminal / python_repl / read_document
"""
from castorice.tools.base_tools import Tool, get_base_tools

__all__ = ["Tool", "get_base_tools"]
