from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from src.db.base import Base


class SystemSettingsVersion(Base):
    __tablename__ = "system_settings_versions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    admin_token_id: Mapped[int | None] = mapped_column(
        ForeignKey("admin_tokens.id", ondelete="SET NULL"), nullable=True
    )
    source: Mapped[str] = mapped_column(Text, nullable=False, default="manual")
    snapshot_json: Mapped[str] = mapped_column(Text, nullable=False)
    changes_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
