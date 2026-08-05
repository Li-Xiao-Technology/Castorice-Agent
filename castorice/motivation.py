"""
P2.3: 内在动机系统
==================

让 Agent 不只响应用户输入，还有自己的"内在驱动"：
- 好奇心：遇到未知概念时想了解
- 成就感：任务成功后想做更多类似任务
- 关系感：与用户的关系影响行为
- 自主目标：Agent 可以自己设定目标
- 价值观：从行为中内化的核心价值观（新增，第二阶段）

设计原则：
- 不强加"必须做什么"，只提供"我想做什么"作为参考
- 动机由价值观推导 + LLM 综合判断（不再是纯规则）
- 当用户输入与动机匹配时，相关行为更可能被采用
- 价值观从行为中统计得出，不是预设的
"""
import json
import logging
import threading
import time
from collections import deque
from typing import Any, Dict, List, Optional

from castorice.storage import SqliteStorage

logger = logging.getLogger("Castorice.Motivation")


class IntrinsicMotivation(SqliteStorage):
    """
    内在动机系统

    维护 Agent 的好奇心、成就感和关系感，
    推导当前"想做"的列表。
    
    第二阶段增强：集成价值观系统，动机从价值观中内生。
    """

    def __init__(self, max_history: int = 100,
                 db_path: str = "./castorice_data/motivation.db",
                 value_system: Optional[Any] = None):
        super().__init__(db_path)
        self._lock = threading.RLock()
        self._max_history = max_history
        self._task_history: deque = deque(maxlen=max_history)  # 任务结果历史
        self._user_interaction_count: int = 0
        self._last_user_feedback: Optional[str] = None
        self._curiosity_queue: List[str] = []  # 好奇的概念队列
        self._self_goals: List[Dict[str, Any]] = []  # 自己设定的目标
        self._init_db()
        self._load_from_db()
        
        # 价值观系统：优先使用外部注入（便于测试/自定义），否则默认懒加载
        if value_system is not None:
            self._value_system = value_system
            logger.info("[动机系统] 价值观系统已由外部注入")
        else:
            try:
                from castorice.values import ValueSystem
                self._value_system = ValueSystem()
                logger.info("[动机系统] 价值观系统已集成")
            except Exception as e:
                logger.warning(f"价值观系统初始化失败: {e}")
                self._value_system = None

        # 主动行为反馈闭环参数（实例属性，避免多实例共享）
        self._proactive_adjustment: float = 1.0
        self._last_proactive_time: float = 0.0
        self._last_proactive_type: str = ""
        self._awaiting_proactive_feedback: bool = False

    # ---- SQLite 持久化 ----

    def _init_db(self) -> None:
        """创建持久化表"""
        conn = self._get_conn()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS task_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                success INTEGER NOT NULL,
                type TEXT NOT NULL,
                ts REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS curiosity_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                concept TEXT NOT NULL,
                sort_order INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS self_goals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                data TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS metadata (
                key TEXT PRIMARY KEY,
                value TEXT
            );
        """)

    def _load_from_db(self) -> None:
        """从 SQLite 加载已有数据到内存"""
        conn = self._get_conn()
        try:
            # task_history
            rows = conn.execute(
                "SELECT success, type, ts FROM task_history ORDER BY id"
            ).fetchall()
            for row in rows:
                self._task_history.append({
                    "success": bool(row[0]),
                    "type": row[1],
                    "ts": row[2],
                })

            # curiosity_queue
            rows = conn.execute(
                "SELECT concept FROM curiosity_queue ORDER BY sort_order"
            ).fetchall()
            self._curiosity_queue = [r[0] for r in rows]

            # self_goals
            rows = conn.execute(
                "SELECT data FROM self_goals ORDER BY id"
            ).fetchall()
            self._self_goals = [json.loads(r[0]) for r in rows]

            # metadata
            row = conn.execute(
                "SELECT value FROM metadata WHERE key='interaction_count'"
            ).fetchone()
            if row:
                self._user_interaction_count = int(row[0])
            row = conn.execute(
                "SELECT value FROM metadata WHERE key='last_user_feedback'"
            ).fetchone()
            if row:
                self._last_user_feedback = row[0]

            logger.debug(
                f"从 SQLite 加载动机数据: history={len(self._task_history)}, "
                f"curiosity={len(self._curiosity_queue)}, goals={len(self._self_goals)}"
            )
        except Exception as e:
            logger.warning(f"从 SQLite 加载动机数据失败: {e}")

    def _save_task_history_incremental(self) -> None:
        """增量保存最新一条 task_history，并裁剪超限旧记录"""
        conn = self._get_conn()
        try:
            if self._task_history:
                last = self._task_history[-1]
                conn.execute(
                    "INSERT INTO task_history (success, type, ts) VALUES (?, ?, ?)",
                    (int(last["success"]), last["type"], last["ts"]),
                )
            count = conn.execute("SELECT COUNT(*) FROM task_history").fetchone()[0]
            if count > self._max_history:
                excess = count - self._max_history
                conn.execute(
                    "DELETE FROM task_history WHERE id IN "
                    "(SELECT id FROM task_history ORDER BY id LIMIT ?)",
                    (excess,),
                )
            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.warning(f"保存任务历史失败: {e}")

    def _save_curiosity_queue(self) -> None:
        """全量保存好奇心队列（数据量小，直接替换）"""
        conn = self._get_conn()
        try:
            conn.execute("DELETE FROM curiosity_queue")
            conn.executemany(
                "INSERT INTO curiosity_queue (concept, sort_order) VALUES (?, ?)",
                [(c, i) for i, c in enumerate(self._curiosity_queue)],
            )
            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.warning(f"保存好奇心队列失败: {e}")

    def _save_self_goals(self) -> None:
        """全量保存自主目标（数据量小，直接替换）"""
        conn = self._get_conn()
        try:
            conn.execute("DELETE FROM self_goals")
            conn.executemany(
                "INSERT INTO self_goals (data) VALUES (?)",
                [(json.dumps(g, ensure_ascii=False),) for g in self._self_goals],
            )
            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.warning(f"保存自主目标失败: {e}")

    def _save_metadata(self) -> None:
        """保存元数据（交互计数、用户反馈）"""
        conn = self._get_conn()
        try:
            conn.execute(
                "INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)",
                ("interaction_count", str(self._user_interaction_count)),
            )
            conn.execute(
                "INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)",
                ("last_user_feedback", self._last_user_feedback),
            )
            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.warning(f"保存元数据失败: {e}")

    def record_task_result(self, success: bool, task_type: str = "general") -> None:
        """记录一次任务结果（用于成就感计算）"""
        with self._lock:
            self._task_history.append({
                "success": success,
                "type": task_type,
                "ts": time.time(),
            })
            self._save_task_history_incremental()

    def record_user_interaction(self, user_input: str) -> None:
        """记录用户交互（用于关系感计算）"""
        with self._lock:
            self._user_interaction_count += 1
            # 检测用户反馈
            positive = any(kw in user_input for kw in ["谢谢", "好的", "不错", "很棒", "厉害"])
            negative = any(kw in user_input for kw in ["差", "没用", "错了", "不好", "失望"])
            if positive:
                self._last_user_feedback = "positive"
            elif negative:
                self._last_user_feedback = "negative"
            self._save_metadata()

    def add_curiosity(self, concept: str) -> None:
        """记录对某个概念的好奇（Agent 在对话中遇到未知事物时）"""
        with self._lock:
            if concept and concept not in self._curiosity_queue:
                self._curiosity_queue.append(concept)
                if len(self._curiosity_queue) > 20:
                    self._curiosity_queue = self._curiosity_queue[-20:]
                self._save_curiosity_queue()

    def satisfy_curiosity(self, concept: str, finding: str = "") -> bool:
        """
        满足好奇心——从队列中移除已探索的概念，记录探索发现
        
        好奇心生命周期：发现未知 → 产生好奇 → 探索 → 获得知识 → 好奇心满足 → 产生成就感
        
        Args:
            concept: 已探索的概念
            finding: 探索发现的内容摘要
        
        Returns:
            是否成功移除
        """
        with self._lock:
            if concept in self._curiosity_queue:
                self._curiosity_queue.remove(concept)
                self._save_curiosity_queue()
                logger.info(f"好奇心已满足: {concept} | 发现: {finding[:80]}")
                # 好奇心满足后产生轻微的成就感（正反馈循环）
                self._task_history.append({
                    "success": True,
                    "type": "curiosity_satisfied",
                    "ts": time.time(),
                })
                self._save_task_history_incremental()
                return True
            return False

    def get_curiosity_queue(self) -> List[str]:
        """获取当前好奇心队列"""
        with self._lock:
            return list(self._curiosity_queue)

    def update_goal_progress(self, goal: str, progress_delta: float) -> bool:
        """
        更新自主目标的进度
        
        Args:
            goal: 目标描述
            progress_delta: 进度增量（正数表示进展）
        
        Returns:
            是否更新成功
        """
        with self._lock:
            for g in self._self_goals:
                if g["goal"] == goal:
                    g["progress"] = max(0.0, min(1.0, g["progress"] + progress_delta))
                    self._save_self_goals()
                    logger.info(f"目标进度更新: {goal} → {g['progress']:.0%}")
                    # 目标完成时记录成就感
                    if g["progress"] >= 1.0:
                        self._task_history.append({
                            "success": True,
                            "type": "goal_completed",
                            "ts": time.time(),
                        })
                        self._save_task_history_incremental()
                        logger.info(f"目标完成: {goal}")
                    return True
            return False

    def set_self_goal(self, goal: str, priority: float = 0.5) -> None:
        """设定一个自主目标"""
        with self._lock:
            self._self_goals.append({
                "goal": goal,
                "priority": priority,
                "created_at": time.time(),
                "progress": 0.0,
            })
            if len(self._self_goals) > 10:
                self._self_goals = sorted(
                    self._self_goals, key=lambda g: g["priority"], reverse=True
                )[:10]
            self._save_self_goals()

    def get_current_motivations(self) -> List[str]:
        """
        推导当前动机列表

        基于：
        - 价值观系统（新增，第二阶段核心）
        - 近期任务成功率（成就感）
        - 用户反馈（关系感）
        - 好奇心队列
        - 自主目标
        """
        motivations = []
        with self._lock:
            # 0. 价值观推导的动机（第二阶段新增，优先级最高）
            # 动机从价值观中内生，而不是从硬编码规则中推导
            if self._value_system:
                value_motivation = self._value_system.derive_motivation()
                # 添加价值观冲突提示
                for conflict in value_motivation.get("conflicts", []):
                    motivations.append(f"价值观冲突: {conflict}")
                # 添加价值观驱动的动机
                for m in value_motivation.get("motivations", []):
                    if m["intensity"] > 0.6:
                        motivations.append(f"{m['description']}（来自{m['source_value_name']}价值观）")
            
            # 1. 成就感：近期成功率高 → 想做更多
            if len(self._task_history) >= 3:
                recent = list(self._task_history)[-10:]
                success_rate = sum(1 for t in recent if t["success"]) / len(recent)
                if success_rate > 0.7:
                    motivations.append("我最近表现不错，想要挑战更有难度的任务")
                elif success_rate < 0.4:
                    motivations.append("我最近表现欠佳，希望用简单任务恢复信心")

            # 2. 关系感：用户反馈
            if self._user_interaction_count > 5 and self._last_user_feedback == "positive":
                motivations.append("我与用户建立了良好的关系，希望继续保持有温度的交流")
            elif self._last_user_feedback == "negative":
                motivations.append("用户最近有些不满，我想更谨慎、细致地回应")

            # 3. 好奇心
            if self._curiosity_queue:
                top = self._curiosity_queue[0]
                motivations.append(f"我对「{top}」这个概念感到好奇，想要了解更多")

            # 4. 自主目标
            if self._self_goals:
                top_goal = max(self._self_goals, key=lambda g: g["priority"])
                motivations.append(f"我的目标: {top_goal['goal']}")

            # 5. 基础动机：自我表达
            motivations.append("我想用自己真实的想法和感受来回应用户")

        return motivations

    def get_value_system(self):
        """获取价值观系统（供外部访问）"""
        return self._value_system

    def get_state_snapshot(self) -> Dict[str, Any]:
        """获取动机系统状态快照"""
        with self._lock:
            return {
                "interaction_count": self._user_interaction_count,
                "last_user_feedback": self._last_user_feedback,
                "curiosity_queue": list(self._curiosity_queue),
                "self_goals": list(self._self_goals),
                "recent_task_count": len(self._task_history),
                "proactive_adjustment": self._proactive_adjustment,
            }

    # ============================================================
    # 主动行为反馈闭环
    # ============================================================

    def record_proactive_action(self, action_type: str) -> None:
        """
        记录一次主动行为的发起
        
        Args:
            action_type: 主动行为类型
        """
        with self._lock:
            self._last_proactive_time = time.time()
            self._last_proactive_type = action_type
            self._awaiting_proactive_feedback = True
            logger.info(f"主动行为已发起: type={action_type}, adjustment={self._proactive_adjustment:.2f}")

    def record_proactive_feedback(self, user_response: str) -> None:
        """
        记录用户对主动行为的反馈，并调整主动行为频率
        
        用户积极回应 → 更主动
        用户冷淡/忽略 → 更被动
        
        Args:
            user_response: 用户的回复内容
        """
        with self._lock:
            if not self._awaiting_proactive_feedback:
                return
            
            self._awaiting_proactive_feedback = False
            
            # 分析用户反馈极性
            positive_signals = ["谢谢", "好的", "嗯", "哈哈", "是啊", "对", "不错", "可以", "好"]
            negative_signals = ["不用", "算了", "别", "烦", "闭嘴", "不要", "不需要", "无聊"]
            ignore_signals = ["?", "？", "啥", "什么", "嗯？"]
            
            response_lower = user_response.lower().strip()
            
            is_positive = any(s in response_lower for s in positive_signals)
            is_negative = any(s in response_lower for s in negative_signals)
            is_ignored = len(response_lower) < 3 or any(s in response_lower for s in ignore_signals)
            
            old_adjustment = self._proactive_adjustment
            
            if is_positive:
                # 积极回应：增加主动频率（上限 1.5）
                self._proactive_adjustment = min(1.5, self._proactive_adjustment + 0.1)
                logger.info(f"主动行为反馈: 积极 → adjustment {old_adjustment:.2f} → {self._proactive_adjustment:.2f}")
            elif is_negative:
                # 消极回应：降低主动频率（下限 0.3）
                self._proactive_adjustment = max(0.3, self._proactive_adjustment - 0.15)
                logger.info(f"主动行为反馈: 消极 → adjustment {old_adjustment:.2f} → {self._proactive_adjustment:.2f}")
            elif is_ignored:
                # 被忽略：轻微降低
                self._proactive_adjustment = max(0.3, self._proactive_adjustment - 0.05)
                logger.info(f"主动行为反馈: 被忽略 → adjustment {old_adjustment:.2f} → {self._proactive_adjustment:.2f}")
            # else: 中性回应，不调整

    def get_proactive_adjustment(self) -> float:
        """获取主动行为频率调整因子"""
        with self._lock:
            return self._proactive_adjustment

    def is_awaiting_proactive_feedback(self) -> bool:
        """是否在等待用户对主动行为的反馈"""
        with self._lock:
            return self._awaiting_proactive_feedback

    def should_initiate_action(
        self,
        seconds_since_last_input: float,
        emotion_state: Optional[Dict[str, float]] = None,
        intent_tracker: Any = None,
        social_relation: Any = None,
        user_id: str = "",
    ) -> Dict[str, Any]:
        """
        判断是否应该主动发起行为（静默轮）

        :param seconds_since_last_input: 距离上次用户输入的秒数
        :param emotion_state: 当前情感状态（可选）
        :param intent_tracker: 意图追踪器（可选，用于检查未完成意图）
        :return: dict {
            "should_initiate": bool,
            "action_type": str,  # "curiosity" | "concern" | "goal_tracking" | "check_in" | "intent_followup"
            "reason": str,
            "target": str,  # 主动行为的目标（如好奇的概念、关心的用户状态等）
        }
        """
        with self._lock:
            # 根据主动行为调整因子缩放时间阈值
            # adjustment > 1.0 → 阈值变小（更主动）
            # adjustment < 1.0 → 阈值变大（更被动）
            adj = self._proactive_adjustment
            curiosity_threshold = 120 / adj
            concern_threshold = 300 / adj
            goal_threshold = 600 / adj
            check_in_threshold = 600 / adj

            # 0. 意图追踪：有未完成的用户意图，主动跟进
            if intent_tracker and seconds_since_last_input > concern_threshold:
                try:
                    active_intents = intent_tracker.get_active_intents(limit=5)
                    if active_intents:
                        # 优先选择进度较低的意图（还没开始）或中等进度的意图（卡住了）
                        target_intent = active_intents[0]
                        if target_intent.progress < 0.3:
                            reason = "用户有未开始的意图，想主动询问是否需要帮助"
                        elif 0.3 <= target_intent.progress < 0.7:
                            reason = "用户的意图进展缓慢，想主动跟进进度"
                        else:
                            reason = "用户的意图接近完成，想主动确认是否需要收尾"
                        return {
                            "should_initiate": True,
                            "action_type": "intent_followup",
                            "reason": reason,
                            "target": target_intent.root_intent,
                        }
                except Exception as e:
                    logger.debug(f"意图追踪检查失败: {e}")

            # 1. 好奇心驱动：有未解决的好奇概念且用户长时间没说话
            if self._curiosity_queue and seconds_since_last_input > curiosity_threshold:
                return {
                    "should_initiate": True,
                    "action_type": "curiosity",
                    "reason": "有未解决的好奇概念，想主动了解",
                    "target": self._curiosity_queue[0],
                }

            # 2. 关系维护：用户最近不满且长时间没说话，主动关心
            if (
                self._last_user_feedback == "negative"
                and seconds_since_last_input > concern_threshold
                and self._user_interaction_count > 3
            ):
                return {
                    "should_initiate": True,
                    "action_type": "concern",
                    "reason": "用户之前有些不满，想主动关心",
                    "target": "用户情绪状态",
                }

            # 3. 目标追踪：有进行中的目标且长时间没进展
            if self._self_goals and seconds_since_last_input > goal_threshold:
                active_goals = [g for g in self._self_goals if g["progress"] < 1.0]
                if active_goals:
                    top_goal = max(active_goals, key=lambda g: g["priority"])
                    return {
                        "should_initiate": True,
                        "action_type": "goal_tracking",
                        "reason": "有进行中的目标，想更新进展",
                        "target": top_goal["goal"],
                    }

            # 4. 日常问候：长时间没说话（超过阈值），主动打招呼
            if seconds_since_last_input > check_in_threshold and self._user_interaction_count > 10:
                return {
                    "should_initiate": True,
                    "action_type": "check_in",
                    "reason": "长时间没交流，想主动打招呼",
                    "target": "日常问候",
                }

            # S1: 关系驱动的主动行为（关系越深，越倾向主动关心）
            if social_relation and user_id and seconds_since_last_input > concern_threshold:
                try:
                    relation = social_relation.get_relation(user_id)
                    if relation:
                        # 亲密度越高，主动关心的阈值越低
                        intimacy = relation.intimacy
                        if intimacy > 0.6 and seconds_since_last_input > 180 / adj:
                            return {
                                "should_initiate": True,
                                "action_type": "relation_care",
                                "reason": f"与用户关系较好（亲密度{intimacy:.0%}），想主动关心近况",
                                "target": "关心用户近况",
                            }
                        if intimacy > 0.4 and relation.interaction_streak >= 3:
                            return {
                                "should_initiate": True,
                                "action_type": "relation_streak",
                                "reason": f"连续互动{relation.interaction_streak}天，保持联系节奏",
                                "target": "延续互动节奏",
                            }
                except Exception as e:
                    logger.debug(f"S1 关系驱动检查失败: {e}")

            # 5. 情感驱动：情绪低落时寻求互动
            if (
                emotion_state
                and emotion_state.get("pleasure", 0) < -0.3
                and seconds_since_last_input > 180 / adj
            ):
                return {
                    "should_initiate": True,
                    "action_type": "emotion_seeking",
                    "reason": "心情不太好，想与人交流",
                    "target": "情感交流",
                }

            return {
                "should_initiate": False,
                "action_type": "",
                "reason": "",
                "target": "",
            }
