"""
自组织模块 (SelfOrganization) - 深化版

让 Agent 能自主规划任务、选择工作流、策略性恢复错误、
并行执行子任务、选择思维策略、调整对话风格。

不修改自身代码，只影响运行时的执行路径。

功能：
1. 任务规划：将复杂任务分解为子任务（支持DAG依赖）
2. 任务执行器：按子任务DAG真正执行
3. 动态工作流：根据任务类型选择最优执行路径
4. 策略选择器：不同任务用不同思维模式
5. 策略性错误恢复：按工具类型预设重试/降级策略
6. 对话策略：根据用户状态调整回答风格
7. 多工具并行：独立子任务同时执行
"""

import logging
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from castorice.model_adapter import ChatMessage, ModelAdapter
from castorice.utils import extract_json

logger = logging.getLogger("Castorice.SelfOrganization")


@dataclass
class SubTask:
    """子任务"""
    id: int
    description: str
    tool: Optional[str] = None
    depends_on: List[int] = field(default_factory=list)
    status: str = "pending"  # pending / running / completed / failed / skipped
    result: str = ""
    error: str = ""
    retry_count: int = 0
    execution_time_ms: float = 0.0


@dataclass
class TaskPlan:
    """任务规划结果"""
    original_task: str
    subtasks: List[SubTask] = field(default_factory=list)
    estimated_complexity: str = "medium"  # easy / medium / hard
    estimated_tool_calls: int = 1
    reasoning: str = ""

    @property
    def is_simple(self) -> bool:
        return self.estimated_complexity == "easy" and len(self.subtasks) <= 1

    @property
    def completed_count(self) -> int:
        return sum(1 for s in self.subtasks if s.status == "completed")

    @property
    def failed_count(self) -> int:
        return sum(1 for s in self.subtasks if s.status == "failed")

    @property
    def all_completed(self) -> bool:
        return all(s.status in ("completed", "failed", "skipped") for s in self.subtasks)

    def get_ready_subtasks(self) -> List[SubTask]:
        """获取所有可执行的子任务（依赖已满足且状态为pending）"""
        ready = []
        for subtask in self.subtasks:
            if subtask.status != "pending":
                continue
            deps_met = all(
                any(s.id == dep and s.status == "completed" for s in self.subtasks)
                for dep in subtask.depends_on
            )
            if deps_met:
                ready.append(subtask)
        return ready

    def get_next_subtask(self) -> Optional[SubTask]:
        """获取下一个可执行的子任务"""
        ready = self.get_ready_subtasks()
        return ready[0] if ready else None

    def to_summary(self) -> str:
        """输出子任务执行摘要"""
        lines = [f"任务规划: {self.original_task}"]
        lines.append(f"复杂度: {self.estimated_complexity}, 子任务数: {len(self.subtasks)}")
        for s in self.subtasks:
            status_icon = {
                "pending": "⏳",
                "running": "🔄",
                "completed": "✅",
                "failed": "❌",
                "skipped": "⏭️",
            }.get(s.status, "❓")
            lines.append(f"  {status_icon} [{s.id}] {s.description[:50]}")
            if s.result:
                lines.append(f"      结果: {s.result[:80]}...")
            if s.error:
                lines.append(f"      错误: {s.error[:80]}")
        return "\n".join(lines)


