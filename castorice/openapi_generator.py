"""
OpenAPI 文档生成器

为 Castorice Agent HTTP API 自动生成 OpenAPI 3.0 规范。
支持：
- 静态端点定义
- 动态字段（如 emotion_*）
- JSON 输出
"""

from typing import Any, Dict, List, Optional
import json


# 端点元数据：路径 -> 方法 -> 描述
ENDPOINTS = [
    {
        "path": "/",
        "method": "GET",
        "summary": "根端点",
        "description": "返回 API 基本信息和版本号",
        "tags": ["系统"],
        "responses": {
            "200": {
                "description": "API 信息",
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": {
                                "message": {"type": "string"},
                                "version": {"type": "string"},
                            },
                        }
                    }
                },
            }
        },
    },
    {
        "path": "/chat",
        "method": "POST",
        "summary": "对话接口",
        "description": "与 Agent 进行对话。支持同步和流式（SSE）输出。",
        "tags": ["对话"],
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": {"$ref": "#/components/schemas/ChatRequest"}
                }
            },
        },
        "responses": {
            "200": {
                "description": "对话成功",
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/ChatResponse"}
                    },
                    "text/event-stream": {
                        "schema": {"type": "string"},
                        "description": "流式输出（SSE）",
                    },
                },
            },
            "500": {"description": "服务器内部错误"},
        },
        "security": [{"ApiKeyAuth": []}],
    },
    {
        "path": "/status",
        "method": "GET",
        "summary": "查询系统状态",
        "description": "返回 Agent 的当前状态，包括模型、会话数、情感引擎等。",
        "tags": ["系统"],
        "responses": {
            "200": {
                "description": "状态信息",
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/StatusResponse"}
                    }
                },
            }
        },
    },
    {
        "path": "/tools",
        "method": "GET",
        "summary": "列出可用工具",
        "description": "获取 Agent 当前注册的所有工具。",
        "tags": ["工具"],
        "responses": {
            "200": {
                "description": "工具列表",
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "name": {"type": "string"},
                                    "description": {"type": "string"},
                                },
                            },
                        }
                    }
                },
            }
        },
    },
    {
        "path": "/skills",
        "method": "GET",
        "summary": "列出已学技能",
        "description": "获取 Agent 通过工具学习积累的技能。",
        "tags": ["技能"],
        "responses": {
            "200": {
                "description": "技能列表",
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "name": {"type": "string"},
                                    "version": {"type": "string"},
                                    "description": {"type": "string"},
                                },
                            },
                        }
                    }
                },
            }
        },
    },
    {
        "path": "/history/{session_id}",
        "method": "GET",
        "summary": "获取会话历史",
        "description": "返回指定会话的消息历史。",
        "tags": ["对话"],
        "parameters": [
            {
                "name": "session_id",
                "in": "path",
                "required": True,
                "description": "会话 ID",
                "schema": {"type": "string"},
            }
        ],
        "responses": {
            "200": {
                "description": "历史消息列表",
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "role": {"type": "string"},
                                    "content": {"type": "string"},
                                    "timestamp": {"type": "number"},
                                },
                            },
                        }
                    }
                },
            }
        },
    },
    {
        "path": "/session/{session_id}",
        "method": "DELETE",
        "summary": "删除会话",
        "description": "删除指定会话及其所有消息。",
        "tags": ["对话"],
        "parameters": [
            {
                "name": "session_id",
                "in": "path",
                "required": True,
                "description": "会话 ID",
                "schema": {"type": "string"},
            }
        ],
        "responses": {
            "200": {
                "description": "删除成功",
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": {
                                "success": {"type": "boolean"},
                                "message": {"type": "string"},
                            },
                        }
                    }
                },
            }
        },
    },
    {
        "path": "/clear_memory",
        "method": "POST",
        "summary": "清空长期记忆",
        "description": "强制清空长期记忆（需要 confirm=true 二次确认）。",
        "tags": ["记忆"],
        "parameters": [
            {
                "name": "confirm",
                "in": "query",
                "required": False,
                "description": "必须为 true 才会执行清空",
                "schema": {"type": "boolean", "default": False},
            }
        ],
        "responses": {
            "200": {
                "description": "清空结果",
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": {
                                "success": {"type": "boolean"},
                                "message": {"type": "string"},
                            },
                        }
                    }
                },
            }
        },
    },
    {
        "path": "/metrics",
        "method": "GET",
        "summary": "Prometheus 指标",
        "description": "导出 Prometheus 格式的运行时指标。",
        "tags": ["监控"],
        "responses": {
            "200": {
                "description": "Prometheus 格式指标",
                "content": {
                    "text/plain": {
                        "schema": {"type": "string"},
                    }
                },
            }
        },
    },
    {
        "path": "/ws",
        "method": "GET",
        "summary": "WebSocket 实时通信",
        "description": "WebSocket 端点，支持实时双向通信、流式对话、状态推送和通知。连接后发送 `{\"type\":\"auth\",\"payload\":{\"api_key\":\"xxx\"}}` 进行认证。",
        "tags": ["WebSocket"],
        "responses": {
            "101": {"description": "WebSocket 协议升级成功"},
        },
    },
    {
        "path": "/sessions",
        "method": "GET",
        "summary": "列出所有会话",
        "description": "获取会话列表，支持分页。",
        "tags": ["对话"],
        "parameters": [
            {"name": "limit", "in": "query", "schema": {"type": "integer", "default": 50}},
            {"name": "offset", "in": "query", "schema": {"type": "integer", "default": 0}},
        ],
        "responses": {
            "200": {
                "description": "会话列表",
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": {
                                "sessions": {"type": "array"},
                                "total": {"type": "integer"},
                                "limit": {"type": "integer"},
                                "offset": {"type": "integer"},
                            },
                        }
                    }
                },
            }
        },
    },
    {
        "path": "/sessions",
        "method": "POST",
        "summary": "创建新会话",
        "description": "创建一个新的对话会话。",
        "tags": ["对话"],
        "parameters": [
            {"name": "title", "in": "query", "schema": {"type": "string"}, "description": "会话标题"},
        ],
        "responses": {
            "200": {
                "description": "创建成功",
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": {
                                "success": {"type": "boolean"},
                                "session_id": {"type": "string"},
                                "title": {"type": "string"},
                            },
                        }
                    }
                },
            }
        },
    },
    {
        "path": "/sessions/{session_id}",
        "method": "PUT",
        "summary": "重命名会话",
        "description": "修改指定会话的标题。",
        "tags": ["对话"],
        "parameters": [
            {"name": "session_id", "in": "path", "required": True, "schema": {"type": "string"}},
        ],
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": {"$ref": "#/components/schemas/RenameSessionRequest"}
                }
            },
        },
        "responses": {
            "200": {"description": "重命名成功"},
            "404": {"description": "会话不存在"},
        },
    },
    {
        "path": "/settings",
        "method": "GET",
        "summary": "获取配置",
        "description": "获取当前运行配置（脱敏后，不含 API Key 等敏感信息）。",
        "tags": ["系统"],
        "responses": {
            "200": {"description": "配置信息"},
        },
    },
    {
        "path": "/settings",
        "method": "PUT",
        "summary": "更新配置",
        "description": "更新运行时配置项。",
        "tags": ["系统"],
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": {"$ref": "#/components/schemas/UpdateSettingsRequest"}
                }
            },
        },
        "responses": {
            "200": {"description": "更新结果"},
        },
    },
    {
        "path": "/agent/emotion",
        "method": "GET",
        "summary": "获取情感状态",
        "description": "获取 Agent 当前的 PAD 情感状态。",
        "tags": ["Agent"],
        "responses": {
            "200": {"description": "情感状态"},
        },
    },
    {
        "path": "/agent/self_concept",
        "method": "GET",
        "summary": "获取自我概念",
        "description": "获取 Agent 的自我概念文档内容。",
        "tags": ["Agent"],
        "responses": {
            "200": {"description": "自我概念内容"},
        },
    },
    {
        "path": "/memory/search",
        "method": "POST",
        "summary": "搜索长期记忆",
        "description": "基于语义相似度搜索长期记忆。",
        "tags": ["记忆"],
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": {"$ref": "#/components/schemas/MemorySearchRequest"}
                }
            },
        },
        "responses": {
            "200": {"description": "搜索结果"},
        },
    },
    {
        "path": "/memory/experiences",
        "method": "GET",
        "summary": "获取经历流",
        "description": "获取 Agent 的经历流记录。",
        "tags": ["记忆"],
        "parameters": [
            {"name": "limit", "in": "query", "schema": {"type": "integer", "default": 20}},
            {"name": "memory_type", "in": "query", "schema": {"type": "string"}, "description": "记忆类型过滤：episodic/emotional/reflective/skill"},
        ],
        "responses": {
            "200": {"description": "经历流列表"},
        },
    },
]


