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
import json
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
        model_adapter: Any = None,
    ) -> Optional[Dict[str, Any]]:
        """
        P3.2: 基于历史记录推荐参数（优先 LLM 推断，回退统计方法）

        如果最相似的历史调用有相同的参数模式，返回推荐参数。
        当提供 model_adapter 时，使用 LLM 智能推断参数，否则使用词频统计。
        """
        similar = self.find_similar(tool_name, input_description, top_k=top_k)
        if not similar:
            return None

        # P3.2: 如果有模型适配器，使用 LLM 智能推断参数
        if model_adapter is not None:
            return self._llm_suggest_arguments(
                tool_name, input_description, similar, model_adapter
            )

        # 回退：词频统计方法
        arg_keys_count: Dict[str, int] = {}
        arg_values: Dict[str, Dict[str, int]] = {}

        for rec in similar:
            for k, v in rec["args"].items():
                arg_keys_count[k] = arg_keys_count.get(k, 0) + 1
                if k not in arg_values:
                    arg_values[k] = {}
                v_str = str(v)
                arg_values[k][v_str] = arg_values[k].get(v_str, 0) + 1

        threshold = max(1, len(similar) // 2)
        suggested = {}
        for k, count in arg_keys_count.items():
            if count >= threshold:
                if k in arg_values and arg_values[k]:
                    best_value = max(arg_values[k], key=arg_values[k].get)
                    suggested[k] = best_value

        return suggested if suggested else None

    def _llm_suggest_arguments(
        self,
        tool_name: str,
        input_description: str,
        similar_records: List[Dict[str, Any]],
        model_adapter: Any,
    ) -> Optional[Dict[str, Any]]:
        """
        P3.2: 使用 LLM 智能推断工具参数

        基于历史成功案例和当前输入描述，让 LLM 推断最合适的参数值。
        """
        from castorice.model_adapter import ChatMessage
        from castorice.utils import extract_json

        records_desc = "\n".join(
            f"- 输入: {r['desc']}\n  参数: {json.dumps(r['args'], ensure_ascii=False)}\n  结果: {r['result_summary']}"
            for r in similar_records
        )

        prompt = f"""你是工具参数推荐专家。请根据以下信息，为工具「{tool_name}」推断合适的参数。

【当前用户输入】
{input_description}

【历史成功案例】
{records_desc}

【任务】
分析当前用户输入与历史案例的相似性，推断应该使用哪些参数。
如果历史案例的参数模式可以复用，直接推荐；如果需要调整，给出调整后的参数。

【输出格式】
只返回 JSON：{{"arguments": {{"参数名": "值"}}, "reasoning": "推荐理由"}}

注意：
- 参数值要具体，不要留空或使用占位符
- 只推荐与当前输入相关的参数
- 如果无法推断，返回空的 arguments"""

        try:
            response = model_adapter.chat([
                ChatMessage("system", "你是工具参数推荐专家，只输出 JSON。"),
                ChatMessage("user", prompt),
            ])
            parsed = extract_json(response.content)
            args = parsed.get("arguments", {})
            if args:
                logger.info(f"P3.2 LLM 参数推荐: {tool_name} -> {json.dumps(args, ensure_ascii=False)}")
                return args
        except Exception as e:
            logger.debug(f"P3.2 LLM 参数推荐失败，回退统计方法: {e}")

        return None

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
