"""
自动生成的 Mixin：WorkflowStepsMixin
从 core.py 中拆分出来，与 CastoriceAgent 组合使用
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from castorice.model_adapter import ChatMessage
from castorice.utils import extract_json
from .common import logger
logger = logging.getLogger(__name__)


class WorkflowStepsMixin:
    def _get_workflow_steps(self, workflow_name: str) -> List[str]:
        """获取工作流模板的步骤列表"""
        if not self.workflows or workflow_name not in self.workflows:
            logger.warning(f"工作流模板 '{workflow_name}' 不存在，使用标准流程")
            return ["intent", "tool_loop", "answer", "reflection", "memory", "skill"]

        workflow = self.workflows.get(workflow_name, {})
        return workflow.get("steps", ["intent", "tool_loop", "answer", "reflection", "memory", "skill"])

    async def _execute_step(self, step: str, state: State, stream_callback: Optional[Callable[[str], None]] = None) -> None:
        """执行单个步骤（支持同步和异步步骤）"""
        step_map = {
            "intent": self._step_intent,
            "planning": self._step_planning,
            "tool_loop": lambda s: self._step_tool_loop(s, stream_callback),
            "answer": lambda s: self._step_answer(s, stream_callback),
            "reflection": self._step_reflection,
            "memory": self._step_memory,
            "skill": self._step_skill,
        }

        if step in step_map:
            fn = step_map[step]
            result = fn(state)
            if asyncio.iscoroutine(result):
                await result
        else:
            logger.warning(f"未知步骤: {step}")

    # ============================================================
    # 阶段1: 意图解析
    # ============================================================
    def _step_intent(self, state: State) -> None:
        """判断用户意图：纯闲聊 vs 需要工具的任务（P0.4: LLM 优先，规则仅做安全兜底）"""
        # P0.4: 技能匹配——让 LLM 自主决定是否匹配技能，不再硬编码关键词判断
        try:
            matches = self.skill_memory.match(state.user_input, top_n=3)
            if matches:
                skill_list = []
                for skill in matches:
                    if skill.enabled:
                        skill_list.append({
                            "name": skill.name,
                            "description": skill.description,
                            "keywords": ", ".join(skill.trigger_keywords),
                        })

                if skill_list:
                    skills_desc = "\n".join(
                        f"- {s['name']}: {s['description']} (触发词: {s['keywords']})"
                        for s in skill_list
                    )

                    prompt = f"""判断以下用户输入是否应该匹配某个技能。

用户输入: {state.user_input}

可用技能:
{skills_desc}

只返回 JSON：{{"match": true/false, "skill_name": "匹配的技能名或空字符串", "reason": "理由"}}

规则：
- 只有当用户输入明确指向技能的功能时才匹配
- 不强制匹配，让 Agent 自主决定是否需要调用技能
- 如果不确定，返回 false"""

                    try:
                        response = self.model.chat([
                            ChatMessage("system", "你是技能匹配器，只输出 JSON。"),
                            ChatMessage("user", prompt),
                        ])
                        parsed = extract_json(response.content)
                        if parsed.get("match") and parsed.get("skill_name"):
                            matched_skill = next((m for m in matches if m.name == parsed["skill_name"]), None)
                            if matched_skill:
                                state.intent_type = "task"
                                state.matched_skill_id = matched_skill.id
                                state.confidence = 0.95
                                logger.info(f"P0.4 LLM 技能匹配: {parsed['skill_name']} | {parsed.get('reason', '')}")
                                return
                    except (OSError, ValueError, RuntimeError) as e:
                        logger.debug(f"LLM 技能匹配失败，跳过: {e}")
        except (OSError, ValueError, RuntimeError) as e:
            logger.warning(f"技能匹配异常: {e}")

        # P0.4: 极简兜底——只拦截明显的危险输入
        # 不再做"是否需要工具"的硬编码判断（让 LLM 自主决定）
        user_input_lower = state.user_input.lower()
        if len(state.user_input.strip()) == 0:
            state.intent_type = "chat"
            state.confidence = 1.0
            return

        # P0.4: 极短输入（1-2字）让 LLM 自主决定，不预设意图
        # 例如用户输入"嗯"、"好"、"哦"等，让 Agent 自己理解语境
        if 1 <= len(state.user_input.strip()) <= 2:
            logger.info(f"P0.4 极短输入，让 LLM 自主决定: {state.user_input}")
            # 直接走 LLM 判断，不做任何预设
            pass

        # P0.4: LLM 自主判断（移除所有硬编码的 chat_patterns 短输入判断）
        # 信任 LLM 的语义理解能力，让 Agent 自主决定如何响应
        prompt = f"""判断用户输入的意图类型。

可选值：
- "chat": 闲聊、问候、知识问答、咨询、表达情绪、询问意见等不需要立即执行外部工具的对话
- "task": 需要调用工具才能完成的任务（搜索、查询天气、读文件、执行命令、生成图片、读写文档等）

判断准则：
- 如果 Agent 可以仅凭自身知识/推理/对话就能给出有意义的回复 → chat
- 如果 Agent 必须获取实时信息/操作外部资源/执行命令才能给出有效回复 → task
- 不确定时，优先选 chat（对话成本更低，也允许 Agent 主动决定是否调用工具）

只返回 JSON：{{"intent": "chat 或 task", "reasoning": "一句话理由"}}

