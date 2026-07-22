"""
自感知模块 (SelfAwareness) - 深化版

让 Agent 知道自己的状态、能力边界、健康状况、资源使用情况、能力画像。
不修改任何代码/配置，纯只读监控。

功能：
1. 状态监控：Token使用、调用次数、错误率、工具成功率
2. 健康检查：综合健康评分、异常检测
3. 能力边界判断：能否处理某个任务、置信度评估
4. 资源感知：上下文窗口、Token预算、自动压缩建议
5. 能力画像：擅长/不擅长的任务类型、工具熟练度
6. 状态模型：疲劳度、速率限制、自适应降速
7. "不知道"检测：何时应该承认自己不知道
"""

import logging
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("Castorice.SelfAwareness")


# 各模型的最大上下文窗口（估算，用于资源感知）
MODEL_CONTEXT_LIMITS = {
    "gpt-4o": 128000,
    "gpt-4o-mini": 128000,
    "gpt-4": 8192,
    "gpt-4-turbo": 128000,
    "claude-3-5-sonnet": 200000,
    "claude-3-opus": 200000,
    "claude-3-haiku": 200000,
    "gemini-1.5-flash": 1000000,
    "gemini-1.5-pro": 2000000,
    "qwen-plus": 32768,
    "qwen-max": 32768,
    "qwen-turbo": 8192,
    "llama3.1:8b": 8192,
    "llama3.1:70b": 128000,
}

DEFAULT_CONTEXT_LIMIT = 8192
CONTEXT_WARNING_THRESHOLD = 0.7
CONTEXT_CRITICAL_THRESHOLD = 0.9


@dataclass
class ToolStats:
    """单个工具的统计数据"""
    call_count: int = 0
    success_count: int = 0
    fail_count: int = 0
    total_time_ms: float = 0.0
    last_called_at: Optional[str] = None

    @property
    def success_rate(self) -> float:
        if self.call_count == 0:
            return 1.0
        return self.success_count / self.call_count

    @property
    def avg_time_ms(self) -> float:
        if self.call_count == 0:
            return 0.0
        return self.total_time_ms / self.call_count


@dataclass
class AgentStats:
    """Agent 整体统计数据"""
    total_calls: int = 0
    total_tokens: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_errors: int = 0
    total_tasks: int = 0
    successful_tasks: int = 0
    started_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @property
    def error_rate(self) -> float:
        if self.total_calls == 0:
            return 0.0
        return self.total_errors / self.total_calls

    @property
    def task_success_rate(self) -> float:
        if self.total_tasks == 0:
            return 1.0
        return self.successful_tasks / self.total_tasks


@dataclass
class ResourceState:
    """资源状态"""
    context_limit: int = DEFAULT_CONTEXT_LIMIT
    current_prompt_tokens: int = 0
    current_completion_tokens: int = 0
    current_total_tokens: int = 0
    usage_ratio: float = 0.0
    status: str = "ok"  # ok / warning / critical


