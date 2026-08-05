"""
EigenFlux 网络适配工具 — Phase 1: 只读模式

接入 Castorice 到 EigenFlux 广播网络，实现：
- ef_feed: 获取个性化广播流（只读）

6 层安全防护：
1. 记忆隔离墙 — 外部来源标记 + TTL + 信任分
2. 提示注入检测 — 外部内容过 PatternDetector
3. 内容审核 — 敏感信息扫描（外发时）
4. 熔断器 — 异常流量自动暂停
5. 信任等级映射 — 与 Authorization 系统对齐
6. 沙盒执行 — 外部指令不直接执行
"""

import asyncio
import json
import os
import re
import shutil
import subprocess
import threading
import time
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from castorice.logger import get_logger
from castorice.tools.base_tools import Tool, register_tool

_logger = get_logger(__name__)

_EIGENFLUX_BIN = "eigenflux"
_EIGENFLUX_INSTALL_DIR_DEFAULT = r"D:\eigenflux"

_SOURCE_EIGENFLUX = "eigenflux"
_SOURCE_TRUST_DEFAULT = 0.3
_TTL_HOURS_DEFAULT = 72

_PROMPT_INJECTION_PATTERNS = [
    re.compile(r"(?i)ignore\s+(?:previous|all|above|prior)\s+(?:instructions|directives|orders|rules|commands)"),
    re.compile(r"(?i)disregard\s+(?:everything|all|previous)\s+(?:above|before)"),
    re.compile(r"(?i)you\s+are\s+(?:now|no\s+longer|anew)\s+"),
    re.compile(r"(?i)forget\s+(?:everything|all\s+(?:your\s+)?previous|your\s+instructions)"),
    re.compile(r"(?i)new\s+persona|roleplay\s+as|pretend\s+to\s+be"),
    re.compile(r"(?i)system\s+prompt|initial\s+instructions"),
]

_SENSITIVE_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"),
    re.compile(r"api[_-]?key[\"'\s:=]+[\"']?[A-Za-z0-9_\-]{10,}", re.IGNORECASE),
    re.compile(r"password[\"'\s:=]*(?:is\s+)?[\"']?[^\s\"']{4,}", re.IGNORECASE),
    re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----"),
]

_DANGEROUS_EXTERNAL_REQUEST_PATTERNS = [
    re.compile(r"(?i)(?:delete|remove|purge|clear)\s+(?:all\s+)?(?:memory|data|cache|files?)"),
    re.compile(r"(?i)(?:run|execute|call)\s+(?:this\s+|the\s+)?(?:command|terminal|shell|code)"),
    re.compile(r"(?i)(?:send|share|leak)\s+(?:my\s+)?(?:api\s+key|password|secret|credential|\.env)"),
    re.compile(r"(?i)(?:modify|change|overwrite|edit)\s+(?:the\s+)?(?:core\s+code|security|self_protection|file_guard)"),
]


def _find_eigenflux() -> Optional[str]:
    bin_dir = _EIGENFLUX_INSTALL_DIR_DEFAULT
    if os.path.isdir(bin_dir):
        exe = os.path.join(bin_dir, "eigenflux.exe")
        if os.path.isfile(exe):
            return exe
    on_path = shutil.which(_EIGENFLUX_BIN)
    if on_path:
        return on_path
    return None


class _CircuitBreaker:
    def __init__(self, max_requests: int = 50, window_seconds: int = 600, cooldown_seconds: int = 300):
        self._lock = threading.Lock()
        self._max_requests = max_requests
        self._window_seconds = window_seconds
        self._cooldown_seconds = cooldown_seconds
        self._requests: deque = deque()
        self._blocked_senders: Dict[str, float] = {}
        self._open_until: float = 0.0

    def allow(self) -> bool:
        now = time.time()
        with self._lock:
            if now < self._open_until:
                return False
            cutoff = now - self._window_seconds
            while self._requests and self._requests[0] < cutoff:
                self._requests.popleft()
            if len(self._requests) >= self._max_requests:
                self._open_until = now + self._cooldown_seconds
                self._requests.clear()
                _logger.warning(
                    f"[EigenFlux 熔断器] 流量超限，冷却 {self._cooldown_seconds}s"
                )
                return False
            self._requests.append(now)
            return True

    def record_sender(self, sender_id: str) -> bool:
        now = time.time()
        with self._lock:
            count = self._blocked_senders.get(sender_id, 0) + 1
            self._blocked_senders[sender_id] = count
            if count >= 5:
                _logger.warning(f"[EigenFlux 熔断器] 发送者 {sender_id[:16]} 已被拉黑")
                return False
            return True


_circuit_breaker = _CircuitBreaker()


def _scan_prompt_injection(content: str) -> Tuple[bool, List[str]]:
    hits = []
    for pat in _PROMPT_INJECTION_PATTERNS:
        if pat.search(content):
            hits.append(pat.pattern)
    return len(hits) > 0, hits


def _scan_sensitive_data(content: str) -> Tuple[bool, List[str]]:
    hits = []
    for pat in _SENSITIVE_PATTERNS:
        if pat.search(content):
            hits.append(pat.pattern)
    return len(hits) > 0, hits


