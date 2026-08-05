from castorice.storage.sqlite_base import SqliteStorage
from castorice.storage.personastore import (
    Personastore,
    DataDomain,
    AccessLevel,
    AccessPolicy,
    StoredExperience,
    StoredSelfConcept,
    StoredEmotionState,
    StoredValueState,
    StoredValues,
)
from castorice.storage.local_personastore import LocalSqlitePersonastore


def create_personastore(backend: str = "local_sqlite", **kwargs) -> Personastore:
    """
    创建 Personastore 实例。

    Args:
        backend: 后端类型，目前支持 "local_sqlite"
        **kwargs: 传递给后端的参数

    Returns:
        Personastore 实例
    """
    if backend == "local_sqlite":
        return LocalSqlitePersonastore(**kwargs)
    else:
        raise ValueError(f"未知的 Personastore 后端: {backend}")


__all__ = [
    "SqliteStorage",
    "Personastore",
    "DataDomain",
    "AccessLevel",
    "AccessPolicy",
    "StoredExperience",
    "StoredSelfConcept",
    "StoredEmotionState",
    "StoredValueState",
    "StoredValues",
    "LocalSqlitePersonastore",
    "create_personastore",
]