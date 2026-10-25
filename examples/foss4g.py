"""Build one STAC Catalog of every FOSS4G conference published on talks.osgeo.org.

    Catalog -> Collection per conference -> Collection per programme -> Item per session

The pretalx slugs below were discovered, not guessed: the workshop suffix is
``-workshop`` for some conferences and ``-workshops`` for others, and the
academic programme is ``-academic-track`` where it exists at all.

Room coordinates come from ``<conference>.venue.yaml`` beside this file where
one exists, and are the city centre otherwise. They place a conference on the
map; they are not surveyed.

Output goes to ``docs/stac``, which GitHub Pages publishes, and what it covers to
the README's coverage section. The catalog is
self-contained -- every link inside it is relative -- so it reads correctly from
a local server, from Pages, or from anywhere else it is copied.
"""

import html
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import pystac
from pystac import CatalogType

from talx_to_stac import Recordings
from talx_to_stac.catalog import Conference, Programme, to_catalog
from talx_to_stac.venue import Venue

HERE = Path(__file__).parent
DOCS = HERE.parent / "docs"
PUBLISHED = DOCS / "stac"
README = HERE.parent / "README.md"
PLATFORMS = {"peertube": "PeerTube", "youtube": "YouTube"}
PRETALX = "https://talks.osgeo.org"
CATALOG_URL = "https://bkavlak.github.io/talx-to-stac/stac/catalog.json"
BROWSERS = {
    "browser.moregeo.it": f"https://browser.moregeo.it/external/{CATALOG_URL}",
    "STAC Browser": f"https://radiantearth.github.io/stac-browser/#/external/{CATALOG_URL}",
}


def event(slug: str) -> str:
    """The schedule URL of a pretalx event."""
    return f"{PRETALX}/{slug}/schedule/"


def venue_file(conference: str) -> Path:
    """Where a conference's room coordinates are kept, once someone has placed them."""
    return HERE / f"{conference}.venue.yaml"


def venue(conference: str, latitude: float, longitude: float) -> Venue:
    """The conference's venue file if there is one, else every room at the city centre.

    ``tools/review_venues.py`` writes these files; see CONTRIBUTING.md.
    """
    path = venue_file(conference)
    if path.exists():
        return Venue.from_file(path)
    return Venue.from_mapping({}, default=(latitude, longitude))


def videos(peertube: str = "", youtube: str = "") -> list[Recordings]:
    """The recording playlists for a programme, in the order they should be preferred."""
    sources = []
    if peertube:
        sources.append(Recordings.peertube_playlist(peertube))
    if youtube:
        sources.append(Recordings.youtube(youtube))
    return sources


CONFERENCES = [
    Conference(
        id="foss4g-2022",
        title="FOSS4G 2022 Firenze",
        venue=venue("foss4g-2022", 43.7696, 11.2558),
        programmes=[
            Programme(
                "talks",
                event("foss4g-2022"),
                videos("5mQAYM9GtE98UiKkxbyfqA", "PLqa06jy1NEM0ec9WH0cV4eDoSyHhLyQ7d"),
            ),
            Programme("workshops", event("foss4g-2022-workshops")),
            Programme("academic", event("foss4g-2022-academic-track")),
        ],
    ),
    Conference(
        id="foss4g-2023",
        title="FOSS4G 2023 Prizren",
        venue=venue("foss4g-2023", 42.2139, 20.7397),
        programmes=[
            Programme(
                "talks",
                event("foss4g-2023"),
                videos("38UXSRCXh8e3asxsr5Fmhk", "PLqa06jy1NEM2Kna9Gt_LDKZHv1dl4xUoZ"),
            ),
            Programme("workshops", event("foss4g-2023-workshop")),
        ],
    ),
    Conference(
        id="foss4g-europe-2024",
        title="FOSS4G Europe 2024 Tartu",
        venue=venue("foss4g-europe-2024", 58.3780, 26.7290),
        programmes=[
            Programme(
                "talks",
                event("foss4g-europe-2024"),
                videos("hTeW9hRWZ97CmrtF3hVswU", "PLqa06jy1NEM0QkCSb94zkEFvzRAMgaFY5"),
            ),
            Programme("workshops", event("foss4g-europe-2024-workshops")),
        ],
    ),
    Conference(
        id="foss4g-2024",
        title="FOSS4G 2024 Belem",
        venue=venue("foss4g-2024", -1.4558, -48.5039),
        programmes=[
            Programme(
                "talks",
                event("foss4g-2024"),
                videos("cEYhRwnYtD4cTvDrikWzn5", "PLqa06jy1NEM3LnWyvjUiA0FmGGrfUrnp9"),
            ),
            Programme("workshops", event("foss4g-2024-workshop")),
            Programme("academic", event("foss4g-2024-academic-track")),
        ],
    ),
    Conference(
        id="foss4g-europe-2025",
        title="FOSS4G Europe 2025 Mostar",
        venue=venue("foss4g-europe-2025", 43.3416, 17.8094),
        programmes=[
            Programme(
                "talks",
                event("foss4g-europe-2025"),
                videos("9sWfVNpmAxzTf46xU42Vmj", "PLqa06jy1NEM0Ss-CMTP4LrOw0f5aeVHdk"),
            ),
            Programme("workshops", event("foss4g-europe-2025-workshops")),
        ],
    ),
    Conference(
        id="foss4g-2025",
        title="FOSS4G 2025 Auckland",
        venue=venue("foss4g-2025", -36.8485, 174.7633),
        description=(
            "FOSS4G 2025 Auckland: one pretalx event for the whole programme. "
            "Its workshops and academic papers are Items here too, told apart "
            "by talk:type rather than by a collection of their own."
        ),
        programmes=[
            Programme(
                "talks",
                event("foss4g-2025"),
                videos(youtube="PLlZzWSPAR5GYPAGSgs1Z6ydhoVgL7CAHd"),
            ),
        ],
    ),
    Conference(
        id="foss4g-europe-2026",
        title="FOSS4G Europe 2026 Timisoara",
        venue=venue("foss4g-europe-2026", 45.7489, 21.2087),
        programmes=[
            Programme("talks", event("foss4g-europe-2026")),
            Programme("workshops", event("foss4g-europe-2026-workshops")),
        ],
    ),
    Conference(
        id="foss4g-2026",
        title="FOSS4G 2026 Hiroshima",
        venue=venue("foss4g-2026", 34.3853, 132.4553),
        programmes=[
            Programme("talks", event("foss4g-2026")),
            Programme("workshops", event("foss4g-2026-workshop")),
        ],
    ),
]