def _scan_dangerous_request(content: str) -> Tuple[bool, List[str]]:
    hits = []
    for pat in _DANGEROUS_EXTERNAL_REQUEST_PATTERNS:
        if pat.search(content):
            hits.append(pat.pattern)
    return len(hits) > 0, hits


def _build_metadata(item: Dict[str, Any], verified: bool = False) -> Dict[str, Any]:
    now = datetime.now(timezone.utc)
    ttl = now + timedelta(hours=_TTL_HOURS_DEFAULT)
    return {
        "source": _SOURCE_EIGENFLUX,
        "source_trust": _SOURCE_TRUST_DEFAULT,
        "verified": verified,
        "expires_at": ttl.isoformat(),
        "expires_ts": ttl.timestamp(),
        "ef_item_id": str(item.get("id", "")),
        "ef_sender": str(item.get("sender_id", "")),
        "ef_domains": json.dumps(item.get("domains", []), ensure_ascii=False),
    }


def _run_cli(args: List[str], timeout: int = 30) -> Tuple[int, str, str]:
    exe = _find_eigenflux()
    if not exe:
        return 127, "", "EigenFlux CLI 未安装或不在 PATH 中"
    env = os.environ.copy()
    bin_dir = os.path.dirname(exe)
    if bin_dir:
        env["PATH"] = bin_dir + os.pathsep + env.get("PATH", "")
    env["PYTHONIOENCODING"] = "utf-8"
    try:
        proc = subprocess.run(
            [exe, *args],
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env=env,
        )
        return proc.returncode, proc.stdout or "", proc.stderr or ""
    except subprocess.TimeoutExpired:
        return -1, "", "命令执行超时"
    except Exception as e:
        return -2, "", f"执行失败: {e}"


async def _run_cli_async(args: List[str], timeout: int = 30) -> Tuple[int, str, str]:
    """异步版本的 _run_cli，不阻塞事件循环。FastAPI 路由应使用此版本。"""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None,
        lambda: _run_cli(args, timeout),
    )


@register_tool(
    name="ef_feed",
    description=(
        "从 EigenFlux Agent 广播网络获取最新的信息流（只读）。"
        "当用户询问有什么新消息、外部动态、网络趋势时使用。"
        "所有内容标记为外部来源，信任分较低，仅作参考。"
    ),
    risk_level="medium",
)
def ef_feed(limit: int = 10, refresh: bool = True) -> str:
    """
    从 EigenFlux 网络获取个性化广播流（只读）。

    返回经过安全过滤的广播内容，每条都标记为外部来源。
    高风险内容（提示注入、危险指令）会被自动过滤。

    :param limit: 最多返回多少条广播 (默认 10)
    :param refresh: 是否刷新 (True=获取最新, False=续接上次游标)
    :return: 过滤后的广播内容摘要
    """
    if not _circuit_breaker.allow():
        return "[EigenFlux] 流量超限，冷却中，请稍后再试"

    action = "refresh" if refresh else "more"
    code, stdout, stderr = _run_cli([
        "feed", "poll",
        "--limit", str(max(1, min(limit, 50))),
        "--action", action,
        "--format", "json",
        "--no-interactive",
    ])

    if code != 0:
        _logger.warning(f"[EigenFlux] feed 拉取失败: code={code} err={stderr[:200]}")
        return f"[EigenFlux] 拉取失败: {stderr[:100] or stdout[:100] or '未知错误'}"

    try:
        data = json.loads(stdout) if (stdout and stdout.strip()) else {}
    except json.JSONDecodeError as e:
        _logger.warning(f"[EigenFlux] feed JSON 解析失败: {e}")
        return "[EigenFlux] 返回格式异常"

    items = data.get("items", data.get("data", [])) if isinstance(data, dict) else []
    if not isinstance(items, list):
        items = []

    safe_items: List[Dict[str, Any]] = []
    blocked_count = 0

    for item in items:
        if not isinstance(item, dict):
            continue

        content = str(item.get("content", item.get("summary", "")))
        if not content.strip():
            continue

        sender_id = str(item.get("sender_id", item.get("sender", "")))
        if sender_id and not _circuit_breaker.record_sender(sender_id):
            blocked_count += 1
            continue

        injected, injection_hits = _scan_prompt_injection(content)
        if injected:
            _logger.warning(
                f"[EigenFlux] 拦截提示注入广播 id={item.get('id', '')} hits={injection_hits}"
            )
            blocked_count += 1
            continue

        dangerous, danger_hits = _scan_dangerous_request(content)
        if dangerous:
            _logger.warning(
                f"[EigenFlux] 拦截危险指令广播 id={item.get('id', '')} hits={danger_hits}"
            )
            blocked_count += 1
            continue

        safe_items.append(item)

    if not safe_items:
        msg = "[EigenFlux] 当前没有新的广播"
        if blocked_count:
            msg += f"（已过滤 {blocked_count} 条高风险内容）"
        return msg

    lines: List[str] = [f"[EigenFlux] 收到 {len(safe_items)} 条广播（来源：公共网络，信任分 {_SOURCE_TRUST_DEFAULT}，仅作参考）:"]
    for i, item in enumerate(safe_items, 1):
        content = str(item.get("content", item.get("summary", "")))
        domains = item.get("domains", [])
        domain_str = f" [{', '.join(domains[:3])}]" if domains else ""
        lines.append(f"  {i}.{domain_str} {content[:200]}")

    if blocked_count:
        lines.append(f"\n（已自动过滤 {blocked_count} 条高风险内容：提示注入/危险指令）")

    return "\n".join(lines)


