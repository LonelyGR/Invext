"""
Базовый класс для всех моделей SQLAlchemy.
"""
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Базовый класс моделей — от него наследуются все ORM-модели проекта."""

    pass
