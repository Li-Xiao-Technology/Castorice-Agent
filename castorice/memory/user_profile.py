"""
用户画像模块 - JSON 文件存储 + 嵌套路径访问
（从原 castorice_memory.user_profile 迁移）
"""

import json
import os
from datetime import datetime
from typing import Any, Dict, Optional


class UserProfile:
    """用户画像管理器（使用点路径访问嵌套字段）"""

    DEFAULT_TEMPLATE: Dict[str, Any] = {
        "preferences": {
            "output_format": "",   # markdown / plain
            "language": "zh-CN",
            "response_style": "",   # concise / detailed
        },
        "tools": {
            "preferred_software": [],
            "banned_commands": [],
        },
        "projects": {
            "current_project": "",
            "tech_stack": [],
        },
        "interests": [],
        "stats": {
            "total_interactions": 0,
            "first_seen": None,
            "last_seen": None,
        },
    }

    def __init__(self, storage_path: str = "./castorice_data/user_profile.json"):
        self.storage_path = storage_path
        self.data: Dict[str, Any] = {}
        self._load()

    def _load(self) -> None:
        if not os.path.exists(self.storage_path):
            os.makedirs(os.path.dirname(self.storage_path) or ".", exist_ok=True)
            self.data = json.loads(json.dumps(self.DEFAULT_TEMPLATE))
            self._save()
            return
        try:
            with open(self.storage_path, "r", encoding="utf-8") as f:
                self.data = json.load(f)
        except Exception:
            self.data = json.loads(json.dumps(self.DEFAULT_TEMPLATE))

    def _save(self) -> None:
        os.makedirs(os.path.dirname(self.storage_path) or ".", exist_ok=True)
        with open(self.storage_path, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)

    def get(self, dotted_key: str, default: Any = None) -> Any:
        """通过点路径读取字段，如 'preferences.language'"""
        keys = dotted_key.split(".")
        cur = self.data
        for k in keys:
            if isinstance(cur, dict) and k in cur:
                cur = cur[k]
            else:
                return default
        return cur

    def set(self, dotted_key: str, value: Any) -> None:
        """通过点路径设置字段"""
        keys = dotted_key.split(".")
        cur = self.data
        for k in keys[:-1]:
            if k not in cur or not isinstance(cur[k], dict):
                cur[k] = {}
            cur = cur[k]
        cur[keys[-1]] = value
        self._save()

    def add_to_list(self, dotted_key: str, value: str) -> None:
        """向列表字段追加元素（去重）"""
        current = self.get(dotted_key, [])
        if not isinstance(current, list):
            current = []
        if value and value not in current:
            current.append(value)
            self.set(dotted_key, current)

    def record_interaction(self) -> None:
        """记录一次用户交互"""
        now = datetime.utcnow().isoformat()
        self.set("stats.last_seen", now)
        if not self.get("stats.first_seen"):
            self.set("stats.first_seen", now)
        self.set("stats.total_interactions", self.get("stats.total_interactions", 0) + 1)

    def to_prompt_context(self) -> str:
        """生成注入到 LLM 系统提示词的画像上下文"""
        lines = ["[用户画像]"]
        for section, values in self.data.items():
            if section == "stats":
                continue
            if isinstance(values, dict):
                for k, v in values.items():
                    if v:
                        lines.append(f"- {section}.{k}: {v}")
            elif isinstance(values, list) and values:
                lines.append(f"- {section}: {', '.join(map(str, values))}")
        return "\n".join(lines) if len(lines) > 1 else ""

    def reset(self) -> None:
        self.data = json.loads(json.dumps(self.DEFAULT_TEMPLATE))
        self._save()
