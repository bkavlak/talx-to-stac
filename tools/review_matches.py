"""Review how recordings were matched to talks, and score the matcher against the reviews.

Matching a talk to its recording is the one part of this library that guesses,
and the only way to know whether it guesses well is for people to look. This
tool shows every decision the matcher makes for the conferences in
``examples/foss4g.py`` -- each talk with the video it got or the closest ones it
did not, each video no talk claimed -- and records what a reviewer says about
them in ``tools/review/labels.json``. Those labels are facts ("this video is,
or is not, this talk's recording"), not opinions about one version of the
matcher, so they stay valid however the matching changes, and ``--score`` turns
them into the test of any change to it.

Usage:
    uv run python tools/review_matches.py            # review in the browser
    uv run python tools/review_matches.py --score    # how the matcher does on the labels
    uv run python tools/review_matches.py --refresh  # fetch schedules and playlists again

Schedules and playlists are fetched once into ``build/match-review/`` and reused,
so a review session and a score both run offline after the first time. YouTube
listings need the ``youtube`` extra.
"""

from __future__ import annotations

import argparse
import contextlib
import difflib
import importlib.util
import json
import re
import unicodedata
import webbrowser
from dataclasses import dataclass
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypeVar

import httpx

from talx_to_stac.recordings import Recordings, Video
from talx_to_stac.schedule import Schedule, export_url

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Iterator, Sequence
    from types import ModuleType

ROOT = Path(__file__).resolve().parent.parent
PAGE = ROOT / "tools" / "review"
LABELS = PAGE / "labels.json"
CACHE = ROOT / "build" / "match-review"
CANDIDATES = 3
T = TypeVar("T")
NEAR = 0.6
"""Similarity at which an unclaimed video is worth showing as a likely miss."""


@dataclass(frozen=True, slots=True)
class Programme:
    """One programme with recordings, as captured for review."""

    id: str
    schedule: Schedule
    playlists: dict[str, tuple[Video, ...]]
    """Every video each platform holds for this programme, by platform."""


@dataclass(frozen=True, slots=True)
class _Listed:
    """A video catalogue already read, so matching runs offline."""

    source: str
    listed: tuple[Video, ...]

    def videos(self) -> Iterable[Video]:
        return self.listed


def programmes(*, refresh: bool) -> list[Programme]:
    """Every programme of ``examples/foss4g.py`` that has recordings, cached on disk."""
    found = []
    for conference in _example().CONFERENCES:
        for programme in conference.programmes:
            if not programme.references:
                continue
            ident = f"{conference.id}-{programme.name}"
            cached = CACHE / f"{ident}.json"
            if refresh or not cached.exists():
                _capture(cached, programme.event_url, programme.references)
            raw = json.loads(cached.read_text(encoding="utf-8"))
            found.append(
                Programme(
                    id=ident,
                    schedule=Schedule.from_payload(raw["schedule"]),
                    playlists={
                        source: tuple(Video(**v) for v in videos)
                        for source, videos in raw["playlists"].items()
                    },
                )
            )
    return found


def decisions(programme: Programme) -> dict[str, dict[str, list[str]]]:
    """What the matcher attaches to each session, by platform then session code."""
    attached: dict[str, dict[str, list[str]]] = {}
    for source, videos in programme.playlists.items():
        recordings = Recordings(_Listed(source, videos))
        attached[source] = {
            s.code: [r.url for r in recordings.references_for(s, programme.schedule)]
            for s in programme.schedule.sessions
        }
    return attached


def cases(programme: Programme) -> Iterator[dict[str, Any]]:
    """Every decision worth a reviewer's look, closest alternatives included."""
    sessions = programme.schedule.sessions
    for source, attached in decisions(programme).items():
        videos = programme.playlists[source]
        by_url = {v.url: v for v in videos}
        claimed: dict[str, list[str]] = {}
        for code, urls in attached.items():
            for url in urls:
                claimed.setdefault(url, []).append(code)
        base = {"programme": programme.id, "platform": source}
        for s in sessions:
            talk = {
                "code": s.code,
                "title": s.title,
                "url": s.url,
                "type": s.type,
                "track": s.track,
                "speakers": [p.name for p in s.persons],
                "do_not_record": s.do_not_record,
            }
            urls = attached[s.code]
            if urls:
                shared = any(len(claimed[u]) > 1 for u in urls)
                exact = all(_similarity(s.title, by_url[u].title) == 1 for u in urls)
                kind = "shared-video" if shared else "matched-exact" if exact else "matched"
                shown = [by_url[u] for u in urls]
            else:
                shown = _closest(s.title, videos, key=lambda v: v.title)
                top = shown[0] if shown else None
                near = top and top.url not in claimed and _similarity(s.title, top.title) >= NEAR
                kind = "near-miss" if near else "unmatched"
            yield {
                **base,
                "kind": kind,
                "session": talk,
                "candidates": [
                    {
                        "title": v.title,
                        "url": v.url,
                        "score": round(_similarity(s.title, v.title), 3),
                        "attached": v.url in urls,
                        "claimed_by": claimed.get(v.url, []),
                    }
                    for v in shown
                ],
            }
        for video in videos:
            if video.url in claimed:
                continue
            nearest = _closest(video.title, sessions, key=lambda s: s.title)
            yield {
                **base,
                "kind": "orphan-video",
                "video": {"title": video.title, "url": video.url},
                "candidates": [
                    {
                        "code": s.code,
                        "title": s.title,
                        "url": s.url,
                        "score": round(_similarity(s.title, video.title), 3),
                        "matched": bool(attached[s.code]),
                    }
                    for s in nearest
                ],
            }


