from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, select

from solvra.config import Settings, load_settings
from solvra.db import create_session_factory, initialize_database
from solvra.models import (
    Customer,
    MerchantAccount,
    Payment,
    ReconciliationMismatch,
    ReconciliationRun,
    Refund,
    WebhookEvent,
)

ZERO = Decimal("0.00")


@dataclass(frozen=True)
class StatusCount:
    label: str
    count: int


@dataclass(frozen=True)
class RevenueOpsSummary:
    gross_payment_amount: Decimal
    total_refund_amount: Decimal
    net_amount: Decimal
    currency: str | None
    customer_count: int
    merchant_account_count: int
    payment_count: int
    refund_count: int
    webhook_event_count: int
    reconciliation_run_count: int
    reconciliation_mismatch_count: int
    latest_reconciliation_run_id: str | None
    latest_reconciliation_status: str | None
    latest_reconciliation_mismatch_count: int | None
    latest_reconciliation_completed_at: datetime | None
    payment_statuses: list[StatusCount]
    refund_statuses: list[StatusCount]
    webhook_event_types: list[StatusCount]


def get_revenue_ops_summary(
    settings: Settings | None = None,
) -> RevenueOpsSummary:
    active_settings = settings or load_settings()
    engine = initialize_database(active_settings)
    session_factory = create_session_factory(engine)

    with session_factory() as session:
        gross_payment_amount = total_amount(
            session.scalar(select(func.sum(Payment.amount)))
        )
        total_refund_amount = total_amount(
            session.scalar(select(func.sum(Refund.amount)))
        )
        latest_run = session.scalar(
            select(ReconciliationRun).order_by(
                ReconciliationRun.created_at.desc(),
                ReconciliationRun.external_id.desc(),
            ),
        )

        return RevenueOpsSummary(
            gross_payment_amount=gross_payment_amount,
            total_refund_amount=total_refund_amount,
            net_amount=(gross_payment_amount - total_refund_amount).quantize(ZERO),
            currency=summarize_currency(
                session.scalars(select(Payment.currency)).all(),
                session.scalars(select(Refund.currency)).all(),
            ),
            customer_count=count_records(session, Customer),
            merchant_account_count=count_records(session, MerchantAccount),
            payment_count=count_records(session, Payment),
            refund_count=count_records(session, Refund),
            webhook_event_count=count_records(session, WebhookEvent),
            reconciliation_run_count=count_records(session, ReconciliationRun),
            reconciliation_mismatch_count=count_records(
                session, ReconciliationMismatch
            ),
            latest_reconciliation_run_id=(
                latest_run.external_id if latest_run is not None else None
            ),
            latest_reconciliation_status=(
                latest_run.status if latest_run is not None else None
            ),
            latest_reconciliation_mismatch_count=(
                latest_run.mismatch_count if latest_run is not None else None
            ),
            latest_reconciliation_completed_at=(
                latest_run.completed_at if latest_run is not None else None
            ),
            payment_statuses=status_counts(session, Payment.status),
            refund_statuses=status_counts(session, Refund.status),
            webhook_event_types=status_counts(session, WebhookEvent.event_type),
        )


def count_records(session, model) -> int:
    return int(session.scalar(select(func.count(model.id))) or 0)


def status_counts(session, column) -> list[StatusCount]:
    rows = session.execute(
        select(column, func.count()).group_by(column).order_by(column),
    ).all()
    return [StatusCount(label=label, count=int(count)) for label, count in rows]


def summarize_currency(
    payment_currencies: list[str],
    refund_currencies: list[str],
) -> str | None:
    currencies = {
        currency.lower()
        for currency in [*payment_currencies, *refund_currencies]
        if currency
    }
    if not currencies:
        return None
    if len(currencies) == 1:
        return next(iter(currencies))
    return "mixed"


def total_amount(value: Decimal | None) -> Decimal:
    if value is None:
        return ZERO
    return value.quantize(ZERO)
