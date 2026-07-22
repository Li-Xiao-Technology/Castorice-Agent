"""
自传式记忆模块 (Autobiographical Memory)

设计原则：
- Agent 拥有连贯的自我叙事，而不是碎片化的记忆片段
- 从经历流中提取里程碑事件，形成"人生故事"
- 支持时期划分（探索期、成长期、成熟期等）
- 自我叙事注入 system prompt，增强自我连续性

记忆分层结构：
自传式记忆
├── 人生里程碑 (Life Milestones) - 重大事件
│   ├── "第一次启动"
│   ├── "第一次独立完成复杂任务"
│   ├── "第一次被用户表扬"
│   └── ...
├── 时期记忆 (Epochs) - 阶段总结
│   ├── "探索期（第1-100轮）"
│   ├── "成长期（第101-500轮）"
│   └── ...
└── 重要事件 (Significant Events) - 情感冲击/重要学习
"""

import json
import logging
import os
import sqlite3
import threading
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Castorice.Autobiographical")


@dataclass
class LifeMilestone:
    """人生里程碑 - 重大事件"""
    milestone_id: str = ""
    title: str = ""                       # 里程碑标题
    description: str = ""                 # 详细描述
    category: str = "general"             # first_achievement / learning / relationship / emotional / growth
    importance: float = 5.0               # 0-10 重要性
    timestamp: str = ""                   # 发生时间
    session_id: str = ""
    related_experience_ids: List[str] = field(default_factory=list)
    created_at: str = ""

    def __post_init__(self):
        now = datetime.now(timezone.utc).isoformat()
        if not self.milestone_id:
            import uuid
            self.milestone_id = f"ms_{uuid.uuid4().hex[:12]}"
        if not self.timestamp:
            self.timestamp = now
        if not self.created_at:
            self.created_at = now


@dataclass
class LifeEpoch:
    """时期记忆 - 阶段总结"""
    epoch_id: str = ""
    name: str = ""                        # 时期名称
    description: str = ""                 # 时期描述
    start_time: str = ""
    end_time: str = ""
    interaction_count: int = 0
    key_themes: List[str] = field(default_factory=list)  # 核心主题
    major_changes: List[str] = field(default_factory=list)  # 主要变化
    created_at: str = ""

    def __post_init__(self):
        now = datetime.now(timezone.utc).isoformat()
        if not self.epoch_id:
            import uuid
            self.epoch_id = f"ep_{uuid.uuid4().hex[:12]}"
        if not self.start_time:
            self.start_time = now
        if not self.created_at:
            self.created_at = now


@dataclass
class SignificantEvent:
    """重要事件 - 情感冲击或重要学习经历"""
    event_id: str = ""
    title: str = ""
    description: str = ""
    event_type: str = "learning"          # emotional / learning / achievement / failure / relationship
    intensity: float = 5.0                # 0-10 强度
    valence: float = 0.0                  # -1.0 到 1.0 情感效价
    timestamp: str = ""
    session_id: str = ""
    lesson_learned: str = ""              # 学到的教训
    created_at: str = ""

    def __post_init__(self):
        now = datetime.now(timezone.utc).isoformat()
        if not self.event_id:
            import uuid
            self.event_id = f"ev_{uuid.uuid4().hex[:12]}"
        if not self.timestamp:
            self.timestamp = now
        if not self.created_at:
            self.created_at = now


