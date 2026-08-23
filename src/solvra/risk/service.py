from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import func, select

from solvra.config import Settings, load_settings
from solvra.db import create_session_factory, initialize_database
from solvra.models import (
    Customer,
    Payment,
    ReconciliationMismatch,
    ReconciliationRun,
    Refund,
    WebhookEvent,
)


@dataclass(frozen=True)
class RiskFinding:
    severity: str
    category: str
    message: str
    related_entity: str | None = None


@dataclass(frozen=True)
class RiskScanResult:
    risk_level: str
    payment_count: int
    refund_count: int
    customer_count: int
    webhook_event_count: int
    reconciliation_run_count: int
    reconciliation_mismatch_count: int
    findings: list[RiskFinding]
    recommendations: list[str]


def scan_local_risks(settings: Settings | None = None) -> RiskScanResult:
    active_settings = settings or load_settings()
    engine = initialize_database(active_settings)
    session_factory = create_session_factory(engine)

    with session_factory() as session:
        payment_count = count_records(session, Payment)
        refund_count = count_records(session, Refund)
        customer_count = count_records(session, Customer)
        webhook_event_count = count_records(session, WebhookEvent)
        reconciliation_run_count = count_records(session, ReconciliationRun)
        mismatches = session.scalars(
            select(ReconciliationMismatch).order_by(
                ReconciliationMismatch.created_at,
                ReconciliationMismatch.external_id,
            ),
        ).all()
        latest_run = session.scalar(
            select(ReconciliationRun).order_by(
                ReconciliationRun.created_at.desc(),
                ReconciliationRun.external_id.desc(),
            ),
        )

        findings = data_completeness_findings(
            payment_count,
            customer_count,
            reconciliation_run_count,
        )
        findings.extend(
            coverage_findings(
                payment_count,
                webhook_event_count,
                reconciliation_run_count,
            ),
        )
        findings.extend(transaction_findings(session))
        findings.extend(mismatch_findings(mismatches, latest_run))
        findings.extend(over_refund_findings(session))
        findings.extend(duplicate_payment_findings(session))

        return RiskScanResult(
            risk_level=risk_level_for(findings),
            payment_count=payment_count,
            refund_count=refund_count,
            customer_count=customer_count,
            webhook_event_count=webhook_event_count,
            reconciliation_run_count=reconciliation_run_count,
            reconciliation_mismatch_count=len(mismatches),
            findings=findings,
            recommendations=recommendations_for(findings),
        )


def count_records(session, model) -> int:
    return int(session.scalar(select(func.count(model.id))) or 0)


def data_completeness_findings(
    payment_count: int,
    customer_count: int,
    reconciliation_run_count: int,
) -> list[RiskFinding]:
    findings: list[RiskFinding] = []
    if payment_count == 0:
        findings.append(
            RiskFinding(
                severity="low",
                category="data completeness",
                message="No payments found; local revenue summary data is unavailable.",
            ),
        )
    if customer_count == 0:
        findings.append(
            RiskFinding(
                severity="low",
                category="data completeness",
                message="No customers found.",
            ),
        )
    if reconciliation_run_count == 0:
        findings.append(
            RiskFinding(
                severity="low",
                category="data completeness",
                message="No reconciliation runs found.",
            ),
        )
    return findings


def coverage_findings(
    payment_count: int,
    webhook_event_count: int,
    reconciliation_run_count: int,
) -> list[RiskFinding]:
    findings: list[RiskFinding] = []
    if payment_count > 0 and webhook_event_count == 0:
        findings.append(
            RiskFinding(
                severity="medium",
                category="webhooks",
                message="Payments exist but no webhook events have been ingested.",
            ),
        )
    if webhook_event_count > 0 and reconciliation_run_count == 0:
        findings.append(
            RiskFinding(
                severity="medium",
                category="reconciliation",
                message=(
                    "Webhook events exist but no reconciliation run has been created."
                ),
            ),
        )
    return findings


