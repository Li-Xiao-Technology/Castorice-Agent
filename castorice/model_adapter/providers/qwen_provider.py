import json
from typing import Any, Dict, Generator, List, Optional

from ..common import ChatMessage, ChatResponse, ToolCall


class QwenProvider:
    """阿里云通义千问官方 SDK 提供商"""

    def __init__(self, adapter):
        self.adapter = adapter

    def chat(self, messages: List[ChatMessage]) -> ChatResponse:
        try:
            from dashscope import Generation
        except ImportError:
            raise ImportError("请安装通义千问 SDK: pip install dashscope")

        api_messages = []
        for m in messages:
            api_messages.append({"role": m.role, "content": m.content})

        response = Generation.call(
            model=self.adapter.qwen_cfg.get("model", "qwen-plus"),
            messages=api_messages,
            api_key=self.adapter.qwen_cfg.get("api_key", ""),
            temperature=self.adapter.temperature,
            max_result_length=self.adapter.max_tokens,
        )

        if response.status_code != 200:
            error_msg = getattr(response, 'message', '') or str(response)
            raise RuntimeError(f"通义千问 API 调用失败 (status_code={response.status_code}): {error_msg}")

        content = response.output.choices[0].message.content

        usage = {}
        if response.usage:
            usage = {
                "prompt_tokens": response.usage.input_tokens,
                "completion_tokens": response.usage.output_tokens,
                "total_tokens": response.usage.total_tokens,
            }

        return ChatResponse(content=content, model=self.adapter.qwen_cfg.get("model", "qwen-plus"), usage=usage)

    def chat_stream(self, messages: List[ChatMessage]) -> Generator[str, None, None]:
        try:
            from dashscope import Generation
        except ImportError:
            raise ImportError("请安装通义千问 SDK: pip install dashscope")

        api_messages = []
        for m in messages:
            api_messages.append({"role": m.role, "content": m.content})

        responses = Generation.call(
            model=self.adapter.qwen_cfg.get("model", "qwen-plus"),
            messages=api_messages,
            api_key=self.adapter.qwen_cfg.get("api_key", ""),
            temperature=self.adapter.temperature,
            max_result_length=self.adapter.max_tokens,
            result_format="message",
            stream=True,
            incremental_output=True,
        )
        for response in responses:
            if response.status_code == 200:
                choice = response.output.choices[0]
                if choice.message.content:
                    yield choice.message.content

    def chat_with_tools(
        self,
        messages: List[ChatMessage],
        tools: List[Dict[str, Any]],
    ) -> ChatResponse:
        try:
            from dashscope import Generation
        except ImportError:
            raise ImportError("请安装通义千问 SDK: pip install dashscope")

        api_messages = []
        for m in messages:
            api_messages.append({"role": m.role, "content": m.content})

        qwen_tools = []
        for t in tools:
            func = t.get("function", t)
            qwen_tools.append({
                "type": "function",
                "function": {
                    "name": func.get("name", ""),
                    "description": func.get("description", ""),
                    "parameters": func.get("parameters", {}),
                },
            })

        response = Generation.call(
            model=self.adapter.qwen_cfg.get("model", "qwen-plus"),
            messages=api_messages,
            tools=qwen_tools,
            api_key=self.adapter.qwen_cfg.get("api_key", ""),
            temperature=self.adapter.temperature,
            max_result_length=self.adapter.max_tokens,
            result_format="message",
        )

        if response.status_code != 200:
            error_msg = getattr(response, 'message', '') or str(response)
            raise RuntimeError(f"通义千问 API 调用失败 (status_code={response.status_code}): {error_msg}")

        choice = response.output.choices[0]
        message = choice.message

        content = message.content or ""
        tool_calls = []
        if hasattr(message, "tool_calls") and message.tool_calls:
            for tc in message.tool_calls:
                try:
                    args = json.loads(tc.function.arguments) if isinstance(tc.function.arguments, str) else (tc.function.arguments or {})
                except (json.JSONDecodeError, TypeError):
                    args = {}
                tool_calls.append(ToolCall(
                    id=getattr(tc, "id", f"qwen_tc_{len(tool_calls)}"),
                    name=tc.function.name,
                    arguments=args,
                ))

        usage = {}
        if response.usage:
            usage = {
                "prompt_tokens": response.usage.input_tokens,
                "completion_tokens": response.usage.output_tokens,
                "total_tokens": response.usage.total_tokens,
            }

        return ChatResponse(
            content=content,
            model=self.adapter.qwen_cfg.get("model", "qwen-plus"),
            usage=usage,
            tool_calls=tool_calls,
        )
