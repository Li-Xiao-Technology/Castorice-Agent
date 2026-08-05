"""
Castorice Agent - LLM 响应缓存

基于内存 + 磁盘的 LRU 缓存：
- 减少重复请求
- 加速相似查询
- 节省成本
"""

import hashlib
import json
import threading
import time
from collections import OrderedDict
from pathlib import Path
from threading import Lock
from typing import Any, Dict, List, Optional

from .logger import get_logger

logger = get_logger(__name__)


class LLMCache:
    """
    LLM 响应缓存

    特性：
    - LRU 淘汰策略
    - 可选磁盘持久化
    - TTL 过期
    - 线程安全
    """

    def __init__(
        self,
        max_size: int = 100,
        ttl: int = 3600,  # 1 小时
        persist_path: Optional[str] = None,
    ):
        """
        参数：
            max_size: 内存中最大缓存条目数
            ttl: 过期时间（秒）
            persist_path: 持久化文件路径（None 则不持久化）
        """
        self.max_size = max_size
        self.ttl = ttl
        self.persist_path = persist_path
        self._cache: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()
        self._lock = Lock()
        self._hits = 0
        self._misses = 0
        self._dirty = False

        if persist_path:
            self._load_from_disk()

    def _make_key(
        self,
        messages: List[Dict[str, str]],
        model: str,
        temperature: float,
        **kwargs,
    ) -> str:
        """生成缓存 key"""
        # 提取关键参数
        payload = {
            "messages": messages,
            "model": model,
            "temperature": temperature,
            **kwargs,
        }
        content = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    def get(
        self,
        messages: List[Dict[str, str]],
        model: str,
        temperature: float = 0.7,
        **kwargs,
    ) -> Optional[str]:
        """获取缓存"""
        key = self._make_key(messages, model, temperature, **kwargs)

        with self._lock:
            if key not in self._cache:
                self._misses += 1
                return None

            entry = self._cache[key]
            # 检查是否过期
            if time.time() - entry["timestamp"] > self.ttl:
                del self._cache[key]
                self._misses += 1
                return None

            # LRU: 移到末尾
            self._cache.move_to_end(key)
            self._hits += 1
            logger.debug(f"LLM 缓存命中: key={key[:8]}...")
            return entry["response"]

    def set(
        self,
        messages: List[Dict[str, str]],
        model: str,
        temperature: float,
        response: str,
        **kwargs,
    ) -> None:
        """设置缓存"""
        key = self._make_key(messages, model, temperature, **kwargs)

        with self._lock:
            # 已存在则更新
            if key in self._cache:
                self._cache.move_to_end(key)

            self._cache[key] = {
                "response": response,
                "timestamp": time.time(),
                "model": model,
            }

            # LRU 淘汰
            while len(self._cache) > self.max_size:
                oldest_key = next(iter(self._cache))
                del self._cache[oldest_key]

        # 异步落盘（write-behind）：释放锁后再执行磁盘 IO，避免阻塞读操作
        if self.persist_path:
            self._dirty = True
            threading.Thread(target=self._save_to_disk, daemon=True).start()

    def clear(self) -> None:
        """清空缓存"""
        with self._lock:
            self._cache.clear()
            self._hits = 0
            self._misses = 0
            if self.persist_path and Path(self.persist_path).exists():
                Path(self.persist_path).unlink()
        logger.info("LLM 缓存已清空")

    def stats(self) -> Dict[str, Any]:
        """获取统计"""
        total = self._hits + self._misses
        hit_rate = self._hits / total if total > 0 else 0.0
        return {
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": f"{hit_rate:.2%}",
            "size": len(self._cache),
            "max_size": self.max_size,
        }

    def _save_to_disk(self) -> None:
        """持久化到磁盘（write-behind 策略，线程内部自行加锁快照）"""
        if not self.persist_path:
            return
        try:
            from castorice.utils import atomic_json_dump
            # 短暂持锁获取快照，避免长时间持锁阻塞读操作
            with self._lock:
                data = {
                    "cache": dict(self._cache),
                    "timestamp": time.time(),
                }
                self._dirty = False
            atomic_json_dump(data, self.persist_path, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"保存 LLM 缓存失败: {e}")

    def _load_from_disk(self) -> None:
        """从磁盘加载"""
        if not self.persist_path:
            return
        path = Path(self.persist_path)
        if not path.exists():
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            cache = data.get("cache", {})
            # 过滤过期数据
            now = time.time()
            valid_items = OrderedDict()
            for k, v in cache.items():
                if now - v.get("timestamp", 0) <= self.ttl:
                    valid_items[k] = v
            self._cache = valid_items
            logger.info(f"从磁盘加载 LLM 缓存: {len(valid_items)} 条")
        except Exception as e:
            logger.warning(f"加载 LLM 缓存失败: {e}")


# 全局单例
_global_cache: Optional[LLMCache] = None
_global_cache_lock = threading.Lock()



def set_global_cache(instance: LLMCache) -> None:
    """手动设置全局 LLMCache 实例（Agent 初始化时调用，确保配置生效）"""
    global _global_cache
    with _global_cache_lock:
        _global_cache = instance
def get_global_cache() -> LLMCache:
    """获取全局缓存实例"""
    global _global_cache
    if _global_cache is None:
        with _global_cache_lock:
            if _global_cache is None:
                _global_cache = LLMCache()
    return _global_cache
