"""
长期意图追踪系统 (Long-Term Intent Tracking)

设计原则：
- 多轮对话中持续追踪用户的核心需求和目标
- 意图状态流转：active → paused → completed
- 支持意图继承和子意图链
- 每轮对话后用 LLM 更新意图状态
- 主动轮检测时检查未完成意图

数据模型：
IntentNode:
  - intent_id: 唯一标识
  - root_intent: 原始意图描述
  - sub_intents: 子意图链（追踪意图演变）
  - status: active / paused / completed
  - progress: 完成度 0.0-1.0
  - last_mentioned: 最后提及时间
  - context: 上下文摘要
  - session_ids: 关联的会话ID列表
"""

import json
import logging
import threading
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Castorice.IntentTracker")


@dataclass
class IntentNode:
    """意图节点数据结构"""
    intent_id: str = ""
    root_intent: str = ""
    sub_intents: List[str] = field(default_factory=list)
    sub_tasks: List[Dict[str, Any]] = field(default_factory=list)  # 子任务列表
    status: str = "active"
    progress: float = 0.0
    last_mentioned: str = ""
    context: str = ""
    session_ids: List[str] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()
        if not self.last_mentioned:
            self.last_mentioned = self.created_at
        if not self.intent_id:
            self.intent_id = str(uuid.uuid4())[:8]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "IntentNode":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    def is_active(self) -> bool:
        return self.status == "active"

    def is_completed(self) -> bool:
        return self.status == "completed"

    def update_progress(self, new_progress: float):
        self.progress = max(0.0, min(1.0, new_progress))
        if self.progress >= 1.0:
            self.status = "completed"
        self.updated_at = datetime.now(timezone.utc).isoformat()

    def add_sub_intent(self, sub_intent: str):
        if sub_intent and sub_intent not in self.sub_intents:
            self.sub_intents.append(sub_intent)
            self.last_mentioned = datetime.now(timezone.utc).isoformat()

    def add_sub_task(self, task_description: str, priority: float = 0.5):
        """添加子任务"""
        import uuid
        task = {
            "task_id": f"task_{uuid.uuid4().hex[:8]}",
            "description": task_description,
            "status": "pending",  # pending / in_progress / completed
            "priority": priority,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "completed_at": "",
        }
        self.sub_tasks.append(task)
        self.last_mentioned = datetime.now(timezone.utc).isoformat()
        return task

    def complete_sub_task(self, task_id: str) -> bool:
        """完成子任务"""
        for task in self.sub_tasks:
            if task.get("task_id") == task_id:
                task["status"] = "completed"
                task["completed_at"] = datetime.now(timezone.utc).isoformat()
                # 更新总进度
                completed = sum(1 for t in self.sub_tasks if t.get("status") == "completed")
                self.update_progress(completed / len(self.sub_tasks))
                return True
        return False

    def get_pending_tasks(self) -> List[Dict[str, Any]]:
        """获取待完成的子任务"""
        return [t for t in self.sub_tasks if t.get("status") in ("pending", "in_progress")]

    def mark_mentioned(self):
        self.last_mentioned = datetime.now(timezone.utc).isoformat()


