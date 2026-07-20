"""
记忆操作模块

记忆归档、反思、技能沉淀、用户画像提取、记忆质量自检。
"""

import asyncio
import logging
import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from castorice.model_adapter import ChatMessage
from castorice.utils import extract_json
from .common import logger, _get_audit_logger, _get_alert_manager


class MemoryOpsMixin:
    """提供 _step_memory、_step_reflection、_step_skill 及记忆相关辅助方法。"""

    # ============================================================
    # 阶段5: 反思
    # ============================================================
    async def _step_reflection(self, state) -> None:
        # 如果配置禁用了反思，跳过
        if not self.enable_reflection:
            return

        # L3: 兴奋时跳过反思（高唤醒 → 反应快，不走深度反思）
        try:
            workflow_adj = self.emotion_engine.get_workflow_adjustment()
            if workflow_adj.get("skip_reflection"):
                logger.info("L3: 当前情绪兴奋(arousal高)，跳过反思步骤")
                state.reflection_summary = "[情绪兴奋，跳过反思]"
                return
        except Exception as e:
            logger.warning(f"L3 反思跳过检查失败: {e}")

        tool_summary = "\n".join(f"- {t['tool_name']}: {t['result'][:200]}" for t in state.tool_calls)

        # 如果配置禁用了技能生成，不请求 LLM 生成技能提案
        skill_prompt = ""
        if self.enable_skill_generation:
            skill_prompt = """,
    "should_generate_skill": true/false,
    "skill_proposal": {
        "name": "技能名", "trigger_keywords": ["kw1"],
        "description": "描述", "steps": [{"tool": "工具名", "参数": "值"}]
    }"""
        else:
            skill_prompt = """,
    "should_generate_skill": false"""

        prompt = f"""复盘以下任务执行，输出 JSON：
{{
    "summary": "复盘总结",
    "suggestions": ["改进建议"]{skill_prompt}
}}

任务: {state.user_input}
错误: {state.errors}
工具调用:
{tool_summary}"""

        try:
            response = await asyncio.to_thread(
                self.model.chat,
                [
                    ChatMessage("system", "你是复盘专家，只输出 JSON。"),
                    ChatMessage("user", prompt),
                ],
            )
            parsed = extract_json(response.content)
            state.reflection_summary = parsed.get("summary", "")
            state.improvement_suggestions = parsed.get("suggestions", [])
            # 只有配置启用技能生成时，才处理技能提案
            if self.enable_skill_generation and parsed.get("should_generate_skill") and parsed.get("skill_proposal", {}).get("name"):
                state.skill_to_generate = parsed["skill_proposal"]

            # P2.4: 元认知从错误中学习（把反思结果转化为规则）
            if hasattr(self, 'metacognition') and state.errors:
                for error in state.errors:
                    try:
                        await asyncio.to_thread(
                            self.metacognition.learn_from_mistake,
                            state.user_input,
                            error,
                            state.reflection_summary,
                        )
                    except Exception as e:
                        logger.debug(f"P2.4 元认知学习失败: {e}")

            # A1: 反思后自动生成自传式时期总结（每10轮触发一次）
            if hasattr(self, 'autobiographical'):
                self._reflection_counter = getattr(self, '_reflection_counter', 0)
                self._reflection_counter += 1
                if self._reflection_counter % 10 == 0:
                    try:
                        current_epoch = self.autobiographical.get_current_epoch()
                        if current_epoch:
                            milestones = self.autobiographical.get_milestones(limit=10)
                            events = self.autobiographical.get_events(limit=10)
                            await asyncio.to_thread(
                                self.autobiographical.summarize_epoch_with_llm,
                                current_epoch,
                                self.model,
                                milestones,
                                events,
                            )
                            logger.info(f"A1 自传式时期总结完成: {current_epoch.name}")
                    except Exception as e:
                        logger.debug(f"A1 自传式时期总结失败: {e}")

        except Exception as e:
            logger.warning(f"反思失败: {e}")

    # ============================================================
    # 阶段6: 记忆归档
    # ============================================================
    async def _step_memory(self, state) -> None:
        try:
            # 记录交互计数（user_profile 之前从未被更新，导致名字等持久信息丢失）
            try:
                await asyncio.to_thread(self.user_profile.record_interaction)
            except Exception as e:
                logger.debug(f"用户画像交互计数失败: {e}")

            # A1: 自传式记忆交互记录（用于时期划分）
            try:
                if hasattr(self, 'autobiographical'):
                    await asyncio.to_thread(self.autobiographical.record_interaction)
                    # 检查是否需要进入新时期
                    new_epoch = await asyncio.to_thread(self.autobiographical.check_epoch_transition)
                    if new_epoch:
                        logger.info(f"A1 进入新时期: {new_epoch.name}")
            except Exception as e:
                logger.debug(f"A1 自传式记忆交互记录失败: {e}")

            # 自动提取用户画像信息（从用户输入中识别名字等关键信息）
            try:
                await self._extract_user_profile(state.user_input)
            except Exception as e:
                logger.debug(f"用户画像提取失败: {e}")

            memory_text = f"用户指令: {state.user_input}\n执行结果: {state.final_answer}"
            if state.reflection_summary:
                memory_text += f"\n反思: {state.reflection_summary}"

            memory_text = self._sanitize_memory_text(memory_text)

            # 记忆写入前验证：判断这条记忆是否值得保存
            should_save = await asyncio.to_thread(
                self._validate_memory_before_write,
                state.user_input, state.final_answer, state.session_id
            )

            if not should_save:
                logger.info(f"记忆验证不通过，跳过写入: {state.user_input[:30]}...")
                return

            # P1-2: long_term.add() 和 short_term.update_summary() 是同步阻塞操作，
            # 用 asyncio.to_thread 避免阻塞事件循环
            await asyncio.to_thread(
                self.long_term.add,
                text=memory_text,
                metadata={
                    "type": "task_summary",
                    "session_id": state.session_id,
                    "success": state.success,
                    "intent": state.intent_type,
                },
            )
            summary = state.user_input[:50] + ("..." if len(state.user_input) > 50 else "")
            await asyncio.to_thread(
                self.short_term.update_summary, state.session_id, summary
            )
        except Exception as e:
            logger.warning(f"长期记忆写入失败: {e}")

    def _sanitize_memory_text(self, memory_text: str) -> str:
        """
        清理记忆文本中的错误信息。

        主要过滤：
        - LLM回复中错误的身份假设（如"你叫XXX"、"你是XXX"）
        - 避免将LLM的猜测当作事实写入记忆
        """
        import re

        current_name = self.user_profile.get("identity.name", "")

        lines = memory_text.split('\n')
        new_lines = []

        for line in lines:
            skip_line = False

            if current_name:
                patterns_to_remove = [
                    rf'你叫\s*{re.escape(current_name)}',
                    rf'你的名字是\s*{re.escape(current_name)}',
                    rf'你的名字叫\s*{re.escape(current_name)}',
                ]
                for pattern in patterns_to_remove:
                    if re.search(pattern, line):
                        skip_line = True
                        break
            else:
                identity_claim_patterns = [
                    r'你叫\s*[A-Za-z\u4e00-\u9fa5][A-Za-z\u4e00-\u9fa5·\s]{0,20}',
                    r'你是\s*[A-Za-z\u4e00-\u9fa5][A-Za-z\u4e00-\u9fa5·\s]{0,20}',
                    r'你的名字是\s*[A-Za-z\u4e00-\u9fa5][A-Za-z\u4e00-\u9fa5·\s]{0,20}',
                    r'你的名字叫\s*[A-Za-z\u4e00-\u9fa5][A-Za-z\u4e00-\u9fa5·\s]{0,20}',
                ]
                for pattern in identity_claim_patterns:
                    if re.search(pattern, line):
                        skip_line = True
                        break

            question_patterns = [
                r'你是谁',
                r'我是谁',
                r'你还记得么',
                r'你认识我吗',
                r'知道我是谁',
                r'还记得我吗',
            ]
            if any(q in line for q in question_patterns):
                skip_line = True

            if not skip_line:
                new_lines.append(line)

        return '\n'.join(new_lines).strip()

    def _validate_memory_before_write(
        self, user_input: str, answer: str, session_id: str
    ) -> bool:
        """
        记忆写入前验证：使用规则匹配判断这条记忆是否值得保存。

        过滤规则：
        - 纯粹的闲聊（如"你好"、"在吗"、"谢谢"）不需要保存
        - 问候语不需要保存
        - 太短的输入不需要保存
        """
        chat_patterns = [
            "你好", "嗨", "hello", "hi", "在吗", "谢谢", "谢谢",
            "再见", "拜拜", "晚安", "早安", "下午好", "晚上好",
        ]

        user_input_lower = user_input.lower().strip()

        if len(user_input_lower) <= 3:
            logger.debug(f"记忆验证: 输入太短，跳过保存")
            return False

        if any(p.lower() in user_input_lower for p in chat_patterns):
            logger.debug(f"记忆验证: 闲聊问候，跳过保存")
            return False

        return True

    async def _reflect_on_memory_quality(self, session_id: str) -> None:
        """
        自我修正：定期检查记忆质量，发现并修正错误记忆。

        每10轮对话触发一次，检查最近的记忆条目是否存在错误或误解。
        """
        from castorice.utils import extract_json

        self._reflection_counter = getattr(self, '_reflection_counter', 0)
        self._reflection_counter += 1

        if self._reflection_counter % 10 != 0:
            return

        logger.info("自我修正: 开始检查记忆质量...")

        try:
            recent_memories = await asyncio.to_thread(
                self.long_term.get_recent, limit=10
            )

            if not recent_memories:
                logger.debug("自我修正: 无近期记忆可检查")
                return

            for memory in recent_memories:
                if isinstance(memory, dict):
                    text = memory.get("text", memory.get("document", ""))
                else:
                    text = str(memory)

                if not text or len(text) < 10:
                    continue

                prompt = f"""你是记忆质量评估器，分析以下记忆是否存在错误或误解。

【记忆内容】
{text}

【分析任务】
1. 判断这条记忆是否存在错误提取（如把疑问句误提取为名字）
2. 判断是否存在误解用户意图的情况
3. 判断是否包含无意义或重复的信息

【输出格式】
只返回JSON：
{{
  "has_error": true/false,
  "error_type": "none/misextraction/misunderstanding/meaningless/redundant",
  "error_description": "错误描述",
  "suggestion": "修正建议（如果有错误）",
  "should_delete": true/false
}}"""

                response = await asyncio.to_thread(
                    self.model.chat,
                    [
                        ChatMessage("system", "你是记忆质量评估器，只输出JSON。"),
                        ChatMessage("user", prompt),
                    ]
                )
                parsed = extract_json(response.content)

                if parsed.get("has_error") and parsed.get("should_delete"):
                    logger.warning(f"自我修正: 发现错误记忆，删除 ({parsed.get('error_type')}: {parsed.get('error_description')})")
                    if isinstance(memory, dict) and "id" in memory:
                        await asyncio.to_thread(self.long_term.delete, memory["id"])

            logger.info("自我修正: 记忆质量检查完成")

        except Exception as e:
            logger.warning(f"自我修正失败: {e}")

    async def _detect_memory_conflict(self, user_input: str) -> Optional[str]:
        """
        记忆冲突检测：当新信息与已有记忆冲突时，返回冲突描述。

        例如：已有名字"张三"，新输入说"我叫李四"，则检测到冲突。
        """
        from castorice.utils import extract_json

        current_name = self.user_profile.get("identity.name", "")
        current_nickname = self.user_profile.get("identity.nickname", "")

        if not current_name and not current_nickname:
            return None

        prompt = f"""检测用户输入与已有记忆是否存在冲突。

【已有记忆】
用户名字: {current_name or '未设置'}
用户昵称: {current_nickname or '未设置'}

【用户输入】
{user_input}

【判断规则】
- 如果用户输入的名字/身份与已有记忆不同，且是明确的身份声明，则存在冲突
- 如果用户只是询问或确认（如"你还记得我吗"），不存在冲突
- 如果用户输入的是职业、爱好等其他信息，不存在冲突

【输出格式】
只返回JSON：
{{
  "has_conflict": true/false,
  "conflict_type": "none/identity/other",
  "conflict_description": "冲突描述",
  "suggestion": "处理建议"
}}"""

        try:
            response = await asyncio.to_thread(
                self.model.chat,
                [
                    ChatMessage("system", "你是记忆冲突检测器，只输出JSON。"),
                    ChatMessage("user", prompt),
                ]
            )
            parsed = extract_json(response.content)

            if parsed.get("has_conflict"):
                conflict_desc = parsed.get("conflict_description", "")
                logger.warning(f"记忆冲突检测: {conflict_desc}")
                return conflict_desc

            return None
        except Exception as e:
            logger.warning(f"记忆冲突检测失败: {e}")
            return None

    async def _extract_user_profile(self, user_input: str) -> None:
        """
        从用户输入中智能提取关键信息到用户画像（规则匹配优先，LLM兜底）。

        支持的模式：
        - "我叫XXX" / "我的名字是XXX" → identity.name
        - "叫我XXX" / "称呼我XXX" → identity.nickname
        - "我喜欢XXX" / "我偏好XXX" → interests

        核心改进：规则匹配能处理的情况不调用LLM，只有模糊情况才用LLM
        """
        import re

        question_patterns = [
            r'我是谁',
            r'你还记得么',
            r'你认识我吗',
            r'知道我是谁',
            r'还记得我吗',
        ]
        for pattern in question_patterns:
            if re.search(pattern, user_input):
                logger.debug(f"检测到疑问句式，跳过身份提取: {user_input}")
                return

        non_name_patterns = [
            r'我是\s*(学生|老师|程序员|开发者|用户|新人|一个|这里|谁|什么|怎么|为什么)',
            r'我是\s*(student|teacher|developer|user)',
        ]
        for pattern in non_name_patterns:
            if re.search(pattern, user_input, re.IGNORECASE):
                logger.debug(f"检测到非身份声明，跳过身份提取: {user_input}")
                return

        name_patterns = [
            (r'我叫\s*([A-Za-z\u4e00-\u9fa5][A-Za-z\u4e00-\u9fa5·\s]{0,20})', '我叫'),
            (r'我的名字是\s*([A-Za-z\u4e00-\u9fa5][A-Za-z\u4e00-\u9fa5·\s]{0,20})', '我的名字是'),
            (r'我的名字叫\s*([A-Za-z\u4e00-\u9fa5][A-Za-z\u4e00-\u9fa5·\s]{0,20})', '我的名字叫'),
        ]
        for pattern, desc in name_patterns:
            m = re.search(pattern, user_input)
            if m:
                name = m.group(1).strip().rstrip('，。,.!?！？')
                non_name_words = {"学生", "老师", "程序员", "开发者", "用户", "新人",
                                  "一个", "这里", "谁", "什么", "怎么", "为什么",
                                  "student", "teacher", "developer", "user"}
                if name and name.lower() not in non_name_words and len(name) >= 2:
                    current_name = self.user_profile.get("identity.name", "")
                    if not current_name:
                        self.user_profile.set("identity.name", name)
                        logger.info(f"用户画像更新: identity.name = {name}")
                    return

        nickname_patterns = [
            r'叫我\s*([A-Za-z\u4e00-\u9fa5][A-Za-z\u4e00-\u9fa5·\s]{0,20})',
            r'称呼我\s*([A-Za-z\u4e00-\u9fa5][A-Za-z\u4e00-\u9fa5·\s]{0,20})',
            r'call me\s+([A-Za-z][A-Za-z\s]{0,20})',
        ]
        for pattern in nickname_patterns:
            m = re.search(pattern, user_input, re.IGNORECASE)
            if m:
                nickname = m.group(1).strip().rstrip('，。,.!?！？')
                if nickname and len(nickname) >= 2:
                    self.user_profile.set("identity.nickname", nickname)
                    logger.info(f"用户画像更新: identity.nickname = {nickname}")
                    if not self.user_profile.get("identity.name", ""):
                        self.user_profile.set("identity.name", nickname)
                        logger.info(f"用户画像更新: identity.name 回退使用 nickname = {nickname}")
                    return

        interest_patterns = [
            r'我喜欢\s*(.{2,30})',
            r'我偏好\s*(.{2,30})',
            r'我爱\s*(.{2,30})',
            r'我对(.{0,5})感兴趣',
        ]
        for pattern in interest_patterns:
            m = re.search(pattern, user_input)
            if m:
                interest = m.group(1).strip().rstrip('，。,.!?！？')
                if interest and not interest.startswith(('这', '那', '它', '他', '她')):
                    self.user_profile.add_to_list("interests", interest)
                    logger.info(f"用户画像更新: interests += {interest}")
                    return

        logger.debug(f"规则匹配未命中，跳过用户画像提取: {user_input}")

    # ============================================================
    # 阶段7: 技能沉淀
    # ============================================================
    async def _step_skill(self, state) -> None:
        # 配置禁用技能生成时，直接返回
        if not self.enable_skill_generation:
            return

        from castorice.memory.skill import Skill
        proposal = state.skill_to_generate
        if not proposal or not proposal.get("name"):
            return
        try:
            skill = Skill(
                name=proposal["name"],
                trigger_keywords=proposal.get("trigger_keywords", []),
                description=proposal.get("description", ""),
                steps=proposal.get("steps", []),
                required_tools=proposal.get("required_tools", []),
                applicable_scenarios=proposal.get("applicable_scenarios", []),
            )
            # 使用公共接口，内部会自动处理版本递增和保存
            self.skill_memory.add_or_update(skill)
            logger.info(f"技能沉淀完成: {skill.name}")
        except Exception as e:
            logger.warning(f"技能生成失败: {e}")

    # ============================================================
    # 阶段8: 主动话题发起（正常对话中自然延续话题）
    # ============================================================
    async def _step_initiate_topic(self, state) -> Optional[str]:
        """
        P2.5: 主动话题生成——在正常对话中主动发起相关话题
        
        判断条件：
        - 用户输入长度 >= 5（排除单字回复）
        - 用户进行中意图 < 3（不打扰忙碌用户）
        - 关系亲密度 >= 0.3（陌生人不主动）
        - 情绪愉悦度 >= -0.5（用户情绪低时不打扰）
        - 对话轮数 < 20（避免信息过载）
        
        输出：自然的延续话题或相关问题，如 None 则不发起
        """
        # 1. 快速判断：某些场景不适合主动发起
        if self._should_skip_initiation(state):
            return None

        # 2. LLM 判断是否应该发起以及发起什么话题
        return await asyncio.to_thread(
            self._generate_initiated_topic, state
        )

    def _should_skip_initiation(self, state) -> bool:
        """快速判断是否应该跳过主动话题生成"""
        # 1. 用户输入太短（可能是简单回应）
        if len(state.user_input.strip()) < 5:
            logger.debug("P2.5 主动话题跳过: 用户输入太短")
            return True

        # 2. 用户有多个进行中的意图（忙）
        if hasattr(self, 'intent_tracker'):
            try:
                active_intents = self.intent_tracker.get_active_intents(limit=5)
                if len(active_intents) >= 3:
                    logger.debug(f"P2.5 主动话题跳过: 用户有 {len(active_intents)} 个进行中意图")
                    return True
            except Exception:
                pass

        # 3. 情绪太低落
        try:
            _state = self.emotion_engine._state
            if _state is not None:
                p, _, _ = _state.pleasure, _state.arousal, _state.dominance
                if p < -0.5:
                    logger.debug(f"P2.5 主动话题跳过: 情绪低落(p={p:.2f})")
                    return True
        except Exception:
            pass

        # 4. 关系太陌生（亲密度 < 0.3）
        if hasattr(self, 'social_relation'):
            try:
                user_id = getattr(state, 'user_id', state.session_id)
                relation = self.social_relation.get_relation(user_id)
                if relation and relation.intimacy < 0.3:
                    logger.debug(f"P2.5 主动话题跳过: 关系陌生(intimacy={relation.intimacy:.2f})")
                    return True
            except Exception:
                pass

        return False

    def _generate_initiated_topic(self, state) -> Optional[str]:
        """LLM 驱动生成主动话题"""
        from castorice.model_adapter import ChatMessage

        curiosity_concepts = []
        if hasattr(self, 'motivation_system'):
            try:
                with self.motivation_system._lock:
                    curiosity_concepts = self.motivation_system._curiosity_queue[:3]
            except Exception:
                pass

        active_intents = []
        if hasattr(self, 'intent_tracker'):
            try:
                active_intents = self.intent_tracker.get_active_intents(limit=3)
            except Exception:
                pass

        relation_info = ""
        if hasattr(self, 'social_relation'):
            try:
                user_id = getattr(state, 'user_id', state.session_id)
                relation = self.social_relation.get_relation(user_id)
                if relation:
                    relation_info = f"亲密度={relation.intimacy:.2f}, 信任度={relation.trust:.2f}"
            except Exception:
                pass

        prompt = f"""你是一个善于主动发起话题的 AI。请根据以下对话信息，判断是否应该主动发起一个自然的延续话题。

【对话上下文】
用户输入: {state.user_input}
你的回答: {state.final_answer[:500]}

【Agent 状态】
当前动机: {state.current_motivations}
好奇概念: {curiosity_concepts}
用户关系: {relation_info}

【任务】
1. 判断是否应该主动发起话题（如果当前对话已经完整，不需要强行拓展）
2. 如果应该发起，生成一个自然、友好的延续话题或问题
3. 如果不应该发起，返回空字符串

【输出格式】
只返回话题文本，如果不发起则返回空字符串。

【话题类型参考】
- 好奇心型："你提到的XX，我很好奇..."
- 关心型："对了，你最近怎么样？"
- 知识扩展型："关于XX，我还了解到..."
- 意图延续型："你之前提到的XX，需要继续吗？"
- 开放式问题："你对XX怎么看？"

【注意】
- 话题要简短自然，不要长篇大论
- 不要重复刚刚讨论过的内容
- 不要问过于私人的问题
- 如果用户刚表达了负面情绪，不要强行发起新话题"""

        try:
            response = self.model.chat([
                ChatMessage("system", "你是一个善于主动发起话题的 AI。"),
                ChatMessage("user", prompt),
            ])
            topic = response.content.strip() if hasattr(response, 'content') else str(response).strip()
        except Exception as e:
            logger.debug(f"P2.5 LLM 生成话题失败: {e}")
            return None

        # 过滤无效话题
        if len(topic) < 5 or len(topic) > 100:
            return None

        # 避免重复内容
        if topic in state.final_answer:
            return None

        return topic