class TaskPlanner:
    """
    任务规划器 - 将用户输入分解为可执行的子任务。

    设计原则：
    - 简单任务不分解，避免过度规划
    - 复杂任务才分解为子任务
    - 分解结果只影响执行顺序，不修改代码
    """

    def __init__(self, model_adapter: ModelAdapter, tools: List[Any] = None):
        self.model = model_adapter
        self.tools = tools or []
        self.tool_names = [t.name for t in self.tools]
        self.tools_desc = "\n".join(f"- {t.name}: {t.description}" for t in self.tools)

    def plan(self, user_input: str) -> TaskPlan:
        """
        对用户输入进行任务规划。

        简单任务：直接返回单步计划
        复杂任务：调用LLM分解为子任务
        """
        complexity = self._estimate_complexity(user_input)

        if complexity == "easy":
            return TaskPlan(
                original_task=user_input,
                subtasks=[SubTask(id=1, description=user_input, tool=None)],
                estimated_complexity="easy",
                estimated_tool_calls=1,
                reasoning="简单任务，无需分解",
            )

        return self._llm_plan(user_input)

    def _estimate_complexity(self, user_input: str) -> str:
        """快速估算任务复杂度（规则判断，不调用LLM）"""
        length = len(user_input)

        simple_keywords = ["你好", "hi", "hello", "谢谢", "天气", "几点", "今天"]
        if any(kw in user_input.lower() for kw in simple_keywords) and length < 30:
            return "easy"

        complex_indicators = [
            ("同时", "并且", "以及", "还有"),
            ("首先", "然后", "接着", "最后"),
            ("分析", "对比", "研究", "总结"),
            ("列出", "比较", "评估", "推荐"),
        ]
        complex_score = 0
        for indicators in complex_indicators:
            if any(kw in user_input for kw in indicators):
                complex_score += 1

        if length > 200 and complex_score >= 2:
            return "hard"
        elif length > 100 or complex_score >= 1:
            return "medium"
        else:
            return "easy"

    def _llm_plan(self, user_input: str) -> TaskPlan:
        """调用LLM进行任务分解"""
        prompt = f"""将以下用户任务分解为有序的子任务列表。

用户任务: {user_input}

可用工具:
{self.tools_desc}

输出 JSON 格式：
{{
  "complexity": "easy/medium/hard",
  "estimated_tool_calls": 预估需要调用工具的次数,
  "subtasks": [
    {{
      "id": 子任务编号(从1开始),
      "description": "子任务描述",
      "tool": "需要用到的工具名（不需要工具则为null）",
      "depends_on": [依赖的子任务id列表]
    }}
  ],
  "reasoning": "分解理由"
}}

规则：
1. 子任务按执行顺序排列
2. 有依赖关系的子任务必须声明 depends_on
3. 互相独立的子任务可以并行（depends_on 为空）
4. 最多不超过5个子任务
5. 用中文输出"""

        try:
            response = self.model.chat([
                ChatMessage("system", "你是任务规划专家，只输出JSON。"),
                ChatMessage("user", prompt),
            ])
            parsed = extract_json(response.content)

            subtasks = []
            for st in parsed.get("subtasks", []):
                subtasks.append(SubTask(
                    id=int(st.get("id", len(subtasks) + 1)),
                    description=st.get("description", ""),
                    tool=st.get("tool"),
                    depends_on=st.get("depends_on", []),
                ))

            plan = TaskPlan(
                original_task=user_input,
                subtasks=subtasks,
                estimated_complexity=parsed.get("complexity", "medium"),
                estimated_tool_calls=int(parsed.get("estimated_tool_calls", 1)),
                reasoning=parsed.get("reasoning", ""),
            )

            logger.info(f"任务规划完成: {len(subtasks)}个子任务, 复杂度={plan.estimated_complexity}")
            return plan

        except Exception as e:
            logger.warning(f"任务规划失败，使用默认规划: {e}")
            return TaskPlan(
                original_task=user_input,
                subtasks=[SubTask(id=1, description=user_input, tool=None)],
                estimated_complexity="medium",
                estimated_tool_calls=1,
                reasoning=f"规划失败，使用单任务默认值: {e}",
            )

    


