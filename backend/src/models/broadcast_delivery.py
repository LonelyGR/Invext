from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from src.db.base import Base


DELIVERY_STATUS_PENDING = "PENDING"
DELIVERY_STATUS_SENT = "SENT"
DELIVERY_STATUS_FAILED = "FAILED"


class BroadcastDelivery(Base):
    __tablename__ = "broadcast_deliveries"
    __table_args__ = (
        UniqueConstraint("broadcast_id", "user_id", name="uq_broadcast_delivery_per_user"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    broadcast_id: Mapped[int] = mapped_column(ForeignKey("broadcast_messages.id"), index=True, nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    telegram_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)

    status: Mapped[str] = mapped_column(String(24), nullable=False, default=DELIVERY_STATUS_PENDING, index=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
