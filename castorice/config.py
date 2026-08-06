"""
配置加载模块（统一从 .env + yaml 读取）

职责：
- 加载 .env 环境变量（API 密钥）——搜索顺序：CWD → ~/.castorice → 源码根目录（向后兼容）
- 加载 castorice_config.yaml 业务配置——搜索顺序：CWD → ~/.castorice → 内嵌默认（castorice/data/default_config.yaml）
- 缺失时从内嵌默认写出到用户目录，保证首次 pip 安装即可启动
- 提供类型安全的配置访问接口
"""

import logging
import os
import sys
import threading
import shutil
from pathlib import Path
from typing import Any, Dict, Optional

import yaml
from dotenv import load_dotenv


# 源码根目录（git clone / pip install -e 时指向项目根；非 editable pip 安装时指向 site-packages）
PROJECT_ROOT = Path(__file__).parent.parent.resolve()

# 嵌入式默认配置（随 pip 包分发）
_PACKAGE_DATA_DIR = Path(__file__).parent / "data"
DEFAULT_CONFIG_PATH = _PACKAGE_DATA_DIR / "default_config.yaml"
DEFAULT_ENV_EXAMPLE_PATH = _PACKAGE_DATA_DIR / "default.env.example"

# 用户级配置目录
USER_CONFIG_DIR = Path.home() / ".castorice"


# ============================================================
# 搜索 + 自动写出工具
# ============================================================

def _cwd() -> Path:
    """返回当前工作目录。抽出来便于测试打桩。"""
    return Path.cwd()


def _find_env_file() -> Optional[Path]:
    """搜索 .env 文件，按优先级返回第一个存在的路径；找不到返回 None。

    优先级：
    1. CWD/.env
    2. ~/.castorice/.env
    3. PROJECT_ROOT/.env  （源码 / editable 安装的老位置，向后兼容）
    """
    candidates = [
        _cwd() / ".env",
        USER_CONFIG_DIR / ".env",
        PROJECT_ROOT / ".env",
    ]
    for p in candidates:
        if p.is_file():
            return p
    return None


def _find_config_yaml(explicit: Optional[str] = None) -> Optional[Path]:
    """搜索 castorice_config.yaml（或用户显式指定路径）。

    显式路径不为空时，只按那个路径去找（不存在即返回 None，不做回退写出）。
    否则按：
    1. CWD/castorice_config.yaml
    2. ~/.castorice/config.yaml
    3. PROJECT_ROOT/castorice_config.yaml  （源码 / editable 向后兼容）
    """
    if explicit is not None:
        p = Path(explicit)
        return p if p.is_file() else None

    candidates = [
        _cwd() / "castorice_config.yaml",
        USER_CONFIG_DIR / "config.yaml",
        PROJECT_ROOT / "castorice_config.yaml",
    ]
    for p in candidates:
        if p.is_file():
            return p
    return None


def _ensure_user_writable_config() -> Path:
    """确保用户目录有一份可写配置并返回其路径。

    搜索顺序下若已有用户配置，直接返回路径。
    否则：
      - 优先把嵌入式默认复制到 CWD/castorice_config.yaml（最直观）
      - CWD 不可写时回退到 ~/.castorice/config.yaml
    同时复制 .env.example 到同目录（如果同目录没有 .env 也没有 .env.example）。

    该函数永远返回一个可直接读取的配置文件路径。
    """
    found = _find_config_yaml()
    if found is not None:
        return found

    # 没找到：从嵌入式默认写出
    if not DEFAULT_CONFIG_PATH.is_file():
        # 极端情况：嵌入式默认也缺失——再退一步，尝试源码根目录
        fallback = PROJECT_ROOT / "castorice_config.yaml"
        if fallback.is_file():
            source = fallback
        else:
            raise FileNotFoundError(
                "未找到 castorice_config.yaml，且内嵌默认缺失。"
                "请重新安装 castorice-agent 包。"
            )
    else:
        source = DEFAULT_CONFIG_PATH

    # 优先写到 CWD
    target_cwd = _cwd() / "castorice_config.yaml"
    target_user = USER_CONFIG_DIR / "config.yaml"
    target = None
    try:
        target_cwd.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target_cwd)
        target = target_cwd
    except (OSError, PermissionError):
        USER_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target_user)
        target = target_user

    # 顺手把 .env.example 放到同目录（如果同目录还没有 .env 和 .env.example）
    target_dir = target.parent
    if not (target_dir / ".env").exists() and not (target_dir / ".env.example").exists():
        try:
            env_src = DEFAULT_ENV_EXAMPLE_PATH
            if env_src.is_file():
                shutil.copy2(env_src, target_dir / ".env.example")
        except (OSError, PermissionError):
            pass

    print(f"[Castorice] 首次启动，已生成默认配置: {target}")
    print(f"[Castorice] 如需自定义，请编辑该文件或复制 {target_dir}/.env.example 为 .env 填入 API Key")
    return target


def _ensure_data_dirs() -> None:
    """尽早创建 castorice_data/ 目录，避免下游 SQLite/JSON 存储因父目录缺失失败。

    相对路径会落在 CWD，符合默认 yaml 中 ./castorice_data/... 的约定。
    """
    candidates = [
        _cwd() / "castorice_data",
        Path("./castorice_data").resolve(),
    ]
    seen = set()
    for p in candidates:
        ap = p.resolve() if not p.is_absolute() else p
        if str(ap) in seen:
            continue
        seen.add(str(ap))
        try:
            ap.mkdir(parents=True, exist_ok=True)
        except (OSError, PermissionError):
            pass


