from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from solvra.models.base import Base, utc_now

if TYPE_CHECKING:
    from solvra.models.account import MerchantAccount
    from solvra.models.customer import Customer
    from solvra.models.ledger import LedgerEntry
    from solvra.models.refund import Refund


class Payment(Base):
    __tablename__ = "payments"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'succeeded', 'failed', 'canceled')",
            name="ck_payments_status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    external_id: Mapped[str] = mapped_column(String(120), unique=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"))
    merchant_account_id: Mapped[int] = mapped_column(
        ForeignKey("merchant_accounts.id"),
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    currency: Mapped[str] = mapped_column(String(3))
    status: Mapped[str] = mapped_column(String(20), default="pending")
    description: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
    )

    customer: Mapped[Customer] = relationship(
        "Customer",
        back_populates="payments",
    )
    ledger_entries: Mapped[list[LedgerEntry]] = relationship(
        "LedgerEntry",
        back_populates="payment",
    )
    merchant_account: Mapped[MerchantAccount] = relationship(
        "MerchantAccount",
        back_populates="payments",
    )
    refunds: Mapped[list[Refund]] = relationship(
        "Refund",
        back_populates="payment",
    )
