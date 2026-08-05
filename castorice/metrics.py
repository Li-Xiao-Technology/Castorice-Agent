"""
Castorice Agent - 监控指标

提供：
- 请求计数
- 延迟统计
- 错误率
- 缓存命中率
- Token 用量

兼容 prometheus_client（可选）
"""

import threading
import time
from collections import defaultdict
from threading import Lock
from typing import Any, Dict, Optional

from .logger import get_logger

logger = get_logger(__name__)


class MetricsCollector:
    """
    轻量级指标收集器

    无需 prometheus_client 依赖，
    提供基本统计和文本格式导出
    """

    def __init__(self):
        self._lock = Lock()
        # 计数器
        self._counters: Dict[str, int] = defaultdict(int)
        # 延迟记录（最近 N 次）
        self._latencies: Dict[str, list] = defaultdict(list)
        self._max_latency_samples = 1000
        # 错误记录
        self._errors: Dict[str, int] = defaultdict(int)
        # Token 用量
        self._tokens: Dict[str, int] = defaultdict(int)
        # Gauge 指标（如会话数、记忆条目数等可增可减的瞬时值）
        self._gauges: Dict[str, float] = {}

    def inc_counter(self, name: str, value: int = 1, **labels) -> None:
        """递增计数器"""
        key = self._make_key(name, labels)
        with self._lock:
            self._counters[key] += value

    def record_latency(self, name: str, duration: float, **labels) -> None:
        """记录延迟（秒）"""
        key = self._make_key(name, labels)
        with self._lock:
            latencies = self._latencies[key]
            latencies.append(duration)
            # 限制样本数量
            if len(latencies) > self._max_latency_samples:
                latencies.pop(0)

    def inc_error(self, name: str, **labels) -> None:
        """记录错误"""
        key = self._make_key(name, labels)
        with self._lock:
            self._errors[key] += 1

    def add_tokens(self, name: str, count: int, **labels) -> None:
        """记录 Token 用量"""
        key = self._make_key(name, labels)
        with self._lock:
            self._tokens[key] += count

    def _make_key(self, name: str, labels: Dict[str, Any]) -> str:
        """生成指标 key"""
        if labels:
            label_str = ",".join(f"{k}={v}" for k, v in sorted(labels.items()))
            return f"{name}{{{label_str}}}"
        return name


    def get_stats(self) -> Dict[str, Any]:
        """获取所有统计"""
        with self._lock:
            stats = {
                "counters": dict(self._counters),
                "latencies": {},
                "errors": dict(self._errors),
                "tokens": dict(self._tokens),
                "gauges": dict(self._gauges),
            }

            for key, samples in self._latencies.items():
                if not samples:
                    continue
                sorted_samples = sorted(samples)
                stats["latencies"][key] = {
                    "count": len(samples),
                    "avg": sum(samples) / len(samples),
                    "min": min(samples),
                    "max": max(samples),
                    "p50": sorted_samples[len(sorted_samples) // 2],
                    "p95": sorted_samples[int(len(sorted_samples) * 0.95)] if len(sorted_samples) > 1 else sorted_samples[0],
                    "p99": sorted_samples[int(len(sorted_samples) * 0.99)] if len(sorted_samples) > 1 else sorted_samples[0],
                }

            return stats

    def export_prometheus(self) -> str:
        """导出为 Prometheus 文本格式"""
        lines = []
        stats = self.get_stats()

    # counters
        for key, value in stats["counters"].items():
            name, labels = self._parse_key(key)
            labels_str = self._format_labels(labels)
            lines.append(f"# TYPE {name} counter")
            lines.append(f"{name}{labels_str} {value}")

    # latencies (gauge)
        for key, info in stats["latencies"].items():
            name, labels = self._parse_key(key)
            for metric in ["avg", "p50", "p95", "p99", "max"]:
                labels_with_metric = {**labels, "quantile": metric} if metric != "avg" else labels
                labels_str = self._format_labels(labels_with_metric)
                lines.append(f"# TYPE {name}_seconds summary")
                lines.append(f"{name}_seconds{labels_str} {info[metric]:.6f}")

    # gauges
        for name, value in stats.get("gauges", {}).items():
            lines.append(f"# TYPE {name} gauge")
            lines.append(f"{name} {value}")

        return "\n".join(lines)

    def _parse_key(self, key: str):
        """解析指标 key"""
        if "{" in key:
            name, label_str = key.split("{", 1)
            label_str = label_str.rstrip("}")
            labels = {}
            if label_str:
                for pair in label_str.split(","):
                    k, v = pair.split("=")
                    labels[k] = v
            return name, labels
        return key, {}

    def _format_labels(self, labels: Dict[str, Any]) -> str:
        """格式化 labels"""
        if not labels:
            return ""
        parts = [f'{k}="{v}"' for k, v in sorted(labels.items())]
        return "{" + ",".join(parts) + "}"

    def reset(self) -> None:
        """重置所有指标"""
        with self._lock:
            self._counters.clear()
            self._latencies.clear()
            self._errors.clear()
            self._tokens.clear()
            self._gauges.clear()

    # ========== 兼容旧版 API（http_server.py 使用） ==========
    def set_sessions_count(self, count: int) -> None:
        """设置当前会话数（兼容旧版 API，gauge 类型）"""
        with self._lock:
            self._gauges["sessions_count"] = float(count)

    def set_long_term_count(self, count: int) -> None:
        """设置长期记忆条目数（兼容旧版 API，gauge 类型）"""
        with self._lock:
            self._gauges["long_term_count"] = float(count)

    def generate_prometheus_output(self) -> str:
        """生成 Prometheus 格式输出（兼容旧版 API）"""
        return self.export_prometheus()


# 全局单例
_global_metrics: Optional[MetricsCollector] = None
_global_metrics_lock = threading.Lock()



def set_metrics(instance: MetricsCollector) -> None:
    """手动设置全局 MetricsCollector 实例（Agent 初始化时调用，确保配置生效）"""
    global _global_metrics
    with _global_metrics_lock:
        _global_metrics = instance

def get_metrics() -> MetricsCollector:
    """获取全局指标收集器"""
    global _global_metrics
    if _global_metrics is None:
        with _global_metrics_lock:
            if _global_metrics is None:
                _global_metrics = MetricsCollector()
    return _global_metrics


# 向后兼容别名（http_server.py 仍使用旧名称）
def get_metrics_collector() -> "MetricsCollector":
    """向后兼容别名"""
    return get_metrics()


class Timer:
    """上下文管理器：自动记录耗时"""

    def __init__(self, name: str, **labels):
        self.name = name
        self.labels = labels
        self.start = 0.0

    def __enter__(self):
        self.start = time.time()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        duration = time.time() - self.start
        metrics = get_metrics()
        metrics.record_latency(self.name, duration, **self.labels)
        if exc_type is not None:
            metrics.inc_error(self.name, **self.labels)
