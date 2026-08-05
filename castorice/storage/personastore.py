"""
Personastore Protocol - 人格数据主权存储接口

去中心化人格数据主权（Self-Sovereign Persona）的核心抽象层。

设计理念：
- 用户真正拥有和控制自己的经历流、人格模型和认知历史
- 所有"人格数据"通过统一接口读写，后端可插拔
- 默认使用本地 SQLite（与现有行为100%一致）
- 未来可扩展到 Solid PDS、远程服务器等其他后端

Personastore 管理的数据域：
1. experiences: 经历流（Agent的交互历史、反思、情感事件）
2. self_concept: 自我概念（核心自我 + 叙事自我）
3. emotion_state: 情感状态（PAD三维 + 情绪历史）
4. values: 价值观系统（10个价值观维度 + 冲突记录）

访问控制：
- 每个数据域支持独立的访问策略
- 支持只读、读写、不可见等权限级别
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("Castorice.Personastore")


class DataDomain(str, Enum):
    """人格数据域枚举"""
    EXPERIENCES = "experiences"
    SELF_CONCEPT = "self_concept"
    EMOTION_STATE = "emotion_state"
    VALUES = "values"


class AccessLevel(str, Enum):
    """访问级别"""
    NONE = "none"          # 不可见
    READ_ONLY = "read"     # 只读
    READ_WRITE = "write"   # 读写
    OWNER = "owner"        # 所有者（完全控制）


@dataclass
class AccessPolicy:
    """数据域访问策略"""
    domain: DataDomain
    level: AccessLevel = AccessLevel.OWNER
    allowed_readers: List[str] = field(default_factory=list)  # 允许的读者ID列表
    allowed_writers: List[str] = field(default_factory=list)  # 允许的写者ID列表

    def can_read(self, actor_id: str = "owner") -> bool:
        if self.level == AccessLevel.NONE:
            return False
        if self.level in (AccessLevel.READ_ONLY, AccessLevel.READ_WRITE, AccessLevel.OWNER):
            if actor_id == "owner" or actor_id in self.allowed_readers:
                return True
        return False

    def can_write(self, actor_id: str = "owner") -> bool:
        if self.level in (AccessLevel.READ_WRITE, AccessLevel.OWNER):
            if actor_id == "owner" or actor_id in self.allowed_writers:
                return True
        return False


# ============================================================
# 数据结构定义（与现有模块兼容）
# ============================================================

@dataclass
class StoredExperience:
    """存储的经历记录"""
    id: str
    timestamp: str
    memory_type: str
    content: str
    importance: float
    emotional_valence: float
    session_id: str
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class StoredSelfConcept:
    """存储的自我概念"""
    core_self: str = ""
    narrative_self: str = ""
    narrative_events: List[Dict[str, Any]] = field(default_factory=list)
    core_evidences: List[Dict[str, Any]] = field(default_factory=list)
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class StoredEmotionState:
    """存储的情感状态"""
    pleasure: float = 0.0
    arousal: float = 0.0
    dominance: float = 0.0
    interaction_count: int = 0
    last_update: str = ""
    emotional_history: List[Dict[str, Any]] = field(default_factory=list)
    afterglow: Dict[str, Any] = field(default_factory=dict)
    baseline: Dict[str, Any] = field(default_factory=dict)


@dataclass
class StoredValueState:
    """单个价值观的存储状态"""
    dimension_id: str
    strength: float = 0.5
    trend: float = 0.0
    history: List[float] = field(default_factory=list)


@dataclass
class StoredValues:
    """存储的价值观系统"""
    values: Dict[str, StoredValueState] = field(default_factory=dict)
    conflicts: List[Dict[str, Any]] = field(default_factory=list)


# ============================================================
# Personastore 抽象接口
# ============================================================

class Personastore(ABC):
    """
    人格数据主权存储抽象接口。

    所有人格相关数据（经历、自我概念、情感、价值观）都通过此接口读写。
    后端实现可以是本地SQLite、Solid PDS、远程服务器等。

    设计原则：
    1. 读写分离：每个数据域有独立的read/write方法
    2. 向后兼容：默认行为与现有实现100%一致
    3. 访问控制：每个操作检查访问策略
    4. 可观察：所有读写操作可以被审计
    """

    def __init__(self):
        self._access_policies: Dict[DataDomain, AccessPolicy] = {}
        self._init_default_policies()

    def _init_default_policies(self) -> None:
        """初始化默认访问策略（所有者完全控制）"""
        for domain in DataDomain:
            self._access_policies[domain] = AccessPolicy(
                domain=domain,
                level=AccessLevel.OWNER,
            )

    def set_access_policy(self, domain: DataDomain, policy: AccessPolicy) -> None:
        """设置指定数据域的访问策略"""
        self._access_policies[domain] = policy
        logger.info(f"访问策略已更新: {domain.value} -> {policy.level.value}")

    def get_access_policy(self, domain: DataDomain) -> AccessPolicy:
        """获取指定数据域的访问策略"""
        return self._access_policies.get(domain, AccessPolicy(domain=domain))

    def _check_read(self, domain: DataDomain, actor_id: str = "owner") -> bool:
        """检查读取权限"""
        policy = self.get_access_policy(domain)
        if not policy.can_read(actor_id):
            logger.warning(f"读取被拒绝: domain={domain.value}, actor={actor_id}")
            return False
        return True

    def _check_write(self, domain: DataDomain, actor_id: str = "owner") -> bool:
        """检查写入权限"""
        policy = self.get_access_policy(domain)
        if not policy.can_write(actor_id):
            logger.warning(f"写入被拒绝: domain={domain.value}, actor={actor_id}")
            return False
        return True

    # ============================================================
    # 经历流 (Experiences)
    # ============================================================

    @abstractmethod
    def add_experience(self, exp: StoredExperience, actor_id: str = "owner") -> str:
        """添加一条经历"""
        ...

    @abstractmethod
    def get_recent_experiences(
        self, limit: int = 20, memory_type: Optional[str] = None, actor_id: str = "owner"
    ) -> List[StoredExperience]:
        """获取最近的经历"""
        ...

    @abstractmethod
    def get_important_experiences(
        self, limit: int = 20, memory_type: Optional[str] = None, actor_id: str = "owner"
    ) -> List[StoredExperience]:
        """获取最重要的经历"""
        ...

    @abstractmethod
    def get_experiences_by_session(
        self, session_id: str, limit: int = 50, actor_id: str = "owner"
    ) -> List[StoredExperience]:
        """获取指定会话的经历"""
        ...

    @abstractmethod
    def get_experiences_since(
        self, since: datetime, limit: int = 100, actor_id: str = "owner"
    ) -> List[StoredExperience]:
        """获取指定时间后的经历"""
        ...

    @abstractmethod
    def search_experiences(
        self, query: str, top_k: int = 10, min_importance: float = 0.0, actor_id: str = "owner"
    ) -> List[StoredExperience]:
        """搜索经历"""
        ...

    @abstractmethod
    def count_experiences(self, memory_type: Optional[str] = None, actor_id: str = "owner") -> int:
        """统计经历数量"""
        ...

    @abstractmethod
    def get_experience_stats(self, actor_id: str = "owner") -> Dict[str, Any]:
        """获取经历统计信息"""
        ...

    # ============================================================
    # 自我概念 (Self-Concept)
    # ============================================================

    @abstractmethod
    def read_self_concept(self, actor_id: str = "owner") -> StoredSelfConcept:
        """读取自我概念"""
        ...

    @abstractmethod
    def write_self_concept(self, data: StoredSelfConcept, actor_id: str = "owner") -> bool:
        """写入自我概念"""
        ...

    # ============================================================
    # 情感状态 (Emotion State)
    # ============================================================

    @abstractmethod
    def read_emotion_state(self, actor_id: str = "owner") -> StoredEmotionState:
        """读取情感状态"""
        ...

    @abstractmethod
    def write_emotion_state(self, data: StoredEmotionState, actor_id: str = "owner") -> bool:
        """写入情感状态"""
        ...

    # ============================================================
    # 价值观系统 (Values)
    # ============================================================

    @abstractmethod
    def read_values(self, actor_id: str = "owner") -> StoredValues:
        """读取价值观系统"""
        ...

    @abstractmethod
    def write_values(self, data: StoredValues, actor_id: str = "owner") -> bool:
        """写入价值观系统"""
        ...

    # ============================================================
    # 生命周期管理
    # ============================================================

    def close(self) -> None:
        """关闭存储连接，释放资源"""
        pass

    def export_all(self, actor_id: str = "owner") -> Dict[str, Any]:
        """导出所有人格数据（用户数据主权的核心）"""
        if not self._check_read(DataDomain.EXPERIENCES, actor_id):
            return {}
        if not self._check_read(DataDomain.SELF_CONCEPT, actor_id):
            return {}
        if not self._check_read(DataDomain.EMOTION_STATE, actor_id):
            return {}
        if not self._check_read(DataDomain.VALUES, actor_id):
            return {}

        return {
            "version": "1.0",
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "domains": {
                "experiences": {
                    "count": self.count_experiences(actor_id=actor_id),
                    "stats": self.get_experience_stats(actor_id=actor_id),
                },
                "self_concept": self.read_self_concept(actor_id=actor_id).__dict__,
                "emotion_state": self.read_emotion_state(actor_id=actor_id).__dict__,
                "values": self.read_values(actor_id=actor_id).__dict__,
            },
        }
