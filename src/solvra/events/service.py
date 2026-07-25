from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from solvra.config import Settings, load_settings
from solvra.db import create_session_factory, initialize_database
from solvra.events.schemas import EventDataBatch, EventValidationError
from solvra.models import WebhookEvent


@dataclass(frozen=True)
class EventIngestionSummary:
    inserted: int = 0
    skipped: int = 0

    def rows(self) -> list[tuple[str, int, int]]:
        return [("webhook_events", self.inserted, self.skipped)]


@dataclass(frozen=True)
class EventRow:
    external_id: str
    event_type: str
    source: str | None
    created_at: datetime
    processed: str


@dataclass(frozen=True)
class EventDetail:
    external_id: str
    event_type: str
    source: str | None
    payload: dict[str, Any]
    received_at: datetime
    created_at: datetime
    processed: str


def load_webhook_event_data(path: Path) -> EventDataBatch:
    try:
        raw_data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise EventValidationError(f"could not read {path}") from exc
    except json.JSONDecodeError as exc:
        raise EventValidationError(f"{path} is not valid JSON") from exc

    if not isinstance(raw_data, dict):
        raise EventValidationError("webhook event data must be a JSON object")
    return EventDataBatch.from_mapping(raw_data)


def ingest_webhook_events_file(
    path: Path,
    settings: Settings | None = None,
) -> EventIngestionSummary:
    batch = load_webhook_event_data(path)
    active_settings = settings or load_settings()
    engine = initialize_database(active_settings)
    session_factory = create_session_factory(engine)

    with session_factory() as session:
        summary = ingest_webhook_events(session, batch)
        session.commit()
        return summary


def ingest_webhook_events(
    session: Session,
    batch: EventDataBatch,
) -> EventIngestionSummary:
    existing_events = existing_event_ids(
        session,
        [event.external_id for event in batch.events],
    )
    inserted = 0

    for item in batch.events:
        if item.external_id in existing_events:
            continue
        session.add(
            WebhookEvent(
                external_id=item.external_id,
                event_type=item.event_type,
                payload=payload_with_source(item.payload, item.source),
            ),
        )
        inserted += 1

    return EventIngestionSummary(
        inserted=inserted,
        skipped=len(batch.events) - inserted,
    )


def list_webhook_events(settings: Settings | None = None) -> list[EventRow]:
    session_factory = create_event_session_factory(settings)
    with session_factory() as session:
        events = session.scalars(
            select(WebhookEvent).order_by(
                WebhookEvent.created_at,
                WebhookEvent.external_id,
            ),
        ).all()

        return [
            EventRow(
                external_id=event.external_id,
                event_type=event.event_type,
                source=event_source(event.payload),
                created_at=event.created_at,
                processed=processed_status(event),
            )
            for event in events
        ]


def webhook_event_detail(
    external_id: str,
    settings: Settings | None = None,
) -> EventDetail | None:
    session_factory = create_event_session_factory(settings)
    with session_factory() as session:
        event = session.scalar(
            select(WebhookEvent).where(WebhookEvent.external_id == external_id),
        )
        if event is None:
            return None

        return EventDetail(
            external_id=event.external_id,
            event_type=event.event_type,
            source=event_source(event.payload),
            payload=display_payload(event.payload),
            received_at=event.received_at,
            created_at=event.created_at,
            processed=processed_status(event),
        )


def existing_event_ids(session: Session, external_ids: list[str]) -> set[str]:
    if not external_ids:
        return set()
    return set(
        session.scalars(
            select(WebhookEvent.external_id).where(
                WebhookEvent.external_id.in_(external_ids),
            ),
        ),
    )


def create_event_session_factory(settings: Settings | None = None):
    engine = initialize_database(settings or load_settings())
    return create_session_factory(engine)


def payload_with_source(payload: dict[str, Any], source: str | None) -> dict[str, Any]:
    persisted_payload = dict(payload)
    if source:
        persisted_payload["source"] = source
    return persisted_payload


def event_source(payload: dict[str, Any]) -> str | None:
    source = payload.get("source")
    if isinstance(source, str) and source:
        return source
    return None


def display_payload(payload: dict[str, Any]) -> dict[str, Any]:
    visible_payload = dict(payload)
    visible_payload.pop("source", None)
    return visible_payload


def processed_status(event: WebhookEvent) -> str:
    return "yes" if event.processed_at else "no"
