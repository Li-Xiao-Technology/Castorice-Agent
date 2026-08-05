"""
P1-2: 数据库定期维护脚本

功能：
- VACUUM：压缩数据库，回收空闲空间
- WAL checkpoint：将 WAL 文件合并入主数据库
- 冷数据归档：将超过 N 天的经历流移到归档数据库
- 索引重建：REINDEX 修复碎片化索引
- 一致性检查：PRAGMA integrity_check

使用方式：
    # 命令行
    python -m castorice.db_maintenance --vacuum --archive --days 30

    # 代码调用
    from castorice.db_maintenance import DatabaseMaintainer
    m = DatabaseMaintainer(data_dir="./castorice_data")
    m.run_all()
"""
import argparse
import json
import logging
import os
import shutil
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Castorice.DBMaint")


@dataclass
class MaintenanceResult:
    """单次维护结果"""
    task: str
    success: bool
    message: str = ""
    details: Dict[str, Any] = field(default_factory=dict)
    duration_seconds: float = 0.0


class DatabaseMaintainer:
    """
    SQLite 数据库维护器

    支持：VACUUM、WAL checkpoint、冷数据归档、索引重建、一致性检查
    """

    # 需要维护的数据库列表
    DB_FILES = [
        "experiences.db",
        "autobiographical.db",
        "intent_tracker.db",
        "metacognition.db",
        "tool_learning.db",
        "sessions.db",
        "action_queue.db",
        "social_relations.db",
        "motivation.db",
        "values.db",
    ]

    def __init__(self, data_dir: Optional[str] = None):
        if data_dir is None:
            data_dir = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "..", "castorice_data"
            )
        self.data_dir = Path(data_dir).resolve()
        self.archive_dir = self.data_dir / "archive"
        self.archive_dir.mkdir(exist_ok=True)

        logger.info(f"数据库维护器初始化: data_dir={self.data_dir}")

    # ============== 单个维护任务 ==============

    def wal_checkpoint(self, db_name: str) -> MaintenanceResult:
        """WAL checkpoint：将 WAL 文件合并入主数据库"""
        start = time.time()
        db_path = self.data_dir / db_name
        if not db_path.exists():
            return MaintenanceResult("wal_checkpoint", True, f"{db_name} 不存在，跳过")

        try:
            before_wal = db_path.with_suffix(db_path.suffix + "-wal")
            before_size = before_wal.stat().st_size if before_wal.exists() else 0

            conn = sqlite3.connect(str(db_path), timeout=30)
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            conn.close()

            after_size = before_wal.stat().st_size if before_wal.exists() else 0
            freed = before_size - after_size

            return MaintenanceResult(
                "wal_checkpoint", True,
                f"{db_name} WAL checkpoint 完成，释放 {freed/1024:.1f}KB",
                {"db": db_name, "freed_bytes": freed, "before_wal_size": before_size},
                time.time() - start,
            )
        except Exception as e:
            return MaintenanceResult(
                "wal_checkpoint", False,
                f"{db_name} WAL checkpoint 失败: {e}",
                {"db": db_name},
                time.time() - start,
            )

    def vacuum(self, db_name: str) -> MaintenanceResult:
        """VACUUM：压缩数据库，回收空闲空间"""
        start = time.time()
        db_path = self.data_dir / db_name
        if not db_path.exists():
            return MaintenanceResult("vacuum", True, f"{db_name} 不存在，跳过")

        try:
            before_size = db_path.stat().st_size

            conn = sqlite3.connect(str(db_path), timeout=120)
            conn.execute("VACUUM")
            conn.close()

            after_size = db_path.stat().st_size
            freed = before_size - after_size

            return MaintenanceResult(
                "vacuum", True,
                f"{db_name} VACUUM 完成，释放 {freed/1024/1024:.2f}MB "
                f"({before_size/1024/1024:.2f}MB -> {after_size/1024/1024:.2f}MB)",
                {"db": db_name, "freed_bytes": freed, "before_mb": before_size/1024/1024, "after_mb": after_size/1024/1024},
                time.time() - start,
            )
        except Exception as e:
            return MaintenanceResult(
                "vacuum", False,
                f"{db_name} VACUUM 失败: {e}",
                {"db": db_name},
                time.time() - start,
            )

    def reindex(self, db_name: str) -> MaintenanceResult:
        """REINDEX：重建索引，修复碎片化"""
        start = time.time()
        db_path = self.data_dir / db_name
        if not db_path.exists():
            return MaintenanceResult("reindex", True, f"{db_name} 不存在，跳过")

        try:
            conn = sqlite3.connect(str(db_path), timeout=120)
            conn.execute("REINDEX")
            conn.close()

            return MaintenanceResult(
                "reindex", True,
                f"{db_name} 索引重建完成",
                {"db": db_name},
                time.time() - start,
            )
        except Exception as e:
            return MaintenanceResult(
                "reindex", False,
                f"{db_name} 索引重建失败: {e}",
                {"db": db_name},
                time.time() - start,
            )

    def integrity_check(self, db_name: str) -> MaintenanceResult:
        """一致性检查：检测数据库损坏"""
        start = time.time()
        db_path = self.data_dir / db_name
        if not db_path.exists():
            return MaintenanceResult("integrity_check", True, f"{db_name} 不存在，跳过")

        try:
            conn = sqlite3.connect(str(db_path), timeout=30)
            cursor = conn.execute("PRAGMA integrity_check")
            result = cursor.fetchone()[0]
            conn.close()

            ok = result == "ok"
            return MaintenanceResult(
                "integrity_check", ok,
                f"{db_name} 完整性检查: {result}",
                {"db": db_name, "result": result},
                time.time() - start,
            )
        except Exception as e:
            return MaintenanceResult(
                "integrity_check", False,
                f"{db_name} 完整性检查失败: {e}",
                {"db": db_name},
                time.time() - start,
            )

    def archive_old_data(self, days: int = 30) -> MaintenanceResult:
        """
        冷数据归档：将超过 N 天的经历流移到归档数据库

        归档后的数据库命名为: experiences_archive_YYYYMM.db
        """
        start = time.time()
        db_path = self.data_dir / "experiences.db"
        if not db_path.exists():
            return MaintenanceResult("archive", True, "experiences.db 不存在，跳过")

        cutoff_ts = (datetime.now() - timedelta(days=days)).timestamp() * 1000

        try:
            conn = sqlite3.connect(str(db_path), timeout=60)

            # 统计可归档数量
            cursor = conn.execute(
                "SELECT COUNT(*) FROM experiences WHERE timestamp < ?",
                (cutoff_ts,)
            )
            count = cursor.fetchone()[0]

            if count == 0:
                conn.close()
                return MaintenanceResult(
                    "archive", True,
                    f"没有超过 {days} 天的经历需要归档",
                    {"days": days, "archived_count": 0},
                    time.time() - start,
                )

            # 创建归档数据库
            archive_name = f"experiences_archive_{datetime.now().strftime('%Y%m')}.db"
            archive_path = self.archive_dir / archive_name

            # 从主库复制数据到归档库
            # 1. 附加归档数据库
            conn.execute(f"ATTACH DATABASE '{archive_path}' AS archive")
            # 2. 创建表结构（如果不存在）
            conn.execute("""
                CREATE TABLE IF NOT EXISTS archive.experiences (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp INTEGER,
                    session_id TEXT,
                    memory_type TEXT,
                    content TEXT,
                    importance REAL,
                    metadata TEXT
                )
            """)
            # 3. 复制数据
            conn.execute("""
                INSERT INTO archive.experiences
                (timestamp, session_id, memory_type, content, importance, metadata)
                SELECT timestamp, session_id, memory_type, content, importance, metadata
                FROM experiences WHERE timestamp < ?
            """, (cutoff_ts,))
            # 4. 从主库删除
            conn.execute("DELETE FROM experiences WHERE timestamp < ?", (cutoff_ts,))
            conn.commit()
            conn.execute("DETACH DATABASE archive")
            conn.close()

            return MaintenanceResult(
                "archive", True,
                f"已归档 {count} 条超过 {days} 天的经历到 {archive_name}",
                {"days": days, "archived_count": count, "archive_file": archive_name},
                time.time() - start,
            )
        except Exception as e:
            return MaintenanceResult(
                "archive", False,
                f"归档失败: {e}",
                {"days": days},
                time.time() - start,
            )

    # ============== 批量执行 ==============

    def run_all(
        self,
        do_wal: bool = True,
        do_vacuum: bool = True,
        do_reindex: bool = False,
        do_integrity: bool = True,
        do_archive: bool = True,
        archive_days: int = 30,
    ) -> List[MaintenanceResult]:
        """
        执行全部维护任务

        默认：WAL checkpoint + 完整性检查 + 归档
        VACUUM 和 REINDEX 比较耗时，默认按需开启
        """
        results: List[MaintenanceResult] = []

        logger.info("=" * 60)
        logger.info("开始数据库维护")
        logger.info("=" * 60)

        for db_name in self.DB_FILES:
            if do_wal:
                r = self.wal_checkpoint(db_name)
                results.append(r)
                self._log_result(r)

            if do_integrity:
                r = self.integrity_check(db_name)
                results.append(r)
                self._log_result(r)

            if do_vacuum:
                r = self.vacuum(db_name)
                results.append(r)
                self._log_result(r)

            if do_reindex:
                r = self.reindex(db_name)
                results.append(r)
                self._log_result(r)

        if do_archive:
            r = self.archive_old_data(archive_days)
            results.append(r)
            self._log_result(r)

        # 汇总
        success = sum(1 for r in results if r.success)
        total = len(results)
        total_time = sum(r.duration_seconds for r in results)

        logger.info("=" * 60)
        logger.info(f"维护完成: {success}/{total} 成功，总耗时 {total_time:.1f}s")
        logger.info("=" * 60)

        return results

    def _log_result(self, r: MaintenanceResult) -> None:
        status = "✅" if r.success else "❌"
        logger.info(f"{status} {r.task:20s} | {r.duration_seconds:6.1f}s | {r.message}")


# ============== 命令行入口 ==============

def main():
    parser = argparse.ArgumentParser(description="Castorice 数据库维护工具")
    parser.add_argument("--data-dir", type=str, default=None, help="数据目录路径")
    parser.add_argument("--wal", action="store_true", default=True, help="执行 WAL checkpoint（默认开启）")
    parser.add_argument("--vacuum", action="store_true", help="执行 VACUUM（比较耗时）")
    parser.add_argument("--reindex", action="store_true", help="执行 REINDEX（比较耗时）")
    parser.add_argument("--no-integrity", action="store_true", help="跳过完整性检查")
    parser.add_argument("--no-archive", action="store_true", help="跳过冷数据归档")
    parser.add_argument("--archive-days", type=int, default=30, help="归档超过多少天的经历（默认 30 天）")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    m = DatabaseMaintainer(args.data_dir)
    results = m.run_all(
        do_wal=args.wal,
        do_vacuum=args.vacuum,
        do_reindex=args.reindex,
        do_integrity=not args.no_integrity,
        do_archive=not args.no_archive,
        archive_days=args.archive_days,
    )

    # 非零退出码表示有失败
    failures = [r for r in results if not r.success]
    return 0 if not failures else 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
