"""
Базовый класс для всех моделей SQLAlchemy.
"""
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Базовый класс моделей — от него наследуются User, DepositRequest и т.д."""

    pass
