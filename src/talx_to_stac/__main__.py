"""Command line entry point: ``python -m talx_to_stac EVENT_URL``.

A deliberately thin shell over :func:`talx_to_stac.to_stac` -- it exists so that
trying a new event costs a shell line rather than a Python file. Every decision
it makes is an argument default, not behaviour of its own.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from pystac import CatalogType

from talx_to_stac import to_stac
from talx_to_stac.recordings import Recordings
from talx_to_stac.schedule import ScheduleError
from talx_to_stac.venue import VenueError


def main(argv: list[str] | None = None) -> int:
    """Write one event's STAC catalog to disk.

    Args:
        argv: Command line arguments, defaulting to ``sys.argv``.

    Returns:
        A process exit status.
    """
    parser = argparse.ArgumentParser(
        prog="talx-to-stac",
        description="Map a pretalx conference schedule to a STAC Collection of talks.",
    )
    parser.add_argument("event_url", help="any URL inside the event, e.g. its schedule page")
    parser.add_argument("-o", "--out", type=Path, default=Path("stac"), help="output directory")
    parser.add_argument("--venue", type=Path, help="YAML or JSON file of room coordinates")
    parser.add_argument(
        "--peertube-playlist",
        metavar="ID_OR_URL",
        help="attach recordings from this video.osgeo.org playlist",
    )
    parser.add_argument(
        "--peertube-channel",
        metavar="HANDLE",
        help="attach recordings from this video.osgeo.org channel; "
        "needs --recordings-event, as a channel spans several years",
    )
    parser.add_argument(
        "--youtube-playlist",
        metavar="ID_OR_URL",
        help="attach recordings from this YouTube playlist (needs yt-dlp)",
    )
    parser.add_argument(
        "--recordings-event",
        metavar="TAG",
        help="consider only videos whose title carries this tag, e.g. 'FOSS4GE 2025'",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")
    event = args.recordings_event
    recordings = []
    if args.peertube_playlist:
        recordings.append(Recordings.peertube_playlist(args.peertube_playlist, event=event))
    if args.peertube_channel:
        recordings.append(Recordings.peertube_channel(args.peertube_channel, event=event))
    if args.youtube_playlist:
        recordings.append(Recordings.youtube(args.youtube_playlist, event=event))

    try:
        collection = to_stac(args.event_url, venue=args.venue, references=recordings)
    except (ScheduleError, VenueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    collection.normalize_and_save(str(args.out), catalog_type=CatalogType.SELF_CONTAINED)
    items = list(collection.get_items())
    recorded = sum(any(k.startswith("recording") for k in item.assets) for item in items)
    print(f"{collection.id}: {len(items)} items ({recorded} with a recording) -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
