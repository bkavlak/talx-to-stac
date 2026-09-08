"""Serve a generated STAC catalog in a local STAC Browser.

The app and the catalog are served from one origin -- the app at ``/`` and the
catalog at ``/stac`` -- so no CORS headers and no second server are needed, and
the catalog is served where it was generated rather than copied.

Usage:
    python3 tools/browse.py [--catalog DIR] [--port N]

Needs nothing installed: the standard library only.
"""

from __future__ import annotations

import argparse
import webbrowser
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "examples" / "browser"
MOUNT = "/stac"
ASKED_FOR = "collection.json"
"""The root document the bundled app requests; its catalogUrl is fixed at build time."""

ROOT_NAMES = ("catalog.json", "collection.json")


class Handler(SimpleHTTPRequestHandler):
    """Serves the browser app, with one catalog grafted in under ``/stac``."""

    def __init__(self, *args: Any, catalog: Path, **kwargs: Any) -> None:
        self._catalog = catalog.resolve()
        super().__init__(*args, **kwargs)

    def translate_path(self, path: str) -> str:
        """Route ``/stac/...`` to the catalog and everything else to the app."""
        clean = unquote(path.split("?", 1)[0].split("#", 1)[0])
        if clean != MOUNT and not clean.startswith(f"{MOUNT}/"):
            return super().translate_path(path)
        relative = clean[len(MOUNT) :].lstrip("/")
        if relative == ASKED_FOR:
            # pystac names the root catalog.json or collection.json depending on
            # what it is; the app only ever asks for one of those names.
            relative = root_of(self._catalog).name
        wanted = (self._catalog / relative).resolve()
        # A crafted request can still carry "..", so confine it to the catalog.
        return str(wanted if wanted.is_relative_to(self._catalog) else self._catalog)

    def log_message(self, *args: Any) -> None:
        """Stay quiet; the interesting output is the URL printed once."""


def root_of(catalog: Path) -> Path:
    """The catalog's root document, whether it is a Catalog or a Collection."""
    return next((catalog / name for name in ROOT_NAMES if (catalog / name).exists()), catalog)


def main() -> int:
    """Serve until interrupted."""
    parser = argparse.ArgumentParser(description="Browse a local STAC catalog.")
    parser.add_argument("--catalog", type=Path, default=ROOT / "docs" / "stac")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    catalog = args.catalog.resolve()

    if not (APP / "index.html").exists():
        print(f"No STAC Browser build at {APP}. Run tools/build_browser.sh first.")
        return 1
    if not root_of(catalog).is_file():
        print(f"No catalog at {catalog}. Generate one first, for example:")
        print(
            f"  python -m talx_to_stac https://talks.osgeo.org/foss4g-2026/schedule/ -o {catalog}"
        )
        return 1

    url = f"http://localhost:{args.port}/"
    handler = partial(Handler, catalog=catalog, directory=str(APP))
    with ThreadingHTTPServer(("127.0.0.1", args.port), handler) as server:
        print(f"STAC Browser on {url} showing {catalog}  (Ctrl-C to stop)")
        webbrowser.open(url)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
