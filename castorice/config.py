"""
配置加载模块（统一从 .env + yaml 读取）

职责：
- 加载 .env 环境变量（API 密钥）
- 加载 castorice_config.yaml 业务配置
- 提供类型安全的配置访问接口
"""

import logging
import os
import sys
import threading
from pathlib import Path
from typing import Any, Dict, Optional

import yaml
from dotenv import load_dotenv


# 项目根目录
PROJECT_ROOT = Path(__file__).parent.parent.resolve()


def _load_dotenv() -> None:
    """加载 .env 环境变量"""
    env_path = PROJECT_ROOT / ".env"
    if env_path.exists():
        load_dotenv(env_path)
    else:
        # 尝试加载 .env.example 给出友好提示
        example = PROJECT_ROOT / ".env.example"
        if example.exists():
            print(f"[提示] 未找到 .env 文件，请复制 .env.example 为 .env 并填入 API 密钥")
        load_dotenv()  # 即便不存在也调用一次，让框架按环境变量查找


def _load_yaml_config(config_path: Optional[str] = None) -> Dict[str, Any]:
    """加载 YAML 业务配置"""
    if config_path is None:
        config_path = PROJECT_ROOT / "castorice_config.yaml"
    else:
        config_path = Path(config_path)

    if not config_path.exists():
        raise FileNotFoundError(f"配置文件不存在: {config_path}")

    with open(config_path, "r", encoding="utf-8") as f:
        config_dict = yaml.safe_load(f) or {}

    return validate_config(config_dict)


# ========== 配置校验（pydantic） ==========

# 支持的 LLM 供应商列表
_SUPPORTED_LLM_PROVIDERS = {
    "openai", "anthropic", "ollama", "openrouter", "gemini", "qwen",
}

# 支持的长期记忆后端列表
_SUPPORTED_MEMORY_BACKENDS = {
    "chroma", "pinecone", "faiss", "langchain",
}


