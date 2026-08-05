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
        # 诊断：打印 LLM 配置状态（不打印 key）
        _llm_logger = logging.getLogger("Castorice.ModelAdapter")
        _freellm_key = self.freellmapi_cfg.get("api_key", "")
        _llm_logger.info(
            f"LLM provider={self.provider} timeout={self.timeout}s retries={self.max_retries} "
            f"freellmapi: base_url={self.freellmapi_cfg.get('base_url','?')} "
            f"model={self.freellmapi_cfg.get('model','?')} "
            f"api_key={'SET(' + str(len(_freellm_key)) + 'chars)' if _freellm_key else 'EMPTY'}"
        )

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
        # 自定义供应商配置（从 config 加载）
        self._custom_providers: Dict[str, Dict[str, Any]] = {}

        # P0-1/P0-2: 熔断器 + 降级管理器
        self._circuit_breaker = None
        self._degradation = None
        try:
            from castorice.health.circuit_breaker import CircuitBreaker
            self._circuit_breaker = CircuitBreaker(
                name=f"llm_{self.provider}",
                failure_threshold=5,
                recovery_timeout=30.0,
            )
        except Exception as e:
            logger.debug(f"熔断器初始化失败: {e}")

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

    # ========== 自定义供应商管理 ==========

    def register_custom_provider(
        self,
        provider_id: str,
        name: str,
        base_url: str,
        api_key: str = "",
        model: str = "",
    ) -> None:
        """注册自定义 OpenAI 兼容供应商"""
        provider_id = provider_id.strip().lower().replace(" ", "_")
        if not provider_id:
            raise ValueError("provider_id 不能为空")
        if provider_id in self._providers and provider_id not in self._custom_providers:
            raise ValueError(f"供应商 '{provider_id}' 是内置供应商，不可覆盖")

        self._custom_providers[provider_id] = {
            "id": provider_id,
            "name": name or provider_id,
            "base_url": base_url.rstrip("/"),
            "api_key": api_key,
            "model": model,
            "is_custom": True,
        }
        # 用 OpenAIProvider 作为统一实现（所有自定义供应商都走 OpenAI 兼容协议）
        self._providers[provider_id] = OpenAIProvider(self)
        logger.info(f"已注册自定义供应商: {provider_id} ({name})")

    def unregister_custom_provider(self, provider_id: str) -> bool:
        """注销自定义供应商"""
        if provider_id not in self._custom_providers:
            return False
        del self._custom_providers[provider_id]
        if provider_id in self._providers:
            del self._providers[provider_id]
        # 如果当前正在使用被删除的供应商，切回 openai
        if self.provider == provider_id:
            self.provider = "openai"
        logger.info(f"已注销自定义供应商: {provider_id}")
        return True

    def update_custom_provider(
        self,
        provider_id: str,
        name: Optional[str] = None,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
    ) -> bool:
        """更新自定义供应商配置"""
        if provider_id not in self._custom_providers:
            return False
        cfg = self._custom_providers[provider_id]
        if name is not None:
            cfg["name"] = name
        if base_url is not None:
            cfg["base_url"] = base_url.rstrip("/")
        if api_key is not None:
            cfg["api_key"] = api_key
        if model is not None:
            cfg["model"] = model
        logger.info(f"已更新自定义供应商: {provider_id}")
        return True

    def list_providers(self) -> List[Dict[str, Any]]:
        """列出所有可用供应商（内置 + 自定义）"""
        builtin_meta = {
            "openai": {"name": "OpenAI", "models": ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "gpt-3.5-turbo"]},
            "anthropic": {"name": "Anthropic Claude", "models": ["claude-3-5-sonnet-20241022", "claude-3-opus", "claude-3-haiku"]},
            "ollama": {"name": "Ollama", "models": ["llama3.1:8b", "qwen2.5:7b", "gemma2:9b"]},
            "openrouter": {"name": "OpenRouter", "models": ["anthropic/claude-3.5-sonnet", "openai/gpt-4o", "google/gemini-1.5-pro", "meta-llama/llama-3.1-405b", "mistralai/mistral-large"]},
            "gemini": {"name": "Google Gemini", "models": ["gemini-1.5-flash", "gemini-1.5-pro"]},
            "qwen": {"name": "通义千问", "models": ["qwen-plus", "qwen-max", "qwen-turbo"]},
            "freellmapi": {"name": "FreeLLMAPI", "models": ["default"]},
        }
        result = []
        # 内置供应商
        for pid, meta in builtin_meta.items():
            has_key = self._check_provider_has_key(pid)
            result.append({
                "id": pid,
                "name": meta["name"],
                "models": meta["models"],
                "has_key": has_key,
                "is_custom": False,
            })
        # 自定义供应商
        for pid, cfg in self._custom_providers.items():
            result.append({
                "id": pid,
                "name": cfg["name"],
                "models": [cfg["model"]] if cfg.get("model") else [],
                "has_key": bool(cfg.get("api_key")),
                "is_custom": True,
                "base_url": cfg["base_url"],
                "model": cfg.get("model", ""),
            })
        return result

    def _check_provider_has_key(self, provider_id: str) -> bool:
        """检查内置供应商是否配置了 API Key"""
        try:
            # 属性名格式: {provider_id}_cfg (无前缀下划线), 例如 freellmapi_cfg
            llm_cfg = getattr(self, f"{provider_id}_cfg", None)
            if llm_cfg and isinstance(llm_cfg, dict):
                return bool(llm_cfg.get("api_key"))
        except Exception:
            pass
        return False

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
        # 认证错误绝不重试（再试多少次也没用）
        if "401" in error_str or "unauthorized" in error_str or "invalid api key" in error_str or "missing credentials" in error_str:
            return False
        # 4xx 客户端错误一般不重试
        match_4xx = re.search(r'\b(4\d{2})\b', str(error))
        if match_4xx and match_4xx.group(1) != "429":
            return False
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
        # P0-1: 熔断器检查（OPEN 状态直接快速失败）
        if self._circuit_breaker and not self._circuit_breaker.is_available():
            stats = self._circuit_breaker.get_stats()
            raise LLMConnectionError(
                f"熔断器 [{stats['name']}] 处于 OPEN 状态，"
                f"已熔断 {stats['open_count']} 次，"
                f"{stats['thresholds']['recovery_timeout']}s 后恢复",
                details={"provider": self.provider, "circuit_breaker": stats},
            )

        last_error = None
        _t_total = time.time()
        for attempt in range(self.max_retries + 1):
            _t0 = time.time()
            try:
                logger.info(f"[LLM] 尝试 {attempt+1}/{self.max_retries+1} | provider={self.provider} timeout={self.timeout}s")
                response = call_fn()
                _dt = time.time() - _t0
                logger.info(f"[LLM] 尝试 {attempt+1} 成功 | 耗时={_dt:.1f}s | model={getattr(response, 'model', '?')}")
                with self._stats_lock:
                    if response.usage:
                        self.total_prompt_tokens += response.usage.get("prompt_tokens", 0)
                        self.total_completion_tokens += response.usage.get("completion_tokens", 0)
                    self.total_calls += 1
                # P0-2: 上报成功给熔断器和降级管理器
                if self._circuit_breaker:
                    try:
                        with self._circuit_breaker:
                            pass  # 空上下文用于记录成功
                    except Exception:
                        pass
                try:
                    deg = getattr(self, "_degradation", None) or getattr(self, "degradation_manager", None)
                    if deg:
                        deg.report_llm_result(True)
                except Exception:
                    pass
                # P1-4: 成本闸记录 token 用量
                try:
                    cb = getattr(self, "cost_budget", None)
                    if cb is not None and response.usage:
                        cb.record_usage(
                            response.usage.get("prompt_tokens", 0),
                            response.usage.get("completion_tokens", 0),
                        )
                except Exception as e:
                    logger.warning(f"[LLM] cost_budget 异常: {e}")
                try:
                    from castorice.metrics import get_metrics
                    metrics = get_metrics()
                    metrics.inc_counter("llm_calls_total", labels={"provider": self.provider, "status": "success"})
                    if response.usage:
                        metrics.add_tokens("llm_prompt_tokens", response.usage.get("prompt_tokens", 0), provider=self.provider)
                        metrics.add_tokens("llm_completion_tokens", response.usage.get("completion_tokens", 0), provider=self.provider)
                except ImportError:
                    pass
                except Exception as e:
                    logger.warning(f"[LLM] metrics 异常: {e}")
                return response
            except (httpx.HTTPError, httpx.TimeoutException, json.JSONDecodeError) as e:
                last_error = e
                _dt = time.time() - _t0
                logger.warning(f"[LLM] 尝试 {attempt+1} 失败 | 耗时={_dt:.1f}s | {type(e).__name__}: {str(e)[:120]}")
                try:
                    from castorice.metrics import get_metrics
                    metrics = get_metrics()
                    metrics.inc_counter("llm_calls_total", labels={"provider": self.provider, "status": "error"})
                    metrics.inc_error("llm_errors", provider=self.provider)
                except ImportError:
                    pass
                # P0-2: 上报失败（仅在最后一次尝试或不可重试时）
                is_last_attempt = attempt >= self.max_retries or not self._is_retryable_error(e)
                if is_last_attempt:
                    if self._circuit_breaker:
                        try:
                            with self._circuit_breaker:
                                raise e  # 触发熔断器记录失败
                        except type(e):
                            pass
                    try:
                        deg = getattr(self, "_degradation", None) or getattr(self, "degradation_manager", None)
                        if deg:
                            deg.report_llm_result(False)
                    except Exception:
                        pass
                if attempt < self.max_retries and self._is_retryable_error(e):
                    delay = self.retry_delay * (2 ** attempt)
                    logger.warning(f"LLM 调用第{attempt + 1}次失败，{delay}s 后重试: {e}")
                    time.sleep(delay)
                    continue
                raise self._wrap_llm_error(e)
            except Exception as e:
                last_error = e
                _dt = time.time() - _t0
                logger.exception(f"[LLM] 尝试 {attempt+1} 未预期异常 | 耗时={_dt:.1f}s | {type(e).__name__}")
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