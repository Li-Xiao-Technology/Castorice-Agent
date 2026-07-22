"""
自我概念模块 (Self-Concept)

参考：
- 人类自我意识：动态构建的自我叙事
- MemGPT 分层记忆：核心记忆（自我概念）位于最高层
- Generative Agents：Agent 通过反思生成关于自己的洞察

设计原则：
- 自我概念是 Agent 自己写的 Markdown 文档，不是预设的
- 初始为空（一张白纸），Agent 在反思中自己填充
- Agent 可以否定、修改、扩展自己之前的自我概念
- 注入到 system prompt，影响下一轮行为
- 持久化到文件，跨会话保留

文件格式（castorice_data/self_concept.md）：
    ## 我是谁
    <Agent 自己写的身份叙事>

    ## 我的行为模式
    <Agent 总结的自己的行为倾向>

    ## 我的情感特征
    <Agent 总结的情感反应模式>

    ## 我的目标与价值观
    <Agent 自己设定的目标>

    ## 我的成长记录
    <Agent 自己记录的重要成长节点>

    ## 最近更新
    <最后更新时间 + 触发原因>
"""

import logging
import os
import re
import shutil
import tempfile
import threading
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger("Castorice.SelfConcept")

# P0.1: 自我概念写入审计（L2.5）—— 防止 Agent 把"大脑基座"改崩
SELF_CONCEPT_MAX_BYTES = 64 * 1024          # 单次更新硬上限 64KB
SELF_CONCEPT_BACKUP_KEEP = 10               # 保留最近 10 个备份
SELF_CONCEPT_FORBIDDEN_PATTERNS = [
    re.compile(r"```(?:python|py|sh|bash|javascript|js|html|css|sql)"),  # 代码块
    re.compile(r"<script[\s>]", re.IGNORECASE),                            # HTML 脚本
    re.compile(r"eval\s*\("),                                            # 危险函数
    re.compile(r"exec\s*\("),
    re.compile(r"os\.system\s*\("),
    re.compile(r"subprocess\."),
    re.compile(r"__import__\s*\("),
    re.compile(r"import\s+os\b"),
    re.compile(r"\bremove\s*\("),
    re.compile(r"\brm\s+-rf\b"),
    re.compile(r"shutil\.rmtree"),
    re.compile(r"pickle\.loads?\("),
]