def transaction_findings(session) -> list[RiskFinding]:
    failed_payment_count = count_matching_status(session, Payment, "failed")
    failed_refund_count = count_matching_status(session, Refund, "failed")
    findings: list[RiskFinding] = []
    if failed_payment_count:
        findings.append(
            RiskFinding(
                severity="high",
                category="payments",
                message=f"{failed_payment_count} failed payment(s) found.",
                related_entity="payments",
            ),
        )
    if failed_refund_count:
        findings.append(
            RiskFinding(
                severity="high",
                category="refunds",
                message=f"{failed_refund_count} failed refund(s) found.",
                related_entity="refunds",
            ),
        )
    return findings


def count_matching_status(session, model, status: str) -> int:
    return int(
        session.scalar(
            select(func.count(model.id)).where(model.status == status),
        )
        or 0
    )


def mismatch_findings(
    mismatches: list[ReconciliationMismatch],
    latest_run: ReconciliationRun | None,
) -> list[RiskFinding]:
    findings = [
        RiskFinding(
            severity="high" if mismatch.severity == "error" else "medium",
            category="reconciliation",
            message=mismatch.message,
            related_entity=(f"{mismatch.entity_type}:{mismatch.entity_external_id}"),
        )
        for mismatch in mismatches
    ]
    if latest_run is not None and latest_run.mismatch_count:
        findings.append(
            RiskFinding(
                severity=(
                    "high"
                    if any(mismatch.severity == "error" for mismatch in mismatches)
                    else "medium"
                ),
                category="reconciliation",
                message=(
                    f"Latest reconciliation run {latest_run.external_id} has "
                    f"{latest_run.mismatch_count} mismatch(es)."
                ),
                related_entity=latest_run.external_id,
            ),
        )
    return findings


def over_refund_findings(session) -> list[RiskFinding]:
    rows = session.execute(
        select(Payment.external_id, Payment.amount, func.sum(Refund.amount))
        .join(Refund, Refund.payment_id == Payment.id)
        .group_by(Payment.id)
        .order_by(Payment.external_id),
    ).all()
    findings: list[RiskFinding] = []
    for external_id, payment_amount, refund_amount in rows:
        if refund_amount > payment_amount:
            findings.append(
                RiskFinding(
                    severity="high",
                    category="refunds",
                    message=(
                        f"Refund total {format_money(refund_amount)} exceeds payment "
                        f"amount {format_money(payment_amount)}."
                    ),
                    related_entity=f"payment:{external_id}",
                ),
            )
    return findings


def duplicate_payment_findings(session) -> list[RiskFinding]:
    rows = session.execute(
        select(
            Payment.customer_id,
            Payment.merchant_account_id,
            Payment.amount,
            Payment.currency,
            Payment.status,
            func.count(Payment.id),
        )
        .group_by(
            Payment.customer_id,
            Payment.merchant_account_id,
            Payment.amount,
            Payment.currency,
            Payment.status,
        )
        .having(func.count(Payment.id) > 1)
        .order_by(Payment.customer_id, Payment.merchant_account_id),
    ).all()
    findings: list[RiskFinding] = []
    for customer_id, account_id, amount, currency, status, count in rows:
        findings.append(
            RiskFinding(
                severity="medium",
                category="data quality",
                message=(
                    f"{count} payments share amount {format_money(amount)} {currency} "
                    f"and status {status}."
                ),
                related_entity=f"customer:{customer_id} account:{account_id}",
            ),
        )
    return findings


def risk_level_for(findings: list[RiskFinding]) -> str:
    if any(finding.severity == "high" for finding in findings):
        return "high"
    if any(finding.severity == "medium" for finding in findings):
        return "medium"
    return "low"


def recommendations_for(findings: list[RiskFinding]) -> list[str]:
    recommended_by_category = {
        "data completeness": "Load local demo data and run reconciliation.",
        "data quality": "Review duplicate-looking payment records.",
        "payments": "Review failed payment records.",
        "reconciliation": "Review reconciliation mismatches and related records.",
        "refunds": "Review failed or over-refunded payment records.",
        "webhooks": "Review webhook ingestion and event coverage.",
    }
    recommendations: list[str] = []
    for finding in findings:
        recommendation = recommended_by_category[finding.category]
        if recommendation not in recommendations:
            recommendations.append(recommendation)
    return recommendations


def format_money(amount: Decimal) -> str:
    return f"{amount:.2f}"
