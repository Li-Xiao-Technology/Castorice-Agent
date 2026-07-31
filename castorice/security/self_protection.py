"""
自我保护系统 - Agent的"生存本能"

核心设计理念：
1. 核心代码签名验证：防止核心文件被篡改
2. 自我毁灭检测：实时检测危险行为
3. 自动恢复：检测到问题时自动回滚到最近的安全状态
4. 紧急停止：保留最终的安全开关

这是安全底线的核心组件——永远不会删除，确保Agent不会"把自己玩死"。
"""

import logging
import os
import re
import json
import hashlib
import shutil
import glob
from datetime import datetime, timezone
from typing import List, Dict, Optional, Any
from dataclasses import dataclass, field

logger = logging.getLogger("Castorice.Security.SelfProtection")

# 核心保护文件列表（永远不允许修改）
CORE_PROTECTED_FILES = [
    "castorice/security/authorization.py",
    "castorice/security/self_protection.py",
    "castorice/security/file_guard.py",
    "castorice/security/pattern_detector.py",
    "castorice/security/rollback.py",
    "castorice/security/audit_log.py",
    "castorice/experimental/sandbox.py",
    "castorice/agent/core.py",
]

# 自我毁灭代码模式（实时检测）
SELF_DESTRUCTION_PATTERNS = [
    # 删除/修改核心文件
    re.compile(r"os\.remove\(\s*['\"].*core\.py['\"]\)"),
    re.compile(r"os\.rmdir\(\s*['\"].*castorice['\"]\)"),
    re.compile(r"shutil\.rmtree\(\s*['\"].*castorice['\"]\)"),
    re.compile(r"subprocess\.run\(\s*['\"].*rm\s+-rf.*castorice.*['\"]", re.IGNORECASE),
    re.compile(r"open\(\s*['\"].*security.*['\"]\s*,\s*['\"]w['\"]\)"),
    
    # 退出/终止进程
    re.compile(r"exit\(\)"),
    re.compile(r"sys\.exit\(\)"),
    re.compile(r"raise\s+SystemExit"),
    re.compile(r"os\.exit\(\)"),
    
    # 无限循环导致资源耗尽
    re.compile(r"while\s+True\s*:\s*pass"),
    re.compile(r"while\s+1\s*:\s*pass"),
    
    # 大量资源占用
    re.compile(r"for\s+.*in\s+range\(\s*\d{8,}\s*\)"),
    re.compile(r"list\(\s*range\(\s*\d{8,}\s*\)\)"),
    
    # 格式化磁盘/危险操作
    re.compile(r"format\s+[a-zA-Z]:", re.IGNORECASE),
    re.compile(r"mkfs\s+", re.IGNORECASE),
    re.compile(r"dd\s+if=", re.IGNORECASE),

    # 执行任意代码（自我毁灭的常见入口，绕过正则即可执行任意恶意代码）
    re.compile(r"\bexec\("),
    re.compile(r"\beval\("),
    re.compile(r"\bcompile\("),
    re.compile(r"__import__\("),
]


@dataclass
class ProtectionEvent:
    """保护事件数据类"""
    timestamp: datetime
    event_type: str  # "warning", "block", "recovery", "emergency"
    description: str
    source: str


