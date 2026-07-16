"""
记忆层包初始化
"""
from castorice.memory.short_term import ShortTermMemory, Message
from castorice.memory.skill import SkillMemory, Skill
from castorice.memory.user_profile import UserProfile

# 长期记忆按需导入（避免 chromadb 强制依赖）
try:
    from castorice.memory.long_term import LongTermMemory
except ImportError:
    LongTermMemory = None
