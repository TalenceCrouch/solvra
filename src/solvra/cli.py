from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from solvra import __version__
from solvra.config import load_settings
from solvra.db import initialize_database
from solvra.events import (
    EventValidationError,
    ingest_webhook_events_file,
    list_webhook_events,
    webhook_event_detail,
)
from solvra.ingest import IngestionValidationError, ingest_payments_file
from solvra.queries import (
    list_customers,
    list_payments,
    list_refunds,
    payment_detail,
)

APP_NAME = "Solvra"
APP_SUBTITLE = "Echelon Proxy"

app = typer.Typer(help="Solvra payments operations CLI.")
payments_app = typer.Typer(help="Inspect local payment records.")
customers_app = typer.Typer(help="Inspect local customer records.")
refunds_app = typer.Typer(help="Inspect local refund records.")
events_app = typer.Typer(help="Ingest and inspect local webhook events.")
console = Console()

app.add_typer(payments_app, name="payments")
app.add_typer(customers_app, name="customers")
app.add_typer(refunds_app, name="refunds")
app.add_typer(events_app, name="events")


@app.callback()
def main() -> None:
    """Solvra payments operations CLI."""


@app.command()
def status() -> None:
    """Show current Solvra runtime status."""
    settings = load_settings()

    table = Table.grid(padding=(0, 2))
    table.add_column(style="bold")
    table.add_column()
    table.add_row("app name", APP_NAME)
    table.add_row("subtitle", APP_SUBTITLE)
    table.add_row("environment", settings.environment)
    table.add_row(
        "database URL configured",
        "yes" if settings.database_url_configured else "no",
    )
    table.add_row("database backend", settings.database_backend)
    table.add_row("version", __version__)

    console.print(Panel(table, title=APP_NAME, subtitle=APP_SUBTITLE))


@app.command("init-db")
def init_db() -> None:
    """Initialize the configured database."""
    settings = load_settings()
    initialize_database(settings)

    table = Table.grid(padding=(0, 2))
    table.add_column(style="bold")
    table.add_column()
    table.add_row("environment", settings.environment)
    table.add_row("database backend", settings.database_backend)

    console.print(Panel(table, title="Database initialized"))


@app.command()
def ingest(path: Path) -> None:
    """Ingest local fake payment data from a JSON file."""
    try:
        summary = ingest_payments_file(path)
    except IngestionValidationError as exc:
        console.print(f"[bold red]Ingestion failed:[/] {exc}")
        raise typer.Exit(code=1) from exc

    table = Table(title="Ingestion summary")
    table.add_column("record")
    table.add_column("inserted", justify="right")
    table.add_column("skipped", justify="right")

    for label, inserted, skipped in summary.rows():
        table.add_row(label, str(inserted), str(skipped))

    console.print(table)


@payments_app.callback()
def payments() -> None:
    """Inspect local payment records."""


@payments_app.command("list")
def list_payment_records() -> None:
    """List payments in the configured database."""
    payments = list_payments()
    if not payments:
        console.print("No payments found.")
        return

    table = Table(title="Payments", padding=(0, 0))
    table.add_column("external ID", no_wrap=True)
    table.add_column("customer", no_wrap=True)
    table.add_column("account", no_wrap=True)
    table.add_column("amount", justify="right", no_wrap=True)
    table.add_column("cur", no_wrap=True)
    table.add_column("status", no_wrap=True)
    table.add_column("created", no_wrap=True)

    for payment in payments:
        table.add_row(
            payment.external_id,
            payment.customer,
            payment.merchant_account,
            format_money(payment.amount),
            payment.currency,
            payment.status,
            format_timestamp(payment.created_at),
        )

    console.print(table)


@payments_app.command("show")
def show_payment_record(external_id: str) -> None:
    """Show payment details by external ID."""
    payment = payment_detail(external_id)
    if payment is None:
        console.print(f"[bold red]Payment not found:[/] {external_id}")
        raise typer.Exit(code=1)

    table = Table.grid(padding=(0, 2))
    table.add_column(style="bold")
    table.add_column()
    table.add_row("external ID", payment.external_id)
    table.add_row("amount", format_money(payment.amount))
    table.add_row("currency", payment.currency)
    table.add_row("status", payment.status)
    table.add_row("description", payment.description or "")
    table.add_row(
        "customer",
        format_customer_detail(
            payment.customer_external_id,
            payment.customer_email,
            payment.customer_name,
        ),
    )
    table.add_row(
        "merchant account",
        f"{payment.merchant_account_external_id} ({payment.merchant_account_name})",
    )
    table.add_row("created", format_timestamp(payment.created_at))

    console.print(Panel(table, title=f"Payment {payment.external_id}"))

    if payment.refunds:
        refunds_table = Table(title="Related refunds", padding=(0, 0))
        refunds_table.add_column("external ID")
        refunds_table.add_column("amount", justify="right")
        refunds_table.add_column("cur")
        refunds_table.add_column("status")
        refunds_table.add_column("reason")
        for refund in payment.refunds:
            refunds_table.add_row(
                refund.external_id,
                format_money(refund.amount),
                refund.currency,
                refund.status,
                refund.reason or "",
            )
        console.print(refunds_table)
    else:
        console.print("No related refunds found.")


