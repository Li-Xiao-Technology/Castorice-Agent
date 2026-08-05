"""
Castorice Agent - 状态持久化

提供：
- 会话状态序列化
- 状态快照与恢复
- 自动备份
"""

import json
import os
import tempfile
import threading
import time
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from .logger import get_logger

logger = get_logger(__name__)


class StatePersistence:
    """
    状态持久化管理器

    将 State 对象保存到 JSON 文件，支持：
    - 自动保存
    - 增量备份
    - 历史回溯
    """

    def __init__(
        self,
        storage_dir: str = "./castorice_data/states",
        max_snapshots: int = 10,
    ):
        """
        参数：
            storage_dir: 状态存储目录
            max_snapshots: 每个会话保留的最大快照数
        """
        self.storage_dir = Path(storage_dir)
        self.max_snapshots = max_snapshots
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        # 并发保护：防止多线程同时读写同一会话文件导致数据损坏
        self._lock = threading.Lock()
        logger.info(f"状态持久化目录: {self.storage_dir.absolute()}")

    def _session_path(self, session_id: str) -> Path:
        """获取会话存储路径"""
        safe_id = "".join(c for c in session_id if c.isalnum() or c in "-_")
        return self.storage_dir / f"{safe_id}.json"

    def save(self, session_id: str, state: Any) -> bool:
        """
        保存状态

        参数：
            session_id: 会话 ID
            state: 状态对象（支持 dataclass 或 dict）

        返回：是否成功
        """
        try:
            # 转换 state 为 dict
            if is_dataclass(state) and not isinstance(state, type):
                state_dict = asdict(state)
            elif isinstance(state, dict):
                state_dict = state
            else:
                state_dict = {"data": str(state)}

            # 添加元信息
            snapshot = {
                "session_id": session_id,
                "timestamp": time.time(),
                "state": state_dict,
            }

            # 读取现有快照
            path = self._session_path(session_id)
            with self._lock:
                snapshots: List[Dict] = []
                if path.exists():
                    try:
                        with open(path, "r", encoding="utf-8") as f:
                            data = json.load(f)
                        snapshots = data.get("snapshots", [])
                    except Exception as e:
                        logger.warning(f"读取旧快照失败: {e}")

                # 添加新快照
                snapshots.append(snapshot)

                # 限制数量
                if len(snapshots) > self.max_snapshots:
                    snapshots = snapshots[-self.max_snapshots:]

                # 原子写入：先写入临时文件，再 os.replace 替换目标文件
                # os.replace 在 POSIX 和 Windows 上都是原子操作，避免半写入状态
                payload = {"session_id": session_id, "snapshots": snapshots}
                tmp_fd, tmp_path = tempfile.mkstemp(
                    suffix=".tmp", prefix=path.stem, dir=str(path.parent)
                )
                try:
                    with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                        json.dump(payload, f, ensure_ascii=False, indent=2)
                    os.replace(tmp_path, path)
                except Exception:
                    # 写入或替换失败时清理临时文件
                    if os.path.exists(tmp_path):
                        try:
                            os.unlink(tmp_path)
                        except OSError:
                            pass
                    raise

                logger.debug(f"状态已保存: {session_id} (共 {len(snapshots)} 快照)")

            return True

        except Exception as e:
            logger.error(f"保存状态失败: {e}")
            return False

    def load_latest(self, session_id: str) -> Optional[Dict[str, Any]]:
        """加载最新状态"""
        path = self._session_path(session_id)
        if not path.exists():
            return None
        with self._lock:
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                snapshots = data.get("snapshots", [])
                if snapshots:
                    return snapshots[-1].get("state")
            except Exception as e:
                logger.warning(f"加载状态失败: {e}")
        return None

    def list_sessions(self) -> List[str]:
        """列出所有会话"""
        return [p.stem for p in self.storage_dir.glob("*.json")]

    def delete(self, session_id: str) -> bool:
        """删除会话状态"""
        path = self._session_path(session_id)
        try:
            if path.exists():
                path.unlink()
            return True
        except Exception as e:
            logger.error(f"删除状态失败: {e}")
            return False
