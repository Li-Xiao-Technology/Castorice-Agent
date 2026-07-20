"""
用户画像模块 - JSON 文件存储 + 嵌套路径访问
（从原 castorice_memory.user_profile 迁移）
"""

import json
import logging
import os
import tempfile
import threading
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger("Castorice.UserProfile")


class UserProfile:
    """用户画像管理器（使用点路径访问嵌套字段）"""

    DEFAULT_TEMPLATE: Dict[str, Any] = {
        "identity": {
            "name": "",             # 用户名字（持久化，跨会话保留）
            "nickname": "",         # 昵称
        },
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
        # P2-7: 线程锁保护并发写
        self._lock = threading.Lock()
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
            # 兼容旧文件：补齐新增的 identity 字段
            self._merge_defaults()
        except Exception:
            self.data = json.loads(json.dumps(self.DEFAULT_TEMPLATE))

    def _merge_defaults(self) -> None:
        """将 DEFAULT_TEMPLATE 中存在但本地文件缺失的字段补齐（深度合并）"""
        def _merge(dst: Dict, src: Dict) -> None:
            for k, v in src.items():
                if k not in dst:
                    dst[k] = json.loads(json.dumps(v))
                elif isinstance(v, dict) and isinstance(dst[k], dict):
                    _merge(dst[k], v)
        _merge(self.data, self.DEFAULT_TEMPLATE)

    def _save(self) -> None:
        """P2-7: 原子写入——先写临时文件再 os.replace，避免并发写时文件损坏"""
        os.makedirs(os.path.dirname(self.storage_path) or ".", exist_ok=True)
        # 写到同目录的临时文件，确保 os.replace 是原子操作（同分区）
        dir_name = os.path.dirname(self.storage_path) or "."
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=dir_name,
                prefix=".user_profile_tmp_", suffix=".json", delete=False,
            ) as tmp_file:
                json.dump(self.data, tmp_file, ensure_ascii=False, indent=2)
                tmp_path = tmp_file.name
            # os.replace 是原子操作（POSIX/Windows 均支持同分区原子替换）
            os.replace(tmp_path, self.storage_path)
        except Exception as e:
            logger.warning(f"P2-7: 用户画像保存失败: {e}")
            # 清理临时文件（如果存在）
            try:
                if 'tmp_path' in locals() and os.path.exists(tmp_path):
                    os.unlink(tmp_path)
            except Exception:
                pass

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
        with self._lock:  # P2-7: 加锁保护读-改-写
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
        with self._lock:  # P2-7: 加锁
            current = self.get(dotted_key, [])
            if not isinstance(current, list):
                current = []
            if value and value not in current:
                current.append(value)
                # 直接写，避免递归加锁
                keys = dotted_key.split(".")
                cur = self.data
                for k in keys[:-1]:
                    if k not in cur or not isinstance(cur[k], dict):
                        cur[k] = {}
                    cur = cur[k]
                cur[keys[-1]] = current
                self._save()

    def record_interaction(self) -> None:
        """记录一次用户交互"""
        with self._lock:  # P2-7: 加锁
            now = datetime.now(timezone.utc).isoformat()
            # 直接操作避免递归加锁
            self._set_raw("stats.last_seen", now)
            if not self.get("stats.first_seen"):
                self._set_raw("stats.first_seen", now)
            current_count = self.get("stats.total_interactions", 0) or 0
            self._set_raw("stats.total_interactions", current_count + 1)
            self._save()

    def _set_raw(self, dotted_key: str, value: Any) -> None:
        """内部 set（不加锁，供已加锁的方法调用）"""
        keys = dotted_key.split(".")
        cur = self.data
        for k in keys[:-1]:
            if k not in cur or not isinstance(cur[k], dict):
                cur[k] = {}
            cur = cur[k]
        cur[keys[-1]] = value

    def increment_interactions(self) -> None:
        """增加交互计数（record_interaction 的简写）"""
        self.record_interaction()

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
        with self._lock:  # P2-7: 加锁
            self.data = json.loads(json.dumps(self.DEFAULT_TEMPLATE))
            self._save()
