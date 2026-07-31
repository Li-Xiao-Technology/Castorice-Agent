import json
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
from castorice.exceptions import (
    LLMError, LLMConnectionError, LLMTimeoutError,
    LLMAuthError, LLMRateLimitError, LLMResponseError,
)

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
    - freellmapi  : FreeLLMAPI（OpenAI 兼容协议）
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
        self.freellmapi_cfg = llm_config.get("freellmapi", {})

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
            "freellmapi": OpenAIProvider(self),
            "anthropic": AnthropicProvider(self),
            "gemini": GeminiProvider(self),
            "qwen": QwenProvider(self),
        }

    def update_config(self, updates):
        """Runtime update of generation params (takes effect immediately)

        Supported: temperature, max_tokens, timeout, provider
        Returns the actually applied updates
        """
        applied = {}
        with self._stats_lock:
            if 'temperature' in updates and updates['temperature'] is not None:
                self.temperature = float(updates["temperature"])
                applied['temperature'] = self.temperature
            if 'max_tokens' in updates and updates['max_tokens'] is not None:
                self.max_tokens = int(updates["max_tokens"])
                applied['max_tokens'] = self.max_tokens
            if 'timeout' in updates and updates['timeout'] is not None:
                self.timeout = int(updates["timeout"])
                applied['timeout'] = self.timeout
            if 'provider' in updates and updates['provider'] is not None:
                self.provider = str(updates["provider"])
                applied['provider'] = self.provider
        if applied:
            logging.getLogger("Castorice.ModelAdapter").info(
                f"Runtime config update: {applied}"
            )
        return applied

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
            if self._anthropic is not None:
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

    def _wrap_llm_error(self, error: Exception) -> Exception:
        """将原始 LLM 异常包装为结构化异常，便于上层分级处理"""
        error_str = str(error).lower()

        if isinstance(error, (LLMError, LLMConnectionError, LLMTimeoutError,
                              LLMAuthError, LLMRateLimitError, LLMResponseError)):
            return error

        if "401" in error_str or "unauthorized" in error_str or "auth" in error_str:
            return LLMAuthError(str(error), details={"provider": self.provider})

        if "429" in error_str or "rate limit" in error_str or "rate_limit" in error_str:
            return LLMRateLimitError(str(error), details={"provider": self.provider})

        if "timeout" in error_str or "timed out" in error_str:
            return LLMTimeoutError(str(error), details={"provider": self.provider})

        if "connection" in error_str or "network" in error_str:
            return LLMConnectionError(str(error), details={"provider": self.provider})

        if "json" in error_str or "decode" in error_str or "parse" in error_str:
            return LLMResponseError(str(error), details={"provider": self.provider})

        return LLMError(str(error), details={"provider": self.provider, "original_type": type(error).__name__})

    def _call_with_retry_stats(self, call_fn) -> ChatResponse:
        last_error = None
        for attempt in range(self.max_retries + 1):
            try:
                response = call_fn()
                with self._stats_lock:
                    if response.usage:
                        self.total_prompt_tokens += response.usage.get("prompt_tokens", 0)
                        self.total_completion_tokens += response.usage.get("completion_tokens", 0)
                    self.total_calls += 1
                # P1-4: 成本闸记录 token 用量
                try:
                    cb = getattr(self, "cost_budget", None)
                    if cb is not None and response.usage:
                        cb.record_usage(
                            response.usage.get("prompt_tokens", 0),
                            response.usage.get("completion_tokens", 0),
                        )
                except Exception:
                    pass
                try:
                    from castorice.metrics import get_metrics
                    metrics = get_metrics()
                    metrics.inc_counter("llm_calls_total", labels={"provider": self.provider, "status": "success"})
                    if response.usage:
                        metrics.add_tokens("llm_prompt_tokens", response.usage.get("prompt_tokens", 0), provider=self.provider)
                        metrics.add_tokens("llm_completion_tokens", response.usage.get("completion_tokens", 0), provider=self.provider)
                except ImportError:
                    pass
                return response
            except (httpx.HTTPError, httpx.TimeoutException, json.JSONDecodeError) as e:
                last_error = e
                try:
                    from castorice.metrics import get_metrics
                    metrics = get_metrics()
                    metrics.inc_counter("llm_calls_total", labels={"provider": self.provider, "status": "error"})
                    metrics.inc_error("llm_errors", provider=self.provider)
                except ImportError:
                    pass
                if attempt < self.max_retries and self._is_retryable_error(e):
                    delay = self.retry_delay * (2 ** attempt)
                    logger.warning(f"LLM 调用第{attempt + 1}次失败，{delay}s 后重试: {e}")
                    time.sleep(delay)
                    continue
                raise self._wrap_llm_error(e)
            except Exception as e:
                last_error = e
                logger.exception("LLM 调用发生未预期异常")
                try:
                    from castorice.metrics import get_metrics
                    metrics = get_metrics()
                    metrics.inc_counter("llm_calls_total", labels={"provider": self.provider, "status": "error"})
                    metrics.inc_error("llm_errors", provider=self.provider)
                except ImportError:
                    pass
                raise self._wrap_llm_error(e)
        if last_error:
            raise self._wrap_llm_error(last_error)
        raise LLMError("未执行任何重试", details={"provider": self.provider})

    def chat(self, messages: List[ChatMessage]) -> ChatResponse:
        try:
            from castorice.llm_cache import get_global_cache
            cache = get_global_cache()
            model_name = self._get_current_model_name()
            msg_dicts = [{"role": m.role, "content": m.content} for m in messages]
            cached = cache.get(msg_dicts, model_name, self.temperature)
            if cached is not None:
                logger.debug(f"LLM 缓存命中（增强版）: model={model_name}")
                return ChatResponse(content=cached, model=model_name)
        except (ImportError, OSError) as e:
            logger.debug(f"增强版缓存读取失败: {e}")

        response = self._call_with_retry_stats(
            lambda: self._get_provider().chat(messages)
        )

        try:
            from castorice.llm_cache import get_global_cache
            cache = get_global_cache()
            model_name = self._get_current_model_name()
            msg_dicts = [{"role": m.role, "content": m.content} for m in messages]
            cache.set(msg_dicts, model_name, self.temperature, response.content or "")
        except (ImportError, OSError) as e:
            logger.debug(f"写入 LLM 缓存失败: {e}")

        return response

    def _get_current_model_name(self) -> str:
        """获取当前使用的模型名（用于缓存 key）"""
        try:
            provider_cfg = self._get_provider_config()
            return provider_cfg.get("model", self.provider)
        except (KeyError, AttributeError):
            return self.provider

    def _get_provider_config(self) -> Dict[str, Any]:
        """获取当前 provider 的配置"""
        provider = self.provider.lower()
        config_map = {
            "openai": self.openai_cfg,
            "anthropic": self.anthropic_cfg,
            "ollama": self.ollama_cfg,
            "openrouter": self.openrouter_cfg,
            "gemini": self.gemini_cfg,
            "qwen": self.qwen_cfg,
            "freellmapi": self.freellmapi_cfg,
        }
        return config_map.get(provider, {}) or {}

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
        except (httpx.HTTPError, httpx.TimeoutException, json.JSONDecodeError) as e:
            logger.error(f"流式输出异常: {e}")
            yield f"[流式输出错误: {e}]"

    @property
    def supports_tools(self) -> bool:
        return self.provider in ("openai", "anthropic", "ollama", "openrouter", "freellmapi", "gemini", "qwen")

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
        except (httpx.HTTPError, httpx.TimeoutException, json.JSONDecodeError) as e:
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
            elif provider == "freellmapi":
                self.freellmapi_cfg["model"] = model

    def get_usage_stats(self) -> Dict[str, Any]:
        with self._stats_lock:
            return {
                "total_prompt_tokens": self.total_prompt_tokens,
                "total_completion_tokens": self.total_completion_tokens,
                "total_tokens": self.total_prompt_tokens + self.total_completion_tokens,
                "total_calls": self.total_calls,
            }