def validate_config(config_dict: Dict[str, Any]) -> Dict[str, Any]:
    """
    使用 pydantic 校验配置字典（关键字段）。
    若 pydantic 未安装则跳过校验，直接返回原配置。
    校验失败抛出 ValueError，包含具体错误信息。
    """
    try:
        from pydantic import BaseModel, Field, field_validator, model_validator
    except ImportError:
        return config_dict

    class LLMConfig(BaseModel):
        provider: str = "openai"

        @field_validator("provider")
        @classmethod
        def validate_provider(cls, v: str) -> str:
            if v.lower() not in _SUPPORTED_LLM_PROVIDERS:
                raise ValueError(
                    f"不支持的 LLM 供应商: {v}，支持列表: {sorted(_SUPPORTED_LLM_PROVIDERS)}"
                )
            return v.lower()

    class LongTermMemoryConfig(BaseModel):
        backend: Optional[str] = None

        @field_validator("backend")
        @classmethod
        def validate_backend(cls, v: Optional[str]) -> Optional[str]:
            if v is not None and v.lower() not in _SUPPORTED_MEMORY_BACKENDS:
                raise ValueError(
                    f"不支持的长期记忆后端: {v}，支持列表: {sorted(_SUPPORTED_MEMORY_BACKENDS)}"
                )
            return v.lower() if v else v

    class MemoryConfig(BaseModel):
        backend: Optional[str] = None
        long_term: Optional[LongTermMemoryConfig] = None

        @field_validator("backend")
        @classmethod
        def validate_backend(cls, v: Optional[str]) -> Optional[str]:
            if v is not None and v.lower() not in _SUPPORTED_MEMORY_BACKENDS:
                raise ValueError(
                    f"不支持的记忆后端: {v}，支持列表: {sorted(_SUPPORTED_MEMORY_BACKENDS)}"
                )
            return v.lower() if v else v

    class AgentConfig(BaseModel):
        max_iterations: Optional[int] = None

    class SelfEvolvingConfig(BaseModel):
        enabled: Optional[bool] = None
        reflection_interval_turns: Optional[int] = None
        reflection_llm_threshold: Optional[float] = None
        max_experiences: Optional[int] = None

        @field_validator("reflection_interval_turns")
        @classmethod
        def validate_interval(cls, v):
            if v is not None and v < 1:
                raise ValueError(f"reflection_interval_turns 必须 >= 1，实际为 {v}")
            return v

        @field_validator("reflection_llm_threshold")
        @classmethod
        def validate_threshold(cls, v):
            if v is not None and not (0.0 <= v <= 1.0):
                raise ValueError(f"reflection_llm_threshold 应在 [0, 1]，实际为 {v}")
            return v

        @field_validator("max_experiences")
        @classmethod
        def validate_max_exp(cls, v):
            if v is not None and v < 100:
                raise ValueError(f"max_experiences 必须 >= 100，实际为 {v}")
            return v

    class RuntimeConfig(BaseModel):
        max_iterations: Optional[int] = None
        self_evolving: Optional[SelfEvolvingConfig] = None

    # QQ 机器人 intent 预设值白名单（字符串形式）
    _SUPPORTED_QQ_BOT_INTENTS = {"basic", "with_c2c", "all"}

    class QQBotConfig(BaseModel):
        intent: Optional[Any] = None  # 可以是字符串或整数

        @field_validator("intent")
        @classmethod
        def validate_intent(cls, v):
            # 仅当 intent 为字符串时校验预设值；整数（位运算结果）直接放行
            if isinstance(v, str):
                if v.lower() not in _SUPPORTED_QQ_BOT_INTENTS:
                    raise ValueError(
                        f"不支持的 QQ 机器人 intent 预设值: {v}，"
                        f"支持列表: {sorted(_SUPPORTED_QQ_BOT_INTENTS)}"
                    )
                return v.lower()
            return v

    class ToolsConfig(BaseModel):
        # 工具配置是动态的，不做严格字段校验
        @model_validator(mode="before")
        @classmethod
        def validate_tools(cls, values):
            # 每个工具的配置项也应该是 dict（或 None）
            if isinstance(values, dict):
                for name, cfg in values.items():
                    if cfg is not None and not isinstance(cfg, dict):
                        raise ValueError(
                            f"工具 '{name}' 的配置应该是 dict，"
                            f"实际为 {type(cfg).__name__}"
                        )
            return values

    class WorkflowsConfig(BaseModel):
        # 工作流配置是动态的，不做严格字段校验
        @model_validator(mode="before")
        @classmethod
        def validate_workflows(cls, values):
            # 每个工作流应该有 steps 字段且为 list
            if isinstance(values, dict):
                for name, cfg in values.items():
                    if not isinstance(cfg, dict):
                        raise ValueError(
                            f"工作流 '{name}' 的配置应该是 dict，"
                            f"实际为 {type(cfg).__name__}"
                        )
                    steps = cfg.get("steps")
                    if steps is None:
                        raise ValueError(
                            f"工作流 '{name}' 缺少必需的 'steps' 字段"
                        )
                    if not isinstance(steps, list):
                        raise ValueError(
                            f"工作流 '{name}' 的 'steps' 字段应该是 list，"
                            f"实际为 {type(steps).__name__}"
                        )
            return values

    class LoggingConfig(BaseModel):
        level: Optional[str] = "INFO"
        format: Optional[str] = "text"
        log_dir: Optional[str] = "./logs"
        max_size_mb: Optional[int] = 10
        backup_count: Optional[int] = 5

    class ConfigSchema(BaseModel):
        llm: Optional[LLMConfig] = None
        memory: Optional[MemoryConfig] = None
        agent: Optional[AgentConfig] = None
        runtime: Optional[RuntimeConfig] = None
        qq_bot: Optional[QQBotConfig] = None
        tools: Optional[ToolsConfig] = None
        workflows: Optional[WorkflowsConfig] = None
        logging: Optional[LoggingConfig] = None

    try:
        ConfigSchema(**config_dict)
    except Exception as e:
        raise ValueError(f"配置校验失败: {e}") from e

    return config_dict


