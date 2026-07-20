"""
P3.2: 工具调用自我学习
======================

记录每次工具调用的"输入描述 → 参数 → 结果"三元组。
新任务来时检索历史上相似描述的成功调用模式，
辅助 LLM 更准确地推断参数。

设计原则：
- 不修改工具本身，只学习"什么输入该用什么参数"
- 检索基于输入描述的语义相似度
- 失败案例不参与推荐（避免学习错误模式）
"""
import logging
import threading
import time
from collections import deque
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("Castorice.ToolLearning")


class ToolCallMemory:
    """
    工具调用模式记忆

    存储每次工具调用的"描述→参数→结果"，用于将来辅助参数推断
    """

    def __init__(self, max_records_per_tool: int = 200):
        self._lock = threading.RLock()
        self._max_records = max_records_per_tool
        # tool_name -> deque of records
        self._records: Dict[str, deque] = {}

    def record(
        self,
        tool_name: str,
        input_description: str,
        arguments: Dict[str, Any],
        result_summary: str,
        success: bool,
    ) -> None:
        """记录一次工具调用"""
        with self._lock:
            if tool_name not in self._records:
                self._records[tool_name] = deque(maxlen=self._max_records)
            self._records[tool_name].append({
                "desc": input_description[:200],
                "args": arguments,
                "result_summary": result_summary[:200],
                "success": success,
                "ts": time.time(),
            })

    def find_similar(
        self,
        tool_name: str,
        input_description: str,
        top_k: int = 3,
    ) -> List[Dict[str, Any]]:
        """
        查找历史上相似的工具调用

        :return: 相似调用列表（按相似度降序）
        """
        with self._lock:
            records = list(self._records.get(tool_name, []))
            if not records:
                return []

            # 仅用成功案例
            success_records = [r for r in records if r["success"]]
            if not success_records:
                return []

            # 简单相似度：词集合 Jaccard
            input_words = set(input_description.lower().split())

            scored = []
            for rec in success_records:
                rec_words = set(rec["desc"].lower().split())
                if not rec_words:
                    continue
                sim = len(input_words & rec_words) / len(input_words | rec_words)
                if sim > 0:
                    scored.append((sim, rec))

            scored.sort(reverse=True, key=lambda x: x[0])
            return [r for _, r in scored[:top_k]]

    def suggest_arguments(
        self,
        tool_name: str,
        input_description: str,
        top_k: int = 3,
    ) -> Optional[Dict[str, Any]]:
        """
        P3.2: 基于历史记录推荐参数

        如果最相似的历史调用有相同的参数模式，返回推荐参数。
        """
        similar = self.find_similar(tool_name, input_description, top_k=top_k)
        if not similar:
            return None

        # 取 top_k 记录的 args，统计频率
        arg_keys_count: Dict[str, int] = {}
        arg_values: Dict[str, Dict[str, int]] = {}

        for rec in similar:
            for k, v in rec["args"].items():
                arg_keys_count[k] = arg_keys_count.get(k, 0) + 1
                if k not in arg_values:
                    arg_values[k] = {}
                v_str = str(v)
                arg_values[k][v_str] = arg_values[k].get(v_str, 0) + 1

        # 构造推荐 args（仅保留出现频率 >= 50% 的 key）
        threshold = max(1, len(similar) // 2)
        suggested = {}
        for k, count in arg_keys_count.items():
            if count >= threshold:
                # 取该 key 下最常见的 value
                if k in arg_values and arg_values[k]:
                    best_value = max(arg_values[k], key=arg_values[k].get)
                    suggested[k] = best_value

        return suggested if suggested else None

    def get_stats(self) -> Dict[str, Any]:
        """获取学习统计"""
        with self._lock:
            return {
                tool_name: {
                    "total": len(recs),
                    "success": sum(1 for r in recs if r["success"]),
                }
                for tool_name, recs in self._records.items()
            }


# 全局单例
_tool_memory: Optional[ToolCallMemory] = None
_tool_memory_lock = threading.Lock()


def get_tool_memory() -> ToolCallMemory:
    """获取全局工具记忆单例"""
    global _tool_memory
    with _tool_memory_lock:
        if _tool_memory is None:
            _tool_memory = ToolCallMemory()
    return _tool_memory
