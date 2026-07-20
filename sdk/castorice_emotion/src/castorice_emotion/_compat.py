"""
SDK 兼容层

让 SDK 不强依赖主项目的 model_adapter，但能适配各种 chat 接口格式。

支持的 model_adapter 接口：
- chat(messages) where messages 是 list[dict] 或 list[ChatMessage]
- 返回对象有 .content 属性，或返回字符串
"""
from typing import Any, List, Union


def to_chat_messages(messages: List[dict], model_adapter: Any = None) -> List:
    """
    将 dict 列表转换为 model_adapter 期望的消息格式

    探测策略：
    1. 如果 model_adapter 有 _message_class 属性，用它构造
    2. 如果 model_adapter 的 chat 方法接受 dict，直接返回 dict
    3. 默认返回 dict（最通用）
    """
    # 检查是否有 ChatMessage 类可用
    msg_class = None
    if model_adapter is not None:
        # 主项目的 ModelAdapter
        if hasattr(model_adapter, "_message_class"):
            msg_class = model_adapter._message_class
        # 兼容主项目 ChatMessage（通过类名探测）
        elif hasattr(model_adapter, "__class__"):
            cls = model_adapter.__class__
            module = getattr(cls, "__module__", "")
            if "castorice" in module and "model_adapter" in module:
                try:
                    from castorice.model_adapter import ChatMessage
                    msg_class = ChatMessage
                except ImportError:
                    pass

    if msg_class is not None:
        return [msg_class(role=m["role"], content=m["content"]) for m in messages]

    # 默认返回 dict（OpenAI 格式）
    return messages
