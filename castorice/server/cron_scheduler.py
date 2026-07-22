"""
CronScheduler - 定时任务调度器

执行定期任务，如自我反思、记忆清理等。
"""
import logging
import threading
import time


class CronScheduler:
    """定时任务调度器"""

    def __init__(self, engine):
        self.engine = engine
        self.logger = logging.getLogger("Castorice.Cron")
        self._running = False
        self._thread = None
        self._ready = False
        self._error = None
        self._reflect_interval = 3600
        self._cleanup_interval = 86400

    def is_running(self) -> bool:
        """检查调度器是否正在运行"""
        return self._running and self._ready

    def get_status_info(self) -> dict:
        """获取状态详情"""
        return {
            "running": self._running,
            "ready": self._ready,
            "error": self._error,
            "reflect_interval": self._reflect_interval,
            "cleanup_interval": self._cleanup_interval,
        }

    def run(self) -> None:
        """启动定时任务调度器（阻塞模式，由调用方在后台线程中运行）"""
        self._running = True
        try:
            cron_cfg = self.engine.config.cron if hasattr(self.engine.config, "cron") else {}
            if isinstance(cron_cfg, dict):
                self._reflect_interval = int(cron_cfg.get("reflect_interval", 3600))
                self._cleanup_interval = int(cron_cfg.get("cleanup_interval", 86400))

            self._ready = True
            self.logger.info("═══════════════════════════════════════")
            self.logger.info("  定时任务调度器已启动")
            self.logger.info(f"  反思间隔: {self._reflect_interval}s ({self._reflect_interval // 60}分钟)")
            self.logger.info(f"  清理间隔: {self._cleanup_interval}s ({self._cleanup_interval // 3600}小时)")
            self.logger.info("═══════════════════════════════════════")
            self._run_loop()
        except Exception as e:
            self._error = str(e)
            self.logger.error(f"启动定时任务调度器失败: {e}")
        finally:
            self._running = False
            self._ready = False

    def _run_loop(self) -> None:
        """定时任务主循环"""
        last_reflect_time = 0
        last_cleanup_time = 0

        while self._running:
            try:
                current_time = time.time()

                if current_time - last_reflect_time >= self._reflect_interval:
                    self._run_periodic_reflection()
                    last_reflect_time = current_time

                if current_time - last_cleanup_time >= self._cleanup_interval:
                    self._run_daily_cleanup()
                    last_cleanup_time = current_time

                time.sleep(60)
            except Exception as e:
                self.logger.error(f"定时任务执行失败: {e}")

    def _run_periodic_reflection(self) -> None:
        """执行定期自我反思"""
        try:
            engine = getattr(self.engine.agent, "reflection_engine", None)
            if engine:
                import asyncio
                result = asyncio.run(engine.reflect(trigger_reason="定时触发"))
                if result.self_concept_updated:
                    self.logger.info(f"定时反思完成，自我概念已更新")
                else:
                    self.logger.info("定时反思完成")
        except Exception as e:
            self.logger.error(f"定期反思失败: {e}")

    def _run_daily_cleanup(self) -> None:
        """执行每日清理任务"""
        try:
            self.logger.info("执行每日清理任务...")
            self.engine.short_term.cleanup_old_sessions(days=30)
            self.engine.long_term.cleanup_old_records(days=90)
            self.logger.info("每日清理完成")
        except Exception as e:
            self.logger.error(f"每日清理失败: {e}")

    def stop(self) -> None:
        """停止定时任务调度器"""
        self._running = False
        self.logger.info("定时任务调度器已停止")