# Pydantic 模型 Schema
SCHEMAS = {
    "ChatRequest": {
        "type": "object",
        "required": ["message"],
        "properties": {
            "message": {
                "type": "string",
                "description": "用户消息",
            },
            "session_id": {
                "type": "string",
                "nullable": True,
                "description": "会话 ID，为空时自动创建",
            },
            "stream": {
                "type": "boolean",
                "default": False,
                "description": "是否启用流式输出（SSE）",
            },
        },
    },
    "ChatResponse": {
        "type": "object",
        "properties": {
            "success": {"type": "boolean"},
            "answer": {"type": "string"},
            "session_id": {"type": "string"},
            "errors": {"type": "array", "items": {"type": "string"}, "nullable": True},
            "tool_calls": {"type": "array", "nullable": True},
        },
    },
    "StatusResponse": {
        "type": "object",
        "properties": {
            "provider": {"type": "string", "description": "LLM 提供商"},
            "model": {"type": "string", "description": "模型名称"},
            "total_calls": {"type": "integer", "description": "总 LLM 调用次数"},
            "total_tokens": {"type": "integer", "description": "总 token 消耗"},
            "tools_count": {"type": "integer", "description": "工具数量"},
            "sessions_count": {"type": "integer", "description": "会话数量"},
            "skills_count": {"type": "integer", "description": "技能数量"},
            "long_term_available": {"type": "boolean", "description": "长期记忆是否可用"},
            "long_term_count": {"type": "integer", "description": "长期记忆条目数"},
            "emotion_enabled": {"type": "boolean", "description": "情感引擎是否启用"},
            "emotion_pleasure": {"type": "number", "nullable": True, "description": "愉悦度 [-1, 1]"},
            "emotion_arousal": {"type": "number", "nullable": True, "description": "唤醒度 [-1, 1]"},
            "emotion_dominance": {"type": "number", "nullable": True, "description": "掌控感 [-1, 1]"},
            "emotion_interaction_count": {"type": "integer", "description": "情感交互次数"},
        },
    },
    "MemorySearchRequest": {
        "type": "object",
        "required": ["query"],
        "properties": {
            "query": {"type": "string", "description": "搜索关键词"},
            "top_k": {"type": "integer", "default": 5, "description": "返回结果数量"},
        },
    },
    "UpdateSettingsRequest": {
        "type": "object",
        "required": ["key", "value"],
        "properties": {
            "key": {"type": "string", "description": "配置项键名"},
            "value": {"description": "配置项值"},
        },
    },
    "RenameSessionRequest": {
        "type": "object",
        "required": ["title"],
        "properties": {
            "title": {"type": "string", "description": "会话新标题"},
        },
    },
}


