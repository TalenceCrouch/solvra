from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select

from solvra.config import Settings, load_settings
from solvra.db import create_session_factory, initialize_database
from solvra.events.schemas import SUPPORTED_EVENT_TYPES
from solvra.models import WebhookEvent

REPLAY_HANDLERS = {event_type: event_type for event_type in SUPPORTED_EVENT_TYPES}


class EventReplayError(ValueError):
    pass


@dataclass(frozen=True)
class ReplayResult:
    external_id: str
    event_type: str
    handler_name: str
    status: str
    message: str


@dataclass(frozen=True)
class ReplaySummary:
    results: list[ReplayResult]
    event_type: str | None = None

    @property
    def processed(self) -> int:
        return count_status(self.results, "processed")

    @property
    def skipped(self) -> int:
        return count_status(self.results, "skipped")

    @property
    def failed(self) -> int:
        return count_status(self.results, "failed")


def replay_webhook_event_by_id(
    external_id: str,
    settings: Settings | None = None,
) -> ReplayResult:
    session_factory = create_replay_session_factory(settings)
    with session_factory() as session:
        event = session.scalar(
            select(WebhookEvent).where(WebhookEvent.external_id == external_id),
        )
        if event is None:
            raise EventReplayError(f"Webhook event not found: {external_id}")
        return simulate_event_replay(event)


def replay_webhook_events_by_type(
    event_type: str,
    settings: Settings | None = None,
) -> ReplaySummary:
    validate_replay_event_type(event_type)
    session_factory = create_replay_session_factory(settings)
    with session_factory() as session:
        events = session.scalars(
            select(WebhookEvent)
            .where(WebhookEvent.event_type == event_type)
            .order_by(WebhookEvent.created_at, WebhookEvent.external_id),
        ).all()
        return ReplaySummary(
            results=[simulate_event_replay(event) for event in events],
            event_type=event_type,
        )


def simulate_event_replay(event: WebhookEvent) -> ReplayResult:
    handler_name = validate_replay_event_type(event.event_type)
    message = f"Replayed {event.external_id} with handler {handler_name}"
    payload = event.payload if isinstance(event.payload, dict) else {}
    target = replay_target(event.event_type, payload)
    if target:
        message = f"{message} for {target}"

    return ReplayResult(
        external_id=event.external_id,
        event_type=event.event_type,
        handler_name=handler_name,
        status="processed",
        message=message,
    )


def validate_replay_event_type(event_type: str) -> str:
    handler_name = REPLAY_HANDLERS.get(event_type)
    if handler_name is None:
        raise EventReplayError(f"Unsupported webhook event type: {event_type}")
    return handler_name


def replay_target(event_type: str, payload: dict[str, Any]) -> str | None:
    if event_type.startswith("refund."):
        refund_id = payload.get("refund_external_id")
        if isinstance(refund_id, str) and refund_id:
            return f"refund {refund_id}"

    payment_id = payload.get("payment_external_id")
    if isinstance(payment_id, str) and payment_id:
        return f"payment {payment_id}"

    return None


def create_replay_session_factory(settings: Settings | None = None):
    engine = initialize_database(settings or load_settings())
    return create_session_factory(engine)


def count_status(results: list[ReplayResult], status: str) -> int:
    return sum(1 for result in results if result.status == status)
