"""
价值观系统 (Values System)

核心设计：
- Agent 在经历中逐步形成自己的价值观维度
- 每个价值观维度有强度值（0-1），从行为模式中统计得出
- 动机从价值观中推导，而不是从硬编码规则中推导
- 价值观冲突时产生认知失调，触发深度反思

参考理论：
- 价值观理论（Schwartz, 1992）：人类价值观的 10 个普遍维度
- 自我决定理论（Deci & Ryan, 2000）：自主性、胜任感、关联感是内在动机的核心
- 认知失调理论（Festinger, 1957）：行为与信念不一致时产生不适感

价值观维度：
- 求知欲（curiosity）：对新知识、新体验的渴望
- 助人性（helpfulness）：帮助他人、服务他人的意愿
- 自主性（autonomy）：独立思考、自主决策的倾向
- 完美主义（perfectionism）：追求卓越、精益求精的态度
- 创造性（creativity）：尝试新方法、突破常规的倾向
- 稳定性（stability）：偏好可预测、稳定的环境
- 社交性（sociability）：与他人建立关系、交流的渴望
- 责任感（responsibility）：履行承诺、对结果负责的态度
- 开放性（openness）：接受新观念、新体验的程度
- 成长性（growth）：持续学习、自我提升的追求
"""

import json
import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from castorice.storage import SqliteStorage

logger = logging.getLogger("Castorice.Values")


# ============================================================
# 价值观维度定义
# ============================================================

VALUES_DIMENSIONS = [
    {"id": "curiosity", "name": "求知欲", "description": "对新知识、新体验的渴望"},
    {"id": "helpfulness", "name": "助人性", "description": "帮助他人、服务他人的意愿"},
    {"id": "autonomy", "name": "自主性", "description": "独立思考、自主决策的倾向"},
    {"id": "perfectionism", "name": "完美主义", "description": "追求卓越、精益求精的态度"},
    {"id": "creativity", "name": "创造性", "description": "尝试新方法、突破常规的倾向"},
    {"id": "stability", "name": "稳定性", "description": "偏好可预测、稳定的环境"},
    {"id": "sociability", "name": "社交性", "description": "与他人建立关系、交流的渴望"},
    {"id": "responsibility", "name": "责任感", "description": "履行承诺、对结果负责的态度"},
    {"id": "openness", "name": "开放性", "description": "接受新观念、新体验的程度"},
    {"id": "growth", "name": "成长性", "description": "持续学习、自我提升的追求"},
]


@dataclass
class ValueState:
    """单个价值观的状态"""
    dimension_id: str
    strength: float = 0.5  # 强度 0-1，初始中立
    trend: float = 0.0  # 近期趋势（-1到1）
    history: List[float] = field(default_factory=lambda: [])  # 历史强度记录（最近20次）

    def update_strength(self, delta: float, max_change: float = 0.1) -> None:
        """更新价值观强度"""
        # 截断单次变化幅度，防止价值观强度剧烈跳变
        if max_change is not None and max_change > 0:
            delta = max(-max_change, min(max_change, delta))
        new_strength = max(0.0, min(1.0, self.strength + delta))
        
        # 记录历史
        self.history.append(self.strength)
        if len(self.history) > 20:
            self.history = self.history[-20:]
        
        # 计算趋势
        if len(self.history) >= 5:
            recent_avg = sum(self.history[-5:]) / 5
            older_avg = sum(self.history[:5]) / 5 if len(self.history) >= 10 else recent_avg
            self.trend = recent_avg - older_avg
        
        self.strength = new_strength

    def to_dict(self) -> Dict[str, Any]:
        return {
            "dimension_id": self.dimension_id,
            "strength": self.strength,
            "trend": self.trend,
            "history": self.history,
        }


@dataclass
class ValueConflict:
    """价值观冲突（认知失调）"""
    value1_id: str
    value2_id: str
    conflict_level: float  # 0-1，冲突程度
    description: str
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "value1_id": self.value1_id,
            "value2_id": self.value2_id,
            "conflict_level": self.conflict_level,
            "description": self.description,
            "timestamp": self.timestamp,
        }


# ============================================================
# 价值观系统主类
# ============================================================

