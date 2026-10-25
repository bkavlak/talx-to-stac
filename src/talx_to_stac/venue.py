"""Where a talk happens.

Pretalx knows room names; it does not know where rooms are. A ``Venue`` closes
that gap and, crucially, always answers: an unknown room falls back to the
event's own coordinate rather than producing a null geometry that every
downstream consumer would have to special-case.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

if TYPE_CHECKING:
    from collections.abc import Mapping

Coordinate = tuple[float, float]
"""Latitude then longitude, the order humans write them in."""


class VenueError(ValueError):
    """A venue definition could not be understood."""


@dataclass(frozen=True, slots=True)
class Venue:
    """A lookup from room name to a point on the Earth.

    Room names are matched loosely -- case and spacing do not matter -- so a
    mapping written by hand does not have to reproduce pretalx's exact spelling.
    """

    _points: Mapping[str, Coordinate]
    _default: Coordinate | None = None

    @classmethod
    def from_mapping(
        cls,
        rooms: Mapping[str, Any],
        *,
        default: Any = None,
    ) -> Venue:
        """Build a venue from room names to coordinates.

        Args:
            rooms: Room name to ``[latitude, longitude]``, or to a
                mapping with ``lat``/``lon`` keys.
            default: Coordinate for rooms not listed, in the same forms.

        Returns:
            The venue.

        Raises:
            VenueError: If a coordinate is not a usable latitude/longitude pair.
        """
        points = {_key(name): _coordinate(value, name) for name, value in rooms.items()}
        return cls(points, _coordinate(default, "default") if default is not None else None)

    @classmethod
    def from_file(cls, path: str | Path) -> Venue:
        """Build a venue from a YAML or JSON file.

        The file is a mapping of room names to coordinates, optionally with a
        top-level ``default`` key used for rooms it does not list.

        Args:
            path: Path to the file.

        Returns:
            The venue.

        Raises:
            VenueError: If the file is not a mapping of coordinates.
        """
        text = Path(path).read_text(encoding="utf-8")
        loaded = yaml.safe_load(text) if not text.lstrip().startswith("{") else json.loads(text)
        if not isinstance(loaded, dict):
            msg = f"{path} does not contain a mapping of room names to coordinates"
            raise VenueError(msg)
        rooms = dict(loaded)
        default = rooms.pop("default", None)
        return cls.from_mapping(rooms, default=default)

    @classmethod
    def anywhere(cls) -> Venue:
        """A venue that knows nothing, placing every room at 0/0.

        Lets a transform succeed before anyone has collected coordinates.
        """
        return cls({}, (0.0, 0.0))

    def knows(self, room: str) -> bool:
        """Whether this venue has a coordinate for the named room."""
        return _key(room) in self._points

    def point_for(self, room: str) -> dict[str, Any]:
        """The GeoJSON Point for a room, always.

        Args:
            room: The room name.

        Returns:
            A GeoJSON Point geometry. Unknown rooms get the venue default.
        """
        lat, lon = self._points.get(_key(room)) or self._default or (0.0, 0.0)
        return {"type": "Point", "coordinates": [lon, lat]}


def _key(name: str) -> str:
    return " ".join(str(name).split()).casefold()


def _coordinate(value: Any, name: str) -> Coordinate:
    pair: Any
    if isinstance(value, dict):
        pair = (value.get("lat", value.get("latitude")), value.get("lon", value.get("longitude")))
    else:
        pair = value
    try:
        lat, lon = (float(pair[0]), float(pair[1]))
    except (TypeError, ValueError, IndexError, KeyError) as exc:
        msg = f"{name!r} is not a latitude/longitude pair: {value!r}"
        raise VenueError(msg) from exc
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        msg = f"{name!r} is not on Earth: {value!r}"
        raise VenueError(msg)
    return (lat, lon)