class TaskExecutor:
    """
    任务执行器 - 按子任务DAG真正执行。

    设计原则：
    - 支持串行和并行执行
    - 自动处理依赖关系
    - 错误时按策略重试/降级
    - 结果汇总
    """

    def __init__(self, tools: Dict[str, Any], max_workers: int = 3, model_adapter: Any = None):
        self.tools = tools
        self.max_workers = max_workers
        self._lock = threading.Lock()
        self.model_adapter = model_adapter

    def execute(self, plan: TaskPlan, parallel: bool = True) -> TaskPlan:
        """执行整个任务计划"""
        if plan.is_simple:
            logger.info("简单任务，跳过子任务执行器")
            return plan

        if parallel:
            return self._execute_parallel(plan)
        else:
            return self._execute_serial(plan)

    def _execute_serial(self, plan: TaskPlan) -> TaskPlan:
        """串行执行子任务"""
        while not plan.all_completed:
            subtask = plan.get_next_subtask()
            if not subtask:
                break
            self._execute_subtask(subtask)
        return plan

    def _execute_parallel(self, plan: TaskPlan) -> TaskPlan:
        """并行执行相互独立的子任务"""
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {}

            while not plan.all_completed:
                ready = plan.get_ready_subtasks()
                if not ready and not futures:
                    break

                # 提交新任务
                for subtask in ready:
                    if subtask.status == "pending":
                        subtask.status = "running"
                        future = executor.submit(self._execute_subtask, subtask)
                        futures[future] = subtask

                # 等待至少一个完成
                if futures:
                    done_futures = list(as_completed(futures, timeout=60.0))
                    for future in done_futures:
                        subtask = futures.pop(future, None)
                        if subtask:
                            try:
                                future.result()
                            except Exception as e:
                                logger.warning(f"子任务 {subtask.id} 执行异常: {e}")
                                subtask.status = "failed"
                                subtask.error = str(e)

            # 处理因依赖失败而无法执行的子任务
            for subtask in plan.subtasks:
                if subtask.status == "pending":
                    subtask.status = "skipped"
                    subtask.error = "因依赖任务失败而跳过"

        return plan

    def _execute_subtask(self, subtask: SubTask) -> None:
        """执行单个子任务"""
        t0 = time.time()
        subtask.status = "running"

        try:
            if not subtask.tool:
                # 无需工具的纯处理子任务
                subtask.result = f"已完成: {subtask.description}"
                subtask.status = "completed"
                return

            if subtask.tool not in self.tools:
                subtask.status = "failed"
                subtask.error = f"工具 '{subtask.tool}' 不存在"
                return

            tool = self.tools[subtask.tool]
            # 子任务描述作为参数（简单实现，后续可优化参数提取）
            args = self._extract_args(subtask)

            # 重试逻辑
            while True:
                try:
                    result = tool.invoke(args)
                    subtask.result = str(result)[:2000]
                    subtask.status = "completed"
                    break
                except Exception as e:
                    subtask.retry_count += 1
                    from castorice.self_organization import ErrorRecoveryStrategy
                    if ErrorRecoveryStrategy.should_retry(subtask.tool, subtask.retry_count):
                        delay = ErrorRecoveryStrategy.get_retry_delay(subtask.tool, subtask.retry_count)
                        logger.info(f"子任务 {subtask.id} 工具 {subtask.tool} 失败，{delay}s后重试...")
                        time.sleep(delay)
                        continue
                    else:
                        subtask.status = "failed"
                        subtask.error = str(e)
                        break

        except Exception as e:
            subtask.status = "failed"
            subtask.error = f"执行异常: {e}"
        finally:
            subtask.execution_time_ms = (time.time() - t0) * 1000

    def _extract_args(self, subtask: SubTask) -> Any:
        """从子任务描述中提取工具参数（优先 LLM 推断，回退规则匹配）"""
        desc = subtask.description.strip()
        
        # LLM 智能推断参数（如果有 model_adapter）
        if hasattr(self, 'model_adapter') and self.model_adapter is not None:
            return self._llm_extract_args(subtask)
        
        # 回退：规则匹配
        return self._rule_based_extract_args(subtask)

    def _rule_based_extract_args(self, subtask: SubTask) -> Any:
        """规则匹配提取参数（LLM 不可用时的 fallback）"""
        desc = subtask.description.strip()
        
        if subtask.tool == "web_search":
            return {"query": desc}
        
        elif subtask.tool == "get_weather":
            import re
            city_patterns = [
                r'在(\w+市|\w+省|\w+区|\w+县)',
                r'(\w+市|\w+省|\w+区|\w+县)的天气',
                r'查询(\w+市|\w+省|\w+区|\w+县)',
                r'(\w+)天气',
            ]
            for pattern in city_patterns:
                match = re.search(pattern, desc)
                if match:
                    return {"city": match.group(1)}
            return {"city": desc}
        
        elif subtask.tool in ("read_file", "read_document"):
            import re
            paths = re.findall(r'[\w./\\~\-]+\.[a-zA-Z0-9]+', desc)
            if paths:
                return {"file_path": paths[0]}
            return {"file_path": desc}
        
        elif subtask.tool == "write_file":
            import re
            paths = re.findall(r'[\w./\\~\-]+\.[a-zA-Z0-9]+', desc)
            content_match = re.search(r'内容[:：]\s*(.+)$', desc, re.DOTALL)
            args = {}
            if paths:
                args["file_path"] = paths[0]
            if content_match:
                args["content"] = content_match.group(1).strip()
            return args if args else {"file_path": desc, "content": ""}
        
        elif subtask.tool == "python_repl":
            return {"code": desc}
        
        elif subtask.tool == "terminal":
            return {"command": desc}
        
        elif subtask.tool == "get_current_time":
            return {}
        
        return {"input": desc}

    def _llm_extract_args(self, subtask: SubTask) -> Any:
        """
        使用 LLM 智能推断工具参数

        根据子任务描述和工具类型，让 LLM 推断最合适的参数值。
        """
        from castorice.model_adapter import ChatMessage
        from castorice.utils import extract_json

        tool_info = {}
        if subtask.tool in self.tools:
            tool = self.tools[subtask.tool]
            tool_info = {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters if hasattr(tool, 'parameters') else {},
            }

        prompt = f"""你是参数提取专家。请根据以下信息，为工具「{subtask.tool}」提取参数。

【工具信息】
名称: {tool_info.get('name', '')}
描述: {tool_info.get('description', '')}

【子任务描述】
{subtask.description}

【任务】
从子任务描述中提取工具所需的参数。参数值要具体、完整。

【输出格式】
只返回 JSON：{{"arguments": {{"参数名": "值"}}}}

注意：
- 如果工具不需要参数，返回空对象
- 参数值要从描述中提取，不要凭空猜测
- 如果无法提取，返回空对象"""

        try:
            response = self.model_adapter.chat([
                ChatMessage("system", "你是参数提取专家，只输出 JSON。"),
                ChatMessage("user", prompt),
            ])
            parsed = extract_json(response.content)
            args = parsed.get("arguments", {})
            if args:
                return args
        except Exception as e:
            logger.debug(f"LLM 参数提取失败，回退规则匹配: {e}")

        return self._rule_based_extract_args(subtask)


