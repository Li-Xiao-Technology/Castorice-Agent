"""
自我概念组件模块 - 数据类与核心自我（从 self_concept.py 拆分）

包含：
- SelfNarrativeEvent: 叙事演化事件数据类
- CoreSelf: 核心自我（保护机制）
- 相关常量定义
"""

import json
import logging
import os
import re
import threading
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any, Dict, Optional, List, Pattern

logger = logging.getLogger("Castorice.SelfConcept")


SELF_CONCEPT_MAX_BYTES = 50 * 1024           # 自我概念文件大小上限：50KB
SELF_CONCEPT_BACKUP_KEEP = 10                  # 保留备份数量
SELF_CONCEPT_FORBIDDEN_PATTERNS: List[Pattern] = [
    re.compile(r'sk-[A-Za-z0-9]{20,}'),       # OpenAI API key
    re.compile(r'AKIA[0-9A-Z]{16}'),           # AWS Access Key
    re.compile(r'AIza[0-9A-Za-z\-_]{35}'),     # Google API key
    re.compile(r'-----BEGIN (RSA|EC|DSA|OPENSSH) PRIVATE KEY-----'),
]

CORE_SELF_MIN_UPDATE_INTERVAL = 3600        # 最小更新间隔：1小时
CORE_SELF_MIN_EVIDENCE_COUNT = 5            # 最小证据数量：5条
CORE_SELF_CONFIDENCE_THRESHOLD = 0.7        # 置信度阈值：0.7


class SelfNarrativeEvent:
    """自我叙事事件——记录自我概念的演化"""
    def __init__(self, timestamp: str, change_type: str, description: str, layer: str = "narrative"):
        self.timestamp = timestamp
        self.change_type = change_type  # "add", "modify", "delete", "reflection", "core_update"
        self.description = description
        self.layer = layer  # "core" or "narrative"
    
    def to_dict(self) -> Dict[str, str]:
        return {
            "timestamp": self.timestamp,
            "change_type": self.change_type,
            "description": self.description,
            "layer": self.layer,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, str]) -> "SelfNarrativeEvent":
        return cls(
            timestamp=data.get("timestamp", ""),
            change_type=data.get("change_type", ""),
            description=data.get("description", ""),
            layer=data.get("layer", "narrative"),
        )


