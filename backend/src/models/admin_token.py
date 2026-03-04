from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from src.db.base import Base


class AdminToken(Base):
    """Одноразовый токен входа в админ-дэшборд."""

    __tablename__ = "admin_tokens"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    token: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    is_used: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    created_by: Mapped[int] = mapped_column(
        BigInteger, nullable=False
    )  # telegram_id админа, который запросил токен

    logs = relationship(
        "AdminLog",
        back_populates="admin_token",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<AdminToken id={self.id} token={self.token} created_by={self.created_by}>"

