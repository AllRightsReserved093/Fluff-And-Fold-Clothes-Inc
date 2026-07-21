# Define the shared SQLAlchemy declarative base.
# 定义 SQLAlchemy ORM 模型共用的声明式基类。

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
