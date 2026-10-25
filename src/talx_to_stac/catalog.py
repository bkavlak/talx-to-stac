"""Conferences, which pretalx does not model.

A conference publishes its talks, its workshops and its academic programme as
separate pretalx events with no link between them -- only a naming convention,
and an inconsistent one: ``foss4g-2024-workshop`` but
``foss4g-europe-2024-workshops``. Nothing can infer the grouping, so it is
stated here as data, and this module turns it into the STAC tree:

    Catalog -> Collection per conference -> Collection per programme -> Items
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import pystac

from talx_to_stac import to_stac
from talx_to_stac.stac import LICENSE, extent_of

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence
    from pathlib import Path

    from talx_to_stac.references import ReferenceSource
    from talx_to_stac.venue import Venue


@dataclass(frozen=True, slots=True)
class Programme:
    """One pretalx event within a conference.

    Named for what it is to an attendee -- ``talks``, ``workshops``,
    ``academic`` -- not for the pretalx slug behind it. Some conferences run
    only one; a few run all three.
    """

    name: str
    event_url: str
    references: Sequence[ReferenceSource] = ()
    """Sources beyond the offline defaults, such as its recordings."""


@dataclass(frozen=True, slots=True)
class Conference:
    """One edition of a conference, with the programmes it published."""

    id: str
    title: str
    programmes: Sequence[Programme]
    venue: Venue | Mapping[str, Any] | str | Path | None = None
    """Room coordinates, in any form :func:`~talx_to_stac.to_stac` accepts."""

    description: str = field(default="")


def to_catalog(
    conferences: Iterable[Conference],
    *,
    catalog_id: str = "conferences",
    title: str = "Conferences",
    description: str = "Conference talks as STAC Items, mapped from pretalx.",
) -> pystac.Catalog:
    """Transform several conferences into one STAC Catalog.

    Args:
        conferences: The conferences to build, each naming its programmes.
        catalog_id: Identifier for the root Catalog.
        title: Title for the root Catalog.
        description: Description for the root Catalog.

    Returns:
        A Catalog holding one Collection per conference, each holding one
        Collection per programme, each holding one Item per session.

    Raises:
        ScheduleError: If any programme's schedule cannot be fetched or parsed.
    """
    catalog = pystac.Catalog(id=catalog_id, title=title, description=description)
    for conference in conferences:
        catalog.add_child(_conference(conference))
    return catalog


def _conference(conference: Conference) -> pystac.Collection:
    children = [_programme(conference, p) for p in conference.programmes]
    collection = pystac.Collection(
        id=conference.id,
        title=conference.title,
        description=conference.description or _describe(conference, children),
        extent=extent_of(item for child in children for item in child.get_items()),
        license=LICENSE,
    )
    for child in children:
        collection.add_child(child)
    return collection


def _programme(conference: Conference, programme: Programme) -> pystac.Collection:
    # The pretalx acronym identifies an event, not a programme within a
    # conference, and for the talks it is the conference's own id.
    collection = to_stac(
        programme.event_url,
        venue=conference.venue,
        references=programme.references,
        collection_id=f"{conference.id}-{programme.name}",
    )
    # Inside a conference, "FOSS4G 2024" beside "FOSS4G 2024 Belem" says
    # nothing; the programme's own name is what tells the three apart. The
    # event's title survives in the description.
    collection.title = programme.name.capitalize()
    collection.extra_fields["talk:programme"] = programme.name
    return collection


def _describe(conference: Conference, children: Sequence[pystac.Collection]) -> str:
    parts = ", ".join(
        f"{len(list(c.get_items()))} {p.name}"
        for c, p in zip(children, conference.programmes, strict=True)
    )
    return f"{conference.title}: {parts}."