class Config:
    """
    全局配置管理器（支持热更新）

    使用示例：
    >>> cfg = Config()
    >>> cfg.agent.name            # "Castorice"
    >>> cfg.llm.provider          # "openai"
    >>> cfg.llm.openai.api_key    # 从 .env 读取
    """

    def __init__(self, config_path: Optional[str] = None):
        _load_dotenv()
        self._config_path = config_path
        self._yaml = _load_yaml_config(config_path)
        self._build_llm_config()
        self._build_qq_bot_config()
        self._validate_api_keys()  # P1-29: 启动校验 API Key
        self._last_modified = self._get_config_mtime()

    def _validate_api_keys(self) -> None:
        """
        P1-29: 校验当前 provider 的 API Key 是否已配置。

        仅警告不抛异常，允许无 Key 启动（如使用 ollama 本地模型）。
        """
        llm = self._yaml.get("llm", {})
        provider = llm.get("provider", "openai").lower() if isinstance(llm, dict) else "openai"

        # provider → (配置段名, key字段, 环境变量名)
        key_map = {
            "openai": ("openai", "api_key", "OPENAI_API_KEY"),
            "anthropic": ("anthropic", "api_key", "ANTHROPIC_API_KEY"),
            "openrouter": ("openrouter", "api_key", "OPENROUTER_API_KEY"),
            "gemini": ("gemini", "api_key", "GEMINI_API_KEY"),
            "qwen": ("qwen", "api_key", "QWEN_API_KEY"),
        }

        logger = logging.getLogger("Castorice.Config")
        if provider in key_map:
            section, key_field, env_var = key_map[provider]
            section_cfg = llm.get(section, {}) if isinstance(llm, dict) else {}
            api_key = section_cfg.get(key_field, "") if isinstance(section_cfg, dict) else ""
            if not api_key:
                logger.warning(
                    f"P1-29: LLM provider '{provider}' 的 API Key 未配置 "
                    f"(环境变量 {env_var})，相关功能将不可用"
                )

    def _get_config_mtime(self) -> float:
        """获取配置文件最后修改时间"""
        if self._config_path:
            path = Path(self._config_path)
        else:
            path = PROJECT_ROOT / "castorice_config.yaml"
        return path.stat().st_mtime if path.exists() else 0

    def check_for_updates(self) -> bool:
        """检查配置文件是否有更新"""
        mtime = self._get_config_mtime()
        if mtime > self._last_modified:
            return True
        return False

    def reload(self) -> None:
        """重新加载配置（热更新）"""
        try:
            _load_dotenv()
            self._yaml = _load_yaml_config(self._config_path)
            self._build_llm_config()
            self._build_qq_bot_config()
            self._last_modified = self._get_config_mtime()
            logger = logging.getLogger("Castorice.Config")
            logger.info("配置已热更新")
        except Exception as e:
            logger = logging.getLogger("Castorice.Config")
            logger.error(f"配置热更新失败: {e}")

    def _build_llm_config(self) -> None:
        """从 .env 构建 LLM 配置，注入到 self._yaml['llm']"""
        # 读取 .env 中的默认供应商
        provider = os.getenv("CASTORICE_LLM_PROVIDER", "openai").lower()

        # 公共参数
        temperature = float(os.getenv("LLM_TEMPERATURE", "0.7"))
        max_tokens = int(os.getenv("LLM_MAX_TOKENS", "4096"))
        timeout = int(os.getenv("LLM_TIMEOUT", "60"))

        # 各供应商配置（从 .env 读取）
        llm_config = {
            "provider": provider,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "timeout": timeout,
            "openai": {
                "api_key": os.getenv("OPENAI_API_KEY", ""),
                "base_url": os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
                "model": os.getenv("OPENAI_MODEL", "gpt-4o"),
            },
            "anthropic": {
                "api_key": os.getenv("ANTHROPIC_API_KEY", ""),
                "base_url": os.getenv("ANTHROPIC_BASE_URL", "https://api.anthropic.com"),
                "model": os.getenv("ANTHROPIC_MODEL", "claude-3-5-sonnet-20241022"),
            },
            "ollama": {
                "base_url": os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
                "model": os.getenv("OLLAMA_MODEL", "llama3.1:8b"),
            },
            "openrouter": {
                "api_key": os.getenv("OPENROUTER_API_KEY", ""),
                "base_url": os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
                "model": os.getenv("OPENROUTER_MODEL", "anthropic/claude-3.5-sonnet"),
            },
            "gemini": {
                "api_key": os.getenv("GEMINI_API_KEY", ""),
                "model": os.getenv("GEMINI_MODEL", "gemini-1.5-flash"),
            },
            "qwen": {
                "api_key": os.getenv("QWEN_API_KEY", ""),
                "model": os.getenv("QWEN_MODEL", "qwen-plus"),
            },
        }

        self._yaml["llm"] = llm_config

    def _build_qq_bot_config(self) -> None:
        """从 .env 构建 QQ 机器人配置，注入到 self._yaml['qq_bot']"""
        qq_cfg = self._yaml.get("qq_bot", {})
        if not isinstance(qq_cfg, dict):
            qq_cfg = {}

        app_id = os.getenv("QQ_BOT_APP_ID", "")
        app_secret = os.getenv("QQ_BOT_APP_SECRET", "")
        sandbox = os.getenv("QQ_BOT_SANDBOX", "true").lower() == "true"

        if app_id:
            qq_cfg["app_id"] = app_id
        if app_secret:
            qq_cfg["app_secret"] = app_secret
        if "sandbox" not in qq_cfg:
            qq_cfg["sandbox"] = sandbox

        # 解析 Intent 配置
        intent_config = qq_cfg.get("intent", "basic")
        qq_cfg["intent_value"] = self._parse_intent(intent_config)

        self._yaml["qq_bot"] = qq_cfg

    def _parse_intent(self, intent_config) -> int:
        """解析 Intent 配置为整数值"""
        from castorice.adapters.qq_bot import QQBotConfig

        # 如果已经是整数，直接返回
        if isinstance(intent_config, int):
            return intent_config

        # 预设值映射（使用 QQBotConfig 中的常量，确保位运算正确）
        intent_map = {
            "basic": QQBotConfig.INTENT_BASIC,           # 1536: AT_MESSAGE + DIRECT_MESSAGE
            "with_c2c": QQBotConfig.INTENT_WITH_C2C,     # 33555968: basic + C2C_MESSAGE
            "all": QQBotConfig.INTENT_ALL,               # 所有消息类型
        }

        # 尝试字符串匹配
        if isinstance(intent_config, str):
            intent_str = intent_config.lower()
            if intent_str in intent_map:
                return intent_map[intent_str]
            # 尝试解析为整数
            try:
                return int(intent_str)
            except ValueError:
                pass

        # 默认使用 basic（无需额外权限）
        return intent_map["basic"]

    def __getattr__(self, key: str) -> Any:
        """
        支持 cfg.agent.name / cfg.memory.short_term 等链式访问。
        注意：以 _ 开头的属性走默认查找，不查 _yaml。
        """
        if key.startswith("_"):
            raise AttributeError(key)
        val = self._yaml.get(key)
        if val is None:
            raise AttributeError(f"配置中不存在该属性: {key}")
        return val

    def raw(self) -> Dict[str, Any]:
        """返回原始字典"""
        return self._yaml


_config_lock = threading.Lock()


def get_config(config_path: Optional[str] = None) -> Config:
    """获取全局配置单例（线程安全）"""
    global _global_config
    with _config_lock:
        if _global_config is None:
            _global_config = Config(config_path)
    return _global_config


_global_config: Optional[Config] = None
