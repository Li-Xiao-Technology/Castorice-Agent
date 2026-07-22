import logging
import re
import threading
import time
from typing import Any, Dict, Generator, List, Optional

import httpx

from .common import ChatMessage, ChatResponse, ToolCall
from .providers.openai_provider import OpenAIProvider
from .providers.anthropic_provider import AnthropicProvider
from .providers.gemini_provider import GeminiProvider
from .providers.qwen_provider import QwenProvider

logger = logging.getLogger("Castorice.ModelAdapter")


class ModelAdapter:
    """
    统一模型适配器
    
    支持的 provider:
    - openai      : OpenAI 官方（兼容 通义千问 / 百度千帆 等）
    - anthropic   : Claude 官方
    - ollama      : 本地大模型（OpenAI 协议）
    - openrouter  : 多模型聚合（OpenAI 协议）
    - gemini      : Google Gemini 官方 SDK
    - qwen        : 阿里云通义千问官方 SDK
    """

    def __init__(self, llm_config: Dict[str, Any]):
        self.provider = llm_config.get("provider", "openai")
        self.temperature = llm_config.get("temperature", 0.7)
        self.max_tokens = llm_config.get("max_tokens", 4096)
        self.timeout = llm_config.get("timeout", 60)

        self.max_retries = llm_config.get("max_retries", 3)
        self.retry_delay = llm_config.get("retry_delay", 1.0)

        self.openai_cfg = llm_config.get("openai", {})
        self.anthropic_cfg = llm_config.get("anthropic", {})
        self.ollama_cfg = llm_config.get("ollama", {})
        self.openrouter_cfg = llm_config.get("openrouter", {})
        self.gemini_cfg = llm_config.get("gemini", {})
        self.qwen_cfg = llm_config.get("qwen", {})

        self._openai_clients: Dict[str, Any] = {}
        self._anthropic_client = None
        self._gemini_model = None
        self._openai_clients_lock = threading.Lock()
        self._anthropic_client_lock = threading.Lock()
        self._gemini_model_lock = threading.Lock()
        self.tool_choice = llm_config.get("tool_choice", "auto")

        self._stats_lock = threading.Lock()

        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0
        self.total_calls = 0

        try:
            from openai import OpenAI
        except ImportError:
            OpenAI = None
        self._OpenAI = OpenAI

        try:
            import anthropic
        except ImportError:
            anthropic = None
        self._anthropic = anthropic

        try:
            import google.genai as genai
        except ImportError:
            try:
                import google.generativeai as genai
            except ImportError:
                genai = None
        self._genai = genai

        self._providers = {
            "openai": OpenAIProvider(self),
            "ollama": OpenAIProvider(self),
            "openrouter": OpenAIProvider(self),
            "anthropic": AnthropicProvider(self),
            "gemini": GeminiProvider(self),
            "qwen": QwenProvider(self),
        }

    def _get_openai_client(self, base_url: str, api_key: str):
        if self._OpenAI is None:
            raise ImportError("请安装 openai SDK: pip install openai")
        key = f"{base_url}|{api_key}"
        if key not in self._openai_clients:
            with self._openai_clients_lock:
                if key not in self._openai_clients:
                    self._openai_clients[key] = self._OpenAI(
                        api_key=api_key or "EMPTY",
                        base_url=base_url,
                        timeout=self.timeout,
                    )
        return self._openai_clients[key]

    def _get_anthropic_client(self):
        if self._anthropic is None:
            raise ImportError("请安装 anthropic SDK: pip install anthropic")
        with self._anthropic_client_lock:
            if self._anthropic_client is None:
                self._anthropic_client = self._anthropic.Anthropic(
                    api_key=self.anthropic_cfg.get("api_key", ""),
                    base_url=self.anthropic_cfg.get("base_url"),
                    timeout=self.timeout,
                )
        return self._anthropic_client

    def _get_gemini_model(self):
        if self._genai is None:
            raise ImportError("请安装 Google Gemini SDK: pip install google-generativeai")
        if self._gemini_model is None:
            with self._gemini_model_lock:
                if self._gemini_model is None:
                    self._genai.configure(api_key=self.gemini_cfg.get("api_key", ""))
                    self._gemini_model = self._genai.GenerativeModel(
                        self.gemini_cfg.get("model", "gemini-1.5-flash")
                    )
        return self._gemini_model

    def _get_provider(self):
        provider = self._providers.get(self.provider)
        if not provider:
            raise ValueError(f"不支持的模型供应商: {self.provider}")
        return provider

    def close(self) -> None:
        """关闭所有缓存的底层 HTTP 客户端，释放连接池。"""
        with self._openai_clients_lock:
            for client in list(self._openai_clients.values()):
                try:
                    client.close()
                except Exception:
                    pass
            self._openai_clients.clear()
        with self._anthropic_client_lock:
            if self._anthropic_client is not None:
                try:
                    self._anthropic_client.close()
                except Exception:
                    pass
                self._anthropic_client = None
        # Gemini / Qwen 使用 httpx 或底层库，通常随进程退出自动释放

    def _is_retryable_error(self, error: Exception) -> bool:
        error_str = str(error).lower()
        if any(keyword in error_str for keyword in ["timeout", "connection", "network", "timed out"]):
            return True
        if "429" in error_str or "rate limit" in error_str or "rate_limit" in error_str:
            return True
        match = re.search(r'\b(5\d{2})\b', str(error))
        if match:
            return True
        try:
            from openai import APIError, APIConnectionError, RateLimitError, APITimeoutError
            if isinstance(error, (APIConnectionError, RateLimitError, APITimeoutError)):
                return True
            if isinstance(error, APIError) and hasattr(error, 'status_code') and error.status_code and error.status_code >= 500:
                return True
        except ImportError:
            pass
        try:
            if __import__('anthropic', fromlist=['']) is not None:
                anthropic = __import__('anthropic', fromlist=[''])
                from anthropic import APIError as AnthropicAPIError, APIConnectionError as AnthropicAPIConnectionError
                from anthropic import RateLimitError as AnthropicRateLimitError, APITimeoutError as AnthropicAPITimeoutError
                if isinstance(error, (AnthropicAPIConnectionError, AnthropicRateLimitError, AnthropicAPITimeoutError)):
                    return True
                if isinstance(error, AnthropicAPIError) and hasattr(error, 'status_code') and error.status_code and error.status_code >= 500:
                    return True
        except ImportError:
            pass
        try:
            if isinstance(error, (httpx.ConnectError, httpx.ReadTimeout, httpx.ConnectTimeout, httpx.PoolTimeout)):
                return True
        except AttributeError:
            pass
        return False

    def _call_with_retry_stats(self, call_fn) -> ChatResponse:
        last_error = None
        for attempt in range(self.max_retries):
            try:
                response = call_fn()
                with self._stats_lock:
                    if response.usage:
                        self.total_prompt_tokens += response.usage.get("prompt_tokens", 0)
                        self.total_completion_tokens += response.usage.get("completion_tokens", 0)
                    self.total_calls += 1
                return response
            except Exception as e:
                last_error = e
                if attempt < self.max_retries - 1 and self._is_retryable_error(e):
                    delay = self.retry_delay * (2 ** attempt)
                    logger.warning(f"LLM 调用第{attempt + 1}次失败，{delay}s 后重试: {e}")
                    time.sleep(delay)
                    continue
                raise

    def chat(self, messages: List[ChatMessage]) -> ChatResponse:
        try:
            from castorice.response_cache import get_response_cache
            cache = get_response_cache()
            cache_key = str(hash(tuple((m.role, m.content) for m in messages)))
            cached = cache.get(cache_key)
            if cached:
                logger.debug(f"LLM 缓存命中")
                return ChatResponse(content=cached)
        except Exception:
            pass

        response = self._call_with_retry_stats(
            lambda: self._get_provider().chat(messages)
        )

        try:
            from castorice.response_cache import get_response_cache
            cache = get_response_cache()
            cache_key = str(hash(tuple((m.role, m.content) for m in messages)))
            cache.set(cache_key, response.content or "")
        except Exception:
            pass

        return response

    def chat_stream(self, messages: List[ChatMessage]) -> Generator[str, None, None]:
        provider = self._get_provider()
        try:
            yield from provider.chat_stream(messages)
        except NotImplementedError:
            response = self.chat(messages)
            if response.content:
                yield response.content
            else:
                yield ""
        except Exception as e:
            logger.error(f"流式输出异常: {e}")
            yield f"[流式输出错误: {e}]"

    @property
    def supports_tools(self) -> bool:
        return self.provider in ("openai", "anthropic", "ollama", "openrouter", "gemini", "qwen")

    def chat_with_tools(
        self,
        messages: List[ChatMessage],
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> ChatResponse:
        if not tools:
            return self.chat(messages)

        provider = self._get_provider()
        return self._call_with_retry_stats(
            lambda: provider.chat_with_tools(messages, tools)
        )

    def test_connection(self) -> Dict[str, Any]:
        try:
            response = self.chat([ChatMessage("user", "Say 'OK' only.")])
            return {
                "success": True,
                "provider": self.provider,
                "model": response.model,
                "response_preview": response.content[:50],
            }
        except Exception as e:
            return {
                "success": False,
                "provider": self.provider,
                "error": str(e),
            }

    def switch_provider(self, provider: str, model: Optional[str] = None) -> None:
        self.provider = provider
        if model:
            if provider == "openai":
                self.openai_cfg["model"] = model
            elif provider == "anthropic":
                self.anthropic_cfg["model"] = model
            elif provider == "ollama":
                self.ollama_cfg["model"] = model
            elif provider == "openrouter":
                self.openrouter_cfg["model"] = model
            elif provider == "gemini":
                self.gemini_cfg["model"] = model
            elif provider == "qwen":
                self.qwen_cfg["model"] = model

    def get_usage_stats(self) -> Dict[str, Any]:
        with self._stats_lock:
            return {
                "total_prompt_tokens": self.total_prompt_tokens,
                "total_completion_tokens": self.total_completion_tokens,
                "total_tokens": self.total_prompt_tokens + self.total_completion_tokens,
                "total_calls": self.total_calls,
            }
