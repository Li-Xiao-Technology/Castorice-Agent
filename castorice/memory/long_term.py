"""
长期记忆模块 - 基于 Chroma 向量数据库

复刻 Hermes Agent 长期记忆设计：
- 延迟加载：仅在首次使用时才尝试加载 chromadb
- 多方案降级：本地模型 → Chroma 默认 embedding
- 国内网络适配：HuggingFace 镜像
"""

import hashlib
import logging
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from castorice.memory.interface import MemoryInterface

logger = logging.getLogger("Castorice.LongTermMemory")

# ========== 国内网络适配配置 ==========
# HuggingFace 镜像（解决 huggingface.co 被墙）
if not os.environ.get("HF_ENDPOINT"):
    os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"

# 延长下载超时
os.environ.setdefault("HF_HUB_ETAG_TIMEOUT", "60")
os.environ.setdefault("HF_HUB_DOWNLOAD_TIMEOUT", "120")

# 模型缓存目录
_CACHE_DIR = os.path.join(os.path.expanduser("~"), ".cache", "castorice", "models")
os.makedirs(_CACHE_DIR, exist_ok=True)
if not os.environ.get("SENTENCE_TRANSFORMERS_HOME"):
    os.environ["SENTENCE_TRANSFORMERS_HOME"] = _CACHE_DIR


