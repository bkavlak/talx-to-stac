"""The STAC side of the world.

Every naming decision -- identifiers, the ``talk:`` property namespace, asset
keys, which reference becomes an asset and which becomes a link -- is made here
and nowhere else, so that changing the STAC shape never reaches into the pretalx
model, the venue or a reference source.
"""

from __future__ import annotations

import datetime as dt
import re
import unicodedata
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

import pystac

from talx_to_stac.references import Kind

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from talx_to_stac.references import Reference, ReferenceSource
    from talx_to_stac.schedule import Event, Schedule, Session
    from talx_to_stac.venue import Venue

LICENSE = "other"
"""Pretalx states no event-wide licence, only a per-session recording licence."""

_PRESENTATION_TYPES = frozenset(
    {
        "application/pdf",
        "application/vnd.ms-powerpoint",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "application/vnd.oasis.opendocument.presentation",
    }
)


def build_collection(
    schedule: Schedule,
    venue: Venue,
    references: ReferenceSource,
    *,
    collection_id: str | None = None,
) -> pystac.Collection:
    """Map a pretalx schedule onto a STAC Collection of talks.

    Args:
        schedule: The parsed pretalx schedule.
        venue: Supplies each room's coordinate.
        references: Supplies each session's URLs.
        collection_id: Identifier for the Collection, defaulting to the pretalx
            acronym. Override it where that acronym would collide, such as
            inside a catalog that also has a collection per conference.

    Returns:
        A Collection holding one Item per scheduled session, with both extents
        derived from those Items.
    """
    items = [_item(session, schedule, venue, references) for session in schedule.sessions]
    collection = pystac.Collection(
        id=collection_id or schedule.event.acronym,
        title=schedule.event.title,
        description=_describe(schedule),
        extent=extent_of(items),
        license=LICENSE,
        keywords=list(schedule.event.tracks),
        providers=_providers(schedule.event),
        summaries=_summaries(items),
        extra_fields={
            "talk:event": schedule.event.acronym,
            "talk:timezone": schedule.event.timezone,
            "talk:schedule_version": schedule.event.version,
        },
    )
    if schedule.event.schedule_url:
        collection.add_link(
            pystac.Link(rel="via", target=schedule.event.schedule_url, title="Schedule")
        )
    collection.add_items(items)
    return collection


def _item(
    session: Session,
    schedule: Schedule,
    venue: Venue,
    references: ReferenceSource,
) -> pystac.Item:
    geometry = venue.point_for(session.room)
    lon, lat = geometry["coordinates"]
    room = schedule.room(session.room)
    item = pystac.Item(
        id=session.code,
        geometry=geometry,
        bbox=[lon, lat, lon, lat],
        datetime=_utc(session.midpoint),
        properties={
            "title": session.title,
            "description": _prose(session),
            "start_datetime": _stamp(session.start),
            "end_datetime": _stamp(session.end),
            "talk:code": session.code,
            "talk:guid": session.guid,
            "talk:event": schedule.event.acronym,
            "talk:track": session.track,
            "talk:type": session.type,
            "talk:subtitle": session.subtitle,
            "talk:language": session.language,
            "talk:room": session.room,
            "talk:room_capacity": room.capacity if room else None,
            "talk:duration_minutes": round(session.duration.total_seconds() / 60),
            "talk:speakers": [
                {"code": p.code, "name": p.name, "url": p.url} for p in session.persons
            ],
            "talk:do_not_record": session.do_not_record,
            "talk:recording_license": session.recording_license,
        },
    )
    item.properties = {k: v for k, v in item.properties.items() if v not in (None, "", [])}

    found = list(references.references_for(session, schedule))
    _add_assets(item, session, found)
    _add_links(item, session, found)
    return item


