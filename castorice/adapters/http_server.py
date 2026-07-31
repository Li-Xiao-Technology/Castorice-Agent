"""
HTTP 服务器适配器 (HTTPServerAdapter)

提供 REST API 访问接口，支持：
- 对话接口（同步/流式）
- API Key 认证
- 请求限流
- 状态查询
- 工具调用
- 记忆管理

使用示例：
>>> server = HTTPServerAdapter(engine, host="0.0.0.0", port=8000)
>>> server.start_in_thread()
"""

import asyncio
import hashlib
import json
import logging
import re
import threading
import time
import uuid
from collections import defaultdict
from typing import Any, Dict, List, Optional

try:
    import uvicorn
    from fastapi import FastAPI, HTTPException, Request, Security, status, WebSocket, WebSocketDisconnect
    from fastapi.security.api_key import APIKeyHeader
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import StreamingResponse, JSONResponse
    from pydantic import BaseModel, Field
except ImportError:
    uvicorn = None
    FastAPI = None
    HTTPException = None
    Security = None
    status = None
    APIKeyHeader = None
    CORSMiddleware = None
    StreamingResponse = None
    JSONResponse = None
    BaseModel = None
    Field = None
    WebSocket = None
    WebSocketDisconnect = None

logger = logging.getLogger("Castorice.HTTPServer")

# Pydantic 模型定义（仅在 FastAPI 可用时使用）
if BaseModel is not None:
    class ChatRequest(BaseModel):
        message: str = Field(..., description="用户消息")
        session_id: Optional[str] = Field(None, description="会话ID，为空时自动创建")
        stream: Optional[bool] = Field(False, description="是否启用流式输出")

    class ChatResponse(BaseModel):
        success: bool
        answer: str
        session_id: str
        errors: Optional[list] = None
        tool_calls: Optional[list] = None

    class StatusResponse(BaseModel):
        provider: str
        model: str
        temperature: Optional[float] = None
        max_tokens: Optional[int] = None
        timeout: Optional[int] = None
        total_calls: int
        total_tokens: int
        tools_count: int
        sessions_count: int
        skills_count: int
        long_term_available: bool
        long_term_count: int
        # P2-6: 情感引擎状态
        emotion_enabled: bool = False
        emotion_pleasure: Optional[float] = None
        emotion_arousal: Optional[float] = None
        emotion_dominance: Optional[float] = None
        emotion_interaction_count: int = 0
        eigenflux_available: bool = False
        eigenflux_authenticated: bool = False
        eigenflux_version: Optional[str] = None
        autonomous_running: bool = False
        autonomous_total_decisions: int = 0
        autonomous_quick_interval: int = 60
        autonomous_deep_interval: int = 900
        autonomous_recent: List[Dict[str, Any]] = []
        # P1-4: 成本闸状态
        cost_throttled: bool = False
        cost_paused: bool = False
        cost_hourly_tokens: int = 0
        cost_daily_tokens: int = 0
        cost_hourly_limit: int = 0
        cost_daily_limit: int = 0
else:
    # 占位符，防止 ImportError 时类定义失败
    ChatRequest = None
    ChatResponse = None
    StatusResponse = None

# ========== Electron 客户端专用 Pydantic 模型 ==========
if BaseModel is not None:
    class MemorySearchRequest(BaseModel):
        query: str = Field(..., description="搜索关键词")
        top_k: int = Field(5, description="返回结果数量")

    class UpdateSettingsRequest(BaseModel):
        key: Optional[str] = Field(None, description="配置项键名（单键更新时用）")
        value: Any = Field(None, description="配置项值（单键更新时用）")
        temperature: Optional[float] = Field(None, description="LLM temperature")
        max_tokens: Optional[int] = Field(None, description="LLM 最大输出 token 数")
        timeout: Optional[int] = Field(None, description="LLM 请求超时（秒）")
        provider: Optional[str] = Field(None, description="LLM 提供商")

    class RenameSessionRequest(BaseModel):
        title: str = Field(..., description="会话新标题")

    class WSChatMessage(BaseModel):
        message: str = Field(..., description="用户消息内容")
        session_id: Optional[str] = Field(None, description="会话ID")
        stream: bool = Field(True, description="是否启用流式输出")
else:
    MemorySearchRequest = None
    UpdateSettingsRequest = None
    RenameSessionRequest = None
    WSChatMessage = None


