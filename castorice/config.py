"""
配置加载模块（统一从 .env + yaml 读取）

职责：
- 加载 .env 环境变量（API 密钥）
- 加载 castorice_config.yaml 业务配置
- 提供类型安全的配置访问接口
"""

import os
import sys
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
        return yaml.safe_load(f) or {}


class Config:
    """
    全局配置管理器

    使用示例：
    >>> cfg = Config()
    >>> cfg.agent.name            # "Castorice"
    >>> cfg.llm.provider          # "openai"
    >>> cfg.llm.openai.api_key    # 从 .env 读取
    """

    def __init__(self, config_path: Optional[str] = None):
        _load_dotenv()
        self._yaml = _load_yaml_config(config_path)
        self._build_llm_config()

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
        }

        self._yaml["llm"] = llm_config

    def __getattr__(self, key: str) -> Any:
        """支持 cfg.agent.name / cfg.memory.short_term 等链式访问"""
        return self._yaml.get(key, {})

    def raw(self) -> Dict[str, Any]:
        """返回原始字典"""
        return self._yaml


def get_config(config_path: Optional[str] = None) -> Config:
    """获取全局配置单例"""
    global _global_config
    if "_global_config" not in globals() or _global_config is None:
        _global_config = Config(config_path)
    return _global_config


_global_config: Optional[Config] = None
