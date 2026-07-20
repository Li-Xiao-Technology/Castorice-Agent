"""
社会关系网络模块 (Social Relation Network)

设计原则：
- Agent 理解并维护与用户的关系深度
- 关系动态演化：从陌生人到朋友
- 关系影响对话风格和行为决策
- 多用户支持：每个用户有独立的关系档案

关系类型演化路径：
stranger → acquaintance → friend → close_friend → trusted

关系维度：
- 亲密度 (intimacy): 0.0-1.0
- 信任度 (trust): 0.0-1.0
- 共同经历数 (shared_history_count)
- 情感联结强度 (emotional_bond)
"""

import json
import logging
import os
import sqlite3
import threading
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Castorice.SocialRelation")


@dataclass
class RelationNode:
    """关系节点数据结构"""
    user_id: str
    user_name: str = ""
    relation_type: str = "stranger"       # stranger / acquaintance / friend / close_friend / trusted
    intimacy: float = 0.0                 # 亲密度 0.0-1.0
    trust_level: float = 0.0               # 信任度 0.0-1.0
    emotional_bond: float = 0.0            # 情感联结强度 0.0-1.0
    shared_history_count: int = 0          # 共同经历次数
    last_interaction: str = ""             # 最后互动时间
    first_met: str = ""                    # 首次见面时间
    key_memories: List[str] = field(default_factory=list)  # 关键共同记忆
    preferences: Dict[str, Any] = field(default_factory=dict)  # 用户偏好（从交互中学习）
    interaction_streak: int = 0             # 连续互动天数
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self):
        now = datetime.now(timezone.utc).isoformat()
        if not self.created_at:
            self.created_at = now
        if not self.first_met:
            self.first_met = now
        if not self.last_interaction:
            self.last_interaction = now
        if not self.updated_at:
            self.updated_at = now

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RelationNode":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    def update_relation_type(self):
        """根据亲密度和信任度自动更新关系类型"""
        score = (self.intimacy + self.trust_level + self.emotional_bond) / 3

        if score >= 0.9:
            self.relation_type = "trusted"
        elif score >= 0.7:
            self.relation_type = "close_friend"
        elif score >= 0.4:
            self.relation_type = "friend"
        elif score >= 0.15:
            self.relation_type = "acquaintance"
        else:
            self.relation_type = "stranger"

    def get_relation_label(self) -> str:
        """获取关系的中文标签"""
        labels = {
            "stranger": "陌生人",
            "acquaintance": "认识的人",
            "friend": "朋友",
            "close_friend": "亲密朋友",
            "trusted": "最信任的人",
        }
        return labels.get(self.relation_type, "陌生人")

    def get_conversation_style(self) -> str:
        """根据关系类型获取推荐的对话风格"""
        styles = {
            "stranger": "礼貌、正式、保持距离感",
            "acquaintance": "友好、自然、略有距离感",
            "friend": "随意、真诚、可以开些玩笑",
            "close_friend": "亲密、坦诚、随意、可以分享内心感受",
            "trusted": "完全信任、深度交流、无话不谈",
        }
        return styles.get(self.relation_type, "礼貌、正式")


