# Configure the SQLite engine and database session lifecycle.
# 配置 SQLite 引擎和数据库会话生命周期。

from collections.abc import Generator
from sqlite3 import Connection as SQLiteConnection
from typing import Any

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.database.base import Base


settings = get_settings()
sqlite_connect_args = (
    {"check_same_thread": False}
    if settings.database_url.startswith("sqlite")
    else {}
)

engine = create_engine(
    settings.database_url,
    connect_args=sqlite_connect_args,
)
SessionFactory = sessionmaker(
    bind=engine,
    autoflush=False,
    expire_on_commit=False,
)


# Enforce declared foreign keys for every SQLite connection.
# 为每个 SQLite 连接启用已声明的外键约束。
@event.listens_for(Engine, "connect")
def enable_sqlite_foreign_keys(database_connection: Any,_connection_record: Any) -> None:
    if not isinstance(database_connection, SQLiteConnection):
        return

    cursor = database_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


# Provide one session to a request or service operation.
# 为一次请求或服务操作提供一个数据库会话。
def get_database_session() -> Generator[Session, None, None]:
    with SessionFactory() as database_session:
        yield database_session


# Create the currently declared tables during explicit application setup.
# 在显式的应用初始化阶段创建当前声明的表。
def initialize_database() -> None:
    from app.database import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
