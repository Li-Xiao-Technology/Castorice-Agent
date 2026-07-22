"""
通用 HTTP 客户端模块

提供统一的 httpx.Client 管理，支持：
- 单例模式避免重复创建连接
- 自定义 User-Agent 避免被 API 拦截
- 超时配置
- 连接池管理
"""

import httpx

_httpx_client = None


def get_http_client() -> httpx.Client:
    """获取单例 httpx.Client（带浏览器 User-Agent，避免被 API 拦截）"""
    global _httpx_client
    if _httpx_client is None:
        _httpx_client = httpx.Client(
            timeout=15,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            },
        )
    return _httpx_client


def close_http_client() -> None:
    """关闭 HTTP 客户端，释放资源"""
    global _httpx_client
    if _httpx_client is not None:
        try:
            _httpx_client.close()
        except Exception:
            pass
        _httpx_client = None
