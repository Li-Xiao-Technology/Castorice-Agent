"""
通用 HTTP 客户端模块

提供统一的 httpx.Client 管理，支持：
- 单例模式避免重复创建连接
- 自定义 User-Agent 避免被 API 拦截
- 超时配置
- 连接池管理
- 线程安全的单例创建
"""

import threading

import httpx

_httpx_client = None
_lock = threading.Lock()


def set_http_client(instance: httpx.Client) -> None:
    """手动设置全局 httpx.Client 实例（Agent 初始化时调用，确保配置生效）"""
    global _httpx_client
    _httpx_client = instance


def get_http_client(timeout: float = 15.0) -> httpx.Client:
    """获取单例 httpx.Client（带浏览器 User-Agent，避免被 API 拦截）

    Args:
        timeout: 请求超时时间（秒），默认 15.0。仅在首次创建客户端时生效。
    """
    global _httpx_client
    if _httpx_client is None:
        with _lock:
            if _httpx_client is None:
                _httpx_client = httpx.Client(
                    timeout=timeout,
                    headers={
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    },
                )
    return _httpx_client


def close_http_client() -> None:
    """关闭 HTTP 客户端，释放资源"""
    global _httpx_client
    with _lock:
        if _httpx_client is not None:
            try:
                _httpx_client.close()
            except Exception:
                pass
            _httpx_client = None
