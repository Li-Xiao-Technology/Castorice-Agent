"""
Prometheus 指标导出模块

提供标准 Prometheus 格式的指标输出，支持：
- LLM 调用统计
- Token 使用量
- 工具调用统计
- 会话统计
- 系统状态
"""

import logging
import time
from typing import Dict, Optional

logger = logging.getLogger("Castorice.Metrics")


class MetricsCollector:
    """Prometheus 指标收集器"""
    
    def __init__(self):
        self._metrics = {
            "castorice_llm_calls_total": {"type": "counter", "help": "Total LLM calls", "value": 0},
            "castorice_llm_errors_total": {"type": "counter", "help": "Total LLM errors", "value": 0},
            "castorice_llm_prompt_tokens_total": {"type": "counter", "help": "Total prompt tokens", "value": 0},
            "castorice_llm_completion_tokens_total": {"type": "counter", "help": "Total completion tokens", "value": 0},
            "castorice_llm_latency_seconds": {"type": "histogram", "help": "LLM latency in seconds", "buckets": [0.1, 0.5, 1.0, 2.0, 5.0, 10.0]},
            "castorice_tool_calls_total": {"type": "counter", "help": "Total tool calls", "value": 0},
            "castorice_tool_errors_total": {"type": "counter", "help": "Total tool errors", "value": 0},
            "castorice_sessions_active": {"type": "gauge", "help": "Active sessions count", "value": 0},
            "castorice_long_term_memory_count": {"type": "gauge", "help": "Long term memory count", "value": 0},
            "castorice_requests_total": {"type": "counter", "help": "Total API requests", "value": 0},
            "castorice_requests_4xx_total": {"type": "counter", "help": "Total 4xx requests", "value": 0},
            "castorice_requests_5xx_total": {"type": "counter", "help": "Total 5xx requests", "value": 0},
        }
        self._latency_buckets = {b: 0 for b in [0.1, 0.5, 1.0, 2.0, 5.0, 10.0]}
        self._latency_sum = 0.0
        self._latency_count = 0
        self._tool_calls_by_name = {}
        self._start_time = time.time()
    
    def record_llm_call(self, prompt_tokens: int = 0, completion_tokens: int = 0, 
                        error: bool = False, latency_ms: float = 0.0) -> None:
        """记录 LLM 调用"""
        self._metrics["castorice_llm_calls_total"]["value"] += 1
        self._metrics["castorice_llm_prompt_tokens_total"]["value"] += prompt_tokens
        self._metrics["castorice_llm_completion_tokens_total"]["value"] += completion_tokens
        if error:
            self._metrics["castorice_llm_errors_total"]["value"] += 1
        if latency_ms > 0:
            latency_s = latency_ms / 1000.0
            self._latency_sum += latency_s
            self._latency_count += 1
            for bucket in self._latency_buckets:
                if latency_s <= bucket:
                    self._latency_buckets[bucket] += 1
    
    def record_tool_call(self, tool_name: str, error: bool = False) -> None:
        """记录工具调用"""
        self._metrics["castorice_tool_calls_total"]["value"] += 1
        if error:
            self._metrics["castorice_tool_errors_total"]["value"] += 1
        self._tool_calls_by_name[tool_name] = self._tool_calls_by_name.get(tool_name, 0) + 1
    
    def record_request(self, status_code: int) -> None:
        """记录 HTTP 请求"""
        self._metrics["castorice_requests_total"]["value"] += 1
        if 400 <= status_code < 500:
            self._metrics["castorice_requests_4xx_total"]["value"] += 1
        elif status_code >= 500:
            self._metrics["castorice_requests_5xx_total"]["value"] += 1
    
    def set_sessions_count(self, count: int) -> None:
        """设置活跃会话数"""
        self._metrics["castorice_sessions_active"]["value"] = count
    
    def set_long_term_count(self, count: int) -> None:
        """设置长期记忆条数"""
        self._metrics["castorice_long_term_memory_count"]["value"] = count
    
    def generate_prometheus_output(self) -> str:
        """生成 Prometheus 格式的指标输出"""
        lines = []
        
        lines.append("# HELP castorice_uptime_seconds Castorice uptime in seconds")
        lines.append("# TYPE castorice_uptime_seconds gauge")
        lines.append(f"castorice_uptime_seconds {time.time() - self._start_time}")
        
        for name, info in self._metrics.items():
            metric_type = info["type"]
            help_text = info["help"]
            
            lines.append(f"# HELP {name} {help_text}")
            lines.append(f"# TYPE {name} {metric_type}")
            
            if metric_type == "counter" or metric_type == "gauge":
                lines.append(f"{name} {info['value']}")
        
        lines.append("# HELP castorice_llm_latency_seconds_bucket LLM latency buckets")
        lines.append("# TYPE castorice_llm_latency_seconds_bucket histogram")
        for bucket, count in self._latency_buckets.items():
            lines.append(f"castorice_llm_latency_seconds_bucket{{le=\"{bucket}\"}} {count}")
        lines.append(f"castorice_llm_latency_seconds_bucket{{le=\"+Inf\"}} {self._latency_count}")
        
        lines.append("# HELP castorice_llm_latency_seconds_sum LLM latency sum")
        lines.append("# TYPE castorice_llm_latency_seconds_sum histogram")
        lines.append(f"castorice_llm_latency_seconds_sum {self._latency_sum}")
        
        lines.append("# HELP castorice_llm_latency_seconds_count LLM latency count")
        lines.append("# TYPE castorice_llm_latency_seconds_count histogram")
        lines.append(f"castorice_llm_latency_seconds_count {self._latency_count}")
        
        lines.append("# HELP castorice_tool_calls_by_name_total Tool calls by name")
        lines.append("# TYPE castorice_tool_calls_by_name_total counter")
        for tool_name, count in self._tool_calls_by_name.items():
            escaped_name = tool_name.replace('"', '\\"')
            lines.append(f'castorice_tool_calls_by_name_total{{name="{escaped_name}"}} {count}')
        
        return "\n".join(lines) + "\n"


_metrics_collector = None


def get_metrics_collector() -> MetricsCollector:
    """获取全局指标收集器单例"""
    global _metrics_collector
    if _metrics_collector is None:
        _metrics_collector = MetricsCollector()
    return _metrics_collector
