"""
MCP (Model Context Protocol) 客户端

纯 Python 实现的 MCP 客户端，通过 stdio 连接 MCP 服务器，
自动发现工具并注册到 Castorice 的工具系统。

支持：
- 多个 MCP 服务器（通过配置列表）
- 工具自动发现与注册
- 工具调用转发
- 进程生命周期管理

协议参考：https://spec.modelcontextprotocol.io/
"""

import asyncio
import json
import logging
import os
import subprocess
import threading
import uuid
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("Castorice.MCP")


class MCPServerConfig:
    """单个 MCP 服务器的配置"""

    def __init__(
        self,
        name: str,
        command: str,
        args: Optional[List[str]] = None,
        env: Optional[Dict[str, str]] = None,
        cwd: Optional[str] = None,
    ):
        self.name = name
        self.command = command
        self.args = args or []
        self.env = env or {}
        self.cwd = cwd

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "command": self.command,
            "args": self.args,
            "env": self.env,
            "cwd": self.cwd,
        }


class MCPServerConnection:
    """到单个 MCP 服务器的连接（stdio 传输）"""

    def __init__(self, config: MCPServerConfig):
        self.config = config
        self._proc: Optional[subprocess.Popen] = None
        self._request_id = 0
        self._lock = threading.Lock()
        self._pending: Dict[str, asyncio.Future] = {}
        self._initialized = False
        self._tools: List[Dict[str, Any]] = []
        self._reader_thread: Optional[threading.Thread] = None
        self._running = False

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------
    def start(self) -> None:
        """启动 MCP 服务器进程并建立连接"""
        if self._proc and self._proc.poll() is None:
            return

        env = os.environ.copy()
        env.update(self.config.env)

        logger.info(f"启动 MCP 服务器: {self.config.name} -> {self.config.command} {' '.join(self.config.args)}")

        try:
            self._proc = subprocess.Popen(
                [self.config.command, *self.config.args],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
                cwd=self.config.cwd,
                bufsize=0,
            )
        except Exception as e:
            logger.error(f"启动 MCP 服务器 {self.config.name} 失败: {e}")
            raise

        self._running = True
        self._reader_thread = threading.Thread(
            target=self._reader_loop, daemon=True, name=f"MCP-{self.config.name}"
        )
        self._reader_thread.start()

        # 初始化握手
        try:
            self._initialize_sync()
        except Exception as e:
            logger.error(f"MCP 服务器 {self.config.name} 初始化失败: {e}")
            self.stop()
            raise

    def stop(self) -> None:
        self._running = False
        if self._proc:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=5)
            except Exception:
                try:
                    self._proc.kill()
                except Exception:
                    pass
            self._proc = None
        self._initialized = False
        self._tools = []

    # ------------------------------------------------------------------
    # 协议：读 / 写
    # ------------------------------------------------------------------
    def _reader_loop(self) -> None:
        assert self._proc is not None and self._proc.stdout is not None
        buf = b""
        while self._running:
            try:
                chunk = self._proc.stdout.read(4096)
            except Exception:
                break
            if not chunk:
                break
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line.decode("utf-8"))
                except json.JSONDecodeError:
                    logger.debug(f"MCP {self.config.name} 收到非 JSON: {line[:200]}")
                    continue
                self._dispatch_message(msg)

        if self._running:
            logger.warning(f"MCP 服务器 {self.config.name} 进程已退出")

    def _dispatch_message(self, msg: Dict[str, Any]) -> None:
        if "id" in msg and ("result" in msg or "error" in msg):
            rid = str(msg["id"])
            if rid in self._pending:
                fut = self._pending.pop(rid)
                loop = fut.get_loop()
                if "error" in msg:
                    loop.call_soon_threadsafe(fut.set_exception, RuntimeError(msg["error"]))
                else:
                    loop.call_soon_threadsafe(fut.set_result, msg.get("result"))
        elif msg.get("method") == "notifications/message":
            logger.debug(f"MCP {self.config.name} notification: {msg.get('params')}")
        else:
            logger.debug(f"MCP {self.config.name} 忽略消息: {msg}")

    def _send_request_sync(self, method: str, params: Optional[Dict[str, Any]] = None, timeout: float = 30.0) -> Any:
        """同步发送 JSON-RPC 请求（在调用线程等待结果）"""
        assert self._proc is not None and self._proc.stdin is not None

        with self._lock:
            self._request_id += 1
            rid = str(self._request_id)

        loop = asyncio.new_event_loop()
        try:
            fut = loop.create_future()
            self._pending[rid] = fut

            payload = json.dumps({
                "jsonrpc": "2.0",
                "id": rid,
                "method": method,
                "params": params or {},
            }) + "\n"

            with self._lock:
                self._proc.stdin.write(payload.encode("utf-8"))
                self._proc.stdin.flush()

            try:
                return loop.run_until_complete(asyncio.wait_for(fut, timeout=timeout))
            except asyncio.TimeoutError:
                self._pending.pop(rid, None)
                raise TimeoutError(f"MCP {self.config.name} 请求 {method} 超时")
        finally:
            loop.close()

    # ------------------------------------------------------------------
    # 协议：初始化
    # ------------------------------------------------------------------
    def _initialize_sync(self) -> None:
        # initialize
        result = self._send_request_sync("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "clientInfo": {"name": "castorice", "version": "1.0.0"},
        })
        logger.info(f"MCP {self.config.name} 初始化成功: {result.get('serverInfo')}")

        # notifications/initialized
        try:
            self._send_request_sync("notifications/initialized", timeout=5)
        except Exception:
            pass  # 通知不需要结果

        self._initialized = True

        # 获取工具列表
        try:
            tools_result = self._send_request_sync("tools/list", timeout=10)
            self._tools = tools_result.get("tools", [])
            logger.info(f"MCP {self.config.name} 发现 {len(self._tools)} 个工具")
        except Exception as e:
            logger.warning(f"MCP {self.config.name} 获取工具列表失败: {e}")

    # ------------------------------------------------------------------
    # 工具调用
    # ------------------------------------------------------------------
    @property
    def tools(self) -> List[Dict[str, Any]]:
        return list(self._tools)

    def call_tool(self, tool_name: str, arguments: Optional[Dict[str, Any]] = None) -> Any:
        if not self._initialized:
            self.start()
        result = self._send_request_sync("tools/call", {
            "name": tool_name,
            "arguments": arguments or {},
        })
        return result