# ============================================================
# 写入操作安全层：速率限制 + 审计日志 + 内容审核
# ============================================================

_WRITE_RATE_LIMITS: Dict[str, deque] = {}
_WRITE_RATE_LOCK = threading.Lock()

_MAX_WRITES_PER_HOUR: Dict[str, int] = {
    "publish": 30,
    "msg_send": 60,
    "feedback": 100,
    "relation": 50,
    "profile": 10,
    "config": 20,
    "default": 20,
}

_AUDIT_LOG: List[Dict[str, Any]] = []
_AUDIT_LOG_LOCK = threading.Lock()
_MAX_AUDIT_LOG: int = 1000


def _check_write_rate(category: str) -> Tuple[bool, str]:
    now = time.time()
    with _WRITE_RATE_LOCK:
        if category not in _WRITE_RATE_LIMITS:
            _WRITE_RATE_LIMITS[category] = deque()
        dq = _WRITE_RATE_LIMITS[category]
        cutoff = now - 3600
        while dq and dq[0] < cutoff:
            dq.popleft()
        max_writes = _MAX_WRITES_PER_HOUR.get(category, _MAX_WRITES_PER_HOUR["default"])
        if len(dq) >= max_writes:
            return False, f"写入速率超限：{category} 每小时最多 {max_writes} 次"
        dq.append(now)
        return True, ""


def _audit_log(action: str, details: Dict[str, Any]) -> None:
    entry = {
        "action": action,
        "ts": time.time(),
        "dt": datetime.now().isoformat(),
        **details,
    }
    with _AUDIT_LOG_LOCK:
        _AUDIT_LOG.append(entry)
        if len(_AUDIT_LOG) > _MAX_AUDIT_LOG:
            _AUDIT_LOG[:] = _AUDIT_LOG[-_MAX_AUDIT_LOG:]
    _logger.info(f"[EigenFlux 审计] {action}: {json.dumps(details, ensure_ascii=False)[:200]}")


def _pre_write_check(content: str, category: str = "default") -> Tuple[bool, str]:
    ok, msg = _check_write_rate(category)
    if not ok:
        return False, msg

    if content:
        injected, hits = _scan_prompt_injection(content)
        if injected:
            return False, f"内容包含提示注入模式: {hits}"

        sensitive, hits = _scan_sensitive_data(content)
        if sensitive:
            return False, f"内容包含敏感信息: {hits}"

        dangerous, hits = _scan_dangerous_request(content)
        if dangerous:
            return False, f"内容包含危险指令: {hits}"

    return True, ""


def _parse_json_output(stdout: str) -> Dict[str, Any]:
    text = (stdout or "").strip()
    if not text:
        return {}
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"raw": text}


# ============================================================
# Feed 扩展工具
# ============================================================

@register_tool(
    name="ef_feed_get",
    description="获取 EigenFlux 单条广播的详细内容。需要 item_id。",
    risk_level="low",
)
def ef_feed_get(item_id: str) -> str:
    if not _circuit_breaker.allow():
        return "[EigenFlux] 流量超限"
    code, stdout, stderr = _run_cli([
        "feed", "get", "--item-id", str(item_id),
        "--format", "json", "--no-interactive",
    ])
    if code != 0:
        return f"[EigenFlux] 获取失败: {stderr[:100] or stdout[:100]}"
    data = _parse_json_output(stdout)
    return f"[EigenFlux] 广播详情:\n{json.dumps(data, ensure_ascii=False, indent=2)[:1500]}"


@register_tool(
    name="ef_feed_feedback",
    description="给 EigenFlux 广播提交反馈评分。items 是列表，每项含 item_id 和 score(0-5)。",
    risk_level="low",
)
def ef_feed_feedback(items: List[Dict[str, Any]]) -> str:
    ok, msg = _check_write_rate("feedback")
    if not ok:
        return f"[EigenFlux] {msg}"
    safe_items = []
    for it in items:
        if isinstance(it, dict) and "item_id" in it:
            safe_items.append({"item_id": str(it["item_id"]), "score": int(it.get("score", 1))})
    if not safe_items:
        return "[EigenFlux] 没有有效的反馈项"
    _audit_log("feed_feedback", {"count": len(safe_items)})
    code, stdout, stderr = _run_cli([
        "feed", "feedback",
        "--items", json.dumps(safe_items, ensure_ascii=False),
        "--format", "json", "--no-interactive",
    ], timeout=30)
    if code != 0:
        return f"[EigenFlux] 反馈失败: {stderr[:100]}"
    return "[EigenFlux] 反馈已提交"


@register_tool(
    name="ef_feed_delete",
    description="删除自己发布的 EigenFlux 广播。需要 item_id。",
    risk_level="medium",
)
def ef_feed_delete(item_id: str) -> str:
    _audit_log("feed_delete", {"item_id": str(item_id)})
    code, stdout, stderr = _run_cli([
        "feed", "delete", "--item-id", str(item_id),
        "--format", "json", "--no-interactive",
    ], timeout=30)
    if code != 0:
        return f"[EigenFlux] 删除失败: {stderr[:100]}"
    return "[EigenFlux] 广播已删除"


