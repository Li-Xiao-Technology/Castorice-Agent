"""
统一模型适配层 (ModelAdapter)

自研多模型兼容层：
- 不依赖 LangChain 任何分包
- 直接调用各厂商官方 SDK
- 支持 OpenAI 协议兼容（Ollama / OpenRouter / 通义千问 / 千帆 等）

支持的 provider:
- openai      : OpenAI 官方（兼容 通义千问 / 百度千帆 等）
- anthropic   : Claude 官方
- ollama      : 本地大模型（OpenAI 协议）
- openrouter  : 多模型聚合（OpenAI 协议）
- gemini      : Google Gemini 官方 SDK
- qwen        : 阿里云通义千问官方 SDK

设计理念：
1. **统一接口**：通过 chat() 抽象方法统一所有供应商
2. **官方 SDK 优先**：用各厂商官方 SDK，不引入中间层
3. **协议兼容**：OpenAI 兼容协议下统一用 openai SDK
4. **动态加载**：SDK 按需导入，不强制依赖
"""

import json
import logging
import re
import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, Generator, List, Optional

logger = logging.getLogger("Castorice.ModelAdapter")

# 官方 SDK（动态加载）
try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

try:
    import anthropic
except ImportError:
    anthropic = None

try:
    import google.genai as genai
except ImportError:
    try:
        import google.generativeai as genai
    except ImportError:
        genai = None

try:
    from dashscope import Generation
except ImportError:
    Generation = None

import httpx


@dataclass
class ToolCall:
    """工具调用结构（Function Calling 返回）"""
    id: str
    name: str
    arguments: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "type": "function",
            "function": {
                "name": self.name,
                "arguments": json.dumps(self.arguments, ensure_ascii=False),
            },
        }


class ChatMessage:
    """统一的对话消息结构（所有供应商通用）"""

    def __init__(
        self,
        role: str,
        content: Optional[str] = None,
        tool_calls: Optional[List[ToolCall]] = None,
        tool_call_id: Optional[str] = None,
        name: Optional[str] = None,
    ):
        self.role = role           # 'system' / 'user' / 'assistant' / 'tool'
        self.content = content
        self.tool_calls = tool_calls or []
        self.tool_call_id = tool_call_id  # 工具结果消息的 call_id
        self.name = name           # 工具结果消息的工具名

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {"role": self.role}
        if self.content is not None:
            d["content"] = self.content
        if self.tool_calls:
            d["tool_calls"] = [tc.to_dict() for tc in self.tool_calls]
        if self.tool_call_id:
            d["tool_call_id"] = self.tool_call_id
        if self.name:
            d["name"] = self.name
        return d

    def to_anthropic_dict(self) -> Dict[str, Any]:
        """转为 Anthropic 消息格式"""
        if self.role == "tool":
            return {
                "role": "user",
                "content": [{
                    "type": "tool_result",
                    "tool_use_id": self.tool_call_id or "",
                    "content": self.content or "",
                }],
            }
        if self.tool_calls:
            blocks: List[Dict[str, Any]] = []
            if self.content:
                blocks.append({"type": "text", "text": self.content})
            for tc in self.tool_calls:
                blocks.append({
                    "type": "tool_use",
                    "id": tc.id,
                    "name": tc.name,
                    "input": tc.arguments,
                })
            return {"role": "assistant", "content": blocks}
        return {"role": self.role, "content": self.content or ""}