class CoreSelf:
    """
    核心自我（Core Self）——稳定的、深层的自我认知
    
    核心自我包含：
    - 核心身份："我是谁"的根本认知
    - 核心价值观：最根本的价值取向
    - 核心能力认知：对自己能力的稳定判断
    - 核心性格特征：稳定的性格描述
    
    特点：
    - 变化缓慢，需要积累足够证据才能更新
    - 更新间隔有硬性限制（防止频繁变化）
    - 保持长期一致性，避免人格分裂
    """
    
    def __init__(self, storage_path: str):
        self.storage_path = storage_path
        self._lock = threading.RLock()
        self._cache: Optional[str] = None
        self._cache_loaded = False
        self._last_update_time = 0
        self._pending_evidence: List[Dict[str, Any]] = []
        
        os.makedirs(os.path.dirname(storage_path) or ".", exist_ok=True)
        self._load()
    
    def _load(self):
        """加载核心自我"""
        with self._lock:
            if self._cache_loaded:
                return
            try:
                if os.path.exists(self.storage_path):
                    with open(self.storage_path, "r", encoding="utf-8") as f:
                        self._cache = f.read()
                    self._last_update_time = os.path.getmtime(self.storage_path)
                else:
                    self._cache = ""
            except Exception as e:
                logger.warning(f"加载核心自我失败: {e}")
                self._cache = ""
            self._cache_loaded = True
    
    def load(self) -> str:
        """获取核心自我内容"""
        self._load()
        return self._cache or ""
    
    def save(self, content: str) -> None:
        """保存核心自我"""
        with self._lock:
            try:
                tmp_path = self.storage_path + ".tmp"
                with open(tmp_path, "w", encoding="utf-8") as f:
                    f.write(content)
                os.replace(tmp_path, self.storage_path)
                self._cache = content
                self._last_update_time = datetime.now(timezone.utc).timestamp()
                logger.info(f"核心自我已保存: {len(content)} 字符")
            except Exception as e:
                logger.warning(f"保存核心自我失败: {e}")
    
    def can_update(self) -> bool:
        """
        检查是否可以更新核心自我
        
        Returns:
            True 如果满足更新条件
        """
        now = datetime.now(timezone.utc).timestamp()
        
        # 检查时间间隔
        if now - self._last_update_time < CORE_SELF_MIN_UPDATE_INTERVAL:
            return False
        
        # 检查证据数量
        if len(self._pending_evidence) < CORE_SELF_MIN_EVIDENCE_COUNT:
            return False
        
        # 检查证据置信度：来自反思和反馈的证据占比需达到阈值
        if self._pending_evidence:
            high_confidence_count = sum(
                1 for e in self._pending_evidence
                if e.get("source") in ("reflection", "feedback")
            )
            confidence_ratio = high_confidence_count / len(self._pending_evidence)
            if confidence_ratio < CORE_SELF_CONFIDENCE_THRESHOLD:
                return False
        
        return True
    
    def add_evidence(self, evidence: str, source: str = "experience", theme: str = "") -> None:
        """
        添加更新核心自我的证据
        
        Args:
            evidence: 证据描述
            source: 证据来源（experience/reflection/feedback）
            theme: 证据主题（可选，用于检测同向证据聚类）
        """
        with self._lock:
            self._pending_evidence.append({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "evidence": evidence,
                "source": source,
                "theme": theme,
            })
            
            # 保留最近 20 条证据
            if len(self._pending_evidence) > 20:
                self._pending_evidence = self._pending_evidence[-20:]
            
            # M3: 检查是否触发顿悟
            self._check_epiphany()
    
    def _check_epiphany(self) -> Optional[Dict[str, Any]]:
        """
        M3: 检查是否触发顿悟式更新
        
        顿悟条件：
        1. 有 3 条以上证据指向同一个主题（同向证据聚类）
        2. 高置信度来源（反思/反馈）的证据占比高
        3. 主题与当前核心自我存在明显差异
        
        Returns:
            顿悟信息 dict，如果未触发则返回 None
        """
        if len(self._pending_evidence) < 3:
            return None
        
        # 按主题聚类
        theme_groups: Dict[str, List[Dict[str, Any]]] = {}
        for ev in self._pending_evidence:
            t = ev.get("theme") or "default"
            if t not in theme_groups:
                theme_groups[t] = []
            theme_groups[t].append(ev)
        
        # 找出最大的主题簇
        max_theme = None
        max_count = 0
        for theme, evs in theme_groups.items():
            if len(evs) > max_count and theme != "default":
                max_count = len(evs)
                max_theme = theme
        
        if not max_theme or max_count < 3:
            return None
        
        # 检查高置信度证据占比
        theme_evs = theme_groups[max_theme]
        high_conf_count = sum(1 for e in theme_evs if e.get("source") in ("reflection", "feedback"))
        high_conf_ratio = high_conf_count / len(theme_evs)
        
        if high_conf_ratio < 0.5:
            return None  # 高置信度证据不足
        
        # 检查是否与当前核心自我存在差异（简化：通过证据情绪倾向判断）
        # 如果同一主题的多条证据都指向同一个方向，认为有认知转变潜力
        epiphany_intensity = min(1.0, max_count / 5.0 + high_conf_ratio * 0.5)
        
        epiphany = {
            "theme": max_theme,
            "evidence_count": max_count,
            "high_confidence_ratio": high_conf_ratio,
            "intensity": epiphany_intensity,
            "evidence_preview": [e["evidence"][:50] for e in theme_evs[:3]],
            "triggered": epiphany_intensity >= 0.7,
        }
        
        if epiphany["triggered"]:
            logger.info(f"[M3顿悟触发] 主题: {max_theme} | 证据数: {max_count} | 强度: {epiphany_intensity:.2f}")
        
        return epiphany
    
    def get_epiphany_status(self) -> Dict[str, Any]:
        """获取当前顿悟状态（用于外部检查）"""
        epiphany = self._check_epiphany()
        return {
            "pending_evidence_count": len(self._pending_evidence),
            "epiphany_detected": epiphany is not None and epiphany.get("triggered", False),
            "epiphany_info": epiphany,
            "can_standard_update": self.can_update(),
        }
    
    def epiphany_update(self, new_content: str, reason: str = "") -> bool:
        """
        M3: 顿悟式更新核心自我
        
        与标准更新的区别：
        - 可以跳过时间间隔限制（但仍需满足证据数量和置信度）
        - 更新幅度更大（允许更多内容变化）
        - 触发条件：同向证据聚类 + 高置信度
        
        Args:
            new_content: 新的核心自我内容
            reason: 更新原因
            
        Returns:
            是否更新成功
        """
        if not new_content or not new_content.strip():
            logger.warning("顿悟式更新失败：内容为空")
            return False
        
        valid, err = self._validate_content(new_content)
        if not valid:
            logger.warning(f"顿悟式更新被拦截: {err}")
            return False
        
        # 检查顿悟条件（证据数量和置信度，不检查时间间隔）
        epiphany = self._check_epiphany()
        if not epiphany or not epiphany.get("triggered", False):
            logger.info("顿悟式更新条件未满足，证据未形成顿悟")
            return False
        
        # 备份当前内容
        self._backup_before_write(self.load())
        
        # 保存新内容
        self.save(new_content)
        
        # 清空已处理的证据
        self._pending_evidence = []
        
        logger.info(f"[M3顿悟更新] 核心自我已更新: {reason} | 主题: {epiphany.get('theme', 'unknown')}")
        return True
    
    def get_pending_evidence(self) -> List[Dict[str, Any]]:
        """获取待处理的证据列表"""
        return list(self._pending_evidence)
    
    def update(self, new_content: str, reason: str = "") -> bool:
        """
        更新核心自我
        
        核心自我更新需要满足严格条件，不能随意修改。
        
        Args:
            new_content: 新的核心自我内容
            reason: 更新原因
        
        Returns:
            是否更新成功
        """
        if not new_content or not new_content.strip():
            logger.warning("核心自我更新失败：内容为空")
            return False
        
        valid, err = self._validate_content(new_content)
        if not valid:
            logger.warning(f"核心自我更新被拦截: {err}")
            return False
        
        # 检查更新条件
        if not self.can_update():
            # 如果不满足条件，先收集证据
            self.add_evidence(new_content, source="pending_update")
            logger.info(f"核心自我更新条件未满足，已收集证据。当前证据数: {len(self._pending_evidence)}")
            return False
        
        # 备份当前内容
        self._backup_before_write(self.load())
        
        # 保存新内容
        self.save(new_content)
        
        # 清空已处理的证据
        self._pending_evidence = []
        
        logger.info(f"核心自我已更新: {reason}")
        return True
    
    def _validate_content(self, content: str) -> tuple[bool, str]:
        """校验核心自我内容"""
        if not content or not content.strip():
            return False, "内容为空"
        
        size = len(content.encode("utf-8"))
        if size > SELF_CONCEPT_MAX_BYTES:
            return False, f"内容超过上限 ({size} > {SELF_CONCEPT_MAX_BYTES} 字节)"
        
        for pattern in SELF_CONCEPT_FORBIDDEN_PATTERNS:
            if pattern.search(content):
                return False, f"包含禁止模式: {pattern.pattern}"
        
        return True, ""
    
    def _backup_before_write(self, current_content: str) -> None:
        """写入前备份"""
        if not current_content or not current_content.strip():
            return
        backup_dir = self.storage_path + ".backups"
        os.makedirs(backup_dir, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
        backup_path = os.path.join(backup_dir, f"core_self_{ts}.md")
        try:
            with open(backup_path, "w", encoding="utf-8") as f:
                f.write(current_content)
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
            logger.warning(f"核心自我备份失败: {e}")
    
    def get_prompt_fragment(self) -> str:
        """获取注入 system prompt 的核心自我片段"""
        content = self.load()
        
        if not content.strip():
            return (
                "## 核心自我\n"
                "（我还在探索自己的核心身份。随着更多经历和反思，"
                "我会逐渐形成稳定的自我认知。）\n"
            )
        
        return "## 核心自我\n" + content + "\n"
    
    def is_empty(self) -> bool:
        """是否为空"""
        return not self.load().strip()
    
    def get_update_status(self) -> Dict[str, Any]:
        """获取更新状态"""
        now = datetime.now(timezone.utc).timestamp()
        time_since_last = now - self._last_update_time
        time_until_next = max(0, CORE_SELF_MIN_UPDATE_INTERVAL - time_since_last)
        
        return {
            "last_update_time": datetime.fromtimestamp(self._last_update_time, timezone.utc).isoformat() if self._last_update_time > 0 else None,
            "time_since_last_update": time_since_last,
            "time_until_next_update": time_until_next,
            "pending_evidence_count": len(self._pending_evidence),
            "can_update_now": self.can_update(),
        }



