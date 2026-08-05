"""
P3: 持续学习管理器 (Continuous Learning Manager)

包含：
- SleepMechanism: 睡眠机制 —— 空闲时压缩记忆、合并相似经历
- ContinuousLearningManager: 定时调度蒸馏与睡眠

参考：
- Generative Agents (Stanford, 2023) — 睡眠时压缩记忆
- Sleep-like Memory Consolidation in AI Systems
"""

import json
import logging
import os
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("Castorice.ContinuousLearning")


# ============================================================
# 睡眠机制 (SleepMechanism)
# ============================================================

@dataclass
class SleepReport:
    """一次睡眠的报告"""
    started_at: str = ""
    ended_at: str = ""
    duration_seconds: float = 0.0
    experiences_merged: int = 0
    memories_compressed: int = 0
    epochs_created: int = 0
    cards_distilled: int = 0
    details: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class SleepMechanism:
    """
    睡眠机制 —— 在 Agent 空闲时进行记忆巩固

    功能：
    1. 相似经历合并：内容相似的经历合并为一条摘要
    2. 低重要性记忆压缩：不重要的经历摘要化，释放空间
    3. 时期总结：自动划分人生时期并生成总结
    4. 知识蒸馏：从最新经历中提取知识卡片
    """

    def __init__(
        self,
        data_dir: Optional[str] = None,
        experience_journal: Any = None,
        knowledge_distiller: Any = None,
    ):
        if data_dir is None:
            data_dir = Path(__file__).parent.parent / "castorice_data"
        self.data_dir = Path(data_dir).resolve()
        self.experience_journal = experience_journal
        self.knowledge_distiller = knowledge_distiller

        # 睡眠记录
        self._sleep_history: List[SleepReport] = []
        self._lock = threading.RLock()

        logger.info("睡眠机制初始化")

    # ============== 核心：执行一次睡眠 ==============

    def perform_sleep(
        self,
        do_merge: bool = True,
        do_compress: bool = True,
        do_epoch: bool = True,
        do_distill: bool = True,
    ) -> SleepReport:
        """
        执行一次完整的睡眠周期

        注意：这会修改经历数据库，建议在空闲时执行
        """
        report = SleepReport(started_at=datetime.now(timezone.utc).isoformat())
        t0 = time.time()

        logger.info("=" * 60)
        logger.info("🌙 开始睡眠周期 —— 记忆巩固中...")
        logger.info("=" * 60)

        try:
            # 1. 相似经历合并
            if do_merge:
                try:
                    merged = self._merge_similar_experiences()
                    report.experiences_merged = merged
                    report.details.append(f"合并了 {merged} 条相似经历")
                    logger.info(f"  ✅ 相似经历合并: {merged} 条")
                except Exception as e:
                    logger.warning(f"  ❌ 相似经历合并失败: {e}")
                    report.details.append(f"合并失败: {e}")

            # 2. 低重要性记忆压缩
            if do_compress:
                try:
                    compressed = self._compress_low_importance()
                    report.memories_compressed = compressed
                    report.details.append(f"压缩了 {compressed} 条低重要性记忆")
                    logger.info(f"  ✅ 低重要性记忆压缩: {compressed} 条")
                except Exception as e:
                    logger.warning(f"  ❌ 记忆压缩失败: {e}")
                    report.details.append(f"压缩失败: {e}")

            # 3. 时期总结
            if do_epoch:
                try:
                    epochs = self._create_epoch_summary()
                    report.epochs_created = epochs
                    report.details.append(f"生成了 {epochs} 个时期总结")
                    logger.info(f"  ✅ 时期总结: {epochs} 个")
                except Exception as e:
                    logger.warning(f"  ❌ 时期总结失败: {e}")
                    report.details.append(f"时期总结失败: {e}")

            # 4. 知识蒸馏
            if do_distill and self.knowledge_distiller:
                try:
                    recent = self._get_recent_experiences(limit=50)
                    if recent:
                        cards = self.knowledge_distiller.distill_from_experiences(recent, max_cards=8)
                        report.cards_distilled = len(cards)
                        report.details.append(f"蒸馏了 {len(cards)} 张知识卡片")
                        logger.info(f"  ✅ 知识蒸馏: {len(cards)} 张卡片")
                except Exception as e:
                    logger.warning(f"  ❌ 知识蒸馏失败: {e}")
                    report.details.append(f"知识蒸馏失败: {e}")

        finally:
            report.ended_at = datetime.now(timezone.utc).isoformat()
            report.duration_seconds = round(time.time() - t0, 1)

            self._sleep_history.append(report)
            if len(self._sleep_history) > 100:
                self._sleep_history = self._sleep_history[-100:]

            logger.info("=" * 60)
            logger.info(
                f"🌞 睡眠完成: 耗时 {report.duration_seconds:.1f}s, "
                f"合并 {report.experiences_merged}, "
                f"压缩 {report.memories_compressed}, "
                f"时期 {report.epochs_created}, "
                f"卡片 {report.cards_distilled}"
            )
            logger.info("=" * 60)

        return report

    # ============== 1. 相似经历合并 ==============

    def _merge_similar_experiences(self) -> int:
        """
        合并内容高度相似的经历（Jaccard > 0.8）

        策略：
        - 只合并 7 天内、同类型的经历
        - 合并后保留时间戳为最早的那条
        - 合并后的内容是各条内容的摘要（取前 100 字 + "..." + 条数）
        - 被合并的经历标记 importance = 0（软删除）
        """
        if not self.experience_journal:
            return 0

        recent = self._get_recent_experiences(days=7, limit=200)
        if len(recent) < 2:
            return 0

        merged_count = 0
        processed = set()

        for i, exp_a in enumerate(recent):
            if exp_a.id in processed:
                continue
            similar = [exp_a]

            for j in range(i + 1, len(recent)):
                exp_b = recent[j]
                if exp_b.id in processed:
                    continue
                if exp_a.memory_type != exp_b.memory_type:
                    continue

                # Jaccard 相似度（基于字符集）
                chars_a = set(exp_a.content)
                chars_b = set(exp_b.content)
                if chars_a and chars_b:
                    intersection = chars_a & chars_b
                    union = chars_a | chars_b
                    jaccard = len(intersection) / len(union) if union else 0
                    if jaccard > 0.75:
                        similar.append(exp_b)

            if len(similar) > 1:
                # 合并：保留最早的那条，其余软删除
                earliest = min(similar, key=lambda e: e.timestamp)
                others = [e for e in similar if e.id != earliest.id]

                # 更新主记录内容
                summary_parts = []
                for e in similar[:3]:
                    summary_parts.append(e.content[:80])
                earliest.content = " [合并了{}条相似经历] ".format(len(similar)) + " | ".join(summary_parts)
                earliest.importance = max(e.importance for e in similar)

                # 保存主记录
                self._update_experience(earliest)

                # 软删除其他记录
                for e in others:
                    self._soft_delete_experience(e.id)
                    processed.add(e.id)

                merged_count += len(others)

            processed.add(exp_a.id)

        return merged_count

    # ============== 2. 低重要性记忆压缩 ==============

    def _compress_low_importance(self) -> int:
        """
        压缩低重要性记忆（importance < 3）

        策略：
        - 只处理超过 7 天的、importance < 3 的经历
        - 内容截断为前 50 字 + "...（已压缩）"
        - 这样可以大幅减少 token 消耗
        """
        if not self.experience_journal:
            return 0

        cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        try:
            conn = sqlite3.connect(str(self.experience_journal.db_path))
            cursor = conn.execute("""
                SELECT id, content FROM experiences
                WHERE importance < 3.0 AND timestamp < ? AND importance > 0
                LIMIT 500
            """, (cutoff,))
            rows = cursor.fetchall()

            compressed = 0
            for row in rows:
                eid, content = row
                if len(content) > 60:
                    new_content = content[:50] + "...（已压缩）"
                    conn.execute(
                        "UPDATE experiences SET content = ? WHERE id = ?",
                        (new_content, eid)
                    )
                    compressed += 1

            conn.commit()
            conn.close()
            return compressed
        except Exception as e:
            logger.debug(f"压缩低重要性记忆失败: {e}")
            return 0

    # ============== 3. 时期总结 ==============

    def _create_epoch_summary(self) -> int:
        """
        自动划分人生时期并生成总结

        策略：
        - 每 100 次交互或每 7 天为一个时期
        - 从经历中提取关键词、情感倾向、主要事件
        - 写入自传式记忆
        """
        if not self.experience_journal:
            return 0

        # 检查是否已有未完成的时期
        recent = self._get_recent_experiences(days=30, limit=500)
        if not recent:
            return 0

        # 简单策略：每 100 条经历生成一个时期
        # 检查已有多少个时期
        auto_epochs_dir = self.data_dir / "epochs"
        auto_epochs_dir.mkdir(exist_ok=True)
        existing_epochs = len(list(auto_epochs_dir.glob("epoch_*.json")))

        target_epochs = len(recent) // 100
        if target_epochs <= existing_epochs:
            return 0

        new_epochs_count = target_epochs - existing_epochs

        for i in range(new_epochs_count):
            epoch_num = existing_epochs + i + 1
            start_idx = (epoch_num - 1) * 100
            end_idx = min(epoch_num * 100, len(recent))
            epoch_experiences = recent[start_idx:end_idx]

            if not epoch_experiences:
                continue

            # 统计
            avg_valence = sum(
                e.emotional_valence for e in epoch_experiences
                if hasattr(e, 'emotional_valence')
            ) / max(1, len(epoch_experiences))

            types_count: Dict[str, int] = {}
            for e in epoch_experiences:
                t = getattr(e, 'memory_type', 'general')
                types_count[t] = types_count.get(t, 0) + 1

            # 关键词
            all_text = " ".join(
                e.content[:50] for e in epoch_experiences if hasattr(e, 'content')
            )
            keywords = self._extract_keywords(all_text, top_k=10)

            epoch_data = {
                "epoch_number": epoch_num,
                "start_time": epoch_experiences[0].timestamp,
                "end_time": epoch_experiences[-1].timestamp,
                "experience_count": len(epoch_experiences),
                "avg_valence": round(avg_valence, 3),
                "types": types_count,
                "keywords": keywords,
                "summary": self._generate_epoch_summary(epoch_experiences, keywords, avg_valence),
            }

            epoch_path = auto_epochs_dir / f"epoch_{epoch_num:04d}.json"
            with open(epoch_path, "w", encoding="utf-8") as f:
                json.dump(epoch_data, f, ensure_ascii=False, indent=2)

        return new_epochs_count

    def _generate_epoch_summary(
        self,
        experiences: List[Any],
        keywords: List[str],
        avg_valence: float,
    ) -> str:
        """生成时期的自然语言总结"""
        mood = "积极" if avg_valence > 0.2 else ("消极" if avg_valence < -0.2 else "平稳")
        count = len(experiences)

        if keywords:
            kw_str = "、".join(keywords[:5])
            return f"这是一段{mood}的时期，共 {count} 次经历。关键词：{kw_str}。"
        return f"这是一段{mood}的时期，共 {count} 次经历。"

    # ============== 辅助方法 ==============

    def _get_recent_experiences(
        self,
        days: int = 7,
        limit: int = 100,
    ) -> List[Any]:
        """获取最近的经历"""
        if not self.experience_journal:
            return []

        try:
            cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
            conn = sqlite3.connect(str(self.experience_journal.db_path))
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("""
                SELECT * FROM experiences
                WHERE timestamp >= ? AND importance > 0
                ORDER BY timestamp DESC LIMIT ?
            """, (cutoff, limit))
            rows = cursor.fetchall()
            conn.close()

            from castorice.experience_journal import Experience
            return [Experience.from_row(r) for r in rows]
        except Exception as e:
            logger.debug(f"获取最近经历失败: {e}")
            return []

    def _update_experience(self, exp: Any) -> None:
        if not self.experience_journal:
            return
        try:
            conn = sqlite3.connect(str(self.experience_journal.db_path))
            conn.execute("""
                UPDATE experiences SET content = ?, importance = ? WHERE id = ?
            """, (exp.content, exp.importance, exp.id))
            conn.commit()
            conn.close()
        except Exception as e:
            logger.debug(f"更新经历失败: {e}")

    def _soft_delete_experience(self, exp_id: str) -> None:
        if not self.experience_journal:
            return
        try:
            conn = sqlite3.connect(str(self.experience_journal.db_path))
            conn.execute("UPDATE experiences SET importance = 0 WHERE id = ?", (exp_id,))
            conn.commit()
            conn.close()
        except Exception as e:
            logger.debug(f"软删除经历失败: {e}")

    def _extract_keywords(self, text: str, top_k: int = 10) -> List[str]:
        import re
        words = re.findall(r'[\u4e00-\u9fff]{2,}|[a-zA-Z]{3,}', text)
        freq: Dict[str, int] = {}
        for w in words:
            freq[w] = freq.get(w, 0) + 1
        sorted_words = sorted(freq.items(), key=lambda x: x[1], reverse=True)
        return [w for w, _ in sorted_words[:top_k]]

    def get_sleep_history(self, limit: int = 20) -> List[Dict[str, Any]]:
        """获取睡眠历史"""
        with self._lock:
            return [r.to_dict() for r in self._sleep_history[-limit:]]


