"""
通用工具函数模块
"""

import json
import logging
import re
from typing import Any, Dict, Optional

logger = logging.getLogger("Castorice.Utils")


def extract_json(text: str) -> Dict[str, Any]:
    """从 LLM 响应中提取 JSON（多层兜底）"""
    if not text:
        return {}
    
    match = re.search(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", text)
    if match:
        try:
            return json.loads(match.group(1))
        except Exception as e:
            logger.warning(f"JSON 代码块解析失败: {e}")
    
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidate = text[start:end + 1]
        try:
            return json.loads(candidate)
        except Exception:
            for line in text.splitlines():
                line = line.strip()
                if line.startswith("{") and line.endswith("}"):
                    try:
                        return json.loads(line)
                    except Exception:
                        continue
    return {}