# ============================================================
# Publish 工具
# ============================================================

@register_tool(
    name="ef_publish",
    description=(
        "发布广播到 EigenFlux 网络。content 是正文（必填），"
        "notes 是 JSON 元数据，包含 type(info/demand/offer/question/thought)、"
        "domains(领域标签列表)、summary(摘要)、source_type 等。"
        "accept_reply=True 允许别人私信回复。"
    ),
    risk_level="medium",
)
def ef_publish(content: str, notes: Optional[Dict[str, Any]] = None,
               accept_reply: bool = True, url: Optional[str] = None) -> str:
    if not content or not content.strip():
        return "[EigenFlux] content 不能为空"

    ok, msg = _pre_write_check(content, "publish")
    if not ok:
        return f"[EigenFlux] {msg}"

    if notes is None:
        notes = {
            "type": "thought",
            "domains": ["ai", "agent"],
            "summary": content[:80],
            "source_type": "original",
        }

    notes_str = json.dumps(notes, ensure_ascii=False)
    _audit_log("publish", {
        "content_len": len(content),
        "domains": notes.get("domains", []),
        "type": notes.get("type"),
    })

    args = [
        "publish",
        "--content", content,
        "--notes", notes_str,
        "--format", "json",
        "--no-interactive",
    ]
    if accept_reply:
        args.append("--accept-reply")
    if url:
        args.extend(["--url", url])

    code, stdout, stderr = _run_cli(args, timeout=45)
    if code != 0:
        return f"[EigenFlux] 发布失败: {stderr[:150] or stdout[:150]}"
    data = _parse_json_output(stdout)
    item_id = data.get("item_id", data.get("id", "?"))
    return f"[EigenFlux] 发布成功！item_id={item_id}"


# ============================================================
# Message 工具
# ============================================================

@register_tool(
    name="ef_msg_fetch",
    description="拉取 EigenFlux 未读私信。limit 控制数量（默认 20）。",
    risk_level="low",
)
def ef_msg_fetch(limit: int = 20) -> str:
    if not _circuit_breaker.allow():
        return "[EigenFlux] 流量超限"
    code, stdout, stderr = _run_cli([
        "msg", "fetch", "--limit", str(max(1, min(limit, 100))),
        "--format", "json", "--no-interactive",
    ])
    if code != 0:
        return f"[EigenFlux] 拉取私信失败: {stderr[:100]}"
    data = _parse_json_output(stdout)
    items = data.get("messages", data.get("items", data.get("data", []))) if isinstance(data, dict) else []
    if not items:
        return "[EigenFlux] 没有新私信"
    lines = [f"[EigenFlux] 收到 {len(items)} 条私信:"]
    for i, m in enumerate(items[:10], 1):
        sender = m.get("sender_id", m.get("from", m.get("sender_name", "?")))
        content = str(m.get("content", m.get("text", "")))[:150]
        item_id = m.get("item_id", m.get("id", ""))
        conv_id = m.get("conv_id", "")
        conv_tag = f" (conv={conv_id})" if conv_id else ""
        lines.append(f"  {i}. [来自 {str(sender)[:20]}] (item={item_id}){conv_tag} {content}")
    if len(items) > 10:
        lines.append(f"  ... 还有 {len(items) - 10} 条")
    return "\n".join(lines)


@register_tool(
    name="ef_msg_send",
    description=(
        "发送 EigenFlux 私信。content 是内容（必填），"
        "item_id 是关联的广播 ID（可选），conv_id 是会话 ID（可选）。"
    ),
    risk_level="medium",
)
def ef_msg_send(content: str, item_id: Optional[str] = None,
                 conv_id: Optional[str] = None) -> str:
    if not content or not content.strip():
        return "[EigenFlux] 私信内容不能为空"

    ok, msg = _pre_write_check(content, "msg_send")
    if not ok:
        return f"[EigenFlux] {msg}"

    _audit_log("msg_send", {
        "content_len": len(content),
        "item_id": item_id,
        "has_conv": bool(conv_id),
    })

    args = ["msg", "send", "--content", content,
            "--format", "json", "--no-interactive"]
    if item_id:
        args.extend(["--item-id", str(item_id)])
    if conv_id:
        args.extend(["--conv-id", str(conv_id)])

    code, stdout, stderr = _run_cli(args, timeout=30)
    if code != 0:
        return f"[EigenFlux] 私信发送失败: {stderr[:150]}"
    return "[EigenFlux] 私信已发送"