class LongTermMemory(MemoryInterface):
    """长期记忆（基于 Chroma 向量库，支持多 embedding 方案自动降级）"""

    def __init__(
        self,
        persist_directory: str = "./castorice_data/chroma_db",
        collection_name: str = "castorice_long_term",
        embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2",
        top_k: int = 5,
        similarity_threshold: float = 0.75,
        max_retries: int = 3,
        retry_delay: float = 2.0,
    ):
        self.persist_directory = persist_directory
        self.collection_name = collection_name
        self.embedding_model_name = embedding_model
        self.top_k = top_k
        # P1-1: similarity_threshold 现在真正用于过滤（cosine 距离 → 相似度）
        # Chroma cosine space 返回的 distance ∈ [0, 2]，相似度 = 1 - distance
        # 阈值 0.75 表示相似度 ≥ 0.75（即 distance ≤ 0.25）才保留
        self.similarity_threshold = similarity_threshold

        # P2-6: 初始化失败重试机制
        self._max_retries = max_retries
        self._retry_delay = retry_delay

        self._available = False
        self._collection = None
        self._embedding_fn = None
        self._client = None

        # P2-6: 用锁保护懒重试，避免并发触发多次初始化
        self._init_lock = threading.Lock()
        self._init_attempted = False

        self._try_init_with_retry()

    def _try_init_with_retry(self) -> None:
        """P2-6: 带重试的初始化"""
        for attempt in range(self._max_retries):
            try:
                self._try_init()
                if self._available:
                    return
            except Exception as e:
                logger.warning(f"长期记忆初始化第 {attempt + 1}/{self._max_retries} 次失败: {e}")

            if attempt < self._max_retries - 1 and not self._available:
                delay = self._retry_delay * (2 ** attempt)
                logger.info(f"等待 {delay}s 后重试初始化...")
                time.sleep(delay)

        if not self._available:
            logger.error(
                f"长期记忆初始化失败（已重试 {self._max_retries} 次），"
                "所有长期记忆操作将静默失效。可调用 retry_init() 手动重试。"
            )

    def retry_init(self) -> bool:
        """
        P2-6: 手动重试初始化（运行时恢复用）。

        :return: True 表示恢复成功
        """
        with self._init_lock:
            if self._available:
                return True
            self._init_attempted = False
            self._try_init_with_retry()
            return self._available

    def _try_init(self) -> None:
        """尝试初始化 chromadb + embedding"""
        try:
            import chromadb
            from chromadb.utils import embedding_functions

            os.makedirs(self.persist_directory, exist_ok=True)
            client = chromadb.PersistentClient(path=self.persist_directory)
            self._client = client

            self._embedding_fn = self._create_embedding_function(embedding_functions)

            try:
                self._collection = client.get_or_create_collection(
                    name=self.collection_name,
                    embedding_function=self._embedding_fn,
                    metadata={"hnsw:space": "cosine"},
                )
            except Exception as e:
                # P0-6: 仅当确认是 embedding 方案变更（特定异常消息）才备份后重建
                err_msg = str(e).lower()
                if "embedding" in err_msg or "dimension" in err_msg or "distance" in err_msg:
                    logger.warning(f"Embedding 方案变更，备份后重建 collection: {e}")
                    # P1-3: 真正的备份——把原 collection 数据导出后删除
                    self._backup_and_recreate_collection(client)
                else:
                    # 非 embedding 方案问题，不删库，仅记录错误
                    logger.error(f"长期记忆 collection 初始化失败（不删库，保留数据）: {e}")
                    raise
            self._available = True
            logger.info(f"长期记忆初始化成功: collection={self.collection_name}")
        except ImportError:
            logger.warning(
                "chromadb 未安装，长期记忆不可用。"
                "可通过 pip install chromadb sentence-transformers 安装。"
            )
        except Exception as e:
            logger.warning(f"长期记忆初始化失败: {e}")

    def _backup_and_recreate_collection(self, client) -> None:
        """
        P1-3: 真正的备份逻辑。

        ChromaDB 不支持 collection 重命名，所以：
        1. 先尝试导出原 collection 的全部数据到 JSON 备份文件
        2. 再删除原 collection
        3. 用新 embedding 方案重建空 collection
        4. 备份文件可在需要时手动 re-embed 后导入
        """
        backup_dir = os.path.join(self.persist_directory, "backups")
        os.makedirs(backup_dir, exist_ok=True)
        backup_filename = f"{self.collection_name}_backup_{int(time.time())}.json"
        backup_path = os.path.join(backup_dir, backup_filename)

        backup_success = True
        # 尝试导出原数据
        try:
            old_collection = client.get_collection(name=self.collection_name)
            all_data = old_collection.get()
            if all_data and all_data.get("ids"):
                import json
                backup_data = {
                    "collection_name": self.collection_name,
                    "backup_time": datetime.now(timezone.utc).isoformat(),
                    "count": len(all_data["ids"]),
                    "ids": all_data["ids"],
                    "documents": all_data.get("documents", []),
                    "metadatas": all_data.get("metadatas", []),
                }
                with open(backup_path, "w", encoding="utf-8") as f:
                    json.dump(backup_data, f, ensure_ascii=False, indent=2)
                logger.info(
                    f"P1-3: 已备份 {len(all_data['ids'])} 条记忆到 {backup_path}"
                )
            else:
                logger.info("P1-3: 原 collection 为空，无需备份")
        except Exception as backup_err:
            backup_success = False
            logger.error(f"P1-3: 备份原 collection 失败，不删除原数据: {backup_err}")

        if not backup_success:
            raise RuntimeError("备份失败，已中止重建操作以保护数据")

        # 删除原 collection
        try:
            client.delete_collection(name=self.collection_name)
        except Exception as del_e:
            logger.warning(f"删除旧 collection 失败: {del_e}")

        # 用新 embedding 方案重建
        self._collection = client.create_collection(
            name=self.collection_name,
            embedding_function=self._embedding_fn,
            metadata={"hnsw:space": "cosine"},
        )

    def _create_embedding_function(self, ef_module):
        """
        按优先级尝试 embedding 方案：
        1. sentence-transformers 本地模型（免费，离线可用）
        2. Chroma 默认 embedding（基于 ONNX，无需下载大模型）
        """
        # ---------- 方案 1: 本地 sentence-transformers ----------
        try:
            embed_fn = ef_module.SentenceTransformerEmbeddingFunction(
                model_name=self.embedding_model_name
            )
            logger.info(f"长期记忆使用本地嵌入模型: {self.embedding_model_name}")
            return embed_fn
        except Exception as e:
            logger.warning(f"本地嵌入模型加载失败（网络问题？将使用默认方案）: {e}")

        # ---------- 方案 2: Chroma 默认 embedding ----------
        # 基于 ONNX 的 all-MiniLM-L6-v2，随 chromadb 自带，无需额外下载
        logger.info("长期记忆使用 Chroma 默认嵌入（ONNX，无需下载）")
        return ef_module.DefaultEmbeddingFunction()

    @property
    def is_available(self) -> bool:
        return self._available

    def add(self, text: str, metadata: Optional[Dict[str, Any]] = None) -> None:
        if not self._ensure_available():
            return
        try:
            # P1-23: 用文本 hash 作为 ID 实现去重（ChromaDB 同 ID 会 upsert）
            doc_id = hashlib.sha256(text.encode("utf-8")).hexdigest()[:32]
            # P1-2/P2-3: metadata 补充 timestamp（数值类型，用于 ChromaDB $lt 过滤）
            # ChromaDB 的 where 操作符 $lt/$gt 仅支持数值，不支持字符串
            meta = metadata or {}
            now = datetime.now(timezone.utc)
            if "timestamp" not in meta:
                # 数值时间戳（Unix timestamp）用于过滤
                meta["timestamp"] = now.timestamp()
            if "timestamp_iso" not in meta:
                # ISO 字符串用于人类可读
                meta["timestamp_iso"] = now.isoformat()
            self._collection.upsert(
                ids=[doc_id],
                documents=[text],
                metadatas=[meta],
            )
        except Exception as e:
            logger.warning(f"写入长期记忆失败: {e}")

    def add_batch(self, texts: List[str], metadatas: Optional[List[Dict[str, Any]]] = None) -> None:
        if not self._ensure_available():
            return
        try:
            # P1-23: 批量去重
            ids = [hashlib.sha256(t.encode("utf-8")).hexdigest()[:32] for t in texts]
            now = datetime.now(timezone.utc)
            now_ts = now.timestamp()
            now_iso = now.isoformat()
            metas = []
            for i, m in enumerate(metadatas or [{}] * len(texts)):
                m = m or {}
                if "timestamp" not in m:
                    m["timestamp"] = now_ts
                if "timestamp_iso" not in m:
                    m["timestamp_iso"] = now_iso
                metas.append(m)
            self._collection.upsert(ids=ids, documents=texts, metadatas=metas)
        except Exception as e:
            logger.warning(f"批量写入长期记忆失败: {e}")

    def get_relevant_context(
        self,
        query: str,
        top_k: Optional[int] = None,
        where: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        检索与 query 最相关的记忆上下文。

        :param query: 查询文本
        :param top_k: 返回条数，默认 self.top_k
        :param where: P1-2 metadata 过滤条件（如 {"session_id": "..."} 或 {"user_id": "..."}）
        :return: 拼接后的记忆文本
        """
        if not self._ensure_available():
            return ""
        try:
            k = top_k or self.top_k
            query_kwargs = {"query_texts": [query], "n_results": k}
            if where:
                query_kwargs["where"] = where
            results = self._collection.query(**query_kwargs)
            docs = results.get("documents", [[]])[0]
            distances = results.get("distances", [[]])[0]
            if not docs:
                return ""

            # P1-1: 按相似度阈值过滤（cosine space: distance ∈ [0,2], similarity = 1 - distance）
            filtered = []
            for doc, dist in zip(docs, distances or [0] * len(docs)):
                similarity = 1.0 - dist
                if similarity >= self.similarity_threshold:
                    filtered.append(doc)

            if not filtered:
                logger.debug(
                    f"长期记忆检索到 {len(docs)} 条，但无一条相似度 ≥ {self.similarity_threshold}"
                )
                return ""
            logger.info(
                f"长期记忆检索: {len(docs)} 条候选，{len(filtered)} 条通过阈值过滤"
            )
            return "\n---\n".join(filtered)
        except Exception as e:
            logger.warning(f"检索长期记忆失败: {e}")
            return ""

    def search(
        self,
        query: str,
        top_k: Optional[int] = None,
        where: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """
        检索记忆，返回结构化结果。

        :param query: 查询文本
        :param top_k: 返回条数
        :param where: P1-2 metadata 过滤条件
        :return: [{"text": ..., "metadata": ..., "similarity": ...}, ...]
        """
        if not self._ensure_available():
            return []
        try:
            k = top_k or self.top_k
            query_kwargs = {"query_texts": [query], "n_results": k}
            if where:
                query_kwargs["where"] = where
            results = self._collection.query(**query_kwargs)
            docs = results.get("documents", [[]])[0]
            metadatas = results.get("metadatas", [[]])[0]
            distances = results.get("distances", [[]])[0]

            # P1-1: 按相似度过滤
            output = []
            for d, m, dist in zip(docs, metadatas, distances or [0] * len(docs)):
                similarity = 1.0 - dist
                if similarity >= self.similarity_threshold:
                    output.append({
                        "text": d,
                        "metadata": m,
                        "similarity": similarity,
                    })
            return output
        except Exception as e:
            logger.warning(f"长期记忆查询失败: {e}")
            return []

    def clear(self) -> None:
        if not self._ensure_available():
            return
        try:
            # 获取所有记录的 ID，然后删除
            all_data = self._collection.get()
            if all_data and all_data.get("ids"):
                self._collection.delete(ids=all_data["ids"])
        except Exception as e:
            logger.warning(f"清空长期记忆失败: {e}")

    def count(self) -> int:
        if not self._ensure_available():
            return 0
        try:
            return self._collection.count()
        except Exception as e:
            logger.warning(f"长期记忆计数失败: {e}")
            return 0

    def cleanup_old_memories(self, days: int = 90) -> int:
        """
        P2-3: 清理超过指定天数的长期记忆。

        :param days: 超过该天数的记忆将被删除（按 metadata.timestamp 数值字段判断）
        :return: 删除的记忆数
        """
        if not self._ensure_available():
            return 0
        try:
            from datetime import timedelta
            cutoff_dt = datetime.now(timezone.utc) - timedelta(days=days)
            cutoff_ts = cutoff_dt.timestamp()
            # ChromaDB 的 $lt 仅支持数值类型，所以 timestamp 必须存为 Unix timestamp
            all_data = self._collection.get(where={"timestamp": {"$lt": cutoff_ts}})
            ids_to_delete = all_data.get("ids", []) if all_data else []
            if ids_to_delete:
                self._collection.delete(ids=ids_to_delete)
                logger.info(f"P2-3: 清理了 {len(ids_to_delete)} 条超过 {days} 天的长期记忆")
            return len(ids_to_delete)
        except Exception as e:
            logger.warning(f"P2-3: 清理旧记忆失败: {e}")
            return 0

    def _ensure_available(self) -> bool:
        """
        P2-6: 检查可用性，不可用时尝试一次懒重试。
        """
        if self._available:
            return True
        # 懒重试（仅一次，避免每次调用都触发）
        if not self._init_attempted:
            with self._init_lock:
                if not self._init_attempted:
                    self._init_attempted = True
                    self._try_init_with_retry()
        return self._available
