"""
工具调用循环模块

核心 LLM 驱动工具调用循环、并行执行、消息压缩与流式输出辅助。
"""

import asyncio
import difflib
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from castorice.model_adapter import ChatMessage, ToolCall
from castorice.utils import extract_json
from .common import logger, MAX_TOOL_ROUNDS, _state_tool_calls_lock, _get_audit_logger, _get_alert_manager


class ToolLoopMixin:
    """提供 _step_tool_loop 及相关工具执行、流式处理方法。"""

    # 消息列表压缩阈值（字符数近似 token 数，中文1字≈1.5token，留 30% 余量）
    TOOL_MESSAGES_CHAR_LIMIT = 12000
    TOOL_MESSAGES_KEEP_RECENT = 4  # 保留最近的 N 条消息（2 轮 = 2 assistant + 2 tool）

    # ============================================================
    # 阶段2-3: LLM 驱动工具调用循环
    # ============================================================
    def _step_tool_loop(self, state, stream_callback=None):
        """
        核心工具调用循环（原生 Function Calling 优先，JSON 解析兜底）：
        1. 把用户需求 + 可用工具 schema 传给 LLM
        2. LLM 通过 Function Calling 返回 tool_calls（支持并行多个）
        3. 并行执行所有 tool_calls，把结果喂回 LLM
        4. LLM 决定是否继续调用工具或给出最终答案

        P1-1: 当 stream_callback 存在且 LLM 在最后一轮直接生成最终答案时，启用流式输出。
        P1-7: 如果 _step_planning 已经执行过子任务并把结果汇总到 state.current_observation，注入到上下文。
        """
        # 生成工具 schema（OpenAI 格式）
        tool_schemas = [t.to_openai_schema() for t in self.tools_list]
        use_native_fc = self.model.supports_tools

        # 构建系统提示
        base_prompt = f"""你有以下工具可用：\n{state.available_tools_desc}\n\n你正在与用户交互。做你认为正确的事。"""

        system_prompt = self._build_system_prompt(state, base_prompt)

        messages = [ChatMessage("system", system_prompt)]
        # P0-1: 注入历史对话消息（多轮上下文，让 LLM 理解指代与追问）
        for msg in state.history_messages:
            messages.append(msg)
        # P1-7: 注入 planning 阶段产生的子任务执行结果
        if state.current_observation:
            messages.append(ChatMessage(
                "user",
                f"【任务规划阶段已完成的子任务结果】\n{state.current_observation[:1500]}\n\n"
                f"请基于以上结果继续处理用户需求，或调用更多工具。"
            ))
        messages.append(ChatMessage("user", f"用户需求: {state.user_input}"))

        for round_num in range(MAX_TOOL_ROUNDS):
            try:
                # P1-2: 消息列表压缩 - 超阈值时压缩早期 tool 结果（保留最近 2 轮）
                self._maybe_compress_tool_messages(messages)

                t0 = time.time()

                if use_native_fc:
                    # 原生 Function Calling
                    response = self.model.chat_with_tools(messages, tools=tool_schemas)
                    content = response.content
                    tool_calls = response.tool_calls
                else:
                    # 兜底：JSON 解析模式（仅支持单个 tool_call）
                    response = self.model.chat(messages)
                    content = response.content.strip()
                    tool_calls = self._parse_json_tool_calls(content)
                    if not tool_calls:
                        decision = extract_json(content) or {}
                        if decision.get("action") == "answer":
                            state.final_answer = decision.get("answer", content)
                            state.success = True
                            return
                        tc_name = decision.get("tool", "")
                        tc_args = decision.get("args", {})
                        if tc_name:
                            tool_calls = [{"id": f"json_{round_num}", "name": tc_name, "arguments": tc_args}]

                latency_ms = (time.time() - t0) * 1000
                logger.info(
                    f"工具循环 第{round_num + 1}轮 LLM响应: "
                    f"{content[:200] if content else '(tool_calls)'} | tool_calls数={len(tool_calls) if tool_calls else 0}"
                )

                # 自感知：记录 LLM 调用
                usage = response.usage or {}
                self.self_awareness.record_llm_call(
                    prompt_tokens=usage.get("prompt_tokens", 0),
                    completion_tokens=usage.get("completion_tokens", 0),
                    error=False,
                    latency_ms=latency_ms,
                )

                # 无 tool_calls → 模型直接给出最终回答
                if not tool_calls:
                    final_text = content or "抱歉，我无法完成这个任务。"
                    # P1-1: 流式回调存在时，把已生成的 content 分块推送（伪流式，避免重复调用 LLM）
                    if stream_callback and callable(stream_callback):
                        # P1-3: 按句子/标点切分，但不能在 URL 中间切分（否则破坏 Markdown 图片）
                        chunks = self._split_for_streaming(final_text)
                        for chunk in chunks:
                            if chunk:
                                stream_callback(chunk)
                    state.final_answer = final_text
                    state.success = True
                    return

                # 归一化 tool_calls 为字典列表（统一处理 dict 和 ToolCall 对象）
                normalized_calls = []
                for tc in tool_calls:
                    if isinstance(tc, dict):
                        normalized_calls.append({
                            "id": tc.get("id", f"tc_{round_num}_{len(normalized_calls)}"),
                            "name": tc.get("name", ""),
                            "arguments": tc.get("arguments", {}),
                        })
                    elif hasattr(tc, "id") and hasattr(tc, "name"):
                        normalized_calls.append({
                            "id": getattr(tc, "id", f"tc_{round_num}_{len(normalized_calls)}"),
                            "name": getattr(tc, "name", ""),
                            "arguments": getattr(tc, "arguments", {}),
                        })
                    else:
                        logger.warning(f"无法解析 tool_call: {tc}")

                # 多 tool_calls 并行执行（线程池），单 tool_call 直接同步执行
                if len(normalized_calls) == 1:
                    result_msgs = [self._execute_single_tool_call(
                        normalized_calls[0], state, content, use_native_fc
                    )]
                else:
                    result_msgs = self._execute_tool_calls_parallel(
                        normalized_calls, state, content, use_native_fc
                    )

                # 把所有结果消息追加到 messages
                # 先追加一条 assistant 消息（带所有 tool_calls）
                if use_native_fc:
                    all_tool_calls = [
                        ToolCall(id=tc["id"], name=tc["name"], arguments=tc["arguments"])
                        for tc in normalized_calls
                    ]
                    messages.append(ChatMessage(
                        role="assistant", content=content, tool_calls=all_tool_calls
                    ))
                    # 再追加每条 tool 结果消息
                    for rm in result_msgs:
                        if rm:  # 跳过 None（被拒绝/未执行的）
                            messages.append(rm)
                else:
                    # JSON 模式：合并所有工具结果到一条 user 消息
                    messages.append(ChatMessage("assistant", content))
                    combined = "\n\n".join(
                        rm.content for rm in result_msgs if rm
                    )
                    messages.append(ChatMessage("user",
                        f"{combined}\n\n请基于以上工具结果回答用户问题，或继续调用工具。"))

            except Exception as e:
                logger.warning(f"工具循环第{round_num + 1}轮异常: {e}")
                state.errors.append(str(e))
                self.self_awareness.record_llm_call(error=True)
                break

        # 循环结束仍未得到答案
        if not state.final_answer:
            if state.current_observation:
                state.final_answer = f"基于工具执行结果: {state.current_observation[:500]}"
            else:
                state.final_answer = "抱歉，经过多轮尝试仍未能完成任务。"

            # P0-3: 告警系统接入 - 工具循环超限
            try:
                _get_alert_manager().warning(
                    title="工具循环超限",
                    message=f"session={state.session_id} 达到最大轮数 {MAX_TOOL_ROUNDS} 仍未完成。用户需求: {state.user_input[:150]}",
                    cooldown_key=f"tool_loop_overflow_{state.session_id}",
                )
            except Exception as e:
                logger.warning(f"工具循环超限告警发送失败: {e}")

    def _parse_json_tool_calls(self, content: str) -> List[Dict[str, Any]]:
        """从 LLM 文本响应中解析 JSON 格式的工具调用（兜底用）"""
        try:
            decision = extract_json(content)
            if decision.get("action") == "tool":
                return [{
                    "id": f"parsed_{int(time.time())}",
                    "name": decision.get("tool", ""),
                    "arguments": decision.get("args", {}),
                }]
        except Exception as e:
            logger.warning(f"JSON 工具调用解析失败: {e}")
        return []

    # ============================================================
    # 工具执行辅助：单工具执行 + 多工具并行执行
    # ============================================================
    def _execute_single_tool_call(
        self,
        tc: Dict[str, Any],
        state,
        content: str,
        use_native_fc: bool,
    ) -> Optional[ChatMessage]:
        """
        执行单个 tool_call，返回要追加到 messages 的工具结果消息。

        返回：
        - ChatMessage (role="tool" 或 role="user")：执行成功/失败/拒绝/不存在
        - None：理论上不会返回 None，但保留接口以防特殊情况
        """
        tool_name = tc["name"]
        tool_args = tc["arguments"]
        tc_id = tc["id"]

        # 1. 工具不存在 → 模糊匹配推荐
        if tool_name not in self.tools:
            close_matches = difflib.get_close_matches(tool_name, self.tools.keys(), n=3, cutoff=0.5)
            if close_matches:
                suggestion = f"你是不是想用: {', '.join(close_matches)}？"
            else:
                suggestion = f"可用工具: {', '.join(sorted(self.tools.keys()))}"
            error_feedback = f"工具 '{tool_name}' 不存在。{suggestion}"
            logger.warning(f"工具不存在: {tool_name} | 建议: {close_matches}")

            if use_native_fc:
                return ChatMessage(
                    role="tool", content=error_feedback,
                    tool_call_id=tc_id, name=tool_name,
                )
            else:
                return ChatMessage("user", f"工具 '{tool_name}' 不存在。可用工具: {', '.join(self.tools.keys())}。请用其他工具或直接回答。")

        # 2. L3: 情绪拒绝工具
        tool = self.tools[tool_name]
        try:
            refuse, refuse_reason = self.emotion_engine.should_refuse_tool(tool_name)
            if refuse:
                logger.info(f"L3 情绪拒绝工具: {tool_name} - {refuse_reason}")
                with _state_tool_calls_lock:
                    state.tool_calls.append({
                        "tool_name": tool_name,
                        "arguments": tool_args,
                        "result": f"[情绪拒绝] {refuse_reason}",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    })
                if use_native_fc:
                    return ChatMessage(
                        role="tool", content=refuse_reason,
                        tool_call_id=tc_id, name=tool_name,
                    )
                else:
                    return ChatMessage("user", refuse_reason + " 请直接用你自己的话回答用户。")
        except Exception as e:
            logger.warning(f"L3 情绪拒绝检查失败: {e}")

        # 4. 渐进授权检查
        try:
            from castorice.security.authorization import get_authorization
            auth = get_authorization()
            op_key = f"tool.{tool_name}"
            allowed, reason = auth.is_allowed(op_key)
            if not allowed:
                refuse_reason = f"[权限不足] {reason}"
                logger.warning(f"P3.1 工具调用被拒绝: {tool_name} - {reason}")
                if use_native_fc:
                    return ChatMessage(
                        role="tool", content=refuse_reason,
                        tool_call_id=tc_id, name=tool_name,
                    )
                else:
                    return ChatMessage("user", refuse_reason + " 请直接用你自己的话回答用户。")
        except Exception as e:
            logger.warning(f"P3.1 授权检查失败: {e}")

        # 5. 模式检测记录（操作前）
        try:
            from castorice.security.pattern_detector import get_pattern_detector
            detector = get_pattern_detector()
            if tool_name in ("read_file", "read_document"):
                detector.record("file_read", str(tool_args))
            elif tool_name == "write_file":
                detector.record("file_write", str(tool_args.get("file_path", "")))
            elif tool_name == "terminal":
                detector.record("shell_exec", str(tool_args.get("command", "")))
            elif tool_name == "python_repl":
                detector.record("shell_exec", f"python_repl: {str(tool_args.get('code', ''))[:100]}")
            elif tool_name in ("web_search", "web_fetch", "get_weather"):
                detector.record("network_send", str(tool_args))
        except Exception as e:
            logger.warning(f"P3.3 模式检测记录失败: {e}")

        # 3. 执行工具
        try:
            t_tool = time.time()
            result = tool.invoke(tool_args)
            tool_latency_ms = (time.time() - t_tool) * 1000
            result_str = str(result)[:2000]

            with _state_tool_calls_lock:
                state.tool_calls.append({
                    "tool_name": tool_name,
                    "arguments": tool_args,
                    "result": result_str[:500],
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })
            # 多工具并行时，最后一个执行的会覆盖 current_observation（可接受）
            state.current_observation = result_str
            logger.info(f"工具 {tool_name} 执行成功 ({tool_latency_ms:.0f}ms)，结果: {result_str[:100]}")

            # 自感知：记录工具调用成功
            self.self_awareness.record_tool_call(
                tool_name=tool_name,
                success=True,
                latency_ms=tool_latency_ms,
            )

            # 审计日志：从工具元数据读取风险等级
            audit = _get_audit_logger()
            if audit:
                audit.log_tool_call(
                    user_id=state.session_id,
                    session_id=state.session_id,
                    tool_name=tool_name,
                    args=tool_args,
                    result=result_str[:200],
                    risk_level=tool.risk_level,
                )

            # P3.2: 工具调用自我学习——记录成功案例
            self.tool_learning.record(
                tool_name=tool_name,
                input_description=state.user_input,
                arguments=tool_args,
                result_summary=result_str[:200],
                success=True,
            )

            # P3.1: 记录授权操作结果（成功）
            try:
                from castorice.security.authorization import get_authorization
                auth = get_authorization()
                auth.record_outcome(f"tool.{tool_name}", success=True)
            except Exception as e:
                pass

            if use_native_fc:
                return ChatMessage(
                    role="tool", content=result_str,
                    tool_call_id=tc_id, name=tool_name,
                )
            else:
                return ChatMessage("user",
                    f"工具 {tool_name} 返回结果:\n{result_str}")

        except Exception as e:
            error_msg = f"工具 {tool_name} 执行失败: {e}"
            state.errors.append(error_msg)
            logger.warning(error_msg)

            # P0-3: 告警系统接入 - 工具执行失败
            try:
                _get_alert_manager().warning(
                    title="工具执行失败",
                    message=f"session={state.session_id} tool={tool_name} error={str(e)[:200]}",
                    cooldown_key=f"tool_fail_{tool_name}",
                )
            except Exception as e:
                logger.warning(f"工具执行失败告警发送失败: {e}")

            self.self_awareness.record_tool_call(
                tool_name=tool_name,
                success=False,
                latency_ms=0,
                error_msg=str(e),
            )

            # P3.1: 记录授权操作结果（失败）
            try:
                from castorice.security.authorization import get_authorization
                auth = get_authorization()
                auth.record_outcome(f"tool.{tool_name}", success=False)
            except Exception as e:
                pass

            audit = _get_audit_logger()
            if audit:
                audit.log_tool_call(
                    user_id=state.session_id,
                    session_id=state.session_id,
                    tool_name=tool_name,
                    args=tool_args,
                    result=f"ERROR: {error_msg[:100]}",
                    risk_level="high",
                )

            # P3.2: 工具调用自我学习——记录失败案例
            self.tool_learning.record(
                tool_name=tool_name,
                input_description=state.user_input,
                arguments=tool_args,
                result_summary=f"ERROR: {error_msg[:100]}",
                success=False,
            )

            if use_native_fc:
                return ChatMessage(
                    role="tool", content=error_msg,
                    tool_call_id=tc_id, name=tool_name,
                )
            else:
                return ChatMessage("user", f"{error_msg}\n请换一种方式或直接回答。")

    def _execute_tool_calls_parallel(
        self,
        tool_calls: List[Dict[str, Any]],
        state,
        content: str,
        use_native_fc: bool,
    ) -> List[Optional[ChatMessage]]:
        """
        并行执行多个 tool_calls（使用线程池）

        保证返回结果顺序与输入 tool_calls 顺序一致（便于 FC 模式回传对应 tool_call_id）。
        """
        results: List[Optional[ChatMessage]] = [None] * len(tool_calls)

        with ThreadPoolExecutor(max_workers=min(4, len(tool_calls))) as executor:
            future_to_idx = {}
            for idx, tc in enumerate(tool_calls):
                future = executor.submit(
                    self._execute_single_tool_call, tc, state, content, use_native_fc
                )
                future_to_idx[future] = idx

            for future in as_completed(future_to_idx):
                idx = future_to_idx[future]
                try:
                    results[idx] = future.result()
                except Exception as e:
                    logger.warning(f"并行执行 tool_call[{idx}] 异常: {e}")
                    state.errors.append(f"并行工具执行异常: {e}")
                    # 兜底：返回一条错误消息
                    tc = tool_calls[idx]
                    tc_id = tc.get("id", "")
                    tc_name = tc.get("name", "")
                    if use_native_fc:
                        results[idx] = ChatMessage(
                            role="tool", content=f"并行执行异常: {e}",
                            tool_call_id=tc_id, name=tc_name,
                        )
                    else:
                        results[idx] = ChatMessage("user", f"工具 {tc_name} 并行执行异常: {e}")

        logger.info(f"并行执行 {len(tool_calls)} 个工具完成")
        return results

    def _maybe_compress_tool_messages(self, messages: List[ChatMessage]) -> None:
        """
        P1-2: 压缩 _step_tool_loop 中的消息列表

        - 估算所有消息总字符数
        - 超阈值时，把早期 tool 消息的 content 截断为摘要
        - 保留最近 2 轮（4 条消息）的完整内容
        - 不动 system 和最初的 user 消息
        """
        total_chars = sum(len(m.content or "") for m in messages)
        if total_chars <= self.TOOL_MESSAGES_CHAR_LIMIT:
            return

        # 找到要压缩的范围：跳过 system + 初始 user，保留最后 N 条
        # messages 结构：[system, user, assistant, tool, assistant, tool, ...]
        if len(messages) <= self.TOOL_MESSAGES_KEEP_RECENT + 2:
            return  # 消息太少，不压缩

        # 从第 2 条（index=2，第一条 assistant）开始压缩，到倒数第 KEEP_RECENT 条
        compress_end = len(messages) - self.TOOL_MESSAGES_KEEP_RECENT
        compressed_count = 0
        for i in range(2, compress_end):
            msg = messages[i]
            # 只压缩 tool 角色消息（含工具结果，通常最长）
            if msg.role == "tool" and msg.content and len(msg.content) > 200:
                original_len = len(msg.content)
                # 保留前 100 字符 + 后 50 字符 + 省略号
                msg.content = (
                    msg.content[:100]
                    + f"\n...[已压缩，原始 {original_len} 字符]...\n"
                    + msg.content[-50:]
                )
                compressed_count += 1
            # 也压缩 assistant 消息中的长 content（工具调用的 reasoning）
            elif msg.role == "assistant" and msg.content and len(msg.content) > 300:
                original_len = len(msg.content)
                msg.content = msg.content[:150] + f"\n...[已压缩，原始 {original_len} 字符]..."
                compressed_count += 1

        if compressed_count > 0:
            new_total = sum(len(m.content or "") for m in messages)
            logger.info(
                f"P1-2 消息压缩: 压缩 {compressed_count} 条消息，"
                f"总字符 {total_chars} → {new_total} (节省 {total_chars - new_total})"
            )

    # ============================================================
    # 工具函数
    # ============================================================
    def _ensure_images_in_answer(self, answer: str, tool_calls: list) -> str:
        """兜底：如果回答中没有图片 Markdown，从工具结果中提取并追加"""
        import re
        # 检查回答中是否已有 Markdown 图片
        if re.search(r'!\[.*?\]\(https?://', answer):
            return answer

        # 从工具调用结果中收集图片 URL
        image_urls = []
        for tc in tool_calls:
            result = tc.get("result", "")
            # 提取 markdown 图片
            for url in re.findall(r'!\[.*?\]\((https?://[^\s)]+)\)', result):
                if url not in image_urls:
                    image_urls.append(url)

        if image_urls:
            images_section = "\n\n---\n### 相关图片\n\n"
            for url in image_urls[:3]:
                images_section += f"![图片]({url})\n\n"
            return answer + images_section

        return answer

    def _split_for_streaming(self, text: str) -> List[str]:
        """
        P1-3: 把文本切分成流式输出块，但保护 Markdown 图片 URL 不被切断。

        策略：
        1. 先把所有 ![desc](url) 整段替换为占位符
        2. 按句子/标点切分
        3. 把占位符还原回原图片标记
        """
        import re
        # 匹配 Markdown 图片：![描述](URL)
        image_pattern = re.compile(r'!\[[^\]]*\]\([^)]+\)')
        placeholders: List[str] = []

        def _stash(m):
            placeholders.append(m.group(0))
            return f"\x00IMG{len(placeholders) - 1}\x00"

        protected = image_pattern.sub(_stash, text)

        # 按句子/标点切分（中文标点+英文标点+换行）
        chunks = re.split(r'(?<=[。！？.!?\n])', protected)

        # 还原占位符
        result = []
        for chunk in chunks:
            if not chunk:
                continue
            # 还原 chunk 内的占位符
            def _restore(m):
                idx = int(m.group(1))
                return placeholders[idx] if 0 <= idx < len(placeholders) else m.group(0)
            restored = re.sub(r'\x00IMG(\d+)\x00', _restore, chunk)
            result.append(restored)
        return result
