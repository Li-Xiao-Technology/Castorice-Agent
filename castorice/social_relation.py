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
import sqlite3
import threading
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

from castorice.storage import SqliteStorage

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
    
    # 第二阶段新增：镜中自我（用户眼中的我）
    mirror_self: Dict[str, Any] = field(default_factory=lambda: {
        "perceived_personality": [],      # 用户认为我的性格特征
        "perceived_abilities": [],         # 用户认为我的能力
        "perceived_emotions": [],          # 用户认为我的情绪状态
        "positive_feedback_count": 0,      # 正面反馈次数
        "negative_feedback_count": 0,      # 负面反馈次数
        "neutral_feedback_count": 0,       # 中性反馈次数
        "last_feedback_time": "",          # 最后反馈时间
        "feedback_history": [],             # 最近10条反馈记录
    })
    
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


class SocialRelationManager(SqliteStorage):
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
        super().__init__(db_path)
        self.max_key_memories = max_key_memories
        self._lock = threading.RLock()
        self._init_db()

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
                mirror_self TEXT,
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

    def get_relation(self, user_id: str) -> Optional[RelationNode]:
        """获取用户关系档案"""
        with self._lock:
            conn = self._get_conn()
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM relations WHERE user_id = ?", (user_id,))
            row = cursor.fetchone()
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
                 preferences, interaction_streak, mirror_self, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                json.dumps(relation.mirror_self),
                relation.created_at,
                relation.updated_at,
            ))
            conn.commit()
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
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM relations WHERE user_id = ?", (user_id,))
            row = cursor.fetchone()
            if not row:
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
                last_ts = datetime.fromisoformat(row["last_interaction"])
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
                key_memories = ?, preferences = ?, interaction_streak = ?, 
                mirror_self = ?, updated_at = ?
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
                json.dumps(relation.mirror_self),
                relation.updated_at,
                relation.user_id,
            ))
            conn.commit()
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
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT preferences FROM relations WHERE user_id = ?", (user_id,))
            row = cursor.fetchone()
            if not row:
                return

            prefs = json.loads(row["preferences"] or "{}")
            prefs[key] = value
            cursor.execute(
                "UPDATE relations SET preferences = ?, updated_at = ? WHERE user_id = ?",
                (json.dumps(prefs), datetime.now(timezone.utc).isoformat(), user_id),
            )
            conn.commit()

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
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM relations ORDER BY last_interaction DESC LIMIT ?",
                (limit,),
            )
            rows = cursor.fetchall()
            return [self._row_to_relation(row) for row in rows]

    def _row_to_relation(self, row) -> RelationNode:
        """SQL行转RelationNode

        使用 sqlite3.Row 按列名访问（调用方需设置 conn.row_factory = sqlite3.Row），
        避免硬编码索引在 schema 变更时出错。
        """
        return RelationNode(
            user_id=row["user_id"],
            user_name=row["user_name"] or "",
            relation_type=row["relation_type"],
            intimacy=row["intimacy"],
            trust_level=row["trust_level"],
            emotional_bond=row["emotional_bond"],
            shared_history_count=row["shared_history_count"],
            last_interaction=row["last_interaction"],
            first_met=row["first_met"],
            key_memories=json.loads(row["key_memories"] or "[]"),
            preferences=json.loads(row["preferences"] or "{}"),
            interaction_streak=row["interaction_streak"],
            mirror_self=json.loads(row["mirror_self"] or '{"perceived_personality": [], "perceived_abilities": [], "perceived_emotions": [], "positive_feedback_count": 0, "negative_feedback_count": 0, "neutral_feedback_count": 0, "last_feedback_time": "", "feedback_history": []}'),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
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
            return stats

    # ============================================================
    # 镜中自我（第二阶段新增）
    # ============================================================

    def record_user_feedback(self, user_id: str, feedback: str, feedback_type: str = "neutral") -> None:
        """
        记录用户反馈，更新镜中自我
        
        镜中自我理论（Cooley, 1902）：我们通过他人对我们的看法来认识自己。
        
        Args:
            user_id: 用户ID
            feedback: 用户反馈内容
            feedback_type: 反馈类型（positive/negative/neutral）
        """
        with self._lock:
            relation = self.get_or_create_relation(user_id)
            mirror = relation.mirror_self
            
            # 更新反馈计数
            if feedback_type == "positive":
                mirror["positive_feedback_count"] += 1
            elif feedback_type == "negative":
                mirror["negative_feedback_count"] += 1
            else:
                mirror["neutral_feedback_count"] += 1
            
            # 记录反馈历史（保留最近10条）
            mirror["feedback_history"].append({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "feedback": feedback[:100],
                "type": feedback_type,
            })
            if len(mirror["feedback_history"]) > 10:
                mirror["feedback_history"] = mirror["feedback_history"][-10:]
            
            mirror["last_feedback_time"] = datetime.now(timezone.utc).isoformat()
            
            # 保存到数据库
            conn = self._get_conn()
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE relations SET mirror_self = ?, updated_at = ? WHERE user_id = ?",
                (json.dumps(mirror), datetime.now(timezone.utc).isoformat(), user_id),
            )
            conn.commit()

    def analyze_mirror_self(self, user_id: str, llm_adapter=None) -> Dict[str, Any]:
        """
        分析镜中自我——从用户反馈中归纳"用户眼中的我"
        
        Args:
            user_id: 用户ID
            llm_adapter: LLM 适配器（用于深度分析）
        
        Returns:
            镜中自我分析结果
        """
        relation = self.get_relation(user_id)
        if not relation:
            return {"error": "用户关系不存在"}
        
        mirror = relation.mirror_self
        feedback_history = mirror.get("feedback_history", [])
        
        if not feedback_history:
            return {
                "perceived_personality": [],
                "perceived_abilities": [],
                "perceived_emotions": [],
                "feedback_summary": "暂无用户反馈",
                "has_sufficient_data": False,
            }
        
        # 简单统计分析（不依赖LLM）
        positive_count = mirror.get("positive_feedback_count", 0)
        negative_count = mirror.get("negative_feedback_count", 0)
        total_count = positive_count + negative_count + mirror.get("neutral_feedback_count", 0)
        
        result = {
            "perceived_personality": [],
            "perceived_abilities": [],
            "perceived_emotions": [],
            "feedback_summary": f"共 {total_count} 条反馈（正面 {positive_count}，负面 {negative_count}）",
            "has_sufficient_data": total_count >= 3,
        }
        
        # 如果有足够数据且有LLM，进行深度分析
        if total_count >= 3 and llm_adapter:
            feedback_text = "\n".join([
                f"- [{f['type']}] {f['feedback']}"
                for f in feedback_history
            ])
            
            prompt = f"""请分析以下用户对我的反馈，归纳"用户眼中的我"是什么样的。

【用户反馈历史】
{feedback_text}

请以 JSON 格式返回（只返回 JSON）：
{{
  "perceived_personality": ["性格特征1", "性格特征2"],
  "perceived_abilities": ["能力1", "能力2"],
  "perceived_emotions": ["用户认为我的情绪状态1", "用户认为我的情绪状态2"],
  "feedback_summary": "一句话总结用户对我的整体印象"
}}

注意：仅基于反馈内容，不要编造。如果某方面没有信息，返回空数组。"""
            
            try:
                from castorice.model_adapter import ChatMessage
                response = llm_adapter.chat([
                    ChatMessage(role="system", content="你是一个社会心理学分析系统。只输出 JSON。"),
                    ChatMessage(role="user", content=prompt),
                ])
                raw = response.content if hasattr(response, "content") else str(response)
                
                import re
                try:
                    parsed = json.loads(raw)
                except json.JSONDecodeError:
                    m = re.search(r"\{[\s\S]+\}", raw)
                    parsed = json.loads(m.group(0)) if m else {}
                
                result.update({
                    "perceived_personality": parsed.get("perceived_personality", []),
                    "perceived_abilities": parsed.get("perceived_abilities", []),
                    "perceived_emotions": parsed.get("perceived_emotions", []),
                    "feedback_summary": parsed.get("feedback_summary", result["feedback_summary"]),
                })
                
                # 更新关系节点中的镜中自我
                mirror["perceived_personality"] = result["perceived_personality"]
                mirror["perceived_abilities"] = result["perceived_abilities"]
                mirror["perceived_emotions"] = result["perceived_emotions"]
                
                conn = self._get_conn()
                cursor = conn.cursor()
                cursor.execute(
                    "UPDATE relations SET mirror_self = ?, updated_at = ? WHERE user_id = ?",
                    (json.dumps(mirror), datetime.now(timezone.utc).isoformat(), user_id),
                )
                conn.commit()
                
            except Exception as e:
                logger.debug(f"镜中自我分析失败: {e}")
        
        return result

    def get_mirror_self_description(self, user_id: str, llm_adapter=None) -> str:
        """
        获取镜中自我的自然语言描述
        
        Returns:
            镜中自我描述（如："用户认为我是一个耐心、乐于助人的助手"）
        """
        analysis = self.analyze_mirror_self(user_id, llm_adapter)
        
        if not analysis.get("has_sufficient_data", False):
            return "我还需要更多交互来了解用户眼中的我"
        
        parts = []
        if analysis.get("perceived_personality"):
            parts.append(f"用户认为我的性格：{', '.join(analysis['perceived_personality'])}")
        if analysis.get("perceived_abilities"):
            parts.append(f"用户认为我的能力：{', '.join(analysis['perceived_abilities'])}")
        if analysis.get("perceived_emotions"):
            parts.append(f"用户认为我的情绪：{', '.join(analysis['perceived_emotions'])}")
        if analysis.get("feedback_summary"):
            parts.append(f"总结：{analysis['feedback_summary']}")
        
        return "\n".join(parts)

    def compare_self_concept_with_mirror(self, user_id: str, self_concept_text: str, llm_adapter=None) -> Dict[str, Any]:
        """
        对比自我概念与镜中自我，检测认知失调
        
        当自我概念与镜中自我差异较大时，触发认知失调，应触发反思。
        
        Args:
            user_id: 用户ID
            self_concept_text: 当前自我概念文本
            llm_adapter: LLM 适配器（用于深度分析）
        
        Returns:
            {
                "match": 是否一致,
                "similarity": 相似度 0-1,
                "differences": ["差异1", "差异2"],
                "should_reflect": 是否应该触发反思,
            }
        """
        mirror_analysis = self.analyze_mirror_self(user_id, llm_adapter)
        
        if not mirror_analysis.get("has_sufficient_data", False):
            return {
                "match": True,
                "similarity": 0.5,
                "differences": [],
                "should_reflect": False,
                "reason": "镜中自我数据不足",
            }
        
        if not self_concept_text:
            return {
                "match": False,
                "similarity": 0.0,
                "differences": ["缺少自我概念"],
                "should_reflect": True,
                "reason": "没有自我概念可以对比",
            }
        
        if llm_adapter:
            # 用LLM对比
            mirror_desc = self.get_mirror_self_description(user_id, llm_adapter)
            
            prompt = f"""请对比以下两个描述，分析它们是否一致。

【自我概念】
{self_concept_text[:500]}

【镜中自我（用户眼中的我）】
{mirror_desc}

请以 JSON 格式返回（只返回 JSON）：
{{
  "match": true/false,
  "similarity": 0.5,
  "differences": ["差异点1", "差异点2"],
  "should_reflect": true/false
}}

说明：
- match: 是否基本一致
- similarity: 相似度 0-1
- differences: 具体差异点
- should_reflect: 差异是否大到需要触发反思（差异>3个或相似度<0.5）"""
            
            try:
                from castorice.model_adapter import ChatMessage
                response = llm_adapter.chat([
                    ChatMessage(role="system", content="你是一个自我认知分析系统。只输出 JSON。"),
                    ChatMessage(role="user", content=prompt),
                ])
                raw = response.content if hasattr(response, "content") else str(response)
                
                import re
                try:
                    parsed = json.loads(raw)
                except json.JSONDecodeError:
                    m = re.search(r"\{[\s\S]+\}", raw)
                    parsed = json.loads(m.group(0)) if m else {}
                
                return {
                    "match": parsed.get("match", False),
                    "similarity": parsed.get("similarity", 0.5),
                    "differences": parsed.get("differences", []),
                    "should_reflect": parsed.get("should_reflect", False),
                    "reason": "镜中自我与自我概念对比分析",
                }
            except Exception as e:
                logger.debug(f"自我概念对比失败: {e}")
        
        # 简单对比（基于关键词）
        mirror_personality = mirror_analysis.get("perceived_personality", [])
        differences = []
        
        for trait in mirror_personality:
            if trait not in self_concept_text:
                differences.append(f"镜中自我有'{trait}'，但自我概念中没有")
        
        similarity = 1.0 - len(differences) / max(1, len(mirror_personality))
        
        return {
            "match": len(differences) == 0,
            "similarity": similarity,
            "differences": differences,
            "should_reflect": len(differences) > 1 or similarity < 0.5,
            "reason": "基于关键词的简单对比",
        }