class ChatResponse:
    """统一的模型回复结构"""

    def __init__(
        self,
        content: str = "",
        model: str = "",
        usage: Optional[Dict] = None,
        tool_calls: Optional[List[ToolCall]] = None,
    ):
        self.content = content or ""
        self.model = model
        self.usage = usage or {}
        self.tool_calls = tool_calls or []
        self.has_tool_calls = len(self.tool_calls) > 0


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

        # 重试配置
        self.max_retries = llm_config.get("max_retries", 3)
        self.retry_delay = llm_config.get("retry_delay", 1.0)

        # 各 provider 配置
        self.openai_cfg = llm_config.get("openai", {})
        self.anthropic_cfg = llm_config.get("anthropic", {})
        self.ollama_cfg = llm_config.get("ollama", {})
        self.openrouter_cfg = llm_config.get("openrouter", {})
        self.gemini_cfg = llm_config.get("gemini", {})
        self.qwen_cfg = llm_config.get("qwen", {})

        # 懒加载客户端
        self._openai_clients: Dict[str, OpenAI] = {}
        self._anthropic_client = None
        self._gemini_model = None
        # P1-11: 懒加载客户端的线程锁（双重检查锁）
        self._openai_clients_lock = threading.Lock()
        self._anthropic_client_lock = threading.Lock()
        self._gemini_model_lock = threading.Lock()
        # P2-4: tool_choice 从配置读取，默认 "auto"
        self.tool_choice = llm_config.get("tool_choice", "auto")

        # Token 使用量统计线程锁（保护并发场景下的累加与读取）
        self._stats_lock = threading.Lock()

        # Token 使用量统计
        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0
        self.total_calls = 0

    def _get_openai_client(self, base_url: str, api_key: str) -> OpenAI:
        """懒加载 OpenAI 兼容客户端（OpenAI / Ollama / OpenRouter 共用）

        P1-11: 双重检查锁保证多线程下客户端只创建一次
        """
        if OpenAI is None:
            raise ImportError("请安装 openai SDK: pip install openai")
        key = f"{base_url}|{api_key}"
        # P1-11: 双重检查锁
        if key not in self._openai_clients:
            with self._openai_clients_lock:
                if key not in self._openai_clients:
                    self._openai_clients[key] = OpenAI(
                        api_key=api_key or "EMPTY",
                        base_url=base_url,
                        timeout=self.timeout,
                    )
        return self._openai_clients[key]

    def _get_anthropic_client(self):
        """懒加载 Anthropic 客户端（线程安全）"""
        if anthropic is None:
            raise ImportError("请安装 anthropic SDK: pip install anthropic")
        with self._anthropic_client_lock:
            if self._anthropic_client is None:
                self._anthropic_client = anthropic.Anthropic(
                    api_key=self.anthropic_cfg.get("api_key", ""),
                    base_url=self.anthropic_cfg.get("base_url"),
                    timeout=self.timeout,
                )
        return self._anthropic_client

    def _get_gemini_model(self):
        """懒加载 Google Gemini 模型（P1-11: 双重检查锁）"""
        if genai is None:
            raise ImportError("请安装 Google Gemini SDK: pip install google-generativeai")
        if self._gemini_model is None:
            with self._gemini_model_lock:
                if self._gemini_model is None:
                    genai.configure(api_key=self.gemini_cfg.get("api_key", ""))
                    self._gemini_model = genai.GenerativeModel(
                        self.gemini_cfg.get("model", "gemini-1.5-flash")
                    )
        return self._gemini_model

    def _is_retryable_error(self, error: Exception) -> bool:
        """判断错误是否可重试

        P1-8: 覆盖 Anthropic / Gemini / Qwen SDK 的异常，不仅限于 OpenAI
        """
        error_str = str(error).lower()
        # 网络错误、超时
        if any(keyword in error_str for keyword in ["timeout", "connection", "network", "timed out"]):
            return True
        # 速率限制
        if "429" in error_str or "rate limit" in error_str or "rate_limit" in error_str:
            return True
        # 5xx 服务端错误
        match = re.search(r'\b(5\d{2})\b', str(error))
        if match:
            return True
        # OpenAI SDK 特定异常
        try:
            from openai import APIError, APIConnectionError, RateLimitError, APITimeoutError
            if isinstance(error, (APIConnectionError, RateLimitError, APITimeoutError)):
                return True
            if isinstance(error, APIError) and hasattr(error, 'status_code') and error.status_code and error.status_code >= 500:
                return True
        except ImportError:
            pass
        # P1-8: Anthropic SDK 特定异常
        try:
            if anthropic is not None:
                from anthropic import APIError as AnthropicAPIError, APIConnectionError as AnthropicAPIConnectionError
                from anthropic import RateLimitError as AnthropicRateLimitError, APITimeoutError as AnthropicAPITimeoutError
                if isinstance(error, (AnthropicAPIConnectionError, AnthropicRateLimitError, AnthropicAPITimeoutError)):
                    return True
                if isinstance(error, AnthropicAPIError) and hasattr(error, 'status_code') and error.status_code and error.status_code >= 500:
                    return True
        except ImportError:
            pass
        # P1-8: httpx 网络异常（Gemini/Qwen 底层可能用 httpx）
        try:
            if isinstance(error, (httpx.ConnectError, httpx.ReadTimeout, httpx.ConnectTimeout, httpx.PoolTimeout)):
                return True
        except AttributeError:
            pass
        return False

    def _chat_with_retry(self, messages: List[ChatMessage]) -> ChatResponse:
        """带指数退避重试的 chat 调用（P2-10: 复用 _call_with_retry_stats）"""
        return self._call_with_retry_stats(
            lambda: self._chat_implementation(messages)
        )

    def _call_with_retry_stats(self, call_fn) -> ChatResponse:
        """
        P2-10: 抽出通用的「指数退避重试 + token 统计」逻辑
        被 _chat_with_retry 和 chat_with_tools 复用，避免代码重复。
        """
        last_error = None
        for attempt in range(self.max_retries):
            try:
                response = call_fn()
                # 累加 token 统计（线程安全，避免并发累加丢失）
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

    def _chat_implementation(self, messages: List[ChatMessage]) -> ChatResponse:
        """实际的 chat 实现（无重试包装）"""
        if self.provider == "openai":
            return self._chat_openai(messages, self.openai_cfg)
        elif self.provider == "anthropic":
            return self._chat_anthropic(messages)
        elif self.provider == "ollama":
            return self._chat_openai(messages, {
                "api_key": "ollama",
                "base_url": self.ollama_cfg.get("base_url", "http://localhost:11434/v1"),
                "model": self.ollama_cfg.get("model", "llama3.1:8b"),
            })
        elif self.provider == "openrouter":
            return self._chat_openai(messages, {
                "api_key": self.openrouter_cfg.get("api_key", ""),
                "base_url": self.openrouter_cfg.get("base_url", "https://openrouter.ai/api/v1"),
                "model": self.openrouter_cfg.get("model", "anthropic/claude-3.5-sonnet"),
            })
        elif self.provider == "gemini":
            return self._chat_gemini(messages)
        elif self.provider == "qwen":
            return self._chat_qwen(messages)
        else:
            raise ValueError(f"不支持的模型供应商: {self.provider}")

    def chat(self, messages: List[ChatMessage]) -> ChatResponse:
        """
        统一对话接口（带重试）

        参数：
            messages: 消息列表，按时间顺序

        返回：
            ChatResponse: 统一格式的回复
        """
        return self._chat_with_retry(messages)

    def chat_stream(self, messages: List[ChatMessage]) -> Generator[str, None, None]:
        """
        流式对话接口，逐字返回 LLM 响应。
        仅支持 OpenAI 兼容协议（openai/ollama/openrouter）。
        其他 provider 回退为非流式（一次性返回完整内容）。
        """
        if self.provider == "openai":
            yield from self._chat_openai_stream(messages, self.openai_cfg)
        elif self.provider == "ollama":
            yield from self._chat_openai_stream(messages, {
                "api_key": "ollama",
                "base_url": self.ollama_cfg.get("base_url", "http://localhost:11434/v1"),
                "model": self.ollama_cfg.get("model", "llama3.1:8b"),
            })
        elif self.provider == "openrouter":
            yield from self._chat_openai_stream(messages, {
                "api_key": self.openrouter_cfg.get("api_key", ""),
                "base_url": self.openrouter_cfg.get("base_url", "https://openrouter.ai/api/v1"),
                "model": self.openrouter_cfg.get("model", "anthropic/claude-3.5-sonnet"),
            })
        elif self.provider == "gemini":
            yield from self._chat_gemini_stream(messages)
        elif self.provider == "qwen":
            yield from self._chat_qwen_stream(messages)
        elif self.provider == "anthropic":
            # anthropic 暂不支持流式，回退为非流式一次性返回
            response = self.chat(messages)
            yield response.content
        else:
            response = self.chat(messages)
            yield response.content

    def _chat_openai(self, messages: List[ChatMessage], cfg: Dict[str, Any]) -> ChatResponse:
        """OpenAI 兼容协议（OpenAI / Ollama / OpenRouter 等）"""
        client = self._get_openai_client(cfg.get("base_url", ""), cfg.get("api_key", ""))
        # 转换消息格式
        api_messages = [m.to_dict() for m in messages]

        # 调用 API
        response = client.chat.completions.create(
            model=cfg.get("model", "gpt-4o"),
            messages=api_messages,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
        )

        content = response.choices[0].message.content or ""
        usage = {}
        if hasattr(response, "usage") and response.usage:
            usage = {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            }
        return ChatResponse(content=content, model=response.model, usage=usage)

    def _chat_openai_stream(self, messages: List[ChatMessage], cfg: Dict[str, Any]) -> Generator[str, None, None]:
        """OpenAI 兼容协议流式输出（OpenAI / Ollama / OpenRouter 等）

        P1-9: 启用 stream_options={"include_usage": True}，最后一个 chunk 会带 usage，
        累加到全局统计。
        """
        client = self._get_openai_client(cfg.get("base_url", ""), cfg.get("api_key", ""))
        # 转换消息格式
        api_messages = [m.to_dict() for m in messages]

        # 流式调用不需要重试（流式中断由用户重新发起）
        # P1-9: 加 stream_options 让最后一个 chunk 返回 usage 统计
        try:
            stream = client.chat.completions.create(
                model=cfg.get("model", "gpt-4o"),
                messages=api_messages,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                stream=True,
                stream_options={"include_usage": True},
            )
        except Exception:
            # 某些 OpenAI 兼容后端不支持 stream_options，回退
            stream = client.chat.completions.create(
                model=cfg.get("model", "gpt-4o"),
                messages=api_messages,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                stream=True,
            )

        # 逐个 chunk 提取增量内容并 yield
        # P1-9: 最后一个 chunk 可能带 usage 字段，累加到统计
        for chunk in stream:
            # P1-9: 处理 usage（最后一个 chunk 通常 choices 为空，但带 usage）
            if hasattr(chunk, "usage") and chunk.usage:
                with self._stats_lock:
                    self.total_prompt_tokens += getattr(chunk.usage, "prompt_tokens", 0) or 0
                    self.total_completion_tokens += getattr(chunk.usage, "completion_tokens", 0) or 0
                    self.total_calls += 1
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if delta and delta.content:
                yield delta.content

    def _chat_anthropic(self, messages: List[ChatMessage]) -> ChatResponse:
        """Anthropic Claude 官方 SDK

        P2-8: 使用 to_anthropic_dict() 正确处理 tool 角色消息和 tool_calls，
        而不是直接拼成 {"role": m.role, "content": m.content}（会丢失 tool_calls 和 tool 结果）。
        """
        client = self._get_anthropic_client()

        # Anthropic 消息格式：system 单独，user/assistant 交替（含 tool_result / tool_use）
        system_msg = None
        api_messages = []
        for m in messages:
            if m.role == "system":
                system_msg = m.content
            else:
                # P2-8: 用 to_anthropic_dict() 处理 tool 角色和 tool_calls
                api_messages.append(m.to_anthropic_dict())

        # 合并连续同角色纯文本消息（与 _chat_anthropic_with_tools 同款逻辑）
        merged_messages = []
        for msg in api_messages:
            if merged_messages and merged_messages[-1]["role"] == msg["role"]:
                prev = merged_messages[-1]
                if isinstance(prev["content"], list) and isinstance(msg["content"], list):
                    prev["content"].extend(msg["content"])
                elif isinstance(prev["content"], list):
                    prev["content"].append({"type": "text", "text": str(msg["content"])})
                elif isinstance(msg["content"], list):
                    merged_messages.append(msg)
                else:
                    prev["content"] = str(prev.get("content", "")) + "\n" + str(msg["content"])
            else:
                merged_messages.append(msg)

        kwargs = {
            "model": self.anthropic_cfg.get("model", "claude-3-5-sonnet-20241022"),
            "messages": merged_messages,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
        }
        if system_msg:
            kwargs["system"] = system_msg

        response = client.messages.create(**kwargs)
        content = ""
        # P2-8: 也解析可能的 tool_use 块（即使没传 tools，历史消息里可能有 tool_calls 上下文）
        tool_calls = []
        if response.content:
            for block in response.content:
                if hasattr(block, "type"):
                    if block.type == "text":
                        content += block.text
                    elif block.type == "tool_use":
                        tool_calls.append(ToolCall(
                            id=block.id,
                            name=block.name,
                            arguments=block.input if isinstance(block.input, dict) else {},
                        ))
                elif hasattr(block, "text"):
                    content += block.text

        usage = {}
        if hasattr(response, "usage") and response.usage:
            prompt_tokens = response.usage.input_tokens
            completion_tokens = response.usage.output_tokens
            usage = {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
            }
        return ChatResponse(content=content, model=response.model, usage=usage, tool_calls=tool_calls)

    def _chat_gemini(self, messages: List[ChatMessage]) -> ChatResponse:
        """Google Gemini 官方 SDK"""
        model = self._get_gemini_model()
        
        # Gemini 消息格式：system 单独处理
        system_parts = []
        chat_parts = []
        for m in messages:
            if m.role == "system":
                system_parts.append(m.content)
            else:
                role = "user" if m.role == "user" else "model"
                chat_parts.append({"role": role, "parts": [m.content]})
        
        system_instruction = "\n".join(system_parts) if system_parts else None
        
        response = model.generate_content(
            chat_parts,
            generation_config={
                "temperature": self.temperature,
                "max_output_tokens": self.max_tokens,
            },
            system_instruction=system_instruction,
        )
        
        content = ""
        try:
            content = response.text or ""
        except Exception as e:
            logger.warning(f"Gemini 获取响应内容失败（可能被安全过滤）: {e}")
            content = "[内容被安全过滤]"
        usage = {}
        if hasattr(response, "usage_metadata") and response.usage_metadata:
            meta = response.usage_metadata
            usage = {
                "prompt_tokens": meta.prompt_token_count,
                "completion_tokens": meta.candidates_token_count,
                "total_tokens": meta.total_token_count,
            }
        
        return ChatResponse(content=content, model=self.gemini_cfg.get("model", "gemini-1.5-flash"), usage=usage)

    def _chat_qwen(self, messages: List[ChatMessage]) -> ChatResponse:
        """阿里云通义千问官方 SDK"""
        if Generation is None:
            raise ImportError("请安装通义千问 SDK: pip install dashscope")
        
        # 构建消息
        api_messages = []
        for m in messages:
            api_messages.append({"role": m.role, "content": m.content})
        
        response = Generation.call(
            model=self.qwen_cfg.get("model", "qwen-plus"),
            messages=api_messages,
            api_key=self.qwen_cfg.get("api_key", ""),
            temperature=self.temperature,
            max_result_length=self.max_tokens,
        )
        
        if response.status_code != 200:
            error_msg = getattr(response, 'message', '') or str(response)
            raise RuntimeError(f"通义千问 API 调用失败 (status_code={response.status_code}): {error_msg}")
        
        content = response.output.choices[0].message.content
        
        usage = {}
        if response.usage:
            usage = {
                "prompt_tokens": response.usage.input_tokens,
                "completion_tokens": response.usage.output_tokens,
                "total_tokens": response.usage.total_tokens,
            }
        
        return ChatResponse(content=content, model=self.qwen_cfg.get("model", "qwen-plus"), usage=usage)

    def _chat_gemini_stream(self, messages: List[ChatMessage]) -> Generator[str, None, None]:
        """Google Gemini 流式输出"""
        model = self._get_gemini_model()
        system_parts = []
        chat_parts = []
        for m in messages:
            if m.role == "system":
                system_parts.append(m.content)
            else:
                role = "user" if m.role == "user" else "model"
                chat_parts.append({"role": role, "parts": [m.content]})
        system_instruction = "\n".join(system_parts) if system_parts else None

        response = model.generate_content(
            chat_parts,
            generation_config={
                "temperature": self.temperature,
                "max_output_tokens": self.max_tokens,
            },
            system_instruction=system_instruction,
            stream=True,
        )
        for chunk in response:
            try:
                if chunk.text:
                    yield chunk.text
            except Exception as e:
                logger.warning(f"Gemini 流式获取内容失败（可能被安全过滤）: {e}")
                yield "[内容被安全过滤]"

    def _chat_qwen_stream(self, messages: List[ChatMessage]) -> Generator[str, None, None]:
        """阿里云通义千问流式输出"""
        if Generation is None:
            raise ImportError("请安装通义千问 SDK: pip install dashscope")

        api_messages = []
        for m in messages:
            api_messages.append({"role": m.role, "content": m.content})

        responses = Generation.call(
            model=self.qwen_cfg.get("model", "qwen-plus"),
            messages=api_messages,
            api_key=self.qwen_cfg.get("api_key", ""),
            temperature=self.temperature,
            max_result_length=self.max_tokens,
            result_format="message",
            stream=True,
            incremental_output=True,
        )
        for response in responses:
            if response.status_code == 200:
                choice = response.output.choices[0]
                if choice.message.content:
                    yield choice.message.content

    @property
    def supports_tools(self) -> bool:
        """当前 provider 是否支持原生 Function Calling"""
        return self.provider in ("openai", "anthropic", "ollama", "openrouter", "gemini", "qwen")

    def chat_with_tools(
        self,
        messages: List[ChatMessage],
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> ChatResponse:
        """
        带 Function Calling 的对话接口（带重试 + Token 统计）

        P2-10: 复用 _call_with_retry_stats，避免与 _chat_with_retry 重复实现。
        """
        if not tools:
            return self.chat(messages)

        if self.provider in ("openai", "ollama", "openrouter"):
            return self._call_with_retry_stats(
                lambda: self._chat_openai_with_tools(messages, tools)
            )
        elif self.provider == "anthropic":
            return self._call_with_retry_stats(
                lambda: self._chat_anthropic_with_tools(messages, tools)
            )
        elif self.provider == "gemini":
            return self._call_with_retry_stats(
                lambda: self._chat_gemini_with_tools(messages, tools)
            )
        elif self.provider == "qwen":
            return self._call_with_retry_stats(
                lambda: self._chat_qwen_with_tools(messages, tools)
            )
        else:
            logger.warning(f"Provider '{self.provider}' 不支持原生 FC，回退到普通 chat（工具描述丢失）")
            return self.chat(messages)

    def _chat_openai_with_tools(
        self,
        messages: List[ChatMessage],
        tools: List[Dict[str, Any]],
        cfg: Optional[Dict[str, Any]] = None,
    ) -> ChatResponse:
        """OpenAI 兼容协议带 Function Calling"""

        if cfg is None:
            cfg = self.openai_cfg

        client = self._get_openai_client(cfg.get("base_url", ""), cfg.get("api_key", ""))

        api_messages = [m.to_dict() for m in messages]

        response = client.chat.completions.create(
            model=cfg.get("model", "gpt-4o"),
            messages=api_messages,
            tools=tools,
            # P2-4: tool_choice 从配置读取，默认 "auto"
            tool_choice=self.tool_choice,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
        )

        message = response.choices[0].message
        content = message.content or ""

        tool_calls = []
        if message.tool_calls:
            for tc in message.tool_calls:
                try:
                    args = json.loads(tc.function.arguments)
                except (json.JSONDecodeError, TypeError):
                    args = {}
                tool_calls.append(ToolCall(
                    id=tc.id,
                    name=tc.function.name,
                    arguments=args,
                ))

        usage = {}
        if hasattr(response, "usage") and response.usage:
            usage = {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            }

        return ChatResponse(
            content=content,
            model=response.model,
            usage=usage,
            tool_calls=tool_calls,
        )

    def _chat_anthropic_with_tools(
        self,
        messages: List[ChatMessage],
        tools: List[Dict[str, Any]],
    ) -> ChatResponse:
        """Anthropic Claude 带 Function Calling"""
        client = self._get_anthropic_client()

        # Anthropic 消息格式：system 单独，user/assistant 交替（含 tool_result / tool_use）
        system_msg = None
        api_messages = []
        for m in messages:
            if m.role == "system":
                system_msg = m.content
            else:
                api_messages.append(m.to_anthropic_dict())

        # 合并连续的同角色消息（Anthropic 要求 user/assistant 严格交替）
        # P2-9: 不能合并包含 tool_use / tool_result 块的消息，否则会破坏 tool_use_id 配对关系
        def _has_tool_block(msg: Dict[str, Any]) -> bool:
            """判断消息的 content 是否包含 tool_use 或 tool_result 块"""
            if not isinstance(msg.get("content"), list):
                return False
            for block in msg["content"]:
                if isinstance(block, dict) and block.get("type") in ("tool_use", "tool_result"):
                    return True
            return False

        merged_messages = []
        for msg in api_messages:
            # P2-9: 含 tool_use/tool_result 块的消息不参与合并，独立成条
            if _has_tool_block(msg):
                merged_messages.append(msg)
                continue
            if merged_messages and merged_messages[-1]["role"] == msg["role"]:
                # 同角色合并 content（仅合并纯文本消息）
                prev = merged_messages[-1]
                if _has_tool_block(prev):
                    # 前一条含 tool 块，不能合并，追加新消息
                    merged_messages.append(msg)
                elif isinstance(prev["content"], list) and isinstance(msg["content"], list):
                    prev["content"].extend(msg["content"])
                elif isinstance(prev["content"], list):
                    prev["content"].append({"type": "text", "text": str(msg["content"])})
                elif isinstance(msg["content"], list):
                    merged_messages.append(msg)  # 无法合并，追加
                else:
                    prev["content"] = str(prev.get("content", "")) + "\n" + str(msg["content"])
            else:
                merged_messages.append(msg)

        kwargs = {
            "model": self.anthropic_cfg.get("model", "claude-3-5-sonnet-20241022"),
            "messages": merged_messages,
            "tools": tools,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            # tool_choice: auto=模型自行决定是否调用工具，避免 Claude 在某些场景下"忘记"调工具
            "tool_choice": {"type": "auto"},
        }
        if system_msg:
            kwargs["system"] = system_msg

        response = client.messages.create(**kwargs)

        content = ""
        tool_calls = []
        for block in response.content:
            if hasattr(block, "type"):
                if block.type == "text":
                    content += block.text
                elif block.type == "tool_use":
                    tool_calls.append(ToolCall(
                        id=block.id,
                        name=block.name,
                        arguments=block.input if isinstance(block.input, dict) else {},
                    ))

        usage = {}
        if hasattr(response, "usage") and response.usage:
            prompt_tokens = response.usage.input_tokens
            completion_tokens = response.usage.output_tokens
            usage = {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
            }

        return ChatResponse(
            content=content,
            model=response.model,
            usage=usage,
            tool_calls=tool_calls,
        )

    def _chat_gemini_with_tools(
        self,
        messages: List[ChatMessage],
        tools: List[Dict[str, Any]],
    ) -> ChatResponse:
        """Google Gemini 带 Function Calling"""
        model = self._get_gemini_model()

        # Gemini 消息格式：system 单独处理
        system_parts = []
        chat_parts = []
        for m in messages:
            if m.role == "system":
                system_parts.append(m.content)
            else:
                role = "user" if m.role == "user" else "model"
                chat_parts.append({"role": role, "parts": [m.content]})

        system_instruction = "\n".join(system_parts) if system_parts else None

        # Gemini tools 格式转换：OpenAI schema → Gemini function declarations
        gemini_tools = []
        for t in tools:
            func = t.get("function", t)
            gemini_tools.append({
                "name": func.get("name", ""),
                "description": func.get("description", ""),
                "parameters": func.get("parameters", {}),
            })

        if genai is None:
            raise ImportError("请安装 Google Gemini SDK: pip install google-generativeai")
        tool_config = genai.types.Tool(function_declarations=[
            genai.types.FunctionDeclaration(
                name=gt["name"],
                description=gt["description"],
                parameters=gt["parameters"] if gt["parameters"].get("properties") else None,
            )
            for gt in gemini_tools
        ])

        response = model.generate_content(
            chat_parts,
            generation_config={
                "temperature": self.temperature,
                "max_output_tokens": self.max_tokens,
            },
            system_instruction=system_instruction,
            tools=[tool_config],
        )

        content = ""
        tool_calls = []
        if response.candidates:
            candidate = response.candidates[0]
            if candidate.content and candidate.content.parts:
                for part in candidate.content.parts:
                    if hasattr(part, "text") and part.text:
                        content += part.text
                    elif hasattr(part, "function_call") and part.function_call:
                        fc = part.function_call
                        tool_calls.append(ToolCall(
                            id=f"gemini_fc_{len(tool_calls)}",
                            name=fc.name,
                            arguments=dict(fc.args) if hasattr(fc, "args") else {},
                        ))

        usage = {}
        if hasattr(response, "usage_metadata") and response.usage_metadata:
            meta = response.usage_metadata
            usage = {
                "prompt_tokens": meta.prompt_token_count,
                "completion_tokens": meta.candidates_token_count,
                "total_tokens": meta.total_token_count,
            }

        return ChatResponse(
            content=content,
            model=self.gemini_cfg.get("model", "gemini-1.5-flash"),
            usage=usage,
            tool_calls=tool_calls,
        )

    def _chat_qwen_with_tools(
        self,
        messages: List[ChatMessage],
        tools: List[Dict[str, Any]],
    ) -> ChatResponse:
        """阿里云通义千问带 Function Calling"""
        if Generation is None:
            raise ImportError("请安装通义千问 SDK: pip install dashscope")

        # 构建消息
        api_messages = []
        for m in messages:
            api_messages.append({"role": m.role, "content": m.content})

        # Qwen tools 格式：OpenAI schema 基本兼容
        qwen_tools = []
        for t in tools:
            func = t.get("function", t)
            qwen_tools.append({
                "type": "function",
                "function": {
                    "name": func.get("name", ""),
                    "description": func.get("description", ""),
                    "parameters": func.get("parameters", {}),
                },
            })

        response = Generation.call(
            model=self.qwen_cfg.get("model", "qwen-plus"),
            messages=api_messages,
            tools=qwen_tools,
            api_key=self.qwen_cfg.get("api_key", ""),
            temperature=self.temperature,
            max_result_length=self.max_tokens,
            result_format="message",
        )

        if response.status_code != 200:
            error_msg = getattr(response, 'message', '') or str(response)
            raise RuntimeError(f"通义千问 API 调用失败 (status_code={response.status_code}): {error_msg}")

        choice = response.output.choices[0]
        message = choice.message

        content = message.content or ""
        tool_calls = []
        if hasattr(message, "tool_calls") and message.tool_calls:
            for tc in message.tool_calls:
                try:
                    args = json.loads(tc.function.arguments) if isinstance(tc.function.arguments, str) else (tc.function.arguments or {})
                except (json.JSONDecodeError, TypeError):
                    args = {}
                tool_calls.append(ToolCall(
                    id=getattr(tc, "id", f"qwen_tc_{len(tool_calls)}"),
                    name=tc.function.name,
                    arguments=args,
                ))

        usage = {}
        if response.usage:
            usage = {
                "prompt_tokens": response.usage.input_tokens,
                "completion_tokens": response.usage.output_tokens,
                "total_tokens": response.usage.total_tokens,
            }

        return ChatResponse(
            content=content,
            model=self.qwen_cfg.get("model", "qwen-plus"),
            usage=usage,
            tool_calls=tool_calls,
        )
    
    def test_connection(self) -> Dict[str, Any]:
        """测试当前 LLM 连接"""
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
        """运行时切换供应商"""
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
        """获取 Token 使用量统计"""
        with self._stats_lock:
            return {
                "total_prompt_tokens": self.total_prompt_tokens,
                "total_completion_tokens": self.total_completion_tokens,
                "total_tokens": self.total_prompt_tokens + self.total_completion_tokens,
                "total_calls": self.total_calls,
            }
