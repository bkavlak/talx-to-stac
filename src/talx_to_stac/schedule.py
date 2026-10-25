"""The pretalx side of the world: a conference schedule as a domain model.

This module owns every fact about how pretalx publishes a schedule -- which URL
holds the machine-readable export, how that export is shaped, and which of its
fields lie about their type. Nothing outside this module should ever parse
pretalx JSON.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from urllib.parse import urljoin, urlsplit

import httpx

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping, Sequence

_EXPORT_SUFFIX = "schedule/export/schedule.json"
_DURATION = re.compile(r"^(\d+):(\d{2})(?::(\d{2}))?$")


class ScheduleError(RuntimeError):
    """The schedule could not be fetched or understood."""


@dataclass(frozen=True, slots=True)
class Person:
    """A speaker, as pretalx knows them."""

    code: str
    name: str
    url: str | None = None
    biography: str | None = None


@dataclass(frozen=True, slots=True)
class Resource:
    """A file or link a speaker attached to their submission."""

    title: str
    url: str


@dataclass(frozen=True, slots=True)
class Room:
    """A physical room, without coordinates -- pretalx does not have them."""

    name: str
    capacity: int | None = None
    description: str | None = None


@dataclass(frozen=True, slots=True)
class Session:
    """One scheduled slot: a talk, workshop, keynote, poster or break.

    ``start`` and ``end`` are always timezone-aware, even though the export
    states only a start and a duration.
    """

    code: str
    guid: str
    title: str
    room: str
    start: dt.datetime
    end: dt.datetime
    url: str
    subtitle: str | None = None
    abstract: str | None = None
    description: str | None = None
    track: str | None = None
    type: str | None = None
    language: str | None = None
    feedback_url: str | None = None
    recording_license: str | None = None
    do_not_record: bool = False
    persons: tuple[Person, ...] = ()
    resources: tuple[Resource, ...] = ()

    @property
    def duration(self) -> dt.timedelta:
        """How long the session runs."""
        return self.end - self.start

    @property
    def midpoint(self) -> dt.datetime:
        """The instant halfway between start and end."""
        return self.start + self.duration / 2


@dataclass(frozen=True, slots=True)
class Event:
    """One pretalx event: a conference's talks, its workshops or its academic track.

    A conference usually publishes several of these, which is why this is not
    called a conference. :mod:`talx_to_stac.catalog` assembles them.
    """

    acronym: str
    title: str
    schedule_url: str
    timezone: str | None = None
    version: str | None = None
    tracks: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Schedule:
    """A whole published schedule: the event, its rooms and its sessions."""

    event: Event
    rooms: tuple[Room, ...]
    sessions: tuple[Session, ...]

    @classmethod
    def from_url(
        cls,
        event_url: str,
        *,
        client: httpx.Client | None = None,
    ) -> Schedule:
        """Fetch and parse the schedule for a pretalx event.

        Args:
            event_url: Any URL inside the event, such as its schedule page.
            client: An httpx client to reuse. One is created and closed if omitted.

        Returns:
            The parsed schedule.

        Raises:
            ScheduleError: If the export cannot be fetched or is not valid JSON.
        """
        url = export_url(event_url)
        try:
            if client is None:
                with httpx.Client(timeout=30.0, follow_redirects=True) as owned:
                    payload = owned.get(url).raise_for_status().json()
            else:
                payload = client.get(url).raise_for_status().json()
        except (httpx.HTTPError, ValueError) as exc:
            msg = f"could not read the pretalx export at {url}: {exc}"
            raise ScheduleError(msg) from exc
        return cls.from_payload(payload)

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> Schedule:
        """Parse an already-fetched frab export.

        Accepts both export layouts pretalx emits: one nests rooms, tracks and
        days directly under ``schedule``, the other nests them under
        ``schedule.conference``.

        Args:
            payload: The decoded ``schedule.json`` document.

        Returns:
            The parsed schedule.

        Raises:
            ScheduleError: If the document has no recognisable day structure.
        """
        body = payload.get("schedule", payload)
        meta = body.get("conference") or {}
        core = body if "days" in body else meta
        if "days" not in core:
            msg = "export contains no 'days'; this does not look like a pretalx schedule"
            raise ScheduleError(msg)

        schedule_url = str(body.get("url") or "")
        base = str(body.get("base_url") or _origin(schedule_url))
        event = Event(
            acronym=str(meta.get("acronym") or "conference"),
            title=str(meta.get("title") or meta.get("acronym") or "Conference"),
            schedule_url=schedule_url,
            timezone=meta.get("time_zone_name"),
            version=str(body.get("version")) if body.get("version") is not None else None,
            tracks=tuple(str(t["name"]) for t in core.get("tracks", []) if t.get("name")),
        )

        sessions = tuple(sorted(_sessions(core["days"], base), key=lambda s: (s.start, s.room)))
        rooms = _rooms(core.get("rooms", []), sessions)
        return cls(event=event, rooms=rooms, sessions=sessions)

    def room(self, name: str) -> Room | None:
        """Look up a room by its exact name."""
        return next((r for r in self.rooms if r.name == name), None)


def export_url(event_url: str) -> str:
    """Turn any URL inside a pretalx event into its JSON export URL.

    ``https://talks.osgeo.org/foss4g-europe-2025/schedule/`` and the bare event
    root both become the event's ``schedule/export/schedule.json``.

    Args:
        event_url: Any URL inside the event.

    Returns:
        The absolute URL of the machine-readable export.
    """
    if event_url.endswith("schedule.json"):
        return event_url
    root = event_url.split("/schedule", 1)[0].rstrip("/")
    return f"{root}/{_EXPORT_SUFFIX}"


def _origin(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}" if parts.netloc else ""


def _sessions(days: Sequence[Mapping[str, Any]], base: str) -> Iterator[Session]:
    """Yield each session once; the export repeats them across days and rooms."""
    seen: set[str] = set()
    for day in days:
        for room_name, slots in (day.get("rooms") or {}).items():
            for raw in slots:
                key = str(raw.get("guid") or raw.get("code") or id(raw))
                if key in seen:
                    continue
                seen.add(key)
                yield _session(raw, room_name, base)


def _session(raw: Mapping[str, Any], room: str, base: str) -> Session:
    start = dt.datetime.fromisoformat(str(raw["date"]))
    return Session(
        code=str(raw.get("code") or raw.get("guid")),
        guid=str(raw.get("guid") or raw.get("code")),
        title=str(raw.get("title") or "").strip(),
        room=str(raw.get("room") or room),
        start=start,
        end=start + _duration(raw.get("duration")),
        url=_absolute(raw.get("url") or raw.get("origin_url") or "", base),
        subtitle=_text(raw.get("subtitle")),
        abstract=_text(raw.get("abstract")),
        description=_text(raw.get("description")),
        track=_text(raw.get("track")),
        type=_text(raw.get("type")),
        language=_text(raw.get("language")),
        feedback_url=_absolute(raw["feedback_url"], base) if raw.get("feedback_url") else None,
        recording_license=_text(raw.get("recording_license")),
        do_not_record=bool(raw.get("do_not_record")),
        persons=tuple(_person(p, base) for p in raw.get("persons") or ()),
        resources=tuple(_resources(raw, base)),
    )


def _person(raw: Mapping[str, Any], base: str) -> Person:
    return Person(
        code=str(raw.get("code") or ""),
        name=str(raw.get("public_name") or raw.get("name") or "").strip(),
        url=_absolute(raw["url"], base) if raw.get("url") else None,
        biography=_text(raw.get("biography")),
    )


def _resources(raw: Mapping[str, Any], base: str) -> Iterator[Resource]:
    """Merge the two places pretalx keeps submission resources into one list."""
    for group in ("attachments", "links"):
        for item in raw.get(group) or ():
            url = str(item.get("url") or "").strip()
            if url:
                yield Resource(
                    title=str(item.get("title") or url).strip(), url=_absolute(url, base)
                )


def _rooms(raw: Sequence[Mapping[str, Any]], sessions: Sequence[Session]) -> tuple[Room, ...]:
    """Use the declared rooms, falling back to the ones the sessions mention.

    Some events omit the room block entirely, so the schedule itself is the only
    evidence a room exists.
    """
    declared = {
        str(r["name"]): Room(
            name=str(r["name"]),
            capacity=int(r["capacity"]) if r.get("capacity") is not None else None,
            description=_text(r.get("description")),
        )
        for r in raw
        if r.get("name")
    }
    for session in sessions:
        declared.setdefault(session.room, Room(name=session.room))
    return tuple(declared.values())


def _duration(value: object) -> dt.timedelta:
    match = _DURATION.match(str(value or "").strip())
    if not match:
        return dt.timedelta()
    hours, minutes, seconds = match.groups()
    return dt.timedelta(hours=int(hours), minutes=int(minutes), seconds=int(seconds or 0))


def _text(value: object) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None


def _absolute(url: str, base: str) -> str:
    return urljoin(base + "/", url) if base and not url.startswith(("http://", "https://")) else url
