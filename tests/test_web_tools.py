"""
Mock-based unit tests for castorice/tools/web_tools.py
"""
import pytest
from unittest.mock import MagicMock, patch, PropertyMock

from castorice.tools.web_tools import (
    _is_internal_url,
    _web_fetch,
    _wikipedia_search,
    _stock_price,
    _translate_text,
    _ip_info,
)


class TestSSRFProtection:
    """Test 1 - SSRF Protection (_is_internal_url)"""

    BLOCKED_HOSTS = [
        ("localhost", "localhost"),
        ("127.0.0.1", "127.0.0.1"),
        ("0.0.0.0", "0.0.0.0"),
        ("[::1]", "::1"),
        ("10.0.0.1", "10.0.0.1"),
        ("10.255.255.254", "10.x range"),
        ("172.16.0.1", "172.16.0.0/12 range"),
        ("172.31.255.254", "172.31.x range"),
        ("192.168.0.1", "192.168.0.0/16 range"),
        ("192.168.1.1", "192.168.1.1"),
        ("169.254.0.1", "169.254.x link-local"),
        ("169.254.169.254", "AWS metadata endpoint"),
    ]

    ALLOWED_HOSTS = [
        ("https://google.com", "google.com"),
        ("https://api.github.com", "api.github.com"),
        ("https://www.example.com/path?q=1", "example.com"),
    ]

    @pytest.mark.parametrize("url,desc", BLOCKED_HOSTS)
    def test_internal_url_blocked(self, url, desc):
        full_url = f"http://{url}" if not url.startswith("http") else url
        assert _is_internal_url(full_url) is True, f"{desc} should be blocked"

    @pytest.mark.parametrize("url,desc", ALLOWED_HOSTS)
    def test_public_url_allowed(self, url, desc):
        assert _is_internal_url(url) is False, f"{desc} should be allowed"


class TestWebFetchSSRF:
    """Test 2 - web_fetch internal URL blocking"""

    def test_fetch_localhost_blocked(self):
        result = _web_fetch("http://127.0.0.1")
        assert result == "SSRF 防护：不允许访问内部/私有网络地址"

    def test_fetch_private_ip_blocked(self):
        result = _web_fetch("http://192.168.1.1")
        assert result == "SSRF 防护：不允许访问内部/私有网络地址"

    def test_fetch_no_protocol(self):
        result = _web_fetch("just-a-string")
        assert result == "URL 必须以 http:// 或 https:// 开头"


class TestWebFetchNormal:
    """Test 3 - web_fetch normal URL"""

    def test_fetch_ok_html(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "text/html"}
        mock_response.text = "<html><body><h1>Hello</h1><p>World.</p></body></html>"
        mock_response.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.get.return_value = mock_response

        with patch("castorice.tools.web_tools._get_httpx_client", return_value=mock_client):
            result = _web_fetch("https://example.com")

        assert "Hello" in result
        assert "World" in result

    def test_fetch_pdf_content_type(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "application/pdf"}
        mock_response.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.get.return_value = mock_response

        with patch("castorice.tools.web_tools._get_httpx_client", return_value=mock_client):
            result = _web_fetch("https://example.com/doc.pdf")

        assert "PDF" in result

    def test_fetch_truncation(self):
        long_text = "abc" * 2000
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "text/html"}
        mock_response.text = f"<html><body>{long_text}</body></html>"
        mock_response.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.get.return_value = mock_response

        with patch("castorice.tools.web_tools._get_httpx_client", return_value=mock_client):
            result = _web_fetch("https://example.com", max_length=500)

        assert "截断" in result

    def test_fetch_http_error(self):
        mock_client = MagicMock()
        mock_client.get.side_effect = Exception("Connection timeout")

        with patch("castorice.tools.web_tools._get_httpx_client", return_value=mock_client):
            result = _web_fetch("https://example.com")

        assert result.startswith("网页抓取失败")


class TestWikipediaSearch:
    """Test 4 - wikipedia_search mock"""

    def test_wikipedia_search_ok(self):
        search_data = {
            "query": {
                "search": [
                    {"pageid": 12345, "title": "Test Article"},
                    {"pageid": 67890, "title": "Other Article"},
                ]
            }
        }
        extract_data = {
            "query": {
                "pages": {
                    "12345": {
                        "title": "Test Article",
                        "extract": "This is a test article about mock testing.",
                    }
                }
            }
        }

        def mock_get(url, **kwargs):
            resp = MagicMock()
            if kwargs.get("params", {}).get("list") == "search":
                resp.json.return_value = search_data
            else:
                resp.json.return_value = extract_data
            return resp

        mock_client = MagicMock()
        mock_client.get.side_effect = mock_get

        with patch("castorice.tools.web_tools._get_httpx_client", return_value=mock_client):
            result = _wikipedia_search("test", lang="en")

        assert "Test Article" in result
        assert "test article" in result.lower()

    def test_wikipedia_search_no_results(self):
        empty_data = {"query": {"search": []}}
        mock_response = MagicMock()
        mock_response.json.return_value = empty_data

        mock_client = MagicMock()
        mock_client.get.return_value = mock_response

        with patch("castorice.tools.web_tools._get_httpx_client", return_value=mock_client):
            result = _wikipedia_search("xyznonexistent", lang="en")

        assert "未找到" in result

    def test_wikipedia_search_error(self):
        mock_client = MagicMock()
        mock_client.get.side_effect = Exception("Network error")

        with patch("castorice.tools.web_tools._get_httpx_client", return_value=mock_client):
            result = _wikipedia_search("test")

        assert result.startswith("维基百科查询失败")


