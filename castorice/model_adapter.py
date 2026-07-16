"""
统一模型适配层 (ModelAdapter)

复刻 Hermes Agent 架构，自研多模型兼容层：
- 不依赖 LangChain 任何分包
- 直接调用 OpenAI / Anthropic 官方 SDK
- 支持 OpenAI 协议兼容（Ollama / OpenRouter / 通义千问 / 千帆 等）

设计理念：
1. **统一接口**：通过 _chat() 抽象方法统一所有供应商
2. **官方 SDK 优先**：用 openai / anthropic 官方 SDK，不引入中间层
3. **协议兼容**：OpenAI 兼容协议下统一用 openai SDK
"""

import json
from typing import Any, Dict, List, Optional

# 官方 SDK
try:
    from openai import OpenAI
except ImportError:
    OpenAI = None  # 提示用户安装

try:
    import anthropic
except ImportError:
    anthropic = None  # 提示用户安装

import httpx


class ChatMessage:
    """统一的对话消息结构（所有供应商通用）"""

    def __init__(self, role: str, content: str):
        self.role = role      # 'system' / 'user' / 'assistant'
        self.content = content

    def to_dict(self) -> Dict[str, str]:
        return {"role": self.role, "content": self.content}


class ChatResponse:
    """统一的模型回复结构"""

    def __init__(self, content: str, model: str, usage: Optional[Dict] = None):
        self.content = content
        self.model = model
        self.usage = usage or {}


class ModelAdapter:
    """
    统一模型适配器

    支持的 provider:
    - openai      : OpenAI 官方（兼容 通义千问 / 百度千帆 等）
    - anthropic   : Claude 官方
    - ollama      : 本地大模型（OpenAI 协议）
    - openrouter  : 多模型聚合（OpenAI 协议）
    """

    def __init__(self, llm_config: Dict[str, Any]):
        self.provider = llm_config.get("provider", "openai")
        self.temperature = llm_config.get("temperature", 0.7)
        self.max_tokens = llm_config.get("max_tokens", 4096)
        self.timeout = llm_config.get("timeout", 60)

        # 各 provider 配置
        self.openai_cfg = llm_config.get("openai", {})
        self.anthropic_cfg = llm_config.get("anthropic", {})
        self.ollama_cfg = llm_config.get("ollama", {})
        self.openrouter_cfg = llm_config.get("openrouter", {})

        # 懒加载客户端
        self._openai_client: Optional[OpenAI] = None
        self._anthropic_client = None

    def _get_openai_client(self, base_url: str, api_key: str) -> OpenAI:
        """懒加载 OpenAI 兼容客户端（OpenAI / Ollama / OpenRouter 共用）"""
        if OpenAI is None:
            raise ImportError("请安装 openai SDK: pip install openai")
        return OpenAI(
            api_key=api_key or "EMPTY",
            base_url=base_url,
            timeout=self.timeout,
        )

    def _get_anthropic_client(self):
        """懒加载 Anthropic 客户端"""
        if anthropic is None:
            raise ImportError("请安装 anthropic SDK: pip install anthropic")
        if self._anthropic_client is None:
            self._anthropic_client = anthropic.Anthropic(
                api_key=self.anthropic_cfg.get("api_key", ""),
                base_url=self.anthropic_cfg.get("base_url"),
                timeout=self.timeout,
            )
        return self._anthropic_client

    def chat(self, messages: List[ChatMessage]) -> ChatResponse:
        """
        统一对话接口

        参数：
            messages: 消息列表，按时间顺序

        返回：
            ChatResponse: 统一格式的回复
        """
        if self.provider == "openai":
            return self._chat_openai(messages, self.openai_cfg)
        elif self.provider == "anthropic":
            return self._chat_anthropic(messages)
        elif self.provider == "ollama":
            return self._chat_openai(messages, {
                "api_key": "ollama",
                "base_url": self.ollama_cfg.get("base_url", "http://localhost:11434/v1"),
                "model": self.ollama_cfg.get("model", "llama3.1:8b"),
            })
        elif self.provider == "openrouter":
            return self._chat_openai(messages, {
                "api_key": self.openrouter_cfg.get("api_key", ""),
                "base_url": self.openrouter_cfg.get("base_url", "https://openrouter.ai/api/v1"),
                "model": self.openrouter_cfg.get("model", "anthropic/claude-3.5-sonnet"),
            })
        else:
            raise ValueError(f"不支持的模型供应商: {self.provider}")

    def _chat_openai(self, messages: List[ChatMessage], cfg: Dict[str, Any]) -> ChatResponse:
        """OpenAI 兼容协议（OpenAI / Ollama / OpenRouter 等）"""
        client = self._get_openai_client(cfg.get("base_url", ""), cfg.get("api_key", ""))
        # 转换消息格式
        api_messages = [m.to_dict() for m in messages]

        # 调用 API
        response = client.chat.completions.create(
            model=cfg.get("model", "gpt-4o"),
            messages=api_messages,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
        )

        content = response.choices[0].message.content or ""
        usage = {}
        if hasattr(response, "usage") and response.usage:
            usage = {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            }
        return ChatResponse(content=content, model=response.model, usage=usage)

    def _chat_anthropic(self, messages: List[ChatMessage]) -> ChatResponse:
        """Anthropic Claude 官方 SDK"""
        client = self._get_anthropic_client()

        # Anthropic 消息格式：system 单独，user/assistant 交替
        system_msg = None
        chat_msgs = []
        for m in messages:
            if m.role == "system":
                system_msg = m.content
            else:
                chat_msgs.append({"role": m.role, "content": m.content})

        kwargs = {
            "model": self.anthropic_cfg.get("model", "claude-3-5-sonnet-20241022"),
            "messages": chat_msgs,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
        }
        if system_msg:
            kwargs["system"] = system_msg

        response = client.messages.create(**kwargs)
        content = ""
        if response.content:
            # Claude 返回的是列表，取第一个 text 块
            for block in response.content:
                if hasattr(block, "text"):
                    content += block.text

        usage = {
            "input_tokens": response.usage.input_tokens,
            "output_tokens": response.usage.output_tokens,
        } if hasattr(response, "usage") else {}
        return ChatResponse(content=content, model=response.model, usage=usage)

    def test_connection(self) -> Dict[str, Any]:
        """测试当前 LLM 连接"""
        try:
            response = self.chat([ChatMessage("user", "Say 'OK' only.")])
            return {
                "success": True,
                "provider": self.provider,
                "model": response.model,
                "response_preview": response.content[:50],
            }
        except Exception as e:
            return {
                "success": False,
                "provider": self.provider,
                "error": str(e),
            }

    def switch_provider(self, provider: str, model: Optional[str] = None) -> None:
        """运行时切换供应商"""
        self.provider = provider
        if model:
            if provider == "openai":
                self.openai_cfg["model"] = model
            elif provider == "anthropic":
                self.anthropic_cfg["model"] = model
            elif provider == "ollama":
                self.ollama_cfg["model"] = model
            elif provider == "openrouter":
                self.openrouter_cfg["model"] = model
