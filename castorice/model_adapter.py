"""
统一模型适配层 (ModelAdapter) - 兼容层

已迁移至 castorice.model_adapter 包，此文件仅用于向后兼容。
"""

from .model_adapter.common import ToolCall, ChatMessage, ChatResponse
from .model_adapter.adapter import ModelAdapter

__all__ = ["ToolCall", "ChatMessage", "ChatResponse", "ModelAdapter"]
