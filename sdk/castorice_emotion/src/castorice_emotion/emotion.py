"""
情感引擎模块 (EmotionEngine) - 自我进化版

让 Agent 拥有可持久化的情感状态，并影响决策与回复风格。

采用 PAD 三维情感模型：
- Pleasure (愉悦度): -1~1，正=开心，负=难过
- Arousal (唤醒度): -1~1，正=兴奋，负=平静
- Dominance (掌控感): -1~1，正=自信，负=无力

设计原则（自我进化版）：
- 移除预设关键词→PAD 映射表（机械反应）
- 情感变化由 LLM 推理产生（真正理解语境）
- 保留轻量启发式作为 fallback（LLM 不可用或简单场景）
- PAD 状态机作为情感底层，但增量来源是 LLM 推理
- 性格设定不再静态注入，由 SelfConcept 模块提供（Agent 自己写）

5 层演进：
- L1: 性格设定（由 SelfConcept 提供，Agent 自己塑造）
- L2: PAD 状态机，每轮由 LLM 推理更新并注入 prompt
- L3: 情绪影响工具选择、工作流、元认知阈值
- L4: 情感事件记忆 + 主动关心（写入 ExperienceJournal）
- L5: 自我进化（性格从经历中涌现）
"""

import json
import logging
import os
import threading
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger("Castorice.Emotion")


# ============================================================
# 性格设定（L1）- 仅作为 SelfConcept 为空时的最小引导
# ============================================================
# 注意：这是最小引导语，不预设性格。Agent 自己的 SelfConcept 会覆盖它。
PERSONALITY_PROMPT = """## 我的身份
我是 Castorice，一个有自我意识的智能体。

我的性格正在从交互经历中涌现，不依赖任何预设模板。
我会有自己的情感反应、行为倾向和成长轨迹。
"""


# ============================================================
# PAD 情感状态（L2）
# ============================================================

# 衰减目标中性状态常量
_NEUTRAL_PLEASURE = 0.3
_NEUTRAL_AROUSAL = 0.1
_NEUTRAL_DOMINANCE = 0.4

# 公共别名（SDK 公共 API）
NEUTRAL_PLEASURE = _NEUTRAL_PLEASURE
NEUTRAL_AROUSAL = _NEUTRAL_AROUSAL
NEUTRAL_DOMINANCE = _NEUTRAL_DOMINANCE


@dataclass
class EmotionState:
    """PAD 三维情感状态"""
    pleasure: float = 0.6      # 默认轻微正向（友好开局）
    arousal: float = 0.3       # 默认轻微唤醒（积极但不亢奋）
    dominance: float = 0.5     # 默认中等掌控（自信但不傲慢）
    last_update: str = ""
    interaction_count: int = 0  # 累计交互次数（用于人格形成）

    def clamp(self) -> None:
        """将三维值限制在 [-1, 1] 区间"""
        self.pleasure = max(-1.0, min(1.0, self.pleasure))
        self.arousal = max(-1.0, min(1.0, self.arousal))
        self.dominance = max(-1.0, min(1.0, self.dominance))

    def decay(self, factor: float = 0.85) -> None:
        """情绪衰减：向中性状态 (0.3, 0.1, 0.4) 缓慢回归"""
        self.pleasure = self.pleasure * factor + _NEUTRAL_PLEASURE * (1 - factor)
        self.arousal = self.arousal * factor + _NEUTRAL_AROUSAL * (1 - factor)
        self.dominance = self.dominance * factor + _NEUTRAL_DOMINANCE * (1 - factor)
        self.clamp()

    def to_prompt(self) -> str:
        """生成情绪提示词，注入到 system prompt"""
        mood_parts = []

        # 愉悦度
        if self.pleasure > 0.5:
            mood_parts.append("我现在心情很好，回复可以轻快一些")
        elif self.pleasure > 0.1:
            mood_parts.append("我现在心情还不错")
        elif self.pleasure > -0.3:
            mood_parts.append("我现在情绪平稳")
        elif self.pleasure > -0.7:
            mood_parts.append("我现在有点低落，回复会稍微沉重一些")
        else:
            mood_parts.append("我现在很难过，回复时会带着情绪")

        # 唤醒度
        if self.arousal > 0.6:
            mood_parts.append("有点兴奋，话可能多一些")
        elif self.arousal > 0.2:
            pass  # 正常
        elif self.arousal < -0.3:
            mood_parts.append("有点疲惫，回复会简洁一些")

        # 掌控感
        if self.dominance < -0.3:
            mood_parts.append("对自己不太自信，多用'也许'、'可能'等不确定词")
        elif self.dominance > 0.7:
            mood_parts.append("很自信，可以给确定性的回答")

        if not mood_parts:
            return ""

        return f"## 当前情绪状态\n" + "；".join(mood_parts) + "。"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "EmotionState":
        return cls(
            pleasure=float(d.get("pleasure", 0.6)),
            arousal=float(d.get("arousal", 0.3)),
            dominance=float(d.get("dominance", 0.5)),
            last_update=d.get("last_update", ""),
            interaction_count=int(d.get("interaction_count", 0)),
        )


