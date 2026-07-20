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
import tempfile
import threading
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger("Castorice.SelfConcept")


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

        # 在内容末尾追加更新时间戳（让 Agent 知道自己什么时候改的）
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        if "## 最近更新" in new_content:
            # 替换已有更新段
            import re
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
    """获取全局自我概念单例"""
    global _global_self_concept
    if _global_self_concept is None:
        with _global_self_concept_lock:
            if _global_self_concept is None:
                if storage_path is None:
                    storage_path = os.path.join(
                        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "castorice_data", "self_concept.md"
                    )
                _global_self_concept = SelfConcept(storage_path=storage_path)
    return _global_self_concept