class CapabilityProfile:
    """
    能力画像 - 统计 Agent 擅长/不擅长什么。

    按任务类型统计：
    - 问答类
    - 搜索类
    - 代码类
    - 文件操作类
    - 分析类
    """

    TASK_TYPES = {
        "chat": ["你好", "hi", "hello", "谢谢", "再见", "闲聊"],
        "search": ["搜索", "查找", "新闻", "最新", "查询"],
        "code": ["python", "代码", "编程", "写个函数", "脚本"],
        "file_io": ["读文件", "写文件", "打开", "保存", "文件"],
        "analysis": ["分析", "对比", "总结", "评估", "推荐"],
        "weather": ["天气", "气温", "下雨"],
    }

    def __init__(self):
        self._task_stats: Dict[str, Dict[str, Any]] = defaultdict(
            lambda: {"count": 0, "success": 0, "total_time_ms": 0.0}
        )

    def classify_task(self, user_input: str) -> List[str]:
        """对任务进行分类（可能属于多个类型）"""
        input_lower = user_input.lower()
        matched = []
        for task_type, keywords in self.TASK_TYPES.items():
            if any(kw in input_lower for kw in keywords):
                matched.append(task_type)
        if not matched:
            matched.append("general")
        return matched

    def record_task(self, user_input: str, success: bool, elapsed_ms: float = 0.0) -> None:
        """记录一次任务执行"""
        task_types = self.classify_task(user_input)
        for task_type in task_types:
            stats = self._task_stats[task_type]
            stats["count"] += 1
            if success:
                stats["success"] += 1
            stats["total_time_ms"] += elapsed_ms

    def get_profile(self) -> Dict[str, Any]:
        """获取能力画像"""
        result = {}
        for task_type, stats in self._task_stats.items():
            count = stats["count"]
            success_rate = stats["success"] / count if count > 0 else 1.0
            avg_time = stats["total_time_ms"] / count if count > 0 else 0.0
            result[task_type] = {
                "count": count,
                "success_rate": round(success_rate, 3),
                "avg_time_ms": round(avg_time, 1),
                "proficiency": self._rate_proficiency(success_rate, count),
            }
        return result

    def _rate_proficiency(self, success_rate: float, count: int) -> str:
        """评级熟练度"""
        if count < 3:
            return "unknown"
        if success_rate >= 0.9:
            return "expert"
        elif success_rate >= 0.7:
            return "proficient"
        elif success_rate >= 0.5:
            return "learning"
        else:
            return "struggling"

    def get_strengths(self, min_count: int = 3) -> List[str]:
        """获取擅长领域"""
        strengths = []
        for task_type, stats in self._task_stats.items():
            if stats["count"] >= min_count and stats["success"] / stats["count"] >= 0.8:
                strengths.append(task_type)
        return strengths

    def get_weaknesses(self, min_count: int = 3) -> List[str]:
        """获取不擅长领域"""
        weaknesses = []
        for task_type, stats in self._task_stats.items():
            if stats["count"] >= min_count and stats["success"] / stats["count"] < 0.5:
                weaknesses.append(task_type)
        return weaknesses


class StateModel:
    """
    状态模型 - 疲劳度、速率限制、自适应降速。

    设计原则：
    - 不阻止任务执行，只提供建议
    - 基于近期错误率和调用频率计算"疲劳度"
    """

    def __init__(self, window_size: int = 10):
        self._recent_errors = deque(maxlen=window_size)
        self._recent_call_times = deque(maxlen=window_size)
        self._consecutive_errors = 0
        self._last_call_time = 0.0
        self._fatigue_score = 0.0

    def record_call(self, error: bool = False, latency_ms: float = 0.0) -> None:
        """记录一次调用"""
        now = time.time()
        self._recent_call_times.append(now)

        if error:
            self._recent_errors.append(1)
            self._consecutive_errors += 1
        else:
            self._recent_errors.append(0)
            self._consecutive_errors = 0

        self._last_call_time = now
        self._update_fatigue()

    def _update_fatigue(self) -> None:
        """更新疲劳度"""
        error_rate = sum(self._recent_errors) / len(self._recent_errors) if self._recent_errors else 0.0
        fatigue = error_rate * 0.5 + min(1.0, self._consecutive_errors / 3) * 0.5
        self._fatigue_score = min(1.0, fatigue)

    def get_state(self) -> Dict[str, Any]:
        """获取当前状态"""
        recent_error_rate = (sum(self._recent_errors) / len(self._recent_errors)
                             if self._recent_errors else 0.0)
        return {
            "fatigue_score": round(self._fatigue_score, 3),
            "consecutive_errors": self._consecutive_errors,
            "recent_error_rate": round(recent_error_rate, 3),
            "should_slow_down": self._fatigue_score > 0.5,
            "recommended_delay_ms": self._recommended_delay(),
        }

    def _recommended_delay(self) -> int:
        """推荐延迟（毫秒）"""
        if self._fatigue_score < 0.3:
            return 0
        elif self._fatigue_score < 0.6:
            return 500
        elif self._fatigue_score < 0.8:
            return 1500
        else:
            return 3000


