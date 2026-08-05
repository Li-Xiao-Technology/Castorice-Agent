"""
P0-2: 三级服务降级策略 (DegradationManager)

当 LLM 服务异常或 token 预算告急时，自动降级以保证核心功能可用：

L1 - 降频 (THROTTLE):
  - 自主循环间隔 ×2
  - 减少工具调用轮次
  - 降低 max_steps

L2 - 精简 (REDUCED):
  - 停用自我反思
  - 停用自我概念更新
  - 停用自传式记忆总结
  - 仅保留核心对话能力

L3 - 保命 (MINIMAL):
  - 停止所有自主活动
  - 仅保留用户对话响应（legacy 模式）
  - 所有工具调用禁用

降级触发条件：
- LLM 连续失败率 > 30%  → L2
- LLM 熔断器 OPEN        → L3
- Token 预算用掉 70%     → L1
- Token 预算用掉 90%     → L2
- Token 预算用掉 95%     → L3
"""
import logging
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger("Castorice.Degradation")


class DegradationLevel(Enum):
    NORMAL = "normal"       # 正常运行
    THROTTLE = "throttle"   # L1 降频
    REDUCED = "reduced"     # L2 精简
    MINIMAL = "minimal"     # L3 保命


@dataclass
class DegradationConfig:
    """降级触发阈值配置"""
    # LLM 失败率阈值
    llm_failure_rate_l1: float = 0.15   # >15% 触发 L1
    llm_failure_rate_l2: float = 0.30   # >30% 触发 L2
    llm_failure_rate_l3: float = 0.60   # >60% 触发 L3

    # Token 预算使用率阈值
    token_usage_l1: float = 0.70   # >70% 触发 L1
    token_usage_l2: float = 0.85   # >85% 触发 L2
    token_usage_l3: float = 0.95   # >95% 触发 L3

    # 评估窗口（最近 N 次 LLM 调用）
    evaluation_window: int = 20

    # 恢复滞后（必须低于阈值 - hysteresis 才恢复）
    hysteresis: float = 0.05


@dataclass
class DegradationStatus:
    """当前降级状态快照"""
    level: str = "normal"
    reason: str = ""
    triggers: Dict[str, float] = field(default_factory=dict)
    since_ts: float = 0.0
    llm_failure_rate: float = 0.0
    token_usage_ratio: float = 0.0


