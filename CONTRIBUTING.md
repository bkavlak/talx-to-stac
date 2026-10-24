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
