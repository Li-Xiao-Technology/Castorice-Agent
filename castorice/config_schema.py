"""
Castorice Agent - 配置 schema 校验

使用 pydantic 进行强类型配置校验：
- 类型检查
- 默认值
- 字段约束
- 错误提示
"""

from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

try:
    from pydantic import BaseModel, Field, field_validator, model_validator
    PYDANTIC_AVAILABLE = True
except ImportError:
    PYDANTIC_AVAILABLE = False
    BaseModel = object
    Field = lambda *args, **kwargs: None
    field_validator = lambda *a, **k: lambda f: f
    model_validator = lambda *a, **k: lambda f: f


# 支持的 LLM 供应商
SUPPORTED_LLM_PROVIDERS = {
    "openai", "anthropic", "ollama", "openrouter", "gemini", "qwen",
}

# 支持的长期记忆后端
SUPPORTED_MEMORY_BACKENDS = {
    "chroma", "pinecone", "faiss", "langchain",
}

# QQ Intent 预设
QQ_INTENT_PRESETS = {"basic", "with_c2c", "all"}


if PYDANTIC_AVAILABLE:

    class LLMProviderConfig(BaseModel):
        """LLM 供应商配置"""
        provider: str = "openai"

        @field_validator("provider")
        @classmethod
        def _v_provider(cls, v: str) -> str:
            v = v.lower()
            if v not in SUPPORTED_LLM_PROVIDERS:
                raise ValueError(
                    f"不支持的 LLM 供应商: {v}，支持列表: {sorted(SUPPORTED_LLM_PROVIDERS)}"
                )
            return v

    class MemoryBackendConfig(BaseModel):
        """长期记忆后端配置"""
        backend: str = "chroma"

        @field_validator("backend")
        @classmethod
        def _v_backend(cls, v: str) -> str:
            v = v.lower()
            if v not in SUPPORTED_MEMORY_BACKENDS:
                raise ValueError(
                    f"不支持的长期记忆后端: {v}，支持列表: {sorted(SUPPORTED_MEMORY_BACKENDS)}"
                )
            return v

    class ShortTermConfig(BaseModel):
        """短期记忆配置"""
        max_messages: int = Field(default=20, ge=1, le=1000)
        storage_path: str = "./castorice_data/sessions.db"

    class LongTermConfig(BaseModel):
        """长期记忆配置"""
        top_k: int = Field(default=5, ge=1, le=50)
        score_threshold: float = Field(default=0.3, ge=0.0, le=1.0)
        chroma_path: str = "./castorice_data/chroma_db"

    class SkillConfig(BaseModel):
        """技能记忆配置"""
        storage_path: str = "./castorice_data/skill_library.json"
        auto_extract: bool = True

    class UserProfileConfig(BaseModel):
        """用户画像配置"""
        storage_path: str = "./castorice_data/user_profile.json"
        auto_extract: bool = True

    class ToolConfig(BaseModel):
        """工具配置"""
        enabled: List[str] = Field(default_factory=list)
        disabled: List[str] = Field(default_factory=list)
        timeout: int = Field(default=30, ge=1, le=300)

    class WorkflowConfig(BaseModel):
        """工作流配置"""
        default: str = "standard"
        steps: Dict[str, List[str]] = Field(default_factory=dict)

    class QQBotConfigSchema(BaseModel):
        """QQ 机器人配置"""
        enabled: bool = True
        sandbox: bool = True
        intent: str = "basic"
        reply_prefix: str = ""
        auto_reply: bool = True
        allowed_groups: List[str] = Field(default_factory=list)
        allowed_users: List[str] = Field(default_factory=list)
        auto_accept_group_invite: bool = False

        @field_validator("intent")
        @classmethod
        def _v_intent(cls, v) -> str:
            if isinstance(v, str) and v not in QQ_INTENT_PRESETS:
                # 尝试解析为整数
                try:
                    int(v)
                    return v
                except (ValueError, TypeError):
                    raise ValueError(
                        f"无效的 intent: {v}，预设: {QQ_INTENT_PRESETS} 或整数"
                    )
            return v

    class HTTPServerConfig(BaseModel):
        """HTTP 服务配置"""
        enabled: bool = False
        host: str = "0.0.0.0"
        port: int = Field(default=8000, ge=1, le=65535)

    class LoggingConfig(BaseModel):
        """日志配置"""
        level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
        file_path: Optional[str] = "./castorice_data/castorice.log"
        max_bytes: int = Field(default=10 * 1024 * 1024, ge=1024)
        backup_count: int = Field(default=5, ge=0, le=100)
        use_color: bool = True

    class CastoriceConfigSchema(BaseModel):
        """完整配置 schema"""
        llm: LLMProviderConfig = Field(default_factory=LLMProviderConfig)
        short_term: ShortTermConfig = Field(default_factory=ShortTermConfig)
        long_term: LongTermConfig = Field(default_factory=LongTermConfig)
        skill: SkillConfig = Field(default_factory=SkillConfig)
        user_profile: UserProfileConfig = Field(default_factory=UserProfileConfig)
        tools: ToolConfig = Field(default_factory=ToolConfig)
        workflows: WorkflowConfig = Field(default_factory=WorkflowConfig)
        qq_bot: QQBotConfigSchema = Field(default_factory=QQBotConfigSchema)
        http_server: HTTPServerConfig = Field(default_factory=HTTPServerConfig)
        logging: LoggingConfig = Field(default_factory=LoggingConfig)


def validate_config_dict(config: Dict[str, Any]) -> Dict[str, Any]:
    """
    校验配置字典

    返回：标准化后的字典（pydantic 校验后）
    异常：pydantic 校验失败时抛出 ValueError
    """
    if config is None:
        config = {}

    if not PYDANTIC_AVAILABLE:
        # pydantic 不可用时直接返回，但确保默认段存在
        if "llm" not in config:
            config["llm"] = {"provider": "openai"}
        return config

    try:
        schema = CastoriceConfigSchema(**config)
        result = schema.model_dump()
        # 确保返回的字典包含所有默认段
        if "llm" not in result:
            result["llm"] = {"provider": "openai"}
        return result
    except Exception as e:
        raise ValueError(f"配置校验失败: {e}")
