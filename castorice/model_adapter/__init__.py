"""
统一模型适配层 (ModelAdapter)

自研多模型兼容层：
- 不依赖 LangChain 任何分包
- 直接调用各厂商官方 SDK
- 支持 OpenAI 协议兼容（Ollama / OpenRouter / 通义千问 / 千帆 等）

支持的 provider:
- openai      : OpenAI 官方（兼容 通义千问 / 百度千帆 等）
- anthropic   : Claude 官方
- ollama      : 本地大模型（OpenAI 协议）
- openrouter  : 多模型聚合（OpenAI 协议）
- gemini      : Google Gemini 官方 SDK
- qwen        : 阿里云通义千问官方 SDK

设计理念：
1. **统一接口**：通过 chat() 抽象方法统一所有供应商
2. **官方 SDK 优先**：用各厂商官方 SDK，不引入中间层
3. **协议兼容**：OpenAI 兼容协议下统一用 openai SDK
4. **动态加载**：SDK 按需导入，不强制依赖
"""

from .common import ToolCall, ChatMessage, ChatResponse
from .adapter import ModelAdapter

__all__ = ["ToolCall", "ChatMessage", "ChatResponse", "ModelAdapter"]
