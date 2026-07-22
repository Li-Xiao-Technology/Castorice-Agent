from typing import Any, Dict, Generator, List, Optional

from ..common import ChatMessage, ChatResponse, ToolCall


class AnthropicProvider:
    """Anthropic Claude 官方 SDK 提供商"""

    def __init__(self, adapter):
        self.adapter = adapter

    def chat(self, messages: List[ChatMessage]) -> ChatResponse:
        client = self.adapter._get_anthropic_client()

        system_msg = None
        api_messages = []
        for m in messages:
            if m.role == "system":
                system_msg = m.content
            else:
                api_messages.append(m.to_anthropic_dict())

        merged_messages = []
        for msg in api_messages:
            if merged_messages and merged_messages[-1]["role"] == msg["role"]:
                prev = merged_messages[-1]
                if isinstance(prev["content"], list) and isinstance(msg["content"], list):
                    prev["content"].extend(msg["content"])
                elif isinstance(prev["content"], list):
                    prev["content"].append({"type": "text", "text": str(msg["content"])})
                elif isinstance(msg["content"], list):
                    merged_messages.append(msg)
                else:
                    prev["content"] = str(prev.get("content", "")) + "\n" + str(msg["content"])
            else:
                merged_messages.append(msg)

        kwargs = {
            "model": self.adapter.anthropic_cfg.get("model", "claude-3-5-sonnet-20241022"),
            "messages": merged_messages,
            "max_tokens": self.adapter.max_tokens,
            "temperature": self.adapter.temperature,
        }
        if system_msg:
            kwargs["system"] = system_msg

        response = client.messages.create(**kwargs)
        content = ""
        tool_calls = []
        if response.content:
            for block in response.content:
                if hasattr(block, "type"):
                    if block.type == "text":
                        content += block.text
                    elif block.type == "tool_use":
                        tool_calls.append(ToolCall(
                            id=block.id,
                            name=block.name,
                            arguments=block.input if isinstance(block.input, dict) else {},
                        ))
                elif hasattr(block, "text"):
                    content += block.text

        usage = {}
        if hasattr(response, "usage") and response.usage:
            prompt_tokens = response.usage.input_tokens
            completion_tokens = response.usage.output_tokens
            usage = {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
            }
        return ChatResponse(content=content, model=response.model, usage=usage, tool_calls=tool_calls)

    def chat_stream(self, messages: List[ChatMessage]) -> Generator[str, None, None]:
        response = self.chat(messages)
        yield response.content

    def chat_with_tools(
        self,
        messages: List[ChatMessage],
        tools: List[Dict[str, Any]],
    ) -> ChatResponse:
        client = self.adapter._get_anthropic_client()

        system_msg = None
        api_messages = []
        for m in messages:
            if m.role == "system":
                system_msg = m.content
            else:
                api_messages.append(m.to_anthropic_dict())

        def _has_tool_block(msg: Dict[str, Any]) -> bool:
            if not isinstance(msg.get("content"), list):
                return False
            for block in msg["content"]:
                if isinstance(block, dict) and block.get("type") in ("tool_use", "tool_result"):
                    return True
            return False

        merged_messages = []
        for msg in api_messages:
            if _has_tool_block(msg):
                merged_messages.append(msg)
                continue
            if merged_messages and merged_messages[-1]["role"] == msg["role"]:
                prev = merged_messages[-1]
                if _has_tool_block(prev):
                    merged_messages.append(msg)
                elif isinstance(prev["content"], list) and isinstance(msg["content"], list):
                    prev["content"].extend(msg["content"])
                elif isinstance(prev["content"], list):
                    prev["content"].append({"type": "text", "text": str(msg["content"])})
                elif isinstance(msg["content"], list):
                    merged_messages.append(msg)
                else:
                    prev["content"] = str(prev.get("content", "")) + "\n" + str(msg["content"])
            else:
                merged_messages.append(msg)

        kwargs = {
            "model": self.adapter.anthropic_cfg.get("model", "claude-3-5-sonnet-20241022"),
            "messages": merged_messages,
            "tools": tools,
            "max_tokens": self.adapter.max_tokens,
            "temperature": self.adapter.temperature,
            "tool_choice": {"type": "auto"},
        }
        if system_msg:
            kwargs["system"] = system_msg

        response = client.messages.create(**kwargs)

        content = ""
        tool_calls = []
        for block in response.content:
            if hasattr(block, "type"):
                if block.type == "text":
                    content += block.text
                elif block.type == "tool_use":
                    tool_calls.append(ToolCall(
                        id=block.id,
                        name=block.name,
                        arguments=block.input if isinstance(block.input, dict) else {},
                    ))

        usage = {}
        if hasattr(response, "usage") and response.usage:
            prompt_tokens = response.usage.input_tokens
            completion_tokens = response.usage.output_tokens
            usage = {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
            }

        return ChatResponse(
            content=content,
            model=response.model,
            usage=usage,
            tool_calls=tool_calls,
        )
