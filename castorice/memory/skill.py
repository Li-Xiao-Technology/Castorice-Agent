"""
技能记忆模块 - JSON 文件 + 版本控制 + 关键词匹配
（从原 castorice_memory.skill_memory 迁移）
"""

import json
import os
import re
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import List, Optional, Dict, Any


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
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    required_tools: List[str] = field(default_factory=list)
    applicable_scenarios: List[str] = field(default_factory=list)
    success_count: int = 0
    failure_count: int = 0

    def bump_version(self) -> None:
        self.version += 1
        self.updated_at = datetime.utcnow().isoformat()

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Skill":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


class SkillMemory:
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
        os.makedirs(os.path.dirname(self.storage_path) or ".", exist_ok=True)
        data = {"version": "1.0", "skills": [s.to_dict() for s in self.skills], "updated_at": datetime.utcnow().isoformat()}
        with open(self.storage_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def add_or_update(self, skill: Skill) -> None:
        existing = self.find_by_name(skill.name)
        if existing:
            existing.bump_version()
            existing.steps = skill.steps or existing.steps
            existing.trigger_keywords = list(set(existing.trigger_keywords + skill.trigger_keywords))
            existing.description = skill.description or existing.description
        else:
            self.skills.append(skill)
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
