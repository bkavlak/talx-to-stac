"""Map a pretalx conference schedule to a STAC Collection.

Example:
    >>> from talx_to_stac import to_stac
    >>> collection = to_stac("https://talks.osgeo.org/foss4g-europe-2025/schedule/")
    >>> collection.normalize_and_save("./stac")
"""

from __future__ import annotations

import logging
from pathlib import PurePath
from typing import TYPE_CHECKING, Any

from talx_to_stac.recordings import Recordings, Video, VideoCatalogue
from talx_to_stac.references import (
    AbstractReferences,
    BiographyReferences,
    Kind,
    Reference,
    ReferenceSource,
    SubmissionReferences,
    combine,
)
from talx_to_stac.schedule import Event, Schedule, ScheduleError, Session
from talx_to_stac.stac import build_collection
from talx_to_stac.venue import Venue, VenueError

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping
    from pathlib import Path

    import pystac

__all__ = [
    "AbstractReferences",
    "BiographyReferences",
    "Event",
    "Kind",
    "Recordings",
    "Reference",
    "ReferenceSource",
    "Schedule",
    "ScheduleError",
    "Session",
    "SubmissionReferences",
    "Venue",
    "VenueError",
    "Video",
    "VideoCatalogue",
    "to_stac",
]

__version__ = "0.1.0"

_LOG = logging.getLogger(__name__)

DEFAULT_SOURCES: tuple[ReferenceSource, ...] = (
    SubmissionReferences(),
    AbstractReferences(),
    BiographyReferences(),
)
"""Sources that need no network, so the default transform stays offline after the fetch."""


def to_stac(
    event_url: str,
    *,
    venue: Venue | Mapping[str, Any] | str | Path | None = None,
    references: Iterable[ReferenceSource] = (),
    collection_id: str | None = None,
) -> pystac.Collection:
    """Transform a pretalx event into a STAC Collection of its talks.

    Args:
        event_url: Any URL inside the event, such as its schedule page.
        venue: Room coordinates, as a :class:`~talx_to_stac.venue.Venue`, a
            mapping of room names to ``[latitude, longitude]``, or the path of a
            YAML or JSON file holding that mapping. Rooms it does not cover fall
            back to its default, and omitting it altogether places every talk at
            0/0 -- the transform still succeeds, and says which rooms are missing.
        references: Extra reference sources, such as
            :class:`~talx_to_stac.recordings.Recordings`. These are added to
            :data:`DEFAULT_SOURCES`, not substituted for them.
        collection_id: Identifier for the Collection, defaulting to the pretalx
            acronym. Override it where that acronym would collide.

    Returns:
        A Collection with one Item per scheduled session. Writing it out is the
        caller's business: ``collection.normalize_and_save(...)``.

    Raises:
        ScheduleError: If the event's schedule cannot be fetched or parsed.
        VenueError: If the venue definition is not usable.
    """
    schedule = Schedule.from_url(event_url)
    place = _venue(venue)
    _warn_about_missing_rooms(schedule, place)
    sources = combine(*DEFAULT_SOURCES, *references)
    return build_collection(schedule, place, sources, collection_id=collection_id)


def _venue(venue: Venue | Mapping[str, Any] | str | Path | None) -> Venue:
    if venue is None:
        return Venue.anywhere()
    if isinstance(venue, Venue):
        return venue
    if isinstance(venue, str | PurePath):
        return Venue.from_file(venue)
    return Venue.from_mapping(venue)


def _warn_about_missing_rooms(schedule: Schedule, venue: Venue) -> None:
    missing = sorted({s.room for s in schedule.sessions if not venue.knows(s.room)})
    if missing:
        _LOG.warning("no coordinates for %d room(s): %s", len(missing), ", ".join(missing))
