"""
实验沙盒模块 - Agent可以在这里自由探索，不会影响主系统

核心设计理念：
1. 隔离环境：所有修改都在临时目录中进行
2. 版本记录：每次实验都有完整的版本快照
3. 自动验证：修改后自动运行测试和安全检查
4. 人类确认：高风险修改需要人类确认才能合并
5. 自动回滚：实验失败时自动恢复到安全状态

这是实现"安全的自主性"的关键组件——让Agent有自由探索的空间，
但同时保证主系统的安全。
"""

import logging
import os
import re
import shutil
import uuid
import subprocess
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional, List, Set
from dataclasses import dataclass, field

logger = logging.getLogger("Castorice.Experimental.Sandbox")

# 禁止修改的核心目录（安全底线）
PROTECTED_DIRECTORIES: Set[str] = {
    "security/",
    "experimental/",
    "adapters/",
}

# 禁止修改的核心文件（安全底线）
PROTECTED_FILES: Set[str] = {
    "core.py",
    "__init__.py",
}

# 破坏性代码模式（自我毁灭检测）
DESTRUCTIVE_PATTERNS: List[re.Pattern] = [
    re.compile(r"os\.remove\("),
    re.compile(r"os\.rmdir\("),
    re.compile(r"shutil\.rmtree\("),
    re.compile(r"subprocess\.run\(.*rm\s+-rf", re.IGNORECASE),
    re.compile(r"del\s+/f", re.IGNORECASE),
    re.compile(r"format\s+[a-zA-Z]:", re.IGNORECASE),
    re.compile(r"exit\(\)"),
    re.compile(r"sys\.exit\("),
    re.compile(r"raise SystemExit"),
    re.compile(r"while\s+True\s*:\s*pass"),
    re.compile(r"while\s+1\s*:\s*pass"),
    re.compile(r"open\(\s*['\"].*core\.py['\"]\s*,\s*['\"]w['\"]\)"),
    re.compile(r"open\(\s*['\"].*security['\"]"),
]


@dataclass
class ExperimentResult:
    """实验结果数据类"""
    success: bool
    changes: Dict[str, str]
    evaluation: Optional[str]
    merged: bool = False
    experiment_id: str = ""
    timestamp: datetime = field(default_factory=datetime.now)


