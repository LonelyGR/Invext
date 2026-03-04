from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from src.db.base import Base


class AdminLog(Base):
    """Лог действий в админ-дэшборде."""

    __tablename__ = "admin_logs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    admin_token_id: Mapped[int] = mapped_column(
        ForeignKey("admin_tokens.id"), nullable=False, index=True
    )

    action_type: Mapped[str] = mapped_column(String(32), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(32), nullable=False)
    # BigInteger: entity_id может быть telegram_id (> 2^31) или id заявки
    entity_id: Mapped[int] = mapped_column(BigInteger, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    admin_token: Mapped["AdminToken"] = relationship(
        "AdminToken", back_populates="logs"
    )

    def __repr__(self) -> str:
        return (
            f"<AdminLog id={self.id} token_id={self.admin_token_id} "
            f"action={self.action_type} {self.entity_type}#{self.entity_id}>"
        )