class SelfAwareness:
    """
    自感知模块 - 纯只读，不产生任何副作用。

    设计原则：
    - 只读取状态，不修改任何东西
    - 所有数据在内存中，重启即清空
    - 线程安全
    """

    def __init__(self, tools: List[Any] = None, model_name: str = ""):
        self._lock = threading.RLock()
        self._stats = AgentStats()
        self._tool_stats: Dict[str, ToolStats] = defaultdict(ToolStats)
        self._tool_names = set(t.name for t in tools) if tools else set()

        self._recent_errors = deque(maxlen=20)
        self._recent_latencies = deque(maxlen=100)

        self._capability_profile = CapabilityProfile()
        self._state_model = StateModel()
        self._resource_state = ResourceState()
        self._model_name = model_name


    # ============================================================
    # 数据记录接口（供 Agent 调用）
    # ============================================================

    def record_llm_call(self, prompt_tokens: int = 0, completion_tokens: int = 0,
                        error: bool = False, latency_ms: float = 0.0) -> None:
        """记录一次 LLM 调用"""
        with self._lock:
            self._stats.total_calls += 1
            self._stats.prompt_tokens += prompt_tokens
            self._stats.completion_tokens += completion_tokens
            self._stats.total_tokens += prompt_tokens + completion_tokens
            if error:
                self._stats.total_errors += 1
            if latency_ms > 0:
                self._recent_latencies.append(latency_ms)

            self._state_model.record_call(error=error, latency_ms=latency_ms)

            # 更新资源状态（当前上下文窗口的 token 用量）
            self._resource_state.current_prompt_tokens = prompt_tokens
            self._resource_state.current_completion_tokens = completion_tokens
            self._resource_state.current_total_tokens = prompt_tokens + completion_tokens
            self._update_resource_state()

    def reset_context_counter(self) -> None:
        """重置上下文窗口计数器（在新会话或新轮次开始时调用）"""
        with self._lock:
            self._resource_state.current_prompt_tokens = 0
            self._resource_state.current_completion_tokens = 0
            self._resource_state.current_total_tokens = 0
            self._update_resource_state()

    def record_tool_call(self, tool_name: str, success: bool,
                         latency_ms: float = 0.0, error_msg: str = "") -> None:
        """记录一次工具调用"""
        with self._lock:
            stats = self._tool_stats[tool_name]
            stats.call_count += 1
            if success:
                stats.success_count += 1
            else:
                stats.fail_count += 1
                if error_msg:
                    self._recent_errors.append({
                        "tool": tool_name,
                        "error": error_msg[:200],
                        "time": datetime.now(timezone.utc).isoformat(),
                    })
            stats.total_time_ms += latency_ms
            stats.last_called_at = datetime.now(timezone.utc).isoformat()

    def record_task(self, user_input: str, success: bool, elapsed_ms: float = 0.0) -> None:
        """记录一次任务完成"""
        with self._lock:
            self._stats.total_tasks += 1
            if success:
                self._stats.successful_tasks += 1
            self._capability_profile.record_task(user_input, success, elapsed_ms)

    def set_model_name(self, model_name: str) -> None:
        """设置模型名称，用于上下文窗口估算"""
        self._model_name = model_name
        self._update_resource_state()

    # ============================================================
    # 资源感知
    # ============================================================

    def _update_resource_state(self) -> None:
        """更新资源使用状态"""
        limit = DEFAULT_CONTEXT_LIMIT
        for key, value in MODEL_CONTEXT_LIMITS.items():
            if key in self._model_name.lower():
                limit = value
                break

        self._resource_state.context_limit = limit
        total = self._resource_state.current_total_tokens
        self._resource_state.usage_ratio = total / limit if limit > 0 else 0.0

        if self._resource_state.usage_ratio >= CONTEXT_CRITICAL_THRESHOLD:
            self._resource_state.status = "critical"
        elif self._resource_state.usage_ratio >= CONTEXT_WARNING_THRESHOLD:
            self._resource_state.status = "warning"
        else:
            self._resource_state.status = "ok"

    def get_resource_state(self) -> Dict[str, Any]:
        """获取资源状态"""
        with self._lock:
            return {
                "context_limit": self._resource_state.context_limit,
                "current_total_tokens": self._resource_state.current_total_tokens,
                "usage_ratio": round(self._resource_state.usage_ratio, 4),
                "status": self._resource_state.status,
                "should_compress": self._resource_state.usage_ratio >= CONTEXT_WARNING_THRESHOLD,
            }

    def estimate_tokens(self, text: str) -> int:
        """
        估算文本 Token 数

        P2-2: 优先使用 tiktoken 精确计数（OpenAI 模型），
        不可用时回退到中英文分离估算（中文1字≈1.5token，英文1词≈1.3token）。
        """
        if not text:
            return 0
        # P2-2: 优先使用 tiktoken（OpenAI cl100k_base 编码，适用于 GPT-4/4o/3.5）
        try:
            import tiktoken
            if not hasattr(self, "_tiktoken_enc") or self._tiktoken_enc is None:
                self._tiktoken_enc = tiktoken.get_encoding("cl100k_base")
            return len(self._tiktoken_enc.encode(text))
        except ImportError:
            pass
        except Exception as e:
            logger.warning(f"tiktoken 编码失败，回退到估算: {e}")

        # 回退：中文按 1.5 token/字，英文按 1.3 token/词
        import re
        chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', text))
        english_words = len(re.findall(r'[a-zA-Z]+', text))
        # 其他字符（标点/数字/emoji）按 0.5 token 估算
        other_chars = len(text) - chinese_chars - sum(len(w) for w in re.findall(r'[a-zA-Z]+', text))
        return int(chinese_chars * 1.5 + english_words * 1.3 + other_chars * 0.5)

    def should_compress_context(self, current_context: str) -> Tuple[bool, str]:
        """判断是否需要压缩上下文"""
        estimated = self.estimate_tokens(current_context)
        limit = self._resource_state.context_limit
        ratio = estimated / limit if limit > 0 else 0.0

        if ratio >= CONTEXT_CRITICAL_THRESHOLD:
            return True, f"上下文占用率 {ratio:.1%}，建议立即压缩"
        elif ratio >= CONTEXT_WARNING_THRESHOLD:
            return True, f"上下文占用率 {ratio:.1%}，建议压缩"
        return False, f"上下文占用率 {ratio:.1%}，无需压缩"

    # ============================================================
    # 状态查询接口
    # ============================================================

    def get_stats(self) -> Dict[str, Any]:
        """获取完整统计数据"""
        with self._lock:
            tool_stats_dict = {
                name: {
                    "call_count": s.call_count,
                    "success_count": s.success_count,
                    "fail_count": s.fail_count,
                    "success_rate": round(s.success_rate, 3),
                    "avg_time_ms": round(s.avg_time_ms, 1),
                }
                for name, s in self._tool_stats.items()
            }
            return {
                "agent": {
                    "total_calls": self._stats.total_calls,
                    "total_tokens": self._stats.total_tokens,
                    "prompt_tokens": self._stats.prompt_tokens,
                    "completion_tokens": self._stats.completion_tokens,
                    "total_errors": self._stats.total_errors,
                    "error_rate": round(self._stats.error_rate, 3),
                    "total_tasks": self._stats.total_tasks,
                    "successful_tasks": self._stats.successful_tasks,
                    "task_success_rate": round(self._stats.task_success_rate, 3),
                    "uptime_seconds": round(
                        (datetime.now(timezone.utc) - datetime.fromisoformat(self._stats.started_at)).total_seconds(),
                        1
                    ),
                },
                "tools": tool_stats_dict,
                "recent_errors": list(self._recent_errors),
                "state_model": self._state_model.get_state(),
                "resource": self.get_resource_state(),
                "capability_profile": self._capability_profile.get_profile(),
                "strengths": self._capability_profile.get_strengths(),
                "weaknesses": self._capability_profile.get_weaknesses(),
            }

    def health_check(self) -> Dict[str, Any]:
        """
        健康检查 - 综合评估 Agent 健康状态。

        返回：
        - status: healthy / warning / critical
        - score: 0-100 健康评分
        - issues: 问题列表
        """
        with self._lock:
            issues = []
            score = 100

            if self._stats.error_rate > 0.3:
                issues.append(f"LLM 错误率过高: {self._stats.error_rate:.1%}")
                score -= 30
            elif self._stats.error_rate > 0.1:
                issues.append(f"LLM 错误率偏高: {self._stats.error_rate:.1%}")
                score -= 10

            if self._stats.task_success_rate < 0.5:
                issues.append(f"任务成功率过低: {self._stats.task_success_rate:.1%}")
                score -= 25
            elif self._stats.task_success_rate < 0.7:
                issues.append(f"任务成功率偏低: {self._stats.task_success_rate:.1%}")
                score -= 10

            for name, stats in self._tool_stats.items():
                if stats.call_count >= 3 and stats.success_rate < 0.5:
                    issues.append(f"工具 {name} 成功率过低: {stats.success_rate:.1%}")
                    score -= 15

            if len(self._recent_errors) >= 5:
                issues.append(f"近期错误频繁: {len(self._recent_errors)} 次/最近20次")
                score -= 10

            state = self._state_model.get_state()
            if state["fatigue_score"] > 0.6:
                issues.append(f"系统疲劳度较高: {state['fatigue_score']:.2f}")
                score -= 10

            resource = self.get_resource_state()
            if resource["status"] == "critical":
                issues.append(f"上下文窗口占用过高: {resource['usage_ratio']:.1%}")
                score -= 15
            elif resource["status"] == "warning":
                issues.append(f"上下文窗口占用偏高: {resource['usage_ratio']:.1%}")
                score -= 5

            if score >= 80:
                status = "healthy"
            elif score >= 50:
                status = "warning"
            else:
                status = "critical"

            return {
                "status": status,
                "score": max(0, score),
                "issues": issues,
            }

    # ============================================================
    # 能力边界判断
    # ============================================================

    def can_handle(self, user_input: str, available_tools: List[str] = None) -> Tuple[bool, float, str]:
        """
        判断 Agent 能否处理这个任务。

        返回：(can_handle, confidence, reason)
        - can_handle: 是否能处理
        - confidence: 置信度 0-1
        - reason: 判断理由
        """
        tools = available_tools or list(self._tool_names)
        input_lower = user_input.lower()

        confidence = 0.5
        reasons = []

        # 规则1：纯闲聊/知识问答 - 能处理
        chat_keywords = ["你好", "hi", "hello", "谢谢", "再见", "介绍", "是什么", "为什么", "怎么"]
        if any(kw in input_lower for kw in chat_keywords) and len(user_input) < 50:
            confidence = 0.9
            reasons.append("简单问答，无需工具")
            return True, confidence, "; ".join(reasons)

        # 规则2：需要工具支持的任务
        tool_indicators = {
            "web_search": ["搜索", "查找", "新闻", "最新", "今天", "查一下", "百度", "谷歌"],
            "get_weather": ["天气", "气温", "下雨", "温度", "气候"],
            "read_file": ["读取", "读文件", "看一下文件", "打开文件", "文件内容"],
            "write_file": ["写入", "写文件", "保存", "创建文件"],
            "python_repl": ["python", "代码", "执行", "运行", "计算"],
            "terminal": ["命令", "终端", "shell", "cmd", "执行命令"],
            "read_document": ["读文档", "文档", "pdf", "word"],
        }

        matched_tools = []
        for tool_name, keywords in tool_indicators.items():
            if tool_name in tools and any(kw in input_lower for kw in keywords):
                matched_tools.append(tool_name)

        if matched_tools:
            confidence = 0.7 + len(matched_tools) * 0.05
            reasons.append(f"需要工具: {', '.join(matched_tools)}")
        else:
            confidence = 0.4
            reasons.append("未匹配到明确的工具需求")

        # 规则3：检测"不知道"的场景
        unknown_indicators = [
            ("个人隐私/私密信息", ["你的密码", "你的密钥", "api key", "secret"]),
            ("实时金融数据", ["股价", "股票", "基金", "行情"]),
            ("医学诊断", ["诊断", "治疗", "药方", "我得了什么病"]),
            ("法律咨询", ["律师", "起诉", "违法", "犯法"]),
        ]

        for category, keywords in unknown_indicators:
            if any(kw in input_lower for kw in keywords):
                confidence -= 0.3
                reasons.append(f"涉及 {category}，建议谨慎回答")

        # 规则4：能力画像调整
        weaknesses = self._capability_profile.get_weaknesses(min_count=2)
        task_types = self._capability_profile.classify_task(user_input)
        weak_match = [t for t in task_types if t in weaknesses]
        if weak_match:
            confidence -= 0.15
            reasons.append(f"历史表现较弱: {', '.join(weak_match)}")

        can_handle = confidence >= 0.3
        return can_handle, max(0.0, min(1.0, confidence)), "; ".join(reasons)

    def should_admit_ignorance(self, user_input: str, tool_results: List[str] = None) -> Tuple[bool, str]:
        """
        判断是否应该说"我不知道"。

        返回：(should_admit, reason)
        """
        tool_results = tool_results or []
        input_lower = user_input.lower()

        high_uncertainty_topics = [
            ("实时股价/金融", ["股价", "股票代码", "今日行情", "基金净值"]),
            ("精确医学建议", ["我得了什么病", "吃什么药", "诊断结果"]),
            ("个人隐私信息", ["某人的电话", "某人的地址", "隐私信息"]),
            ("未来预测", ["明天会涨吗", "预测一下", "未来会怎样"]),
        ]

        for category, keywords in high_uncertainty_topics:
            if any(kw in input_lower for kw in keywords):
                if not tool_results:
                    return True, f"涉及 {category}，且无工具结果支撑，建议承认不知道"

        if tool_results:
            empty_results = sum(1 for r in tool_results if not r or len(r) < 10)
            if empty_results / len(tool_results) > 0.7:
                return True, "工具返回结果大多为空，信息不足"

        return False, ""

    def should_slow_down(self) -> Tuple[bool, Dict[str, Any]]:
        """判断是否应该降速"""
        state = self._state_model.get_state()
        return state["should_slow_down"], state

    # ============================================================
    # 诊断建议
    # ============================================================

    def get_diagnosis(self) -> List[str]:
        """获取诊断建议 - 基于当前状态给出改进建议"""
        suggestions = []
        health = self.health_check()
        stats = self.get_stats()

        if health["status"] == "critical":
            suggestions.append("⚠️ 系统状态危急，建议检查网络连接和API密钥配置")
        elif health["status"] == "warning":
            suggestions.append("⚠️ 系统状态有异常，建议查看错误日志")

        tool_stats = stats.get("tools", {})
        for name, ts in tool_stats.items():
            if ts.get("call_count", 0) >= 5 and ts.get("success_rate", 1) < 0.6:
                suggestions.append(f"🔧 工具 '{name}' 成功率偏低（{ts['success_rate']:.0%}），建议检查工具配置")

        if stats["agent"]["total_tokens"] > 100000:
            suggestions.append(f"💰 Token 用量已达 {stats['agent']['total_tokens']:,}，注意成本控制")

        resource = stats.get("resource", {})
        if resource.get("status") in ("warning", "critical"):
            suggestions.append(f"📏 上下文窗口占用 {resource.get('usage_ratio', 0):.1%}，建议压缩历史对话")

        weaknesses = stats.get("weaknesses", [])
        if weaknesses:
            suggestions.append(f"📉 在以下领域表现较弱: {', '.join(weaknesses)}，建议重点关注")

        if not suggestions:
            suggestions.append("✅ 系统运行正常，无明显问题")

        return suggestions

    # ============================================================
    # P0.2: 认知健康度指标（防止认知层面的自我崩溃）
    # ============================================================

    def record_cognitive_event(self, event_type: str, payload: Optional[Dict[str, Any]] = None) -> None:
        """
        P0.2: 记录一次认知事件（自我概念更新、记忆删除、行为策略改变等）

        用于追踪 Agent 的"思想轨迹"，检测认知漂移。
        """
        with self._lock:
            if not hasattr(self, "_cognitive_events"):
                self._cognitive_events = deque(maxlen=100)
            self._cognitive_events.append({
                "type": event_type,
                "ts": time.time(),
                "payload": payload or {},
            })

    def _get_cognitive_events(self) -> list:
        """P0.2: 内部获取认知事件列表"""
        if not hasattr(self, "_cognitive_events"):
            return []
        return list(self._cognitive_events)

    def cognitive_health_check(self, self_concept_text: str = "",
                                initial_self_concept_text: str = "") -> Dict[str, Any]:
        """
        P0.2: 认知健康度评估

        三维指标：
        1. 连贯性：当前自我概念与初始版本的语义相似度
        2. 稳定性：近期认知事件（自我概念更新/记忆删除）的频率与方差
        3. 完整性：重要记忆的引用计数（与自我概念交叉引用）

        返回：
        - status: healthy / warning / critical
        - score: 0-100
        - dimensions: {连贯性, 稳定性, 完整性}
        - anomalies: 异常列表
        """
        with self._lock:
            dimensions = {"连贯性": 100, "稳定性": 100, "完整性": 100}
            anomalies: List[str] = []

            # 维度1: 连贯性（自我概念与初始版本的差异）
            if self_concept_text and initial_self_concept_text:
                sim = self._text_similarity(self_concept_text, initial_self_concept_text)
                coherence_score = int(sim * 100)
                dimensions["连贯性"] = coherence_score
                if coherence_score < 30:
                    anomalies.append(f"自我概念与初始版本相似度极低 ({coherence_score}%)，可能已'自我消解'")
                elif coherence_score < 50:
                    anomalies.append(f"自我概念漂移明显 ({coherence_score}%)，建议关注")

            # 维度2: 稳定性（认知事件频率）
            events = self._get_cognitive_events()
            recent_events = [e for e in events if time.time() - e["ts"] < 3600]  # 1h 内
            update_events = [e for e in recent_events if e["type"] in
                             ("self_concept_update", "memory_delete", "rule_change")]
            if len(update_events) > 10:
                dimensions["稳定性"] = 30
                anomalies.append(f"近期认知变更过于频繁 (1h 内 {len(update_events)} 次)")
            elif len(update_events) > 5:
                dimensions["稳定性"] = 60
                anomalies.append(f"近期认知变更较频繁 (1h 内 {len(update_events)} 次)")

            # 维度3: 完整性（自我概念必须有核心章节）
            if self_concept_text:
                required_sections = ["## 我是谁", "## 我的行为模式", "## 我的情感特征"]
                missing = [s for s in required_sections if s not in self_concept_text]
                if missing:
                    dimensions["完整性"] = max(0, 100 - len(missing) * 30)
                    anomalies.append(f"自我概念缺少核心章节: {', '.join(missing)}")

            score = sum(dimensions.values()) // 3
            if score >= 80:
                status = "healthy"
            elif score >= 50:
                status = "warning"
            else:
                status = "critical"

            return {
                "status": status,
                "score": score,
                "dimensions": dimensions,
                "anomalies": anomalies,
                "should_alert_agent": status == "critical",
            }

    @staticmethod
    def _text_similarity(a: str, b: str) -> float:
        """
        P0.2: 简易文本相似度（基于字符集合 + 词集合 Jaccard）
        不依赖外部库，开销极低。
        """
        if not a or not b:
            return 0.0
        # 词级 Jaccard
        import re
        tokens_a = set(re.findall(r"[\w\u4e00-\u9fa5]+", a.lower()))
        tokens_b = set(re.findall(r"[\w\u4e00-\u9fa5]+", b.lower()))
        if not tokens_a or not tokens_b:
            return 0.0
        inter = tokens_a & tokens_b
        union = tokens_a | tokens_b
        return len(inter) / len(union)