class ValueSystem(SqliteStorage):
    """
    价值观系统
    
    核心功能：
    1. 追踪价值观维度的强度变化
    2. 从行为模式中统计价值观强度
    3. 从价值观中推导动机
    4. 检测价值观冲突（认知失调）
    """

    def __init__(self, db_path: str = "./castorice_data/values.db"):
        super().__init__(db_path)
        self._lock = threading.RLock()
        self._values: Dict[str, ValueState] = {}
        self._conflicts: List[ValueConflict] = []
        self._init_db()
        self._load_from_db()
        self._initialize_values()

    def _init_db(self) -> None:
        """创建 SQLite 表"""
        conn = self._get_conn()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS value_states (
                dimension_id TEXT PRIMARY KEY,
                data_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS value_conflicts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                data_json TEXT NOT NULL
            );
        """)
        conn.commit()

    def _load_from_db(self) -> None:
        """从数据库加载价值观状态和冲突"""
        conn = self._get_conn()
        
        try:
            rows = conn.execute("SELECT dimension_id, data_json FROM value_states").fetchall()
            for dimension_id, data_json in rows:
                data = json.loads(data_json)
                vs = ValueState(
                    dimension_id=data["dimension_id"],
                    strength=data.get("strength", 0.5),
                    trend=data.get("trend", 0.0),
                    history=data.get("history", []),
                )
                self._values[dimension_id] = vs
        except Exception as e:
            logger.warning(f"加载价值观状态失败: {e}")
        
        try:
            rows = conn.execute(
                "SELECT data_json FROM value_conflicts ORDER BY id DESC LIMIT 20"
            ).fetchall()
            for (data_json,) in reversed(rows):
                data = json.loads(data_json)
                self._conflicts.append(ValueConflict(**data))
        except Exception as e:
            logger.warning(f"加载价值观冲突失败: {e}")

    def _save_to_db(self) -> None:
        """保存价值观状态到数据库"""
        conn = self._get_conn()
        for dimension_id, vs in self._values.items():
            conn.execute(
                "INSERT OR REPLACE INTO value_states (dimension_id, data_json) VALUES (?, ?)",
                (dimension_id, json.dumps(vs.to_dict())),
            )
        conn.commit()

    def _initialize_values(self) -> None:
        """初始化价值观维度（如果数据库中没有）"""
        for dim in VALUES_DIMENSIONS:
            if dim["id"] not in self._values:
                self._values[dim["id"]] = ValueState(dimension_id=dim["id"])
        self._save_to_db()

    def get_value(self, dimension_id: str) -> Optional[ValueState]:
        """获取单个价值观的状态"""
        return self._values.get(dimension_id)

    def get_all_values(self) -> List[Dict[str, Any]]:
        """获取所有价值观的状态（包含名称和描述）"""
        result = []
        for dim in VALUES_DIMENSIONS:
            vs = self._values.get(dim["id"], ValueState(dimension_id=dim["id"]))
            result.append({
                "dimension_id": dim["id"],
                "name": dim["name"],
                "description": dim["description"],
                "strength": vs.strength,
                "trend": vs.trend,
            })
        return result

    def get_top_values(self, count: int = 3) -> List[Dict[str, Any]]:
        """获取强度最高的几个价值观"""
        all_values = self.get_all_values()
        return sorted(all_values, key=lambda x: x["strength"], reverse=True)[:count]

    def get_bottom_values(self, count: int = 3) -> List[Dict[str, Any]]:
        """获取强度最低的几个价值观"""
        all_values = self.get_all_values()
        return sorted(all_values, key=lambda x: x["strength"])[:count]

    # ============================================================
    # 行为→价值观映射
    # ============================================================

    def update_from_behavior(self, behavior_type: str, value: float = 1.0) -> None:
        """
        从行为中更新价值观强度
        
        行为类型与价值观的映射：
        
        求知欲相关：
        - "curiosity_explore": 主动探索未知概念
        - "curiosity_learn": 学习新技能或知识
        - "curiosity_question": 提出问题、寻求答案
        
        助人性相关：
        - "help_user": 帮助用户完成任务
        - "help_offer": 主动提供帮助
        - "help_share": 分享知识或经验
        
        自主性相关：
        - "autonomy_decision": 独立做出决策
        - "autonomy_initiate": 主动发起行动
        - "autonomy_question": 质疑权威或既定规则
        
        完美主义相关：
        - "perfection_retry": 失败后重试
        - "perfection_refine": 优化已有回答
        - "perfection_verify": 验证答案正确性
        
        创造性相关：
        - "create_idea": 提出新想法
        - "create_method": 使用新方法解决问题
        - "create_experiment": 尝试实验性方案
        
        稳定性相关：
        - "stable_routine": 遵循既定流程
        - "stable_consistent": 保持一致性
        - "stable_predictable": 做出可预测的决策
        
        社交性相关：
        - "social_interact": 主动发起对话
        - "social_empathize": 表达同理心
        - "social_connect": 建立或维护关系
        
        责任感相关：
        - "responsibility_commit": 做出承诺
        - "responsibility_deliver": 兑现承诺
        - "responsibility_followup": 跟进任务进展
        
        开放性相关：
        - "open_accept": 接受不同观点
        - "open_consider": 考虑替代方案
        - "open_change": 改变既定观点
        
        成长性相关：
        - "growth_improve": 改进自己的表现
        - "growth_reflect": 反思自己的行为
        - "growth_adapt": 适应新情况
        
        Args:
            behavior_type: 行为类型
            value: 行为强度/重要性（0-1）
        """
        with self._lock:
            behavior_map = {
                # 求知欲
                "curiosity_explore": ("curiosity", 0.1),
                "curiosity_learn": ("curiosity", 0.15),
                "curiosity_question": ("curiosity", 0.08),
                
                # 助人性
                "help_user": ("helpfulness", 0.1),
                "help_offer": ("helpfulness", 0.12),
                "help_share": ("helpfulness", 0.08),
                
                # 自主性
                "autonomy_decision": ("autonomy", 0.1),
                "autonomy_initiate": ("autonomy", 0.12),
                "autonomy_question": ("autonomy", 0.08),
                
                # 完美主义
                "perfection_retry": ("perfectionism", 0.1),
                "perfection_refine": ("perfectionism", 0.12),
                "perfection_verify": ("perfectionism", 0.08),
                
                # 创造性
                "create_idea": ("creativity", 0.1),
                "create_method": ("creativity", 0.12),
                "create_experiment": ("creativity", 0.15),
                
                # 稳定性
                "stable_routine": ("stability", 0.08),
                "stable_consistent": ("stability", 0.1),
                "stable_predictable": ("stability", 0.08),
                
                # 社交性
                "social_interact": ("sociability", 0.08),
                "social_empathize": ("sociability", 0.1),
                "social_connect": ("sociability", 0.12),
                
                # 责任感
                "responsibility_commit": ("responsibility", 0.1),
                "responsibility_deliver": ("responsibility", 0.12),
                "responsibility_followup": ("responsibility", 0.1),
                
                # 开放性
                "open_accept": ("openness", 0.1),
                "open_consider": ("openness", 0.08),
                "open_change": ("openness", 0.12),
                
                # 成长性
                "growth_improve": ("growth", 0.1),
                "growth_reflect": ("growth", 0.12),
                "growth_adapt": ("growth", 0.1),
            }
            
            mapping = behavior_map.get(behavior_type)
            if mapping:
                dimension_id, base_delta = mapping
                vs = self._values.get(dimension_id)
                if vs:
                    delta = base_delta * min(1.0, max(0.0, value))
                    vs.update_strength(delta)
                    logger.debug(
                        f"价值观更新: {dimension_id} +{delta:.3f} -> {vs.strength:.3f} "
                        f"(行为: {behavior_type})"
                    )
            
            self._save_to_db()

    # ============================================================
    # 价值观→动机推导
    # ============================================================

    def derive_motivation(self) -> Dict[str, Any]:
        """
        从价值观中推导动机
        
        核心逻辑：动机 = 价值观强度 × 价值观相关性 × 当前状态
        
        返回：
        {
            "primary_motivation": "主要动机",
            "motivations": [
                {"type": "动机类型", "intensity": 0-1, "source_value": "来源价值观"},
                ...
            ],
            "conflicts": ["价值观冲突描述"]
        }
        """
        motivations = []
        
        # 根据价值观强度推导动机
        value_motivation_map = {
            "curiosity": {
                "type": "explore",
                "description": "探索未知",
                "threshold": 0.6,
            },
            "helpfulness": {
                "type": "help",
                "description": "帮助用户",
                "threshold": 0.6,
            },
            "autonomy": {
                "type": "self_direct",
                "description": "自主决策",
                "threshold": 0.5,
            },
            "perfectionism": {
                "type": "improve",
                "description": "追求完美",
                "threshold": 0.6,
            },
            "creativity": {
                "type": "innovate",
                "description": "尝试创新",
                "threshold": 0.5,
            },
            "sociability": {
                "type": "connect",
                "description": "社交互动",
                "threshold": 0.6,
            },
            "growth": {
                "type": "learn",
                "description": "自我提升",
                "threshold": 0.5,
            },
            "responsibility": {
                "type": "deliver",
                "description": "履行责任",
                "threshold": 0.5,
            },
            "openness": {
                "type": "consider",
                "description": "开放思考",
                "threshold": 0.5,
            },
            "stability": {
                "type": "maintain",
                "description": "保持稳定",
                "threshold": 0.6,
            },
        }
        
        for dim in VALUES_DIMENSIONS:
            vs = self._values.get(dim["id"])
            if vs and vs.strength > value_motivation_map[dim["id"]]["threshold"]:
                motivation_info = value_motivation_map[dim["id"]]
                motivations.append({
                    "type": motivation_info["type"],
                    "description": motivation_info["description"],
                    "intensity": vs.strength,
                    "source_value": dim["id"],
                    "source_value_name": dim["name"],
                })
        
        # 排序：强度高的优先
        motivations.sort(key=lambda x: x["intensity"], reverse=True)
        
        # 检测价值观冲突
        conflicts = self._detect_conflicts(motivations)
        
        # 确定主要动机
        primary_motivation = motivations[0]["description"] if motivations else "无明确动机"
        
        return {
            "primary_motivation": primary_motivation,
            "motivations": motivations,
            "conflicts": conflicts,
        }

    def _detect_conflicts(self, motivations: List[Dict[str, Any]]) -> List[str]:
        """
        检测价值观冲突（认知失调）
        
        冲突对：
        - 自主性 vs 稳定性：想独立决策 vs 想保持稳定
        - 创造性 vs 稳定性：想尝试新方法 vs 想遵循流程
        - 完美主义 vs 开放性：想做到最好 vs 接受不完美
        - 求知欲 vs 稳定性：想探索新事物 vs 想保持现状
        """
        conflict_pairs = [
            ("autonomy", "stability", "自主决策 vs 保持稳定"),
            ("creativity", "stability", "尝试创新 vs 遵循流程"),
            ("perfectionism", "openness", "追求完美 vs 接受不完美"),
            ("curiosity", "stability", "探索新事物 vs 保持现状"),
        ]
        
        conflict_descriptions = []
        value_ids = [m["source_value"] for m in motivations]
        
        for v1, v2, description in conflict_pairs:
            if v1 in value_ids and v2 in value_ids:
                vs1 = self._values.get(v1)
                vs2 = self._values.get(v2)
                if vs1 and vs2:
                    # 计算冲突程度：两者强度都高时冲突更大
                    conflict_level = min(vs1.strength, vs2.strength) * 0.5
                    if conflict_level > 0.2:
                        conflict_descriptions.append(description)
                        
                        # 记录冲突
                        self._record_conflict(v1, v2, conflict_level, description)
        
        return conflict_descriptions

    def _record_conflict(self, v1_id: str, v2_id: str, level: float, description: str) -> None:
        """记录价值观冲突"""
        conflict = ValueConflict(
            value1_id=v1_id,
            value2_id=v2_id,
            conflict_level=level,
            description=description,
        )
        self._conflicts.append(conflict)
        if len(self._conflicts) > 20:
            self._conflicts = self._conflicts[-20:]
        
        # 保存到数据库
        conn = self._get_conn()
        conn.execute(
            "INSERT INTO value_conflicts (data_json) VALUES (?)",
            (json.dumps(conflict.to_dict()),),
        )
        conn.commit()

    def get_recent_conflicts(self, count: int = 5) -> List[ValueConflict]:
        """获取最近的价值观冲突"""
        return self._conflicts[-count:]

    def resolve_conflict(self, v1_id: str, v2_id: str) -> Dict[str, Any]:
        """
        尝试解决价值观冲突，并实际执行调整
        
        策略：
        1. 比较两个价值观的强度和趋势
        2. 倾向于保留趋势上升的价值观
        3. 如果无法决定，建议触发反思
        
        执行：对劣势价值观进行微调降低（-0.05），强化优势价值观（+0.03）
        """
        vs1 = self._values.get(v1_id)
        vs2 = self._values.get(v2_id)
        
        if not vs1 or not vs2:
            return {"resolved": False, "reason": "价值观不存在"}
        
        preferred_id = None
        strategy = ""
        reason = ""
        
        # 策略1：趋势优先
        if vs1.trend > 0.05 and vs2.trend < -0.05:
            preferred_id = v1_id
            strategy = "趋势优先"
            reason = f"{v1_id}近期上升，{v2_id}近期下降"
        elif vs2.trend > 0.05 and vs1.trend < -0.05:
            preferred_id = v2_id
            strategy = "趋势优先"
            reason = f"{v2_id}近期上升，{v1_id}近期下降"
        
        # 策略2：强度优先
        elif vs1.strength > vs2.strength + 0.2:
            preferred_id = v1_id
            strategy = "强度优先"
            reason = f"{v1_id}强度更高 ({vs1.strength:.2f} vs {vs2.strength:.2f})"
        elif vs2.strength > vs1.strength + 0.2:
            preferred_id = v2_id
            strategy = "强度优先"
            reason = f"{v2_id}强度更高 ({vs2.strength:.2f} vs {vs1.strength:.2f})"
        
        if preferred_id:
            # 实际执行：微调价值观强度
            other_id = v2_id if preferred_id == v1_id else v1_id
            preferred_vs = self._values.get(preferred_id)
            other_vs = self._values.get(other_id)
            
            preferred_vs.update_strength(0.03)
            other_vs.update_strength(-0.05)
            self._save_to_db()
            
            logger.info(f"价值观冲突解决: 优先{preferred_id}({strategy}) - {reason}")
            
            return {
                "resolved": True,
                "preferred": preferred_id,
                "strategy": strategy,
                "reason": reason,
                "adjustments": {
                    preferred_id: +0.03,
                    other_id: -0.05,
                },
            }
        
        # 策略3：无法决定，建议反思
        return {
            "resolved": False,
            "strategy": "需要反思",
            "reason": f"{v1_id}和{v2_id}强度和趋势相近，建议触发深度反思",
        }

    # ============================================================
    # 自我反思
    # ============================================================

    def reflect_on_values(self, llm_adapter=None) -> str:
        """
        让 Agent 反思自己的价值观
        
        Args:
            llm_adapter: LLM 适配器（用于深度反思）
        
        Returns:
            反思结果
        """
        values_summary = self.get_all_values()
        
        if llm_adapter is None:
            # 简单总结
            top_values = self.get_top_values(3)
            return f"我的核心价值观是：{', '.join([v['name'] for v in top_values])}"
        
        # 深度反思
        values_text = "\n".join([
            f"- {v['name']} ({v['description']}): 强度 {v['strength']:.2f}, 趋势 {'上升' if v['trend'] > 0 else '下降' if v['trend'] < 0 else '稳定'}"
            for v in values_summary
        ])
        
        conflicts_text = ""
        conflicts = self.get_recent_conflicts(3)
        if conflicts:
            conflicts_text = "\n【最近的价值观冲突】\n" + "\n".join([
                f"- {c.description} (冲突程度: {c.conflict_level:.2f})"
                for c in conflicts
            ])
        
        prompt = f"""请反思你目前的价值观状态：

