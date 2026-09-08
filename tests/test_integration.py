"""The one integration test: a real schedule, all the way to a valid STAC Collection."""

from __future__ import annotations

import pytest

from talx_to_stac import Recordings, Schedule, to_stac
from talx_to_stac.recordings import Video
from talx_to_stac.references import (
    AbstractReferences,
    BiographyReferences,
    SubmissionReferences,
    combine,
)
from talx_to_stac.stac import build_collection
from talx_to_stac.venue import Venue
from tests.conftest import stub_client

EVENT = "https://talks.osgeo.org/foss4g-europe-2025/schedule/"
PLAYLIST = "PLqa06jy1NEM0Ss-CMTP4LrOw0f5aeVHdk"
VENUE = {"KOS": [43.3436, 17.8117], "SA01": [43.3389, 17.8064]}


class FakePlaylist:
    """The same titles YouTube carries, without the network."""

    source = "youtube"

    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def videos(self) -> list[Video]:
        return [
            Video(title=v["name"], url=f"https://www.youtube.com/watch?v={v['shortUUID']}")
            for v in self._payload["data"]
        ]


@pytest.fixture
def collection(schedule_payload, video_payload):
    """FOSS4G Europe 2025, transformed offline from captured responses."""
    client = stub_client({"video-channels": video_payload})
    return build_collection(
        Schedule.from_payload(schedule_payload),
        Venue.from_mapping(VENUE, default=[43.3416, 17.8094]),
        combine(
            SubmissionReferences(),
            AbstractReferences(),
            BiographyReferences(),
            Recordings.peertube_channel("foss4geurope", event="FOSS4GE 2025", client=client),
            Recordings(FakePlaylist(video_payload), event="FOSS4GE 2025"),
        ),
    )


def test_the_collection_is_valid_stac(collection, tmp_path):
    collection.normalize_hrefs(str(tmp_path))
    assert collection.validate_all() == len(list(collection.get_items()))


def test_the_whole_schedule_arrives(collection):
    items = list(collection.get_items())
    assert collection.id == "foss4g-europe-2025"
    assert len(items) == 153
    assert len({item.id for item in items}) == 153


def test_every_item_is_placed_and_timed(collection):
    for item in collection.get_items():
        assert item.geometry["type"] == "Point"
        assert item.datetime is not None
        assert item.properties["start_datetime"] <= item.properties["end_datetime"]


def test_a_talk_reaches_its_slides_and_both_recordings(collection):
    opening = collection.get_item("YLEXT7")
    assert opening.assets["slides"].media_type == "application/pdf"
    assert opening.assets["recording-peertube"].href.startswith("https://video.osgeo.org/")
    assert opening.assets["recording-youtube"].href.startswith("https://www.youtube.com/")
    for platform in ("peertube", "youtube"):
        assert opening.assets[f"recording-{platform}"].roles == ["data", "video", platform]


def test_dynamic_pages_are_links_rather_than_assets(collection):
    opening = collection.get_item("YLEXT7")
    related = {link.title: link.href for link in opening.links if link.rel == "related"}
    assert related["Feedback"].endswith("/feedback/")
    assert not any("feedback" in key for key in opening.assets)


def test_recordings_and_mentions_reach_the_whole_catalog(collection):
    items = list(collection.get_items())
    assert sum(any(k.startswith("recording") for k in item.assets) for item in items) == 136
    assert sum(len([lk for lk in item.links if lk.rel == "related"]) for item in items) > 200

    # One session was filmed five times; all five recordings belong to it.
    unscheduled = next(i for i in items if i.properties["title"] == "Unscheduled talks")
    assert len([k for k in unscheduled.assets if k.startswith("recording")]) == 10
    assert "recording-peertube-2" in unscheduled.assets


@pytest.mark.network
def test_the_live_event_still_transforms():
    collection = to_stac(
        EVENT,
        venue=VENUE,
        references=[
            Recordings.peertube_channel("foss4geurope", event="FOSS4GE 2025"),
            Recordings.youtube(PLAYLIST, event="FOSS4GE 2025"),
        ],
    )
    assert len(list(collection.get_items())) > 100
