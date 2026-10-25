"""Place each conference room on the map, and check the places already given.

Pretalx knows room names, not where rooms are, so every talk's geometry comes
from a venue file -- ``examples/<conference>.venue.yaml`` -- that a person wrote.
A room the file does not list sits on its ``default``, the city centre. This
tool shows each conference's rooms on a map, with how many sessions each one
holds and what pretalx says about it, and writes a reviewer's placements
straight into that conference's venue file. The file is the record: it is what
``examples/foss4g.py`` reads, so a placement reaches the catalog on its next build.

Usage:
    uv run python tools/review_venues.py            # place rooms in the browser
    uv run python tools/review_venues.py --check    # what is placed, and what looks wrong
    uv run python tools/review_venues.py --refresh  # fetch the schedules again

Schedules are fetched once into ``build/venue-review/`` and reused.
"""

from __future__ import annotations

import argparse
import contextlib
import importlib.util
import json
import math
import re
import webbrowser
from collections import Counter
from dataclasses import dataclass
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx
import yaml

from talx_to_stac.schedule import Schedule, export_url
from talx_to_stac.venue import Venue

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping
    from types import ModuleType

ROOT = Path(__file__).resolve().parent.parent
PAGE = ROOT / "tools" / "venues"
CACHE = ROOT / "build" / "venue-review"
NEARBY_KM = 25.0
"""How far from the city centre a room may be before it is probably a mistake."""

_LINE = re.compile(
    r'^(?P<key>"(?:[^"\\]|\\.)*"|[^#\s][^#]*?):\s*\[[^\]]*\]\s*(?:#\s*(?P<place>.*))?$'
)


@dataclass(frozen=True, slots=True)
class Room:
    """One room of a conference, with what reviewers need to place it."""

    name: str
    sessions: int
    programmes: tuple[str, ...]
    description: str | None
    capacity: int | None


@dataclass(frozen=True, slots=True)
class Conference:
    """One conference: its rooms and where its venue file says they are."""

    id: str
    title: str
    file: Path
    default: tuple[float, float]
    """The city centre, where every room not in the venue file is placed."""
    rooms: tuple[Room, ...]

    def venue(self) -> Venue:
        """The venue as the catalog will see it."""
        return Venue.from_file(self.file)

    def as_json(self) -> dict[str, Any]:
        """The conference as the review page shows it."""
        venue, places = self.venue(), _places(self.file)
        return {
            "id": self.id,
            "title": self.title,
            "file": str(self.file.relative_to(ROOT)),
            "default": list(self.default),
            "rooms": [
                {
                    "name": r.name,
                    "sessions": r.sessions,
                    "programmes": list(r.programmes),
                    "description": r.description,
                    "capacity": r.capacity,
                    "placed": venue.knows(r.name),
                    "point": _latlon(venue, r.name),
                    "place": places.get(_key(r.name), ""),
                }
                for r in self.rooms
            ],
        }

    def place(self, rooms: Iterable[str], point: tuple[float, float] | None, place: str) -> None:
        """Put ``rooms`` at ``point``, or back on the city centre when ``point`` is None."""
        current = _read(self.file)
        for room in rooms:
            current.pop(_key(room), None)
            if point is not None:
                current[_key(room)] = (room, (round(point[0], 5), round(point[1], 5)), place)
        _write(self.file, self.title, self.default, current.values())


def conferences(*, refresh: bool) -> list[Conference]:
    """Every conference of ``examples/foss4g.py``, its schedules cached on disk."""
    found = []
    for conference in _example().CONFERENCES:
        sessions: Counter[str] = Counter()
        programmes: dict[str, list[str]] = {}
        rooms: dict[str, Any] = {}
        for programme in conference.programmes:
            schedule = _schedule(f"{conference.id}-{programme.name}", programme.event_url, refresh)
            for session in schedule.sessions:
                sessions[session.room] += 1
                if programme.name not in programmes.setdefault(session.room, []):
                    programmes[session.room].append(programme.name)
            for room in schedule.rooms:
                rooms.setdefault(room.name, room)
        file = Path(conference.venue)
        found.append(
            Conference(
                id=conference.id,
                title=conference.title,
                file=file,
                default=_default_of(file),
                rooms=tuple(
                    Room(
                        name=name,
                        sessions=count,
                        programmes=tuple(programmes[name]),
                        description=getattr(rooms.get(name), "description", None),
                        capacity=getattr(rooms.get(name), "capacity", None),
                    )
                    for name, count in sessions.most_common()
                ),
            )
        )
    return found


def check(found: Iterable[Conference]) -> int:
    """Print what is placed and what looks wrong; return how many problems there are."""
    problems = 0
    for conference in found:
        venue = conference.venue()
        total = sum(r.sessions for r in conference.rooms)
        placed = [r for r in conference.rooms if venue.knows(r.name)]
        share = sum(r.sessions for r in placed) / total if total else 0.0
        print(
            f"{conference.id}: {len(placed)} of {len(conference.rooms)} rooms placed, "
            f"holding {share:.0%} of {total} sessions"
        )
        for room in placed:
            lat, lon = _latlon(venue, room.name)
            away = _km((lat, lon), conference.default)
            if away > NEARBY_KM:
                swapped = _km((lon, lat), conference.default) <= NEARBY_KM
                hint = "; latitude and longitude look swapped" if swapped else ""
                print(f"  {room.name!r} is {away:,.0f} km from the city centre{hint}")
                problems += 1
        for name, point, _ in _read(conference.file).values():
            alone = Venue.from_mapping({name: point})
            if not any(alone.knows(r.name) for r in conference.rooms):
                print(f"  {name!r} is in {conference.file.name} but in no schedule; misspelt?")
                problems += 1
    return problems


