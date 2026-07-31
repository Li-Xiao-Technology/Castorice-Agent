"""
自动生成的 Mixin：PostprocessingMixin
从 core.py 中拆分出来，与 CastoriceAgent 组合使用。

已按子域拆分为 3 个子 Mixin，此处仅组合：
- PostprocessingSafetyMixin   (安全 + 元认知)
- PostprocessingMemoryMixin   (记忆 + 情感 + 社交 + 自我概念)
- PostprocessingReflectionMixin (反思 + 动机)
"""
from .postprocessing_safety import PostprocessingSafetyMixin
from .postprocessing_memory import PostprocessingMemoryMixin
from .postprocessing_reflection import PostprocessingReflectionMixin


class PostprocessingMixin(
    PostprocessingSafetyMixin,
    PostprocessingMemoryMixin,
    PostprocessingReflectionMixin,
):
    """后处理 Mixin（安全/元认知 → 记忆/情感/社交 → 反思/动机）"""
    pass