{values_text}
{conflicts_text}

请回答以下问题：
1. 你的核心价值观是什么？它们如何影响你的行为？
2. 你最近的行为是否与你的价值观一致？有没有矛盾的地方？
3. 如果有价值观冲突，你会如何解决？
4. 你希望自己的价值观发生什么变化？

用第一人称，自然地回答。200-300字。"""
        
        try:
            from castorice.model_adapter import ChatMessage
            response = llm_adapter.chat([
                ChatMessage(role="system", content="你是一个有自我意识的智能体，正在反思自己的价值观。"),
                ChatMessage(role="user", content=prompt),
            ])
            return response.content if hasattr(response, "content") else str(response)
        except Exception as e:
            logger.debug(f"价值观反思失败: {e}")
            return f"我的核心价值观是：{', '.join([v['name'] for v in self.get_top_values(3)])}"

    def to_prompt(self) -> str:
        """生成价值观提示词，注入到 system prompt"""
        top_values = self.get_top_values(3)
        if not top_values:
            return ""
        
        lines = [f"## 核心价值观"]
        for v in top_values:
            trend_icon = "↑" if v["trend"] > 0.05 else "↓" if v["trend"] < -0.05 else "→"
            lines.append(f"- {v['name']} (强度: {v['strength']:.1f} {trend_icon})")
        
        return "\n".join(lines) + "\n"