class DegradationManager:
    """
    降级管理器

    - 监控 LLM 失败率和 token 使用率
    - 自动升降降级级别
    - 提供 should_enable() 接口，各模块查询功能是否可用
    - 提供 apply_runtime_overrides() 接口，动态调整运行参数
    """

    def __init__(
        self,
        config: Optional[DegradationConfig] = None,
        circuit_breaker: Any = None,
        cost_budget: Any = None,
    ):
        self.config = config or DegradationConfig()
        self.circuit_breaker = circuit_breaker
        self.cost_budget = cost_budget

        self._lock = threading.RLock()
        self._level = DegradationLevel.NORMAL
        self._level_since = time.time()
        self._reason = ""

        # LLM 调用结果滑动窗口
        self._llm_results: list = []  # True=成功, False=失败

        logger.info("降级管理器已初始化")

    # ============== LLM 结果上报 ==============

    def report_llm_result(self, success: bool) -> None:
        """上报一次 LLM 调用结果"""
        with self._lock:
            self._llm_results.append(success)
            if len(self._llm_results) > self.config.evaluation_window:
                self._llm_results = self._llm_results[-self.config.evaluation_window:]
            self._evaluate_locked()

    # ============== 降级级别查询 ==============

    @property
    def level(self) -> DegradationLevel:
        with self._lock:
            return self._level

    def is_at_least(self, target: DegradationLevel) -> bool:
        """当前级别是否 >= target（越高级限制越多）"""
        order = {
            DegradationLevel.NORMAL: 0,
            DegradationLevel.THROTTLE: 1,
            DegradationLevel.REDUCED: 2,
            DegradationLevel.MINIMAL: 3,
        }
        return order[self.level] >= order[target]

    def should_enable(self, feature: str) -> bool:
        """
        查询某个功能在当前降级级别下是否应该启用

        功能清单：
        - autonomous_quick:      快速自主循环
        - autonomous_deep:       深度自主循环
        - self_reflection:       自我反思
        - self_concept_update:   自我概念更新
        - autobiographical:      自传式记忆总结
        - tool_calls:            工具调用
        - thinking_loop:         ThinkingLoop 自主思考
        - emotion_inference:     情感推理
        """
        if self.is_at_least(DegradationLevel.MINIMAL):
            # L3: 仅保留最基础的对话
            return feature in {"emotion_inference"}

        if self.is_at_least(DegradationLevel.REDUCED):
            # L2: 停用反思、自我概念更新、自传式记忆
            return feature not in {
                "self_reflection", "self_concept_update", "autobiographical",
            }

        if self.is_at_least(DegradationLevel.THROTTLE):
            # L1: 全部功能可用，但自主循环降频（频率在 cost_budget 中控制）
            return True

        # 正常：全部启用
        return True

    # ============== 运行时参数调整 ==============

    def apply_runtime_overrides(self, base_params: Dict[str, Any]) -> Dict[str, Any]:
        """
        根据当前降级级别，调整运行时参数

        会修改：max_steps, tool_rounds, autonomous_interval 等
        """
        params = dict(base_params)

        if self.is_at_least(DegradationLevel.MINIMAL):
            # L3: 极限精简
            params["max_steps"] = min(params.get("max_steps", 8), 2)
            params["enable_self_reflection"] = False
            params["tool_rounds"] = 0
            params["agent_mode"] = "legacy"

        elif self.is_at_least(DegradationLevel.REDUCED):
            # L2: 精简非核心功能
            params["max_steps"] = min(params.get("max_steps", 8), 4)
            params["enable_self_reflection"] = False
            params["tool_rounds"] = min(params.get("tool_rounds", 5), 2)

        elif self.is_at_least(DegradationLevel.THROTTLE):
            # L1: 降频但保留功能
            params["max_steps"] = min(params.get("max_steps", 8), 6)

        return params

    # ============== 状态快照 ==============

    def get_status(self) -> Dict[str, Any]:
        """获取当前降级状态快照"""
        with self._lock:
            failure_rate = self._compute_failure_rate_locked()
            token_ratio = self._compute_token_ratio_locked()

            return {
                "level": self._level.value,
                "level_since": self._level_since,
                "level_seconds_ago": round(time.time() - self._level_since, 1),
                "reason": self._reason,
                "llm": {
                    "failure_rate": round(failure_rate, 3),
                    "window_size": len(self._llm_results),
                    "recent_successes": sum(1 for r in self._llm_results if r),
                    "recent_failures": sum(1 for r in self._llm_results if not r),
                },
                "token_usage_ratio": round(token_ratio, 3),
                "circuit_breaker_open": (
                    self.circuit_breaker.state == "open"
                    if self.circuit_breaker else False
                ),
            }

    # ============== 内部评估逻辑 ==============

    def _evaluate_locked(self) -> None:
        """（需在锁内）评估是否需要升降级"""
        failure_rate = self._compute_failure_rate_locked()
        token_ratio = self._compute_token_ratio_locked()
        hysteresis = self.config.hysteresis

        triggers = {}
        target_level = DegradationLevel.NORMAL

        # 熔断器直接触发 L3
        if self.circuit_breaker and self.circuit_breaker.state == CircuitState.OPEN:
            target_level = DegradationLevel.MINIMAL
            triggers["circuit_breaker"] = 1.0

        # LLM 失败率
        if failure_rate >= self.config.llm_failure_rate_l3:
            target_level = max(target_level, DegradationLevel.MINIMAL)
            triggers["llm_failure_rate"] = failure_rate
        elif failure_rate >= self.config.llm_failure_rate_l2:
            target_level = max(target_level, DegradationLevel.REDUCED)
            triggers["llm_failure_rate"] = failure_rate
        elif failure_rate >= self.config.llm_failure_rate_l1:
            target_level = max(target_level, DegradationLevel.THROTTLE)
            triggers["llm_failure_rate"] = failure_rate

        # Token 使用率
        if token_ratio >= self.config.token_usage_l3:
            target_level = max(target_level, DegradationLevel.MINIMAL)
            triggers["token_usage"] = token_ratio
        elif token_ratio >= self.config.token_usage_l2:
            target_level = max(target_level, DegradationLevel.REDUCED)
            triggers["token_usage"] = token_ratio
        elif token_ratio >= self.config.token_usage_l1:
            target_level = max(target_level, DegradationLevel.THROTTLE)
            triggers["token_usage"] = token_ratio

        # 应用滞后（恢复时需要低于阈值 - hysteresis）
        if target_level.value < self._level.value:
            # 正在恢复，检查滞后
            recovering = True
            if failure_rate >= self.config.llm_failure_rate_l1 - hysteresis:
                recovering = False
            if token_ratio >= self.config.token_usage_l1 - hysteresis:
                recovering = False
            if not recovering:
                target_level = self._level

        # 状态变更
        if target_level != self._level:
            old_level = self._level
            self._level = target_level
            self._level_since = time.time()
            self._reason = "; ".join(
                f"{k}={v:.0%}" for k, v in triggers.items()
            ) if triggers else "所有指标恢复正常"

            if target_level.value > old_level.value:
                logger.warning(
                    f"⚠️  降级: {old_level.value} -> {target_level.value} "
                    f"（原因: {self._reason}）"
                )
            else:
                logger.info(
                    f"✅ 恢复: {old_level.value} -> {target_level.value} "
                    f"（原因: {self._reason}）"
                )

    def _compute_failure_rate_locked(self) -> float:
        """（需在锁内）计算 LLM 失败率"""
        if not self._llm_results:
            return 0.0
        failures = sum(1 for r in self._llm_results if not r)
        return failures / len(self._llm_results)

    def _compute_token_ratio_locked(self) -> float:
        """（需在锁内）计算 token 预算使用率"""
        if not self.cost_budget:
            return 0.0
        try:
            status = self.cost_budget.get_status()
            hour_pct = status.get("hourly", {}).get("used_pct", 0) / 100.0
            day_pct = status.get("daily", {}).get("used_pct", 0) / 100.0
            return max(hour_pct, day_pct)
        except Exception:
            return 0.0


# 避免循环导入
from castorice.health.circuit_breaker import CircuitState  # noqa: E402
