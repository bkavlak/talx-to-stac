# How Laya helped match talks to recordings

Pretalx knows neither which video is a talk's recording nor where its room is.
Recordings are matched by title, and titles are shortened, abbreviated,
reworded, or have the speaker's name added. A matcher that only compares titles
either misses real recordings or pairs look-alikes such as
`pygeoapi project status` and `pygeometa project status`.

So the matcher is held to facts people have checked. Two review dashboards
collect those facts ([CONTRIBUTING.md](CONTRIBUTING.md) explains how to use
both):

| Dashboard | What it checks | Where answers go |
| --- | --- | --- |
| `tools/review_matches.py` | which video, if any, is each talk's recording | `tools/review/labels.json` |
| `tools/review_venues.py` | where each room is on the map | `examples/<conference>.venue.yaml` |

## Where Laya came in

[Laya](https://github.com/NandhaKishorM/laya) is an open-source (Apache-2.0)
decision engine. It answers typed questions about text in one forward pass,
without generating text. "Is this video this talk's recording?" is a question
of exactly that kind.

1. **Matcher:** proposes a video for each talk, or none.
2. **Laya:** gives its own matching results for the same talks and videos. That
   brings up the cases where the two disagree and the recordings the matcher
   missed.
3. **People:** settle each case in the match review dashboard. Nothing becomes
   a label until a person confirms it.
4. **Matcher:** is scored against the labels with
   `uv run python tools/review_matches.py --score`. A change is an improvement
   only when more labels agree and none that agreed before stops agreeing.

Laya is used during review only. The catalog build never calls it, so rebuilding
the catalog needs no model.

## What came out of it

- 144 reviewed labels in `tools/review/labels.json`.
- On the 140 cases evaluated in [ARCHITECTURE.md](ARCHITECTURE.md), the matcher
  found 115 of 117 confirmed recordings, and every rejected pairing stayed
  rejected.
- Videos that no talk claimed fell from 316 to 131.

Laya is a separate project by its own authors. This page only describes how
this project used it.
