from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from src.db.base import Base


class AdminLoginEvent(Base):
    __tablename__ = "admin_login_events"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    admin_token_id: Mapped[int | None] = mapped_column(
        ForeignKey("admin_tokens.id"), nullable=True, index=True
    )
    success: Mapped[bool] = mapped_column(nullable=False, default=False, index=True)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