def _add_assets(item: pystac.Item, session: Session, references: Iterable[Reference]) -> None:
    """Attach the talk page and every downloadable artifact of the talk."""
    keys = _Keys()
    item.add_asset(
        keys.take("schedule"),
        pystac.Asset(
            href=session.url, title="Talk page", media_type="text/html", roles=["metadata"]
        ),
    )
    for reference in references:
        if reference.kind is Kind.RECORDING:
            key, roles = "recording", ["data", "video"]
        elif reference.kind is Kind.RESOURCE:
            key = _slug(reference.title) or "resource"
            roles = ["presentation" if reference.media_type in _PRESENTATION_TYPES else "data"]
        else:
            continue
        # A named platform identifies the asset better than a collision counter,
        # and belongs among its roles rather than in a field of its own.
        if reference.source:
            key, roles = f"{key}-{reference.source}", [*roles, reference.source]
        item.add_asset(
            keys.take(key),
            pystac.Asset(
                href=reference.url,
                title=reference.title,
                media_type=reference.media_type,
                roles=roles,
            ),
        )


def _add_links(item: pystac.Item, session: Session, references: Iterable[Reference]) -> None:
    """Point at the talk, its speakers, and whatever the talk merely names."""
    item.add_link(pystac.Link(rel="via", target=session.url, title=session.title))
    if session.feedback_url:
        # A form to submit to, not a document to retrieve, so not an asset.
        item.add_link(pystac.Link(rel="related", target=session.feedback_url, title="Feedback"))
    for person in session.persons:
        if person.url:
            item.add_link(pystac.Link(rel="related", target=person.url, title=person.name))
    for reference in references:
        if reference.kind is Kind.MENTION:
            item.add_link(pystac.Link(rel="related", target=reference.url, title=reference.title))


def extent_of(items: Iterable[pystac.Item]) -> pystac.Extent:
    """Cover every Item in space and time: the one extent rule, for any level of the tree.

    With no Items there is nothing to cover, so the extent is the whole Earth and
    all time, which is valid STAC where pystac's own empty extent is not.
    """
    found = list(items)
    if not found:
        always: list[dt.datetime | None] = [None, None]
        return pystac.Extent(
            pystac.SpatialExtent([[-180.0, -90.0, 180.0, 90.0]]),
            pystac.TemporalExtent([always]),
        )
    return pystac.Extent.from_items(found)


def _summaries(items: Sequence[pystac.Item]) -> pystac.Summaries:
    """Offer the fields a consumer would filter on."""
    fields = ("talk:track", "talk:type", "talk:room", "talk:language")
    summaries = {
        field: sorted({str(i.properties[field]) for i in items if i.properties.get(field)})
        for field in fields
    }
    return pystac.Summaries({k: v for k, v in summaries.items() if v})


def _providers(event: Event) -> list[pystac.Provider]:
    host = urlsplit(event.schedule_url).netloc
    if not host:
        return []
    return [
        pystac.Provider(
            name=host,
            description="pretalx instance publishing this schedule",
            roles=[pystac.ProviderRole.HOST, pystac.ProviderRole.PROCESSOR],
            url=f"https://{host}",
        )
    ]


def _describe(schedule: Schedule) -> str:
    rooms = len({s.room for s in schedule.sessions})
    return (
        f"{schedule.event.title}: {len(schedule.sessions)} scheduled sessions "
        f"across {rooms} rooms, mapped from pretalx."
    )


def _prose(session: Session) -> str:
    return "\n\n".join(part for part in (session.abstract, session.description) if part)


def _utc(moment: dt.datetime) -> dt.datetime:
    return moment.astimezone(dt.UTC)


def _stamp(moment: dt.datetime) -> str:
    return pystac.utils.datetime_to_str(_utc(moment))


class _Keys:
    """Hands out asset keys, keeping them unique and stable within one Item."""

    def __init__(self) -> None:
        self._seen: dict[str, int] = {}

    def take(self, key: str) -> str:
        """Return ``key``, suffixed if it has been taken already."""
        self._seen[key] = self._seen.get(key, 0) + 1
        return key if self._seen[key] == 1 else f"{key}-{self._seen[key]}"


def _slug(text: str) -> str:
    folded = unicodedata.normalize("NFKD", text)
    ascii_only = "".join(c for c in folded if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "-", ascii_only.lower()).strip("-")[:60]
