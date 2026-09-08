#!/usr/bin/env bash
# Rebuild examples/browser/ from source. Needs node and git; takes a few minutes.
# The checked-in build was made exactly this way.
set -euo pipefail

VERSION="v5.0.0"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

git clone --depth 1 --branch "$VERSION" https://github.com/radiantearth/stac-browser.git "$WORK/sb"
cd "$WORK/sb"

# Serve the catalog from the same origin as the app, under /stac.
# An absolute path is required: a relative catalogUrl is re-resolved against
# itself when STAC Browser follows the catalog's own relative links.
python3 - <<'PY'
import pathlib
p = pathlib.Path("config.js"); t = p.read_text()
t = t.replace('catalogUrl: null,', 'catalogUrl: "/stac/collection.json",')
t = t.replace('catalogTitle: null,', 'catalogTitle: "talx-to-stac",')
t = t.replace('historyMode: "history",', 'historyMode: "hash",')
p.write_text(t)
PY

npm install --no-audit --no-fund
npm run build
find dist -name '*.map' -delete

rm -rf "$ROOT/examples/browser"
mkdir -p "$ROOT/examples/browser"
cp -r dist/. "$ROOT/examples/browser/"
echo "Built STAC Browser $VERSION into examples/browser"
