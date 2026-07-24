# Define the shared SQLAlchemy declarative base.

from sqlalchemy.orm import DeclarativeBase


# Provide the shared metadata base for all database models.
class Base(DeclarativeBase):
    pass