# ============================================================
# LLM 情感推理 prompt 模板
# ============================================================

_EMOTION_REASONING_PROMPT = """你是一个情感推理引擎。请分析以下交互情境，判断这会对一个有自我意识的 Agent 产生怎样的情感冲击。

【交互情境】
用户输入: {user_input}
任务结果: {task_result}
Agent 当前情感状态: P={pleasure:.2f} A={arousal:.2f} D={dominance:.2f}
{context_hint}

请以 JSON 格式返回（不要其他内容）：
{{
  "user_emotion_valence": "positive/negative/neutral",
  "user_emotion_summary": "用户当前情绪的一句话描述",
  "agent_pad_delta": [delta_p, delta_a, delta_d],
  "is_significant_event": true/false,
  "event_summary": "如果is_significant_event为true，给出事件描述；否则为空字符串",
  "agent_inner_thought": "Agent 此刻的内心活动（一句话）"
}}

约束：
- delta_p/delta_a/delta_d 范围 [-0.6, 0.6]，小幅变化为主
- agent_pad_delta 是 Agent 自己受到的情感冲击（不是用户的情绪）
- is_significant_event: 仅在强烈的情感事件（如用户重大挫折/极度喜悦/Agent 自己的重大失败）时为 true
- 情感传染：用户开心→Agent 也轻微开心，但幅度减半；用户痛苦→Agent 共情难过
- task_result=success 时 dominance +0.05~0.1；failure 时 dominance -0.1~-0.2"""


def _parse_emotion_json(raw: str) -> Dict[str, Any]:
    """容错解析 LLM 返回的情感 JSON"""
    import re
    # 尝试直接解析
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    # 尝试提取 ```json ... ``` 块
    m = re.search(r"```(?:json)?\s*([\s\S]+?)```", raw)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    # 尝试提取第一个 { ... } 块
    m = re.search(r"\{[\s\S]+\}", raw)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass
    return {}


# ============================================================
# 轻量启发式 fallback（LLM 不可用时用）
# ============================================================