class Handler(SimpleHTTPRequestHandler):
    """Serves the page and the conferences, and writes placements to venue files."""

    def __init__(self, *args: Any, found: Mapping[str, Conference], **kwargs: Any) -> None:
        self._found = found
        super().__init__(*args, directory=str(PAGE), **kwargs)

    def do_GET(self) -> None:
        """Serve the conferences fresh from their files, and the page from ``tools/venues``."""
        if self.path.split("?", 1)[0] == "/conferences.json":
            self._send([c.as_json() for c in self._found.values()])
        else:
            super().do_GET()

    def do_POST(self) -> None:
        """Place rooms: ``{"conference", "rooms", "point": [lat, lon] | null, "place"}``."""
        change = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        conference = self._found.get(change.get("conference", ""))
        if self.path != "/place" or conference is None:
            self.send_error(404)
            return
        point = change.get("point")
        conference.place(
            change["rooms"], (float(point[0]), float(point[1])) if point else None, change["place"]
        )
        self._send(conference.as_json())

    def _send(self, payload: Any) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: Any) -> None:
        """Stay quiet; the interesting output is the URL printed once."""


def main() -> None:
    """Serve the placing page, or check the venue files."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--check", action="store_true", help="check the venue files and exit")
    parser.add_argument("--refresh", action="store_true", help="fetch the schedules again")
    parser.add_argument("--port", type=int, default=8002)
    args = parser.parse_args()

    found = conferences(refresh=args.refresh)
    if args.check:
        raise SystemExit(1 if check(found) else 0)

    handler = partial(Handler, found={c.id: c for c in found})
    server = ThreadingHTTPServer(("127.0.0.1", args.port), handler)
    url = f"http://127.0.0.1:{args.port}/"
    print(f"Placing rooms at {url} -- placements go to examples/*.venue.yaml. Ctrl-C to stop.")
    webbrowser.open(url)
    with contextlib.suppress(KeyboardInterrupt):
        server.serve_forever()


def _schedule(ident: str, event_url: str, refresh: bool) -> Schedule:
    cached = CACHE / f"{ident}.json"
    if refresh or not cached.exists():
        print(f"fetching {event_url}", flush=True)
        response = httpx.get(export_url(event_url), follow_redirects=True, timeout=60)
        cached.parent.mkdir(parents=True, exist_ok=True)
        cached.write_text(response.raise_for_status().text, encoding="utf-8")
    return Schedule.from_payload(json.loads(cached.read_text(encoding="utf-8")))


def _example() -> ModuleType:
    """The conference list of ``examples/foss4g.py``, which is not a package."""
    spec = importlib.util.spec_from_file_location("foss4g", ROOT / "examples" / "foss4g.py")
    if spec is None or spec.loader is None:  # pragma: no cover - the file ships with the repo
        raise SystemExit("examples/foss4g.py is missing")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


Entry = tuple[str, tuple[float, float], str]
"""A room as its venue file states it: name, latitude/longitude, and a place note."""


def _read(file: Path) -> dict[str, Entry]:
    """The rooms a venue file places, by matching key, keeping each line's comment."""
    loaded = yaml.safe_load(file.read_text(encoding="utf-8")) or {}
    places = _places(file)
    return {
        _key(name): (name, (float(value[0]), float(value[1])), places.get(_key(name), ""))
        for name, value in loaded.items()
        if name != "default"
    }


def _places(file: Path) -> dict[str, str]:
    """The comment on each room's line, which says what the place is."""
    found = {}
    for line in file.read_text(encoding="utf-8").splitlines():
        if match := _LINE.match(line.strip()):
            raw = match.group("key").strip()
            name = json.loads(raw) if raw.startswith('"') else raw
            found[_key(name)] = (match.group("place") or "").strip()
    return found


def _default_of(file: Path) -> tuple[float, float]:
    """The city centre a venue file places unlisted rooms at."""
    value = yaml.safe_load(file.read_text(encoding="utf-8"))["default"]
    return (float(value[0]), float(value[1]))


def _write(file: Path, title: str, default: tuple[float, float], rooms: Iterable[Entry]) -> None:
    """Write a venue file in the one layout this tool and people both read easily."""
    lines = [
        f"# Room coordinates for {title}, kept with tools/review_venues.py.",
        "# Latitude then longitude, placed by reviewers from a map: not surveyed.",
        f"default: [{default[0]}, {default[1]}]  # city centre, for rooms not listed",
    ]
    for name, (lat, lon), place in sorted(rooms, key=lambda e: e[0].casefold()):
        note = f"  # {' '.join(place.split())}" if place.strip() else ""
        lines.append(f"{_yaml_key(name)}: [{lat}, {lon}]{note}")
    if len(lines) > 3:
        lines.insert(3, "")
    file.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _yaml_key(name: str) -> str:
    """The room name bare when YAML reads it back unchanged, else quoted."""
    try:
        plain = yaml.safe_load(f"{name}: 0") == {name: 0} and "#" not in name
    except yaml.YAMLError:
        plain = False
    return name if plain else json.dumps(name, ensure_ascii=False)


def _key(name: str) -> str:
    """How ``Venue`` compares room names: case and spacing do not matter."""
    return " ".join(str(name).split()).casefold()


def _latlon(venue: Venue, room: str) -> tuple[float, float]:
    lon, lat = venue.point_for(room)["coordinates"]
    return (lat, lon)


def _km(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Great-circle distance between two latitude/longitude pairs."""
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    h = math.sin((lat2 - lat1) / 2) ** 2 + (
        math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    )
    return 6371.0 * 2 * math.asin(math.sqrt(min(1.0, h)))


if __name__ == "__main__":
    main()