# ============================================================
# 加载器
# ============================================================

def _load_dotenv() -> None:
    """加载 .env 环境变量（搜索多路径，全部加载以保证最宽覆盖）。

    顺序是低优先级先加载，高优先级后加载——后者覆盖前者（dotenv 默认 override=False，但我们显式走一遍所有存在的文件以兼容老结构）。
    实际行为：dotenv 默认不覆盖已存在的同名环境变量，因此用户通过 `export VAR=xxx` 设置的变量优先级最高。
    """
    candidates = [
        PROJECT_ROOT / ".env",       # 最低优先级：源码根
        USER_CONFIG_DIR / ".env",    # 中优先级：用户目录
        _cwd() / ".env",             # 最高优先级：当前目录
    ]
    loaded_any = False
    for p in candidates:
        if p.is_file():
            load_dotenv(p, override=False)
            loaded_any = True

    if not loaded_any:
        # 没有任何 .env 也没关系：尝试给出提示，然后调用 load_dotenv() 走系统环境变量
        env_example_hint = _cwd() / ".env.example"
        if env_example_hint.is_file() or (USER_CONFIG_DIR / ".env.example").is_file():
            print(
                "[Castorice] 未找到 .env 文件，请复制同目录下 .env.example 为 .env 并填入 API Key；"
                "或直接通过系统环境变量设置。"
            )
        load_dotenv()  # 即便没有文件，也兜底调用一次，保证系统级 env 正常传入


def _load_yaml_config(config_path: Optional[str] = None) -> Dict[str, Any]:
    """加载 YAML 业务配置。

    如果显式传了 config_path 但不存在：抛 FileNotFoundError（用户写错路径不该静默回退）。
    否则使用 _ensure_user_writable_config() 得到实际路径，保证一定可读。
    """
    if config_path is not None:
        path = Path(config_path)
        if not path.is_file():
            raise FileNotFoundError(f"配置文件不存在: {path}")
    else:
        path = _ensure_user_writable_config()

    with open(path, "r", encoding="utf-8") as f:
        config_dict = yaml.safe_load(f) or {}

    return validate_config(config_dict)


# ============================================================
# AttrDict —— 支持 cfg.agent.name 形式的嵌套属性访问
# ============================================================

class AttrDict:
    """把 dict 递归包成对象式访问（仍然是 dict 子类行为不保留，仅提供 .attr 语法糖）。

    读取时像对象：cfg.agent.name
    写入时仍当 dict：cfg.raw()['agent']['name'] = '...'
    这样既满足文档承诺的 .attr 链式访问，又不破坏下游的 dict isinstance 行为。
    """

    __slots__ = ("_data",)

    def __init__(self, data: Dict[str, Any]):
        object.__setattr__(self, "_data", data)

    def __getattr__(self, key: str) -> Any:
        if key.startswith("_"):
            raise AttributeError(key)
        if key not in self._data:
            raise AttributeError(f"配置中不存在该属性: {key}")
        val = self._data[key]
        if isinstance(val, dict):
            return AttrDict(val)
        if isinstance(val, list):
            return [AttrDict(v) if isinstance(v, dict) else v for v in val]
        return val

    def __repr__(self) -> str:
        return f"AttrDict({self._data!r})"

    def keys(self):
        return self._data.keys()

    def __iter__(self):
        return iter(self._data)

    def __len__(self):
        return len(self._data)

    def get(self, key, default=None):
        return self._data.get(key, default)

    def __contains__(self, key):
        return key in self._data


# ============================================================
# 配置校验
# ============================================================

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
            from pydantic import BaseModel, Field, field_validator, model_validator  # noqa: F401
        except ImportError:
            return config_dict

    # pydantic 可用但 config_schema 不可达时的兜底（极罕见）
    return config_dict


# ============================================================
# Config 主类
# ============================================================

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
        # 先建数据目录，避免后续存储组件因父目录不存在报错
        _ensure_data_dirs()
        _load_dotenv()
        self._config_path_override = config_path
        self._yaml = _load_yaml_config(config_path)
        self._actual_path: Path = _ensure_user_writable_config() if config_path is None else Path(config_path)
        self._build_llm_config()
        self._build_qq_bot_config()
        self._validate_api_keys()
        self._last_modified = self._get_config_mtime()

    def _validate_api_keys(self) -> None:
        """
        校验当前 provider 的 API Key 是否已配置。

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
                    f"LLM provider '{provider}' 的 API Key 未配置 "
                    f"(环境变量 {env_var})，相关功能将不可用"
                )

    def _get_config_mtime(self) -> float:
        """获取配置文件最后修改时间"""
        return self._actual_path.stat().st_mtime if self._actual_path.exists() else 0

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
            self._yaml = _load_yaml_config(self._config_path_override)
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
                "model": os.getenv("OPENROUTER_MODEL", "anthropic/claude-3-5-sonnet"),
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
        dict/list 会被 AttrDict 递归包装以支持 .attr 链式访问。
        """
        if key.startswith("_"):
            raise AttributeError(key)
        val = self._yaml.get(key)
        if val is None:
            raise AttributeError(f"配置中不存在该属性: {key}")
        if isinstance(val, dict):
            return AttrDict(val)
        if isinstance(val, list):
            return [AttrDict(v) if isinstance(v, dict) else v for v in val]
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