class MCPClient:
    """
    MCP 客户端管理器：管理多个 MCP 服务器连接

    使用示例：
    >>> mcp = MCPClient()
    >>> mcp.add_server(MCPServerConfig("filesystem", "python", ["-m", "mcp_server_filesystem"]))
    >>> mcp.start_all()
    >>> tools = mcp.get_all_tools()
    """

    def __init__(self):
        self._servers: Dict[str, MCPServerConnection] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # 配置
    # ------------------------------------------------------------------
    def add_server(self, config: MCPServerConfig) -> None:
        with self._lock:
            if config.name in self._servers:
                logger.warning(f"MCP 服务器 {config.name} 已存在，覆盖")
                old = self._servers.pop(config.name)
                try:
                    old.stop()
                except Exception:
                    pass
            self._servers[config.name] = MCPServerConnection(config)

    def remove_server(self, name: str) -> None:
        with self._lock:
            if name in self._servers:
                conn = self._servers.pop(name)
                try:
                    conn.stop()
                except Exception:
                    pass

    def list_servers(self) -> List[Dict[str, Any]]:
        with self._lock:
            result = []
            for name, conn in self._servers.items():
                result.append({
                    "name": name,
                    "running": conn._proc is not None and conn._proc.poll() is None,
                    "tool_count": len(conn.tools),
                    "config": conn.config.to_dict(),
                })
            return result

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------
    def start_all(self) -> Dict[str, bool]:
        results: Dict[str, bool] = {}
        with self._lock:
            servers = list(self._servers.values())
        for conn in servers:
            try:
                conn.start()
                results[conn.config.name] = True
            except Exception as e:
                logger.error(f"启动 MCP 服务器 {conn.config.name} 失败: {e}")
                results[conn.config.name] = False
        return results

    def stop_all(self) -> None:
        with self._lock:
            servers = list(self._servers.values())
        for conn in servers:
            try:
                conn.stop()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # 工具
    # ------------------------------------------------------------------
    def get_all_tools(self) -> List[Dict[str, Any]]:
        tools: List[Dict[str, Any]] = []
        with self._lock:
            servers = list(self._servers.values())
        for conn in servers:
            for t in conn.tools:
                tools.append({
                    **t,
                    "mcp_server": conn.config.name,
                })
        return tools

    def call_tool(self, server_name: str, tool_name: str, arguments: Optional[Dict[str, Any]] = None) -> Any:
        with self._lock:
            conn = self._servers.get(server_name)
        if not conn:
            raise KeyError(f"MCP 服务器 {server_name} 不存在")
        return conn.call_tool(tool_name, arguments)
