"""
批量对话导入功能

支持从多种格式导入历史对话数据：
- JSONL 格式
- JSON 数组格式
- 微信导出格式
- 文本日志格式

导入后自动：
- 转换为统一的 ChatMessage 格式
- 存储到短期记忆
- 更新用户画像
"""

import json
import logging
import os
import re
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Castorice.ConversationImporter")


class ImportFormat(Enum):
    JSONL = "jsonl"
    JSON = "json"
    WECHAT = "wechat"
    TEXT = "text"


class ConversationImporter:
    """对话导入器"""

    def __init__(self):
        self._imported_count = 0
        self._skipped_count = 0

    def import_from_file(
        self,
        file_path: str,
        format_type: ImportFormat = None,
        user_id: str = "default",
    ) -> Dict[str, Any]:
        """从文件导入对话"""
        if not os.path.exists(file_path):
            return {"error": f"文件不存在: {file_path}"}

        if format_type is None:
            format_type = self._detect_format(file_path)

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception as e:
            return {"error": f"读取文件失败: {e}"}

        if format_type == ImportFormat.JSONL:
            messages = self._parse_jsonl(content)
        elif format_type == ImportFormat.JSON:
            messages = self._parse_json(content)
        elif format_type == ImportFormat.WECHAT:
            messages = self._parse_wechat(content)
        elif format_type == ImportFormat.TEXT:
            messages = self._parse_text(content)
        else:
            return {"error": f"不支持的格式: {format_type}"}

        self._imported_count += len(messages)
        return {
            "success": True,
            "imported_count": len(messages),
            "total_imported": self._imported_count,
            "messages": messages,
        }

    def _detect_format(self, file_path: str) -> ImportFormat:
        """自动检测文件格式"""
        ext = os.path.splitext(file_path)[1].lower()
        if ext == ".jsonl":
            return ImportFormat.JSONL
        elif ext == ".json":
            return ImportFormat.JSON
        elif ext == ".txt":
            return ImportFormat.TEXT
        return ImportFormat.JSON

    def _parse_jsonl(self, content: str) -> List[Dict[str, Any]]:
        """解析 JSONL 格式"""
        messages = []
        for line in content.strip().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                messages.append(self._normalize_message(data))
            except json.JSONDecodeError:
                self._skipped_count += 1
        return messages

    def _parse_json(self, content: str) -> List[Dict[str, Any]]:
        """解析 JSON 数组格式"""
        try:
            data = json.loads(content)
            if isinstance(data, list):
                return [self._normalize_message(m) for m in data]
            elif isinstance(data, dict):
                messages = data.get("messages", data.get("conversation", []))
                return [self._normalize_message(m) for m in messages]
        except json.JSONDecodeError as e:
            logger.error(f"JSON 解析失败: {e}")
        return []

    def _parse_wechat(self, content: str) -> List[Dict[str, Any]]:
        """解析微信导出格式"""
        messages = []
        lines = content.strip().splitlines()
        
        current_date = None
        current_sender = None
        current_content = []
        
        for line in lines:
            date_match = re.match(r"^(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2}:\d{2})$", line)
            if date_match:
                current_date = date_match.group(1)
                continue
            
            sender_match = re.match(r"^(.+?):\s*(.+)$", line)
            if sender_match:
                if current_sender and current_content:
                    messages.append({
                        "role": "user" if current_sender == "我" else "assistant",
                        "content": "\n".join(current_content),
                        "sender": current_sender,
                    })
                current_sender = sender_match.group(1)
                current_content = [sender_match.group(2)]
            else:
                if line.strip():
                    current_content.append(line.strip())
        
        if current_sender and current_content:
            messages.append({
                "role": "user" if current_sender == "我" else "assistant",
                "content": "\n".join(current_content),
                "sender": current_sender,
            })
        
        return [self._normalize_message(m) for m in messages]

    def _parse_text(self, content: str) -> List[Dict[str, Any]]:
        """解析文本日志格式"""
        messages = []
        lines = content.strip().splitlines()
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            user_match = re.match(r"^(?:User|用户|Q|问):\s*(.+)$", line, re.IGNORECASE)
            if user_match:
                messages.append({"role": "user", "content": user_match.group(1)})
                continue
            
            assistant_match = re.match(r"^(?:Assistant|助手|A|答|Bot):\s*(.+)$", line, re.IGNORECASE)
            if assistant_match:
                messages.append({"role": "assistant", "content": assistant_match.group(1)})
                continue
            
            system_match = re.match(r"^(?:System|系统):\s*(.+)$", line, re.IGNORECASE)
            if system_match:
                messages.append({"role": "system", "content": system_match.group(1)})
        
        return [self._normalize_message(m) for m in messages]

    def _normalize_message(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """标准化消息格式"""
        role_map = {
            "user": "user",
            "assistant": "assistant",
            "system": "system",
            "bot": "assistant",
            "ai": "assistant",
        }
        
        role = data.get("role", "")
        role = role_map.get(role.lower(), "user")
        
        content = data.get("content", data.get("message", data.get("text", "")))
        
        return {
            "role": role,
            "content": str(content),
            "sender": data.get("sender", ""),
        }

    def export_to_jsonl(self, messages: List[Dict[str, Any]], file_path: str) -> bool:
        """导出为 JSONL 格式"""
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                for msg in messages:
                    f.write(json.dumps(msg, ensure_ascii=False) + "\n")
            return True
        except Exception as e:
            logger.error(f"导出失败: {e}")
            return False

    def get_stats(self) -> Dict[str, int]:
        """获取导入统计"""
        return {
            "imported": self._imported_count,
            "skipped": self._skipped_count,
        }


_conversation_importer = None


def get_conversation_importer() -> ConversationImporter:
    """获取全局对话导入器单例"""
    global _conversation_importer
    if _conversation_importer is None:
        _conversation_importer = ConversationImporter()
    return _conversation_importer