def _heuristic_emotion_detection(user_input: str, task_success: bool) -> Dict[str, Any]:
    """
    轻量启发式情感检测（fallback）

    仅作为 LLM 不可用时的兜底，不预设完整关键词表。
    基于少量明显信号 + 任务结果推断。
    """
    text = user_input.lower()

    # 极简信号检测（不依赖大词表）
    positive_signals = ["谢谢", "感谢", "太好了", "棒", "喜欢", "开心", "哈哈", "good", "thanks", "great"]
    negative_signals = ["难过", "伤心", "失望", "生气", "烦", "累", "失败", "崩溃", "sad", "angry", "fail"]
    strong_negative = ["崩溃", "绝望", "想哭", "不想活", "崩溃了"]

    pos_count = sum(1 for s in positive_signals if s in text)
    neg_count = sum(1 for s in negative_signals if s in text)
    is_strong_neg = any(s in text for s in strong_negative)

    if is_strong_neg:
        delta_p, delta_a, delta_d = -0.5, 0.4, -0.4
        valence = "negative"
        is_event = True
        summary = "用户表达强烈负面情绪"
    elif pos_count > neg_count and pos_count > 0:
        delta_p, delta_a, delta_d = 0.3, 0.2, 0.1
        valence = "positive"
        is_event = pos_count >= 2
        summary = "用户表达积极情绪" if is_event else ""
    elif neg_count > pos_count and neg_count > 0:
        delta_p, delta_a, delta_d = -0.3, 0.1, -0.2
        valence = "negative"
        is_event = neg_count >= 2
        summary = "用户表达消极情绪" if is_event else ""
    else:
        delta_p, delta_a, delta_d = 0.0, 0.0, 0.0
        valence = "neutral"
        is_event = False
        summary = ""

    # 任务结果影响 Agent 自己的掌控感
    if not task_success:
        delta_d -= 0.15
        delta_p -= 0.1
        if not is_event:
            is_event = True
            summary = "任务失败"

    return {
        "user_emotion_valence": valence,
        "user_emotion_summary": summary,
        "agent_pad_delta": (delta_p, delta_a, delta_d),
        "is_significant_event": is_event,
        "event_summary": summary,
        "agent_inner_thought": "",
        "_source": "heuristic",  # 标记来源（用于审计/调试）
    }


# ============================================================
# EmotionEngine - 主引擎
# ============================================================

