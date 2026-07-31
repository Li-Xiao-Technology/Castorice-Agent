"""
Castorice Agent - 自定义异常类

统一异常处理：
- 业务异常（可恢复）
- 系统异常（不可恢复）
- 工具异常
- 网络异常
"""

from typing import Optional


class CastoriceError(Exception):
    """Castorice 基础异常"""

    def __init__(self, message: str, details: Optional[dict] = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def __str__(self):
        if self.details:
            return f"{self.message} | 详情: {self.details}"
        return self.message


# ==================== 配置相关 ====================
class ConfigError(CastoriceError):
    """配置错误（不可恢复，需用户修正）"""
    pass


# ==================== LLM 相关 ====================
class LLMError(CastoriceError):
    """LLM 调用错误基类"""
    pass


class LLMConnectionError(LLMError):
    """LLM 连接错误（网络问题）"""
    pass


class LLMTimeoutError(LLMConnectionError):
    """LLM 调用超时"""
    pass


class LLMAuthError(LLMConnectionError):
    """LLM 鉴权错误（API Key 无效）"""
    pass


class LLMRateLimitError(LLMConnectionError):
    """LLM 速率限制"""
    pass


class LLMResponseError(LLMError):
    """LLM 响应格式错误"""
    pass


# ==================== 工具相关 ====================
class ToolError(CastoriceError):
    """工具执行错误基类"""
    pass


class ToolNotFoundError(ToolError):
    """工具不存在"""
    pass


class ToolTimeoutError(ToolError):
    """工具执行超时"""
    pass


class ToolSecurityError(ToolError):
    """工具安全检查失败（如命令黑名单）"""
    pass


class ToolArgumentError(ToolError):
    """工具参数错误"""
    pass


# ==================== 记忆相关 ====================
class MemoryError(CastoriceError):
    """记忆错误基类"""
    pass


class MemoryBackendError(MemoryError):
    """记忆后端错误"""
    pass


class MemoryNotFoundError(MemoryError):
    """记忆未找到"""
    pass


# ==================== 平台适配器 ====================
class AdapterError(CastoriceError):
    """适配器错误基类"""
    pass


class QQBotError(AdapterError):
    """QQ 机器人错误"""
    pass


class QQBotAuthError(QQBotError):
    """QQ 机器人鉴权失败"""
    pass


class QQBotConnectionError(QQBotError):
    """QQ 机器人连接失败"""
    pass


class QQBotMessageError(QQBotError):
    """QQ 消息发送/接收失败"""
    pass


# ==================== 业务异常（可恢复） ====================
class BusinessError(CastoriceError):
    """业务异常（可恢复，通常返回友好提示）"""
    pass


class UserInputError(BusinessError):
    """用户输入错误"""
    pass


# ==================== 异常分类辅助 ====================
RECOVERABLE_EXCEPTIONS = (
    LLMRateLimitError,
    LLMTimeoutError,
    ToolTimeoutError,
    QQBotConnectionError,
    MemoryBackendError,
)


def is_recoverable(error: Exception) -> bool:
    """判断异常是否可恢复"""
    return isinstance(error, RECOVERABLE_EXCEPTIONS)