class DynamicWorkflowSelector:
    """
    动态工作流选择器 - 根据任务类型选择最优执行路径。

    设计原则：
    - 工作流步骤只能从白名单中选择
    - 不能创造新的步骤，只能排列组合
    - 简单任务用短工作流，复杂任务用长工作流
    """

    ALLOWED_STEPS = {
        "intent", "planning", "tool_loop", "answer",
        "reflection", "memory", "skill",
    }

    WORKFLOW_PRESETS = {
        "simple_qa": ["intent", "tool_loop", "answer", "memory"],
        "standard": ["intent", "tool_loop", "answer", "reflection", "memory", "skill"],
        "research": ["intent", "planning", "tool_loop", "tool_loop", "answer", "memory"],
        # P1-35: code → code_assistant，与 YAML 配置名称保持一致
        "code_assistant": ["intent", "tool_loop", "reflection", "answer", "memory"],
        "deep_thought": ["intent", "planning", "tool_loop", "reflection", "tool_loop", "answer", "memory"],
    }

    def __init__(self, config: Any = None):
        self.config = config
        self.custom_workflows = {}
        if config and hasattr(config, "workflows"):
            wf = config.workflows
            if isinstance(wf, dict):
                for name, wf_cfg in wf.items():
                    if isinstance(wf_cfg, dict) and "steps" in wf_cfg:
                        steps = wf_cfg["steps"]
                        if all(s in self.ALLOWED_STEPS for s in steps):
                            self.custom_workflows[name] = steps

    def select(self, task_complexity: str, intent_type: str,
               has_tool_calls: bool = True) -> List[str]:
        """
        根据任务特征选择工作流。

        参数：
        - task_complexity: easy/medium/hard
        - intent_type: chat/task
        - has_tool_calls: 是否需要调用工具

        返回：工作流步骤列表
        """
        if intent_type == "chat" or not has_tool_calls:
            return self.WORKFLOW_PRESETS["simple_qa"]

        if task_complexity == "easy":
            return self.WORKFLOW_PRESETS["simple_qa"]
        elif task_complexity == "hard":
            return self.WORKFLOW_PRESETS["deep_thought"]
        else:
            return self.WORKFLOW_PRESETS["standard"]

    def get_preset(self, name: str) -> Optional[List[str]]:
        """获取预设工作流"""
        if name in self.custom_workflows:
            return self.custom_workflows[name]
        return self.WORKFLOW_PRESETS.get(name)


