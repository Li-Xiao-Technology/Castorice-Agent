"""
P3 通用 HTTP 客户端测试
"""
import pytest
from castorice.http_client import (
    get_http_client,
    close_http_client,
)


class TestHTTPClient:
    def test_singleton(self):
        """测试全局单例"""
        c1 = get_http_client()
        c2 = get_http_client()
        assert c1 is c2

    def test_get_returns_client(self):
        """测试 get 返回可用 client"""
        client = get_http_client()
        assert client is not None
        assert hasattr(client, "get")
        assert hasattr(client, "post")

    def test_close_and_recreate(self):
        """测试关闭后重新创建"""
        c1 = get_http_client()
        c1.close()
        # 关闭后 get_http_client 会创建新实例
        c2 = get_http_client()
        assert c2 is not None

    def test_close_http_client(self):
        """测试 close_http_client 函数"""
        get_http_client()  # 确保已创建
        close_http_client()
        # 关闭后能正常重新创建
        c = get_http_client()
        assert c is not None
