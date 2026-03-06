"""
Payment webhook event: raw IPN/webhook payloads for audit and idempotency.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import DateTime, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from src.db.base import Base

PROVIDER_NOWPAYMENTS = "nowpayments"

PROCESSING_STATUS_PENDING = "pending"
PROCESSING_STATUS_PROCESSED = "processed"
PROCESSING_STATUS_SKIPPED = "skipped"
PROCESSING_STATUS_ERROR = "error"


class PaymentWebhookEvent(Base):
    """One webhook event from payment provider (e.g. NOWPayments IPN)."""

    __tablename__ = "payment_webhook_events"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    external_event_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, index=True)
    order_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, index=True)

    payload_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    signature_header: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)

    processing_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=PROCESSING_STATUS_PENDING, index=True
    )
    processing_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return (
            f"<PaymentWebhookEvent id={self.id} provider={self.provider} "
            f"order_id={self.order_id} status={self.processing_status}>"
        )