@dataclass(frozen=True, slots=True)
class ProgrammeCoverage:
    """How much of one programme the catalog could fill in."""

    name: str
    sessions: int
    filmed: int
    """Sessions with at least one recording."""
    videos: dict[str, tuple[int, int]]
    """Per platform: videos attached to a session, and videos the platform lists."""


@dataclass(frozen=True, slots=True)
class ConferenceCoverage:
    """How much of one conference the catalog could fill in."""

    title: str
    rooms: int
    placed: int
    """Rooms the venue file places; the others sit on the city centre."""
    sessions: int
    sessions_placed: int
    programmes: list[ProgrammeCoverage]


def coverage(catalog: pystac.Catalog) -> list[ConferenceCoverage]:
    """What the built catalog holds, measured against what its sources offered."""
    report = []
    for conference in CONFERENCES:
        venue = conference.venue
        knows = venue.knows if isinstance(venue, Venue) else lambda room: False
        built = _child(catalog, conference.id)
        rooms: Counter[str] = Counter()
        programmes = []
        for programme in conference.programmes:
            child = _child(built, f"{conference.id}-{programme.name}")
            items = list(child.get_items())
            rooms.update(str(i.properties.get("talk:room")) for i in items)
            attached = {
                a.href for i in items for k, a in i.assets.items() if k.startswith("recording")
            }
            videos = {}
            for source in programme.recordings:
                if isinstance(source, Recordings):
                    listed = {v.url for v in source.videos}
                    videos[source.source] = (len(listed & attached), len(listed))
            filmed = sum(any(k.startswith("recording") for k in i.assets) for i in items)
            programmes.append(ProgrammeCoverage(programme.name, len(items), filmed, videos))
        placed = [room for room in rooms if knows(room)]
        report.append(
            ConferenceCoverage(
                title=conference.title,
                rooms=len(rooms),
                placed=len(placed),
                sessions=sum(rooms.values()),
                sessions_placed=sum(rooms[r] for r in placed),
                programmes=programmes,
            )
        )
    return report


def _child(parent: pystac.Catalog, ident: str) -> pystac.Catalog:
    child = parent.get_child(ident)
    if child is None:
        raise LookupError(f"{ident} is missing from the catalog")
    return child


def write_coverage(report: list[ConferenceCoverage], path: Path) -> None:
    """Rewrite the README's coverage section, between its two markers, from the report."""
    platforms = sorted({p for c in report for g in c.programmes for p in g.videos})
    lines = [
        "Written by `examples/foss4g.py` from the catalog it publishes; edits here are lost.",
        "",
        "**Recordings.** Sessions with a recording, and how many of each platform's videos",
        "were matched to a session. The rest are reviewable with `tools/review_matches.py`.",
        "",
        "| Programme | Sessions | Filmed | "
        + " | ".join(f"{PLATFORMS.get(p, p)} matched" for p in platforms)
        + " |",
        "| --- | ---: | ---: | " + " | ".join("---:" for _ in platforms) + " |",
    ]
    for c in report:
        for g in c.programmes:
            if not g.videos:
                continue
            cells = [
                f"{g.videos[p][0]} of {g.videos[p][1]}" if p in g.videos else "-" for p in platforms
            ]
            row = [f"{c.title}, {g.name}", str(g.sessions), str(g.filmed), *cells]
            lines.append("| " + " | ".join(row) + " |")
    lines += [
        "",
        "**Locations.** Rooms placed by a reviewer, and the share of sessions held in them.",
        "Every other room sits on its city centre; `tools/review_venues.py` places them.",
        "",
        "| Conference | Rooms placed | Sessions placed |",
        "| --- | ---: | ---: |",
    ]
    for c in report:
        share = c.sessions_placed / c.sessions if c.sessions else 0.0
        lines.append(f"| {c.title} | {c.placed} of {c.rooms} | {share:.0%} of {c.sessions} |")
    text = path.read_text(encoding="utf-8")
    section = _COVERAGE.sub(
        lambda m: f"{m.group(1)}\n" + "\n".join(lines) + f"\n{m.group(2)}", text
    )
    path.write_text(section, encoding="utf-8")


