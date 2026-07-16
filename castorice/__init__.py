"""
Castorice Agent - 自进化智能体

复刻 Hermes Agent 架构思想：
- 自研主循环（移除 LangGraph 第三方编排）
- 原生 SDK 对接多模型（OpenAI / Claude / Ollama / OpenRouter）
- 精简依赖（移除 LangChain 体系碎片化子包）
- 统一配置（.env 存密钥 + yaml 存业务）
"""
__version__ = "2.0.0"