SECURITY_SCHEMES = {
    "ApiKeyAuth": {
        "type": "apiKey",
        "in": "header",
        "name": "X-API-Key",
        "description": "API 密钥认证",
    },
    "ApiKeyQuery": {
        "type": "apiKey",
        "in": "query",
        "name": "api_key",
        "description": "URL 查询参数形式的 API 密钥",
    },
}


def generate_openapi_spec(
    title: str = "Castorice Agent API",
    version: str = "3.0.0",
    description: str = "Castorice Agent REST API",
) -> Dict[str, Any]:
    """生成 OpenAPI 3.0 规范"""
    paths = {}
    for endpoint in ENDPOINTS:
        path = endpoint["path"]
        method = endpoint["method"].lower()
        if path not in paths:
            paths[path] = {}
        paths[path][method] = {
            "summary": endpoint["summary"],
            "description": endpoint["description"],
            "tags": endpoint.get("tags", []),
            "responses": endpoint.get("responses", {}),
        }
        if "requestBody" in endpoint:
            paths[path][method]["requestBody"] = endpoint["requestBody"]
        if "parameters" in endpoint:
            paths[path][method]["parameters"] = endpoint["parameters"]
        if "security" in endpoint:
            paths[path][method]["security"] = endpoint["security"]

    return {
        "openapi": "3.0.3",
        "info": {
            "title": title,
            "version": version,
            "description": description,
            "contact": {
                "name": "Castorice Agent",
                "url": "https://github.com/castorice/castorice-agent",
            },
        },
        "servers": [
            {"url": "http://localhost:8000", "description": "本地开发服务器"},
        ],
        "paths": paths,
        "components": {
            "schemas": SCHEMAS,
            "securitySchemes": SECURITY_SCHEMES,
        },
        "tags": [
            {"name": "系统", "description": "系统级端点"},
            {"name": "对话", "description": "对话与历史管理"},
            {"name": "工具", "description": "工具查询"},
            {"name": "技能", "description": "技能查询"},
            {"name": "记忆", "description": "记忆管理"},
            {"name": "监控", "description": "监控与指标"},
            {"name": "WebSocket", "description": "实时双向通信"},
            {"name": "Agent", "description": "Agent 状态与自我概念"},
        ],
    }


def export_openapi_json() -> str:
    """导出 OpenAPI 规范的 JSON 字符串"""
    return json.dumps(generate_openapi_spec(), ensure_ascii=False, indent=2)


def export_openapi_to_file(file_path: str) -> None:
    """导出 OpenAPI 规范到文件"""
    spec = generate_openapi_spec()
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(spec, f, ensure_ascii=False, indent=2)
