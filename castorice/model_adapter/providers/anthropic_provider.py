from typing import Any, Dict, Generator, List, Optional

from ..common import ChatMessage, ChatResponse, ToolCall


class AnthropicProvider:
    """Anthropic Claude 官方 SDK 提供商"""

    def __init__(self, adapter):
        self.adapter = adapter

    def _merge_messages(self, messages: List[ChatMessage]) -> List[dict]:
        """合并相邻同角色消息（内部方法）

        - 跳过 system 消息
        - 将 ChatMessage 转换为 anthropic dict
        - 合并相邻同角色的消息内容
        - 含 tool_use / tool_result 块的消息不参与合并，保持原样
        """
        def _has_tool_block(msg: Dict[str, Any]) -> bool:
            if not isinstance(msg.get("content"), list):
                return False
            for block in msg["content"]:
                if isinstance(block, dict) and block.get("type") in ("tool_use", "tool_result"):
                    return True
            return False

        api_messages = [m.to_anthropic_dict() for m in messages if m.role != "system"]

        merged_messages: List[dict] = []
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
        return merged_messages

    @staticmethod
    def _extract_system(messages: List[ChatMessage]) -> Optional[str]:
        """从消息列表中提取 system 消息内容"""
        for m in messages:
            if m.role == "system":
                return m.content
        return None

    def chat(self, messages: List[ChatMessage]) -> ChatResponse:
        client = self.adapter._get_anthropic_client()

        system_msg = self._extract_system(messages)
        merged_messages = self._merge_messages(messages)

        # P1-1: Provider 级 prompt caching
        # 检测是否有 system 消息被标记为 cacheable
        has_cacheable_system = any(
            m.role == "system" and getattr(m, "cacheable", False) for m in messages
        )

        kwargs = {
            "model": self.adapter.anthropic_cfg.get("model", "claude-3-5-sonnet-20241022"),
            "messages": merged_messages,
            "max_tokens": self.adapter.max_tokens,
            "temperature": self.adapter.temperature,
        }
        if system_msg:
            if has_cacheable_system:
                # 用块格式传递 system，支持 cache_control
                kwargs["system"] = [
                    {
                        "type": "text",
                        "text": system_msg,
                        "cache_control": {"type": "ephemeral"},
                    }
                ]
            else:
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
        """流式输出（真正的流式实现，基于 anthropic SDK 的 messages.stream）"""
        client = self.adapter._get_anthropic_client()

        system_msg = self._extract_system(messages)
        merged_messages = self._merge_messages(messages)

        # P1-1: Provider 级 prompt caching
        has_cacheable_system = any(
            m.role == "system" and getattr(m, "cacheable", False) for m in messages
        )

        kwargs = {
            "model": self.adapter.anthropic_cfg.get("model", "claude-3-5-sonnet-20241022"),
            "messages": merged_messages,
            "max_tokens": self.adapter.max_tokens,
            "temperature": self.adapter.temperature,
        }
        if system_msg:
            if has_cacheable_system:
                kwargs["system"] = [
                    {"type": "text", "text": system_msg, "cache_control": {"type": "ephemeral"}}
                ]
            else:
                kwargs["system"] = system_msg

        with client.messages.stream(**kwargs) as stream:
            for text in stream.text_stream:
                yield text

    def chat_with_tools(
        self,
        messages: List[ChatMessage],
        tools: List[Dict[str, Any]],
    ) -> ChatResponse:
        client = self.adapter._get_anthropic_client()

        system_msg = self._extract_system(messages)
        merged_messages = self._merge_messages(messages)

        # P1-1: Provider 级 prompt caching
        has_cacheable_system = any(
            m.role == "system" and getattr(m, "cacheable", False) for m in messages
        )

        kwargs = {
            "model": self.adapter.anthropic_cfg.get("model", "claude-3-5-sonnet-20241022"),
            "messages": merged_messages,
            "tools": tools,
            "max_tokens": self.adapter.max_tokens,
            "temperature": self.adapter.temperature,
            "tool_choice": {"type": "auto"},
        }
        if system_msg:
            if has_cacheable_system:
                kwargs["system"] = [
                    {"type": "text", "text": system_msg, "cache_control": {"type": "ephemeral"}}
                ]
            else:
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
