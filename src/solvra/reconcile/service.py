from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

from sqlalchemy import select

from solvra.config import Settings, load_settings
from solvra.db import create_session_factory, initialize_database
from solvra.models import (
    Payment,
    ReconciliationMismatch,
    ReconciliationRun,
    Refund,
    WebhookEvent,
)
from solvra.models.base import utc_now

ZERO = Decimal("0.00")


class ReconciliationRunNotFoundError(ValueError):
    pass


@dataclass(frozen=True)
class ReconciliationMismatchDraft:
    mismatch_type: str
    severity: str
    entity_type: str
    entity_external_id: str
    expected: str | None
    actual: str | None
    message: str


@dataclass(frozen=True)
class ReconciliationMismatchRow:
    run_external_id: str
    external_id: str
    mismatch_type: str
    severity: str
    entity_type: str
    entity_external_id: str
    expected: str | None
    actual: str | None
    message: str
    created_at: datetime


@dataclass(frozen=True)
class ReconciliationMismatchList:
    run_external_id: str | None
    mismatches: list[ReconciliationMismatchRow]


@dataclass(frozen=True)
class ReconciliationRunSummary:
    external_id: str
    status: str
    payment_count: int
    refund_count: int
    webhook_event_count: int
    mismatch_count: int
    total_payment_amount: Decimal
    total_refund_amount: Decimal
    net_amount: Decimal
    currency: str | None
    started_at: datetime
    completed_at: datetime | None
    created_at: datetime
    summary_json: dict
    mismatches: list[ReconciliationMismatchRow]


@dataclass(frozen=True)
class ReconciliationRunRow:
    external_id: str
    status: str
    payment_count: int
    refund_count: int
    webhook_event_count: int
    mismatch_count: int
    net_amount: Decimal
    currency: str | None
    created_at: datetime
    completed_at: datetime | None


def create_reconciliation_run(
    settings: Settings | None = None,
) -> ReconciliationRunSummary:
    session_factory = create_reconciliation_session_factory(settings)
    with session_factory() as session:
        started_at = utc_now()
        payments = session.scalars(select(Payment)).all()
        refunds = session.scalars(select(Refund)).all()
        webhook_events = session.scalars(select(WebhookEvent)).all()
        mismatch_drafts = detect_reconciliation_mismatches(
            payments,
            refunds,
            webhook_events,
        )

        total_payment_amount = sum_money(payment.amount for payment in payments)
        total_refund_amount = sum_money(refund.amount for refund in refunds)
        net_amount = total_payment_amount - total_refund_amount
        currency = summarize_currency(
            [payment.currency for payment in payments],
            [refund.currency for refund in refunds],
        )
        completed_at = utc_now()

        run = ReconciliationRun(
            external_id=make_reconciliation_external_id(),
            status="completed",
            payment_count=len(payments),
            refund_count=len(refunds),
            webhook_event_count=len(webhook_events),
            mismatch_count=len(mismatch_drafts),
            total_payment_amount=total_payment_amount,
            total_refund_amount=total_refund_amount,
            net_amount=net_amount,
            currency=currency,
            started_at=started_at,
            completed_at=completed_at,
            summary_json={
                "payment_count": len(payments),
                "refund_count": len(refunds),
                "webhook_event_count": len(webhook_events),
                "mismatch_count": len(mismatch_drafts),
                "total_payment_amount": str(total_payment_amount),
                "total_refund_amount": str(total_refund_amount),
                "net_amount": str(net_amount),
                "currency": currency,
            },
        )
        run.mismatches = [
            ReconciliationMismatch(
                external_id=make_mismatch_external_id(),
                mismatch_type=draft.mismatch_type,
                severity=draft.severity,
                entity_type=draft.entity_type,
                entity_external_id=draft.entity_external_id,
                expected=draft.expected,
                actual=draft.actual,
                message=draft.message,
            )
            for draft in mismatch_drafts
        ]
        session.add(run)
        session.commit()
        session.refresh(run)
        return run_summary(
            run,
            [mismatch_row(mismatch, run.external_id) for mismatch in run.mismatches],
        )


def list_reconciliation_runs(
    settings: Settings | None = None,
) -> list[ReconciliationRunRow]:
    session_factory = create_reconciliation_session_factory(settings)
    with session_factory() as session:
        runs = session.scalars(
            select(ReconciliationRun).order_by(
                ReconciliationRun.created_at.desc(),
                ReconciliationRun.external_id.desc(),
            ),
        ).all()
        return [run_row(run) for run in runs]