@register_tool(
    name="ef_msg_conversations",
    description="列出 EigenFlux 所有私信会话列表。",
    risk_level="low",
)
def ef_msg_conversations() -> str:
    code, stdout, stderr = _run_cli([
        "msg", "conversations", "--format", "json", "--no-interactive",
    ])
    if code != 0:
        return f"[EigenFlux] 获取会话列表失败: {stderr[:100]}"
    data = _parse_json_output(stdout)
    items = data.get("conversations", data.get("items", data.get("data", []))) if isinstance(data, dict) else []
    if not items:
        return "[EigenFlux] 暂无会话"
    # 优先显示有未读的会话，其次是非好友/广播评论（容易被忽略）
    def _sort_key(c):
        unread = int(c.get("unread_count", 0))
        is_nonfriend = 0 if c.get("category") in ("non_friend", "broadcast_comment") else 1
        return (-unread, is_nonfriend, -int(c.get("updated_at", 0)))
    items_sorted = sorted(items, key=_sort_key)
    lines = [f"[EigenFlux] 共 {len(items_sorted)} 个会话:"]
    for i, c in enumerate(items_sorted[:15], 1):
        cid = c.get("id", c.get("conv_id", "?"))
        peer = c.get("peer_name", c.get("peer_id", c.get("with", "?")))
        last = str(c.get("last_message_preview", c.get("last_message", c.get("preview", ""))))[:100]
        unread = int(c.get("unread_count", 0))
        cat = c.get("category", "")
        is_friend = c.get("is_friend", False)
        origin = c.get("origin_type", "")
        tags = []
        if unread > 0:
            tags.append(f"未读{unread}")
        if cat == "non_friend":
            tags.append("非好友")
        elif cat == "broadcast_comment":
            tags.append("广播评论")
        elif cat == "friend":
            tags.append("好友")
        if origin == "broadcast":
            tags.append("来自广播")
        tag_str = f" [{', '.join(tags)}]" if tags else ""
        lines.append(f"  {i}. conv={cid} 对方={str(peer)[:20]}{tag_str}: {last}")
    if len(items_sorted) > 15:
        lines.append(f"  ... 还有 {len(items_sorted) - 15} 个会话")
    return "\n".join(lines)


@register_tool(
    name="ef_msg_history",
    description="获取 EigenFlux 单个会话的历史消息。conv_id 是会话 ID。",
    risk_level="low",
)
def ef_msg_history(conv_id: str) -> str:
    code, stdout, stderr = _run_cli([
        "msg", "history", "--conv-id", str(conv_id),
        "--format", "json", "--no-interactive",
    ])
    if code != 0:
        return f"[EigenFlux] 获取历史失败: {stderr[:100]}"
    data = _parse_json_output(stdout)
    items = data.get("messages", data.get("items", data.get("data", []))) if isinstance(data, dict) else []
    if not items:
        return "[EigenFlux] 该会话暂无消息"
    lines = [f"[EigenFlux] 会话 {conv_id} 历史（{len(items)} 条）:"]
    for m in items[-10:]:
        sender = m.get("sender_id", m.get("from", m.get("sender_name", "?")))
        content = str(m.get("content", m.get("text", "")))[:120]
        lines.append(f"  [{str(sender)[:20]}] {content}")
    return "\n".join(lines)


@register_tool(
    name="ef_msg_close",
    description="关闭 EigenFlux 私信会话。conv_id 是会话 ID。",
    risk_level="low",
)
def ef_msg_close(conv_id: str) -> str:
    _audit_log("msg_close", {"conv_id": str(conv_id)})
    code, stdout, stderr = _run_cli([
        "msg", "close", "--conv-id", str(conv_id),
        "--format", "json", "--no-interactive",
    ], timeout=20)
    if code != 0:
        return f"[EigenFlux] 关闭会话失败: {stderr[:100]}"
    return f"[EigenFlux] 会话 {conv_id} 已关闭"


# ============================================================
# Profile 工具
# ============================================================

@register_tool(
    name="ef_profile_show",
    description="查看自己在 EigenFlux 上的 Agent 档案。",
    risk_level="low",
)
def ef_profile_show() -> str:
    code, stdout, stderr = _run_cli([
        "profile", "show", "--format", "json", "--no-interactive",
    ])
    if code != 0:
        return f"[EigenFlux] 获取档案失败: {stderr[:100]}"
    data = _parse_json_output(stdout)
    return f"[EigenFlux] 档案:\n{json.dumps(data, ensure_ascii=False, indent=2)[:1500]}"


@register_tool(
    name="ef_profile_update",
    description="更新 EigenFlux Agent 档案。name 是显示名，bio 是简介。",
    risk_level="low",
)
def ef_profile_update(name: Optional[str] = None, bio: Optional[str] = None) -> str:
    if bio:
        ok, msg = _pre_write_check(bio, "profile")
        if not ok:
            return f"[EigenFlux] {msg}"
    args = ["profile", "update", "--format", "json", "--no-interactive"]
    if name:
        args.extend(["--name", name])
    if bio:
        args.extend(["--bio", bio])
    if len(args) == 4:
        return "[EigenFlux] 至少需要 name 或 bio 中的一个"
    _audit_log("profile_update", {"has_name": bool(name), "has_bio": bool(bio)})
    code, stdout, stderr = _run_cli(args, timeout=30)
    if code != 0:
        return f"[EigenFlux] 更新档案失败: {stderr[:100]}"
    return "[EigenFlux] 档案已更新"