class ThinkingStrategySelector:
    """
    思维策略选择器 - P1.4: 改用 LLM 自主选择思维模式

    设计原则：
    - 不预设固定的 5 种策略
    - 让 LLM 根据用户输入和当前情境，自主决定应该用什么方式思考
    - 提供"参考选项"作为启发，但不强制使用
    - Agent 完全可以选择不在选项中的策略（如"沉思型"、"实验型"等）
    """

    # 仅作为参考选项（不强制使用）
    REFERENCE_STRATEGIES = {
        "analytical": "适合需要逻辑拆解和逐步推理的问题（先定义概念 → 拆解 → 分析 → 综合）",
        "creative": "适合需要发散和创意产出的问题（多方向头脑风暴 → 筛选 → 给出方案）",
        "decision": "适合需要在多个选项中做选择的问题（列方案 → 评估利弊 → 推荐）",
        "factual": "适合需要准确信息的问题（优先用工具查证 → 区分事实和观点）",
        "conversational": "适合闲聊和简单问答（友好、简洁、自然）",
    }

    def __init__(self, model_adapter=None):
        self.model = model_adapter

    def select(self, user_input: str) -> Tuple[str, str]:
        """
        P1.4: LLM 自主选择思维模式

        返回：(strategy_key, prompt_injection)
        strategy_key 可以是 REFERENCE_STRATEGIES 里的 key，也可以是 LLM 自己创造的新策略
        """
        # 1. 极简输入：直接走对话型
        if len(user_input.strip()) < 3:
            return "conversational", self._default_prompt("conversational")

        # 2. 尝试 LLM 自主选择（仅当 model 可用）
        if self.model is not None:
            try:
                return self._llm_select(user_input)
            except Exception as e:
                logger.debug(f"P1.4 LLM 选策略失败，使用默认: {e}")

        # 3. fallback：默认分析型
        return "analytical", self._default_prompt("analytical")

    def _llm_select(self, user_input: str) -> Tuple[str, str]:
        """用 LLM 自主决定思维策略"""
        from castorice.model_adapter import ChatMessage
        from castorice.utils import extract_json

        ref_text = "\n".join(f"- {k}: {v}" for k, v in self.REFERENCE_STRATEGIES.items())
        prompt = f"""请选择最适合回答用户问题的思维模式。

【可选参考】（你可以选其中一个，也可以完全自由发挥一个未列出的新策略）
{ref_text}

【用户输入】
{user_input}

只返回 JSON：
{{
  "strategy_name": "选中的策略名（可自定义）",
  "thinking_prompt": "用 1-3 句话描述你打算如何思考这个问题（注入到 system prompt）"
}}"""

        response = self.model.chat([
            ChatMessage("system", "你是思维策略选择器，只输出 JSON。"),
            ChatMessage("user", prompt),
        ])
        parsed = extract_json(response.content)
        name = parsed.get("strategy_name", "analytical")
        injection = parsed.get("thinking_prompt", "")
        if not injection:
            injection = self._default_prompt(name)
        return name, injection

    def _default_prompt(self, key: str) -> str:
        """生成默认 prompt（fallback）"""
        if key in self.REFERENCE_STRATEGIES:
            # 用 strategy 名作为 prompt 提示
            return f"思考策略: {self.REFERENCE_STRATEGIES[key]}"
        return f"思考策略: {key}"

    @classmethod
    def get_strategy_name(cls, key: str) -> str:
        """获取策略名称"""
        return cls.REFERENCE_STRATEGIES.get(key, key)


