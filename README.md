# talx-to-stac

> [!WARNING]
> **This is a vibe-coded repository.** Most of the code, tests and docs were
> written by an AI assistant under human direction, and reviewed only as far
> as the tests and the checks in `pre-commit` reach. It works for the FOSS4G
> catalog it publishes, but read it before you depend on it, and expect rough
> edges. Issues and pull requests are welcome; see [CONTRIBUTING.md](CONTRIBUTING.md).

**[Browse the published catalog](https://browser.moregeo.it/external/https://bkavlak.github.io/talx-to-stac/stac/catalog.json)**
— 2209 talks from eight FOSS4G conferences, at
`https://bkavlak.github.io/talx-to-stac/stac/catalog.json`.

Map a [pretalx](https://pretalx.com) conference schedule to a
[STAC](https://stacspec.org) Collection: one Collection per event, one Item per
scheduled session, placed at the room it happens in and spanning the time it runs.

```python
from talx_to_stac import Recordings, to_stac

collection = to_stac(
    "https://talks.osgeo.org/foss4g-europe-2025/schedule/",
    venue="examples/foss4g-europe-2025.venue.yaml",
    references=[
        Recordings.peertube_channel("foss4geurope", event="FOSS4GE 2025"),
        Recordings.youtube("PLqa06jy1NEM0Ss-CMTP4LrOw0f5aeVHdk", event="FOSS4GE 2025"),
    ],
)
collection.normalize_and_save("./stac")
```

`to_stac` is the whole API. `venue` supplies the coordinates pretalx does not
have; without it the transform still succeeds and logs which rooms are missing.
`references` adds sources of extra URLs — recordings, here — to the offline ones
that always run. A talk gets one `recording` asset per platform that has it.
YouTube listings need the optional extra: `pip install 'talx-to-stac[youtube]'`.

A conference publishes its talks, workshops and academic papers as separate
pretalx events. `to_catalog` groups them:

```python
from talx_to_stac.catalog import Conference, Programme, to_catalog

catalog = to_catalog(
    [
        Conference(
            id="foss4g-2026",
            title="FOSS4G 2026 Hiroshima",
            programmes=[
                Programme("talks", "https://talks.osgeo.org/foss4g-2026/schedule/"),
                Programme("workshops", "https://talks.osgeo.org/foss4g-2026-workshop/schedule/"),
            ],
        ),
    ]
)
```

giving `Catalog -> Collection per conference -> Collection per programme -> Item
per session`. `examples/foss4g.py` builds every FOSS4G conference on
talks.osgeo.org this way: 8 conferences, 17 programmes, 2209 talks. It writes
`docs/`, which GitHub Pages serves. The catalog is self-contained -- every link
inside it is relative -- so it reads the same locally, from Pages, or from any
STAC Browser pointed at its URL.

See [ARCHITECTURE.md](ARCHITECTURE.md) for the design and its reasoning.

## Coverage

How much of each conference the published catalog fills in.

<!-- coverage -->
<!-- /coverage -->

## Review the recording matches

Pretalx does not know where a talk's video ended up, so recordings are matched
to talks by title, and titles on video platforms are truncated, reworded and
decorated with speaker names. To see every decision the matcher makes and say
which are wrong:

```sh
uv sync --extra dev --extra youtube
uv run python tools/review_matches.py          # opens the review page
uv run python tools/review_matches.py --score  # the matcher against every review so far
```

Verdicts land in `tools/review/labels.json`.

Room coordinates are reviewed the same way: `tools/review_venues.py` places each
conference's rooms on a map and writes `examples/<conference>.venue.yaml`, and
`--check` reports coverage and suspicious points.
[CONTRIBUTING.md](CONTRIBUTING.md) says how to turn either into a pull request.

## Try it locally

The browser needs nothing installed -- `tools/browse.py` is standard library only,
and the catalog is already built in `docs/stac`:

```sh
python3 tools/browse.py            # http://localhost:8000
```

That opens the whole FOSS4G catalog. To rebuild it:

```sh
uv sync --extra dev --extra youtube
uv run python examples/foss4g.py
```

To generate another event, install the package and use the CLI:

```sh
uv sync
uv run python -m talx_to_stac https://talks.osgeo.org/foss4g-2026/schedule/ -o /tmp/stac2026
python3 tools/browse.py --catalog /tmp/stac2026
```

```
usage: talx-to-stac [-h] [-o OUT] [--venue VENUE] [--osgeo-channel HANDLE]
                    [--youtube-playlist ID_OR_URL] [--recordings-event TAG]
                    event_url
```

`tools/browse.py` serves a bundled [STAC Browser](https://github.com/radiantearth/stac-browser)
5.0.0 at `/` and the catalog at `/stac`, from one origin, so nothing needs CORS.
`tools/build_browser.sh` rebuilds the bundled app from source.

## Development

```sh
uv sync --extra dev
uv run pytest
uv run pre-commit run --all-files
```
