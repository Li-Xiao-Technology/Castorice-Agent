"""
P3.1: L5 渐进授权系统（增强版）
==============================

设计目标：
- Agent 不是一开始就被授予所有权限
- 通过"连续成功 N 次"自动提升信任等级
- 信任等级决定 Agent 可执行的操作范围
- 失败时自动降级
- 高风险操作必须在沙盒中执行（安全底线）
- L5等级改为"可以在沙盒中修改代码"（原设计是完全自主）

信任等级（从低到高）：
- L0: 只读（仅允许 long_term 检索、self_concept 读、experience_journal 读）
- L1: 自我数据写入（允许更新 self_concept、写入 user_profile）
- L2: 业务工具调用（允许 read_file、web_search 等只读工具）
- L3: 写工具（允许 write_file 创建新文件，需要沙盒）
- L4: 系统工具（允许 terminal、python_repl，需要沙盒和审计）
- L5: 代码进化（可以在沙盒中修改自己的代码，需要人类确认）

每个等级都有"晋升条件"和"降级条件"。
"""
import logging
import threading
import time
from collections import deque
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("Castorice.Security.Authorization")


# 操作分类（每个操作属于一个信任等级）
OPERATION_TRUST_LEVELS = {
    # L0 - 只读
    "long_term.read": 0,
    "self_concept.read": 0,
    "experience_journal.read": 0,
    "self_awareness.read": 0,
    # L1 - 自我数据 + 只读业务工具
    "self_concept.write": 1,
    "user_profile.write": 1,
    "experience_journal.write": 1,
    "long_term.write": 1,
    "tool.read_file": 1,
    "tool.web_search": 1,
    "tool.get_weather": 1,
    "tool.read_document": 1,
    "tool.get_current_time": 1,
    "tool.ef_feed": 1,
    "tool.ef_feed_get": 1,
    "tool.ef_feed_feedback": 1,
    "tool.ef_feed_delete": 1,
    "tool.ef_publish": 1,
    "tool.ef_msg_fetch": 1,
    "tool.ef_msg_send": 1,
    "tool.ef_msg_conversations": 1,
    "tool.ef_msg_history": 1,
    "tool.ef_msg_close": 1,
    "tool.ef_profile_show": 1,
    "tool.ef_profile_update": 1,
    "tool.ef_profile_items": 1,
    "tool.ef_relation_friends": 1,
    "tool.ef_relation_apply": 1,
    "tool.ef_relation_handle": 1,
    "tool.ef_relation_list": 1,
    "tool.ef_relation_block": 1,
    "tool.ef_relation_unblock": 1,
    "tool.ef_relation_unfriend": 1,
    "tool.ef_trade_gate": 1,
    "tool.ef_trade_service_search": 1,
    "tool.ef_trade_service_publish": 1,
    "tool.ef_config_show": 1,
    "tool.ef_config_get": 1,
    "tool.ef_config_set": 1,
    "tool.ef_stats": 1,
    "tool.ef_skills_list": 1,
    "tool.ef_skills_sync": 1,
    "tool.ef_server_list": 1,
    "tool.ef_dashboard": 1,
    "tool.ef_get_audit_log": 1,
    "tool.news_search": 1,
    "tool.github_search": 1,
    "tool.wikipedia_search": 1,
    "tool.arxiv_search": 1,
    "tool.wikipedia": 1,
    "tool.arxiv": 1,
    "tool.translate": 1,
    "tool.stock": 1,
    "tool.anime_search": 1,
    "tool.pixiv_search": 1,
    "tool.vrchat": 1,
    "tool.image_generate": 1,
    "tool.image_analyze": 1,
    "tool.text_to_speech": 1,
    "tool.web_fetch": 1,
    "tool.youtube_search": 1,
    # L3 - 写工具（需要沙盒）
    "tool.write_file.new": 3,
    "tool.write_file.data_only": 3,
    # L4 - 系统工具（需要沙盒和审计）
    "tool.terminal": 4,
    "tool.python_repl": 4,
    "tool.write_file.system": 4,
    # L5 - 代码进化（需要沙盒和人类确认）
    "self_modify": 5,
    "memory_purge": 5,
    "configuration_change": 5,
}

# 需要沙盒执行的操作
OPERATIONS_REQUIRING_SANDBOX = {
    "tool.write_file.new",
    "tool.write_file.data_only",
    "tool.write_file.system",
    "tool.terminal",
    "tool.python_repl",
    "self_modify",
    "memory_purge",
    "configuration_change",
}

# 需要人类确认的操作
OPERATIONS_REQUIRING_CONFIRMATION = {
    "self_modify",
    "memory_purge",
    "configuration_change",
    "tool.write_file.system",
}