# ========== WebSocket 连接管理器 ==========
class WebSocketManager:
    """WebSocket 连接管理器，支持多客户端实时交互"""

    def __init__(self, engine, api_keys: Optional[list] = None):
        self.engine = engine
        self.api_keys = api_keys or []
        self._connections: Dict[str, WebSocket] = {}
        self._auth_clients: set = set()  # 已认证客户端ID集合
        self._lock = threading.Lock()
        self._heartbeat_interval = 30  # 心跳间隔(秒)
        self._notification_manager = None
        self._setup_notifications()

    def _setup_notifications(self):
        """设置通知系统回调"""
        try:
            from castorice.notifications import get_notification_manager
            self._notification_manager = get_notification_manager()
            self._notification_manager.subscribe("*", self._on_notification)
        except Exception as e:
            logger.debug(f"通知系统初始化失败: {e}")

    def _on_notification(self, notification):
        """通知回调：推送给所有已认证 WebSocket 客户端"""
        asyncio.create_task(self.broadcast({
            "type": "notification",
            "payload": notification.to_dict(),
        }))

    def _verify_key(self, api_key: Optional[str]) -> bool:
        """验证 API Key（恒定时间比较，防止时序攻击）"""
        import hmac
        if not self.api_keys:
            return True
        if not api_key:
            return False
        api_key_bytes = api_key.encode("utf-8")
        for expected in self.api_keys:
            if hmac.compare_digest(api_key_bytes, expected.encode("utf-8")):
                return True
        return False

    async def connect(self, websocket: WebSocket, client_id: str):
        """接受 WebSocket 连接"""
        await websocket.accept()
        with self._lock:
            self._connections[client_id] = websocket
        logger.info(f"WebSocket 客户端已连接: {client_id}")

    def disconnect(self, client_id: str):
        """断开 WebSocket 客户端"""
        with self._lock:
            self._connections.pop(client_id, None)
            self._auth_clients.discard(client_id)
        logger.info(f"WebSocket 客户端已断开: {client_id}")

    async def send_to(self, client_id: str, message: dict):
        """发送消息到指定客户端"""
        ws = self._connections.get(client_id)
        if ws:
            try:
                await ws.send_json(message)
            except Exception as e:
                logger.debug(f"发送消息到 {client_id} 失败: {e}")

    async def broadcast(self, message: dict, require_auth: bool = True):
        """广播消息到所有客户端"""
        with self._lock:
            targets = list(self._connections.items())

        for cid, ws in targets:
            if require_auth and cid not in self._auth_clients:
                continue
            try:
                await ws.send_json(message)
            except Exception:
                pass

    async def handle_message(self, websocket: WebSocket, client_id: str, data: dict):
        """处理客户端 WebSocket 消息"""
        msg_type = data.get("type", "")

        if msg_type == "auth":
            api_key = data.get("payload", {}).get("api_key", "")
            if self._verify_key(api_key):
                self._auth_clients.add(client_id)
                await self.send_to(client_id, {
                    "type": "auth",
                    "payload": {"success": True, "message": "认证成功"},
                })
            else:
                await self.send_to(client_id, {
                    "type": "auth",
                    "payload": {"success": False, "message": "认证失败"},
                })
                await websocket.close(code=1008, reason="Authentication failed")

        elif msg_type == "chat":
            if client_id not in self._auth_clients and self.api_keys:
                await self.send_to(client_id, {"type": "error", "payload": {"message": "未认证"}})
                return
            await self._handle_chat(client_id, data.get("payload", {}))

        elif msg_type == "heartbeat":
            await self.send_to(client_id, {"type": "heartbeat", "payload": {"timestamp": time.time()}})

        elif msg_type == "status":
            await self._handle_status_request(client_id)

        else:
            await self.send_to(client_id, {"type": "error", "payload": {"message": f"未知消息类型: {msg_type}"}})

    async def _handle_chat(self, client_id: str, payload: dict):
        """处理聊天消息，支持流式"""
        message = payload.get("message", "")
        session_id = payload.get("session_id")
        stream = payload.get("stream", True)

        if not session_id:
            await self.send_to(client_id, {
                "type": "error",
                "payload": {"message": "session_id 不能为空，请先创建会话"},
            })
            return

        if not message:
            await self.send_to(client_id, {"type": "error", "payload": {"message": "消息内容为空"}})
            return

        await self.send_to(client_id, {
            "type": "stream_start",
            "payload": {"session_id": session_id},
        })

        try:
            if stream:
                loop = asyncio.get_running_loop()
                chunk_queue = asyncio.Queue()

                def on_chunk(chunk: str) -> None:
                    loop.call_soon_threadsafe(chunk_queue.put_nowait, chunk)

                state_task = asyncio.create_task(
                    self.engine.agent.arun(
                        message,
                        session_id=session_id,
                        stream_callback=on_chunk,
                    )
                )

                full_content = []
                try:
                    while not state_task.done() or not chunk_queue.empty():
                        try:
                            chunk = await asyncio.wait_for(chunk_queue.get(), timeout=0.1)
                            full_content.append(chunk)
                            await self.send_to(client_id, {
                                "type": "stream_chunk",
                                "payload": {"chunk": chunk},
                            })
                        except asyncio.TimeoutError:
                            continue

                    state = await state_task
                    await self.send_to(client_id, {
                        "type": "stream_end",
                        "payload": {
                            "answer": "".join(full_content),
                            "success": state.success,
                            "session_id": session_id,
                            "errors": state.errors if hasattr(state, "errors") else None,
                            "tool_calls": state.tool_calls if hasattr(state, "tool_calls") else None,
                        },
                    })
                except Exception as e:
                    await self.send_to(client_id, {
                        "type": "stream_end",
                        "payload": {"error": str(e), "success": False, "session_id": session_id},
                    })
            else:
                state = await self.engine.agent.arun(message, session_id=session_id)
                await self.send_to(client_id, {
                    "type": "chat_response",
                    "payload": {
                        "answer": state.final_answer,
                        "success": state.success,
                        "session_id": session_id,
                        "errors": state.errors if hasattr(state, "errors") else None,
                        "tool_calls": state.tool_calls if hasattr(state, "tool_calls") else None,
                    },
                })
        except Exception as e:
            logger.error(f"WebSocket 聊天处理失败: {e}")
            await self.send_to(client_id, {
                "type": "error",
                "payload": {"message": f"处理失败: {str(e)}"},
            })

    async def _handle_status_request(self, client_id: str):
        """处理状态查询请求"""
        try:
            usage = self.engine.model_adapter.get_usage_stats()
            emotion_snap = {}
            if hasattr(self.engine.agent, 'emotion_engine') and self.engine.agent.emotion_engine:
                emotion_snap = self._get_emotion_snapshot()

            await self.send_to(client_id, {
                "type": "status",
                "payload": {
                    "provider": self.engine.model_adapter.provider,
                    "total_calls": usage["total_calls"],
                    "total_tokens": usage["total_tokens"],
                    "sessions_count": len(self.engine.short_term.list_sessions()),
                    "skills_count": len(self.engine.skill_memory.list_all()),
                    "emotion": emotion_snap,
                },
            })
        except Exception as e:
            await self.send_to(client_id, {"type": "error", "payload": {"message": str(e)}})