# ============================================================
# 持续学习管理器 (ContinuousLearningManager)
# ============================================================

class ContinuousLearningManager:
    """
    持续学习管理器 —— 定时调度蒸馏与睡眠

    触发机制：
    - 蒸馏：每 N 次交互（默认 20 次）触发一次
    - 睡眠：空闲时间超过阈值（默认 10 分钟无交互）触发

    设计原则：
    - 后台线程运行，不阻塞主循环
    - 所有操作有超时保护
    - 可通过 API 手动触发
    """

    def __init__(
        self,
        data_dir: Optional[str] = None,
        engine: Any = None,
        experience_journal: Any = None,
        llm_adapter: Any = None,
    ):
        if data_dir is None:
            data_dir = Path(__file__).parent.parent / "castorice_data"
        self.data_dir = Path(data_dir).resolve()
        self.engine = engine
        self.experience_journal = experience_journal
        self.llm_adapter = llm_adapter

        # 子模块
        self.knowledge_distiller = KnowledgeDistiller(
            data_dir=str(self.data_dir),
            llm_adapter=llm_adapter,
        )
        self.sleep_mechanism = SleepMechanism(
            data_dir=str(self.data_dir),
            experience_journal=experience_journal,
            knowledge_distiller=self.knowledge_distiller,
        )

        # 调度配置
        self.distill_interval_interactions: int = 20  # 每 N 次交互蒸馏一次
        self.sleep_idle_seconds: float = 600.0         # 空闲 10 分钟触发睡眠

        # 状态
        self._interaction_count: int = 0
        self._last_distill_count: int = 0
        self._last_interaction_ts: float = time.time()
        self._is_sleeping: bool = False
        self._is_distilling: bool = False

        # 线程
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

        logger.info("持续学习管理器初始化完成")

    # ============== 生命周期 ==============

    def start(self) -> None:
        """启动后台线程"""
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop,
            name="ContinuousLearning",
            daemon=True,
        )
        self._thread.start()
        logger.info(
            f"持续学习管理器已启动: "
            f"蒸馏间隔={self.distill_interval_interactions}次交互, "
            f"睡眠阈值={self.sleep_idle_seconds:.0f}s"
        )

    def stop(self) -> None:
        """停止后台线程"""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=10.0)
        logger.info("持续学习管理器已停止")

    def _run_loop(self) -> None:
        """后台调度循环"""
        while not self._stop_event.is_set():
            try:
                self._tick()
            except Exception as e:
                logger.error(f"持续学习循环异常: {e}")

            # 每 10 秒检查一次
            self._stop_event.wait(10.0)

    def _tick(self) -> None:
        """单次调度检查"""
        now = time.time()

        # 检查是否该蒸馏
        with self._lock:
            interactions_since = self._interaction_count - self._last_distill_count

        if interactions_since >= self.distill_interval_interactions and not self._is_distilling:
            self.trigger_distill()

        # 检查是否该睡眠（空闲超过阈值）
        idle_seconds = now - self._last_interaction_ts
        if idle_seconds >= self.sleep_idle_seconds and not self._is_sleeping:
            self.trigger_sleep()

    # ============== 交互上报 ==============

    def report_interaction(self) -> None:
        """上报一次用户交互（用于计数和空闲检测）"""
        with self._lock:
            self._interaction_count += 1
            self._last_interaction_ts = time.time()

    # ============== 手动触发 ==============

    def trigger_distill(self, max_cards: int = 5) -> List[Any]:
        """手动触发知识蒸馏"""
        if self._is_distilling:
            logger.debug("蒸馏已在进行中，跳过")
            return []

        with self._lock:
            self._is_distilling = True
            self._last_distill_count = self._interaction_count

        try:
            # 获取最近的经历
            recent = self._get_recent_experiences_for_distill()
            if not recent:
                return []

            cards = self.knowledge_distiller.distill_from_experiences(recent, max_cards=max_cards)
            logger.info(f"手动蒸馏完成: 产出 {len(cards)} 张知识卡片")
            return cards
        except Exception as e:
            logger.error(f"蒸馏失败: {e}")
            return []
        finally:
            self._is_distilling = False

    def trigger_sleep(self) -> Optional[SleepReport]:
        """手动触发睡眠（记忆巩固）"""
        if self._is_sleeping:
            logger.debug("睡眠已在进行中，跳过")
            return None

        with self._lock:
            self._is_sleeping = True
            self._last_interaction_ts = time.time()  # 重置空闲计时

        try:
            logger.info("开始睡眠周期（手动触发）")
            report = self.sleep_mechanism.perform_sleep()
            return report
        except Exception as e:
            logger.error(f"睡眠失败: {e}")
            return None
        finally:
            self._is_sleeping = False

    # ============== 辅助 ==============

    def _get_recent_experiences_for_distill(self) -> List[Any]:
        """获取待蒸馏的经历（上次蒸馏之后的）"""
        if not self.experience_journal:
            return []

        # 通过 knowledge_distiller 的进度获取上次处理的位置
        stats = self.knowledge_distiller.get_stats()
        last_id = stats.get("progress", {}).get("last_experience_id", "")

        try:
            conn = sqlite3.connect(str(self.experience_journal.db_path))
            conn.row_factory = sqlite3.Row

            if last_id:
                # 获取指定 id 之后的经历
                cursor = conn.execute("""
                    SELECT * FROM experiences
                    WHERE id > ? AND importance > 0
                    ORDER BY timestamp ASC LIMIT 100
                """, (last_id,))
            else:
                # 第一次：获取最近 50 条
                cursor = conn.execute("""
                    SELECT * FROM experiences
                    WHERE importance > 0
                    ORDER BY timestamp DESC LIMIT 50
                """)

            rows = cursor.fetchall()
            conn.close()

            from castorice.experience_journal import Experience
            return [Experience.from_row(r) for r in rows]
        except Exception as e:
            logger.debug(f"获取待蒸馏经历失败: {e}")
            return []

    # ============== 状态查询 ==============

    def get_status(self) -> Dict[str, Any]:
        """获取整体状态"""
        with self._lock:
            now = time.time()
            idle_seconds = now - self._last_interaction_ts

        return {
            "running": self._thread is not None and self._thread.is_alive(),
            "is_sleeping": self._is_sleeping,
            "is_distilling": self._is_distilling,
            "interaction_count": self._interaction_count,
            "last_distill_count": self._last_distill_count,
            "interactions_until_distill": max(
                0, self.distill_interval_interactions - (self._interaction_count - self._last_distill_count)
            ),
            "idle_seconds": round(idle_seconds, 1),
            "seconds_until_sleep": max(0.0, round(self.sleep_idle_seconds - idle_seconds, 1)),
            "knowledge_cards": self.knowledge_distiller.get_stats(),
            "sleep_history_count": len(self.sleep_mechanism._sleep_history),
        }


# 避免循环导入
from castorice.knowledge_distiller import KnowledgeDistiller  # noqa: E402
