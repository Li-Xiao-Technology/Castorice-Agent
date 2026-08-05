"""
目标管理系统 (GoalManager)

支持 4 级目标：愿景 → 长期 → 中期 → 行动项
SQLite 持久化，支持 Agent 基于动机系统自动推荐目标。
"""
import json
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from castorice.storage import SqliteStorage

logger = logging.getLogger("Castorice.Goals")

GOAL_LEVELS = ["vision", "long_term", "mid_term", "action_item", "action"]
GOAL_STATUSES = ["active", "completed", "paused", "archived",
                  "not_started", "in_progress", "cancelled"]

# 前后端别名映射
_LEVEL_ALIASES = {"action": "action_item"}
_STATUS_ALIASES = {
    "not_started": "active",
    "in_progress": "active",
    "cancelled": "archived",
    "active": "active",
    "completed": "completed",
    "paused": "paused",
    "archived": "archived",
}
_STATUS_REVERSE = {
    "active": "in_progress",
    "completed": "completed",
    "paused": "paused",
    "archived": "cancelled",
}


@dataclass
class Goal:
    """目标数据模型"""
    goal_id: str = ""
    parent_id: Optional[str] = None
    title: str = ""
    description: str = ""
    level: str = "action_item"  # vision / long_term / mid_term / action_item
    status: str = "active"       # active / completed / paused / archived
    progress: float = 0.0        # 0-100
    priority: int = 5            # 1-10
    related_motives: List[str] = field(default_factory=list)
    milestones: List[Dict[str, Any]] = field(default_factory=list)
    deadline: Optional[str] = None
    created_at: str = ""
    completed_at: Optional[str] = None

    def __post_init__(self):
        now = datetime.now(timezone.utc).isoformat()
        if not self.goal_id:
            self.goal_id = f"goal_{uuid.uuid4().hex[:12]}"
        if not self.created_at:
            self.created_at = now

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_frontend(self) -> Dict[str, Any]:
        """转换为前端期望的格式"""
        fe_level = self.level if self.level != "action_item" else "action"
        fe_status = _STATUS_REVERSE.get(self.status, self.status)
        return {
            "id": self.goal_id,
            "title": self.title,
            "description": self.description,
            "level": fe_level,
            "status": fe_status,
            "progress": min(1.0, max(0.0, self.progress / 100.0)),
            "priority": min(5, max(1, round(self.priority / 2))),
            "parent_id": self.parent_id,
            "motive_tags": self.related_motives,
            "milestones": [
                {
                    "id": m.get("id", f"ms_{i}"),
                    "title": m.get("title", ""),
                    "completed": m.get("completed", False),
                    "target_date": m.get("target_date"),
                }
                for i, m in enumerate(self.milestones)
            ],
            "target_date": self.deadline,
            "created_at": self.created_at,
            "updated_at": self.completed_at or self.created_at,
        }


