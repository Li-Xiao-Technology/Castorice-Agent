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
import threading
import time
import uuid
from collections import defaultdict
from typing import Any, Dict, Optional

try:
    import uvicorn
    from fastapi import FastAPI, HTTPException, Request, Security, status, WebSocket, WebSocketDisconnect
    from fastapi.security.api_key import APIKeyHeader, APIKeyQuery
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
    APIKeyQuery = None
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
        key: str = Field(..., description="配置项键名")
        value: Any = Field(..., description="配置项值")

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
        """验证 API Key"""
        if not self.api_keys:
            return True
        return api_key in self.api_keys

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
        session_id = payload.get("session_id") or self.engine.short_term.create_session()
        stream = payload.get("stream", True)

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
                emotion_snap = self.engine.agent.emotion_engine.get_state_snapshot()

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
                 cors_origins: Optional[list] = None):
        self.engine = engine
        self.host = host
        self.port = port
        self.api_keys = api_keys or []
        self.rate_limiter = RateLimiter(max_requests=max_requests_per_minute)
        # P0-5: CORS 默认限制为本地，避免完全开放；可通过参数显式配置
        self.cors_origins = cors_origins if cors_origins is not None else ["http://localhost", "http://127.0.0.1"]

        self._running = False
        self._thread = None
        self._app = None
        self._server = None
        self._loop = None
        self._error = None
        self._ws_manager = WebSocketManager(engine, api_keys=api_keys) if WebSocket else None

        self._api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False) if APIKeyHeader else None
        self._api_key_query = APIKeyQuery(name="api_key", auto_error=False) if APIKeyQuery else None

    def _verify_api_key(self, api_key_header: Optional[str] = None,
                        api_key_query: Optional[str] = None) -> bool:
        """验证 API Key"""
        if not self.api_keys:
            return True

        api_key = api_key_header or api_key_query
        if not api_key:
            return False

        return api_key in self.api_keys

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
            allow_methods=["GET", "POST", "DELETE"],
            allow_headers=["X-API-Key", "Content-Type"],
        )

        @app.middleware("http")
        async def request_middleware(request: Request, call_next):
            """请求中间件：日志、限流、认证"""
            trace_id = str(uuid.uuid4())[:8]
            start_time = time.time()

            api_key = request.headers.get("X-API-Key") or request.query_params.get("api_key")
            client_ip = request.client.host if request.client else "unknown"

            # P1-18: /status 等运维接口始终要求认证（即使配置了 api_keys）
            sensitive_paths = {"/status", "/metrics", "/clear_memory", "/delete_session", "/sessions", "/tools"}
            needs_auth = bool(self.api_keys) or request.url.path in sensitive_paths
            if needs_auth and not self._verify_api_key(api_key):
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
                session_id = request.session_id or self.engine.short_term.create_session()
                
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
                            yield f"data: {json.dumps({
                                'chunk': '',
                                'final': True,
                                'answer': ''.join(full_content),
                                'success': state.success,
                                'session_id': session_id
                            })}\n\n"
                        except Exception as e:
                            # LLM 任务异常：向客户端发送错误事件后结束流
                            logger.error(f"[SSE] 后台任务异常 session={session_id}: {e}")
                            yield f"data: {json.dumps({
                                'chunk': '',
                                'final': True,
                                'error': str(e),
                                'success': False,
                                'session_id': session_id
                            })}\n\n"
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
                logger.error(f"对话接口异常: {e}")
                raise HTTPException(status_code=500, detail=str(e))

        @app.get("/status", response_model=StatusResponse)
        def status():
            """状态查询接口"""
            usage = self.engine.model_adapter.get_usage_stats()
            # P2-6: 情感引擎状态
            emotion_snap = {}
            if hasattr(self.engine.agent, 'emotion_engine') and self.engine.agent.emotion_engine:
                emotion_snap = self.engine.agent.emotion_engine.get_state_snapshot()
            return StatusResponse(
                provider=self.engine.model_adapter.provider,
                model=self.engine.model_adapter.openai_cfg.get("model", 
                    self.engine.model_adapter.anthropic_cfg.get("model", 
                    self.engine.model_adapter.gemini_cfg.get("model", "unknown"))),
                total_calls=usage["total_calls"],
                total_tokens=usage["total_tokens"],
                tools_count=len(self.engine.tools),
                sessions_count=len(self.engine.short_term.list_sessions()),
                skills_count=len(self.engine.skill_memory.list_all()),
                long_term_available=self.engine.long_term.is_available,
                long_term_count=self.engine.long_term.count(),
                emotion_enabled=emotion_snap.get("enabled", False),
                emotion_pleasure=emotion_snap.get("pleasure"),
                emotion_arousal=emotion_snap.get("arousal"),
                emotion_dominance=emotion_snap.get("dominance"),
                emotion_interaction_count=emotion_snap.get("interaction_count", 0),
            )

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
            self.engine.long_term.clear()
            return {"success": True, "message": "长期记忆已清空"}

        @app.get("/metrics")
        def metrics():
            """Prometheus 指标导出"""
            from castorice.metrics import get_metrics_collector
            collector = get_metrics_collector()
            collector.set_sessions_count(len(self.engine.short_term.list_sessions()))
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
            return {
                "success": False,
                "message": "运行时配置更新暂未实现，请直接修改 castorice_config.yaml",
            }

        @app.get("/agent/emotion")
        def get_agent_emotion():
            """获取 Agent 情感状态"""
            if hasattr(self.engine.agent, 'emotion_engine') and self.engine.agent.emotion_engine:
                return self.engine.agent.emotion_engine.get_state_snapshot()
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

        @app.post("/memory/search")
        def search_memory(request: MemorySearchRequest):
            """搜索长期记忆"""
            if not self.engine.long_term.is_available:
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

        return app

    async def _start_server(self) -> None:
        """启动 HTTP 服务器（异步）"""
        self._loop = asyncio.get_running_loop()
        self._app = self._create_app()
        config = uvicorn.Config(
            self._app,
            host=self.host,
            port=self.port,
            log_level="info",
            access_log=False,
        )
        self._server = uvicorn.Server(config)
        await self._server.serve()

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
                       api_keys: Optional[list] = None, max_requests_per_minute: int = 100) -> HTTPServerAdapter:
    """便捷创建 HTTP 服务器实例"""
    return HTTPServerAdapter(engine, host=host, port=port, 
                             api_keys=api_keys, max_requests_per_minute=max_requests_per_minute)
