"""
自研 Agent 主循环 (CastoriceAgent)

复刻 Hermes Agent 架构，彻底移除 LangGraph：
- 手写主循环：阶段化执行
- LLM 驱动工具调用：让模型决定用哪个工具、传什么参数
- 状态对象：State 数据类管理运行时数据
"""

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from castorice.model_adapter import ChatMessage, ModelAdapter

logger = logging.getLogger("Castorice.Agent")

# 工具调用最大轮数（防止无限循环）
MAX_TOOL_ROUNDS = 5


@dataclass
class State:
    """Agent 运行时状态（替代 LangGraph 状态传递）"""
    user_input: str = ""
    session_id: str = ""

    # 意图与规划
    intent_type: str = ""              # chat / task
    confidence: float = 1.0
    matched_skill_id: Optional[str] = None
    execution_plan: str = ""

    # 工具执行
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    current_observation: str = ""

    # 结果
    final_answer: str = ""
    success: bool = False
    errors: List[str] = field(default_factory=list)

    # 反思
    reflection_summary: str = ""
    improvement_suggestions: List[str] = field(default_factory=list)
    skill_to_generate: Optional[Dict[str, Any]] = None

    # 上下文
    user_profile_context: str = ""
    relevant_history: str = ""
    available_tools_desc: str = ""