def score(found: Sequence[Programme], labels: Sequence[dict[str, Any]]) -> int:
    """Print how the matcher does against the labels; return how many it gets wrong."""
    attached = {p.id: decisions(p) for p in found}
    right, missed, wrong = 0, [], []
    for label in labels:
        got = attached.get(label["programme"], {}).get(label["platform"], {})
        has = label["video"] in got.get(label["session"], [])
        if has == label["same"]:
            right += 1
        elif label["same"]:
            missed.append(label)
        else:
            wrong.append(label)
    print(f"{len(labels)} labels: {right} agree, {len(missed)} missed, {len(wrong)} wrong")
    for heading, group in (("Missed", missed), ("Wrong", wrong)):
        for label in group:
            talk, video = label["session_title"], label["video_title"]
            print(f"  {heading} ({label['platform']}): {talk!r} <- {video!r}")
    return len(missed) + len(wrong)


class Handler(SimpleHTTPRequestHandler):
    """Serves the review page, its cases, and reads and writes the labels."""

    def __init__(self, *args: Any, cases: bytes, **kwargs: Any) -> None:
        self._cases = cases
        super().__init__(*args, directory=str(PAGE), **kwargs)

    def do_GET(self) -> None:
        """Serve the cases from memory and everything else from ``tools/review``."""
        if self.path.split("?", 1)[0] == "/cases.json":
            self._send(self._cases)
        else:
            super().do_GET()

    def do_POST(self) -> None:
        """Replace one case's labels: ``{"remove": [keys], "add": [labels]}``."""
        if self.path != "/labels":
            self.send_error(404)
            return
        change = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        current = {_key(x): x for x in _labels()}
        for key in change.get("remove", []):
            current.pop(tuple(key), None)
        for label in change.get("add", []):
            current[_key(label)] = label
        LABELS.write_text(
            json.dumps(sorted(current.values(), key=_key), indent=1, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        self._send(b"{}")

    def _send(self, body: bytes) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: Any) -> None:
        """Stay quiet; the interesting output is the URL printed once."""


def main() -> None:
    """Build the cases, then serve the review page or print the score."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--score", action="store_true", help="score the matcher and exit")
    parser.add_argument("--refresh", action="store_true", help="fetch everything again")
    parser.add_argument("--port", type=int, default=8001)
    args = parser.parse_args()

    found = programmes(refresh=args.refresh)
    if args.score:
        raise SystemExit(1 if score(found, _labels()) else 0)

    print("working out every decision the matcher makes...", flush=True)
    body = json.dumps([c for p in found for c in cases(p)], ensure_ascii=False).encode()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), partial(Handler, cases=body))
    url = f"http://127.0.0.1:{args.port}/"
    print(
        f"Reviewing at {url} -- verdicts go to {LABELS.relative_to(ROOT)}. Ctrl-C to stop.",
        flush=True,
    )
    webbrowser.open(url)
    with contextlib.suppress(KeyboardInterrupt):
        server.serve_forever()


def _capture(path: Path, event_url: str, references: Sequence[Any]) -> None:
    """Fetch one programme's schedule and every video its sources list."""
    print(f"fetching {event_url}", flush=True)
    schedule = httpx.get(export_url(event_url), follow_redirects=True, timeout=60)
    playlists = {
        r.source: [{"title": v.title, "url": v.url} for v in r.videos]
        for r in references
        if isinstance(r, Recordings)
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"schedule": schedule.raise_for_status().json(), "playlists": playlists}
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _example() -> ModuleType:
    """The conference list of ``examples/foss4g.py``, which is not a package."""
    spec = importlib.util.spec_from_file_location("foss4g", ROOT / "examples" / "foss4g.py")
    if spec is None or spec.loader is None:  # pragma: no cover - the file ships with the repo
        raise SystemExit("examples/foss4g.py is missing")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _labels() -> list[dict[str, Any]]:
    if not LABELS.exists():
        return []
    labels: list[dict[str, Any]] = json.loads(LABELS.read_text(encoding="utf-8"))
    return labels


def _key(label: dict[str, Any]) -> tuple[str, str, str, str]:
    return (label["programme"], label["platform"], label["session"], label["video"])


def _closest(title: str, among: Iterable[T], *, key: Callable[[T], str]) -> list[T]:
    ranked = sorted(among, key=lambda x: -_similarity(title, key(x)))
    return ranked[:CANDIDATES]


def _similarity(talk: str, video: str) -> float:
    """How alike two titles read, for ranking alternatives -- not the matcher's rule."""
    a, b = _words(talk), _words(video.split("|", 1)[-1])
    return difflib.SequenceMatcher(None, a, b, autojunk=False).ratio()


def _words(text: str) -> str:
    folded = unicodedata.normalize("NFKD", text.replace("&", " and "))
    plain = "".join(c for c in folded if not unicodedata.combining(c)).lower()
    return " ".join(re.sub(r"[^0-9a-z]+", " ", plain).split())


if __name__ == "__main__":
    main()