用户输入: {state.user_input}"""

        try:
            response = self.model.chat([
                ChatMessage("system", "你是意图分类器，只输出 JSON。"),
                ChatMessage("user", prompt),
            ])
            parsed = extract_json(response.content)
            state.intent_type = parsed.get("intent", "chat")
            if state.intent_type not in ("chat", "task"):
                state.intent_type = "chat"  # 默认 chat（更保守，不强加工具）
            logger.info(f"P0.4 LLM 意图分类: {state.intent_type} | {parsed.get('reasoning', '')}")
        except Exception as e:
            logger.warning(f"意图分类失败，默认 chat: {e}")
            state.intent_type = "chat"

    # ============================================================
    # 阶段1.5: 任务规划（自组织）
    # ============================================================
    def _step_planning(self, state: State) -> None:
        """
        任务规划步骤（自组织能力）。
        复杂任务分解为子任务，然后真正执行子任务。
        简单任务直接跳过。
        """
        if state.intent_type == "chat":
            logger.info("闲聊模式，跳过任务规划")
            return

        try:
            t0 = time.time()
            plan = self.task_planner.plan(state.user_input)
            state.task_plan = plan
            state.task_complexity = plan.estimated_complexity

            logger.info(
                f"任务规划完成: {len(plan.subtasks)}个子任务, "
                f"复杂度={plan.estimated_complexity}, "
                f"预估工具调用={plan.estimated_tool_calls}次, "
                f"耗时={time.time() - t0:.2f}s"
            )

            if plan.reasoning:
                logger.debug(f"规划理由: {plan.reasoning}")

            # 真正执行子任务（支持并行）
            if not plan.is_simple:
                logger.info("开始执行子任务...")
                plan = self.task_executor.execute(plan, parallel=True)
                logger.info("子任务执行完成:\n" + plan.to_summary())

                # 将子任务结果汇总到 state.current_observation
                results = []
                for subtask in plan.subtasks:
                    if subtask.status == "completed" and subtask.result:
                        results.append(f"[{subtask.id}] {subtask.description}: {subtask.result}")
                    elif subtask.status == "failed":
                        results.append(f"[{subtask.id}] {subtask.description}: 失败 - {subtask.error}")

                if results:
                    state.current_observation = "\n\n".join(results)
                    # 也记录为工具调用，方便后续流程使用
                    state.tool_calls.append({
                        "tool_name": "task_planning",
                        "arguments": {"subtasks": len(plan.subtasks)},
                        "result": state.current_observation[:500],
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    })

        except Exception as e:
            logger.warning(f"任务规划失败: {e}")
            state.errors.append(f"任务规划失败: {e}")

    # ============================================================
    # 阶段4: 结果生成（兜底）
    # ============================================================
    def _step_answer(self, state: State, stream_callback: Optional[Callable[[str], None]] = None) -> None:
        """直接用 LLM 生成回答（无工具调用或兜底），注入历史记忆"""
        # P1-5: 如果 _step_tool_loop 已经生成了 final_answer，跳过本步骤避免覆盖
        if state.final_answer:
            logger.debug("P1-5: _step_tool_loop 已生成 final_answer，跳过 _step_answer")
            return

        # 构建系统提示（统一方法，注入用户画像 + 长期记忆 + 短期记忆）
        base_prompt = "你正在与用户交互。做你认为正确的事。"
        system_prompt = self._build_system_prompt(state, base_prompt)

        if state.intent_type == "chat":
            # 闲聊模式：直接回答，但带上历史记忆
            prompt = state.user_input
        else:
            # 任务模式：基于工具结果回答
            obs = "\n---\n".join(t["result"] for t in state.tool_calls) or state.current_observation
            prompt = f"""用户需求: {state.user_input}
工具结果:
{obs}

请给出清晰完整的最终回答。"""

        try:
            t0 = time.time()
            messages = [
                ChatMessage("system", system_prompt, cacheable=True),
                ChatMessage("user", prompt),
            ]

            if stream_callback and callable(stream_callback):
                # 流式输出模式
                full_content = ""
                for chunk in self.model.chat_stream(messages):
                    full_content += chunk
                    stream_callback(chunk)
                state.final_answer = full_content
                latency_ms = (time.time() - t0) * 1000
                # P1-3: 用 tiktoken 精确统计 token（prompt + completion），替代硬编码 0
                prompt_text = system_prompt + "\n" + prompt
                self.self_awareness.record_llm_call(
                    prompt_tokens=self.self_awareness.estimate_tokens(prompt_text),
                    completion_tokens=self.self_awareness.estimate_tokens(full_content),
                    error=False,
                    latency_ms=latency_ms,
                )
            else:
                # 非流式模式
                response = self.model.chat(messages)
                latency_ms = (time.time() - t0) * 1000
                state.final_answer = response.content

                # 自感知：记录 LLM 调用
                usage = response.usage or {}
                self.self_awareness.record_llm_call(
                    prompt_tokens=usage.get("prompt_tokens", 0),
                    completion_tokens=usage.get("completion_tokens", 0),
                    error=False,
                    latency_ms=latency_ms,
                )
        except Exception as e:
            state.final_answer = f"生成回答失败: {e}"
            # 自感知：记录 LLM 调用错误
            self.self_awareness.record_llm_call(error=True)

        state.success = len(state.errors) == 0 and bool(state.final_answer)

    # ============================================================
    # 辅助方法：上下文压缩、资源感知、不确定性提示
    # ============================================================