class SocialRelationManager:
    """
    社会关系管理器

    功能：
    - 维护与每个用户的关系档案
    - 每轮交互后更新关系状态
    - 检测关系里程碑
    - 提供关系状态查询
    - 关系状态注入 system prompt
    """

    RELATION_TYPES = ["stranger", "acquaintance", "friend", "close_friend", "trusted"]

    def __init__(
        self,
        db_path: str = "./castorice_data/social_relations.db",
        max_key_memories: int = 20,
    ):
        self.db_path = db_path
        self.max_key_memories = max_key_memories
        self._lock = threading.Lock()
        self._init_db()

    def _get_conn(self):
        import os
        os.makedirs(os.path.dirname(self.db_path) or ".", exist_ok=True)
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        return conn

    def _init_db(self):
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS relations (
                user_id TEXT PRIMARY KEY,
                user_name TEXT,
                relation_type TEXT DEFAULT 'stranger',
                intimacy REAL DEFAULT 0.0,
                trust_level REAL DEFAULT 0.0,
                emotional_bond REAL DEFAULT 0.0,
                shared_history_count INTEGER DEFAULT 0,
                last_interaction TEXT NOT NULL,
                first_met TEXT NOT NULL,
                key_memories TEXT,
                preferences TEXT,
                interaction_streak INTEGER DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_relations_type
            ON relations(relation_type)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_relations_last_interaction
            ON relations(last_interaction)
        """)
        conn.commit()
        conn.close()

    def get_relation(self, user_id: str) -> Optional[RelationNode]:
        """获取用户关系档案"""
        with self._lock:
            conn = self._get_conn()
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM relations WHERE user_id = ?", (user_id,))
            row = cursor.fetchone()
            conn.close()
            return self._row_to_relation(row) if row else None

    def get_or_create_relation(self, user_id: str, user_name: str = "") -> RelationNode:
        """获取或创建关系档案"""
        relation = self.get_relation(user_id)
        if relation is None:
            relation = self._create_relation(user_id, user_name)
            logger.info(f"新关系建立: user_id={user_id[:8]}")
        return relation

    def _create_relation(self, user_id: str, user_name: str = "") -> RelationNode:
        """创建新的关系档案"""
        with self._lock:
            relation = RelationNode(user_id=user_id, user_name=user_name)
            conn = self._get_conn()
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO relations
                (user_id, user_name, relation_type, intimacy, trust_level, emotional_bond,
                 shared_history_count, last_interaction, first_met, key_memories,
                 preferences, interaction_streak, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                relation.user_id,
                relation.user_name,
                relation.relation_type,
                relation.intimacy,
                relation.trust_level,
                relation.emotional_bond,
                relation.shared_history_count,
                relation.last_interaction,
                relation.first_met,
                json.dumps(relation.key_memories),
                json.dumps(relation.preferences),
                relation.interaction_streak,
                relation.created_at,
                relation.updated_at,
            ))
            conn.commit()
            conn.close()
            return relation

    def update_relation(
        self,
        user_id: str,
        interaction_quality: float = 0.5,
        task_success: bool = True,
        emotional_intensity: float = 0.0,
        user_feedback: str = "",
        context: str = "",
    ) -> Optional[RelationNode]:
        """
        更新关系状态

        :param user_id: 用户ID
        :param interaction_quality: 交互质量 0.0-1.0（主观评估）
        :param task_success: 任务是否成功
        :param emotional_intensity: 情感强度 -1.0 到 1.0
        :param user_feedback: 用户反馈（正面/负面词汇）
        :param context: 交互上下文（用于关键记忆）
        :return: 更新后的关系节点
        """
        with self._lock:
            conn = self._get_conn()
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM relations WHERE user_id = ?", (user_id,))
            row = cursor.fetchone()
            if not row:
                conn.close()
                return None

            relation = self._row_to_relation(row)
            old_type = relation.relation_type

            # 更新共同经历计数
            relation.shared_history_count += 1

            # 更新最后互动时间
            now = datetime.now(timezone.utc)
            relation.last_interaction = now.isoformat()

            # 更新连续互动天数
            try:
                last_ts = datetime.fromisoformat(row[7])
                if now.date() != last_ts.date():
                    if (now.date() - last_ts.date()).days == 1:
                        relation.interaction_streak += 1
                    else:
                        relation.interaction_streak = 1
            except Exception:
                pass

            # 亲密度更新
            intimacy_delta = 0.0
            if interaction_quality > 0.7:
                intimacy_delta += 0.02
            elif interaction_quality < 0.3:
                intimacy_delta -= 0.01
            if emotional_intensity > 0.5:
                intimacy_delta += 0.03
            elif emotional_intensity < -0.3:
                intimacy_delta += 0.01  # 负面情绪也是一种联结
            if relation.interaction_streak > 3:
                intimacy_delta += 0.005 * min(relation.interaction_streak, 10)

            # 信任度更新
            trust_delta = 0.0
            if task_success:
                trust_delta += 0.015
            else:
                trust_delta -= 0.02
            if interaction_quality > 0.8:
                trust_delta += 0.01

            # 情感联结更新
            bond_delta = 0.0
            if abs(emotional_intensity) > 0.5:
                bond_delta += abs(emotional_intensity) * 0.02

            # 用户反馈影响
            positive_words = ["谢谢", "感谢", "很棒", "厉害", "好的", "不错", "喜欢", "爱"]
            negative_words = ["差", "没用", "错了", "不好", "失望", "讨厌", "生气"]
            for word in positive_words:
                if word in user_feedback:
                    intimacy_delta += 0.02
                    trust_delta += 0.01
                    bond_delta += 0.02
                    break
            for word in negative_words:
                if word in user_feedback:
                    trust_delta -= 0.03
                    break

            # 应用增量（带衰减因子）
            relation.intimacy = max(0.0, min(1.0, relation.intimacy + intimacy_delta))
            relation.trust_level = max(0.0, min(1.0, relation.trust_level + trust_delta))
            relation.emotional_bond = max(0.0, min(1.0, relation.emotional_bond + bond_delta))

            # 自然衰减（长期不互动会缓慢下降）
            # （这里不做，因为每次更新都是互动后调用的）

            # 更新关系类型
            relation.update_relation_type()

            # 检测关系里程碑（类型变化）
            if old_type != relation.relation_type:
                milestone_msg = f"关系升级: {old_type} → {relation.relation_type}"
                logger.info(milestone_msg)
                self._add_key_memory(relation, milestone_msg)

            # 检测数量里程碑
            if relation.shared_history_count in [10, 50, 100, 500, 1000]:
                milestone_msg = f"第 {relation.shared_history_count} 次互动里程碑"
                self._add_key_memory(relation, milestone_msg)

            # 更新时间戳
            relation.updated_at = now.isoformat()

            # 写回数据库
            cursor.execute("""
                UPDATE relations SET
                user_name = ?, relation_type = ?, intimacy = ?, trust_level = ?,
                emotional_bond = ?, shared_history_count = ?, last_interaction = ?,
                key_memories = ?, preferences = ?, interaction_streak = ?, updated_at = ?
                WHERE user_id = ?
            """, (
                relation.user_name,
                relation.relation_type,
                relation.intimacy,
                relation.trust_level,
                relation.emotional_bond,
                relation.shared_history_count,
                relation.last_interaction,
                json.dumps(relation.key_memories),
                json.dumps(relation.preferences),
                relation.interaction_streak,
                relation.updated_at,
                relation.user_id,
            ))
            conn.commit()
            conn.close()
            return relation

    def _add_key_memory(self, relation: RelationNode, memory: str):
        """添加关键记忆（保持不超过 max_key_memories）"""
        relation.key_memories.append(memory)
        if len(relation.key_memories) > self.max_key_memories:
            relation.key_memories = relation.key_memories[-self.max_key_memories:]

    def add_preference(self, user_id: str, key: str, value: Any):
        """记录用户偏好（从交互中学习）"""
        with self._lock:
            conn = self._get_conn()
            cursor = conn.cursor()
            cursor.execute("SELECT preferences FROM relations WHERE user_id = ?", (user_id,))
            row = cursor.fetchone()
            if not row:
                conn.close()
                return

            prefs = json.loads(row[0] or "{}")
            prefs[key] = value
            cursor.execute(
                "UPDATE relations SET preferences = ?, updated_at = ? WHERE user_id = ?",
                (json.dumps(prefs), datetime.now(timezone.utc).isoformat(), user_id),
            )
            conn.commit()
            conn.close()

    def to_prompt(self, user_id: str) -> str:
        """
        生成关系状态提示词，注入到 system prompt

        格式：
        ## 当前关系状态
        关系类型: 朋友
        亲密度: 65%
        信任度: 70%
        对话风格: 随意、真诚、可以开些玩笑
        关键共同记忆:
        - 第50次互动里程碑
        - 关系升级: acquaintance → friend
        """
        relation = self.get_relation(user_id)
        if relation is None:
            return ""

        lines = ["## 当前关系状态"]
        lines.append(f"关系类型: {relation.get_relation_label()}")
        lines.append(f"认识时长: 从 {relation.first_met[:19].replace('T', ' ')} 开始")
        lines.append(f"共同经历: {relation.shared_history_count} 次")
        if relation.interaction_streak > 1:
            lines.append(f"连续互动: {relation.interaction_streak} 天")
        lines.append(f"亲密度: {relation.intimacy:.0%}")
        lines.append(f"信任度: {relation.trust_level:.0%}")
        lines.append(f"推荐对话风格: {relation.get_conversation_style()}")

        if relation.key_memories:
            lines.append("关键共同记忆:")
            for mem in relation.key_memories[-5:]:
                lines.append(f"- {mem}")

        if relation.preferences:
            lines.append("已知偏好:")
            for k, v in list(relation.preferences.items())[:3]:
                lines.append(f"- {k}: {v}")

        return "\n".join(lines)

    def get_all_relations(self, limit: int = 20) -> List[RelationNode]:
        """获取所有关系（按最后互动时间排序）"""
        with self._lock:
            conn = self._get_conn()
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM relations ORDER BY last_interaction DESC LIMIT ?",
                (limit,),
            )
            rows = cursor.fetchall()
            conn.close()
            return [self._row_to_relation(row) for row in rows]

    def _row_to_relation(self, row) -> RelationNode:
        """SQL行转RelationNode"""
        return RelationNode(
            user_id=row[0],
            user_name=row[1] or "",
            relation_type=row[2],
            intimacy=row[3],
            trust_level=row[4],
            emotional_bond=row[5],
            shared_history_count=row[6],
            last_interaction=row[7],
            first_met=row[8],
            key_memories=json.loads(row[9] or "[]"),
            preferences=json.loads(row[10] or "{}"),
            interaction_streak=row[11],
            created_at=row[12],
            updated_at=row[13],
        )

    def get_stats(self) -> Dict[str, Any]:
        """获取关系网络统计"""
        with self._lock:
            conn = self._get_conn()
            cursor = conn.cursor()
            stats = {}
            for rtype in self.RELATION_TYPES:
                cursor.execute(
                    "SELECT COUNT(*) FROM relations WHERE relation_type = ?",
                    (rtype,),
                )
                stats[rtype] = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM relations")
            stats["total"] = cursor.fetchone()[0]
            conn.close()
            return stats