"""
Castorice Agent 核心包

将原 agent.py 拆分为多个子模块：
- core: 主循环 + State + 初始化
- prompt_builder: system prompt 构建
- tool_loop: 工具调用循环
- memory_ops: 记忆操作

保持向后兼容：从包根导入 CastoriceAgent 与之前一致
"""
from .core import CastoriceAgent, State

__all__ = ["CastoriceAgent", "State"]