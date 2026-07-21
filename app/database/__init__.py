# Provide the application's database package boundary.
# 提供应用数据库层的包边界。

from app.database.base import Base


__all__ = ["Base"]
