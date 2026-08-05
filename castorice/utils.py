"""
通用工具函数模块
"""

import json
import logging
import os
import re
import tempfile
from typing import Any, Dict, Optional, Set

logger = logging.getLogger("Castorice.Utils")


def atomic_json_dump(data: Any, file_path: str, **kwargs) -> None:
    """
    原子化写入 JSON 文件，避免进程崩溃导致文件损坏。

    原理：先写入临时文件，成功后用 os.replace 原子替换目标文件。
    在 Windows 上 os.replace 也是原子的（只要在同一卷上）。

    :param data: 要序列化的数据
    :param file_path: 目标文件路径
    :param kwargs: 透传给 json.dump 的额外参数（indent, ensure_ascii 等）
    """
    dir_name = os.path.dirname(os.path.abspath(file_path))
    os.makedirs(dir_name, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        suffix=".tmp",
        prefix=os.path.basename(file_path) + ".",
        dir=dir_name,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, **kwargs)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, file_path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


# CJK 统一表意文字基本区范围
_CJK_RANGES = re.compile(
    r'[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff'
    r'\U00020000-\U0002a6df\U0002a700-\U0002b73f'
    r'\U0002b740-\U0002b81f\U0002b820-\U0002ceaf]'
)


def _is_mostly_chinese(text: str) -> bool:
    """判断文本是否以中文字符为主"""
    if not text:
        return False
    cjk_count = sum(1 for ch in text if _CJK_RANGES.match(ch))
    # 去除空格后计算有效字符数
    non_space = sum(1 for ch in text if not ch.isspace())
    if non_space == 0:
        return False
    return cjk_count / non_space > 0.3


def chinese_tokenize(text: str) -> Set[str]:
    """
    中英文混合文本分词（无外部依赖）

    - 中文字符段：提取连续 CJK 字符的 bigrams + trigrams
    - 英文/数字段：按空格或 CJK 边界拆分出独立单词
    - 自动适配纯中文、纯英文、中英混合场景

    :param text: 输入文本
    :return: token 集合
    """
    if not text or not text.strip():
        return set()

    tokens: Set[str] = set()
    text_lower = text.lower().strip()

    if _is_mostly_chinese(text_lower):
        # 1. 提取所有连续 CJK 字符段，生成 bigrams + trigrams
        #    复用模块级 _CJK_RANGES 的 pattern，避免 CJK 范围正则重复定义
        for match in re.finditer(_CJK_RANGES.pattern + '+', text_lower):
            seg = match.group()
            if len(seg) >= 2:
                for i in range(len(seg) - 1):
                    tokens.add(seg[i:i + 2])
            if len(seg) >= 3:
                for i in range(len(seg) - 2):
                    tokens.add(seg[i:i + 3])
            if len(seg) == 1:
                tokens.add(seg)

        # 2. 提取非 CJK 的英文/数字单词
        for word in re.findall(r'[a-z0-9]+', text_lower):
            if len(word) >= 2:  # 过滤掉单字母噪声
                tokens.add(word)
    else:
        # 英文为主：按空格拆分
        tokens = set(text_lower.split())

    return tokens


def chinese_text_similarity(text_a: str, text_b: str) -> float:
    """
    基于 chinese_tokenize 的 Jaccard 相似度，适用于中英文混合文本。

    :param text_a: 文本 A
    :param text_b: 文本 B
    :return: 0-1 之间的相似度分数
    """
    tokens_a = chinese_tokenize(text_a)
    tokens_b = chinese_tokenize(text_b)
    if not tokens_a or not tokens_b:
        return 0.0
    intersection = len(tokens_a & tokens_b)
    union = len(tokens_a | tokens_b)
    return intersection / union if union > 0 else 0.0


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
