import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class ToolCall:
    """工具调用结构（Function Calling 返回）"""
    id: str
    name: str
    arguments: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "type": "function",
            "function": {
                "name": self.name,
                "arguments": json.dumps(self.arguments, ensure_ascii=False),
            },
        }


class ChatMessage:
    """统一的对话消息结构（所有供应商通用）"""

    def __init__(
        self,
        role: str,
        content: Optional[str] = None,
        tool_calls: Optional[List[ToolCall]] = None,
        tool_call_id: Optional[str] = None,
        name: Optional[str] = None,
        image_urls: Optional[List[str]] = None,
    ):
        self.role = role
        self.content = content
        self.tool_calls = tool_calls or []
        self.tool_call_id = tool_call_id
        self.name = name
        self.image_urls = image_urls or []

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {"role": self.role}
        if self.image_urls:
            content_parts: List[Dict[str, Any]] = []
            if self.content:
                content_parts.append({"type": "text", "text": self.content})
            for img_url in self.image_urls:
                content_parts.append({"type": "image_url", "image_url": {"url": img_url}})
            d["content"] = content_parts
        elif self.content is not None:
            d["content"] = self.content
        if self.tool_calls:
            d["tool_calls"] = [tc.to_dict() for tc in self.tool_calls]
        if self.tool_call_id:
            d["tool_call_id"] = self.tool_call_id
        if self.name:
            d["name"] = self.name
        return d

    def to_anthropic_dict(self) -> Dict[str, Any]:
        """转为 Anthropic 消息格式"""
        if self.role == "tool":
            return {
                "role": "user",
                "content": [{
                    "type": "tool_result",
                    "tool_use_id": self.tool_call_id or "",
                    "content": self.content or "",
                }],
            }
        if self.tool_calls:
            blocks: List[Dict[str, Any]] = []
            if self.content:
                blocks.append({"type": "text", "text": self.content})
            for tc in self.tool_calls:
                blocks.append({
                    "type": "tool_use",
                    "id": tc.id,
                    "name": tc.name,
                    "input": tc.arguments,
                })
            return {"role": "assistant", "content": blocks}
        return {"role": self.role, "content": self.content or ""}


class ChatResponse:
    """统一的模型回复结构"""

    def __init__(
        self,
        content: str = "",
        model: str = "",
        usage: Optional[Dict] = None,
        tool_calls: Optional[List[ToolCall]] = None,
    ):
        self.content = content or ""
        self.model = model
        self.usage = usage or {}
        self.tool_calls = tool_calls or []
        self.has_tool_calls = len(self.tool_calls) > 0