class TestStockPrice:
    """Test 5 - stock_price mock"""

    def test_stock_price_ok(self):
        mock_data = {
            "chart": {
                "result": [
                    {
                        "meta": {
                            "regularMarketPrice": 150.25,
                            "regularMarketChange": 2.50,
                            "regularMarketChangePercent": 1.69,
                            "currency": "USD",
                            "exchangeName": "NMS",
                            "shortName": "Test Corp",
                        }
                    }
                ]
            }
        }
        mock_response = MagicMock()
        mock_response.json.return_value = mock_data
        mock_response.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.get.return_value = mock_response

        with patch("castorice.tools.web_tools._get_httpx_client", return_value=mock_client):
            result = _stock_price("TEST")

        assert "Test Corp" in result
        assert "150.25" in result
        assert "USD" in result

    def test_stock_price_not_found(self):
        mock_data = {"chart": {"result": []}}
        mock_response = MagicMock()
        mock_response.json.return_value = mock_data
        mock_response.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.get.return_value = mock_response

        with patch("castorice.tools.web_tools._get_httpx_client", return_value=mock_client):
            result = _stock_price("NONEXISTENT")

        assert "未找到" in result

    def test_stock_price_error(self):
        mock_client = MagicMock()
        mock_client.get.side_effect = Exception("API limit")

        with patch("castorice.tools.web_tools._get_httpx_client", return_value=mock_client):
            result = _stock_price("TEST")

        assert result.startswith("股票查询失败")


class TestTranslateText:
    """Test 6 - translate_text mock"""

    def test_translate_ok(self):
        mock_data = [
            [["你好世界", "hello world", None, None, 1]],
            None,
            "zh-CN",
        ]
        mock_response = MagicMock()
        mock_response.json.return_value = mock_data
        mock_response.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.get.return_value = mock_response

        with patch("castorice.tools.web_tools._get_httpx_client", return_value=mock_client):
            result = _translate_text("hello world", target_lang="zh")

        assert "你好世界" in result

    def test_translate_error(self):
        mock_client = MagicMock()
        mock_client.get.side_effect = Exception("Service unavailable")

        with patch("castorice.tools.web_tools._get_httpx_client", return_value=mock_client):
            result = _translate_text("hello")

        assert result.startswith("翻译失败")

    def test_translate_invalid_response(self):
        mock_response = MagicMock()
        mock_response.json.return_value = None
        mock_response.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.get.return_value = mock_response

        with patch("castorice.tools.web_tools._get_httpx_client", return_value=mock_client):
            result = _translate_text("hello")

        assert "翻译失败" in result


class TestIPInfo:
    """Test 7 - ip_info mock"""

    def test_ip_info_ok(self):
        mock_data = {
            "status": "success",
            "query": "8.8.8.8",
            "country": "United States",
            "regionName": "California",
            "city": "Mountain View",
            "isp": "Google LLC",
            "org": "Google Public DNS",
            "as": "AS15169 Google LLC",
            "timezone": "America/Los_Angeles",
        }
        mock_response = MagicMock()
        mock_response.json.return_value = mock_data
        mock_response.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.get.return_value = mock_response

        with patch("castorice.tools.web_tools._get_httpx_client", return_value=mock_client):
            result = _ip_info("8.8.8.8")

        assert "8.8.8.8" in result
        assert "United States" in result
        assert "Google" in result

    def test_ip_info_failed(self):
        mock_data = {"status": "fail", "message": "Invalid query"}
        mock_response = MagicMock()
        mock_response.json.return_value = mock_data
        mock_response.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.get.return_value = mock_response

        with patch("castorice.tools.web_tools._get_httpx_client", return_value=mock_client):
            result = _ip_info("invalid")

        assert "查询失败" in result

    def test_ip_info_error(self):
        mock_client = MagicMock()
        mock_client.get.side_effect = Exception("Timeout")

        with patch("castorice.tools.web_tools._get_httpx_client", return_value=mock_client):
            result = _ip_info("1.2.3.4")

        assert result.startswith("IP 查询失败")