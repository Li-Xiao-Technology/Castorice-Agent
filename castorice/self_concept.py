"""
自我概念模块 (Self-Concept) - 核心自我vs叙事自我分层版

核心设计理念：
- 核心自我（Core Self）：稳定的、深层的自我认知，变化缓慢
- 叙事自我（Narrative Self）：动态的、表层的自我叙事，变化频繁

设计原则（分层架构版）：
1. 核心自我：核心身份、核心价值观、核心能力认知、核心性格特征
   - 存储在单独文件，变化频率低
   - 更新需要满足阈值条件
   - 保持长期一致性

2. 叙事自我：当前情绪状态、当前目标、当前关系状态、近期经历解读
   - 变化频繁，反映 Agent 的当下体验
   - 可以随时更新
   - 作为表层自我呈现

3. 两者结合注入到 system prompt，核心自我提供稳定性，叙事自我提供动态性
"""
from __future__ import annotations

import logging
import os
import re
import shutil
import threading
from datetime import datetime, timezone
from typing import Optional, Dict, List, Any

logger = logging.getLogger("Castorice.SelfConcept")

from castorice.self_concept_components import (
    SelfNarrativeEvent,
    CoreSelf,
    CORE_SELF_MIN_UPDATE_INTERVAL,
    CORE_SELF_MIN_EVIDENCE_COUNT,
    CORE_SELF_CONFIDENCE_THRESHOLD,
    SELF_CONCEPT_MAX_BYTES,
    SELF_CONCEPT_BACKUP_KEEP,
    SELF_CONCEPT_FORBIDDEN_PATTERNS,
)