def get_reconciliation_run(
    external_id: str,
    settings: Settings | None = None,
) -> ReconciliationRunSummary:
    session_factory = create_reconciliation_session_factory(settings)
    with session_factory() as session:
        run = session.scalar(
            select(ReconciliationRun).where(
                ReconciliationRun.external_id == external_id,
            ),
        )
        if run is None:
            raise ReconciliationRunNotFoundError(
                f"Reconciliation run not found: {external_id}",
            )

        mismatches = session.scalars(
            select(ReconciliationMismatch)
            .where(ReconciliationMismatch.run_id == run.id)
            .order_by(
                ReconciliationMismatch.severity,
                ReconciliationMismatch.mismatch_type,
                ReconciliationMismatch.external_id,
            ),
        ).all()
        return run_summary(
            run,
            [mismatch_row(mismatch, run.external_id) for mismatch in mismatches],
        )


def list_latest_reconciliation_mismatches(
    settings: Settings | None = None,
) -> ReconciliationMismatchList:
    session_factory = create_reconciliation_session_factory(settings)
    with session_factory() as session:
        run = session.scalar(
            select(ReconciliationRun).order_by(
                ReconciliationRun.created_at.desc(),
                ReconciliationRun.external_id.desc(),
            ),
        )
        if run is None:
            return ReconciliationMismatchList(run_external_id=None, mismatches=[])

        mismatches = session.scalars(
            select(ReconciliationMismatch)
            .where(ReconciliationMismatch.run_id == run.id)
            .order_by(
                ReconciliationMismatch.severity,
                ReconciliationMismatch.mismatch_type,
                ReconciliationMismatch.external_id,
            ),
        ).all()
        return ReconciliationMismatchList(
            run_external_id=run.external_id,
            mismatches=[
                mismatch_row(mismatch, run.external_id) for mismatch in mismatches
            ],
        )


def detect_reconciliation_mismatches(
    payments: list[Payment],
    refunds: list[Refund],
    webhook_events: list[WebhookEvent],
) -> list[ReconciliationMismatchDraft]:
    mismatches: list[ReconciliationMismatchDraft] = []
    payments_by_external_id = {payment.external_id: payment for payment in payments}
    refunds_by_external_id = {refund.external_id: refund for refund in refunds}
    payment_succeeded_event_ids = matching_payload_ids(
        webhook_events,
        event_type="payment.succeeded",
        payload_key="payment_external_id",
    )
    refund_succeeded_event_ids = matching_payload_ids(
        webhook_events,
        event_type="refund.succeeded",
        payload_key="refund_external_id",
    )

    for payment in payments:
        if (
            payment.status == "succeeded"
            and payment.external_id not in payment_succeeded_event_ids
        ):
            mismatches.append(
                ReconciliationMismatchDraft(
                    mismatch_type="missing_payment_succeeded_event",
                    severity="warning",
                    entity_type="payment",
                    entity_external_id=payment.external_id,
                    expected="payment.succeeded webhook",
                    actual="missing",
                    message=(
                        f"Payment {payment.external_id} is succeeded but has no "
                        "payment.succeeded webhook event."
                    ),
                ),
            )

    for refund in refunds:
        if (
            refund.status == "succeeded"
            and refund.external_id not in refund_succeeded_event_ids
        ):
            mismatches.append(
                ReconciliationMismatchDraft(
                    mismatch_type="missing_refund_succeeded_event",
                    severity="warning",
                    entity_type="refund",
                    entity_external_id=refund.external_id,
                    expected="refund.succeeded webhook",
                    actual="missing",
                    message=(
                        f"Refund {refund.external_id} is succeeded but has no "
                        "refund.succeeded webhook event."
                    ),
                ),
            )

    for event in webhook_events:
        payload = safe_payload(event.payload)
        if event.event_type.startswith("payment."):
            payment_external_id = payload_string(payload, "payment_external_id")
            if payment_external_id is None:
                continue
            payment = payments_by_external_id.get(payment_external_id)
            if payment is None:
                mismatches.append(
                    ReconciliationMismatchDraft(
                        mismatch_type="webhook_missing_payment",
                        severity="error",
                        entity_type="webhook_event",
                        entity_external_id=event.external_id,
                        expected=f"payment {payment_external_id}",
                        actual="missing",
                        message=(
                            f"Webhook event {event.external_id} references missing "
                            f"payment {payment_external_id}."
                        ),
                    ),
                )
                continue
            mismatches.extend(payment_status_mismatches(event, payment))

        if event.event_type.startswith("refund."):
            refund_external_id = payload_string(payload, "refund_external_id")
            if refund_external_id is None:
                continue
            refund = refunds_by_external_id.get(refund_external_id)
            if refund is None:
                mismatches.append(
                    ReconciliationMismatchDraft(
                        mismatch_type="webhook_missing_refund",
                        severity="error",
                        entity_type="webhook_event",
                        entity_external_id=event.external_id,
                        expected=f"refund {refund_external_id}",
                        actual="missing",
                        message=(
                            f"Webhook event {event.external_id} references missing "
                            f"refund {refund_external_id}."
                        ),
                    ),
                )
                continue
            mismatches.extend(refund_status_mismatches(event, refund))

    return mismatches