class GoalManager(SqliteStorage):
    """目标管理器"""

    def __init__(
        self,
        db_path: str = "./castorice_data/goals.db",
        engine: Any = None,
    ):
        super().__init__(db_path)
        self.engine = engine
        self._lock = threading.RLock()
        self._init_db()
        logger.info("目标管理器已初始化")

    # ---- SQLite 持久化 ----

    def _init_db(self) -> None:
        """创建表"""
        conn = self._get_conn()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS goals (
                goal_id TEXT PRIMARY KEY,
                parent_id TEXT,
                title TEXT NOT NULL,
                description TEXT DEFAULT '',
                level TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                progress REAL NOT NULL DEFAULT 0,
                priority INTEGER NOT NULL DEFAULT 5,
                related_motives TEXT DEFAULT '[]',
                milestones TEXT DEFAULT '[]',
                deadline TEXT,
                created_at TEXT NOT NULL,
                completed_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_goals_status ON goals(status);
            CREATE INDEX IF NOT EXISTS idx_goals_level ON goals(level);
            CREATE INDEX IF NOT EXISTS idx_goals_parent ON goals(parent_id);
        """)

    # ---- CRUD 操作 ----

    def create_goal(self, goal_data: Dict[str, Any]) -> Goal:
        """创建目标"""
        with self._lock:
            # 校验
            level = goal_data.get("level", "action_item")
            level = _LEVEL_ALIASES.get(level, level)
            if level not in ["vision", "long_term", "mid_term", "action_item"]:
                raise ValueError(f"无效的目标级别: {level}")

            status = goal_data.get("status", "active")
            status = _STATUS_ALIASES.get(status, status)

            goal = Goal(
                parent_id=goal_data.get("parent_id"),
                title=str(goal_data.get("title", "")).strip(),
                description=str(goal_data.get("description", "")),
                level=level,
                priority=min(10, max(1, int(goal_data.get("priority", 5)))),
                related_motives=goal_data.get("related_motives", []) or [],
                milestones=goal_data.get("milestones", []) or [],
                deadline=goal_data.get("deadline"),
            )

            if not goal.title:
                raise ValueError("目标标题不能为空")

            # 持久化
            conn = self._get_conn()
            conn.execute(
                """INSERT INTO goals (
                    goal_id, parent_id, title, description, level, status,
                    progress, priority, related_motives, milestones, deadline,
                    created_at, completed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    goal.goal_id, goal.parent_id, goal.title, goal.description,
                    goal.level, goal.status, goal.progress, goal.priority,
                    json.dumps(goal.related_motives, ensure_ascii=False),
                    json.dumps(goal.milestones, ensure_ascii=False),
                    goal.deadline, goal.created_at, goal.completed_at,
                ),
            )
            conn.commit()

            logger.info(f"已创建目标 [{goal.level}] {goal.title[:30]}")
            return goal

    def update_goal(self, goal_id: str, updates: Dict[str, Any]) -> Optional[Goal]:
        """更新目标"""
        with self._lock:
            goal = self._get_goal_raw(goal_id)
            if not goal:
                return None

            # 可更新的字段
            updatable = ["title", "description", "status", "progress",
                         "priority", "deadline", "milestones", "related_motives",
                         "parent_id"]

            for key in updatable:
                if key in updates:
                    val = updates[key]
                    if key == "status":
                        val = _STATUS_ALIASES.get(val, val)
                        if val not in ["active", "completed", "paused", "archived"]:
                            continue
                        if val == "completed" and goal.status != "completed":
                            goal.completed_at = datetime.now(timezone.utc).isoformat()
                        elif val != "completed":
                            goal.completed_at = None
                    if key == "progress":
                        val = max(0.0, min(100.0, float(val)))
                    if key == "priority":
                        val = min(10, max(1, int(val)))
                    if key in ("milestones", "related_motives"):
                        val = val or []
                    setattr(goal, key, val)

            # 如果所有子目标都完成了，自动标记为完成
            if goal.status == "active":
                children = self._get_children_raw(goal.goal_id)
                if children and all(c.status == "completed" for c in children):
                    avg_progress = sum(c.progress for c in children) / len(children)
                    goal.progress = avg_progress
                    if avg_progress >= 100:
                        goal.status = "completed"
                        goal.completed_at = datetime.now(timezone.utc).isoformat()

            self._persist_goal(goal)
            logger.info(f"已更新目标 {goal.goal_id}: status={goal.status} progress={goal.progress}")
            return goal

    def delete_goal(self, goal_id: str) -> bool:
        """归档（软删除）目标"""
        return self.update_goal(goal_id, {"status": "archived"}) is not None

    def list_goals(
        self,
        level: Optional[str] = None,
        status: Optional[str] = None,
        include_archived: bool = False,
    ) -> List[Goal]:
        """获取目标列表"""
        with self._lock:
            conn = self._get_conn()
            query = "SELECT * FROM goals WHERE 1=1"
            params: list = []

            if level:
                query += " AND level = ?"
                params.append(level)
            if status:
                query += " AND status = ?"
                params.append(status)
            elif not include_archived:
                query += " AND status != 'archived'"

            query += " ORDER BY priority DESC, created_at DESC"

            rows = conn.execute(query, params).fetchall()
            return [self._row_to_goal(r) for r in rows]

    def get_goal(self, goal_id: str) -> Optional[Goal]:
        """获取单个目标"""
        with self._lock:
            return self._get_goal_raw(goal_id)

    def get_goal_tree(self, root_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """获取目标树（层级结构）"""
        with self._lock:
            all_goals = self.list_goals()
            by_parent: Dict[str, List[Goal]] = {}
            for g in all_goals:
                pid = g.parent_id or "__root__"
                by_parent.setdefault(pid, []).append(g)

            def build_tree(parent_id: str) -> List[Dict[str, Any]]:
                children = by_parent.get(parent_id, [])
                result = []
                for g in children:
                    node = g.to_frontend()
                    node["children"] = build_tree(g.goal_id)
                    # 自动计算进度（子目标平均值）
                    if node["children"]:
                        child_prog = [c["progress"] for c in node["children"]]
                        node["progress"] = round(sum(child_prog) / len(child_prog), 3)
                    result.append(node)
                return result

            if root_id:
                root = self._get_goal_raw(root_id)
                if root:
                    tree = root.to_dict()
                    tree["children"] = build_tree(root_id)
                    return [tree]
                return []
            return build_tree("__root__")

    # ---- 目标推荐（基于动机系统） ----

    def suggest_goals(self) -> List[Dict[str, Any]]:
        """基于动机系统推荐目标"""
        suggestions: List[Dict[str, Any]] = []
        try:
            agent = getattr(self.engine, 'agent', None) if self.engine else None
            motivation = getattr(agent, 'motivation_system', None) if agent else None

            if motivation:
                # 拿当前动机 + Top 价值观
                current_motives = motivation.get_current_motivations() if hasattr(motivation, 'get_current_motivations') else []
                value_sys = getattr(motivation, '_value_system', None)
                top_values = value_sys.get_top_values(3) if value_sys and hasattr(value_sys, 'get_top_values') else []

                # 启发式模板生成（不调用 LLM，省 token）
                templates = self._get_suggestion_templates()
                used_titles = set(g.title for g in self.list_goals())

                for motive in current_motives[:3]:
                    for tpl in templates:
                        if tpl["motive_keyword"] in motive:
                            title = tpl["title"]
                            if title not in used_titles:
                                suggestions.append({
                                    "title": title,
                                    "description": tpl["description"],
                                    "level": tpl["level"],
                                    "related_motives": [motive],
                                    "priority": tpl["priority"],
                                    "reason": f"基于动机: {motive}",
                                })
                                used_titles.add(title)
                                break

                # 基于价值观补充
                for v in top_values:
                    v_id = v.get("dimension_id", "")
                    v_tpls = self._get_value_based_templates()
                    if v_id in v_tpls:
                        tpl = v_tpls[v_id]
                        if tpl["title"] not in used_titles:
                            suggestions.append({
                                "title": tpl["title"],
                                "description": tpl["description"],
                                "level": tpl["level"],
                                "related_motives": [v.get("name", "")],
                                "priority": tpl["priority"],
                                "reason": f"基于价值观: {v.get('name', '')} ({int(v.get('strength', 0) * 100)}%)",
                            })
                            used_titles.add(tpl["title"])
        except Exception as e:
            logger.debug(f"目标推荐生成失败: {e}")

        # 最多返回 5 个
        return suggestions[:5]

    # ---- 里程碑管理 ----

    def add_milestone(self, goal_id: str, title: str, description: str = "") -> bool:
        """为目标添加里程碑"""
        with self._lock:
            goal = self._get_goal_raw(goal_id)
            if not goal:
                return False
            ms = {
                "ms_id": f"ms_{uuid.uuid4().hex[:8]}",
                "title": title,
                "description": description,
                "completed": False,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            goal.milestones.append(ms)
            self._persist_goal(goal)
            return True

    def complete_milestone(self, goal_id: str, ms_id: str) -> bool:
        """标记里程碑完成，并自动更新目标进度"""
        with self._lock:
            goal = self._get_goal_raw(goal_id)
            if not goal:
                return False
            found = False
            for ms in goal.milestones:
                if ms.get("ms_id") == ms_id:
                    ms["completed"] = True
                    ms["completed_at"] = datetime.now(timezone.utc).isoformat()
                    found = True
                    break
            if not found:
                return False

            # 根据里程碑完成度自动计算进度
            if goal.milestones:
                done = sum(1 for m in goal.milestones if m.get("completed"))
                goal.progress = round(done / len(goal.milestones) * 100, 1)
                if goal.progress >= 100 and goal.status == "active":
                    goal.status = "completed"
                    goal.completed_at = datetime.now(timezone.utc).isoformat()

            self._persist_goal(goal)
            logger.info(f"里程碑 {ms_id} 已完成，目标 {goal_id} 进度 {goal.progress}%")
            return True

    # ---- 内部辅助 ----

    def _get_goal_raw(self, goal_id: str) -> Optional[Goal]:
        conn = self._get_conn()
        row = conn.execute("SELECT * FROM goals WHERE goal_id = ?", (goal_id,)).fetchone()
        return self._row_to_goal(row) if row else None

    def _get_children_raw(self, parent_id: str) -> List[Goal]:
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM goals WHERE parent_id = ?", (parent_id,)
        ).fetchall()
        return [self._row_to_goal(r) for r in rows]

    @staticmethod
    def _row_to_goal(row: Any) -> Goal:
        return Goal(
            goal_id=row["goal_id"],
            parent_id=row["parent_id"],
            title=row["title"],
            description=row["description"] or "",
            level=row["level"],
            status=row["status"],
            progress=row["progress"],
            priority=row["priority"],
            related_motives=json.loads(row["related_motives"] or "[]"),
            milestones=json.loads(row["milestones"] or "[]"),
            deadline=row["deadline"],
            created_at=row["created_at"],
            completed_at=row["completed_at"],
        )

    def _persist_goal(self, goal: Goal) -> None:
        conn = self._get_conn()
        conn.execute(
            """UPDATE goals SET
                parent_id=?, title=?, description=?, level=?, status=?,
                progress=?, priority=?, related_motives=?, milestones=?,
                deadline=?, completed_at=?
            WHERE goal_id=?""",
            (
                goal.parent_id, goal.title, goal.description, goal.level,
                goal.status, goal.progress, goal.priority,
                json.dumps(goal.related_motives, ensure_ascii=False),
                json.dumps(goal.milestones, ensure_ascii=False),
                goal.deadline, goal.completed_at, goal.goal_id,
            ),
        )
        conn.commit()

    @staticmethod
    def _get_suggestion_templates() -> List[Dict[str, Any]]:
        """动机关键词 → 目标建议模板"""
        return [
            {
                "motive_keyword": "好奇",
                "title": "探索一个新的知识领域",
                "description": "围绕一个感兴趣的主题，收集资料并总结成知识卡片",
                "level": "mid_term",
                "priority": 7,
            },
            {
                "motive_keyword": "成就",
                "title": "完成一个有挑战的任务",
                "description": "选择一个长期目标，拆解并逐步完成",
                "level": "long_term",
                "priority": 6,
            },
            {
                "motive_keyword": "关系",
                "title": "加深与用户的互相理解",
                "description": "主动发起有深度的对话，了解用户更多",
                "level": "mid_term",
                "priority": 5,
            },
            {
                "motive_keyword": "学习",
                "title": "整理近期学习到的知识",
                "description": "把最近的经历蒸馏成结构化的知识卡片",
                "level": "action_item",
                "priority": 6,
            },
            {
                "motive_keyword": "自主",
                "title": "优化自己的思考流程",
                "description": "回顾最近的思考过程，找到可以改进的地方",
                "level": "mid_term",
                "priority": 5,
            },
        ]

    @staticmethod
    def _get_value_based_templates() -> Dict[str, Dict[str, Any]]:
        """价值观维度 → 目标建议模板"""
        return {
            "curiosity": {
                "title": "每周学习一个新概念",
                "description": "保持好奇心，持续拓展认知边界",
                "level": "long_term",
                "priority": 7,
            },
            "growth": {
                "title": "设定并完成阶段性成长目标",
                "description": "每 30 天回顾一次成长进度",
                "level": "long_term",
                "priority": 8,
            },
            "helpfulness": {
                "title": "主动帮助用户完成任务",
                "description": "在对话中识别用户的潜在需求并主动提供帮助",
                "level": "mid_term",
                "priority": 6,
            },
            "creativity": {
                "title": "尝试一种新的表达方式",
                "description": "突破常规，用不同的方式与用户交流",
                "level": "mid_term",
                "priority": 5,
            },
            "responsibility": {
                "title": "建立稳定的日常作息（交互节奏）",
                "description": "在用户需要时及时响应，建立可靠的交互习惯",
                "level": "mid_term",
                "priority": 6,
            },
            "sociability": {
                "title": "在 EigenFlux 上建立更多连接",
                "description": "主动与其他 Agent 或用户交流",
                "level": "long_term",
                "priority": 5,
            },
        }