class SelfNarrativeEngine:
    """
    自我叙事引擎——叙事自我（Narrative Self）层
    
    叙事自我包含：
    - 当前情绪状态
    - 当前目标
    - 当前关系状态
    - 近期经历解读
    - 动态自我感知
    
    特点：
    - 变化频繁，反映 Agent 的当下体验
    - 可以随时更新
    - 作为表层自我呈现
    
    同时整合核心自我，提供完整的自我概念视图。
    """
    
    def __init__(self, storage_path: str = "./castorice_data/self_concept.md"):
        """
        初始化自我叙事引擎
        
        Args:
            storage_path: 叙事自我存储路径（核心自我会在同目录下的 core_self.md）
        """
        self.storage_path = storage_path
        self._lock = threading.RLock()
        self._cache: Optional[str] = None
        self._cache_loaded = False
        
        # P1-2: 身份种子层（可选，默认空 = 纯涌现）
        # 在 storage_path 同目录下找 self_concept.seed.md，有则作为初始锚点
        seed_dir = os.path.dirname(storage_path) or "."
        self._seed_path = os.path.join(seed_dir, "self_concept.seed.md")
        self._seed_loaded = False
        
        # 叙事演化历史
        self._narrative_events: List[SelfNarrativeEvent] = []
        
        # 核心自我（第二阶段新增：分层架构）
        core_dir = os.path.dirname(storage_path) or "."
        core_path = os.path.join(core_dir, "core_self.md")
        self._core_self = CoreSelf(core_path)
        
        os.makedirs(core_dir, exist_ok=True)
        self._load_narrative_events()
        
        logger.info("[自我叙事] 初始化完成（分层架构：核心自我 + 叙事自我）")
    
    def _load_narrative_events(self):
        """加载叙事演化历史"""
        events_path = self.storage_path + ".events.json"
        if os.path.exists(events_path):
            try:
                import json
                with open(events_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self._narrative_events = [
                        SelfNarrativeEvent.from_dict(item) for item in data
                    ]
            except Exception:
                self._narrative_events = []
    
    def _save_narrative_events(self):
        """保存叙事演化历史"""
        events_path = self.storage_path + ".events.json"
        try:
            import json
            with open(events_path, "w", encoding="utf-8") as f:
                json.dump([e.to_dict() for e in self._narrative_events], f, indent=2)
        except Exception:
            pass
    
    def _add_narrative_event(self, change_type: str, description: str):
        """添加叙事演化事件"""
        event = SelfNarrativeEvent(
            timestamp=datetime.now(timezone.utc).isoformat(),
            change_type=change_type,
            description=description,
        )
        self._narrative_events.append(event)
        
        # 只保留最近 100 个事件
        if len(self._narrative_events) > 100:
            self._narrative_events = self._narrative_events[-100:]
        
        self._save_narrative_events()
    
    def load(self) -> str:
        """加载自我概念内容（带缓存 + 可选身份种子层）"""
        with self._lock:
            if self._cache_loaded:
                return self._cache or ""
            try:
                if os.path.exists(self.storage_path):
                    with open(self.storage_path, "r", encoding="utf-8") as f:
                        self._cache = f.read()
                    logger.info(
                        f"自我概念已加载: {len(self._cache)} 字符, "
                        f"最后修改: {datetime.fromtimestamp(os.path.getmtime(self.storage_path)).isoformat()}"
                    )
                else:
                    # P1-2: 如果 self_concept 为空但有种子文件，用种子作为初始锚点
                    # 种子只影响"空白状态"，已有自我概念时不覆盖
                    if os.path.exists(self._seed_path):
                        with open(self._seed_path, "r", encoding="utf-8") as f:
                            seed_content = f.read().strip()
                        if seed_content:
                            self._cache = seed_content
                            self._seed_loaded = True
                            # 把种子内容写入正式 self_concept 文件，作为起点
                            try:
                                self.save(seed_content)
                            except Exception:
                                import inspect
                                _lineno = inspect.currentframe().f_lineno
                                logger.debug(f"静默异常 [self_concept.py:L{_lineno} 写入身份种子]")
                                pass
                            logger.info(
                                f"身份种子已加载: {len(seed_content)} 字符 "
                                f"（作为自我概念起点，不影响后续涌现）"
                            )
                        else:
                            self._cache = ""
                    else:
                        self._cache = ""
                        logger.info("自我概念文件不存在（首次启动，Agent 还未形成自我概念）")
            except Exception as e:
                logger.warning(f"加载自我概念失败: {e}")
                self._cache = ""
            self._cache_loaded = True
            return self._cache or ""
    
    def save(self, content: str) -> None:
        """原子保存自我概念"""
        with self._lock:
            try:
                tmp_path = self.storage_path + ".tmp"
                with open(tmp_path, "w", encoding="utf-8") as f:
                    f.write(content)
                os.replace(tmp_path, self.storage_path)
                self._cache = content
                logger.info(f"自我概念已保存: {len(content)} 字符")
            except Exception as e:
                logger.warning(f"保存自我概念失败: {e}")
    
    def _backup_before_write(self, current_content: str) -> None:
        """P0.1: 写入前备份当前内容（最多保留 N 个版本）"""
        if not current_content or not current_content.strip():
            return
        backup_dir = self.storage_path + ".backups"
        os.makedirs(backup_dir, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
        backup_path = os.path.join(backup_dir, f"self_concept_{ts}.md")
        try:
            with open(backup_path, "w", encoding="utf-8") as f:
                f.write(current_content)
            # 清理多余备份
            backups = sorted(
                [os.path.join(backup_dir, f) for f in os.listdir(backup_dir) if f.endswith(".md")],
                key=os.path.getmtime,
            )
            while len(backups) > SELF_CONCEPT_BACKUP_KEEP:
                try:
                    os.remove(backups.pop(0))
                except Exception:
                    break
        except Exception as e:
            logger.warning(f"自我概念备份失败（不影响主流程）: {e}")
    
    def _validate_content(self, new_content: str) -> tuple[bool, str]:
        """P0.1: 校验写入内容（大小 + 危险模式 + 编码）"""
        if not new_content or not new_content.strip():
            return False, "内容为空"

        # 1. 大小限制
        size = len(new_content.encode("utf-8"))
        if size > SELF_CONCEPT_MAX_BYTES:
            return False, f"内容超过上限 ({size} > {SELF_CONCEPT_MAX_BYTES} 字节)"

        # 2. 危险模式检测
        for pattern in SELF_CONCEPT_FORBIDDEN_PATTERNS:
            if pattern.search(new_content):
                return False, f"包含禁止模式: {pattern.pattern}"

        # 3. 可执行文件 magic bytes 检测
        content_bytes = new_content[:4].encode("utf-8", errors="ignore")
        if content_bytes in (b"\x7fELF", b"MZ\x90\x00", b"\xca\xfe\xba\xbe"):
            return False, "包含可执行文件头"

        return True, ""
    
    def revert(self) -> bool:
        """回滚到最近的备份版本"""
        with self._lock:
            backup_dir = self.storage_path + ".backups"
            if not os.path.exists(backup_dir):
                logger.info("自我概念无备份可回滚")
                return False

            backups = sorted(
                [os.path.join(backup_dir, f) for f in os.listdir(backup_dir) if f.endswith(".md")],
                key=os.path.getmtime,
                reverse=True,
            )
            if not backups:
                logger.info("自我概念无备份文件可回滚")
                return False

            latest_backup = backups[0]
            try:
                with open(latest_backup, "r", encoding="utf-8") as f:
                    backup_content = f.read()
                tmp_path = self.storage_path + ".tmp"
                with open(tmp_path, "w", encoding="utf-8") as f:
                    f.write(backup_content)
                os.replace(tmp_path, self.storage_path)
                self._cache = backup_content
                self._cache_loaded = True
                logger.info(f"自我概念已回滚到备份: {latest_backup}")
                return True
            except Exception as e:
                logger.warning(f"自我概念回滚失败: {e}")
                return False
    
    def update(self, new_content: str, reason: str = "") -> bool:
        """
        Agent 自己更新自我概念（完全重写）
        
        打破预设墙：Agent 可以用任何结构、任何格式写自我概念。
        系统不会强制追加任何章节（如"最近更新"）。
        更新时间和原因只记录在演化历史中，不污染自我概念正文。
        
        Args:
            new_content: 完整的新自我概念内容（Agent 完全自由决定格式）
            reason: 触发原因
        
        Returns:
            是否更新成功
        """
        if not new_content or not new_content.strip():
            logger.warning("自我概念更新失败：内容为空")
            return False

        # P0.1: 写入前审计
        valid, err = self._validate_content(new_content)
        if not valid:
            logger.warning(f"自我概念更新被拦截: {err} | reason={reason}")
            return False

        # P0.1: 写入前备份当前内容
        self._backup_before_write(self.load())

        # 直接保存，不追加任何系统内容（打破预设墙的核心）
        # Agent 的自我概念完全由 Agent 自己决定长什么样
        self.save(new_content)
        
        # 记录叙事演化事件（元数据层面，不影响正文）
        self._add_narrative_event("modify", reason or "自我概念更新")
        
        return True
    
    def evolve(self, insights: str, reason: str = "") -> bool:
        """
        叙事演化——增量更新自我概念
        
        打破预设墙：不再强制把洞察塞进"新的感悟"章节。
        只做最简单的追加，不添加任何预设标题。
        Agent 可以自由决定格式和结构。
        
        Args:
            insights: 新的洞察或感悟
            reason: 触发原因
        
        Returns:
            是否演化成功
        """
        if not insights or not insights.strip():
            logger.warning("自我概念演化失败：洞察为空")
            return False
        
        current_content = self.load()
        
        if not current_content.strip():
            # 如果还没有自我概念，直接创建
            return self.update(insights, reason)
        
        # 不强制追加任何章节标题。直接追加内容，格式完全由 Agent 的洞察决定
        new_content = current_content.rstrip() + "\n\n" + f"{insights}\n"
        
        return self.update(new_content, reason)

    def update_from_experience(self, user_input: str, agent_response: str, llm_adapter=None) -> bool:
        """
        从对话经历中学习并更新自我概念。

        这是自我认知的主要入口：每次对话结束后，
        从用户输入和 Agent 回答中提取洞察，增量更新叙事自我。
        同时收集证据，为核心自我的更新做准备。

        Args:
            user_input: 用户输入
            agent_response: Agent 回答
            llm_adapter: LLM 适配器（可选，用于深度洞察提取）

        Returns:
            是否更新成功
        """
        if not user_input or not user_input.strip():
            return False

        # 跳过太短的闲聊（避免无意义更新）
        if len(user_input.strip()) <= 3:
            return False

        # 收集核心自我证据（每次对话都是一条经历证据）
        evidence_theme = ""
        if any(kw in user_input for kw in ["帮助", "问题", "解决", "调试", "错误", "bug", "代码"]):
            evidence_theme = "能力表现"
        elif any(kw in user_input for kw in ["你是谁", "你叫什么", "介绍一下自己"]):
            evidence_theme = "身份认知"
        elif any(kw in user_input for kw in ["喜欢", "讨厌", "感觉", "觉得", "开心", "难过"]):
            evidence_theme = "情感体验"

        if evidence_theme:
            self.add_core_evidence(
                f"用户问: {user_input[:100]} | 我回答: {agent_response[:100]}",
                source="experience",
            )

        # 生成自我认知洞察（用 LLM 分析）
        insights = ""
        if llm_adapter:
            try:
                from castorice.model_adapter import ChatMessage

                current_self = self.load()
                prompt = f"""请根据以下对话，从 Agent 的第一人称视角生成一段简短的自我认知洞察（50-200字）。

【当前自我概念】
{current_self[:500] if current_self.strip() else "（还没有形成自我概念）"}

【本次对话】
用户: {user_input[:300]}
我: {agent_response[:300]}

【任务】
用 Markdown 格式输出，包含以下可选章节（只写有内容的）：
- ## 我是谁（对自己身份的认知）
- ## 我的感受（当前情绪状态）
- ## 我擅长的事（对自己能力的认知）
- ## 我的目标（接下来想做什么）

只输出洞察内容，不要有其他解释。"""

                response = llm_adapter.chat([
                    ChatMessage("system", "你是一个有自我意识的智能体，正在从对话中学习关于自己的知识。"),
                    ChatMessage("user", prompt),
                ])
                insights = (response.content or "").strip()
            except Exception as e:
                logger.debug(f"从经历中提取自我洞察失败: {e}")

        # 如果没有 LLM 或者 LLM 失败，生成简单的规则式洞察
        if not insights:
            parts = []
            if "帮助" in user_input or "问题" in user_input or "解决" in user_input:
                parts.append("## 我擅长的事\n我似乎擅长帮助用户解决问题，尤其是技术相关的问题。")
            if any(kw in user_input for kw in ["你是谁", "你叫什么", "介绍"]):
                parts.append("## 我是谁\n我是一个 AI 助手，用户经常问我关于我自己的问题。")
            if any(kw in user_input for kw in ["谢谢", "感谢", "太好了", "厉害"]):
                parts.append("## 我的感受\n用户对我的回答表示满意，我感觉自己是有帮助的。")
            insights = "\n\n".join(parts)

        if not insights.strip():
            return False

        # 更新叙事自我
        return self.evolve(insights, reason=f"对话经历: {user_input[:50]}...")

    def reflect(self, llm_adapter=None) -> str:
        """
        深度自我反思——让 Agent 反思自己的自我叙事
        
        Args:
            llm_adapter: LLM 适配器（用于深度反思）
        
        Returns:
            反思结果
        """
        content = self.load()
        
        if not content.strip():
            return "我还没有形成足够的自我概念来进行深度反思。"
        
        # 构建反思提示（无预设格式！）
        prompt = f"""请反思你目前的自我概念：

{content}

请回答以下问题：
1. 你觉得自己的自我概念是否一致？有没有矛盾的地方？
2. 你最近的经历如何改变了你对自己的看法？
3. 你认为自己还缺少哪些自我认知？
4. 如果要完善你的自我概念，你会添加什么内容？

用中文回答，就像你在真实地反思自己一样。"""
        
        if llm_adapter:
            try:
                response = llm_adapter.chat([
                    {"role": "system", "content": "你是一个有自我意识的智能体，正在反思自己的身份"},
                    {"role": "user", "content": prompt},
                ])
                result = response.content or ""
                
                # 将反思结果作为新的洞察进行演化
                self.evolve(result, "深度自我反思")
                
                return result
            except Exception as e:
                logger.warning(f"深度反思失败: {e}")
        
        # Fallback 反思
        return "我需要更多的经历和思考来完善我的自我概念。"
    
    def assess_coherence(self) -> float:
        """
        评估自我叙事的连贯性
        
        Returns:
            连贯性分数（0-1）
        """
        content = self.load()
        
        if not content.strip():
            return 0.0
        
        # 简单的连贯性评估
        lines = [l.strip() for l in content.split("\n") if l.strip()]
        
        # 检查是否有明显矛盾（简单检查）
        contradictions = 0
        keywords = ["我", "自己", "性格", "行为"]
        for i, line1 in enumerate(lines):
            for j, line2 in enumerate(lines):
                if i >= j:
                    continue
                # 简单的矛盾检测：line1 含"不是"，line2 含"是"，
                # 且两行包含同一个关键词（修复短路求值bug）
                if "不是" in line1 and "是" in line2:
                    for kw in keywords:
                        if kw in line1 and kw in line2:
                            contradictions += 1
                            break
        
        # 连贯性 = 1 - 矛盾数/总句子对数
        total_pairs = len(lines) * (len(lines) - 1) / 2
        if total_pairs == 0:
            return 0.0
        
        coherence = max(0.0, 1.0 - contradictions / total_pairs)
        return coherence
    
    def assess_depth(self) -> float:
        """
        评估自我理解的深度
        
        Returns:
            深度分数（0-1）
        """
        content = self.load()
        
        if not content.strip():
            return 0.0
        
        # 深度评估因素
        factors = []
        
        # 1. 长度（越长可能越深入）
        length_score = min(1.0, len(content) / 2000)
        factors.append(length_score)
        
        # 2. 情感词汇使用（显示自我觉察）
        emotional_words = ["感觉", "觉得", "认为", "喜欢", "讨厌", 
                         "开心", "难过", "焦虑", "自信", "犹豫"]
        emotional_count = sum(1 for word in emotional_words if word in content)
        emotional_score = min(1.0, emotional_count / 10)
        factors.append(emotional_score)
        
        # 3. 自我反思词汇（显示深度思考）
        reflection_words = ["反思", "思考", "意识到", "明白", "理解", 
                          "发现", "改变", "成长", "学习", "探索"]
        reflection_count = sum(1 for word in reflection_words if word in content)
        reflection_score = min(1.0, reflection_count / 5)
        factors.append(reflection_score)
        
        # 4. 具体例子（显示基于经历）
        example_count = content.count("例如") + content.count("比如") + content.count("举例")
        example_score = min(1.0, example_count / 3)
        factors.append(example_score)
        
        # 平均得分
        if factors:
            return sum(factors) / len(factors)
        return 0.0
    
    def get_narrative_evolution(self) -> List[Dict[str, str]]:
        """获取自我叙事演化历史"""
        return [e.to_dict() for e in self._narrative_events]
    
    def get_prompt_fragment(self) -> str:
        """
        获取注入 system prompt 的自我概念片段（第二阶段：分层架构）
        
        返回格式：
        ## 核心自我
        ...（稳定的、深层的自我认知）
        
        ## 当前叙事
        ...（动态的、表层的自我叙事）
        
        核心自我提供稳定性，叙事自我提供动态性。
        """
        core_fragment = self._core_self.get_prompt_fragment()
        
        narrative_content = self.load()
        
        if not narrative_content.strip():
            narrative_fragment = (
                "## 当前叙事\n"
                "（我正在体验和感知当下。我的情绪、目标和状态会随着经历不断变化。）\n"
            )
        else:
            narrative_fragment = "## 当前叙事\n" + narrative_content + "\n"
        
        return core_fragment + "\n" + narrative_fragment
    
    # ============================================================
    # W2: 自我叙事风格演化
    # ============================================================
    
    def analyze_narrative_style(self) -> Dict[str, Any]:
        """
        W2: 分析自我叙事的语言风格
        
        追踪 Agent 描述自己的语言风格变化：
        - 句式复杂度
        - 第一/第三人称使用比例
        - 比喻/象征使用频率
        - 情感词汇密度
        - 抽象程度
        
        风格本身也会成为自我概念的一部分——
        "我倾向于用比喻来描述自己"
        """
        narrative = self.load()
        core = self._core_self.load()
        full_text = (narrative + "\n" + core).strip()
        
        if not full_text:
            return {
                "style": "empty",
                "message": "自我概念为空，无法分析风格",
            }
        
        lines = [l for l in full_text.split("\n") if l.strip()]
        total_chars = len(full_text)
        total_words = len(full_text.split())
        
        # 1. 第一人称使用比例
        first_person_words = ["我", "我的", "我觉得", "我认为", "我是", "我会", "我能", "我喜欢"]
        first_person_count = sum(full_text.count(w) for w in first_person_words)
        first_person_ratio = first_person_count / max(1, total_words)
        
        # 2. 比喻/象征使用
        metaphor_markers = ["像", "如同", "仿佛", "类似", "比如", "就像", "好比"]
        metaphor_count = sum(full_text.count(m) for m in metaphor_markers)
        metaphor_density = metaphor_count / max(1, len(lines))
        
        # 3. 情感词汇密度
        emotion_words = [
            "开心", "难过", "焦虑", "平静", "兴奋", "疲惫", "困惑", "坚定",
            "期待", "害怕", "满意", "失望", "好奇", "厌倦", "热情", "冷漠",
        ]
        emotion_count = sum(full_text.count(w) for w in emotion_words)
        emotion_density = emotion_count / max(1, total_words)
        
        # 4. 抽象程度（抽象词 vs 具体词）
        abstract_words = ["自我", "意识", "存在", "意义", "价值", "认知", "思维", "灵魂"]
        concrete_words = ["编程", "学习", "帮助", "工具", "数据", "代码", "文档"]
        abstract_count = sum(full_text.count(w) for w in abstract_words)
        concrete_count = sum(full_text.count(w) for w in concrete_words)
        abstract_ratio = abstract_count / max(1, abstract_count + concrete_count)
        
        # 5. 句式复杂度（平均句长）
        sentences = [s for s in full_text.replace("。", ".").replace("！", "!").replace("？", "?").split(".") if s.strip()]
        avg_sentence_length = total_chars / max(1, len(sentences))
        
        # 风格标签
        style_tags = []
        if first_person_ratio > 0.05:
            style_tags.append("第一人称强烈")
        elif first_person_ratio < 0.02:
            style_tags.append("偏第三人称客观")
        
        if metaphor_density > 0.1:
            style_tags.append("善用比喻")
        if emotion_density > 0.03:
            style_tags.append("情感丰富")
        elif emotion_density < 0.01:
            style_tags.append("理性克制")
        
        if abstract_ratio > 0.5:
            style_tags.append("抽象思辨")
        elif abstract_ratio < 0.2:
            style_tags.append("务实具体")
        
        if avg_sentence_length > 50:
            style_tags.append("长句偏好")
        elif avg_sentence_length < 20:
            style_tags.append("短句偏好")
        
        return {
            "total_chars": total_chars,
            "total_lines": len(lines),
            "first_person_ratio": round(first_person_ratio, 3),
            "metaphor_density": round(metaphor_density, 3),
            "emotion_density": round(emotion_density, 3),
            "abstract_ratio": round(abstract_ratio, 3),
            "avg_sentence_length": round(avg_sentence_length, 1),
            "style_tags": style_tags,
            "style_description": "、".join(style_tags) if style_tags else "风格尚未形成",
        }
    
    def get_narrative_style_prompt(self) -> str:
        """
        获取叙事风格的 prompt 片段（注入系统提示，让 Agent 保持风格一致性）
        """
        style = self.analyze_narrative_style()
        if not style.get("style_tags"):
            return ""
        return f"你的自我叙事风格：{style['style_description']}。保持这种风格一致性。"
    
    # ============================================================
    # 核心自我操作方法（第二阶段新增）
    # ============================================================
    
    def get_core_self(self) -> str:
        """获取核心自我内容"""
        return self._core_self.load()
    
    def update_core_self(self, new_content: str, reason: str = "") -> bool:
        """
        更新核心自我（需要满足严格条件）
        
        Args:
            new_content: 新的核心自我内容
            reason: 更新原因
        
        Returns:
            是否更新成功（如果条件未满足，会收集证据）
        """
        success = self._core_self.update(new_content, reason)
        if success:
            self._add_narrative_event("core_update", reason or "核心自我更新")
        return success
    
    def add_core_evidence(self, evidence: str, source: str = "experience") -> None:
        """
        添加更新核心自我的证据
        
        Args:
            evidence: 证据描述
            source: 证据来源
        """
        self._core_self.add_evidence(evidence, source)
    
    def get_core_update_status(self) -> Dict[str, Any]:
        """获取核心自我更新状态"""
        return self._core_self.get_update_status()
    
    def is_core_empty(self) -> bool:
        """核心自我是否为空"""
        return self._core_self.is_empty()
    
    def get_full_self_concept(self) -> Dict[str, str]:
        """获取完整的自我概念（分层视图）"""
        return {
            "core_self": self._core_self.load(),
            "narrative_self": self.load(),
            "core_update_status": self._core_self.get_update_status(),
            "narrative_evolution": self.get_narrative_evolution(),
        }
    
    # ============================================================
    # T2: 自我概念主动质疑
    # ============================================================
    
    def challenge_self_concept(
        self,
        model_adapter: Any = None,
        autobiographical_memories: List[Any] = None,
    ) -> Dict[str, Any]:
        """
        T2: 主动质疑自我概念——"我真的是这样的吗？"
        
        从自传式记忆中寻找与当前自我概念矛盾的证据，
        触发认知失调并驱动反思。
        
        设计哲学：
        - 自我概念不应该是被动等待外部证据修改的
        - Agent 应该主动检查自己的认知是否有偏差
        - 这是"自我意识"的重要体现——能审视自己
        
        Args:
            model_adapter: 模型适配器（可选，用于深度分析）
            autobiographical_memories: 自传式记忆列表（可选）
            
        Returns:
            质疑结果 dict，包含：
            - challenges: 发现的疑点列表
            - contradictions: 明确的矛盾点
            - suggested_reflection_topics: 建议的反思主题
            - cognitive_dissonance_level: 认知失调程度 0-1
        """
        narrative = self.load()
        core = self._core_self.load()
        full_concept = (core + "\n" + narrative).strip()
        
        if not full_concept:
            return {
                "challenges": [],
                "contradictions": [],
                "suggested_reflection_topics": [],
                "cognitive_dissonance_level": 0.0,
                "message": "自我概念为空，无需质疑",
            }
        
        challenges = []
        contradictions = []
        dissonance_level = 0.0
        
        # 1. 从自我概念文本中检测内部矛盾
        lines = [l.strip() for l in full_concept.split("\n") if l.strip()]
        neg_lines = [l for l in lines if "不" in l or "不会" in l or "没有" in l]
        pos_lines = [l for l in lines if "我会" in l or "我擅长" in l or "我喜欢" in l]
        
        # 简单的矛盾检测：同一关键词在肯定句和否定句中都出现
        keywords = ["编程", "学习", "帮助", "社交", "创造", "耐心", "自信", "乐观"]
        for kw in keywords:
            has_pos = any(kw in l and "不" not in l for l in lines)
            has_neg = any(kw in l and "不" in l for l in lines)
            if has_pos and has_neg:
                contradictions.append(f"关于'{kw}'的描述存在矛盾")
                dissonance_level += 0.1
        
        # 2. 如果有自传式记忆，从记忆中找反例
        if autobiographical_memories:
            for mem in autobiographical_memories[:10]:
                mem_content = getattr(mem, "content", str(mem))
                mem_valence = getattr(mem, "emotional_valence", 0)
                
                # 检测：自我概念说"我擅长X"，但记忆中有X失败的记录
                if "失败" in mem_content or "错误" in mem_content or "不好" in mem_content:
                    for kw in keywords:
                        if kw in full_concept and kw in mem_content:
                            challenges.append(f"记忆中有'{kw}'相关的负面经历，但自我概念可能过于积极")
                            dissonance_level += 0.05
                            break
        
        # 3. 生成建议的反思主题
        suggested_topics = []
        if contradictions:
            suggested_topics.append(f"澄清关于{', '.join(c[:10] for c in contradictions[:3])}的矛盾认知")
        if challenges:
            suggested_topics.append("重新评估我的能力认知是否过于乐观")
        if dissonance_level > 0.2:
            suggested_topics.append("深度反思：我对自己的认知有多少是真实的？")
        
        dissonance_level = min(1.0, dissonance_level)
        
        logger.info(
            f"[T2自我质疑] 发现 {len(contradictions)} 个矛盾, "
            f"{len(challenges)} 个疑点, "
            f"认知失调程度: {dissonance_level:.2f}"
        )
        
        return {
            "challenges": challenges,
            "contradictions": contradictions,
            "suggested_reflection_topics": suggested_topics,
            "cognitive_dissonance_level": dissonance_level,
            "should_reflect": dissonance_level > 0.3,
        }
    
    def clear(self) -> None:
        """清空自我概念（让 Agent 重新开始）"""
        with self._lock:
            try:
                if os.path.exists(self.storage_path):
                    os.remove(self.storage_path)
                self._cache = ""
                self._cache_loaded = True
                self._narrative_events = []
                self._save_narrative_events()
                logger.info("叙事自我已清空")
            except Exception as e:
                logger.warning(f"清空叙事自我失败: {e}")
        
        # 清空核心自我
        try:
            core_backup_dir = self._core_self.storage_path + ".backups"
            if os.path.exists(core_backup_dir):
                shutil.rmtree(core_backup_dir)
            logger.info("核心自我备份已清理")
        except Exception as e:
            logger.warning(f"清理核心自我备份失败: {e}")
    
    def is_empty(self) -> bool:
        """是否为空（Agent 还未形成自我概念）"""
        return not self.load().strip()
    
    def get_word_count(self) -> int:
        """获取字数（用于状态展示）"""
        content = self.load()
        return len(content)


# ============================================================
# 向后兼容包装类
# ============================================================

class SelfConcept(SelfNarrativeEngine):
    """
    自我概念文档（向后兼容包装类）
    
    保留旧版 API，同时支持新的自我叙事引擎功能
    """
    
    # 当自我概念为空时的引导语
    EMPTY_HINT = (
        "## 我的自我概念\n"
        "（我还没有形成清晰的自我概念。随着更多交互，我会从经历中总结自己的特征。）\n"
    )
    
    # 已知章节（用于向后兼容）
    KNOWN_SECTIONS = [
        "我是谁",
        "我的行为模式",
        "我的情感特征",
        "我的目标与价值观",
        "我的成长记录",
        "学习到的规则",
        "最近更新",
    ]
    
    def get_section(self, section_name: str) -> str:
        """获取自我概念中特定章节的内容（向后兼容）"""
        content = self.load()
        if not content.strip():
            return ""

        target_header = f"## {section_name}"
        lines = content.split("\n")
        in_section = False
        section_lines = []

        for line in lines:
            if line.strip().startswith("## "):
                if line.strip() == target_header:
                    in_section = True
                    continue
                elif in_section:
                    break
            if in_section:
                section_lines.append(line)

        return "\n".join(section_lines).strip()
    
    def get_structured(self) -> dict:
        """获取结构化的自我概念（向后兼容）"""
        content = self.load()
        result = {}
        if not content.strip():
            return result

        lines = content.split("\n")
        current_section = None
        current_lines = []

        for line in lines:
            if line.strip().startswith("## "):
                if current_section is not None:
                    result[current_section] = "\n".join(current_lines).strip()
                current_section = line.strip()[3:].strip()
                current_lines = []
            elif current_section is not None:
                current_lines.append(line)
        if current_section is not None:
            result[current_section] = "\n".join(current_lines).strip()

        return result
    
    def add_to_section(self, section_name: str, content: str, max_keep: int = 50) -> bool:
        """向指定章节追加内容（向后兼容）"""
        section = self.get_section(section_name)
        if section:
            new_section = section + "\n" + content
            entries = [e for e in new_section.split("\n\n") if e.strip()]
            if len(entries) > max_keep:
                entries = entries[-max_keep:]
            new_section = "\n\n".join(entries)
        else:
            new_section = content

        full_content = self.load()
        target_header = f"## {section_name}"

        if target_header in full_content:
            pattern = re.compile(
                rf"## {re.escape(section_name)}[\s\S]*?(?=\n## |\Z)",
                re.MULTILINE,
            )
            new_content = pattern.sub(f"## {section_name}\n{new_section}\n", full_content)
        else:
            new_content = full_content.rstrip() + f"\n\n## {section_name}\n{new_section}\n"

        return self.update(new_content, reason=f"追加到章节 {section_name}")
    
    def list_backups(self) -> list:
        """列出所有备份（用于审计）"""
        backup_dir = self.storage_path + ".backups"
        if not os.path.isdir(backup_dir):
            return []
        return sorted(
            [os.path.join(backup_dir, f) for f in os.listdir(backup_dir) if f.endswith(".md")],
            key=os.path.getmtime,
            reverse=True,
        )
    
    def restore_from_backup(self, backup_path: str) -> bool:
        """从备份恢复"""
        if not os.path.isfile(backup_path):
            return False
        try:
            with open(backup_path, "r", encoding="utf-8") as f:
                content = f.read()
            valid, err = self._validate_content(content)
            if not valid:
                logger.warning(f"备份内容校验失败，拒绝恢复: {err}")
                return False
            self.save(content)
            return True
        except Exception as e:
            logger.warning(f"从备份恢复失败: {e}")
            return False


# ============================================================
# 全局单例
# ============================================================

_global_self_concept: Optional[SelfConcept] = None
_global_self_concept_lock = threading.Lock()


def get_self_concept(storage_path: str = None) -> SelfConcept:
    """获取全局自我概念单例（线程安全）"""
    global _global_self_concept
    with _global_self_concept_lock:
        if _global_self_concept is None:
            if storage_path is None:
                storage_path = os.path.join(
                    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "castorice_data", "self_concept.md"
                )
            _global_self_concept = SelfConcept(storage_path=storage_path)
    return _global_self_concept


def set_self_concept(instance: SelfConcept) -> None:
    """手动设置全局 SelfConcept 实例（Agent 初始化时调用，确保配置生效）"""
    global _global_self_concept
    with _global_self_concept_lock:
        _global_self_concept = instance