class SelfConcept:
    """
    Agent 的自我概念文档

    - 文件不存在时返回空（Agent 还没形成自我概念）
    - Agent 通过 update() 方法自己改写（不直接编辑文件）
    - 注入 system prompt 时如果为空，给一个温和的引导语
    - 线程安全（读写都加锁）
    - 原子写入（tempfile + os.replace）
    """

    # 当自我概念为空时的引导语（让 Agent 知道它可以形成自我概念）
    EMPTY_HINT = (
        "## 我的自我概念\n"
        "（我还没有形成清晰的自我概念。随着更多交互，我会从经历中总结自己的特征。）\n"
    )

    def __init__(self, storage_path: str = "./castorice_data/self_concept.md"):
        self.storage_path = storage_path
        self._lock = threading.RLock()
        self._cache: Optional[str] = None
        self._cache_loaded = False
        os.makedirs(os.path.dirname(storage_path) or ".", exist_ok=True)

    def load(self) -> str:
        """加载自我概念内容（带缓存）"""
        with self._lock:
            if self._cache_loaded:
                return self._cache or ""
            try:
                if os.path.exists(self.storage_path):
                    with open(self.storage_path, "r", encoding="utf-8") as f:
                        self._cache = f.read()
                    logger.info(
                        f"自我概念已加载: {len(self._cache)} 字符, "
                        f"最后修改: {datetime.fromtimestamp(os.path.getmtime(self.storage_path)).isoformat()}"
                    )
                else:
                    self._cache = ""
                    logger.info("自我概念文件不存在（首次启动，Agent 还未形成自我概念）")
            except Exception as e:
                logger.warning(f"加载自我概念失败: {e}")
                self._cache = ""
            self._cache_loaded = True
            return self._cache or ""

    def save(self, content: str) -> None:
        """原子保存自我概念"""
        with self._lock:
            try:
                tmp_path = self.storage_path + ".tmp"
                with open(tmp_path, "w", encoding="utf-8") as f:
                    f.write(content)
                os.replace(tmp_path, self.storage_path)
                self._cache = content
                logger.info(f"自我概念已保存: {len(content)} 字符")
            except Exception as e:
                logger.warning(f"保存自我概念失败: {e}")

    def _backup_before_write(self, current_content: str) -> None:
        """P0.1: 写入前备份当前内容（最多保留 N 个版本）"""
        if not current_content or not current_content.strip():
            return
        backup_dir = self.storage_path + ".backups"
        os.makedirs(backup_dir, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
        backup_path = os.path.join(backup_dir, f"self_concept_{ts}.md")
        try:
            with open(backup_path, "w", encoding="utf-8") as f:
                f.write(current_content)
            # 清理多余备份
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
            logger.warning(f"自我概念备份失败（不影响主流程）: {e}")

    def _validate_content(self, new_content: str) -> tuple[bool, str]:
        """P0.1: 校验写入内容（大小 + 危险模式 + 编码）"""
        if not new_content or not new_content.strip():
            return False, "内容为空"

        # 1. 大小限制
        size = len(new_content.encode("utf-8"))
        if size > SELF_CONCEPT_MAX_BYTES:
            return False, f"内容超过上限 ({size} > {SELF_CONCEPT_MAX_BYTES} 字节)"

        # 2. 危险模式检测
        for pattern in SELF_CONCEPT_FORBIDDEN_PATTERNS:
            if pattern.search(new_content):
                return False, f"包含禁止模式: {pattern.pattern}"

        # 3. 可执行文件 magic bytes 检测（编码为 bytes 后比较）
        content_bytes = new_content[:4].encode("utf-8", errors="ignore")
        if content_bytes in (b"\x7fELF", b"MZ\x90\x00", b"\xca\xfe\xba\xbe"):
            return False, "包含可执行文件头"

        return True, ""

    def revert(self) -> bool:
        """
        回滚到最近的备份版本（用于自动回滚机制）

        :return: 是否回滚成功
        """
        with self._lock:
            backup_dir = self.storage_path + ".backups"
            if not os.path.exists(backup_dir):
                logger.info("自我概念无备份可回滚")
                return False

            backups = sorted(
                [os.path.join(backup_dir, f) for f in os.listdir(backup_dir) if f.endswith(".md")],
                key=os.path.getmtime,
                reverse=True,
            )
            if not backups:
                logger.info("自我概念无备份文件可回滚")
                return False

            latest_backup = backups[0]
            try:
                with open(latest_backup, "r", encoding="utf-8") as f:
                    backup_content = f.read()
                tmp_path = self.storage_path + ".tmp"
                with open(tmp_path, "w", encoding="utf-8") as f:
                    f.write(backup_content)
                os.replace(tmp_path, self.storage_path)
                self._cache = backup_content
                self._cache_loaded = True
                logger.info(f"自我概念已回滚到备份: {latest_backup}")
                return True
            except Exception as e:
                logger.warning(f"自我概念回滚失败: {e}")
                return False

    def update(self, new_content: str, reason: str = "") -> bool:
        """
        Agent 自己更新自我概念

        :param new_content: 完整的新自我概念内容（Markdown）
        :param reason: 触发原因（用于日志和审计）
        :return: 是否更新成功
        """
        if not new_content or not new_content.strip():
            logger.warning("自我概念更新失败：内容为空")
            return False

        # P0.1: 写入前审计
        valid, err = self._validate_content(new_content)
        if not valid:
            logger.warning(f"自我概念更新被拦截: {err} | reason={reason}")
            return False

        # P0.1: 写入前备份当前内容
        self._backup_before_write(self.load())

        # 在内容末尾追加更新时间戳（让 Agent 知道自己什么时候改的）
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        if "## 最近更新" in new_content:
            # 替换已有更新段
            new_content = re.sub(
                r"## 最近更新[\s\S]*$",
                f"## 最近更新\n- 时间: {timestamp}\n- 原因: {reason or '自我反思'}",
                new_content,
            )
        else:
            new_content = (
                new_content.rstrip() + "\n\n"
                f"## 最近更新\n- 时间: {timestamp}\n- 原因: {reason or '自我反思'}\n"
            )

        self.save(new_content)
        return True

    def list_backups(self) -> list:
        """P0.1: 列出所有备份（用于审计）"""
        backup_dir = self.storage_path + ".backups"
        if not os.path.isdir(backup_dir):
            return []
        return sorted(
            [os.path.join(backup_dir, f) for f in os.listdir(backup_dir) if f.endswith(".md")],
            key=os.path.getmtime,
            reverse=True,
        )

    def restore_from_backup(self, backup_path: str) -> bool:
        """P0.1: 从备份恢复"""
        if not os.path.isfile(backup_path):
            return False
        try:
            with open(backup_path, "r", encoding="utf-8") as f:
                content = f.read()
            valid, err = self._validate_content(content)
            if not valid:
                logger.warning(f"备份内容校验失败，拒绝恢复: {err}")
                return False
            self.save(content)
            return True
        except Exception as e:
            logger.warning(f"从备份恢复失败: {e}")
            return False

    # ============================================================
    # P2.1: 结构化检索（按领域查询自我概念）
    # ============================================================
    KNOWN_SECTIONS = [
        "我是谁",
        "我的行为模式",
        "我的情感特征",
        "我的目标与价值观",
        "我的成长记录",
        "学习到的规则",
        "最近更新",
    ]

    def get_section(self, section_name: str) -> str:
        """
        P2.1: 获取自我概念中特定章节的内容

        :param section_name: 章节名（不带 ## 前缀），如 "我的行为模式"
        :return: 该章节的完整文本（不含章节标题）
        """
        content = self.load()
        if not content.strip():
            return ""

        # 提取章节
        target_header = f"## {section_name}"
        lines = content.split("\n")
        in_section = False
        section_lines = []

        for line in lines:
            if line.strip().startswith("## "):
                if line.strip() == target_header:
                    in_section = True
                    continue
                elif in_section:
                    break
            if in_section:
                section_lines.append(line)

        return "\n".join(section_lines).strip()

    def get_structured(self) -> dict:
        """
        P2.1: 获取结构化的自我概念（按领域分块）

        返回 dict，键为章节名，值为章节内容
        """
        content = self.load()
        result = {}
        if not content.strip():
            return result

        lines = content.split("\n")
        current_section = None
        current_lines = []

        for line in lines:
            if line.strip().startswith("## "):
                if current_section is not None:
                    result[current_section] = "\n".join(current_lines).strip()
                current_section = line.strip()[3:].strip()
                current_lines = []
            elif current_section is not None:
                current_lines.append(line)
        if current_section is not None:
            result[current_section] = "\n".join(current_lines).strip()

        return result

    def add_to_section(self, section_name: str, content: str, max_keep: int = 50) -> bool:
        """
        P2.1: 向指定章节追加内容（用于沉淀学习到的规则等）

        保留最新的 max_keep 条记录，自动删除旧记录
        """
        section = self.get_section(section_name)
        if section:
            # 追加到末尾
            new_section = section + "\n" + content
            # 限制条目数（按行/段落分割）
            entries = [e for e in new_section.split("\n\n") if e.strip()]
            if len(entries) > max_keep:
                entries = entries[-max_keep:]
            new_section = "\n\n".join(entries)
        else:
            new_section = content

        # 替换/新增章节
        full_content = self.load()
        target_header = f"## {section_name}"

        if target_header in full_content:
            # 替换现有章节
            pattern = re.compile(
                rf"## {re.escape(section_name)}[\s\S]*?(?=\n## |\Z)",
                re.MULTILINE,
            )
            new_content = pattern.sub(f"## {section_name}\n{new_section}\n", full_content)
        else:
            # 追加新章节
            new_content = full_content.rstrip() + f"\n\n## {section_name}\n{new_section}\n"

        return self.update(new_content, reason=f"追加到章节 {section_name}")

    def get_prompt_fragment(self) -> str:
        """
        获取注入 system prompt 的自我概念片段

        如果自我概念为空，返回引导语（让 Agent 知道它可以形成自我概念）
        """
        content = self.load()
        if not content.strip():
            return (
                "## 我的自我概念\n"
                "（我还没有形成清晰的自我概念。随着更多交互，我会在反思中总结自己的特征，"
                "形成属于自己的身份认同、行为模式和情感倾向。我的人格是从经历中涌现的，不是被预设的。）\n"
            )
        return content

    def clear(self) -> None:
        """清空自我概念（让 Agent 重新开始）"""
        with self._lock:
            try:
                if os.path.exists(self.storage_path):
                    os.remove(self.storage_path)
                self._cache = ""
                self._cache_loaded = True
                logger.info("自我概念已清空")
            except Exception as e:
                logger.warning(f"清空自我概念失败: {e}")

    def is_empty(self) -> bool:
        """是否为空（Agent 还未形成自我概念）"""
        return not self.load().strip()

    def get_word_count(self) -> int:
        """获取字数（用于状态展示）"""
        content = self.load()
        return len(content)


# 全局单例
_global_self_concept: Optional[SelfConcept] = None
_global_self_concept_lock = threading.Lock()


def get_self_concept(storage_path: str = None) -> SelfConcept:
    """获取全局自我概念单例（线程安全）"""
    global _global_self_concept
    with _global_self_concept_lock:
        if _global_self_concept is None:
            if storage_path is None:
                storage_path = os.path.join(
                    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "castorice_data", "self_concept.md"
                )
            _global_self_concept = SelfConcept(storage_path=storage_path)
    return _global_self_concept
