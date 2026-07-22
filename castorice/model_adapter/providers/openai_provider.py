import json
from typing import Any, Dict, Generator, List, Optional

from ..common import ChatMessage, ChatResponse, ToolCall


class OpenAIProvider:
    """OpenAI 兼容协议提供商（OpenAI / Ollama / OpenRouter）"""

    def __init__(self, adapter):
        self.adapter = adapter

    def _get_cfg(self):
        provider = self.adapter.provider
        if provider == "ollama":
            return {
                "api_key": "ollama",
                "base_url": self.adapter.ollama_cfg.get("base_url", "http://localhost:11434/v1"),
                "model": self.adapter.ollama_cfg.get("model", "llama3.1:8b"),
            }
        elif provider == "openrouter":
            return {
                "api_key": self.adapter.openrouter_cfg.get("api_key", ""),
                "base_url": self.adapter.openrouter_cfg.get("base_url", "https://openrouter.ai/api/v1"),
                "model": self.adapter.openrouter_cfg.get("model", "anthropic/claude-3.5-sonnet"),
            }
        return self.adapter.openai_cfg

    def chat(self, messages: List[ChatMessage]) -> ChatResponse:
        cfg = self._get_cfg()
        client = self.adapter._get_openai_client(cfg.get("base_url", ""), cfg.get("api_key", ""))
        api_messages = [m.to_dict() for m in messages]

        response = client.chat.completions.create(
            model=cfg.get("model", "gpt-4o"),
            messages=api_messages,
            temperature=self.adapter.temperature,
            max_tokens=self.adapter.max_tokens,
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

    def chat_stream(self, messages: List[ChatMessage]) -> Generator[str, None, None]:
        cfg = self._get_cfg()
        client = self.adapter._get_openai_client(cfg.get("base_url", ""), cfg.get("api_key", ""))
        api_messages = [m.to_dict() for m in messages]

        try:
            stream = client.chat.completions.create(
                model=cfg.get("model", "gpt-4o"),
                messages=api_messages,
                temperature=self.adapter.temperature,
                max_tokens=self.adapter.max_tokens,
                stream=True,
                stream_options={"include_usage": True},
            )
        except Exception:
            stream = client.chat.completions.create(
                model=cfg.get("model", "gpt-4o"),
                messages=api_messages,
                temperature=self.adapter.temperature,
                max_tokens=self.adapter.max_tokens,
                stream=True,
            )

        for chunk in stream:
            if hasattr(chunk, "usage") and chunk.usage:
                with self.adapter._stats_lock:
                    self.adapter.total_prompt_tokens += getattr(chunk.usage, "prompt_tokens", 0) or 0
                    self.adapter.total_completion_tokens += getattr(chunk.usage, "completion_tokens", 0) or 0
                    self.adapter.total_calls += 1
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if delta and delta.content:
                yield delta.content

    def chat_with_tools(
        self,
        messages: List[ChatMessage],
        tools: List[Dict[str, Any]],
    ) -> ChatResponse:
        cfg = self._get_cfg()
        client = self.adapter._get_openai_client(cfg.get("base_url", ""), cfg.get("api_key", ""))

        api_messages = [m.to_dict() for m in messages]

        response = client.chat.completions.create(
            model=cfg.get("model", "gpt-4o"),
            messages=api_messages,
            tools=tools,
            tool_choice=self.adapter.tool_choice,
            temperature=self.adapter.temperature,
            max_tokens=self.adapter.max_tokens,
        )

        message = response.choices[0].message
        content = message.content or ""

        tool_calls = []
        if message.tool_calls:
            for tc in message.tool_calls:
                try:
                    args = json.loads(tc.function.arguments)
                except (json.JSONDecodeError, TypeError):
                    args = {}
                tool_calls.append(ToolCall(
                    id=tc.id,
                    name=tc.function.name,
                    arguments=args,
                ))

        usage = {}
        if hasattr(response, "usage") and response.usage:
            usage = {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            }

        return ChatResponse(
            content=content,
            model=response.model,
            usage=usage,
            tool_calls=tool_calls,
        )
