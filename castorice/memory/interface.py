"""
记忆接口层 (Memory Interface)

定义统一的记忆接口标准，支持多种后端切换：
- Chroma（默认）
- Pinecone
- FAISS
- LangChain VectorStore（适配器）

设计原则：
1. 接口统一：所有后端实现同一套 API
2. 动态加载：后端按需导入，不强制依赖
3. 向后兼容：当前 Chroma 实现自动适配新接口
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


class MemoryInterface(ABC):
    """
    记忆接口抽象基类
    
    所有记忆后端都必须实现以下接口：
    - add(text, metadata): 添加单条记忆
    - add_batch(texts, metadatas): 批量添加记忆
    - get_relevant_context(query, top_k): 检索相关上下文
    - search(query, top_k): 检索并返回结构化结果
    - clear(): 清空所有记忆
    - count(): 返回记忆数量
    - is_available: 属性，是否可用
    """
    
    @abstractmethod
    def add(self, text: str, metadata: Optional[Dict[str, Any]] = None) -> None:
        """添加单条记忆"""
        pass
    
    @abstractmethod
    def add_batch(self, texts: List[str], metadatas: Optional[List[Dict[str, Any]]] = None) -> None:
        """批量添加记忆"""
        pass
    
    @abstractmethod
    def get_relevant_context(
        self,
        query: str,
        top_k: Optional[int] = None,
        where: Optional[Dict[str, Any]] = None,
    ) -> str:
        """检索相关上下文，返回格式化文本

        :param where: P1-2 metadata 过滤条件（如 {"session_id": "..."} 用于多用户隔离）
        """
        pass

    @abstractmethod
    def search(
        self,
        query: str,
        top_k: Optional[int] = None,
        where: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """检索并返回结构化结果列表

        :param where: P1-2 metadata 过滤条件
        """
        pass
    
    @abstractmethod
    def clear(self) -> None:
        """清空所有记忆"""
        pass
    
    @abstractmethod
    def count(self) -> int:
        """返回记忆数量"""
        pass
    
    @property
    @abstractmethod
    def is_available(self) -> bool:
        """是否可用"""
        pass


class ShortTermMemoryInterface(ABC):
    """短期记忆抽象接口"""

    @abstractmethod
    def create_session(self, session_id: str) -> None: ...

    @abstractmethod
    def add_message(self, session_id: str, message: Any) -> None: ...

    @abstractmethod
    def get_history(self, session_id: str, limit: int = 20) -> List[Any]: ...

    @abstractmethod
    def update_summary(self, session_id: str, summary: str) -> None: ...

    @abstractmethod
    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]: ...

    @abstractmethod
    def close(self) -> None: ...


class SkillMemoryInterface(ABC):
    """技能记忆抽象接口"""

    @abstractmethod
    def add_or_update(self, skill: Any) -> None: ...

    @abstractmethod
    def find_by_name(self, name: str) -> Optional[Any]: ...

    @abstractmethod
    def match(self, query: str, top_n: int = 3) -> List[Any]: ...

    @abstractmethod
    def list_all(self) -> List[Any]: ...

    @abstractmethod
    def delete(self, name: str) -> bool: ...


class MemoryFactory:
    """
    记忆工厂：根据配置创建不同的记忆后端
    
    使用示例：
    >>> factory = MemoryFactory()
    >>> memory = factory.create("chroma", persist_directory="./data/chroma")
    >>> memory = factory.create("pinecone", api_key="xxx", index_name="my-index")
    >>> memory = factory.create("faiss")
    """
    
    _registered_backends: Dict[str, callable] = {}
    
    @classmethod
    def register(cls, name: str, creator: callable):
        """注册自定义后端"""
        cls._registered_backends[name] = creator
    
    @classmethod
    def create(cls, backend: str = "chroma", **kwargs) -> MemoryInterface:
        """创建记忆后端实例"""
        backend = backend.lower()
        
        if backend == "chroma":
            return cls._create_chroma(**kwargs)
        elif backend == "pinecone":
            return cls._create_pinecone(**kwargs)
        elif backend == "faiss":
            return cls._create_faiss(**kwargs)
        elif backend == "langchain":
            return cls._create_langchain(**kwargs)
        else:
            raise ValueError(f"不支持的记忆后端: {backend}")
    
    @classmethod
    def _create_chroma(cls, **kwargs) -> MemoryInterface:
        """创建 Chroma 后端（默认）"""
        from castorice.memory.long_term import LongTermMemory
        return LongTermMemory(**kwargs)
    
    @classmethod
    def _create_pinecone(cls, **kwargs) -> MemoryInterface:
        """创建 Pinecone 后端"""
        try:
            import pinecone
            from pinecone import Pinecone as PineconeClient
            
            api_key = kwargs.get("api_key", "")
            index_name = kwargs.get("index_name", "castorice")
            environment = kwargs.get("environment", "us-east-1")
            top_k = kwargs.get("top_k", 5)
            
            pc = PineconeClient(api_key=api_key)
            index = pc.Index(index_name)
            
            class PineconeAdapter(MemoryInterface):
                def __init__(self, index, top_k):
                    self._index = index
                    self._top_k = top_k
                    self._available = True
                    self._encoder = None
                    self._model_name = "all-MiniLM-L6-v2"
                
                def _get_encoder(self):
                    if self._encoder is None:
                        try:
                            from sentence_transformers import SentenceTransformer
                            self._encoder = SentenceTransformer(self._model_name)
                        except Exception as e:
                            from castorice.memory.long_term import logger
                            logger.warning(f"Pinecone encoder 加载失败: {e}")
                            self._encoder = None
                            self._available = False
                    return self._encoder
                
                def add(self, text: str, metadata: Optional[Dict] = None) -> None:
                    try:
                        import uuid
                        encoder = self._get_encoder()
                        if encoder is None:
                            return
                        embedding = encoder.encode(text).tolist()
                        self._index.upsert(
                            vectors=[(str(uuid.uuid4()), embedding, {"text": text, **(metadata or {})})]
                        )
                    except Exception as e:
                        from castorice.memory.long_term import logger
                        logger.warning(f"Pinecone 写入失败: {e}")
                
                def add_batch(self, texts: List[str], metadatas: Optional[List[Dict]] = None) -> None:
                    try:
                        import uuid
                        encoder = self._get_encoder()
                        if encoder is None:
                            return
                        vectors = []
                        for i, text in enumerate(texts):
                            embedding = encoder.encode(text).tolist()
                            meta = metadatas[i] if metadatas else {}
                            vectors.append((str(uuid.uuid4()), embedding, {"text": text, **meta}))
                        self._index.upsert(vectors=vectors)
                    except Exception as e:
                        from castorice.memory.long_term import logger
                        logger.warning(f"Pinecone 批量写入失败: {e}")
                
                def get_relevant_context(self, query: str, top_k: Optional[int] = None, where: Optional[Dict] = None) -> str:
                    try:
                        encoder = self._get_encoder()
                        if encoder is None:
                            return ""
                        embedding = encoder.encode(query).tolist()
                        results = self._index.query(
                            vector=embedding, top_k=top_k or self._top_k,
                            include_metadata=True,
                            filter=where or None,
                        )
                        docs = [r["metadata"].get("text", "") for r in results["matches"]]
                        return "\n---\n".join(docs)
                    except Exception as e:
                        from castorice.memory.long_term import logger
                        logger.warning(f"Pinecone 检索失败: {e}")
                        return ""

                def search(self, query: str, top_k: Optional[int] = None, where: Optional[Dict] = None) -> List[Dict]:
                    try:
                        encoder = self._get_encoder()
                        if encoder is None:
                            return []
                        embedding = encoder.encode(query).tolist()
                        results = self._index.query(
                            vector=embedding, top_k=top_k or self._top_k,
                            include_metadata=True,
                            filter=where or None,
                        )
                        return [{"text": r["metadata"].get("text", ""), "metadata": r["metadata"]} for r in results["matches"]]
                    except Exception:
                        return []
                
                def clear(self) -> None:
                    try:
                        self._index.delete(delete_all=True)
                    except Exception as e:
                        from castorice.memory.long_term import logger
                        logger.warning(f"Pinecone 清空失败: {e}")
                
                def count(self) -> int:
                    try:
                        return self._index.describe_index_stats()["total_vector_count"]
                    except Exception:
                        return 0
                
                @property
                def is_available(self) -> bool:
                    return self._available
            
            return PineconeAdapter(index, top_k)
        
        except ImportError:
            raise ImportError("请安装 pinecone-client: pip install pinecone-client")
    
    @classmethod
    def _create_faiss(cls, **kwargs) -> MemoryInterface:
        """创建 FAISS 后端"""
        try:
            import faiss
            
            model_name = kwargs.get("model_name", "all-MiniLM-L6-v2")
            top_k = kwargs.get("top_k", 5)
            persist_path = kwargs.get("persist_path", "./castorice_data/faiss_index")
            
            import os
            index = None
            if os.path.exists(persist_path + ".index"):
                index = faiss.read_index(persist_path)
            
            class FAISSAdapter(MemoryInterface):
                def __init__(self, index, model_name, top_k, persist_path):
                    self._index = index
                    self._encoder = None
                    self._model_name = model_name
                    self._top_k = top_k
                    self._persist_path = persist_path
                    self._texts = []
                    self._metadatas = []
                    self._available = True
                
                def _get_encoder(self):
                    if self._encoder is None:
                        try:
                            from sentence_transformers import SentenceTransformer
                            self._encoder = SentenceTransformer(self._model_name)
                        except Exception as e:
                            from castorice.memory.long_term import logger
                            logger.warning(f"FAISS encoder 加载失败: {e}")
                            self._encoder = None
                            self._available = False
                    return self._encoder
                
                def _ensure_index(self):
                    import faiss
                    if self._index is None:
                        encoder = self._get_encoder()
                        if encoder is None:
                            return False
                        dim = encoder.get_sentence_embedding_dimension()
                        self._index = faiss.IndexFlatL2(dim)
                    return True
                
                def add(self, text: str, metadata: Optional[Dict] = None) -> None:
                    try:
                        import faiss
                        if not self._ensure_index():
                            return
                        encoder = self._get_encoder()
                        if encoder is None:
                            return
                        embedding = encoder.encode(text).reshape(1, -1)
                        self._index.add(embedding)
                        self._texts.append(text)
                        self._metadatas.append(metadata or {})
                        faiss.write_index(self._index, self._persist_path)
                    except Exception as e:
                        from castorice.memory.long_term import logger
                        logger.warning(f"FAISS 写入失败: {e}")
                
                def add_batch(self, texts: List[str], metadatas: Optional[List[Dict]] = None) -> None:
                    try:
                        import faiss
                        if not self._ensure_index():
                            return
                        encoder = self._get_encoder()
                        if encoder is None:
                            return
                        embeddings = encoder.encode(texts)
                        self._index.add(embeddings)
                        self._texts.extend(texts)
                        self._metadatas.extend(metadatas or [{}] * len(texts))
                        faiss.write_index(self._index, self._persist_path)
                    except Exception as e:
                        from castorice.memory.long_term import logger
                        logger.warning(f"FAISS 批量写入失败: {e}")
                
                def get_relevant_context(self, query: str, top_k: Optional[int] = None, where: Optional[Dict] = None) -> str:
                    try:
                        if not self._ensure_index():
                            return ""
                        encoder = self._get_encoder()
                        if encoder is None:
                            return ""
                        embedding = encoder.encode(query).reshape(1, -1)
                        _, indices = self._index.search(embedding, top_k or self._top_k)
                        docs = []
                        for i in indices[0]:
                            if i < len(self._texts):
                                # where 过滤（简单实现：检查 metadata 是否匹配）
                                if where:
                                    meta = self._metadatas[i] if i < len(self._metadatas) else {}
                                    if not all(meta.get(k) == v for k, v in where.items()):
                                        continue
                                docs.append(self._texts[i])
                        return "\n---\n".join(docs)
                    except Exception as e:
                        from castorice.memory.long_term import logger
                        logger.warning(f"FAISS 检索失败: {e}")
                        return ""

                def search(self, query: str, top_k: Optional[int] = None, where: Optional[Dict] = None) -> List[Dict]:
                    try:
                        if not self._ensure_index():
                            return []
                        encoder = self._get_encoder()
                        if encoder is None:
                            return []
                        embedding = encoder.encode(query).reshape(1, -1)
                        _, indices = self._index.search(embedding, top_k or self._top_k)
                        output = []
                        for i in indices[0]:
                            if i < len(self._texts):
                                meta = self._metadatas[i] if i < len(self._metadatas) else {}
                                if where and not all(meta.get(k) == v for k, v in where.items()):
                                    continue
                                output.append({"text": self._texts[i], "metadata": meta})
                        return output
                    except Exception:
                        return []
                
                def clear(self) -> None:
                    try:
                        import faiss
                        if self._index is None:
                            return
                        dim = self._index.d
                        self._index = faiss.IndexFlatL2(dim)
                        self._texts = []
                        self._metadatas = []
                        faiss.write_index(self._index, self._persist_path)
                    except Exception as e:
                        from castorice.memory.long_term import logger
                        logger.warning(f"FAISS 清空失败: {e}")
                
                def count(self) -> int:
                    if self._index is None:
                        return 0
                    return self._index.ntotal
                
                @property
                def is_available(self) -> bool:
                    return self._available
            
            return FAISSAdapter(index, model_name, top_k, persist_path)
        
        except ImportError:
            raise ImportError("请安装 faiss-cpu: pip install faiss-cpu")
    
    @classmethod
    def _create_langchain(cls, **kwargs) -> MemoryInterface:
        """创建 LangChain VectorStore 后端（适配器）"""
        try:
            from castorice.adapters import VectorStoreAdapter
            
            lc_vectorstore = kwargs.get("vectorstore")
            if not lc_vectorstore:
                raise ValueError("需要提供 LangChain VectorStore 实例")
            
            class LangChainMemoryAdapter(MemoryInterface):
                def __init__(self, adapter):
                    self._adapter = adapter
                    self._available = True
                
                def add(self, text: str, metadata: Optional[Dict] = None) -> None:
                    self._adapter.add_documents([text], [metadata] if metadata else None)
                
                def add_batch(self, texts: List[str], metadatas: Optional[List[Dict]] = None) -> None:
                    self._adapter.add_documents(texts, metadatas)
                
                def get_relevant_context(self, query: str, top_k: Optional[int] = None, where: Optional[Dict] = None) -> str:
                    return self._adapter.get_relevant_context(query, top_k)

                def search(self, query: str, top_k: Optional[int] = None, where: Optional[Dict] = None) -> List[Dict]:
                    results = self._adapter.get_relevant_context(query, top_k)
                    if not results:
                        return []
                    return [{"text": results, "metadata": {}}]
                
                def clear(self) -> None:
                    self._adapter.clear()
                
                def count(self) -> int:
                    return 0
                
                @property
                def is_available(self) -> bool:
                    return self._available
            
            adapter = VectorStoreAdapter(lc_vectorstore)
            return LangChainMemoryAdapter(adapter)
        
        except ImportError:
            raise ImportError("请安装 langchain-core: pip install langchain-core")