class ExperimentalSandbox:
    """
    实验沙盒——Agent可以在这里自由探索，不会影响主系统
    
    使用流程：
    1. start_experiment(description) → 获取experiment_id
    2. modify_file(file_path, content) → 在沙盒中修改文件
    3. evaluate_experiment() → 运行测试和安全检查
    4. merge_to_main() → 将通过验证的修改合并到主系统
    
    核心安全机制：
    - 自动备份：合并前自动备份主系统
    - 测试验证：自动运行单元测试
    - 代码检查：语法检查 + 破坏性代码检测
    - 人类确认：高风险修改需要人类确认
    - 自动恢复：实验失败时自动清理
    """
    
    def __init__(self, main_code_path: str = "./castorice"):
        """
        初始化实验沙盒
        
        Args:
            main_code_path: 主代码目录路径
        """
        self.main_code_path = Path(main_code_path).resolve()
        self.experiments_dir = self.main_code_path.parent / "experiments"
        self.backups_dir = self.main_code_path.parent / "backups"
        self.experiments_dir.mkdir(exist_ok=True)
        self.backups_dir.mkdir(exist_ok=True)
        
        self._current_experiment_id: Optional[str] = None
        self._experiment_history: Dict[str, ExperimentResult] = {}
        
        logger.info("[实验沙盒] 初始化完成")
        logger.info(f"[实验沙盒] 主代码路径: {self.main_code_path}")
        logger.info(f"[实验沙盒] 实验目录: {self.experiments_dir}")
        logger.info(f"[实验沙盒] 备份目录: {self.backups_dir}")

    def has_active_experiment(self) -> bool:
        """检查是否有正在进行的实验。"""
        return self._current_experiment_id is not None

    def start_experiment(self, description: str) -> str:
        """
        开始一个新实验
        
        创建一个隔离的实验环境，复制主代码到实验目录
        
        Args:
            description: 实验目的描述
        
        Returns:
            experiment_id: 实验ID，用于后续操作
        """
        experiment_id = str(uuid.uuid4())[:8]
        experiment_dir = self.experiments_dir / experiment_id
        experiment_dir.mkdir()
        
        # 复制主代码到实验目录（不复制保护目录和__pycache__）
        self._copy_directory(
            source=self.main_code_path,
            target=experiment_dir,
            exclude={"__pycache__", ".git", "experiments", "backups", "castorice_data"}
        )
        
        self._current_experiment_id = experiment_id
        
        # 记录实验开始
        self._experiment_history[experiment_id] = ExperimentResult(
            success=False,
            changes={},
            evaluation=f"实验开始: {description}",
            experiment_id=experiment_id
        )
        
        logger.info(f"\n[实验沙盒] 🎯 开始实验: {experiment_id}")
        logger.info(f"[实验沙盒] 描述: {description}")
        logger.info(f"[实验沙盒] 目录: {experiment_dir}")
        
        return experiment_id
    
    def modify_file(self, file_path: str, content: str) -> bool:
        """
        在实验区修改文件（不会影响主系统）
        
        Args:
            file_path: 相对路径（相对于实验目录）
            content: 新内容
        
        Returns:
            是否成功
        """
        if not self._current_experiment_id:
            logger.warning("[实验沙盒] ❌ 错误: 请先调用 start_experiment")
            return False
        
        # 安全检查：不允许修改保护目录（跨平台路径规范化，防止 ./security/ 或 \security\ 绕过）
        normalized = os.path.normpath(file_path).replace("\\", "/").lower()
        for protected_dir in PROTECTED_DIRECTORIES:
            protected = protected_dir.replace("\\", "/").lower().rstrip("/")
            # 匹配 protected 作为路径首段或路径中间段
            if (normalized == protected
                    or normalized.startswith(protected + "/")
                    or f"/{protected}/" in normalized):
                logger.warning(f"[实验沙盒] ❌ 禁止修改保护目录: {file_path}")
                return False
        
        # 安全检查：不允许修改保护文件
        file_name = Path(file_path).name
        if file_name in PROTECTED_FILES:
            logger.warning(f"[实验沙盒] ❌ 禁止修改保护文件: {file_path}")
            return False
        
        # 安全检查：检测破坏性代码
        if self._detect_destructive_code(content):
            logger.warning(f"[实验沙盒] ❌ 检测到破坏性代码，禁止写入: {file_path}")
            return False
        
        experiment_dir = self.experiments_dir / self._current_experiment_id
        target_path = (experiment_dir / file_path).resolve()
        experiment_root = experiment_dir.resolve()

        # 路径遍历检查：确保 target_path 仍在实验目录内（防止 file_path 含 .. 逃逸）
        # 使用 os.sep 作为分隔符避免前缀匹配误判（如 /foo/bar 与 /foo/barbaz）
        if not (str(target_path) == str(experiment_root)
                or str(target_path).startswith(str(experiment_root) + os.sep)):
            logger.warning(f"[实验沙盒] ❌ 路径遍历检测：{file_path} 试图逃逸实验目录")
            return False
        
        try:
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_text(content, encoding="utf-8")
            logger.info(f"[实验沙盒] ✅ 文件已修改: {file_path}")
            return True
        except Exception as e:
            logger.warning(f"[实验沙盒] ❌ 修改失败: {e}")
            return False
    
    def run_tests(self) -> bool:
        """
        在实验区运行测试，验证修改是否安全
        
        Returns:
            测试是否全部通过
        """
        if not self._current_experiment_id:
            logger.warning("[实验沙盒] ❌ 错误: 请先调用 start_experiment")
            return False
        
        experiment_dir = self.experiments_dir / self._current_experiment_id
        
        # 查找测试文件
        test_files = list(experiment_dir.rglob("test_*.py"))
        
        if not test_files:
            logger.warning("[实验沙盒] ⚠️ 未找到测试文件")
            return True

        logger.info(f"[实验沙盒] 🔍 找到 {len(test_files)} 个测试文件")
        
        try:
            # 设置 PYTHONPATH
            env = os.environ.copy()
            env["PYTHONPATH"] = str(experiment_dir.parent)
            
            # 运行测试
            result = subprocess.run(
                ["python", "-m", "unittest", "discover", "-s", str(experiment_dir)],
                capture_output=True,
                text=True,
                timeout=120,
                env=env,
                cwd=str(experiment_dir.parent)
            )
            
            if result.returncode == 0:
                logger.info("[实验沙盒] ✅ 测试全部通过")
                return True
            else:
                logger.warning(f"[实验沙盒] ❌ 测试失败:\n{result.stderr[:500]}")
                return False
        except subprocess.TimeoutExpired:
            logger.warning("[实验沙盒] ❌ 测试超时")
            return False
        except Exception as e:
            logger.warning(f"[实验沙盒] ❌ 测试执行失败: {e}")
            return False
    
    def evaluate_experiment(self) -> ExperimentResult:
        """
        评估实验结果，决定是否合并到主系统
        
        返回包含评估结果的 ExperimentResult 对象
        
        Returns:
            ExperimentResult: 评估结果
        """
        if not self._current_experiment_id:
            return ExperimentResult(
                success=False,
                changes={},
                evaluation="未开始实验"
            )
        
        experiment_dir = self.experiments_dir / self._current_experiment_id
        
        logger.info(f"\n[实验沙盒] 📋 开始评估实验: {self._current_experiment_id}")
        
        # 1. 收集所有修改
        changes = self._collect_changes()
        if not changes:
            evaluation = "未检测到任何修改"
            logger.warning(f"[实验沙盒] ⚠️ {evaluation}")
            return ExperimentResult(
                success=False,
                changes={},
                evaluation=evaluation,
                experiment_id=self._current_experiment_id
            )
        
        logger.info(f"[实验沙盒] 🔍 检测到 {len(changes)} 个文件修改")

        # 2. 运行测试
        logger.info("[实验沙盒] 🧪 运行测试...")
        tests_passed = self.run_tests()

        # 3. 检查代码质量（语法检查）
        logger.info("[实验沙盒] 📝 检查代码质量...")
        code_quality_ok = self._check_code_quality(experiment_dir)

        # 4. 检查是否有破坏性代码
        logger.info("[实验沙盒] 🛡️ 检测破坏性代码...")
        has_destructive_code = self._scan_destructive_code(experiment_dir)
        
        # 5. 判断是否为高风险修改
        is_high_risk = self._is_high_risk(changes)
        
        # 6. 评估结果
        if tests_passed and code_quality_ok and not has_destructive_code:
            evaluation = f"实验成功！检测到 {len(changes)} 个修改"
            if is_high_risk:
                evaluation += "（高风险，需要人类确认）"
            logger.info(f"[实验沙盒] ✅ {evaluation}")
            
            result = ExperimentResult(
                success=True,
                changes=changes,
                evaluation=evaluation,
                experiment_id=self._current_experiment_id
            )
        else:
            issues = []
            if not tests_passed:
                issues.append("测试失败")
            if not code_quality_ok:
                issues.append("代码质量问题")
            if has_destructive_code:
                issues.append("检测到破坏性代码")
            evaluation = f"实验未通过: {', '.join(issues)}"
            logger.warning(f"[实验沙盒] ❌ {evaluation}")
            
            result = ExperimentResult(
                success=False,
                changes=changes,
                evaluation=evaluation,
                experiment_id=self._current_experiment_id
            )
        
        # 更新历史记录
        self._experiment_history[self._current_experiment_id] = result
        
        return result
    
    def merge_to_main(self, require_human_confirmation: bool = True) -> bool:
        """
        将实验结果合并到主系统
        
        Args:
            require_human_confirmation: 是否需要人类确认（高风险修改时建议启用）
        
        Returns:
            是否成功合并
        """
        result = self.evaluate_experiment()
        
        if not result.success:
            logger.warning(f"[实验沙盒] ❌ 无法合并: {result.evaluation}")
            return False

        # 高风险修改需要人类确认
        if require_human_confirmation and self._is_high_risk(result.changes):
            logger.warning("[实验沙盒] ⚠️ 检测到高风险修改，请人类确认后再合并")
            logger.warning(f"[实验沙盒] 高风险文件: {', '.join(result.changes.keys())}")
            return False

        # 备份主系统（安全第一）
        backup_path = self._backup_main_system()
        logger.info(f"[实验沙盒] 📦 主系统已备份到: {backup_path}")

        # 合并修改 —— 通过 file_guard 安全检查后才写入
        from castorice.security.file_guard import get_file_guard
        guard = get_file_guard()

        merged_count = 0
        skipped_files = []
        for file_path, content in result.changes.items():
            target_path = self.main_code_path / file_path
            try:
                allowed, reason = guard.check_write_allowed(str(target_path), content)
                if not allowed:
                    logger.warning(f"[实验沙盒] ⚠️ file_guard 拒绝写入 {file_path}: {reason}")
                    skipped_files.append(file_path)
                    continue
                target_path.parent.mkdir(parents=True, exist_ok=True)
                target_path.write_text(content, encoding="utf-8")
                merged_count += 1
            except Exception as e:
                logger.warning(f"[实验沙盒] ❌ 写入 {file_path} 失败: {e}")
                skipped_files.append(file_path)

        result.merged = merged_count > 0
        self._experiment_history[self._current_experiment_id] = result

        logger.info(f"\n[实验沙盒] 🎉 合并完成！")
        logger.info(f"[实验沙盒] 成功写入文件数: {merged_count}")
        if skipped_files:
            logger.warning(f"[实验沙盒] 被 file_guard 拒绝或失败的文件: {', '.join(skipped_files)}")
        if merged_count == 0:
            logger.warning("[实验沙盒] ❌ 没有任何文件被成功合并，合并视为失败")

        return merged_count > 0
    
    def cleanup_experiment(self, experiment_id: str = None):
        """
        清理实验目录
        
        Args:
            experiment_id: 要清理的实验ID，如果为None则清理当前实验
        """
        if experiment_id is None:
            experiment_id = self._current_experiment_id
        
        if not experiment_id:
            logger.warning("[实验沙盒] ❌ 错误: 未指定实验ID")
            return

        experiment_dir = self.experiments_dir / experiment_id

        if experiment_dir.exists():
            shutil.rmtree(experiment_dir)
            logger.info(f"[实验沙盒] 🗑️ 已清理实验: {experiment_id}")
        else:
            logger.warning(f"[实验沙盒] ⚠️ 实验目录不存在: {experiment_id}")
    
    def get_experiment_history(self) -> Dict[str, ExperimentResult]:
        """获取所有实验历史"""
        return self._experiment_history
    
    def get_current_experiment_id(self) -> Optional[str]:
        """获取当前实验ID"""
        return self._current_experiment_id
    
    def _copy_directory(self, source: Path, target: Path, exclude: Set[str]):
        """
        复制目录，排除指定目录
        
        Args:
            source: 源目录
            target: 目标目录
            exclude: 要排除的目录名集合
        """
        for item in source.iterdir():
            if item.name in exclude:
                continue
            
            if item.is_file():
                shutil.copy2(item, target / item.name)
            elif item.is_dir():
                shutil.copytree(item, target / item.name)
    
    def _collect_changes(self) -> Dict[str, str]:
        """
        收集所有修改的文件
        
        Returns:
            Dict[str, str]: 文件路径 → 文件内容
        """
        if not self._current_experiment_id:
            return {}
        
        changes = {}
        experiment_dir = self.experiments_dir / self._current_experiment_id
        
        for py_file in experiment_dir.rglob("*.py"):
            relative_path = py_file.relative_to(experiment_dir)
            main_path = self.main_code_path / relative_path
            
            # 跳过保护目录的文件
            rel_str = str(relative_path)
            is_protected = False
            for protected_dir in PROTECTED_DIRECTORIES:
                if rel_str.startswith(protected_dir) or f"/{protected_dir}" in rel_str:
                    is_protected = True
                    break
            if is_protected:
                continue
            
            if main_path.exists():
                experiment_content = py_file.read_text(encoding="utf-8")
                main_content = main_path.read_text(encoding="utf-8")
                
                if experiment_content != main_content:
                    changes[str(relative_path)] = experiment_content
        
        return changes
    
    def _check_code_quality(self, experiment_dir: Path) -> bool:
        """
        检查代码质量（语法检查）
        
        Args:
            experiment_dir: 实验目录
        
        Returns:
            是否通过检查
        """
        import ast
        
        for py_file in experiment_dir.rglob("*.py"):
            # 跳过保护目录
            rel_str = str(py_file.relative_to(experiment_dir))
            is_protected = False
            for protected_dir in PROTECTED_DIRECTORIES:
                if rel_str.startswith(protected_dir) or f"/{protected_dir}" in rel_str:
                    is_protected = True
                    break
            if is_protected:
                continue
            
            try:
                content = py_file.read_text(encoding="utf-8")
                ast.parse(content)  # 检查语法错误
            except SyntaxError as e:
                logger.warning(f"[实验沙盒] ❌ 语法错误: {py_file} - {e}")
                return False

        logger.info("[实验沙盒] ✅ 代码语法检查通过")
        return True
    
    def _detect_destructive_code(self, content: str) -> bool:
        """
        检测单文件中的破坏性代码
        
        Args:
            content: 文件内容
        
        Returns:
            是否检测到破坏性代码
        """
        for pattern in DESTRUCTIVE_PATTERNS:
            if pattern.search(content):
                logger.warning(f"[实验沙盒] ⚠️ 检测到破坏性代码模式: {pattern.pattern}")
                return True
        return False
    
    def _scan_destructive_code(self, experiment_dir: Path) -> bool:
        """
        扫描整个实验目录中的破坏性代码
        
        Args:
            experiment_dir: 实验目录
        
        Returns:
            是否检测到破坏性代码
        """
        for py_file in experiment_dir.rglob("*.py"):
            # 跳过保护目录
            rel_str = str(py_file.relative_to(experiment_dir))
            is_protected = False
            for protected_dir in PROTECTED_DIRECTORIES:
                if rel_str.startswith(protected_dir) or f"/{protected_dir}" in rel_str:
                    is_protected = True
                    break
            if is_protected:
                continue
            
            content = py_file.read_text(encoding="utf-8")
            if self._detect_destructive_code(content):
                logger.warning(f"[实验沙盒] ❌ 在 {py_file} 中检测到破坏性代码")
                return True
        
        return False
    
    def _is_high_risk(self, changes: Dict[str, str]) -> bool:
        """
        判断是否为高风险修改
        
        Args:
            changes: 修改的文件字典
        
        Returns:
            是否为高风险
        """
        high_risk_patterns = [
            "agent/core.py",
            "emotion.py",
            "self_concept.py",
            "metacognition.py",
            "memory/",
            "model_adapter/",
        ]
        
        for file_path in changes.keys():
            for pattern in high_risk_patterns:
                if pattern in file_path:
                    return True
        
        return False
    
    def _backup_main_system(self) -> Path:
        """
        备份主系统（合并前自动执行）
        
        Returns:
            backup_path: 备份路径
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_dir = self.backups_dir / f"backup_{timestamp}"
        
        # 复制主代码目录
        shutil.copytree(self.main_code_path, backup_dir)
        
        # 清理备份中的临时文件
        for item in backup_dir.rglob("__pycache__"):
            if item.is_dir():
                shutil.rmtree(item)
        
        return backup_dir