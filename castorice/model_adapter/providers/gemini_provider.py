import logging
from typing import Any, Dict, Generator, List, Optional

from ..common import ChatMessage, ChatResponse, ToolCall

logger = logging.getLogger("Castorice.ModelAdapter.Gemini")


class GeminiProvider:
    """Google Gemini 官方 SDK 提供商"""

    def __init__(self, adapter):
        self.adapter = adapter

    def chat(self, messages: List[ChatMessage]) -> ChatResponse:
        model = self.adapter._get_gemini_model()

        system_parts = []
        chat_parts = []
        for m in messages:
            if m.role == "system":
                system_parts.append(m.content)
            else:
                role = "user" if m.role == "user" else "model"
                chat_parts.append({"role": role, "parts": [m.content]})

        system_instruction = "\n".join(system_parts) if system_parts else None

        response = model.generate_content(
            chat_parts,
            generation_config={
                "temperature": self.adapter.temperature,
                "max_output_tokens": self.adapter.max_tokens,
            },
            system_instruction=system_instruction,
        )

        content = ""
        try:
            content = response.text or ""
        except Exception as e:
            logger.warning(f"Gemini 获取响应内容失败（可能被安全过滤）: {e}")
            content = "[内容被安全过滤]"
        usage = {}
        if hasattr(response, "usage_metadata") and response.usage_metadata:
            meta = response.usage_metadata
            usage = {
                "prompt_tokens": meta.prompt_token_count,
                "completion_tokens": meta.candidates_token_count,
                "total_tokens": meta.total_token_count,
            }

        return ChatResponse(content=content, model=self.adapter.gemini_cfg.get("model", "gemini-1.5-flash"), usage=usage)

    def chat_stream(self, messages: List[ChatMessage]) -> Generator[str, None, None]:
        model = self.adapter._get_gemini_model()
        system_parts = []
        chat_parts = []
        for m in messages:
            if m.role == "system":
                system_parts.append(m.content)
            else:
                role = "user" if m.role == "user" else "model"
                chat_parts.append({"role": role, "parts": [m.content]})
        system_instruction = "\n".join(system_parts) if system_parts else None

        response = model.generate_content(
            chat_parts,
            generation_config={
                "temperature": self.adapter.temperature,
                "max_output_tokens": self.adapter.max_tokens,
            },
            system_instruction=system_instruction,
            stream=True,
        )
        for chunk in response:
            try:
                if chunk.text:
                    yield chunk.text
            except Exception as e:
                logger.warning(f"Gemini 流式获取内容失败（可能被安全过滤）: {e}")
                yield "[内容被安全过滤]"

    def chat_with_tools(
        self,
        messages: List[ChatMessage],
        tools: List[Dict[str, Any]],
    ) -> ChatResponse:
        model = self.adapter._get_gemini_model()

        system_parts = []
        chat_parts = []
        for m in messages:
            if m.role == "system":
                system_parts.append(m.content)
            else:
                role = "user" if m.role == "user" else "model"
                chat_parts.append({"role": role, "parts": [m.content]})

        system_instruction = "\n".join(system_parts) if system_parts else None

        gemini_tools = []
        for t in tools:
            func = t.get("function", t)
            gemini_tools.append({
                "name": func.get("name", ""),
                "description": func.get("description", ""),
                "parameters": func.get("parameters", {}),
            })

        import google.generativeai as genai
        tool_config = genai.types.Tool(function_declarations=[
            genai.types.FunctionDeclaration(
                name=gt["name"],
                description=gt["description"],
                parameters=gt["parameters"] if gt["parameters"].get("properties") else None,
            )
            for gt in gemini_tools
        ])

        response = model.generate_content(
            chat_parts,
            generation_config={
                "temperature": self.adapter.temperature,
                "max_output_tokens": self.adapter.max_tokens,
            },
            system_instruction=system_instruction,
            tools=[tool_config],
        )

        content = ""
        tool_calls = []
        if response.candidates:
            candidate = response.candidates[0]
            if candidate.content and candidate.content.parts:
                for part in candidate.content.parts:
                    if hasattr(part, "text") and part.text:
                        content += part.text
                    elif hasattr(part, "function_call") and part.function_call:
                        fc = part.function_call
                        tool_calls.append(ToolCall(
                            id=f"gemini_fc_{len(tool_calls)}",
                            name=fc.name,
                            arguments=dict(fc.args) if hasattr(fc, "args") else {},
                        ))

        usage = {}
        if hasattr(response, "usage_metadata") and response.usage_metadata:
            meta = response.usage_metadata
            usage = {
                "prompt_tokens": meta.prompt_token_count,
                "completion_tokens": meta.candidates_token_count,
                "total_tokens": meta.total_token_count,
            }

        return ChatResponse(
            content=content,
            model=self.adapter.gemini_cfg.get("model", "gemini-1.5-flash"),
            usage=usage,
            tool_calls=tool_calls,
        )