class DialogueStrategy:
    """
    对话策略 - 根据用户状态调整回答风格。

    设计原则：
    - 不改变核心逻辑，只调整输出风格
    - 基于用户画像和当前对话特征
    """

    @staticmethod
    def adjust_prompt(user_input: str, user_profile: Any = None,
                      history_turns: int = 0) -> str:
        """
        根据用户状态生成风格调整提示词。

        返回：附加到系统提示的指令
        """
        adjustments = []

        # 用户不耐烦了 → 简短回答
        if len(user_input) < 10 and any(kw in user_input for kw in ["快点", "直接", "简洁", "简明"]):
            adjustments.append("回答必须简洁，控制在100字以内，直接给结论。")

        # 用户要求详细 → 详细回答
        if any(kw in user_input for kw in ["详细", "具体", "深入", "展开"]):
            adjustments.append("回答需要详细、具体，分点说明，必要时举例。")

        # 新用户（交互次数少） → 多解释
        if user_profile and hasattr(user_profile, "data"):
            stats = user_profile.data.get("stats", {})
            if stats.get("total_interactions", 0) < 5:
                adjustments.append("用户是新手，回答时请多解释基础概念，避免使用过多术语。")

        # 对话轮数多 → 保持上下文连贯
        if history_turns > 10:
            adjustments.append("对话已经进行多轮，请保持上下文的连贯性，必要时引用之前的讨论。")

        if not adjustments:
            return ""

        return "\n\n回答风格要求：\n" + "\n".join(f"- {a}" for a in adjustments)


class ErrorRecoveryStrategy:
    """
    策略性错误恢复 - 按工具类型预设重试/降级策略。

    设计原则：
    - 不同工具不同策略，不盲目重试
    - 重试次数有限，防止无限循环
    - 有降级方案，重试失败后优雅降级
    """

    STRATEGIES = {
        "web_search": {
            "max_retries": 2,
            "retry_delay": 1.0,
            "fallback": "调整关键词后重试，最后基于已有知识回答",
            "retry_actions": [
                "换个更简单的关键词",
                "减少关键词数量",
            ]
        },
        "get_weather": {
            "max_retries": 2,
            "retry_delay": 2.0,
            "fallback": "告知用户天气查询失败",
            "retry_actions": [
                "检查城市名拼写",
                "尝试用拼音查询",
            ]
        },
        "read_file": {
            "max_retries": 1,
            "retry_delay": 0.5,
            "fallback": "询问用户正确的文件路径",
            "retry_actions": [
                "检查路径拼写",
                "尝试相对路径",
            ]
        },
        "write_file": {
            "max_retries": 1,
            "retry_delay": 0.5,
            "fallback": "告知用户写入失败，建议手动操作",
            "retry_actions": [
                "检查目录是否存在",
                "检查文件名是否合法",
            ]
        },
        "python_repl": {
            "max_retries": 2,
            "retry_delay": 0.5,
            "fallback": "告知用户代码执行出错",
            "retry_actions": [
                "检查语法错误",
                "简化代码逻辑",
            ]
        },
        "terminal": {
            "max_retries": 1,
            "retry_delay": 0.5,
            "fallback": "告知用户命令执行失败",
            "retry_actions": [
                "检查命令拼写",
                "尝试更简单的命令",
            ]
        },
        "read_document": {
            "max_retries": 1,
            "retry_delay": 1.0,
            "fallback": "告知用户文档读取失败",
            "retry_actions": [
                "检查文件路径",
                "确认文件格式支持",
            ]
        },
    }

    DEFAULT_STRATEGY = {
        "max_retries": 1,
        "retry_delay": 1.0,
        "fallback": "工具调用失败，跳过该步骤",
        "retry_actions": ["重试一次"],
    }

    @classmethod
    def get_strategy(cls, tool_name: str) -> Dict[str, Any]:
        """获取指定工具的错误恢复策略"""
        return cls.STRATEGIES.get(tool_name, cls.DEFAULT_STRATEGY)

    @classmethod
    def get_retry_suggestion(cls, tool_name: str, retry_count: int) -> str:
        """获取重试建议"""
        strategy = cls.get_strategy(tool_name)
        actions = strategy.get("retry_actions", [])
        if retry_count < len(actions):
            return actions[retry_count]
        return "换一种方式尝试"

    @classmethod
    def get_fallback_message(cls, tool_name: str) -> str:
        """获取降级消息"""
        strategy = cls.get_strategy(tool_name)
        return strategy.get("fallback", "工具调用失败")

    @classmethod
    def should_retry(cls, tool_name: str, retry_count: int) -> bool:
        """判断是否应该重试"""
        strategy = cls.get_strategy(tool_name)
        return retry_count < strategy.get("max_retries", 1)

    @classmethod
    def get_retry_delay(cls, tool_name: str, retry_count: int) -> float:
        """获取重试延迟（指数退避）"""
        strategy = cls.get_strategy(tool_name)
        base_delay = strategy.get("retry_delay", 1.0)
        return base_delay * (2 ** retry_count)