class CastoriceAgent:
    """Castorice Agent 主循环"""

    def __init__(
        self,
        model_adapter: ModelAdapter,
        tools: List[Any],
        short_term_memory: Any,
        long_term_memory: Any,
        skill_memory: Any,
        user_profile: Any,
        config: Any,
    ):
        self.model = model_adapter
        self.tools = {t.name: t for t in tools}
        self.tools_list = tools
        self.short_term = short_term_memory
        self.long_term = long_term_memory
        self.skill_memory = skill_memory
        self.user_profile = user_profile
        self.config = config

        runtime_cfg = config.runtime if hasattr(config, "runtime") else {}
        self.max_iterations = runtime_cfg.get("max_iterations", 10) if isinstance(runtime_cfg, dict) else 10
        self.enable_reflection = runtime_cfg.get("enable_reflection", True) if isinstance(runtime_cfg, dict) else True
        self.enable_skill_generation = runtime_cfg.get("enable_skill_generation", True) if isinstance(runtime_cfg, dict) else True

    # ============================================================
    # 主循环
    # ============================================================
    def run(self, user_input: str, session_id: str) -> State:
        """执行一次完整任务闭环"""
        state = State(user_input=user_input, session_id=session_id)

        # 注入上下文
        try:
            state.relevant_history = self.long_term.get_relevant_context(user_input) or ""
        except Exception:
            state.relevant_history = ""
        state.user_profile_context = self.user_profile.to_prompt_context()
        state.available_tools_desc = "\n".join(
            f"- {t.name}: {t.description}" for t in self.tools_list
        )

        # 阶段1: 意图解析
        self._step_intent(state)

        # 闲聊直接回答
        if state.intent_type == "chat":
            self._step_answer(state)
        else:
            # 阶段2-3: LLM 驱动工具调用循环
            self._step_tool_loop(state)

        # 阶段4: 反思
        if self.enable_reflection and (state.errors or state.tool_calls):
            self._step_reflection(state)

        # 阶段5: 记忆归档
        try:
            self._step_memory(state)
        except Exception as e:
            logger.warning(f"记忆归档失败: {e}")

        # 阶段6: 技能沉淀
        if self.enable_skill_generation and state.skill_to_generate:
            self._step_skill(state)

        # 写入短时记忆
        try:
            from castorice.memory.short_term import Message
            self.short_term.add_message(session_id, Message(role="user", content=user_input))
            self.short_term.add_message(
                session_id,
                Message(role="assistant", content=state.final_answer,
                        metadata={"intent": state.intent_type, "success": state.success}),
            )
        except Exception as e:
            logger.warning(f"短时记忆写入失败: {e}")

        return state

    # ============================================================
    # 阶段1: 意图解析
    # ============================================================
    def _step_intent(self, state: State) -> None:
        """判断用户意图：纯闲聊 vs 需要工具的任务"""
        # 技能匹配
        try:
            matches = self.skill_memory.match(state.user_input, top_n=1)
            if matches and matches[0].enabled:
                top = matches[0]
                if any(kw.lower() in state.user_input.lower() for kw in top.trigger_keywords):
                    state.intent_type = "task"
                    state.matched_skill_id = top.id
                    state.confidence = 0.95
                    return
        except Exception:
            pass

        # LLM 分类
        prompt = f"""判断用户输入是需要调用工具的任务，还是普通闲聊。

只返回 JSON，不要多余内容：
{{"intent": "chat 或 task"}}

判断标准：
- 需要联网搜索、读写文件、执行命令、读文档 → task
- 闲聊、问候、知识问答、翻译、写作 → chat

用户输入: {state.user_input}"""

        try:
            response = self.model.chat([
                ChatMessage("system", "你是意图分类器，只输出 JSON。"),
                ChatMessage("user", prompt),
            ])
            parsed = self._extract_json(response.content)
            state.intent_type = parsed.get("intent", "task")
            if state.intent_type not in ("chat", "task"):
                state.intent_type = "task"
        except Exception as e:
            logger.warning(f"意图分类失败，默认为 task: {e}")
            state.intent_type = "task"

    # ============================================================
    # 阶段2-3: LLM 驱动工具调用循环
    # ============================================================
    def _step_tool_loop(self, state: State) -> None:
        """
        核心工具调用循环：
        1. 把用户需求 + 可用工具告诉 LLM
        2. LLM 输出工具调用决策（JSON）
        3. 执行工具，把结果喂回 LLM
        4. LLM 决定是否继续调用工具或给出最终答案
        """
        tools_desc = state.available_tools_desc
        history_ctx = state.relevant_history

        system_prompt = f"""你是 Castorice Agent，一个能调用工具的智能助手。

你有以下工具可用：
{tools_desc}

调用工具时，输出 JSON：
{{"action": "tool", "tool": "工具名", "args": {{"参数名": "值"}}}}

不需要工具时，输出 JSON：
{{"action": "answer", "answer": "你的回答"}}

规则：
1. 需要实时信息（天气、新闻、股价等）时，使用 web_search
2. 每次只调用一个工具
3. 工具返回结果后，基于结果给出最终回答
4. 用中文回答"""

        # 第一轮：让 LLM 决定调用什么工具
        user_msg = f"用户需求: {state.user_input}"
        if history_ctx:
            user_msg += f"\n\n相关历史记忆:\n{history_ctx[:500]}"

        messages = [
            ChatMessage("system", system_prompt),
            ChatMessage("user", user_msg),
        ]

        for round_num in range(MAX_TOOL_ROUNDS):
            try:
                response = self.model.chat(messages)
                content = response.content.strip()
                logger.info(f"工具循环 第{round_num + 1}轮 LLM响应: {content[:200]}")

                decision = self._extract_json(content)

                action = decision.get("action", "")

                if action == "answer":
                    # LLM 给出最终答案
                    state.final_answer = decision.get("answer", content)
                    state.success = True
                    return

                elif action == "tool":
                    tool_name = decision.get("tool", "")
                    tool_args = decision.get("args", {})

                    if tool_name not in self.tools:
                        # 工具不存在，告诉 LLM
                        messages.append(ChatMessage("assistant", content))
                        messages.append(ChatMessage("user",
                            f"工具 '{tool_name}' 不存在。可用工具: {', '.join(self.tools.keys())}。请用其他工具或直接回答。"))
                        continue

                    # 执行工具
                    try:
                        tool = self.tools[tool_name]
                        result = tool.invoke(tool_args)
                        result_str = str(result)[:2000]

                        state.tool_calls.append({
                            "tool_name": tool_name,
                            "arguments": tool_args,
                            "result": result_str[:500],
                            "timestamp": datetime.utcnow().isoformat(),
                        })
                        state.current_observation = result_str
                        logger.info(f"工具 {tool_name} 执行成功，结果: {result_str[:100]}")

                        # 把工具结果喂回 LLM
                        messages.append(ChatMessage("assistant", content))
                        messages.append(ChatMessage("user",
                            f"工具 {tool_name} 返回结果:\n{result_str}\n\n请基于以上结果回答用户问题，或继续调用工具。"))

                    except Exception as e:
                        error_msg = f"工具 {tool_name} 执行失败: {e}"
                        state.errors.append(error_msg)
                        logger.warning(error_msg)
                        messages.append(ChatMessage("assistant", content))
                        messages.append(ChatMessage("user", f"{error_msg}\n请换一种方式或直接回答。"))
                else:
                    # 无法解析，直接当回答
                    state.final_answer = content
                    state.success = True
                    return

            except Exception as e:
                logger.warning(f"工具循环第{round_num + 1}轮异常: {e}")
                state.errors.append(str(e))
                break

        # 循环结束仍未得到答案，用已有信息生成回答
        if not state.final_answer:
            self._step_answer(state)

    # ============================================================
    # 阶段4: 结果生成（兜底）
    # ============================================================
    def _step_answer(self, state: State) -> None:
        """直接用 LLM 生成回答（无工具调用或兜底）"""
        if state.intent_type == "chat":
            prompt = state.user_input
        else:
            obs = "\n---\n".join(t["result"] for t in state.tool_calls) or state.current_observation
            prompt = f"""用户需求: {state.user_input}
工具结果:
{obs}

请给出清晰完整的最终回答。"""

        try:
            response = self.model.chat([
                ChatMessage("system", "你是 Castorice Agent，自进化智能体。用中文回答。"),
                ChatMessage("user", prompt),
            ])
            state.final_answer = response.content
        except Exception as e:
            state.final_answer = f"生成回答失败: {e}"

        state.success = len(state.errors) == 0

    # ============================================================
    # 阶段5: 反思
    # ============================================================
    def _step_reflection(self, state: State) -> None:
        tool_summary = "\n".join(f"- {t['tool_name']}: {t['result'][:200]}" for t in state.tool_calls)

        prompt = f"""复盘以下任务执行，输出 JSON：
{{
    "summary": "复盘总结",
    "suggestions": ["改进建议"],
    "should_generate_skill": true/false,
    "skill_proposal": {{
        "name": "技能名", "trigger_keywords": ["kw1"],
        "description": "描述", "steps": [{{"tool": "工具名", "参数": "值"}}]
    }}
}}

任务: {state.user_input}
错误: {state.errors}
工具调用:
{tool_summary}"""

        try:
            response = self.model.chat([
                ChatMessage("system", "你是复盘专家，只输出 JSON。"),
                ChatMessage("user", prompt),
            ])
            parsed = self._extract_json(response.content)
            state.reflection_summary = parsed.get("summary", "")
            state.improvement_suggestions = parsed.get("suggestions", [])
            if parsed.get("should_generate_skill") and parsed.get("skill_proposal", {}).get("name"):
                state.skill_to_generate = parsed["skill_proposal"]
        except Exception as e:
            logger.warning(f"反思失败: {e}")

    # ============================================================
    # 阶段6: 记忆归档
    # ============================================================
    def _step_memory(self, state: State) -> None:
        try:
            memory_text = f"用户指令: {state.user_input}\n执行结果: {state.final_answer}"
            if state.reflection_summary:
                memory_text += f"\n反思: {state.reflection_summary}"
            self.long_term.add_single(
                text=memory_text,
                metadata={
                    "type": "task_summary",
                    "session_id": state.session_id,
                    "success": state.success,
                    "intent": state.intent_type,
                },
            )
            summary = state.user_input[:50] + ("..." if len(state.user_input) > 50 else "")
            self.short_term.update_summary(state.session_id, summary)
        except Exception as e:
            logger.warning(f"长期记忆写入失败: {e}")

    # ============================================================
    # 阶段7: 技能沉淀
    # ============================================================
    def _step_skill(self, state: State) -> None:
        from castorice.memory.skill import Skill
        proposal = state.skill_to_generate
        if not proposal or not proposal.get("name"):
            return
        try:
            existing = self.skill_memory.find_by_name(proposal["name"])
            if existing:
                existing.trigger_keywords = list(set(existing.trigger_keywords + proposal.get("trigger_keywords", [])))
                existing.steps = proposal.get("steps", existing.steps)
                existing.description = proposal.get("description", existing.description)
                existing.bump_version()
                self.skill_memory._save()
            else:
                skill = Skill(
                    name=proposal["name"],
                    trigger_keywords=proposal.get("trigger_keywords", []),
                    description=proposal.get("description", ""),
                    steps=proposal.get("steps", []),
                    required_tools=proposal.get("required_tools", []),
                    applicable_scenarios=proposal.get("applicable_scenarios", []),
                )
                self.skill_memory.add_or_update(skill)
        except Exception as e:
            logger.warning(f"技能生成失败: {e}")

    # ============================================================
    # 工具函数
    # ============================================================
    def _extract_json(self, text: str) -> Dict[str, Any]:
        """从 LLM 响应中提取 JSON（多层兜底）"""
        if not text:
            return {}
        # 1. markdown 代码块
        match = re.search(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", text)
        if match:
            try:
                return json.loads(match.group(1))
            except Exception:
                pass
        # 2. 取最外层大括号（贪婪匹配）
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            candidate = text[start:end + 1]
            try:
                return json.loads(candidate)
            except Exception:
                # 3. 逐行尝试，找到第一对完整的 JSON
                for line in text.splitlines():
                    line = line.strip()
                    if line.startswith("{") and line.endswith("}"):
                        try:
                            return json.loads(line)
                        except Exception:
                            continue
        return {}