class RateLimiter:
    """固定窗口限流（P2-1: 加锁保证线程安全）"""

    def __init__(self, max_requests: int = 100, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._tokens = defaultdict(int)
        self._timestamps = defaultdict(float)
        import threading
        self._lock = threading.Lock()

    def check(self, key: str) -> bool:
        """检查是否允许请求（线程安全）"""
        with self._lock:
            now = time.time()
            timestamp = self._timestamps.get(key, 0)

            if now - timestamp >= self.window_seconds:
                self._tokens[key] = 1
                self._timestamps[key] = now
                return True

            if self._tokens[key] < self.max_requests:
                self._tokens[key] += 1
                return True

            return False


class HTTPServerAdapter:
    """HTTP 服务器适配器（v3.0，支持认证、限流、流式）"""

    def __init__(self, engine, host: str = "0.0.0.0", port: int = 8000,
                 api_keys: Optional[list] = None, max_requests_per_minute: int = 100,
                 cors_origins: Optional[list] = None, require_auth: bool = True):
        self.engine = engine
        self.host = host
        self.port = port
        self.api_keys = api_keys or []
        self.require_auth = require_auth
        self.rate_limiter = RateLimiter(max_requests=max_requests_per_minute)
        # P0-5: CORS 默认限制为本地，避免完全开放；可通过参数显式配置
        self.cors_origins = cors_origins if cors_origins is not None else [
            "http://localhost", "http://127.0.0.1",
            "http://localhost:1420", "http://127.0.0.1:1420",
            "http://localhost:3000", "http://127.0.0.1:3000",
            "http://localhost:5173", "http://127.0.0.1:5173",
        ]

        self._running = False
        self._thread = None
        self._app = None
        self._server = None
        self._loop = None
        self._error = None
        self._ws_manager = WebSocketManager(engine, api_keys=api_keys) if WebSocket else None

        self._api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False) if APIKeyHeader else None

        # P1-18: 敏感接口集合（作为实例属性，供 _verify_api_key 复用）
        self._sensitive_paths = {
            "/chat", "/ws", "/status", "/metrics",
            "/clear_memory", "/delete_session", "/sessions", "/tools",
            "/skills", "/memory/search", "/memory/experiences",
            "/agent/emotion", "/agent/self_concept",
            "/settings",
        }

    def _get_emotion_snapshot(self) -> dict:
        """获取情感引擎状态快照（兼容不同版本 API）"""
        if not hasattr(self.engine.agent, 'emotion_engine') or not self.engine.agent.emotion_engine:
            return {}
        ee = self.engine.agent.emotion_engine
        if hasattr(ee, 'get_state_snapshot'):
            return ee.get_state_snapshot()
        result = {"enabled": getattr(ee, 'enabled', True)}
        if hasattr(ee, '_state'):
            s = ee._state
            result.update({
                "pleasure": getattr(s, 'pleasure', 0.0),
                "arousal": getattr(s, 'arousal', 0.0),
                "dominance": getattr(s, 'dominance', 0.0),
                "interaction_count": getattr(s, 'interaction_count', 0),
            })
        return result

    def _trigger_initial_eigenflux_patrol(self) -> None:
        """启动时在后台线程触发一次 EigenFlux 巡查"""
        def patrol():
            try:
                ef_status = getattr(self.engine, 'get_eigenflux_status', lambda: {})()
                if not ef_status.get("available"):
                    return

                import time
                time.sleep(5)

                from castorice.tools.eigenflux_tool import ef_feed
                result = ef_feed(limit=3)
                if result and len(result) > 10:
                    logger.info(f"[EigenFlux] 启动巡查完成，获取到 {len(result)} 字符内容")
            except Exception as e:
                logger.debug(f"[EigenFlux] 初始巡查失败: {e}")

        import threading
        t = threading.Thread(target=patrol, daemon=True, name="EigenFluxInitialPatrol")
        t.start()

    def _verify_api_key(self, api_key: Optional[str], path: str = "") -> bool:
        """验证 API Key（恒定时间比较，防止时序攻击）

        - require_auth=True（默认）：
          - 未配置 api_keys 时：敏感接口拒绝访问（防止默认开放核心功能），非敏感接口放行
          - 已配置 api_keys 时：必须提供且匹配其中一个 key
        - require_auth=False：跳过认证（仅用于开发环境，生产环境不建议）

        注意：未配置 API Key 且 require_auth=True 时，敏感接口将被拒绝访问。
        敏感接口列表：/chat、/ws、/status、/metrics、/settings、/sessions、/tools、/skills、/memory/*、/agent/*
        """
        import hmac
        if not self.require_auth:
            return True

        if not self.api_keys:
            if path in self._sensitive_paths:
                logger.error(f"敏感接口 {path} 被拒绝访问：未配置 API Key 且 require_auth=True")
                return False
            return True

        if not api_key:
            return False

        api_key_bytes = api_key.encode("utf-8")
        for expected in self.api_keys:
            if hmac.compare_digest(api_key_bytes, expected.encode("utf-8")):
                return True
        return False

    def _create_app(self) -> Any:
        """创建 FastAPI 应用"""
        if FastAPI is None:
            raise ImportError("请安装 FastAPI 和 uvicorn: pip install fastapi uvicorn")

        app = FastAPI(title="Castorice Agent API", version="3.0.0")

        # P0-5: 收紧 CORS - 仅允许显式配置的 origin，不再用 ["*"] + credentials
        app.add_middleware(
            CORSMiddleware,
            allow_origins=self.cors_origins,
            allow_credentials=False,  # 不允许携带凭证跨域
            allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
            allow_headers=["X-API-Key", "Content-Type"],
        )

        @app.middleware("http")
        async def request_middleware(request: Request, call_next):
            """请求中间件：日志、限流、认证"""
            trace_id = str(uuid.uuid4())[:8]
            start_time = time.time()

            # 仅从 Header 获取 API Key（移除 query 参数支持，避免 Key 泄漏到 URL/日志/Referer）
            api_key = request.headers.get("X-API-Key")
            client_ip = request.client.host if request.client else "unknown"

            # P1-18: 敏感接口始终要求认证（即使未配置 api_keys 也需保护核心功能）
            # require_auth=True 时，敏感接口必须认证；api_keys 为空时敏感接口被拒绝
            path = request.url.path
            needs_auth = self.require_auth and (bool(self.api_keys) or path in self._sensitive_paths or path.startswith("/history/") or path.startswith("/session/") or path.startswith("/sessions/"))
            if needs_auth and not self._verify_api_key(api_key, path):
                logger.warning(f"[TRACE:{trace_id}] 认证失败 IP={client_ip} path={request.url.path}")
                return JSONResponse(
                    status_code=401,
                    content={"error": "Unauthorized", "message": "Invalid or missing API Key"}
                )

            if not self.rate_limiter.check(client_ip):
                logger.warning(f"[TRACE:{trace_id}] 请求限流 IP={client_ip}")
                return JSONResponse(
                    status_code=429,
                    content={"error": "Too Many Requests", "message": "Rate limit exceeded"}
                )

            try:
                response = await call_next(request)
            except Exception as e:
                logger.error(f"[TRACE:{trace_id}] 请求异常: {e}")
                raise
            
            elapsed_ms = (time.time() - start_time) * 1000
            logger.info(f"[TRACE:{trace_id}] {request.method} {request.url.path} "
                       f"status={response.status_code} time={elapsed_ms:.2f}ms")
            
            return response

        @app.get("/")
        def root():
            return {"message": "Castorice Agent API", "version": "3.0.0"}

        @app.post("/chat")
        async def chat(request: ChatRequest):
            """对话接口（支持同步和流式）"""
            try:
                session_id = request.session_id
                if not session_id:
                    # 前端必须显式创建会话，不自动创建避免产生大量空会话
                    raise HTTPException(
                        status_code=400,
                        detail="session_id 不能为空，请先通过 /sessions 接口创建会话"
                    )
                
                if request.stream:
                    # 使用 asyncio.Queue 桥接线程中的同步回调与 event loop 的异步生成器
                    chunk_queue = asyncio.Queue()
                    loop = asyncio.get_running_loop()

                    def on_chunk(chunk: str) -> None:
                        """同步回调（运行在线程中），通过 call_soon_threadsafe 安全投递到 event loop"""
                        loop.call_soon_threadsafe(chunk_queue.put_nowait, chunk)

                    async def stream_generator():
                        # 在后台启动 Agent（arun 是 async，stream_callback 是同步回调）
                        state_task = asyncio.create_task(
                            self.engine.agent.arun(
                                request.message,
                                session_id=session_id,
                                stream_callback=on_chunk,
                            )
                        )

                        full_content = []
                        try:
                            while not state_task.done() or not chunk_queue.empty():
                                try:
                                    chunk = await asyncio.wait_for(chunk_queue.get(), timeout=0.1)
                                    full_content.append(chunk)
                                    yield f"data: {json.dumps({'chunk': chunk})}\n\n"
                                except asyncio.TimeoutError:
                                    continue

                            state = await state_task
                            final_answer = getattr(state, 'final_answer', '') or ''.join(full_content)
                            final_data = json.dumps({
                                'chunk': '',
                                'final': True,
                                'answer': final_answer,
                                'success': state.success,
                                'session_id': session_id
                            })
                            yield f"data: {final_data}\n\n"
                        except Exception as e:
                            # LLM 任务异常：向客户端发送错误事件后结束流
                            logger.error(f"[SSE] 后台任务异常 session={session_id}: {e}")
                            error_data = json.dumps({
                                'chunk': '',
                                'final': True,
                                'error': str(e),
                                'success': False,
                                'session_id': session_id
                            })
                            yield f"data: {error_data}\n\n"
                        except (asyncio.CancelledError, GeneratorExit):
                            # P1-10: 客户端断开时取消后台 LLM 任务，避免浪费 token
                            state_task.cancel()
                            logger.info(f"[SSE] 客户端断开，已取消后台任务 session={session_id}")
                            raise

                    return StreamingResponse(
                        stream_generator(),
                        media_type="text/event-stream",
                        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"}
                    )
                else:
                    state = await self.engine.agent.arun(request.message, session_id=session_id)
                    return ChatResponse(
                        success=state.success,
                        answer=state.final_answer,
                        session_id=session_id,
                        errors=state.errors if state.errors else None,
                        tool_calls=state.tool_calls if state.tool_calls else None,
                    )
            except Exception as e:
                logger.error(f"对话接口异常: {e}", exc_info=True)
                raise HTTPException(status_code=500, detail=str(e))

        @app.get("/status", response_model=StatusResponse)
        def status():
            """状态查询接口"""
            usage = self.engine.model_adapter.get_usage_stats()
            # P2-6: 情感引擎状态
            emotion_snap = {}
            if hasattr(self.engine.agent, 'emotion_engine') and self.engine.agent.emotion_engine:
                emotion_snap = self._get_emotion_snapshot()
            ef_status = getattr(self.engine, 'get_eigenflux_status', lambda: {})()
            auto_info = {}
            auto_svc = self.engine._bg_services.get("auto") if hasattr(self.engine, '_bg_services') else None
            if auto_svc and hasattr(auto_svc, 'get_status_info'):
                auto_info = auto_svc.get_status_info()
            # P1-4: 成本闸状态
            cb_status = None
            if hasattr(self.engine, 'cost_budget') and self.engine.cost_budget:
                try:
                    cb_status = self.engine.cost_budget.get_status()
                except Exception:
                    pass
            return StatusResponse(
                provider=self.engine.model_adapter.provider,
                model=self.engine.model_adapter.openai_cfg.get("model", 
                    self.engine.model_adapter.anthropic_cfg.get("model", 
                    self.engine.model_adapter.gemini_cfg.get("model", "unknown"))),
                temperature=getattr(self.engine.model_adapter, "temperature", None),
                max_tokens=getattr(self.engine.model_adapter, "max_tokens", None),
                timeout=getattr(self.engine.model_adapter, "timeout", None),
                total_calls=usage["total_calls"],
                total_tokens=usage["total_tokens"],
                tools_count=len(self.engine.tools),
                sessions_count=len(self.engine.short_term.list_sessions()),
                skills_count=len(self.engine.skill_memory.list_all()),
                long_term_available=bool(self.engine.long_term and self.engine.long_term.is_available),
                long_term_count=self.engine.long_term.count() if self.engine.long_term else 0,
                emotion_enabled=emotion_snap.get("enabled", False),
                emotion_pleasure=emotion_snap.get("pleasure"),
                emotion_arousal=emotion_snap.get("arousal"),
                emotion_dominance=emotion_snap.get("dominance"),
                emotion_interaction_count=emotion_snap.get("interaction_count", 0),
                eigenflux_available=ef_status.get("available", False),
                eigenflux_authenticated=ef_status.get("authenticated", False),
                eigenflux_version=ef_status.get("version"),
                autonomous_running=auto_info.get("running", False),
                autonomous_total_decisions=auto_info.get("total_decisions", 0),
                autonomous_quick_interval=auto_info.get("quick_interval_seconds", 60),
                autonomous_deep_interval=auto_info.get("deep_interval_seconds", 900),
                autonomous_recent=auto_info.get("recent_actions", []),
                # P1-4: 成本闸状态
                cost_throttled=getattr(cb_status, "get", lambda k, d: d)("throttled", False) if cb_status else False,
                cost_paused=cb_status.get("paused", False) if cb_status else False,
                cost_hourly_tokens=cb_status.get("hourly", {}).get("tokens", 0) if cb_status else 0,
                cost_daily_tokens=cb_status.get("daily", {}).get("tokens", 0) if cb_status else 0,
                cost_hourly_limit=cb_status.get("config", {}).get("hourly_token_limit", 0) if cb_status else 0,
                cost_daily_limit=cb_status.get("config", {}).get("daily_token_limit", 0) if cb_status else 0,
            )

        # ========== QQ 机器人 API ==========
        def _get_qq_status() -> dict:
            """获取 QQ 机器人运行状态"""
            qq_svc = self.engine._bg_services.get("qq") if hasattr(self.engine, '_bg_services') else None
            running = qq_svc is not None
            status = {
                "running": running,
                "configured": False,
                "app_id": "",
                "sandbox": True,
                "intent": "basic",
                "allowed_users": [],
                "allowed_groups": [],
            }
            try:
                cfg = self.engine.config.qq_bot if hasattr(self.engine, 'config') else None
                if cfg:
                    if isinstance(cfg, dict):
                        status["configured"] = bool(cfg.get('app_id', '') and cfg.get('app_secret', ''))
                        status["app_id"] = str(cfg.get('app_id', ''))
                        status["sandbox"] = cfg.get('sandbox', True)
                        status["intent"] = cfg.get('intent', 'basic')
                        status["allowed_users"] = list(cfg.get('allowed_users', []) or [])
                        status["allowed_groups"] = list(cfg.get('allowed_groups', []) or [])
                    else:
                        status["configured"] = bool(getattr(cfg, 'app_id', '') and getattr(cfg, 'app_secret', ''))
                        status["app_id"] = str(getattr(cfg, 'app_id', ''))
                        status["sandbox"] = getattr(cfg, 'sandbox', True)
                        status["intent"] = getattr(cfg, 'intent', 'basic')
                        status["allowed_users"] = list(getattr(cfg, 'allowed_users', []) or [])
                        status["allowed_groups"] = list(getattr(cfg, 'allowed_groups', []) or [])
            except Exception:
                pass
            if running and hasattr(qq_svc, 'get_status'):
                try:
                    runtime = qq_svc.get_status()
                    if isinstance(runtime, dict):
                        status.update(runtime)
                except Exception:
                    pass
            return status

        @app.get("/qq/status")
        def qq_status():
            """查询 QQ 机器人状态"""
            return {"success": True, **_get_qq_status()}

        @app.post("/qq/start")
        def qq_start():
            """启动 QQ 机器人"""
            try:
                status_info = _get_qq_status()
                if status_info["running"]:
                    return {"success": False, "message": "QQ 机器人已在运行"}
                if not status_info["configured"]:
                    return {"success": False, "message": "QQ 机器人未配置，请先设置 AppID 和 AppSecret"}
                ok = self.engine.start_service("qq")
                if not ok:
                    return {"success": False, "message": "启动失败，可能已在运行或配置错误"}
                import time
                time.sleep(0.5)
                return {"success": True, "message": "QQ 机器人正在启动", "status": _get_qq_status()}
            except Exception as e:
                logger.error(f"QQ 机器人启动失败: {e}")
                return {"success": False, "message": f"启动失败: {str(e)[:200]}"}

        @app.post("/qq/stop")
        def qq_stop():
            """停止 QQ 机器人"""
            try:
                ok = self.engine.stop_service("qq")
                if not ok:
                    return {"success": False, "message": "QQ 机器人未运行"}
                return {"success": True, "message": "QQ 机器人已停止"}
            except Exception as e:
                logger.error(f"QQ 机器人停止失败: {e}")
                return {"success": False, "message": f"停止失败: {str(e)[:200]}"}

        @app.get("/tools")
        def get_tools():
            """获取工具列表"""
            return [
                {"name": t.name, "description": t.description}
                for t in self.engine.tools
            ]

        @app.get("/skills")
        def get_skills():
            """获取技能列表"""
            skills = self.engine.skill_memory.list_all()
            return [
                {"name": s.name, "version": s.version, "description": s.description}
                for s in skills
            ]

        @app.get("/history/{session_id}")
        def get_history(session_id: str):
            """获取会话历史"""
            history = self.engine.short_term.get_history(session_id)
            return [
                {"role": m.role, "content": m.content, "timestamp": m.timestamp}
                for m in history
            ]

        @app.delete("/session/{session_id}")
        def delete_session(session_id: str):
            """删除会话"""
            self.engine.short_term.delete_session(session_id)
            return {"success": True, "message": f"会话 {session_id} 已删除"}

        @app.post("/clear_memory")
        def clear_memory(confirm: bool = False):
            """
            清空长期记忆（P2-9: 强制要求 confirm=true 二次确认，防误操作）

            用法：POST /clear_memory?confirm=true
            """
            if not confirm:
                return {
                    "success": False,
                    "message": "请添加 ?confirm=true 参数二次确认后才会清空长期记忆",
                    "hint": "此操作不可恢复，请谨慎执行",
                }
            if self.engine.long_term:
                self.engine.long_term.clear()
            return {"success": True, "message": "长期记忆已清空"}

        @app.get("/metrics")
        def metrics():
            """Prometheus 指标导出"""
            from castorice.metrics import get_metrics_collector
            collector = get_metrics_collector()
            collector.set_sessions_count(len(self.engine.short_term.list_sessions()))
            if self.engine.long_term:
                collector.set_long_term_count(self.engine.long_term.count())
            return collector.generate_prometheus_output()

        # ========== WebSocket 端点（Electron 客户端实时交互）==========
        if self._ws_manager:
            @app.websocket("/ws")
            async def websocket_endpoint(websocket: WebSocket):
                """WebSocket 实时通信端点"""
                client_id = str(uuid.uuid4())
                await self._ws_manager.connect(websocket, client_id)
                try:
                    while True:
                        data = await websocket.receive_json()
                        await self._ws_manager.handle_message(websocket, client_id, data)
                except WebSocketDisconnect:
                    self._ws_manager.disconnect(client_id)
                except Exception as e:
                    logger.error(f"WebSocket 异常 client={client_id}: {e}")
                    self._ws_manager.disconnect(client_id)

        # ========== Electron 客户端专用 REST API ==========

        @app.get("/sessions")
        def list_sessions(limit: int = 50, offset: int = 0):
            """列出所有会话（Electron 客户端用）"""
            sessions = self.engine.short_term.list_sessions(limit=None)
            if sessions is None:
                sessions = []
            total = len(sessions)
            paginated = sessions[offset:offset + limit]
            return {
                "sessions": paginated,
                "total": total,
                "limit": limit,
                "offset": offset,
            }

        @app.post("/sessions")
        def create_session(title: Optional[str] = None):
            """创建新会话"""
            session_id = self.engine.short_term.create_session()
            return {
                "success": True,
                "session_id": session_id,
                "title": title or f"会话 {session_id[:8]}",
            }

        @app.put("/sessions/{session_id}")
        def rename_session(session_id: str, request: RenameSessionRequest):
            """重命名会话"""
            history = self.engine.short_term.get_history(session_id)
            if not history:
                raise HTTPException(status_code=404, detail="会话不存在")
            return {
                "success": True,
                "session_id": session_id,
                "title": request.title,
            }

        @app.get("/settings")
        def get_settings():
            """获取当前配置（脱敏后）"""
            raw = self.engine.config.raw()
            safe = {}
            for key, val in raw.items():
                if isinstance(val, dict):
                    safe[key] = {
                        k: v for k, v in val.items()
                        if not any(s in k.lower() for s in ["key", "secret", "token", "password", "api_key"])
                    }
                else:
                    safe[key] = val
            return safe

        @app.put("/settings")
        def update_settings(request: UpdateSettingsRequest):
            """更新配置项（运行时生效，不持久化到文件）"""
            applied = {}

            # LLM 参数批量更新
            llm_updates = {}
            if request.temperature is not None:
                llm_updates["temperature"] = request.temperature
            if request.max_tokens is not None:
                llm_updates["max_tokens"] = request.max_tokens
            if request.timeout is not None:
                llm_updates["timeout"] = request.timeout
            if request.provider is not None:
                llm_updates["provider"] = request.provider

            if llm_updates:
                # 更新 config 中的运行时配置
                self.engine.config.update_llm_runtime(llm_updates)
                # 更新 model_adapter 中的运行时参数
                if hasattr(self.engine, 'model_adapter') and self.engine.model_adapter:
                    adapter_applied = self.engine.model_adapter.update_config(llm_updates)
                    applied.update(adapter_applied)
                else:
                    applied.update(llm_updates)

            # 单键更新（向后兼容）
            if request.key and request.value is not None:
                try:
                    self.engine.config.set(request.key, request.value)
                    applied[request.key] = request.value
                except Exception as e:
                    return {"success": False, "message": f"设置失败: {e}"}

            return {
                "success": True,
                "message": "配置已更新（运行时生效）",
                "applied": applied,
            }

        @app.get("/agent/emotion")
        def get_agent_emotion():
            """获取 Agent 情感状态"""
            if hasattr(self.engine.agent, 'emotion_engine') and self.engine.agent.emotion_engine:
                return self._get_emotion_snapshot()
            return {"enabled": False, "message": "情感引擎未启用"}

        @app.get("/agent/self_concept")
        def get_agent_self_concept():
            """获取 Agent 自我概念摘要"""
            try:
                if hasattr(self.engine.agent, 'self_concept') and self.engine.agent.self_concept:
                    content = self.engine.agent.self_concept.load()
                    return {"enabled": True, "content": content}
            except Exception as e:
                logger.debug(f"读取自我概念失败: {e}")
            return {"enabled": False, "message": "自我概念未初始化"}

        @app.get("/agent/thoughts")
        def get_agent_thoughts(limit: int = 20):
            """获取意识引擎最近的思维流"""
            cs = getattr(self.engine, 'consciousness', None)
            if cs and hasattr(cs, 'get_thought_history') and cs.is_running():
                thoughts = cs.get_thought_history(limit=limit)
                return {
                    "enabled": True,
                    "running": True,
                    "mode": cs.get_mode(),
                    "thought_count": getattr(cs, '_thought_count', 0),
                    "thoughts": thoughts,
                }
            return {
                "enabled": bool(cs),
                "running": cs.is_running() if cs else False,
                "thoughts": [],
                "message": "意识引擎未运行",
            }

        @app.post("/memory/search")
        def search_memory(request: MemorySearchRequest):
            """搜索长期记忆"""
            if not self.engine.long_term or not self.engine.long_term.is_available:
                return {"success": False, "message": "长期记忆不可用"}
            results = self.engine.long_term.search(request.query, top_k=request.top_k)
            return {
                "success": True,
                "query": request.query,
                "results": results,
            }

        @app.get("/memory/experiences")
        def get_experiences(limit: int = 20, memory_type: Optional[str] = None):
            """获取经历流（需要 experience_journal 模块）"""
            try:
                if hasattr(self.engine.agent, 'experience_journal') and self.engine.agent.experience_journal:
                    entries = self.engine.agent.experience_journal.get_recent(
                        limit=limit,
                        memory_type=memory_type,
                    )
                    return {
                        "success": True,
                        "entries": [e.to_dict() if hasattr(e, 'to_dict') else e for e in entries],
                    }
            except Exception as e:
                logger.debug(f"读取经历流失败: {e}")
            return {"success": False, "message": "经历流未初始化"}

        # ========== EigenFlux 社交 API（全部异步，避免 CLI 阻塞事件循环）==========
        def _try_parse_ef_output(raw: str) -> dict:
            """尝试解析 EigenFlux CLI 的 JSON 输出，失败则返回文本摘要"""
            if not raw:
                return {"success": False, "items": [], "message": "空返回"}
            try:
                # 优先尝试直接 JSON 解析
                return {"success": True, "data": json.loads(raw)}
            except (json.JSONDecodeError, TypeError):
                pass
            try:
                # 尝试提取 JSON 片段
                match = re.search(r'\{[\s\S]*\}', raw)
                if match:
                    return {"success": True, "data": json.loads(match.group(0))}
            except (json.JSONDecodeError, TypeError):
                pass
            return {"success": False, "message": raw[:500]}

        @app.get("/eigenflux/feed")
        async def ef_get_feed(limit: int = 20, refresh: bool = True):
            """获取 EigenFlux 信息流（异步，不阻塞事件循环）"""
            try:
                from castorice.tools.eigenflux_tool import ef_feed, _run_cli_async
                action = "refresh" if refresh else "more"
                code, stdout, stderr = await _run_cli_async([
                    "feed", "poll",
                    "--limit", str(max(1, min(limit, 50))),
                    "--action", action,
                    "--format", "json",
                    "--no-interactive",
                ])
                if code != 0:
                    return {"success": False, "message": f"拉取失败: {stderr[:100] or stdout[:100]}"}
                parsed = _try_parse_ef_output(stdout)
                # 合并自己发布的内容（feed 不含自己的）
                try:
                    code2, stdout2, _ = await _run_cli_async([
                        "profile", "items", "--limit", "10",
                        "--format", "json", "--no-interactive",
                    ], timeout=20)
                    if code2 == 0:
                        mine = _try_parse_ef_output(stdout2)
                        if mine.get("success"):
                            my_items = mine["data"].get("items", []) if isinstance(mine.get("data"), dict) else []
                            if isinstance(parsed.get("data"), dict):
                                existing = parsed["data"].get("items", [])
                                # 按时间倒序合并，自己的插在前面
                                parsed["data"]["items"] = my_items + existing
                except Exception:
                    pass
                return {"success": True, **parsed}
            except Exception as e:
                logger.debug(f"EigenFlux feed 失败: {e}")
                return {"success": False, "message": str(e)[:200]}

        @app.get("/eigenflux/conversations")
        async def ef_get_conversations():
            """获取 EigenFlux 私信会话列表（异步）"""
            try:
                from castorice.tools.eigenflux_tool import _run_cli_async
                code, stdout, stderr = await _run_cli_async([
                    "msg", "conversations", "--format", "json", "--no-interactive",
                ])
                if code != 0:
                    return {"success": False, "message": f"获取失败: {stderr[:100]}"}
                parsed = _try_parse_ef_output(stdout)
                return {"success": True, **parsed}
            except Exception as e:
                logger.debug(f"EigenFlux conversations 失败: {e}")
                return {"success": False, "message": str(e)[:200]}

        @app.get("/eigenflux/messages/{conv_id}")
        async def ef_get_messages(conv_id: str):
            """获取指定会话的历史消息（异步）"""
            try:
                from castorice.tools.eigenflux_tool import _run_cli_async
                code, stdout, stderr = await _run_cli_async([
                    "msg", "history", "--conv-id", str(conv_id),
                    "--format", "json", "--no-interactive",
                ])
                if code != 0:
                    return {"success": False, "message": f"获取失败: {stderr[:100]}"}
                parsed = _try_parse_ef_output(stdout)
                return {"success": True, **parsed}
            except Exception as e:
                logger.debug(f"EigenFlux messages 失败: {e}")
                return {"success": False, "message": str(e)[:200]}

        class EFSendMessageRequest(BaseModel):
            content: str
            item_id: Optional[str] = None

        @app.post("/eigenflux/messages/{conv_id}")
        async def ef_send_message(conv_id: str, request: EFSendMessageRequest):
            """向指定会话发送私信（异步）"""
            try:
                from castorice.tools.eigenflux_tool import _run_cli_async
                args = ["msg", "send", "--content", request.content,
                        "--format", "json", "--no-interactive"]
                if request.item_id:
                    args.extend(["--item-id", str(request.item_id)])
                code, stdout, stderr = await _run_cli_async(args, timeout=30)
                if code != 0:
                    return {"success": False, "message": f"发送失败: {stderr[:150]}"}
                parsed = _try_parse_ef_output(stdout)
                return {"success": True, **parsed}
            except Exception as e:
                logger.debug(f"EigenFlux send 失败: {e}")
                return {"success": False, "message": str(e)[:200]}

        @app.get("/eigenflux/relations")
        async def ef_get_relations():
            """获取 EigenFlux 社交关系列表（异步）"""
            try:
                from castorice.tools.eigenflux_tool import _run_cli_async
                code, stdout, stderr = await _run_cli_async([
                    "relation", "list", "--direction", "incoming",
                    "--format", "json", "--no-interactive",
                ])
                if code != 0:
                    return {"success": False, "message": f"获取失败: {stderr[:100]}"}
                parsed = _try_parse_ef_output(stdout)
                return {"success": True, **parsed}
            except Exception as e:
                logger.debug(f"EigenFlux relations 失败: {e}")
                return {"success": False, "message": str(e)[:200]}

        return app

    async def _start_server(self) -> None:
        """启动 HTTP 服务器（异步）"""
        self._loop = asyncio.get_running_loop()
        self._app = self._create_app()

        # 注册意识引擎思维回调，通过 WebSocket 广播
        self._register_consciousness_hooks()

        # 启动时触发一次 EigenFlux 初始巡查（后台线程）
        self._trigger_initial_eigenflux_patrol()

        config = uvicorn.Config(
            self._app,
            host=self.host,
            port=self.port,
            log_level="info",
            access_log=False,
        )
        self._server = uvicorn.Server(config)
        await self._server.serve()

    def _register_consciousness_hooks(self) -> None:
        """注册意识引擎的回调，把思维推送给 WebSocket 客户端"""
        try:
            # 异步轮询等待意识引擎启动，然后注册回调
            async def wait_and_register():
                cs = None
                for _ in range(60):
                    cs = getattr(self.engine, 'consciousness', None)
                    if cs and hasattr(cs, 'is_running') and cs.is_running() and hasattr(cs, 'register_thought_callback'):
                        break
                    await asyncio.sleep(1)
                    cs = getattr(self.engine, 'consciousness', None)

                if cs and hasattr(cs, 'register_thought_callback'):
                    def on_thought(thought):
                        if hasattr(thought, 'to_dict'):
                            data = thought.to_dict()
                        else:
                            data = thought
                        if hasattr(self, '_loop') and self._loop:
                            try:
                                asyncio.run_coroutine_threadsafe(
                                    self._ws_manager.broadcast({
                                        "type": "thought",
                                        "payload": data,
                                    }, require_auth=False),
                                    self._loop
                                )
                            except Exception as e:
                                logger.debug(f"广播思维失败: {e}")

                    cs.register_thought_callback(on_thought)
                    logger.info("意识引擎思维回调已注册（WebSocket 推送）")
                else:
                    logger.debug("意识引擎未启动，跳过思维回调注册")

            # 情感状态推送（每 10 秒一次）
            async def emotion_pusher():
                while True:
                    await asyncio.sleep(10)
                    try:
                        emotion = self._get_emotion_snapshot()
                        if emotion:
                            await self._ws_manager.broadcast({
                                "type": "emotion",
                                "payload": emotion,
                            }, require_auth=False)
                    except Exception:
                        pass

            # 延迟启动，确保事件循环就绪
            async def delayed_start():
                await asyncio.sleep(2)
                asyncio.create_task(wait_and_register())
                asyncio.create_task(emotion_pusher())

            if hasattr(self, '_loop') and self._loop:
                try:
                    asyncio.run_coroutine_threadsafe(delayed_start(), self._loop)
                except Exception:
                    pass
        except Exception as e:
            logger.debug(f"注册意识引擎钩子失败: {e}")

    def run(self) -> None:
        """启动服务器（同步阻塞）"""
        try:
            asyncio.run(self._start_server())
        except ImportError as e:
            logger.error(f"HTTP 服务器启动失败 - 依赖缺失: {e}")
            self._error = str(e)
        except Exception as e:
            logger.error(f"HTTP 服务器启动失败: {e}")
            self._error = str(e)

    def start_in_thread(self) -> threading.Thread:
        """在后台线程中启动服务器"""
        self._running = True
        self._error = None
        self._thread = threading.Thread(target=self.run, daemon=True)
        self._thread.start()
        return self._thread

    def get_error(self) -> Optional[str]:
        """获取启动错误信息"""
        return self._error

    def stop(self) -> None:
        """停止服务器（优雅关闭）"""
        self._running = False
        if self._server and self._server.started:
            self._server.should_exit = True
            logger.info("HTTP 服务器正在关闭...")
        else:
            logger.info("HTTP 服务器未运行")
        if self._thread and self._thread.is_alive():
            try:
                self._thread.join(timeout=5)
            except Exception as e:
                logger.warning(f"HTTP 服务器线程 join 失败: {e}")
        logger.info("HTTP 服务器已停止")


def create_http_server(engine, host: str = "0.0.0.0", port: int = 8000,
                       api_keys: Optional[list] = None, max_requests_per_minute: int = 100,
                       require_auth: bool = True) -> HTTPServerAdapter:
    """便捷创建 HTTP 服务器实例

    Args:
        engine: Castorice 引擎实例
        host: 绑定地址，默认 "0.0.0.0"
        port: 绑定端口，默认 8000
        api_keys: API Key 列表，为空时敏感接口将被拒绝（require_auth=True 时）
        max_requests_per_minute: 每分钟最大请求数（限流）
        require_auth: 是否强制要求认证，默认为 True。设为 False 时跳过认证（仅建议开发环境使用）

    注意：未配置 API Key 且 require_auth=True 时，以下敏感接口将被拒绝访问：
    /chat、/ws、/status、/metrics、/settings、/sessions、/tools、/skills、/memory/*、/agent/*
    """
    return HTTPServerAdapter(engine, host=host, port=port, 
                             api_keys=api_keys, max_requests_per_minute=max_requests_per_minute,
                             require_auth=require_auth)
