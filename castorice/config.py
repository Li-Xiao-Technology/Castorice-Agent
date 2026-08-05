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
    "openai", "anthropic", "ollama", "openrouter", "gemini", "qwen", "freellmapi",
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

    统一委托给 config_schema.validate_config_dict 作为单一校验源。
    """
    try:
        from castorice.config_schema import validate_config_dict
        return validate_config_dict(config_dict)
    except ImportError:
        try:
            from pydantic import BaseModel, Field, field_validator, model_validator
        except ImportError:
            return config_dict

    # pydantic 可用但 config_schema 不可达时的兜底（极罕见）
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
            "freellmapi": ("freellmapi", "api_key", "FREELLMAPI_API_KEY"),
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
            "freellmapi": {
                "api_key": os.getenv("FREELLMAPI_API_KEY", ""),
                "base_url": os.getenv("FREELLMAPI_BASE_URL", "http://127.0.0.1:31415/v1"),
                "model": os.getenv("FREELLMAPI_MODEL", "auto"),
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
        # 优先使用已配置的 intent_value（整数），否则从 intent（字符串预设）解析
        if "intent_value" in qq_cfg:
            qq_cfg["intent_value"] = int(qq_cfg["intent_value"])
        else:
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

    def update_llm_runtime(self, updates: Dict[str, Any]) -> Dict[str, Any]:
        """运行时更新 LLM 配置（立即生效，不写入文件）

        支持的参数：temperature, max_tokens, timeout, provider
        返回更新后的 llm 配置段
        """
        if "llm" not in self._yaml or not isinstance(self._yaml["llm"], dict):
            self._yaml["llm"] = {}
        llm = self._yaml["llm"]

        applied = {}
        for key in ("temperature", "max_tokens", "timeout", "provider"):
            if key in updates and updates[key] is not None:
                if key == "temperature":
                    llm[key] = float(updates[key])
                elif key in ("max_tokens", "timeout"):
                    llm[key] = int(updates[key])
                else:
                    llm[key] = str(updates[key])
                applied[key] = llm[key]

        log = logging.getLogger("Castorice.Config")
        if applied:
            log.info(f"LLM 配置运行时更新: {applied}")
        return llm


_config_lock = threading.Lock()


def set_config(instance: Config) -> None:
    """手动设置全局 Config 实例（Agent 初始化时调用，确保配置生效）"""
    global _global_config
    with _config_lock:
        _global_config = instance


def get_config(config_path: Optional[str] = None) -> Config:
    """获取全局配置单例（线程安全）"""
    global _global_config
    with _config_lock:
        if _global_config is None:
            _global_config = Config(config_path)
    return _global_config


_global_config: Optional[Config] = None