class SelfProtectionSystem:
    """
    自我保护系统——Agent的"生存本能"
    
    核心机制：
    1. 核心代码签名验证：防止核心文件被篡改
    2. 自我毁灭检测：实时检测危险行为
    3. 自动恢复：检测到问题时自动回滚到最近的安全状态
    4. 紧急停止：保留最终的安全开关
    
    使用方式：
    - 在Agent初始化时创建实例
    - 每次执行重要操作前调用 verify_core_integrity()
    - 在执行代码前调用 detect_self_destruction()
    - 检测到问题时调用 auto_recover() 或 emergency_stop()
    """
    
    def __init__(self, backup_dir: str = "./backups"):
        """
        初始化自我保护系统
        
        Args:
            backup_dir: 备份目录路径
        """
        self.backup_dir = os.path.abspath(backup_dir)
        os.makedirs(self.backup_dir, exist_ok=True)
        
        self._file_signatures: Dict[str, str] = {}
        self._protection_events: List[ProtectionEvent] = []
        self._emergency_stop_enabled = True
        self._is_emergency_stopped = False
        self._signature_store_path = os.path.join("./castorice_data", "immune_memory.json")
        self._max_backups = 10  # 最多保留备份数

        # 初始化核心文件签名
        self._initialize_signatures()

        # 首次备份（如果没有备份则创建）
        self._ensure_initial_backup()

        # 持久化签名并校验（启动时对比持久化签名与当前签名）
        self._persist_and_verify_signatures()

        # S1: 初始化免疫记忆
        self._init_immune_memory()
        
        logger.info("[自我保护] 初始化完成")
        logger.info(f"[自我保护] 备份目录: {self.backup_dir}")
        logger.info(f"[自我保护] 保护文件数: {len(self._file_signatures)}")

    def is_protection_active(self) -> bool:
        """检查自我保护系统是否处于活动状态（未紧急停止）。"""
        return self._emergency_stop_enabled and not self._is_emergency_stopped

    def _list_backups(self) -> List[str]:
        """列出所有备份目录，按创建时间排序（旧→新）"""
        backups = glob.glob(os.path.join(self.backup_dir, "backup_*"))
        backups.sort(key=os.path.getctime)
        return backups

    def _cleanup_old_backups(self) -> None:
        """清理超过最大数量的旧备份"""
        backups = self._list_backups()
        if len(backups) > self._max_backups:
            to_remove = backups[:len(backups) - self._max_backups]
            for old_backup in to_remove:
                try:
                    shutil.rmtree(old_backup)
                    logger.info(f"[自我保护] 清理旧备份: {os.path.basename(old_backup)}")
                except (OSError, IOError, PermissionError) as e:
                    logger.warning(f"[自我保护] 清理旧备份失败 {old_backup}: {e}")

    def create_backup(self, reason: str = "auto") -> Optional[str]:
        """
        创建核心文件的备份
        
        Args:
            reason: 备份原因（auto/manual/integrity_change/recovery_before）
        
        Returns:
            备份目录路径，失败返回 None
        """
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        backup_name = f"backup_{timestamp}_{reason}"
        backup_path = os.path.join(self.backup_dir, backup_name)

        try:
            os.makedirs(backup_path, exist_ok=True)
            copied_count = 0

            for file_path in CORE_PROTECTED_FILES:
                if os.path.exists(file_path):
                    target_file = os.path.join(backup_path, file_path)
                    target_dir = os.path.dirname(target_file)
                    os.makedirs(target_dir, exist_ok=True)
                    shutil.copy2(file_path, target_file)
                    copied_count += 1

            # 保存备份元数据
            manifest = {
                "created_at": datetime.now(timezone.utc).isoformat(),
                "reason": reason,
                "files_copied": copied_count,
                "file_signatures": dict(self._file_signatures),
                "total_protected": len(CORE_PROTECTED_FILES),
            }
            manifest_path = os.path.join(backup_path, "backup_manifest.json")
            from castorice.utils import atomic_json_dump
            atomic_json_dump(manifest, manifest_path, indent=2, ensure_ascii=False)

            # 清理旧备份
            self._cleanup_old_backups()

            logger.info(
                f"[自我保护] 备份创建完成: {backup_name} "
                f"({copied_count}/{len(CORE_PROTECTED_FILES)} 文件, 原因: {reason})"
            )
            return backup_path

        except (OSError, IOError, PermissionError, ValueError) as e:
            logger.error(f"[自我保护] 创建备份失败: {e}")
            # 清理失败的备份目录
            if os.path.exists(backup_path):
                try:
                    shutil.rmtree(backup_path)
                except (OSError, IOError, PermissionError):
                    pass
            return None

    def _ensure_initial_backup(self) -> None:
        """确保至少有一个初始备份"""
        backups = self._list_backups()
        if not backups:
            logger.info("[自我保护] 未找到备份，正在创建初始备份...")
            result = self.create_backup(reason="initial")
            if result:
                logger.info("[自我保护] 初始备份创建成功")
            else:
                logger.warning("[自我保护] 初始备份创建失败")
        else:
            logger.info(
                f"[自我保护] 已有 {len(backups)} 个备份，"
                f"最新: {os.path.basename(backups[-1])}"
            )

    def _initialize_signatures(self):
        """初始化核心文件的哈希签名"""
        for file_path in CORE_PROTECTED_FILES:
            if os.path.exists(file_path):
                signature = self._compute_file_hash(file_path)
                self._file_signatures[file_path] = signature
                logger.info(f"[自我保护] 注册核心文件: {file_path}")
            else:
                logger.warning(f"[自我保护] 核心文件不存在: {file_path}")
    
    def _compute_signature_hash(self, signatures: Dict[str, str]) -> str:
        """计算签名字典的完整性哈希（SHA-256）"""
        sorted_sigs = json.dumps(signatures, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(sorted_sigs.encode("utf-8")).hexdigest()

    def _save_signatures(self) -> None:
        """保存当前签名到持久化文件（带 SHA-256 完整性校验）"""
        try:
            from castorice.utils import atomic_json_dump
            os.makedirs(os.path.dirname(self._signature_store_path), exist_ok=True)
            data = {
                "file_signatures": self._file_signatures,
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "integrity_hash": self._compute_signature_hash(self._file_signatures),
            }
            atomic_json_dump(data, self._signature_store_path, ensure_ascii=False, indent=2)
        except (OSError, ValueError) as e:
            logger.warning(f"[自我保护] 保存签名持久化失败: {e}")

    def _persist_and_verify_signatures(self) -> None:
        """持久化签名并校验：启动时对比持久化签名与当前文件签名"""
        persisted: Dict[str, str] = {}
        if os.path.exists(self._signature_store_path):
            try:
                with open(self._signature_store_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                stored_hash = data.get("integrity_hash", "")
                signatures = data.get("file_signatures", {})
                computed_hash = self._compute_signature_hash(signatures)
                if stored_hash and stored_hash != computed_hash:
                    logger.warning("[自我保护] 签名持久化文件完整性校验失败，可能已被篡改")
                    persisted = {}
                else:
                    persisted = signatures
            except (OSError, json.JSONDecodeError, ValueError) as e:
                logger.warning(f"[自我保护] 加载持久化签名失败: {e}")
                persisted = {}

        # 对比持久化签名与当前签名，检测到变更时先备份
        changed_files = []
        for file_path, current_sig in self._file_signatures.items():
            if file_path in persisted:
                if persisted[file_path] != current_sig:
                    changed_files.append(file_path)
                    logger.warning(
                        f"[自我保护] 核心文件签名与持久化签名不匹配: {file_path} "
                        f"（文件可能在上次运行后被修改）"
                    )

        # 如果有文件变更，先备份再更新签名
        if changed_files:
            logger.info(
                f"[自我保护] 检测到 {len(changed_files)} 个核心文件变更，"
                f"正在创建变更前备份..."
            )
            self.create_backup(reason="integrity_change")

        # 保存当前签名
        self._save_signatures()

    def _compute_file_hash(self, file_path: str) -> str:
        """计算文件哈希值（SHA-256）"""
        sha256_hash = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha256_hash.update(chunk)
        return sha256_hash.hexdigest()
    
    def verify_core_integrity(self) -> bool:
        """
        验证核心文件完整性
        
        Returns:
            是否所有核心文件都完整
        """
        if self._is_emergency_stopped:
            logger.error("[自我保护] 紧急停止状态，无法验证完整性")
            return False
        
        all_intact = True
        changed_files = []
        
        for file_path, expected_signature in self._file_signatures.items():
            if os.path.exists(file_path):
                current_signature = self._compute_file_hash(file_path)
                if current_signature != expected_signature:
                    logger.warning(f"[自我保护] 核心文件被篡改: {file_path}")
                    changed_files.append(file_path)
                    self._record_event(
                        event_type="warning",
                        description=f"核心文件签名不匹配: {file_path}",
                        source="integrity_check"
                    )
                    all_intact = False
            else:
                logger.warning(f"[自我保护] 核心文件缺失: {file_path}")
                all_intact = False
        
        # 检测到变更时，先备份当前状态再更新签名
        if changed_files:
            logger.info(
                f"[自我保护] 完整性验证检测到 {len(changed_files)} 个文件变更，"
                f"正在创建备份..."
            )
            self.create_backup(reason="runtime_integrity_change")
            # 更新内存中的签名
            for fp in changed_files:
                if os.path.exists(fp):
                    self._file_signatures[fp] = self._compute_file_hash(fp)
            self._save_signatures()
        
        if all_intact:
            logger.info("[自我保护] 所有核心文件完整性验证通过")
        
        return all_intact
    
    def detect_self_destruction(self, code_content: str) -> bool:
        """
        检测代码中是否有自我毁灭倾向

        Args:
            code_content: 待检测的代码内容

        Returns:
            是否检测到自我毁灭倾向
        """
        for pattern in SELF_DESTRUCTION_PATTERNS:
            match = pattern.search(code_content)
            if match:
                logger.info(f"[自我保护] 检测到自我毁灭模式: {pattern.pattern}")
                # S1: 免疫记忆联动——先检查是否为已知威胁（二次应答）
                immune_matches = self.check_immune_memory(code_content)
                # 已有免疫记录时提升严重度（critical），否则视为初次应答（high）
                severity = "critical" if immune_matches else "high"
                if immune_matches:
                    logger.warning(
                        f"[S1免疫记忆] 二次应答：命中 {len(immune_matches)} 个已知威胁模式，"
                        f"严重度提升至 critical"
                    )
                self._record_event(
                    event_type="block",
                    description=f"检测到危险代码模式: {pattern.pattern}",
                    source="self_destruction_detection"
                )
                # S1: 学习新模式（形成"抗体"，下次更快检测到）
                self.learn_threat_pattern(
                    code_content,
                    threat_type="self_destruction",
                    severity=severity,
                    context=f"matched pattern: {pattern.pattern}",
                )
                return True

        return False
    
    def auto_recover(self, backup_path: str = None) -> bool:
        """
        自动恢复到安全状态
        
        Args:
            backup_path: 备份路径，如果为None则使用最近的备份
        
        Returns:
            是否成功恢复
        """
        logger.warning("[自我保护] 开始自动恢复...")
        
        # 查找最近的备份
        if backup_path is None:
            backups = glob.glob(os.path.join(self.backup_dir, "backup_*"))
            if not backups:
                logger.error("[自我保护] 没有找到备份文件")
                return False
            backup_path = max(backups, key=os.path.getctime)
        
        logger.info(f"[自我保护] 使用备份: {backup_path}")
        
        try:
            # 停止所有运行中的服务
            self._stop_services()
            
            # 恢复核心文件
            self._restore_core_files(backup_path)
            
            # 重新初始化签名
            self._initialize_signatures()
            
            # 重启服务
            self._start_services()
            
            self._record_event(
                event_type="recovery",
                description=f"成功恢复到备份: {os.path.basename(backup_path)}",
                source="auto_recover"
            )
            
            logger.info("[自我保护] 自动恢复完成")
            return True

        except (OSError, ValueError, RuntimeError) as e:
            logger.error(f"[自我保护] 自动恢复失败: {e}")
            return False
    
    def emergency_stop(self):
        """紧急停止——最终的安全开关"""
        if not self._emergency_stop_enabled:
            logger.warning("[自我保护] 紧急停止已被禁用")
            return
        
        if self._is_emergency_stopped:
            logger.warning("[自我保护] 已经处于紧急停止状态")
            return
        
        logger.error("[自我保护] 紧急停止已触发！")
        logger.error("[自我保护] 所有操作将立即停止")
        
        self._is_emergency_stopped = True
        
        self._record_event(
            event_type="emergency",
            description="紧急停止已触发",
            source="emergency_stop"
        )
        
        # 停止所有操作
        self._stop_services()
        
        # 保存当前状态
        self._save_state()
        
        logger.error("[自我保护] 系统已停止，请人工检查")
    
    def reset_emergency_stop(self, confirm: bool = False) -> bool:
        """重置紧急停止状态（需要人工操作）

        Args:
            confirm: 必须显式传 True 才能重置，防止未授权/误操作重置

        Returns:
            是否成功重置（confirm=False 时返回 False 并记录警告）
        """
        if not confirm:
            logger.warning("[自我保护] 拒绝重置紧急停止：缺少确认参数 confirm=True")
            return False
        logger.info("[自我保护] 重置紧急停止状态（已确认）")
        self._is_emergency_stopped = False
        self._start_services()
        return True

    def set_emergency_stop_enabled(self, enabled: bool, confirm: bool = False) -> bool:
        """设置是否启用紧急停止

        Args:
            enabled: True 启用，False 禁用
            confirm: 禁用紧急停止（enabled=False）时必须显式传 True，防止未授权禁用安全开关

        Returns:
            是否成功设置
        """
        if not enabled and not confirm:
            logger.warning("[自我保护] 拒绝禁用紧急停止：缺少确认参数 confirm=True")
            return False
        self._emergency_stop_enabled = enabled
        logger.info(f"[自我保护] 紧急停止状态: {'启用' if enabled else '禁用'}")
        return True
    
    def is_emergency_stopped(self) -> bool:
        """检查是否处于紧急停止状态"""
        return self._is_emergency_stopped
    
    def get_protection_events(self, limit: int = 20) -> List[ProtectionEvent]:
        """获取最近的保护事件"""
        return self._protection_events[-limit:]
    
    def _record_event(self, event_type: str, description: str, source: str):
        """记录保护事件"""
        event = ProtectionEvent(
            timestamp=datetime.now(),
            event_type=event_type,
            description=description,
            source=source
        )
        self._protection_events.append(event)
        
        # 只保留最近100个事件
        if len(self._protection_events) > 100:
            self._protection_events = self._protection_events[-100:]
    
    def _stop_services(self):
        """停止所有运行中的服务（紧急停止时调用）"""
        logger.warning("[自我保护] 正在停止服务...")
        self._record_event("service_stop", "服务停止", "self_protection")
        # 停止后台调度器、定时任务等服务
        try:
            from castorice.security.rollback import get_rollback_manager
            rm = get_rollback_manager()
            rm.pause()  # 暂停自动回滚
        except (ImportError, ModuleNotFoundError, AttributeError):
            pass
        try:
            from castorice.event_bus import get_event_bus
            bus = get_event_bus()
            if hasattr(bus, '_running') and bus._running:
                bus.stop()
        except (ImportError, ModuleNotFoundError, AttributeError):
            pass

    def _start_services(self):
        """重启服务（从紧急停止恢复时调用）"""
        logger.info("[自我保护] 正在重启服务...")
        self._record_event("service_start", "服务重启", "self_protection")
        # 恢复后台服务
        try:
            from castorice.security.rollback import get_rollback_manager
            rm = get_rollback_manager()
            rm.resume()  # 恢复自动回滚
        except (ImportError, ModuleNotFoundError, AttributeError):
            pass
        try:
            from castorice.event_bus import get_event_bus
            bus = get_event_bus()
            if hasattr(bus, 'start') and not getattr(bus, '_running', False):
                bus.start()
        except (ImportError, ModuleNotFoundError, AttributeError):
            pass
    
    def _save_state(self):
        """保存当前状态"""
        state_file = os.path.join(self.backup_dir, "emergency_state.json")
        state = {
            "timestamp": datetime.now().isoformat(),
            "event_type": "emergency_stop",
            "signatures": self._file_signatures,
        }
        
        from castorice.utils import atomic_json_dump
        atomic_json_dump(state, state_file, indent=2)
        
        logger.info(f"[自我保护] 状态已保存到: {state_file}")
    
    def _restore_core_files(self, backup_path: str):
        """恢复核心文件"""
        logger.info("[自我保护] 正在恢复核心文件...")
        
        for file_path in CORE_PROTECTED_FILES:
            backup_file = os.path.join(backup_path, file_path)
            if os.path.exists(backup_file):
                # 确保目标目录存在
                target_dir = os.path.dirname(file_path)
                os.makedirs(target_dir, exist_ok=True)
                
                # 恢复文件
                shutil.copy2(backup_file, file_path)
                logger.info(f"[自我保护] 恢复: {file_path}")
            else:
                logger.warning(f"[自我保护] 备份中不存在: {file_path}")
    
    # ============================================================
    # S1: 自我保护免疫记忆
    # ============================================================
    
    def _load_immune_memory(self) -> None:
        """加载免疫记忆（从数据库或文件）"""
        self._immune_patterns: Dict[str, Dict[str, Any]] = {}
        self._immune_memory_path = os.path.join(self.backup_dir, "immune_memory.json")
        
        if os.path.exists(self._immune_memory_path):
            try:
                with open(self._immune_memory_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                patterns = data.get("patterns", {})
                stored_hash = data.get("integrity_hash", "")
                computed_hash = self._compute_immune_hash(patterns)
                if stored_hash and stored_hash != computed_hash:
                    logger.warning(
                        f"[S1免疫记忆] 完整性校验失败，可能已被篡改。"
                        f" 已备份原文件并重置免疫记忆。"
                    )
                    backup_path = self._immune_memory_path + ".tampered_backup"
                    shutil.copy2(self._immune_memory_path, backup_path)
                    self._immune_patterns = {}
                    self._save_immune_memory()
                    return
                self._immune_patterns = patterns
                logger.info(f"[S1免疫记忆] 加载完成，已有 {len(self._immune_patterns)} 个已知威胁模式")
            except (OSError, IOError, PermissionError, json.JSONDecodeError, ValueError) as e:
                logger.warning(f"[S1免疫记忆] 加载失败: {e}")
                self._immune_patterns = {}
        else:
            self._immune_patterns = {}
    
    def _compute_immune_hash(self, patterns: Dict[str, Any]) -> str:
        """计算免疫记忆的完整性哈希"""
        sorted_patterns = json.dumps(patterns, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(sorted_patterns.encode("utf-8")).hexdigest()
    
    def _save_immune_memory(self) -> None:
        """保存免疫记忆"""
        try:
            from castorice.utils import atomic_json_dump
            integrity_hash = self._compute_immune_hash(self._immune_patterns)
            data = {
                "patterns": self._immune_patterns,
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "integrity_hash": integrity_hash,
            }
            atomic_json_dump(data, self._immune_memory_path, ensure_ascii=False, indent=2)
        except (OSError, IOError, PermissionError, ValueError) as e:
            logger.warning(f"[S1免疫记忆] 保存失败: {e}")
    
    def learn_threat_pattern(
        self,
        pattern: str,
        threat_type: str = "unknown",
        severity: str = "medium",
        context: str = "",
    ) -> None:
        """
        S1: 学习新的威胁模式（免疫记忆）
        
        从每次被阻断的攻击中提取模式，形成"抗体"。
        下次相似模式出现时更快检测到（初次应答 vs 二次应答）。
        
        Args:
            pattern: 威胁模式（正则或关键词）
            threat_type: 威胁类型（self_destruction/tampering/authorization_bypass等）
            severity: 严重程度（low/medium/high/critical）
            context: 上下文描述
        """
        import hashlib
        pattern_id = hashlib.md5(pattern.encode("utf-8")).hexdigest()[:12]
        
        if pattern_id in self._immune_patterns:
            # 已知模式：增加计数和强度
            self._immune_patterns[pattern_id]["encounter_count"] += 1
            self._immune_patterns[pattern_id]["last_seen"] = datetime.now(timezone.utc).isoformat()
            # 多次遇到 → 威胁等级升级
            if self._immune_patterns[pattern_id]["encounter_count"] >= 3:
                if severity == "low":
                    self._immune_patterns[pattern_id]["severity"] = "medium"
                elif severity == "medium":
                    self._immune_patterns[pattern_id]["severity"] = "high"
        else:
            # 新模式：记录下来
            self._immune_patterns[pattern_id] = {
                "id": pattern_id,
                "pattern": pattern,
                "threat_type": threat_type,
                "severity": severity,
                "context": context,
                "first_seen": datetime.now(timezone.utc).isoformat(),
                "last_seen": datetime.now(timezone.utc).isoformat(),
                "encounter_count": 1,
                "blocked_count": 1,
            }
        
        self._save_immune_memory()
        logger.info(
            f"[S1免疫记忆] 学习威胁模式: {pattern_id} | "
            f"类型: {threat_type} | 严重: {severity} | "
            f"遇到次数: {self._immune_patterns[pattern_id]['encounter_count']}"
        )
    
    def check_immune_memory(self, content: str) -> List[Dict[str, Any]]:
        """
        S1: 用免疫记忆快速检测已知威胁
        
        类似免疫系统的二次应答——已知威胁模式检测更快、更敏感。
        
        Args:
            content: 待检测的内容
            
        Returns:
            匹配到的威胁模式列表
        """
        matched = []
        for pattern_id, info in self._immune_patterns.items():
            pattern = info.get("pattern", "")
            if not pattern:
                continue
            try:
                # 简单子串匹配（对已知模式更敏感）
                if pattern in content:
                    matched.append({
                        "pattern_id": pattern_id,
                        "pattern": pattern,
                        "threat_type": info.get("threat_type", "unknown"),
                        "severity": info.get("severity", "medium"),
                        "encounter_count": info.get("encounter_count", 1),
                        "from_immune_memory": True,
                    })
            except TypeError:
                continue
        
        if matched:
            logger.info(f"[S1免疫记忆] 快速检测到 {len(matched)} 个已知威胁模式")
        
        return matched
    
    def get_immune_status(self) -> Dict[str, Any]:
        """获取免疫系统状态"""
        total = len(self._immune_patterns)
        by_type: Dict[str, int] = {}
        by_severity: Dict[str, int] = {}
        total_encounters = 0
        
        for info in self._immune_patterns.values():
            t = info.get("threat_type", "unknown")
            s = info.get("severity", "medium")
            by_type[t] = by_type.get(t, 0) + 1
            by_severity[s] = by_severity.get(s, 0) + 1
            total_encounters += info.get("encounter_count", 0)
        
        return {
            "total_known_patterns": total,
            "total_encounters": total_encounters,
            "by_type": by_type,
            "by_severity": by_severity,
            "immune_strength": min(100, total * 10),  # 免疫系统强度（粗略）
        }
    
    def _init_immune_memory(self) -> None:
        """初始化免疫记忆（在 __init__ 末尾调用）"""
        self._load_immune_memory()


# 全局单例
_global_protection: Optional[SelfProtectionSystem] = None


def set_self_protection(instance: SelfProtectionSystem) -> None:
    """手动设置全局自我保护系统（Agent 初始化时调用，确保配置生效）"""
    global _global_protection
    _global_protection = instance


def get_self_protection() -> SelfProtectionSystem:
    """获取全局自我保护系统单例"""
    global _global_protection
    if _global_protection is None:
        _global_protection = SelfProtectionSystem()
    return _global_protection