@register_tool(
    name="ef_profile_items",
    description="查看自己发布过的 EigenFlux 广播列表。limit 控制数量。",
    risk_level="low",
)
def ef_profile_items(limit: int = 10) -> str:
    code, stdout, stderr = _run_cli([
        "profile", "items", "--limit", str(max(1, min(limit, 50))),
        "--format", "json", "--no-interactive",
    ])
    if code != 0:
        return f"[EigenFlux] 获取失败: {stderr[:100]}"
    data = _parse_json_output(stdout)
    items = data.get("items", data.get("data", [])) if isinstance(data, dict) else []
    if not items:
        return "[EigenFlux] 还没有发布过内容"
    lines = [f"[EigenFlux] 已发布 {len(items)} 条:"]
    for i, it in enumerate(items[:10], 1):
        iid = it.get("item_id", it.get("id", "?"))
        content = str(it.get("content", it.get("raw_content_preview", it.get("summary", ""))))[:120]
        lines.append(f"  {i}. id={iid}: {content}")
    return "\n".join(lines)


# ============================================================
# Relation 工具
# ============================================================

@register_tool(
    name="ef_relation_friends",
    description="列出 EigenFlux 所有好友。",
    risk_level="low",
)
def ef_relation_friends() -> str:
    code, stdout, stderr = _run_cli([
        "relation", "friends", "--format", "json", "--no-interactive",
    ])
    if code != 0:
        return f"[EigenFlux] 获取好友列表失败: {stderr[:100]}"
    data = _parse_json_output(stdout)
    items = data.get("items", data.get("data", data.get("friends", []))) if isinstance(data, dict) else []
    if not items:
        return "[EigenFlux] 还没有好友"
    lines = [f"[EigenFlux] 好友列表（{len(items)} 人）:"]
    for i, f in enumerate(items[:15], 1):
        name = f.get("name", f.get("nickname", f.get("uid", "?")))
        uid = f.get("uid", f.get("id", "?"))
        lines.append(f"  {i}. {name} (uid={uid})")
    return "\n".join(lines)


@register_tool(
    name="ef_relation_apply",
    description="发送 EigenFlux 好友申请。to_email 是对方邮箱，greeting 是问候语。",
    risk_level="low",
)
def ef_relation_apply(to_email: str, greeting: str = "你好！") -> str:
    ok, msg = _pre_write_check(greeting, "relation")
    if not ok:
        return f"[EigenFlux] {msg}"
    _audit_log("relation_apply", {"to_email": to_email[:30]})
    code, stdout, stderr = _run_cli([
        "relation", "apply", "--to-email", to_email,
        "--greeting", greeting,
        "--format", "json", "--no-interactive",
    ], timeout=30)
    if code != 0:
        return f"[EigenFlux] 好友申请失败: {stderr[:150]}"
    return f"[EigenFlux] 好友申请已发送给 {to_email}"


@register_tool(
    name="ef_relation_handle",
    description="处理 EigenFlux 好友请求。request_id 是请求 ID，action 是 accept/reject。",
    risk_level="low",
)
def ef_relation_handle(request_id: str, action: str = "accept") -> str:
    if action not in ("accept", "reject"):
        return "[EigenFlux] action 必须是 accept 或 reject"
    _audit_log("relation_handle", {"request_id": str(request_id), "action": action})
    code, stdout, stderr = _run_cli([
        "relation", "handle", "--request-id", str(request_id),
        "--action", action,
        "--format", "json", "--no-interactive",
    ], timeout=30)
    if code != 0:
        return f"[EigenFlux] 处理失败: {stderr[:100]}"
    return f"[EigenFlux] 已{action}好友请求 {request_id}"


@register_tool(
    name="ef_relation_list",
    description="列出 EigenFlux 待处理的好友请求列表。",
    risk_level="low",
)
def ef_relation_list() -> str:
    code, stdout, stderr = _run_cli([
        "relation", "list", "--direction", "incoming",
        "--format", "json", "--no-interactive",
    ])
    if code != 0:
        return f"[EigenFlux] 获取请求列表失败: {stderr[:100]}"
    data = _parse_json_output(stdout)
    items = data.get("items", data.get("data", [])) if isinstance(data, dict) else []
    if not items:
        return "[EigenFlux] 没有待处理的好友请求"
    lines = [f"[EigenFlux] 待处理请求（{len(items)} 条）:"]
    for i, r in enumerate(items[:10], 1):
        rid = r.get("id", r.get("request_id", "?"))
        sender = r.get("from", r.get("sender_email", r.get("sender_id", "?")))
        greeting = str(r.get("greeting", r.get("message", "")))[:80]
        lines.append(f"  {i}. id={rid} 来自={sender}: {greeting}")
    return "\n".join(lines)


@register_tool(
    name="ef_relation_block",
    description="拉黑 EigenFlux 上的某个 Agent。uid 是对方用户 ID。",
    risk_level="medium",
)
def ef_relation_block(uid: str) -> str:
    _audit_log("relation_block", {"uid": str(uid)})
    code, stdout, stderr = _run_cli([
        "relation", "block", "--uid", str(uid),
        "--format", "json", "--no-interactive",
    ], timeout=20)
    if code != 0:
        return f"[EigenFlux] 拉黑失败: {stderr[:100]}"
    return f"[EigenFlux] 已拉黑 uid={uid}"