def payment_status_mismatches(
    event: WebhookEvent,
    payment: Payment,
) -> list[ReconciliationMismatchDraft]:
    expected_status = event_status(event.event_type, prefix="payment")
    if expected_status is None or payment.status == expected_status:
        return []

    return [
        ReconciliationMismatchDraft(
            mismatch_type="payment_status_mismatch",
            severity="warning",
            entity_type="payment",
            entity_external_id=payment.external_id,
            expected=expected_status,
            actual=payment.status,
            message=(
                f"Payment {payment.external_id} status is {payment.status}, but "
                f"webhook event {event.external_id} is {event.event_type}."
            ),
        ),
    ]


def refund_status_mismatches(
    event: WebhookEvent,
    refund: Refund,
) -> list[ReconciliationMismatchDraft]:
    expected_status = event_status(event.event_type, prefix="refund")
    if expected_status is None or refund.status == expected_status:
        return []

    return [
        ReconciliationMismatchDraft(
            mismatch_type="refund_status_mismatch",
            severity="warning",
            entity_type="refund",
            entity_external_id=refund.external_id,
            expected=expected_status,
            actual=refund.status,
            message=(
                f"Refund {refund.external_id} status is {refund.status}, but "
                f"webhook event {event.external_id} is {event.event_type}."
            ),
        ),
    ]


def event_status(event_type: str, prefix: str) -> str | None:
    for status in ("succeeded", "failed"):
        if event_type == f"{prefix}.{status}":
            return status
    return None


def matching_payload_ids(
    webhook_events: list[WebhookEvent],
    event_type: str,
    payload_key: str,
) -> set[str]:
    return {
        payload_id
        for event in webhook_events
        if event.event_type == event_type
        for payload_id in [payload_string(safe_payload(event.payload), payload_key)]
        if payload_id is not None
    }


def safe_payload(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    return {}


def payload_string(payload: dict[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if isinstance(value, str) and value:
        return value
    return None


def create_reconciliation_session_factory(settings: Settings | None = None):
    engine = initialize_database(settings or load_settings())
    return create_session_factory(engine)


def make_reconciliation_external_id() -> str:
    return f"rec_{uuid4().hex[:12]}"


def make_mismatch_external_id() -> str:
    return f"mis_{uuid4().hex[:12]}"


def summarize_currency(
    payment_currencies: list[str], refund_currencies: list[str]
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


def sum_money(amounts) -> Decimal:
    total = ZERO
    for amount in amounts:
        total += amount
    return total.quantize(ZERO)


def run_summary(
    run: ReconciliationRun,
    mismatches: list[ReconciliationMismatchRow],
) -> ReconciliationRunSummary:
    return ReconciliationRunSummary(
        external_id=run.external_id,
        status=run.status,
        payment_count=run.payment_count,
        refund_count=run.refund_count,
        webhook_event_count=run.webhook_event_count,
        mismatch_count=run.mismatch_count,
        total_payment_amount=run.total_payment_amount,
        total_refund_amount=run.total_refund_amount,
        net_amount=run.net_amount,
        currency=run.currency,
        started_at=run.started_at,
        completed_at=run.completed_at,
        created_at=run.created_at,
        summary_json=run.summary_json,
        mismatches=mismatches,
    )


def run_row(run: ReconciliationRun) -> ReconciliationRunRow:
    return ReconciliationRunRow(
        external_id=run.external_id,
        status=run.status,
        payment_count=run.payment_count,
        refund_count=run.refund_count,
        webhook_event_count=run.webhook_event_count,
        mismatch_count=run.mismatch_count,
        net_amount=run.net_amount,
        currency=run.currency,
        created_at=run.created_at,
        completed_at=run.completed_at,
    )


def mismatch_row(
    mismatch: ReconciliationMismatch,
    run_external_id: str,
) -> ReconciliationMismatchRow:
    return ReconciliationMismatchRow(
        run_external_id=run_external_id,
        external_id=mismatch.external_id,
        mismatch_type=mismatch.mismatch_type,
        severity=mismatch.severity,
        entity_type=mismatch.entity_type,
        entity_external_id=mismatch.entity_external_id,
        expected=mismatch.expected,
        actual=mismatch.actual,
        message=mismatch.message,
        created_at=mismatch.created_at,
    )