@customers_app.callback()
def customers() -> None:
    """Inspect local customer records."""


@customers_app.command("list")
def list_customer_records() -> None:
    """List customers in the configured database."""
    customers = list_customers()
    if not customers:
        console.print("No customers found.")
        return

    table = Table(title="Customers", padding=(0, 0))
    table.add_column("external ID", no_wrap=True)
    table.add_column("email")
    table.add_column("name")
    table.add_column("created", no_wrap=True)
    table.add_column("payments", justify="right")

    for customer in customers:
        table.add_row(
            customer.external_id,
            customer.email or "",
            customer.name or "",
            format_timestamp(customer.created_at),
            str(customer.payment_count),
        )

    console.print(table)


@refunds_app.callback()
def refunds() -> None:
    """Inspect local refund records."""


@refunds_app.command("list")
def list_refund_records() -> None:
    """List refunds in the configured database."""
    refunds = list_refunds()
    if not refunds:
        console.print("No refunds found.")
        return

    table = Table(title="Refunds", padding=(0, 0))
    table.add_column("external ID", no_wrap=True)
    table.add_column("payment", no_wrap=True)
    table.add_column("amount", justify="right", no_wrap=True)
    table.add_column("cur", no_wrap=True)
    table.add_column("status", no_wrap=True)
    table.add_column("reason")
    table.add_column("created", no_wrap=True)

    for refund in refunds:
        table.add_row(
            refund.external_id,
            refund.payment_external_id,
            format_money(refund.amount),
            refund.currency,
            refund.status,
            refund.reason or "",
            format_timestamp(refund.created_at),
        )

    console.print(table)


@events_app.callback()
def events() -> None:
    """Ingest and inspect local webhook events."""


@events_app.command("ingest")
def ingest_webhook_events(path: Path) -> None:
    """Ingest local fake webhook events from a JSON file."""
    try:
        summary = ingest_webhook_events_file(path)
    except EventValidationError as exc:
        console.print(f"[bold red]Event ingestion failed:[/] {exc}")
        raise typer.Exit(code=1) from exc

    table = Table(title="Webhook event ingestion")
    table.add_column("record")
    table.add_column("inserted", justify="right")
    table.add_column("skipped", justify="right")

    for label, inserted, skipped in summary.rows():
        table.add_row(label, str(inserted), str(skipped))

    console.print(table)


@events_app.command("list")
def list_event_records() -> None:
    """List webhook events in the configured database."""
    events = list_webhook_events()
    if not events:
        console.print("No webhook events found.")
        return

    table = Table(title="Webhook events", padding=(0, 0))
    table.add_column("external ID", no_wrap=True)
    table.add_column("type", no_wrap=True)
    table.add_column("source", no_wrap=True)
    table.add_column("created", no_wrap=True)
    table.add_column("processed", no_wrap=True)

    for event in events:
        table.add_row(
            event.external_id,
            event.event_type,
            event.source or "",
            format_timestamp(event.created_at),
            event.processed,
        )

    console.print(table)


@events_app.command("show")
def show_event_record(external_id: str) -> None:
    """Show webhook event details by external ID."""
    event = webhook_event_detail(external_id)
    if event is None:
        console.print(f"[bold red]Webhook event not found:[/] {external_id}")
        raise typer.Exit(code=1)

    table = Table.grid(padding=(0, 2))
    table.add_column(style="bold")
    table.add_column()
    table.add_row("external ID", event.external_id)
    table.add_row("event type", event.event_type)
    table.add_row("source", event.source or "")
    table.add_row("processed", event.processed)
    table.add_row("received", format_timestamp(event.received_at))
    table.add_row("created", format_timestamp(event.created_at))

    console.print(Panel(table, title=f"Webhook event {event.external_id}"))
    console.print_json(data=event.payload)


def format_money(amount) -> str:
    return f"{amount:.2f}"


def format_timestamp(value) -> str:
    return value.isoformat(sep=" ", timespec="minutes")


def format_customer_detail(
    external_id: str,
    email: str | None,
    name: str | None,
) -> str:
    details = [external_id]
    if email:
        details.append(email)
    if name:
        details.append(name)
    return " / ".join(details)


if __name__ == "__main__":
    app()
