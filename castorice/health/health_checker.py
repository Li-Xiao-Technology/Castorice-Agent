"""
P0-1: 健康检查器 (HealthChecker)

定期巡检各子系统的健康状态，提供统一的 /health 接口。

检查项：
- llm:            LLM 服务连通性（轻量 /v1/models 探测）
- database:       SQLite 数据库读写
- memory:         记忆系统（向量库 / 长期记忆）
- eigenflux:      EigenFlux 网络连通性
- system:         内存、磁盘、CPU
- cost_budget:    成本预算状态

使用方式：
    hc = HealthChecker(engine=engine)
    hc.start()   # 后台线程定期巡检
    status = hc.get_overall_status()
"""
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("Castorice.HealthChecker")


@dataclass
class CheckResult:
    """单次检查结果"""
    name: str
    healthy: bool
    message: str = ""
    details: Dict[str, Any] = field(default_factory=dict)
    latency_ms: float = 0.0
    timestamp: float = field(default_factory=time.time)


class HealthChecker:
    """
    健康检查器

    - 后台线程定期巡检（默认每 30 秒一次）
    - 每次检查有独立超时（默认 5 秒），避免慢检查阻塞
    - 结果缓存，HTTP API 直接读缓存，<10ms 返回
    """

    def __init__(
        self,
        engine: Any = None,
        check_interval: float = 30.0,
        check_timeout: float = 5.0,
    ):
        self.engine = engine
        self.check_interval = check_interval
        self.check_timeout = check_timeout

        self._lock = threading.RLock()
        self._results: Dict[str, CheckResult] = {}
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

        # 注册内置检查项
        self._checks: Dict[str, Callable[[], CheckResult]] = {}
        self._register_builtin_checks()

    # ============== 检查项注册 ==============

    def register_check(self, name: str, check_fn: Callable[[], CheckResult]) -> None:
        """注册自定义检查项"""
        self._checks[name] = check_fn
        logger.info(f"健康检查: 注册检查项 [{name}]")

    def _register_builtin_checks(self) -> None:
        """注册内置检查项"""
        self.register_check("system", self._check_system)
        self.register_check("llm", self._check_llm)
        self.register_check("database", self._check_database)
        self.register_check("memory", self._check_memory)
        self.register_check("emotion", self._check_emotion)
        self.register_check("self_concept", self._check_self_concept)
        self.register_check("consciousness", self._check_consciousness)
        self.register_check("motivation", self._check_motivation)
        self.register_check("cost_budget", self._check_cost_budget)
        self.register_check("continuous_learning", self._check_continuous_learning)
        self.register_check("mcp", self._check_mcp)
        self.register_check("qq_bot", self._check_qq_bot)
        self.register_check("telegram_bot", self._check_telegram_bot)
        self.register_check("eigenflux", self._check_eigenflux)

    # ============== 内置检查项 ==============

    def _check_system(self) -> CheckResult:
        """系统资源检查（内存、磁盘）"""
        start = time.time()
        try:
            import psutil
            mem = psutil.virtual_memory()
            disk = psutil.disk_usage(os.path.dirname(os.path.abspath(__file__)) + "/..")

            details = {
                "memory_percent": mem.percent,
                "memory_available_mb": round(mem.available / 1024 / 1024, 1),
                "disk_percent": disk.percent,
                "disk_free_gb": round(disk.free / 1024 / 1024 / 1024, 2),
            }

            healthy = True
            warnings = []
            if mem.percent > 90:
                healthy = False
                warnings.append(f"内存使用率过高: {mem.percent:.0f}%")
            if disk.percent > 90:
                healthy = False
                warnings.append(f"磁盘使用率过高: {disk.percent:.0f}%")

            return CheckResult(
                name="system",
                healthy=healthy,
                message="; ".join(warnings) if warnings else "系统资源正常",
                details=details,
                latency_ms=(time.time() - start) * 1000,
            )
        except ImportError:
            return CheckResult(
                name="system",
                healthy=True,
                message="psutil 未安装，跳过系统资源检查",
                latency_ms=(time.time() - start) * 1000,
            )
        except Exception as e:
            return CheckResult(
                name="system",
                healthy=False,
                message=f"系统检查失败: {e}",
                latency_ms=(time.time() - start) * 1000,
            )

    def _check_llm(self) -> CheckResult:
        """LLM 服务连通性检查"""
        start = time.time()
        try:
            model_adapter = getattr(self.engine, 'model_adapter', None)
            if model_adapter is None:
                return CheckResult(
                    name="llm",
                    healthy=False,
                    message="ModelAdapter 未初始化",
                    latency_ms=(time.time() - start) * 1000,
                )

            provider = getattr(model_adapter, 'provider', 'unknown')
            cfg = getattr(model_adapter, f'{provider}_cfg', {}) or {}
            base_url = cfg.get('base_url', '')

            if not base_url:
                return CheckResult(
                    name="llm",
                    healthy=False,
                    message=f"Provider {provider} 未配置 base_url",
                    latency_ms=(time.time() - start) * 1000,
                )

            # 轻量探测：访问 /v1/models
            import httpx
            models_url = base_url.rstrip('/') + '/models'
            api_key = cfg.get('api_key', '')
            headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}

            with httpx.Client(timeout=self.check_timeout) as client:
                r = client.get(models_url, headers=headers)

            details = {
                "provider": provider,
                "base_url": base_url,
                "status_code": r.status_code,
            }

            if r.status_code == 200:
                return CheckResult(
                    name="llm",
                    healthy=True,
                    message=f"LLM ({provider}) 连接正常",
                    details=details,
                    latency_ms=(time.time() - start) * 1000,
                )
            elif r.status_code == 401:
                return CheckResult(
                    name="llm",
                    healthy=False,
                    message=f"LLM ({provider}) 认证失败 (401)，请检查 API Key",
                    details=details,
                    latency_ms=(time.time() - start) * 1000,
                )
            else:
                return CheckResult(
                    name="llm",
                    healthy=False,
                    message=f"LLM ({provider}) 返回异常: HTTP {r.status_code}",
                    details=details,
                    latency_ms=(time.time() - start) * 1000,
                )
        except Exception as e:
            return CheckResult(
                name="llm",
                healthy=False,
                message=f"LLM 连接失败: {type(e).__name__}: {e}",
                latency_ms=(time.time() - start) * 1000,
            )

    def _check_database(self) -> CheckResult:
        """SQLite 数据库检查"""
        start = time.time()
        try:
            # 检查 experiences.db 是否可读写
            data_dir = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "..", "castorice_data"
            )
            db_path = os.path.join(data_dir, "experiences.db")

            if not os.path.exists(db_path):
                return CheckResult(
                    name="database",
                    healthy=True,
                    message="数据库文件不存在（首次运行正常）",
                    latency_ms=(time.time() - start) * 1000,
                )

            import sqlite3
            conn = sqlite3.connect(db_path, timeout=2.0)
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'")
            table_count = cursor.fetchone()[0]
            cursor.execute("PRAGMA journal_mode")
            journal_mode = cursor.fetchone()[0]
            conn.close()

            file_size_mb = round(os.path.getsize(db_path) / 1024 / 1024, 2)

            return CheckResult(
                name="database",
                healthy=True,
                message=f"数据库正常，{table_count} 个表，{file_size_mb}MB",
                details={
                    "table_count": table_count,
                    "file_size_mb": file_size_mb,
                    "journal_mode": journal_mode,
                },
                latency_ms=(time.time() - start) * 1000,
            )
        except Exception as e:
            return CheckResult(
                name="database",
                healthy=False,
                message=f"数据库检查失败: {e}",
                latency_ms=(time.time() - start) * 1000,
            )

    def _check_eigenflux(self) -> CheckResult:
        """EigenFlux 网络连通性"""
        start = time.time()
        try:
            from castorice.tools.eigenflux_tool import _run_cli_sync

            code, stdout, stderr = _run_cli_sync([
                "status", "--format", "json", "--no-interactive",
            ], timeout=self.check_timeout)

            details = {"exit_code": code}
            if code == 0:
                return CheckResult(
                    name="eigenflux",
                    healthy=True,
                    message="EigenFlux 连接正常",
                    details=details,
                    latency_ms=(time.time() - start) * 1000,
                )
            else:
                return CheckResult(
                    name="eigenflux",
                    healthy=False,
                    message=f"EigenFlux 未连接: {stderr[:100] or '未登录'}",
                    details={**details, "stderr": stderr[:200]},
                    latency_ms=(time.time() - start) * 1000,
                )
        except Exception as e:
            return CheckResult(
                name="eigenflux",
                healthy=False,
                message=f"EigenFlux 检查失败: {e}",
                latency_ms=(time.time() - start) * 1000,
            )

    def _check_memory(self) -> CheckResult:
        """记忆系统检查（短时 + 长时）"""
        start = time.time()
        try:
            stm = getattr(self.engine, 'short_term', None)
            ltm = getattr(self.engine, 'long_term', None)
            details = {}
            warnings = []

            if stm is not None and hasattr(stm, 'list_sessions'):
                try:
                    sessions = stm.list_sessions(limit=5)
                    details["short_term_sessions"] = len(sessions) if sessions else 0
                except Exception as e:
                    warnings.append(f"短时记忆异常: {e}")

            if ltm is not None and hasattr(ltm, 'is_available'):
                try:
                    available = ltm.is_available()
                    details["long_term_available"] = available
                    if not available:
                        warnings.append("长时记忆未启用")
                except Exception as e:
                    warnings.append(f"长时记忆异常: {e}")

            healthy = len(warnings) == 0
            return CheckResult(
                name="memory",
                healthy=healthy,
                message="; ".join(warnings) if warnings else "记忆系统正常",
                details=details,
                latency_ms=(time.time() - start) * 1000,
            )
        except Exception as e:
            return CheckResult(
                name="memory",
                healthy=False,
                message=f"记忆检查失败: {e}",
                latency_ms=(time.time() - start) * 1000,
            )

    def _check_emotion(self) -> CheckResult:
        """情感系统检查"""
        start = time.time()
        try:
            emotion = getattr(self.engine, 'emotion', None)
            if emotion is None:
                return CheckResult(
                    name="emotion",
                    healthy=True,
                    message="情感模块未加载（可选）",
                    latency_ms=(time.time() - start) * 1000,
                )
            pad = getattr(emotion, 'pad', None)
            details = {}
            if pad is not None:
                details = {
                    "pleasure": round(getattr(pad, 'pleasure', 0), 2),
                    "arousal": round(getattr(pad, 'arousal', 0), 2),
                    "dominance": round(getattr(pad, 'dominance', 0), 2),
                }
            return CheckResult(
                name="emotion",
                healthy=True,
                message="情感系统正常",
                details=details,
                latency_ms=(time.time() - start) * 1000,
            )
        except Exception as e:
            return CheckResult(
                name="emotion",
                healthy=False,
                message=f"情感检查失败: {e}",
                latency_ms=(time.time() - start) * 1000,
            )

    def _check_self_concept(self) -> CheckResult:
        """自我概念检查"""
        start = time.time()
        try:
            sc = getattr(self.engine, 'self_concept', None)
            if sc is None:
                return CheckResult(
                    name="self_concept",
                    healthy=True,
                    message="自我概念模块未加载（可选）",
                    latency_ms=(time.time() - start) * 1000,
                )
            details = {}
            if hasattr(sc, 'get_summary'):
                try:
                    summary = sc.get_summary()
                    if summary:
                        details["summary_length"] = len(summary)
                except Exception:
                    pass
            return CheckResult(
                name="self_concept",
                healthy=True,
                message="自我概念正常",
                details=details,
                latency_ms=(time.time() - start) * 1000,
            )
        except Exception as e:
            return CheckResult(
                name="self_concept",
                healthy=False,
                message=f"自我概念检查失败: {e}",
                latency_ms=(time.time() - start) * 1000,
            )

    def _check_consciousness(self) -> CheckResult:
        """意识流检查"""
        start = time.time()
        try:
            consciousness = getattr(self.engine, 'consciousness', None)
            if consciousness is None:
                return CheckResult(
                    name="consciousness",
                    healthy=True,
                    message="意识流模块未加载（可选）",
                    latency_ms=(time.time() - start) * 1000,
                )
            details = {}
            if hasattr(consciousness, 'thought_stream'):
                ts = consciousness.thought_stream
                details["thought_count"] = len(getattr(ts, 'thoughts', [])) if ts else 0
                details["running"] = bool(getattr(ts, '_running', False))
            return CheckResult(
                name="consciousness",
                healthy=True,
                message="意识流正常",
                details=details,
                latency_ms=(time.time() - start) * 1000,
            )
        except Exception as e:
            return CheckResult(
                name="consciousness",
                healthy=False,
                message=f"意识流检查失败: {e}",
                latency_ms=(time.time() - start) * 1000,
            )

    def _check_motivation(self) -> CheckResult:
        """动机系统检查"""
        start = time.time()
        try:
            motivation = getattr(self.engine, 'motivation', None)
            if motivation is None:
                return CheckResult(
                    name="motivation",
                    healthy=True,
                    message="动机模块未加载（可选）",
                    latency_ms=(time.time() - start) * 1000,
                )
            return CheckResult(
                name="motivation",
                healthy=True,
                message="动机系统正常",
                latency_ms=(time.time() - start) * 1000,
            )
        except Exception as e:
            return CheckResult(
                name="motivation",
                healthy=False,
                message=f"动机检查失败: {e}",
                latency_ms=(time.time() - start) * 1000,
            )

    def _check_cost_budget(self) -> CheckResult:
        """成本预算检查"""
        start = time.time()
        try:
            cb = getattr(self.engine, 'cost_budget', None)
            if cb is None:
                return CheckResult(
                    name="cost_budget",
                    healthy=True,
                    message="成本闸未启用（可选）",
                    latency_ms=(time.time() - start) * 1000,
                )
            details = {}
            if hasattr(cb, 'get_status'):
                status = cb.get_status()
                details = status if isinstance(status, dict) else {}
            enabled = getattr(cb, 'enabled', True)
            return CheckResult(
                name="cost_budget",
                healthy=True,
                message=f"成本闸{'已启用' if enabled else '已关闭'}",
                details=details,
                latency_ms=(time.time() - start) * 1000,
            )
        except Exception as e:
            return CheckResult(
                name="cost_budget",
                healthy=False,
                message=f"成本闸检查失败: {e}",
                latency_ms=(time.time() - start) * 1000,
            )

    def _check_continuous_learning(self) -> CheckResult:
        """持续学习检查"""
        start = time.time()
        try:
            cl = getattr(self.engine, 'continuous_learning', None)
            if cl is None:
                return CheckResult(
                    name="continuous_learning",
                    healthy=True,
                    message="持续学习模块未加载（可选）",
                    latency_ms=(time.time() - start) * 1000,
                )
            details = {}
            if hasattr(cl, 'get_status'):
                try:
                    status = cl.get_status()
                    if isinstance(status, dict):
                        details = {
                            "is_sleeping": status.get("is_sleeping", False),
                            "is_distilling": status.get("is_distilling", False),
                            "interaction_count": status.get("interaction_count", 0),
                        }
                except Exception:
                    pass
            return CheckResult(
                name="continuous_learning",
                healthy=True,
                message="持续学习正常",
                details=details,
                latency_ms=(time.time() - start) * 1000,
            )
        except Exception as e:
            return CheckResult(
                name="continuous_learning",
                healthy=False,
                message=f"持续学习检查失败: {e}",
                latency_ms=(time.time() - start) * 1000,
            )

    def _check_mcp(self) -> CheckResult:
        """MCP 客户端检查"""
        start = time.time()
        try:
            mcp = getattr(self.engine, 'mcp_client', None)
            if mcp is None:
                return CheckResult(
                    name="mcp",
                    healthy=True,
                    message="MCP 客户端未初始化（可选）",
                    latency_ms=(time.time() - start) * 1000,
                )
            servers = mcp.list_servers() if hasattr(mcp, 'list_servers') else []
            running_count = sum(1 for s in servers if s.get("running"))
            details = {
                "total_servers": len(servers),
                "running_servers": running_count,
            }
            return CheckResult(
                name="mcp",
                healthy=True,
                message=f"MCP: {running_count}/{len(servers)} 个服务器运行中",
                details=details,
                latency_ms=(time.time() - start) * 1000,
            )
        except Exception as e:
            return CheckResult(
                name="mcp",
                healthy=False,
                message=f"MCP 检查失败: {e}",
                latency_ms=(time.time() - start) * 1000,
            )

    def _check_qq_bot(self) -> CheckResult:
        """QQ 机器人检查"""
        start = time.time()
        try:
            bg = getattr(self.engine, '_bg_services', {}) or {}
            qq = bg.get('qq')
            if qq is None:
                return CheckResult(
                    name="qq_bot",
                    healthy=True,
                    message="QQ 机器人未启动（可选）",
                    latency_ms=(time.time() - start) * 1000,
                )
            running = bool(getattr(qq, '_running', False))
            return CheckResult(
                name="qq_bot",
                healthy=True,
                message=f"QQ 机器人{'运行中' if running else '已停止'}",
                details={"running": running},
                latency_ms=(time.time() - start) * 1000,
            )
        except Exception as e:
            return CheckResult(
                name="qq_bot",
                healthy=False,
                message=f"QQ 机器人检查失败: {e}",
                latency_ms=(time.time() - start) * 1000,
            )

    def _check_telegram_bot(self) -> CheckResult:
        """Telegram 机器人检查"""
        start = time.time()
        try:
            bg = getattr(self.engine, '_bg_services', {}) or {}
            tg = bg.get('telegram')
            if tg is None:
                return CheckResult(
                    name="telegram_bot",
                    healthy=True,
                    message="Telegram 机器人未启动（可选）",
                    latency_ms=(time.time() - start) * 1000,
                )
            running = bool(getattr(tg, '_running', False))
            return CheckResult(
                name="telegram_bot",
                healthy=True,
                message=f"Telegram 机器人{'运行中' if running else '已停止'}",
                details={"running": running},
                latency_ms=(time.time() - start) * 1000,
            )
        except Exception as e:
            return CheckResult(
                name="telegram_bot",
                healthy=False,
                message=f"Telegram 机器人检查失败: {e}",
                latency_ms=(time.time() - start) * 1000,
            )

    # ============== 巡检循环 ==============

    def start(self) -> None:
        """启动后台巡检线程"""
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop,
            name="HealthChecker",
            daemon=True,
        )
        self._thread.start()
        logger.info(f"健康检查器已启动，巡检间隔 {self.check_interval}s")

    def stop(self) -> None:
        """停止后台巡检"""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5.0)
        logger.info("健康检查器已停止")

    def _run_loop(self) -> None:
        """后台巡检循环"""
        # 启动时立刻跑一次
        self._run_all_checks()

        while not self._stop_event.is_set():
            try:
                self._stop_event.wait(self.check_interval)
                if not self._stop_event.is_set():
                    self._run_all_checks()
            except Exception as e:
                logger.error(f"健康检查循环异常: {e}")

    def _run_all_checks(self) -> None:
        """（内部）执行所有检查项，带超时保护"""
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(
            max_workers=len(self._checks) or 1,
            thread_name_prefix="HealthCheck",
        ) as executor:
            future_to_name = {}
            for name, fn in self._checks.items():
                future = executor.submit(self._safe_check, name, fn)
                future_to_name[future] = name

            for future in concurrent.futures.as_completed(future_to_name):
                name = future_to_name[future]
                try:
                    result = future.result(timeout=self.check_timeout + 1)
                except concurrent.futures.TimeoutError:
                    result = CheckResult(
                        name=name,
                        healthy=False,
                        message=f"检查超时 (>{self.check_timeout}s)",
                    )
                except Exception as e:
                    result = CheckResult(
                        name=name,
                        healthy=False,
                        message=f"检查异常: {type(e).__name__}: {e}",
                    )

                with self._lock:
                    self._results[name] = result

    def _safe_check(self, name: str, fn: Callable) -> CheckResult:
        """安全执行单个检查（捕获所有异常）"""
        try:
            return fn()
        except Exception as e:
            return CheckResult(
                name=name,
                healthy=False,
                message=f"{type(e).__name__}: {e}",
            )

    # ============== 状态查询 ==============

    def run_once(self) -> Dict[str, Any]:
        """立刻执行一次完整检查并返回结果（阻塞调用）"""
        self._run_all_checks()
        return self.get_overall_status()

    def get_overall_status(self) -> Dict[str, Any]:
        """获取整体健康状态（读缓存，<10ms）"""
        with self._lock:
            results = dict(self._results)
            registered_names = list(self._checks.keys())

        all_checks = []
        healthy_count = 0
        total_count = len(registered_names)

        for name in registered_names:
            result = results.get(name)
            if result is not None:
                check_data = {
                    "name": result.name,
                    "healthy": result.healthy,
                    "message": result.message,
                    "details": result.details,
                    "latency_ms": round(result.latency_ms, 1),
                    "timestamp": result.timestamp,
                }
                if result.healthy:
                    healthy_count += 1
            else:
                check_data = {
                    "name": name,
                    "healthy": False,
                    "message": "检测中...",
                    "details": {},
                    "latency_ms": 0,
                    "timestamp": time.time(),
                    "pending": True,
                }
            all_checks.append(check_data)

        completed_count = len(results)
        if completed_count == 0:
            overall = "unknown"
        elif healthy_count == total_count:
            overall = "healthy"
        elif healthy_count > 0:
            overall = "degraded"
        else:
            overall = "unhealthy"

        return {
            "overall": overall,
            "healthy_count": healthy_count,
            "total_count": total_count,
            "checks": all_checks,
            "timestamp": time.time(),
        }
