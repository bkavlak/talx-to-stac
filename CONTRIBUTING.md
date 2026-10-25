# Contributing

This repository is vibe-coded: an AI assistant wrote most of it under human
direction. Read [ARCHITECTURE.md](ARCHITECTURE.md) before changing a module, and
[CLAUDE.md](CLAUDE.md) for the design rules every change is held to -- they
apply to people and assistants alike.

```sh
uv sync --extra dev --extra youtube
uv run pytest
uv run pre-commit run --all-files
```

## Reviewing recording matches

The most useful contribution needs no code: telling the matcher where it is
wrong. `Recordings` attaches a video to a talk when their titles agree closely
enough, and the only way to know whether "closely enough" is right is for
people to look.

1. Run `uv run python tools/review_matches.py`. The first run fetches every
   schedule and playlist in `examples/foss4g.py` into `build/match-review/`;
   later runs start from that copy. The review page opens in your browser.
2. Work through a queue. *Likely misses* and *Orphan videos* are where the
   matcher most often falls short; *Inexact matches* and *Shared videos* are
   where it may have gone too far. For each case, say which video is the talk's
   recording, or that none is, and tag why the titles differ.
3. Each verdict is written straight to `tools/review/labels.json` as a fact:
   this video is, or is not, this talk's recording. Commit that file and open a
   pull request. Diffs stay readable because the file is sorted and one label is
   one object.

Labels describe the talks and videos, not a version of the matcher, so they
stay true however the matching changes. That is what makes them a test.

## Placing rooms

Every talk is a STAC Item placed at its room, but pretalx does not know where
rooms are. A conference's rooms come from `examples/<conference>.venue.yaml`;
a room the file does not list sits on its `default`, the city centre.

1. Run `uv run python tools/review_venues.py`. It shows one conference's rooms
   on a map, with how many sessions each holds and what pretalx says about it --
   often the building and floor.
2. Select rooms, click where they are (the building search helps), say what is
   there, and place them. Rooms in one building can be placed together. The
   venue file is rewritten as you go.
3. Run `uv run python tools/review_venues.py --check`. It reports how many
   sessions each conference has placed, and flags a room far from its city
   (latitude and longitude swapped, usually) or a file entry no schedule names
   (usually a misspelling, which leaves that room on the city centre).
4. Commit the venue files and open a pull request. `examples/foss4g.py` reads
   them, so the next catalog build moves those talks.

Place a room as precisely as you can tell: the building is enough, the room is
better. Leave a room you cannot find on the city centre rather than guessing.

## Improving the matcher

1. Run `uv run python tools/review_matches.py --score` and note the result. It
   prints every label the matcher disagrees with.
2. Change `src/talx_to_stac/recordings.py`. Before reaching for a new rule, look
   at the titles that fail: every rule in there was found in the data, and
   ARCHITECTURE.md records why each was chosen over the obvious alternative.
3. Add a unit test in `tests/unit/test_recordings.py` for the case, built from
   the real titles.
4. Score again. A change is an improvement when more labels agree and none that
   agreed before stops agreeing. Say both numbers in the pull request.

A label you believe is wrong is worth a pull request of its own, with the
reason, rather than a rule that works around it.