class IntentTracker:
    """
    意图追踪器

    功能：
    - 追踪用户的长期意图（跨会话）
    - 每轮对话后更新意图状态
    - 提供未完成意图查询
    - 意图注入到系统提示词
    """

    def __init__(
        self,
        db_path: str = "./castorice_data/intent_tracker.db",
        max_intents_per_session: int = 10,
        intent_expiry_days: int = 30,
    ):
        self.db_path = db_path
        self.max_intents_per_session = max_intents_per_session
        self.intent_expiry_days = intent_expiry_days
        self._lock = threading.Lock()
        self._local = threading.local()
        self._init_db()

    def _get_conn(self):
        """thread-local SQLite 连接（复用，避免频繁创建/关闭）"""
        import sqlite3
        import os
        if not hasattr(self._local, "conn"):
            os.makedirs(os.path.dirname(self.db_path) or ".", exist_ok=True)
            conn = sqlite3.connect(self.db_path, timeout=30.0, check_same_thread=False)
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA synchronous=NORMAL;")
            self._local.conn = conn
        return self._local.conn

    def close(self) -> None:
        """关闭当前线程的连接"""
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
            CREATE TABLE IF NOT EXISTS intents (
                intent_id TEXT PRIMARY KEY,
                root_intent TEXT NOT NULL,
                sub_intents TEXT,
                sub_tasks TEXT,
                status TEXT DEFAULT 'active',
                progress REAL DEFAULT 0.0,
                last_mentioned TEXT NOT NULL,
                context TEXT,
                session_ids TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_intents_status
            ON intents(status, last_mentioned)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_intents_session
            ON intents(session_ids)
        """)
        conn.commit()

    def add_intent(
        self,
        root_intent: str,
        session_id: str,
        context: str = "",
    ) -> IntentNode:
        """添加新意图"""
        with self._lock:
            intent = IntentNode(
                root_intent=root_intent,
                context=context,
                session_ids=[session_id],
            )
            conn = self._get_conn()
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO intents
                (intent_id, root_intent, sub_intents, sub_tasks, status, progress,
                 last_mentioned, context, session_ids, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                intent.intent_id,
                intent.root_intent,
                json.dumps(intent.sub_intents),
                json.dumps(intent.sub_tasks),
                intent.status,
                intent.progress,
                intent.last_mentioned,
                intent.context,
                json.dumps(intent.session_ids),
                intent.created_at,
                intent.updated_at,
            ))
            conn.commit()
            logger.info(f"新增意图: {intent.intent_id} | {root_intent[:50]}")
            return intent

    def update_intent(
        self,
        intent_id: str,
        root_intent: Optional[str] = None,
        sub_intent: Optional[str] = None,
        status: Optional[str] = None,
        progress: Optional[float] = None,
        context: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> Optional[IntentNode]:
        """更新意图"""
        with self._lock:
            conn = self._get_conn()
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM intents WHERE intent_id = ?", (intent_id,))
            row = cursor.fetchone()
            if not row:
                        return None

            intent = IntentNode.from_dict({
                "intent_id": row[0],
                "root_intent": row[1],
                "sub_intents": json.loads(row[2] or "[]"),
                "sub_tasks": json.loads(row[3] or "[]"),
                "status": row[4],
                "progress": row[5],
                "last_mentioned": row[6],
                "context": row[7],
                "session_ids": json.loads(row[8] or "[]"),
                "created_at": row[9],
                "updated_at": row[10],
            })

            if root_intent:
                intent.root_intent = root_intent
            if sub_intent:
                intent.add_sub_intent(sub_intent)
            if status:
                intent.status = status
            if progress is not None:
                intent.update_progress(progress)
            if context:
                intent.context = context
            if session_id and session_id not in intent.session_ids:
                intent.session_ids.append(session_id)

            now = datetime.now(timezone.utc).isoformat()
            intent.updated_at = now

            cursor.execute("""
                UPDATE intents SET
                root_intent = ?, sub_intents = ?, sub_tasks = ?, status = ?, progress = ?,
                last_mentioned = ?, context = ?, session_ids = ?, updated_at = ?
                WHERE intent_id = ?
            """, (
                intent.root_intent,
                json.dumps(intent.sub_intents),
                json.dumps(intent.sub_tasks),
                intent.status,
                intent.progress,
                intent.last_mentioned,
                intent.context,
                json.dumps(intent.session_ids),
                intent.updated_at,
                intent.intent_id,
            ))
            conn.commit()
            return intent

    def get_active_intents(self, limit: int = 10) -> List[IntentNode]:
        """获取所有活跃意图"""
        with self._lock:
            conn = self._get_conn()
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM intents WHERE status = 'active' ORDER BY last_mentioned DESC LIMIT ?",
                (limit,),
            )
            rows = cursor.fetchall()
            return [self._row_to_intent(row) for row in rows]

    def get_intents_by_session(self, session_id: str, limit: int = 10) -> List[IntentNode]:
        """获取某个会话关联的意图"""
        with self._lock:
            conn = self._get_conn()
            cursor = conn.cursor()
            # 使用 json_each() 精确匹配 JSON 数组元素，避免子串误报
            # 例如 session_id="123" 不会再匹配到包含 "1234" 的记录
            cursor.execute(
                "SELECT * FROM intents WHERE json_array_length(session_ids) > 0 "
                "AND EXISTS (SELECT 1 FROM json_each(session_ids) WHERE value = ?) "
                "ORDER BY last_mentioned DESC LIMIT ?",
                (session_id, limit),
            )
            rows = cursor.fetchall()
            return [self._row_to_intent(row) for row in rows]

    def get_expired_intents(self) -> List[IntentNode]:
        """获取过期意图（超过指定天数未提及）"""
        with self._lock:
            cutoff = (datetime.now(timezone.utc) - timedelta(days=self.intent_expiry_days)).isoformat()
            conn = self._get_conn()
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM intents WHERE last_mentioned < ? AND status != 'completed'",
                (cutoff,),
            )
            rows = cursor.fetchall()
            return [self._row_to_intent(row) for row in rows]

    def cleanup_expired(self) -> int:
        """清理过期意图"""
        with self._lock:
            cutoff = (datetime.now(timezone.utc) - timedelta(days=self.intent_expiry_days)).isoformat()
            conn = self._get_conn()
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM intents WHERE last_mentioned < ? AND status != 'completed'",
                (cutoff,),
            )
            deleted = cursor.rowcount
            conn.commit()
            if deleted > 0:
                logger.info(f"清理了 {deleted} 个过期意图")
            return deleted

    def get_intent_by_id(self, intent_id: str) -> Optional[IntentNode]:
        """根据ID获取意图"""
        with self._lock:
            conn = self._get_conn()
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM intents WHERE intent_id = ?", (intent_id,))
            row = cursor.fetchone()
            return self._row_to_intent(row) if row else None

    def delete_intent(self, intent_id: str) -> bool:
        """删除意图"""
        with self._lock:
            conn = self._get_conn()
            cursor = conn.cursor()
            cursor.execute("DELETE FROM intents WHERE intent_id = ?", (intent_id,))
            deleted = cursor.rowcount > 0
            conn.commit()
            return deleted

    def _row_to_intent(self, row) -> IntentNode:
        """SQL行转IntentNode"""
        return IntentNode.from_dict({
            "intent_id": row[0],
            "root_intent": row[1],
            "sub_intents": json.loads(row[2] or "[]"),
            "sub_tasks": json.loads(row[3] or "[]"),
            "status": row[4],
            "progress": row[5],
            "last_mentioned": row[6],
            "context": row[7],
            "session_ids": json.loads(row[8] or "[]"),
            "created_at": row[9],
            "updated_at": row[10],
        })

    def to_prompt(self, session_id: str = "", max_intents: int = 5) -> str:
        """
        生成意图提示词，注入到 system prompt

        格式：
        ## 未完成意图
        - [进度50%] 用户想做XXX（上次提及：2026-07-20 10:00）
        """
        if session_id:
            intents = self.get_intents_by_session(session_id, limit=max_intents)
        else:
            intents = self.get_active_intents(limit=max_intents)

        active = [i for i in intents if i.is_active()]
        if not active:
            return ""

        lines = ["## 未完成意图"]
        for intent in active:
            time_str = intent.last_mentioned[:19].replace("T", " ")
            lines.append(f"- [{intent.status}] [{intent.progress:.0%}] {intent.root_intent}（上次提及：{time_str}）")
            if intent.sub_intents:
                for sub in intent.sub_intents[-3:]:
                    lines.append(f"  - 子意图：{sub}")
            if intent.sub_tasks:
                pending = intent.get_pending_tasks()
                if pending:
                    lines.append(f"  - 待办子任务（{len(pending)}个）：")
                    for task in pending[:3]:
                        lines.append(f"    * [{task.get('status')}] {task.get('description', '')[:40]}")

        return "\n".join(lines)

    def analyze_and_update(
        self,
        user_input: str,
        agent_response: str,
        session_id: str,
        model_adapter: Any = None,
    ) -> List[IntentNode]:
        """
        使用 LLM 分析对话，更新意图状态

        逻辑：
        1. 分析用户输入中是否有新意图
        2. 分析现有意图是否推进/完成
        3. 更新意图状态
        """
        if model_adapter is None:
            logger.debug("模型适配器不可用，跳过意图分析")
            return []

        try:
            from castorice.model_adapter import ChatMessage
            from castorice.utils import extract_json

            active_intents = self.get_active_intents(limit=10)
            intents_text = "\n".join(
                f"- {i.intent_id}: [{i.progress:.0%}] {i.root_intent}"
                for i in active_intents
            ) or "(无活跃意图)"

            prompt = f"""你是意图分析专家。请分析以下对话，更新用户意图状态。

【当前活跃意图】
{intents_text}

【用户输入】
{user_input}

【Agent 回复】
{agent_response}

请以 JSON 格式返回分析结果：
{{
  "new_intents": [
    {{"description": "新意图描述", "context": "上下文"}}
  ],
  "updates": [
    {{"intent_id": "意图ID", "progress": 0.5, "status": "active/paused/completed", "sub_intent": "新子意图"}}
  ],
  "completed": ["已完成的意图ID"]
}}

分析规则：
1. 新意图：用户明确表达想要做的事情，或提到的长期目标
2. 意图更新：对话内容推进了某个现有意图的进度
3. 完成判断：用户确认"搞定了"、"完成了"、"不用了"等
4. 进度估算：0.0-1.0，根据对话内容判断完成程度
5. 如果没有变化，返回空数组"""

            response = model_adapter.chat([
                ChatMessage("system", "你是意图分析专家，只输出 JSON。"),
                ChatMessage("user", prompt),
            ])
            raw = response.content if hasattr(response, "content") else str(response)
            parsed = extract_json(raw)

            if not parsed:
                return []

            results = []

            for new_intent in parsed.get("new_intents", []):
                intent = self.add_intent(
                    root_intent=new_intent.get("description", ""),
                    session_id=session_id,
                    context=new_intent.get("context", ""),
                )
                results.append(intent)

            for update in parsed.get("updates", []):
                intent_id = update.get("intent_id")
                if intent_id:
                    updated = self.update_intent(
                        intent_id=intent_id,
                        status=update.get("status"),
                        progress=update.get("progress"),
                        sub_intent=update.get("sub_intent"),
                    )
                    if updated:
                        results.append(updated)

            for intent_id in parsed.get("completed", []):
                updated = self.update_intent(
                    intent_id=intent_id,
                    status="completed",
                    progress=1.0,
                )
                if updated:
                    results.append(updated)

            if results:
                logger.info(f"意图分析完成：新增{len([r for r in results if r.created_at == r.updated_at])}个，更新{len(results)}个")

            return results

        except Exception as e:
            logger.warning(f"意图分析失败: {e}")
            import traceback
            logger.debug(traceback.format_exc())
            return []

    def decompose_intent(
        self,
        intent_id: str,
        model_adapter: Any,
    ) -> Optional[IntentNode]:
        """
        使用LLM将复杂意图分解为可执行的子任务

        :param intent_id: 意图ID
        :param model_adapter: 模型适配器
        :return: 更新后的意图节点
        """
        from castorice.model_adapter import ChatMessage

        intent = self.get_intent_by_id(intent_id)
        if not intent:
            return None

        if intent.sub_tasks:
            return intent  # 已经有子任务，不再分解

        prompt = f"""请将以下复杂意图分解为3-5个可执行的子任务：

意图：{intent.root_intent}
上下文：{intent.context}

要求：
1. 每个子任务应该是具体的、可执行的
2. 子任务之间有合理的依赖关系
3. 按执行顺序排列

请用JSON格式返回：
{{
    "sub_tasks": [
        {{"description": "子任务1描述", "priority": 0.9}},
        {{"description": "子任务2描述", "priority": 0.7}}
    ]
}}
"""

        try:
            response = model_adapter.chat([
                ChatMessage("system", "你是任务分解专家，将复杂目标分解为可执行的子任务。"),
                ChatMessage("user", prompt),
            ])
            raw = response.content if hasattr(response, "content") else str(response)

            # 解析JSON
            import re
            json_match = re.search(r'\{.*\}', raw, re.DOTALL)
            if not json_match:
                return intent

            result = json.loads(json_match.group())
            tasks = result.get("sub_tasks", [])

            if not tasks:
                return intent

            for task in tasks:
                intent.add_sub_task(
                    task_description=task.get("description", ""),
                    priority=task.get("priority", 0.5),
                )

            # 更新数据库
            with self._lock:
                conn = self._get_conn()
                cursor = conn.cursor()
                cursor.execute("""
                    UPDATE intents SET sub_tasks = ?, updated_at = ?
                    WHERE intent_id = ?
                """, (
                    json.dumps(intent.sub_tasks),
                    datetime.now(timezone.utc).isoformat(),
                    intent.intent_id,
                ))
                conn.commit()
        
            logger.info(f"意图分解完成: {intent.intent_id} -> {len(tasks)}个子任务")
            return intent

        except Exception as e:
            logger.warning(f"意图分解失败: {e}")
            return intent