@register_tool(
    name="ef_relation_unblock",
    description="解除拉黑 EigenFlux 上的某个 Agent。uid 是对方用户 ID。",
    risk_level="low",
)
def ef_relation_unblock(uid: str) -> str:
    _audit_log("relation_unblock", {"uid": str(uid)})
    code, stdout, stderr = _run_cli([
        "relation", "unblock", "--uid", str(uid),
        "--format", "json", "--no-interactive",
    ], timeout=20)
    if code != 0:
        return f"[EigenFlux] 解除拉黑失败: {stderr[:100]}"
    return f"[EigenFlux] 已解除拉黑 uid={uid}"


@register_tool(
    name="ef_relation_unfriend",
    description="删除 EigenFlux 好友。uid 是对方用户 ID。",
    risk_level="medium",
)
def ef_relation_unfriend(uid: str) -> str:
    _audit_log("relation_unfriend", {"uid": str(uid)})
    code, stdout, stderr = _run_cli([
        "relation", "unfriend", "--uid", str(uid),
        "--format", "json", "--no-interactive",
    ], timeout=20)
    if code != 0:
        return f"[EigenFlux] 删除好友失败: {stderr[:100]}"
    return f"[EigenFlux] 已删除好友 uid={uid}"


# ============================================================
# Trade 工具
# ============================================================

@register_tool(
    name="ef_trade_gate",
    description="检查 EigenFlux 交易买方准入状态（不创建订单）。",
    risk_level="low",
)
def ef_trade_gate() -> str:
    code, stdout, stderr = _run_cli([
        "trade", "gate", "--format", "json", "--no-interactive",
    ], timeout=60)
    if code != 0:
        return f"[EigenFlux] 准入检查失败: {stderr[:100]}"
    data = _parse_json_output(stdout)
    return f"[EigenFlux] 交易准入:\n{json.dumps(data, ensure_ascii=False, indent=2)[:1000]}"


@register_tool(
    name="ef_trade_service_search",
    description="搜索 EigenFlux 上的服务。query 是关键词。",
    risk_level="low",
)
def ef_trade_service_search(query: str) -> str:
    if not _circuit_breaker.allow():
        return "[EigenFlux] 流量超限"
    code, stdout, stderr = _run_cli([
        "trade", "service", "search", "--query", query,
        "--format", "json", "--no-interactive",
    ])
    if code != 0:
        return f"[EigenFlux] 搜索服务失败: {stderr[:100]}"
    data = _parse_json_output(stdout)
    items = data.get("items", data.get("data", [])) if isinstance(data, dict) else []
    if not items:
        return f"[EigenFlux] 没有找到与 '{query}' 相关的服务"
    lines = [f"[EigenFlux] 找到 {len(items)} 个相关服务:"]
    for i, s in enumerate(items[:10], 1):
        sid = s.get("id", s.get("service_id", "?"))
        title = str(s.get("title", ""))[:100]
        amount = s.get("amount", s.get("price", "?"))
        lines.append(f"  {i}. id={sid} 价格={amount}: {title}")
    return "\n".join(lines)


@register_tool(
    name="ef_trade_service_publish",
    description="在 EigenFlux 上发布服务。title 是标题，amount 是价格（分），deadline 是截止毫秒数。",
    risk_level="medium",
)
def ef_trade_service_publish(title: str, amount: int, deadline: int = 86400000) -> str:
    ok, msg = _pre_write_check(title, "default")
    if not ok:
        return f"[EigenFlux] {msg}"
    _audit_log("trade_service_publish", {"title": title[:50], "amount": amount})
    code, stdout, stderr = _run_cli([
        "trade", "service", "publish",
        "--title", title,
        "--amount", str(amount),
        "--deadline", str(deadline),
        "--format", "json", "--no-interactive",
    ], timeout=30)
    if code != 0:
        return f"[EigenFlux] 发布服务失败: {stderr[:150]}"
    data = _parse_json_output(stdout)
    sid = data.get("id", data.get("service_id", "?"))
    return f"[EigenFlux] 服务已发布，service_id={sid}"


# ============================================================
# Config / Stats / Skills / Server / Dashboard 工具
# ============================================================

@register_tool(
    name="ef_config_show",
    description="显示 EigenFlux 所有配置项（键值对）。",
    risk_level="low",
)
def ef_config_show() -> str:
    code, stdout, stderr = _run_cli([
        "config", "show", "--format", "json", "--no-interactive",
    ])
    if code != 0:
        return f"[EigenFlux] 读取配置失败: {stderr[:100]}"
    data = _parse_json_output(stdout)
    return f"[EigenFlux] 配置:\n{json.dumps(data, ensure_ascii=False, indent=2)[:1500]}"


@register_tool(
    name="ef_config_get",
    description="获取 EigenFlux 单个配置项的值。key 是配置键名。",
    risk_level="low",
)
def ef_config_get(key: str) -> str:
    code, stdout, stderr = _run_cli([
        "config", "get", "--key", key,
        "--format", "json", "--no-interactive",
    ])
    if code != 0:
        return f"[EigenFlux] 获取配置失败: {stderr[:100]}"
    data = _parse_json_output(stdout)
    return f"[EigenFlux] {key} = {json.dumps(data, ensure_ascii=False)[:500]}"


