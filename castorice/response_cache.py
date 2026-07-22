"""
LLM 调用缓存模块

提供响应缓存功能，减少重复请求：
- 基于请求内容的哈希缓存
- 支持 TTL 和容量限制
- 线程安全
- 支持内存和文件两种存储方式
"""

import hashlib
import json
import logging
import os
import threading
import time
from typing import Any, Dict, Optional

logger = logging.getLogger("Castorice.ResponseCache")


class ResponseCache:
    """LLM 响应缓存"""

    def __init__(self, max_size: int = 1000, ttl_seconds: int = 3600):
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._max_size = max_size
        self._ttl = ttl_seconds
        self._lock = threading.Lock()
        self._hit_count = 0
        self._miss_count = 0

    def _compute_key(self, messages: list, model: str, **kwargs) -> str:
        """计算缓存键"""
        data = {
            "messages": messages,
            "model": model,
            "kwargs": kwargs,
        }
        serialized = json.dumps(data, ensure_ascii=False, sort_keys=True)
        return hashlib.md5(serialized.encode("utf-8")).hexdigest()

    def get(self, messages: list, model: str, **kwargs) -> Optional[Dict[str, Any]]:
        """获取缓存响应"""
        key = self._compute_key(messages, model, **kwargs)
        with self._lock:
            if key in self._cache:
                entry = self._cache[key]
                if time.time() - entry["timestamp"] < self._ttl:
                    self._hit_count += 1
                    return entry["response"]
                else:
                    del self._cache[key]
            self._miss_count += 1
        return None

    def set(self, messages: list, model: str, response: Dict[str, Any], **kwargs) -> None:
        """设置缓存响应"""
        key = self._compute_key(messages, model, **kwargs)
        with self._lock:
            if len(self._cache) >= self._max_size:
                oldest = min(self._cache.keys(), key=lambda k: self._cache[k]["timestamp"])
                del self._cache[oldest]
            
            self._cache[key] = {
                "response": response,
                "timestamp": time.time(),
            }

    def clear(self) -> None:
        """清空缓存"""
        with self._lock:
            self._cache.clear()
            self._hit_count = 0
            self._miss_count = 0

    def get_stats(self) -> Dict[str, Any]:
        """获取缓存统计"""
        with self._lock:
            total = self._hit_count + self._miss_count
            hit_rate = self._hit_count / total if total > 0 else 0
            return {
                "hit_count": self._hit_count,
                "miss_count": self._miss_count,
                "hit_rate": hit_rate,
                "cache_size": len(self._cache),
                "max_size": self._max_size,
            }


class FileResponseCache(ResponseCache):
    """基于文件的响应缓存"""

    def __init__(self, cache_dir: str = "cache/responses", max_size: int = 1000, ttl_seconds: int = 3600):
        super().__init__(max_size, ttl_seconds)
        self._cache_dir = cache_dir
        os.makedirs(cache_dir, exist_ok=True)

    def _get_file_path(self, key: str) -> str:
        return os.path.join(self._cache_dir, f"{key}.json")

    def get(self, messages: list, model: str, **kwargs) -> Optional[Dict[str, Any]]:
        key = self._compute_key(messages, model, **kwargs)
        
        mem_result = super().get(messages, model, **kwargs)
        if mem_result:
            return mem_result

        file_path = self._get_file_path(key)
        if os.path.exists(file_path):
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if time.time() - data["timestamp"] < self._ttl:
                    response = data["response"]
                    super().set(messages, model, response, **kwargs)
                    return response
                else:
                    os.remove(file_path)
            except Exception:
                pass

        return None

    def set(self, messages: list, model: str, response: Dict[str, Any], **kwargs) -> None:
        super().set(messages, model, response, **kwargs)
        key = self._compute_key(messages, model, **kwargs)
        file_path = self._get_file_path(key)
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump({
                    "response": response,
                    "timestamp": time.time(),
                }, f, ensure_ascii=False)
        except Exception:
            pass

    def clear(self) -> None:
        super().clear()
        try:
            for filename in os.listdir(self._cache_dir):
                if filename.endswith(".json"):
                    os.remove(os.path.join(self._cache_dir, filename))
        except Exception:
            pass


_response_cache = None


def get_response_cache() -> ResponseCache:
    """获取全局响应缓存单例"""
    global _response_cache
    if _response_cache is None:
        _response_cache = ResponseCache()
    return _response_cache