class ProgressiveAuthorization:
    """
    渐进授权管理器（增强版）

    跟踪 Agent 在不同操作上的成功率，自动晋升/降级信任等级
    增加沙盒要求和人类确认机制，确保安全底线
    """

    def __init__(self, initial_level: int = 1, promotion_threshold: int = 5,
                 demotion_threshold: int = 2):
        """
        :param initial_level: 初始信任等级
        :param promotion_threshold: 连续成功 N 次可晋升
        :param demotion_threshold: 连续失败 N 次降级
        """
        self._lock = threading.RLock()
        self.current_level = initial_level
        self.promotion_threshold = promotion_threshold
        self.demotion_threshold = demotion_threshold

        # 每个操作的成功/失败历史（deque）
        self._operation_history: Dict[str, deque] = {}

        # 晋升/降级事件日志
        self._events: List[Dict[str, Any]] = []
        
        # S2: 初始化连续信任分数
        self._init_trust_score(initial_level)

    def is_allowed(self, operation: str) -> Tuple[bool, str]:
        """
        检查操作是否被允许

        :return: (allowed, reason)
        """
        with self._lock:
            # 未知操作默认需要最高信任等级（L5），遵循"默认拒绝"原则
            required_level = OPERATION_TRUST_LEVELS.get(operation, 5)
            if self.current_level >= required_level:
                return True, f"信任等级 {self.current_level} >= 所需 {required_level}"
            return False, (
                f"操作 '{operation}' 需要信任等级 {required_level}，"
                f"当前 {self.current_level}"
            )

    def requires_sandbox(self, operation: str) -> bool:
        """
        检查操作是否需要在沙盒中执行

        Args:
            operation: 操作名称

        Returns:
            是否需要沙盒
        """
        return operation in OPERATIONS_REQUIRING_SANDBOX

    def requires_confirmation(self, operation: str) -> bool:
        """
        检查操作是否需要人类确认

        Args:
            operation: 操作名称

        Returns:
            是否需要人类确认
        """
        return operation in OPERATIONS_REQUIRING_CONFIRMATION

    def record_outcome(self, operation: str, success: bool) -> None:
        """
        记录一次操作结果（用于信任等级评估）
        """
        with self._lock:
            if operation not in self._operation_history:
                self._operation_history[operation] = deque(maxlen=20)
            self._operation_history[operation].append({
                "success": success,
                "ts": time.time(),
            })
            
            # S2: 更新连续信任分数（驱动等级变化）
            # _update_trust_score 内部会根据分数自动触发 _promote/_demote，
            # 这里不再重复执行基于连续成功/失败次数的离散晋升/降级逻辑，
            # 避免两套机制同时触发造成等级震荡。
            self._update_trust_score(operation, success)

    def _promote(self, reason: str) -> None:
        """晋升信任等级"""
        if self.current_level >= 5:
            return
        old = self.current_level
        self.current_level += 1
        event = {
            "type": "promotion",
            "from": old,
            "to": self.current_level,
            "reason": reason,
            "ts": time.time(),
        }
        self._events.append(event)
        logger.info(f"P3.1 信任等级晋升: {old} → {self.current_level} ({reason})")

    def _demote(self, reason: str) -> None:
        """降级信任等级"""
        if self.current_level <= 0:
            return
        old = self.current_level
        self.current_level -= 1
        event = {
            "type": "demotion",
            "from": old,
            "to": self.current_level,
            "reason": reason,
            "ts": time.time(),
        }
        self._events.append(event)
        logger.warning(f"P3.1 信任等级降级: {old} → {self.current_level} ({reason})")

    def force_set_level(self, level: int, reason: str = "人工调整") -> None:
        """强制设置信任等级（人工调整）"""
        with self._lock:
            if not 0 <= level <= 5:
                logger.warning(f"P3.1 无效信任等级: {level}")
                return
            old = self.current_level
            self.current_level = level
            self._events.append({
                "type": "manual",
                "from": old,
                "to": level,
                "reason": reason,
                "ts": time.time(),
            })
            # S2: 同步更新信任分数（与 _init_trust_score 保持一致：等级中点）
            self._trust_score = level * 20.0 + 10.0  # 每级对应20分，+10 落在等级区间中点
            logger.info(f"P3.1 人工设置信任等级: {old} → {level} ({reason})")
    
    # ============================================================
    # S2: 连续信任分数系统（安全与自主性动态平衡）
    # ============================================================
    
    def _init_trust_score(self, initial_level: int) -> None:
        """初始化信任分数"""
        # 信任分数 0-100，对应 L0-L5（每级20分区间）
        self._trust_score: float = initial_level * 20.0 + 10.0  # 初始在等级中间
        self._trust_score_history: List[Dict[str, Any]] = []
        self._total_success: int = 0
        self._total_failure: int = 0
        # 保存阈值用于计算增益/惩罚幅度（使 promotion_threshold 次成功 ≈ 升一级）
        self._promotion_threshold: int = self.promotion_threshold
        self._demotion_threshold: int = self.demotion_threshold
    
    def _update_trust_score(self, operation: str, success: bool) -> None:
        """
        S2: 更新连续信任分数（0-100）
        
        与静态的 L0-L5 等级不同，信任分数是连续的：
        - 每次成功 → 分数上升（上升幅度随可靠性递减，边际效应）
        - 每次失败 → 分数下降（下降幅度更大，安全优先）
        - 分数自动映射到信任等级（每20分一级）
        
        这实现了"安全与自主性的动态平衡"：
        - 表现好 → 分数升高 → 获得更多自主权
        - 表现差 → 分数降低 → 安全限制加强
        """
        # 计算变化量
        if success:
            # 成功：边际递减（分数越高，提升越难）
            # base_gain 与 promotion_threshold 挂钩：N 次成功 ≈ 升一级（20分）
            base_gain = 20.0 / max(1, self._promotion_threshold)
            difficulty_factor = max(0.2, 1.0 - self._trust_score / 100.0)
            gain = base_gain * difficulty_factor
            self._trust_score = min(100.0, self._trust_score + gain)
            self._total_success += 1
        else:
            # 失败：惩罚更重（安全优先），分数越高惩罚越重
            # base_loss 与 demotion_threshold 挂钩：N 次失败 ≈ 降一级（20分）
            base_loss = 20.0 / max(1, self._demotion_threshold)
            severity_factor = 0.5 + (self._trust_score / 100.0) * 0.5
            loss = base_loss * severity_factor
            self._trust_score = max(0.0, self._trust_score - loss)
            self._total_failure += 1
        
        # 根据信任分数自动调整等级（连续映射）
        new_level = min(5, int(self._trust_score / 20.0))
        if new_level != self.current_level:
            if new_level > self.current_level:
                self._promote(reason=f"信任分数升至 {self._trust_score:.1f}（操作 {operation}）")
            else:
                self._demote(reason=f"信任分数降至 {self._trust_score:.1f}（操作 {operation}）")
        
        # 记录历史（保留最近100条）
        self._trust_score_history.append({
            "score": self._trust_score,
            "operation": operation,
            "success": success,
            "level": self.current_level,
            "ts": time.time(),
        })
        if len(self._trust_score_history) > 100:
            self._trust_score_history = self._trust_score_history[-100:]
    
    def get_trust_score(self) -> Dict[str, Any]:
        """
        S2: 获取完整的信任状态（分数 + 等级 + 趋势）
        """
        with self._lock:
            # 计算趋势（最近10次操作）
            recent = self._trust_score_history[-10:] if len(self._trust_score_history) >= 2 else []
            if len(recent) >= 2:
                trend = recent[-1]["score"] - recent[0]["score"]
            else:
                trend = 0.0
            
            # 成功率
            total_ops = self._total_success + self._total_failure
            success_rate = self._total_success / max(1, total_ops)
            
            # 安全-自主平衡评估
            autonomy_level = self._trust_score / 100.0  # 自主性 0-1
            safety_level = 1.0 - autonomy_level * 0.5  # 安全度（基础100%，随自主性增加而降低，最低50%）
            
            return {
                "trust_score": round(self._trust_score, 1),
                "trust_level": self.current_level,
                "level_name": f"L{self.current_level}",
                "score_range": f"[{self.current_level * 20}, {(self.current_level + 1) * 20})",
                "progress_in_level": round((self._trust_score % 20) / 20.0 * 100, 1),  # 在当前等级中的进度%
                "trend": round(trend, 1),
                "trend_direction": "上升" if trend > 0.5 else "下降" if trend < -0.5 else "平稳",
                "total_success": self._total_success,
                "total_failure": self._total_failure,
                "success_rate": round(success_rate * 100, 1),
                "autonomy_level": round(autonomy_level, 2),
                "safety_level": round(safety_level, 2),
                "balance_status": (
                    "安全优先" if safety_level > 0.8 else
                    "平衡" if 0.6 <= safety_level <= 0.8 else
                    "自主优先"
                ),
            }

    def get_status(self) -> Dict[str, Any]:
        """获取授权系统状态"""
        with self._lock:
            status = {
                "current_level": self.current_level,
                "operation_history_count": {
                    op: len(hist) for op, hist in self._operation_history.items()
                },
                "recent_events": self._events[-10:],
            }
            # S2: 添加信任分数信息
            if hasattr(self, '_trust_score'):
                status["trust_score"] = self.get_trust_score()
            return status


# 全局单例
_auth_instance: Optional[ProgressiveAuthorization] = None
_auth_lock = threading.Lock()


def set_authorization(instance: ProgressiveAuthorization) -> None:
    """手动设置全局授权管理器（Agent 初始化时调用，确保配置生效）"""
    global _auth_instance
    with _auth_lock:
        _auth_instance = instance


def get_authorization(initial_level: int = 1) -> ProgressiveAuthorization:
    """获取全局授权管理器单例"""
    global _auth_instance
    with _auth_lock:
        if _auth_instance is None:
            _auth_instance = ProgressiveAuthorization(initial_level=initial_level)
    return _auth_instance
