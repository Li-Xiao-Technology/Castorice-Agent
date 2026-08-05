"""
技能记忆模块 - JSON 文件 + 版本控制 + 关键词匹配
（从原 castorice_memory.skill_memory 迁移）
"""

import json
import logging
import os
import re
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any

from castorice.memory.interface import SkillMemoryInterface

logger = logging.getLogger("Castorice.SkillMemory")


@dataclass
class Skill:
    """技能结构定义"""
    name: str
    trigger_keywords: List[str]
    description: str
    steps: List[Dict[str, Any]] = field(default_factory=list)
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    version: int = 1
    enabled: bool = True
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    required_tools: List[str] = field(default_factory=list)
    applicable_scenarios: List[str] = field(default_factory=list)
    success_count: int = 0
    failure_count: int = 0

    def bump_version(self) -> None:
        self.version += 1
        self.updated_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Skill":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


class SkillMemory(SkillMemoryInterface):
    """技能库管理器"""

    def __init__(self, storage_path: str = "./castorice_data/skill_library.json"):
        self.storage_path = storage_path
        self.skills: List[Skill] = []
        self._load()

    def _load(self) -> None:
        if not os.path.exists(self.storage_path):
            os.makedirs(os.path.dirname(self.storage_path) or ".", exist_ok=True)
            self._save()
            return
        try:
            with open(self.storage_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.skills = [Skill.from_dict(s) for s in data.get("skills", [])]
        except Exception:
            self.skills = []

    def _save(self) -> None:
        from castorice.utils import atomic_json_dump
        data = {"version": "1.0", "skills": [s.to_dict() for s in self.skills], "updated_at": datetime.now(timezone.utc).isoformat()}
        atomic_json_dump(data, self.storage_path, ensure_ascii=False, indent=2)

    def add_or_update(self, skill: Skill) -> None:
        existing = self.find_by_name(skill.name)
        if existing:
            existing.bump_version()
            existing.steps = skill.steps or existing.steps
            existing.trigger_keywords = list(set(existing.trigger_keywords + skill.trigger_keywords))
            existing.description = skill.description or existing.description
            # P2-8: 补全 required_tools 和 applicable_scenarios 字段更新
            if skill.required_tools:
                existing.required_tools = list(set(existing.required_tools + skill.required_tools))
            if skill.applicable_scenarios:
                existing.applicable_scenarios = list(set(existing.applicable_scenarios + skill.applicable_scenarios))
        else:
            self.skills.append(skill)
        self._save()

    def record_success(self, skill_id: str) -> None:
        """P2-8: 记录技能成功使用"""
        skill = self.find_by_id(skill_id)
        if skill:
            skill.success_count += 1
            self._save()

    def record_failure(self, skill_id: str) -> None:
        """P2-8: 记录技能使用失败"""
        skill = self.find_by_id(skill_id)
        if skill:
            skill.failure_count += 1
            self._save()

    def find_by_name(self, name: str) -> Optional[Skill]:
        for s in self.skills:
            if s.name == name:
                return s
        return None

    def find_by_id(self, skill_id: str) -> Optional[Skill]:
        for s in self.skills:
            if s.id == skill_id:
                return s
        return None

    def match(self, query: str, top_n: int = 3) -> List[Skill]:
        """根据查询匹配最相关的技能"""
        query_lower = query.lower()
        scored = []
        for skill in self.skills:
            if not skill.enabled:
                continue
            score = 0
            for kw in skill.trigger_keywords:
                kw_lower = kw.lower()
                if kw_lower in query_lower:
                    score += 10
                else:
                    # 部分匹配
                    for word in re.findall(r"[\w\u4e00-\u9fa5]+", query_lower):
                        if kw_lower in word or word in kw_lower:
                            score += 3
            if skill.name.lower() in query_lower:
                score += 5
            if score > 0:
                scored.append((score, skill))
        scored.sort(key=lambda x: -x[0])
        return [s for _, s in scored[:top_n]]

    def list_all(self, enabled_only: bool = False) -> List[Skill]:
        if enabled_only:
            return [s for s in self.skills if s.enabled]
        return self.skills

    def delete(self, skill_id: str) -> bool:
        for i, s in enumerate(self.skills):
            if s.id == skill_id:
                del self.skills[i]
                self._save()
                return True
        return False

    def export(self, export_path: str) -> None:
        # P3-6: 导出前创建目录，避免路径不存在时失败
        os.makedirs(os.path.dirname(export_path) or ".", exist_ok=True)
        with open(export_path, "w", encoding="utf-8") as f:
            json.dump({"skills": [s.to_dict() for s in self.skills]}, f, ensure_ascii=False, indent=2)

    def import_skills(self, import_path: str, merge: bool = True) -> int:
        with open(import_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        count = 0
        for s in data.get("skills", []):
            skill = Skill.from_dict(s)
            if merge and self.find_by_name(skill.name):
                continue
            self.skills.append(skill)
            count += 1
        if count > 0:
            self._save()
        return count
    
    # ============================================================
    # M2: 技能自动抽象与重组
    # ============================================================
    
    def abstract_skill_from_sequence(
        self,
        name: str,
        tool_sequence: List[Dict[str, Any]],
        description: str = "",
        trigger_keywords: List[str] = None,
        success: bool = True,
    ) -> Optional[Skill]:
        """
        M2: 从工具调用序列中抽象出新技能
        
        从多次成功的工具调用模式中，提炼出可复用的"技能"——
        包含步骤序列、所需工具、适用场景等信息。
        
        Args:
            name: 技能名称
            tool_sequence: 工具调用序列 [{tool_name, args, result, order}]
            description: 技能描述
            trigger_keywords: 触发关键词
            success: 是否为成功序列（成功才抽象）
            
        Returns:
            新创建的 Skill 对象，如果已存在则更新
        """
        if not success or not tool_sequence:
            return None
        
        # 提取步骤
        steps = []
        required_tools = set()
        for i, step in enumerate(tool_sequence):
            tool_name = step.get("tool_name", "")
            if tool_name:
                required_tools.add(tool_name)
            steps.append({
                "order": i + 1,
                "tool_name": tool_name,
                "purpose": step.get("purpose", step.get("result_summary", "")[:100]),
                "args_template": step.get("args", {}),
                "expected_output": step.get("result_summary", "")[:200],
            })
        
        # 自动生成触发关键词（从描述中提取）
        if not trigger_keywords:
            trigger_keywords = self._extract_keywords(name + " " + description)
        
        skill = Skill(
            name=name,
            description=description or f"自动抽象的技能: {name}",
            steps=steps,
            trigger_keywords=trigger_keywords,
            required_tools=list(required_tools),
            applicable_scenarios=[description[:100]] if description else [],
        )
        
        self.add_or_update(skill)
        logger.info(f"[M2技能抽象] 新技能: {name} | {len(steps)}步 | 工具: {', '.join(required_tools)}")
        return skill
    
    def _extract_keywords(self, text: str, max_keywords: int = 8) -> List[str]:
        """从文本中简单提取关键词（中文分词简化版）"""
        # 提取中文字符和英文单词
        words = re.findall(r"[\u4e00-\u9fa5]{2,}|[a-zA-Z]{3,}", text)
        # 简单去重并取前 N 个
        seen = set()
        keywords = []
        for w in words:
            if w not in seen and len(w) >= 2:
                seen.add(w)
                keywords.append(w)
                if len(keywords) >= max_keywords:
                    break
        return keywords
    
    def compose_skill(
        self,
        skill_ids: List[str],
        new_name: str,
        new_description: str = "",
    ) -> Optional[Skill]:
        """
        M2: 重组多个技能为一个新技能（技能组合）
        
        将多个现有技能的步骤按顺序组合，形成更复杂的复合技能。
        这是Agent创造力的体现——从已有技能中组合出新能力。
        
        Args:
            skill_ids: 要组合的技能ID列表（按顺序）
            new_name: 新技能名称
            new_description: 新技能描述
            
        Returns:
            新创建的复合 Skill
        """
        skills_to_compose = []
        for sid in skill_ids:
            s = self.find_by_id(sid)
            if s and s.enabled:
                skills_to_compose.append(s)
        
        if len(skills_to_compose) < 2:
            return None  # 至少组合2个技能才有意义
        
        # 合并步骤
        all_steps = []
        all_tools = set()
        all_keywords = set()
        all_scenarios = set()
        step_offset = 0
        
        for skill in skills_to_compose:
            for step in skill.steps:
                new_step = dict(step)
                new_step["order"] = step_offset + new_step.get("order", 1)
                new_step["source_skill"] = skill.name
                all_steps.append(new_step)
            for t in skill.required_tools:
                all_tools.add(t)
            for kw in skill.trigger_keywords:
                all_keywords.add(kw)
            for sc in skill.applicable_scenarios:
                all_scenarios.add(sc)
            step_offset += len(skill.steps)
        
        # 自动添加组合关键词
        all_keywords.add(new_name)
        for s in skills_to_compose:
            all_keywords.add(s.name)
        
        composite_skill = Skill(
            name=new_name,
            description=new_description or f"组合技能: {' + '.join(s.name for s in skills_to_compose)}",
            steps=all_steps,
            trigger_keywords=list(all_keywords),
            required_tools=list(all_tools),
            applicable_scenarios=list(all_scenarios)[:5],
        )
        composite_skill.version = 1  # 新技能从v1开始
        composite_skill.success_count = 0
        composite_skill.failure_count = 0
        
        self.add_or_update(composite_skill)
        logger.info(f"[M2技能重组] 新复合技能: {new_name} | 由 {len(skills_to_compose)} 个技能组成 | {len(all_steps)} 步")
        return composite_skill
    
    def get_skill_library_health(self) -> Dict[str, Any]:
        """获取技能库健康状态"""
        total = len(self.skills)
        enabled = sum(1 for s in self.skills if s.enabled)
        with_steps = sum(1 for s in self.skills if s.steps)
        
        # 成功率分布
        high_success = sum(1 for s in self.skills if s.success_count > 0 and 
                          s.success_count / max(1, s.success_count + s.failure_count) > 0.7)
        low_success = sum(1 for s in self.skills if s.failure_count > 0 and 
                         s.success_count / max(1, s.success_count + s.failure_count) < 0.3)
        never_used = sum(1 for s in self.skills if s.success_count == 0 and s.failure_count == 0)
        
        # 工具覆盖率
        all_tools = set()
        for s in self.skills:
            for t in s.required_tools:
                all_tools.add(t)
        
        return {
            "total_skills": total,
            "enabled_skills": enabled,
            "skills_with_steps": with_steps,
            "high_success_rate": high_success,
            "low_success_rate": low_success,
            "never_used": never_used,
            "unique_tools_covered": len(all_tools),
            "tools_covered": list(all_tools),
        }