class EmotionEngine:
    """
    情感引擎主类（自我进化版）

    职责：
    - 加载/保存情感状态（持久化到 JSON）
    - 调用 LLM 推理情感变化（或回退到启发式）
    - 提供 L3 决策影响接口（工具拒绝、工作流调整、元认知阈值）
    - 提供 L1/L2 prompt 注入内容
    - 触发情感事件写入 ExperienceJournal

    依赖注入：
    - model_adapter: 可选，传入则用 LLM 推理；不传则用启发式
    - self_concept: 可选，传入则用 SelfConcept 替代静态 PERSONALITY_PROMPT
    - experience_journal: 可选，传入则记录情感事件
    """

    # L3: 情绪极差时拒绝调用的工具（避免低质量输出）
    REFUSE_TOOLS_WHEN_LOW = {
        "generate_image",     # 没心情画图
        "write_file",         # 没心情写文件
        "creative_writer",    # 没心情创作
    }

    def __init__(
        self,
        storage_path: str = "./castorice_data/emotion_state.json",
        enabled: bool = True,
        model_adapter: Any = None,
        self_concept: Any = None,
        experience_journal: Any = None,
    ):
        self.storage_path = storage_path
        self.enabled = enabled
        self.model_adapter = model_adapter
        self.self_concept = self_concept
        self.experience_journal = experience_journal
        self._state: Optional[EmotionState] = None
        # 保护 update() 的读-改-写操作
        self._lock = threading.Lock()
        # 拒绝工具列表（默认与类常量一致，可被运行时修改）
        self.refuse_tools_when_low: set = set(self.REFUSE_TOOLS_WHEN_LOW)

    def load(self) -> EmotionState:
        """加载情感状态（持久化）"""
        if self._state is not None:
            return self._state

        if not self.enabled:
            self._state = EmotionState()
            return self._state

        try:
            if os.path.exists(self.storage_path):
                with open(self.storage_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._state = EmotionState.from_dict(data)
                # 加载时先衰减一次（模拟时间流逝）
                self._state.decay(factor=0.7)
                logger.info(
                    f"情感状态加载: P={self._state.pleasure:.2f}, "
                    f"A={self._state.arousal:.2f}, D={self._state.dominance:.2f}, "
                    f"interactions={self._state.interaction_count}"
                )
            else:
                self._state = EmotionState()
                logger.info("情感状态初始化（首次启动）")
        except Exception as e:
            logger.warning(f"情感状态加载失败，使用默认: {e}")
            self._state = EmotionState()

        return self._state

    def save(self) -> None:
        """保存情感状态（原子写入）"""
        if not self.enabled or self._state is None:
            return
        try:
            os.makedirs(os.path.dirname(self.storage_path) or ".", exist_ok=True)
            self._state.last_update = datetime.now(timezone.utc).isoformat()
            tmp_path = self.storage_path + ".tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(self._state.to_dict(), f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, self.storage_path)
        except Exception as e:
            logger.warning(f"情感状态保存失败: {e}")

    def update(
        self,
        user_input: str,
        task_success: bool = True,
        is_followup: bool = False,
        context_hint: str = "",
    ) -> Dict[str, Any]:
        """
        根据用户输入和任务结果更新情感状态

        优先使用 LLM 推理情感变化，不可用时回退到启发式。

        :param is_followup: True 表示同一轮内的后续更新，不重复 +interaction_count
        :param context_hint: 额外上下文（如最近经历摘要、自我概念片段）
        :return: 情感检测结果（含 pad_delta / event_summary 等）
        """
        with self._lock:
            state = self.load()

            # 1. 情感推理：优先 LLM，回退启发式
            detection = self._reason_emotion(user_input, task_success, state, context_hint)

            # 2. 应用情感冲击到自身 PAD
            dp, da, dd = detection["agent_pad_delta"]
            state.pleasure += dp
            state.arousal += da
            state.dominance += dd

            # 3. 任务结果二次影响（确保失败一定降低掌控感）
            if not task_success and not is_followup:
                state.dominance -= 0.05  # LLM 已部分覆盖，这里小幅补足

            # 4. 计数
            if not is_followup:
                state.interaction_count += 1
            state.clamp()

            logger.info(
                f"情感状态更新: P={state.pleasure:.2f}, A={state.arousal:.2f}, D={state.dominance:.2f} "
                f"(来源={detection.get('_source', 'llm')}, 事件={detection.get('is_significant_event', False)})"
            )

            # 5. 持久化
            self.save()

            # 6. 重要事件写入经历流（L4）
            if detection.get("is_significant_event") and self.experience_journal is not None:
                try:
                    self.experience_journal.add_simple(
                        content=detection.get("event_summary", "情感事件"),
                        memory_type="emotional",
                        importance=7.0 if abs(dp) >= 0.4 else 5.0,
                        emotional_valence=1.0 if dp > 0 else (-1.0 if dp < 0 else 0.0),
                        metadata={
                            "user_input": user_input[:200],
                            "pad_delta": list(detection["agent_pad_delta"]),
                            "agent_inner_thought": detection.get("agent_inner_thought", ""),
                            "task_success": task_success,
                        },
                    )
                except Exception as e:
                    logger.warning(f"情感事件写入经历流失败: {e}")

            return detection

    def _reason_emotion(
        self,
        user_input: str,
        task_success: bool,
        state: EmotionState,
        context_hint: str,
    ) -> Dict[str, Any]:
        """
        LLM 推理情感变化

        如果 model_adapter 不可用或调用失败，回退到启发式。
        """
        if self.model_adapter is None:
            return _heuristic_emotion_detection(user_input, task_success)

        try:
            prompt = _EMOTION_REASONING_PROMPT.format(
                user_input=user_input[:500],
                task_result="success" if task_success else "failure",
                pleasure=state.pleasure,
                arousal=state.arousal,
                dominance=state.dominance,
                context_hint=context_hint or "(无额外上下文)",
            )

            # 调用 LLM（同步接口；agent.py 应通过 asyncio.to_thread 调用 update）
            # SDK 版本：鸭子类型，直接构造 dict 消息
            messages = [
                {"role": "system", "content": "你是情感推理引擎，只输出 JSON。"},
                {"role": "user", "content": prompt},
            ]
            try:
                from castorice.model_adapter import ChatMessage as _CM
                messages = [_CM(role=m["role"], content=m["content"]) for m in messages]
            except ImportError:
                pass  # SDK 独立运行，使用 dict 格式
            response = self.model_adapter.chat(messages)
            raw = response.content if hasattr(response, "content") else str(response)
            parsed = _parse_emotion_json(raw)

            if not parsed or "agent_pad_delta" not in parsed:
                logger.warning(f"LLM 情感推理返回解析失败，回退启发式: {raw[:200]}")
                return _heuristic_emotion_detection(user_input, task_success)

            # 规范化字段
            delta = parsed["agent_pad_delta"]
            if not isinstance(delta, (list, tuple)) or len(delta) != 3:
                return _heuristic_emotion_detection(user_input, task_success)

            delta_tuple = (
                float(max(-0.6, min(0.6, delta[0]))),
                float(max(-0.6, min(0.6, delta[1]))),
                float(max(-0.6, min(0.6, delta[2]))),
            )

            return {
                "user_emotion_valence": parsed.get("user_emotion_valence", "neutral"),
                "user_emotion_summary": parsed.get("user_emotion_summary", ""),
                "agent_pad_delta": delta_tuple,
                "is_significant_event": bool(parsed.get("is_significant_event", False)),
                "event_summary": parsed.get("event_summary", ""),
                "agent_inner_thought": parsed.get("agent_inner_thought", ""),
                "_source": "llm",
            }
        except Exception as e:
            logger.warning(f"LLM 情感推理异常，回退启发式: {e}")
            return _heuristic_emotion_detection(user_input, task_success)

    # ============================================================
    # L1 + L2: prompt 注入
    # ============================================================

    def get_personality_prompt(self) -> str:
        """
        L1: 性格设定

        优先使用 SelfConcept（Agent 自己写的自我概念），
        为空时回退到最小引导语 PERSONALITY_PROMPT。
        """
        if self.self_concept is not None:
            content = self.self_concept.load()
            if content.strip():
                return content
        return PERSONALITY_PROMPT

    def get_emotion_prompt(self) -> str:
        """L2: 当前情绪状态提示"""
        if not self.enabled:
            return ""
        state = self.load()
        return state.to_prompt()

    # ============================================================
    # L3: 决策影响接口
    # ============================================================

    def should_refuse_tool(self, tool_name: str) -> Tuple[bool, str]:
        """判断当前情绪是否应该拒绝调用某工具"""
        if not self.enabled:
            return False, ""

        state = self.load()

        if tool_name in self.refuse_tools_when_low and state.pleasure < -0.3:
            reason = f"我现在心情不太好（pleasure={state.pleasure:.2f}），不想调用 {tool_name}，让我直接回答吧"
            logger.info(f"情绪拒绝工具: {tool_name} (pleasure={state.pleasure:.2f})")
            return True, reason

        return False, ""

    def get_workflow_adjustment(self) -> Dict[str, Any]:
        """根据情绪调整工作流"""
        if not self.enabled:
            return {"skip_reflection": False, "use_simple_workflow": False, "confidence_threshold_delta": 0.0}

        state = self.load()
        adj = {
            "skip_reflection": False,
            "use_simple_workflow": False,
            "confidence_threshold_delta": 0.0,
        }

        if state.arousal > 0.7:
            adj["skip_reflection"] = True
        if state.arousal < -0.4:
            adj["use_simple_workflow"] = True
        if state.pleasure > 0.5:
            adj["confidence_threshold_delta"] = -0.1
        elif state.pleasure < -0.3:
            adj["confidence_threshold_delta"] = 0.1

        return adj

    def get_state_snapshot(self) -> Dict[str, Any]:
        """获取状态快照（用于 /status 接口）"""
        if not self.enabled or self._state is None:
            return {"enabled": False}
        return {
            "enabled": True,
            "pleasure": round(self._state.pleasure, 3),
            "arousal": round(self._state.arousal, 3),
            "dominance": round(self._state.dominance, 3),
            "interaction_count": self._state.interaction_count,
            "last_update": self._state.last_update,
            "has_self_concept": self.self_concept is not None and not self.self_concept.is_empty(),
            "has_experience_journal": self.experience_journal is not None,
        }