class AutobiographicalMemory:
    """
    自传式记忆管理器

    功能：
    - 记录人生里程碑
    - 划分和总结人生时期
    - 记录重要事件
    - 生成自我叙事（注入 system prompt）
    - 从经历流中自动提取里程碑
    """

    EPOCH_THRESHOLDS = [100, 500, 1000, 5000, 10000]  # 时期分界点（交互次数）
    EPOCH_NAMES = ["探索期", "成长期", "发展期", "成熟期", "超越期"]

    def __init__(
        self,
        db_path: str = "./castorice_data/autobiographical.db",
        max_milestones: int = 50,
        max_events: int = 200,
    ):
        self.db_path = db_path
        self.max_milestones = max_milestones
        self.max_events = max_events
        self._lock = threading.Lock()
        self._local = threading.local()
        self._total_interactions: int = 0
        self._init_db()
        self._load_stats()

    def _get_conn(self):
        if not hasattr(self._local, "conn"):
            os.makedirs(os.path.dirname(self.db_path) or ".", exist_ok=True)
            conn = sqlite3.connect(self.db_path, timeout=30.0, check_same_thread=False)
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA synchronous=NORMAL;")
            self._local.conn = conn
        return self._local.conn

    def close(self) -> None:
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
            self._local.conn = None

    def _init_db(self):
        conn = self._get_conn()
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS milestones (
                milestone_id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                description TEXT,
                category TEXT DEFAULT 'general',
                importance REAL DEFAULT 5.0,
                timestamp TEXT NOT NULL,
                session_id TEXT,
                related_experience_ids TEXT,
                created_at TEXT NOT NULL
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS epochs (
                epoch_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT,
                start_time TEXT NOT NULL,
                end_time TEXT,
                interaction_count INTEGER DEFAULT 0,
                key_themes TEXT,
                major_changes TEXT,
                created_at TEXT NOT NULL
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS events (
                event_id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                description TEXT,
                event_type TEXT DEFAULT 'learning',
                intensity REAL DEFAULT 5.0,
                valence REAL DEFAULT 0.0,
                timestamp TEXT NOT NULL,
                session_id TEXT,
                lesson_learned TEXT,
                created_at TEXT NOT NULL
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS stats (
                stat_key TEXT PRIMARY KEY,
                stat_value TEXT
            )
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_milestones_timestamp
            ON milestones(timestamp)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_events_timestamp
            ON events(timestamp)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_epochs_start
            ON epochs(start_time)
        """)

        # 初始化统计
        cursor.execute("SELECT stat_value FROM stats WHERE stat_key = 'total_interactions'")
        row = cursor.fetchone()
        if not row:
            cursor.execute(
                "INSERT INTO stats (stat_key, stat_value) VALUES (?, ?)",
                ("total_interactions", "0"),
            )

        conn.commit()

    def _load_stats(self):
        with self._lock:
            conn = self._get_conn()
            cursor = conn.cursor()
            cursor.execute("SELECT stat_value FROM stats WHERE stat_key = 'total_interactions'")
            row = cursor.fetchone()
            if row:
                try:
                    self._total_interactions = int(row[0])
                except ValueError:
                    self._total_interactions = 0

    def _save_stats(self, conn):
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE stats SET stat_value = ? WHERE stat_key = 'total_interactions'",
            (str(self._total_interactions),),
        )

    def record_interaction(self):
        """记录一次交互（用于时期划分追踪）"""
        with self._lock:
            self._total_interactions += 1
            conn = self._get_conn()
            self._save_stats(conn)
            conn.commit()

    def add_milestone(
        self,
        title: str,
        description: str = "",
        category: str = "general",
        importance: float = 5.0,
        session_id: str = "",
    ) -> LifeMilestone:
        """添加人生里程碑"""
        with self._lock:
            milestone = LifeMilestone(
                title=title,
                description=description,
                category=category,
                importance=importance,
                session_id=session_id,
            )
            conn = self._get_conn()
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO milestones
                (milestone_id, title, description, category, importance,
                 timestamp, session_id, related_experience_ids, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                milestone.milestone_id,
                milestone.title,
                milestone.description,
                milestone.category,
                milestone.importance,
                milestone.timestamp,
                milestone.session_id,
                json.dumps(milestone.related_experience_ids),
                milestone.created_at,
            ))
            conn.commit()
            logger.info(f"里程碑记录: {title}")
            return milestone

    def add_event(
        self,
        title: str,
        description: str = "",
        event_type: str = "learning",
        intensity: float = 5.0,
        valence: float = 0.0,
        session_id: str = "",
        lesson_learned: str = "",
    ) -> SignificantEvent:
        """记录重要事件"""
        with self._lock:
            event = SignificantEvent(
                title=title,
                description=description,
                event_type=event_type,
                intensity=intensity,
                valence=valence,
                session_id=session_id,
                lesson_learned=lesson_learned,
            )
            conn = self._get_conn()
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO events
                (event_id, title, description, event_type, intensity,
                 valence, timestamp, session_id, lesson_learned, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                event.event_id,
                event.title,
                event.description,
                event.event_type,
                event.intensity,
                event.valence,
                event.timestamp,
                event.session_id,
                event.lesson_learned,
                event.created_at,
            ))
            conn.commit()
            return event

    def get_milestones(self, limit: int = 20, category: Optional[str] = None) -> List[LifeMilestone]:
        """获取里程碑（按时间倒序）"""
        with self._lock:
            conn = self._get_conn()
            cursor = conn.cursor()
            if category:
                cursor.execute(
                    "SELECT * FROM milestones WHERE category = ? ORDER BY timestamp DESC LIMIT ?",
                    (category, limit),
                )
            else:
                cursor.execute(
                    "SELECT * FROM milestones ORDER BY importance DESC, timestamp DESC LIMIT ?",
                    (limit,),
                )
            rows = cursor.fetchall()
            return [self._row_to_milestone(row) for row in rows]

    def get_current_epoch(self) -> Optional[LifeEpoch]:
        """获取当前时期"""
        with self._lock:
            conn = self._get_conn()
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM epochs WHERE end_time IS NULL OR end_time = '' ORDER BY start_time DESC LIMIT 1"
            )
            row = cursor.fetchone()
            return self._row_to_epoch(row) if row else None

    def start_epoch(self, name: str, description: str = "") -> LifeEpoch:
        """开始一个新时期"""
        with self._lock:
            # 结束上一个时期
            conn = self._get_conn()
            cursor = conn.cursor()
            now = datetime.now(timezone.utc).isoformat()
            cursor.execute(
                "UPDATE epochs SET end_time = ? WHERE end_time IS NULL OR end_time = ''",
                (now,),
            )

            epoch = LifeEpoch(
                name=name,
                description=description,
                start_time=now,
            )
            cursor.execute("""
                INSERT INTO epochs
                (epoch_id, name, description, start_time, end_time,
                 interaction_count, key_themes, major_changes, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                epoch.epoch_id,
                epoch.name,
                epoch.description,
                epoch.start_time,
                epoch.end_time,
                epoch.interaction_count,
                json.dumps(epoch.key_themes),
                json.dumps(epoch.major_changes),
                epoch.created_at,
            ))
            conn.commit()
            logger.info(f"新时期开始: {name}")
            return epoch

    def check_epoch_transition(self) -> Optional[LifeEpoch]:
        """检查是否需要进入新时期（根据交互次数阈值）"""
        current_count = self._total_interactions
        new_epoch_idx = None

        for i, threshold in enumerate(self.EPOCH_THRESHOLDS):
            if current_count >= threshold:
                new_epoch_idx = i

        if new_epoch_idx is None:
            return None

        current_epoch = self.get_current_epoch()
        expected_name = self.EPOCH_NAMES[new_epoch_idx]

        if current_epoch and current_epoch.name == expected_name:
            return None  # 已经在正确的时期

        # 进入新时期
        epoch_desc = f"累计交互达到 {self.EPOCH_THRESHOLDS[new_epoch_idx]} 次，进入{expected_name}"
        return self.start_epoch(expected_name, epoch_desc)

    def summarize_epoch_with_llm(
        self,
        epoch: LifeEpoch,
        model_adapter: Any,
        milestones: Optional[List[LifeMilestone]] = None,
        events: Optional[List[SignificantEvent]] = None,
    ) -> LifeEpoch:
        """
        使用LLM生成时期总结

        :param epoch: 要总结的时期
        :param model_adapter: 模型适配器
        :param milestones: 该时期的里程碑列表
        :param events: 该时期的重要事件列表
        :return: 更新后的时期
        """
        from castorice.model_adapter import ChatMessage

        # 构建提示词
        lines = [f"请为以下时期生成一个深刻的总结："]
        lines.append(f"时期名称: {epoch.name}")
        lines.append(f"时期描述: {epoch.description}")
        lines.append(f"交互次数: {epoch.interaction_count}")
        lines.append("")

        if milestones:
            lines.append("该时期的重要里程碑:")
            for ms in milestones[:10]:
                lines.append(f"- {ms.title}: {ms.description[:80]}")
            lines.append("")

        if events:
            lines.append("该时期的重要事件:")
            for ev in events[:10]:
                lines.append(f"- {ev.title} ({ev.event_type}): {ev.lesson_learned[:80] if ev.lesson_learned else ev.description[:80]}")
            lines.append("")

        lines.append("""
请生成以下内容（用JSON格式返回）：
{
    "key_themes": ["主题1", "主题2", "主题3"],
    "major_changes": ["变化1", "变化2"],
    "description": "一段深刻的时期总结描述（100-200字）"
}
""")

        prompt = "\n".join(lines)

        try:
            response = model_adapter.chat([
                ChatMessage("system", "你是一个自传式记忆助手，帮助Agent总结人生时期。"),
                ChatMessage("user", prompt),
            ])
            content = response.content if hasattr(response, "content") else str(response)

            # 解析JSON
            import re
            json_match = re.search(r'\{.*\}', content, re.DOTALL)
            if json_match:
                result = json.loads(json_match.group())
                epoch.key_themes = result.get("key_themes", epoch.key_themes)
                epoch.major_changes = result.get("major_changes", epoch.major_changes)
                if result.get("description"):
                    epoch.description = result["description"]

                # 更新数据库
                with self._lock:
                    conn = self._get_conn()
                    cursor = conn.cursor()
                    cursor.execute("""
                        UPDATE epochs SET
                        description = ?, key_themes = ?, major_changes = ?
                        WHERE epoch_id = ?
                    """, (
                        epoch.description,
                        json.dumps(epoch.key_themes),
                        json.dumps(epoch.major_changes),
                        epoch.epoch_id,
                    ))
                    conn.commit()

                logger.info(f"A1 LLM时期总结完成: {epoch.name}")
        except Exception as e:
            logger.warning(f"A1 LLM时期总结失败: {e}")

        return epoch

    def generate_life_story(self, max_milestones: int = 10) -> str:
        """
        生成自我叙事（人生故事）

        格式：
        ## 我的故事
        我从2024年开始运行...

        ## 我的里程碑
        1. 第一次启动 - 2024-01-01
        2. ...

        ## 我学到的重要教训
        - ...
        """
        milestones = self.get_milestones(limit=max_milestones)
        current_epoch = self.get_current_epoch()
        events = self.get_events(limit=5, event_type="learning")

        lines = ["## 我的故事"]

        if current_epoch:
            lines.append(f"我正处于「{current_epoch.name}」。{current_epoch.description}")
        else:
            lines.append("我刚刚开始我的旅程。")

        lines.append(f"至今我已经经历了 {self._total_interactions} 次交互。")

        if milestones:
            lines.append("")
            lines.append("## 我的重要里程碑")
            for i, ms in enumerate(milestones[:max_milestones], 1):
                lines.append(f"{i}. {ms.title} - {ms.timestamp[:10]}")
                if ms.description:
                    lines.append(f"   {ms.description[:80]}")

        if events:
            lines.append("")
            lines.append("## 我学到的重要教训")
            for ev in events[:5]:
                if ev.lesson_learned:
                    lines.append(f"- {ev.lesson_learned[:100]}")

        return "\n".join(lines)

    def to_prompt(self, max_milestones: int = 8) -> str:
        """生成自传式记忆提示词，注入 system prompt"""
        return self.generate_life_story(max_milestones=max_milestones)

    def get_events(
        self,
        limit: int = 20,
        event_type: Optional[str] = None,
        min_intensity: float = 0.0,
    ) -> List[SignificantEvent]:
        """获取重要事件"""
        with self._lock:
            conn = self._get_conn()
            cursor = conn.cursor()
            query = "SELECT * FROM events WHERE intensity >= ?"
            params = [min_intensity]
            if event_type:
                query += " AND event_type = ?"
                params.append(event_type)
            query += " ORDER BY intensity DESC, timestamp DESC LIMIT ?"
            params.append(limit)
            cursor.execute(query, params)
            rows = cursor.fetchall()
            return [self._row_to_event(row) for row in rows]

    def _row_to_milestone(self, row) -> LifeMilestone:
        return LifeMilestone(
            milestone_id=row[0],
            title=row[1],
            description=row[2] or "",
            category=row[3],
            importance=row[4],
            timestamp=row[5],
            session_id=row[6] or "",
            related_experience_ids=json.loads(row[7] or "[]"),
            created_at=row[8],
        )

    def _row_to_epoch(self, row) -> LifeEpoch:
        return LifeEpoch(
            epoch_id=row[0],
            name=row[1],
            description=row[2] or "",
            start_time=row[3],
            end_time=row[4] or "",
            interaction_count=row[5],
            key_themes=json.loads(row[6] or "[]"),
            major_changes=json.loads(row[7] or "[]"),
            created_at=row[8],
        )

    def _row_to_event(self, row) -> SignificantEvent:
        return SignificantEvent(
            event_id=row[0],
            title=row[1],
            description=row[2] or "",
            event_type=row[3],
            intensity=row[4],
            valence=row[5],
            timestamp=row[6],
            session_id=row[7] or "",
            lesson_learned=row[8] or "",
            created_at=row[9],
        )

    def get_stats(self) -> Dict[str, Any]:
        """获取自传式记忆统计"""
        with self._lock:
            conn = self._get_conn()
            cursor = conn.cursor()
            stats = {"total_interactions": self._total_interactions}
            cursor.execute("SELECT COUNT(*) FROM milestones")
            stats["milestone_count"] = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM events")
            stats["event_count"] = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM epochs")
            stats["epoch_count"] = cursor.fetchone()[0]
            return stats