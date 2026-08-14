from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import JSON, CheckConstraint, DateTime, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from solvra.models.base import Base, utc_now


class ReconciliationRun(Base):
    __tablename__ = "reconciliation_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'completed', 'failed')",
            name="ck_reconciliation_runs_status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    external_id: Mapped[str] = mapped_column(String(120), unique=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    payment_count: Mapped[int] = mapped_column(default=0)
    refund_count: Mapped[int] = mapped_column(default=0)
    webhook_event_count: Mapped[int] = mapped_column(default=0)
    mismatch_count: Mapped[int] = mapped_column(default=0)
    total_payment_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)
    total_refund_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)
    net_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)
    currency: Mapped[str | None] = mapped_column(String(10))
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    summary_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
    )

    mismatches: Mapped[list[ReconciliationMismatch]] = relationship(
        "ReconciliationMismatch",
        back_populates="run",
    )


class ReconciliationMismatch(Base):
    __tablename__ = "reconciliation_mismatches"

    id: Mapped[int] = mapped_column(primary_key=True)
    external_id: Mapped[str] = mapped_column(String(120), unique=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("reconciliation_runs.id"))
    mismatch_type: Mapped[str] = mapped_column(String(120), index=True)
    severity: Mapped[str] = mapped_column(String(20), index=True)
    entity_type: Mapped[str] = mapped_column(String(80), index=True)
    entity_external_id: Mapped[str] = mapped_column(String(120), index=True)
    expected: Mapped[str | None] = mapped_column(String(255))
    actual: Mapped[str | None] = mapped_column(String(255))
    message: Mapped[str] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
    )

    run: Mapped[ReconciliationRun] = relationship(
        "ReconciliationRun",
        back_populates="mismatches",
    )