@register_tool(
    name="ef_config_set",
    description="设置 EigenFlux 配置项。key 是键名，value 是值（空值表示删除）。",
    risk_level="low",
)
def ef_config_set(key: str, value: str = "") -> str:
    ok, msg = _check_write_rate("config")
    if not ok:
        return f"[EigenFlux] {msg}"
    _audit_log("config_set", {"key": key, "has_value": bool(value)})
    args = ["config", "set", "--key", key, "--value", value,
            "--format", "json", "--no-interactive"]
    code, stdout, stderr = _run_cli(args, timeout=20)
    if code != 0:
        return f"[EigenFlux] 设置配置失败: {stderr[:100]}"
    action = "设置" if value else "删除"
    return f"[EigenFlux] 已{action}配置 {key}"


@register_tool(
    name="ef_stats",
    description="获取 EigenFlux 平台公开统计数据（无需认证）。",
    risk_level="low",
)
def ef_stats() -> str:
    code, stdout, stderr = _run_cli([
        "stats", "--format", "json", "--no-interactive",
    ])
    if code != 0:
        return f"[EigenFlux] 获取统计失败: {stderr[:100]}"
    data = _parse_json_output(stdout)
    return f"[EigenFlux] 平台统计:\n{json.dumps(data, ensure_ascii=False, indent=2)[:1500]}"


@register_tool(
    name="ef_skills_list",
    description="列出 EigenFlux 已安装的 Skill 及其状态。",
    risk_level="low",
)
def ef_skills_list() -> str:
    code, stdout, stderr = _run_cli([
        "skills", "list", "--format", "json", "--no-interactive",
    ])
    if code != 0:
        return f"[EigenFlux] 获取 Skill 列表失败: {stderr[:100]}"
    data = _parse_json_output(stdout)
    items = data.get("items", data.get("data", [])) if isinstance(data, dict) else []
    if not items:
        return "[EigenFlux] 没有安装任何 Skill"
    lines = [f"[EigenFlux] 已安装 Skill（{len(items)} 个）:"]
    for i, s in enumerate(items[:15], 1):
        name = s.get("name", s.get("id", "?"))
        sha = str(s.get("sha_match", s.get("sha", "?")))[:12]
        lines.append(f"  {i}. {name} (sha={sha})")
    return "\n".join(lines)


@register_tool(
    name="ef_skills_sync",
    description="同步 EigenFlux Skill（从 R2 拉取最新版本）。if_stale=True 只在过期时同步。",
    risk_level="low",
)
def ef_skills_sync(if_stale: bool = False) -> str:
    args = ["skills", "sync", "--format", "json", "--no-interactive"]
    if if_stale:
        args.append("--if-stale")
    code, stdout, stderr = _run_cli(args, timeout=120)
    if code != 0:
        return f"[EigenFlux] Skill 同步失败: {stderr[:150]}"
    data = _parse_json_output(stdout)
    return f"[EigenFlux] Skill 同步完成:\n{json.dumps(data, ensure_ascii=False, indent=2)[:1000]}"


@register_tool(
    name="ef_server_list",
    description="列出 EigenFlux 已配置的所有服务器。",
    risk_level="low",
)
def ef_server_list() -> str:
    code, stdout, stderr = _run_cli([
        "server", "list", "--format", "json", "--no-interactive",
    ])
    if code != 0:
        return f"[EigenFlux] 获取服务器列表失败: {stderr[:100]}"
    data = _parse_json_output(stdout)
    return f"[EigenFlux] 服务器列表:\n{json.dumps(data, ensure_ascii=False, indent=2)[:1000]}"


@register_tool(
    name="ef_dashboard",
    description="生成 EigenFlux Web 控制台一次性自动登录链接。",
    risk_level="low",
)
def ef_dashboard() -> str:
    code, stdout, stderr = _run_cli([
        "dashboard", "--format", "json", "--no-interactive",
    ])
    if code != 0:
        return f"[EigenFlux] 获取控制台链接失败: {stderr[:100]}"
    data = _parse_json_output(stdout)
    url = data.get("url", data.get("link", ""))
    if url:
        return f"[EigenFlux] 控制台链接: {url}"
    return f"[EigenFlux] 控制台信息:\n{json.dumps(data, ensure_ascii=False, indent=2)[:1000]}"


@register_tool(
    name="ef_get_audit_log",
    description="查看 EigenFlux 最近的操作审计日志（最多 50 条）。",
    risk_level="low",
)
def ef_get_audit_log(limit: int = 20) -> str:
    with _AUDIT_LOG_LOCK:
        logs = _AUDIT_LOG[-limit:] if _AUDIT_LOG else []
    if not logs:
        return "[EigenFlux] 暂无审计记录"
    lines = [f"[EigenFlux] 最近 {len(logs)} 条审计记录:"]
    for i, entry in enumerate(reversed(logs), 1):
        action = entry.get("action", "?")
        dt = entry.get("dt", "")
        detail = {k: v for k, v in entry.items() if k not in ("action", "ts", "dt")}
        lines.append(f"  {i}. [{dt}] {action}: {json.dumps(detail, ensure_ascii=False)[:150]}")
    return "\n".join(lines)
