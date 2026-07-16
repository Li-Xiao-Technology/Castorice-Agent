"""
长期记忆模块 - 基于 Chroma 向量数据库

复刻 Hermes Agent 长期记忆设计：
- 延迟加载：仅在首次使用时才尝试加载 chromadb
- 多方案降级：本地模型 → Chroma 默认 embedding
- 国内网络适配：HuggingFace 镜像
"""

import os
import logging
from typing import Any, Dict, List, Optional

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


class LongTermMemory:
    """长期记忆（基于 Chroma 向量库，支持多 embedding 方案自动降级）"""

    def __init__(
        self,
        persist_directory: str = "./castorice_data/chroma_db",
        collection_name: str = "castorice_long_term",
        embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2",
        top_k: int = 5,
        similarity_threshold: float = 0.75,
    ):
        self.persist_directory = persist_directory
        self.collection_name = collection_name
        self.embedding_model_name = embedding_model
        self.top_k = top_k
        self.similarity_threshold = similarity_threshold

        self._available = False
        self._collection = None
        self._embedding_fn = None

        self._try_init()

    def _try_init(self) -> None:
        """尝试初始化 chromadb + embedding"""
        try:
            import chromadb
            from chromadb.utils import embedding_functions

            os.makedirs(self.persist_directory, exist_ok=True)
            client = chromadb.PersistentClient(path=self.persist_directory)

            self._embedding_fn = self._create_embedding_function(embedding_functions)

            try:
                self._collection = client.get_or_create_collection(
                    name=self.collection_name,
                    embedding_function=self._embedding_fn,
                    metadata={"hnsw:space": "cosine"},
                )
            except Exception:
                # embedding 方案变化导致冲突，删除旧 collection 重建
                logger.warning("Embedding 方案变更，重建 collection...")
                try:
                    client.delete_collection(name=self.collection_name)
                except Exception:
                    pass
                self._collection = client.create_collection(
                    name=self.collection_name,
                    embedding_function=self._embedding_fn,
                    metadata={"hnsw:space": "cosine"},
                )
            self._available = True
        except ImportError:
            logger.warning(
                "chromadb 未安装，长期记忆不可用。"
                "可通过 pip install chromadb sentence-transformers 安装。"
            )
        except Exception as e:
            logger.warning(f"长期记忆初始化失败: {e}")

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

    def add_single(self, text: str, metadata: Optional[Dict[str, Any]] = None) -> None:
        if not self._available:
            return
        try:
            import uuid
            self._collection.add(
                ids=[str(uuid.uuid4())],
                documents=[text],
                metadatas=[metadata or {}],
            )
        except Exception as e:
            logger.warning(f"写入长期记忆失败: {e}")

    def add_batch(self, texts: List[str], metadatas: Optional[List[Dict[str, Any]]] = None) -> None:
        if not self._available:
            return
        try:
            import uuid
            ids = [str(uuid.uuid4()) for _ in texts]
            self._collection.add(ids=ids, documents=texts, metadatas=metadatas or [{}] * len(texts))
        except Exception as e:
            logger.warning(f"批量写入长期记忆失败: {e}")

    def get_relevant_context(self, query: str, top_k: Optional[int] = None) -> str:
        if not self._available:
            return ""
        try:
            k = top_k or self.top_k
            results = self._collection.query(query_texts=[query], n_results=k)
            docs = results.get("documents", [[]])[0]
            if not docs:
                return ""
            return "\n---\n".join(docs)
        except Exception as e:
            logger.warning(f"检索长期记忆失败: {e}")
            return ""

    def search(self, query: str, top_k: Optional[int] = None) -> List[Dict[str, Any]]:
        if not self._available:
            return []
        try:
            k = top_k or self.top_k
            results = self._collection.query(query_texts=[query], n_results=k)
            docs = results.get("documents", [[]])[0]
            metadatas = results.get("metadatas", [[]])[0]
            return [{"text": d, "metadata": m} for d, m in zip(docs, metadatas)]
        except Exception:
            return []

    def clear(self) -> None:
        if not self._available:
            return
        try:
            self._collection.delete(where={})
        except Exception as e:
            logger.warning(f"清空长期记忆失败: {e}")

    def count(self) -> int:
        if not self._available:
            return 0
        try:
            return self._collection.count()
        except Exception:
            return 0