def write_index(report: list[ConferenceCoverage], path: Path) -> None:
    """Write the landing page GitHub Pages serves, with counts taken from the catalog."""
    total = sum(g.sessions for c in report for g in c.programmes)
    body = "\n".join(
        "<tr><th>{}</th><td>{}</td></tr>".format(
            html.escape(c.title),
            " ".join(
                f'<span class="p">{html.escape(g.name.capitalize())} <b>{g.sessions}</b>'
                + (f" <i>{g.filmed} filmed</i>" if g.filmed else "")
                + "</span>"
                for g in c.programmes
            ),
        )
        for c in report
    )
    links = " ".join(
        f'<a class="b" href="{url}">Open in {html.escape(n)}</a>' for n, url in BROWSERS.items()
    )
    path.write_text(_PAGE.format(total=total, catalog=CATALOG_URL, links=links, rows=body), "utf-8")


_COVERAGE = re.compile(r"(<!-- coverage -->)\n(?:.*?\n)?(<!-- /coverage -->)", re.S)

_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>FOSS4G talks as STAC</title>
<style>
:root {{ color-scheme: light dark; --fg:#16211c; --bg:#fbfbf9; --mut:#5d6b64;
        --line:#dfe3e0; --acc:#2f7d4f; }}
@media (prefers-color-scheme: dark) {{
  :root {{ --fg:#e6ece8; --bg:#121714; --mut:#9aa8a0; --line:#26302b; --acc:#6fbf8b; }} }}
* {{ box-sizing:border-box }}
body {{ margin:0; padding:3rem 1.25rem 4rem; background:var(--bg); color:var(--fg);
  font:16px/1.6 ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif }}
main {{ max-width:52rem; margin:0 auto }}
h1 {{ font-size:1.9rem; margin:0 0 .4rem; letter-spacing:-.02em }}
p.lead {{ color:var(--mut); margin:0 0 2rem; max-width:40rem }}
code.url {{ display:block; padding:.7rem .9rem; border:1px solid var(--line);
  border-radius:.5rem; font-size:.85rem; overflow-x:auto; white-space:nowrap; margin-bottom:1rem }}
a.b {{ display:inline-block; padding:.5rem .9rem; margin:0 .4rem .5rem 0; border-radius:.5rem;
  background:var(--acc); color:var(--bg); text-decoration:none; font-weight:600; font-size:.9rem }}
a.b:hover {{ filter:brightness(1.08) }}
table {{ width:100%; border-collapse:collapse; margin-top:2.5rem }}
th, td {{ text-align:left; padding:.7rem .4rem; border-top:1px solid var(--line);
  vertical-align:top }}
th {{ font-weight:600; white-space:nowrap; padding-right:1.5rem }}
span.p {{ display:inline-block; margin-right:1.1rem; color:var(--mut); font-size:.9rem }}
span.p b {{ color:var(--fg); font-variant-numeric:tabular-nums }}
span.p i {{ font-style:normal; color:var(--acc) }}
footer {{ margin-top:3rem; padding-top:1.2rem; border-top:1px solid var(--line);
  color:var(--mut); font-size:.85rem }}
footer a {{ color:inherit }}
</style></head><body><main>
<h1>FOSS4G talks as STAC</h1>
<p class="lead">{total} conference sessions from eight FOSS4G conferences, each a STAC Item
placed at its room and spanning its slot, with slides and recordings as assets. Built from
the pretalx schedules on talks.osgeo.org.</p>
<code class="url">{catalog}</code>
{links}
<table>{rows}</table>
<footer>Generated by <a href="https://github.com/bkavlak/talx-to-stac">talx-to-stac</a>
from <a href="https://talks.osgeo.org">talks.osgeo.org</a>, with recordings from
video.osgeo.org and YouTube.</footer>
</main></body></html>
"""


def main() -> None:
    """Build the catalog, write the landing page, and report what landed in it."""
    catalog = to_catalog(
        CONFERENCES,
        catalog_id="foss4g",
        title="FOSS4G conferences",
        description="Talks, workshops and academic papers from FOSS4G conferences.",
    )
    catalog.normalize_and_save(str(PUBLISHED), catalog_type=CatalogType.SELF_CONTAINED)

    report = coverage(catalog)
    write_index(report, DOCS / "index.html")
    write_coverage(report, README)
    for c in report:
        print(f"{c.title}: {c.placed} of {c.rooms} rooms placed")
        for g in c.programmes:
            print(f"  {g.name:12} {g.sessions:4d} items  {g.filmed:4d} recorded  {g.videos}")


if __name__ == "__main__":
    main()
