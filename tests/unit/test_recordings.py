import datetime as dt

import pytest

from talx_to_stac.recordings import Recordings, Video
from talx_to_stac.schedule import Session
from tests.conftest import stub_client

START = dt.datetime(2025, 7, 16, 9, tzinfo=dt.UTC)


class FakeCatalogue:
    source = "fakeplatform"

    def __init__(self, *titles: str) -> None:
        self.titles = titles
        self.reads = 0

    def videos(self):
        self.reads += 1
        return [Video(title=t, url=f"https://v.example/{i}") for i, t in enumerate(self.titles)]


class BrokenCatalogue:
    source = "fakeplatform"

    def videos(self):
        raise RuntimeError("the platform is down")


def session(title: str) -> Session:
    return Session(
        code="A",
        guid="g",
        title=title,
        room="Hall",
        start=START,
        end=START + dt.timedelta(minutes=30),
        url="https://x.org/t/",
    )


def urls(src: Recordings, title: str) -> list[str]:
    return [r.url for r in src.references_for(session(title))]


def source(*titles: str, event: str | None = "FOSS4GE 2025") -> Recordings:
    return Recordings(FakeCatalogue(*titles), event=event)


def test_a_title_matches_past_the_event_prefix_and_case():
    assert urls(source("FOSS4GE 2025 | Opening ceremony"), "Opening Ceremony") == [
        "https://v.example/0"
    ]


def test_a_truncated_title_still_matches_its_session():
    src = source("FOSS4GE 2025 | Community led Open Mapping Solutions: addressing humanitarian ...")
    assert urls(src, "Community led Open Mapping Solutions: addressing humanitarian needs") == [
        "https://v.example/0"
    ]


def test_a_video_that_appends_the_speaker_still_matches_its_session():
    """Some collections title entries ``EVENT | Talk title - Speaker Name``."""
    src = source(
        "2023 | SMASH and the new survey server - state of the art - Andrea Antonello", event=None
    )
    assert urls(src, "SMASH and the new survey server - state of the art") == [
        "https://v.example/0"
    ]


def test_a_bar_inside_the_talk_title_does_not_hide_the_video():
    title = "QGIS | the whole story of a long running open source project"
    assert urls(source(title, event=None), title) == ["https://v.example/0"]


def test_titles_too_short_to_be_evidence_are_not_matched_on_a_prefix():
    assert urls(source("FOSS4GE 2025 | State of the map"), "State of the map in Europe") == []


def test_a_truncated_title_too_short_to_be_evidence_is_ignored():
    assert urls(source("FOSS4GE 2025 | State ..."), "State of GeoServer") == []


def test_recordings_from_another_year_in_the_same_collection_are_not_borrowed():
    assert urls(source("FOSS4GE 2024 | State of GeoServer"), "State of GeoServer") == []


def test_without_a_tag_every_video_in_the_catalogue_is_eligible():
    """A playlist is already one conference, so it needs no tag."""
    src = source("FOSS4GE 2024 | State of GeoServer", event=None)
    assert urls(src, "State of GeoServer") == ["https://v.example/0"]


def test_several_recordings_of_one_session_are_all_kept():
    src = source("FOSS4GE 2025 | Unscheduled talks", "FOSS4GE 2025 | Unscheduled talks")
    assert len(urls(src, "Unscheduled talks")) == 2


def test_ambiguous_truncated_titles_are_dropped_rather_than_guessed():
    src = source(
        "FOSS4GE 2025 | Mapping the world with open data ...",
        "FOSS4GE 2025 | Mapping the world with open data and ...",
    )
    assert urls(src, "Mapping the world with open data and tools") == []


def test_an_unreadable_catalogue_yields_no_recordings_rather_than_failing():
    assert urls(Recordings(BrokenCatalogue(), event="FOSS4GE 2025"), "Opening ceremony") == []


def test_the_catalogue_is_read_once_however_many_sessions_ask():
    catalogue = FakeCatalogue("FOSS4GE 2025 | Opening ceremony")
    src = Recordings(catalogue, event="FOSS4GE 2025")
    for _ in range(3):
        src.references_for(session("Opening ceremony"))
    assert catalogue.reads == 1


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ("PL123", "https://www.youtube.com/playlist?list=PL123"),
        (
            "https://www.youtube.com/watch?v=abc&list=PL123",
            "https://www.youtube.com/watch?v=abc&list=PL123",
        ),
    ],
)
def test_a_playlist_is_named_by_id_or_by_any_url_carrying_one(given, expected):
    from talx_to_stac.recordings import _playlist_url

    assert _playlist_url(given) == expected


def test_a_recording_names_the_platform_it_came_from():
    found = list(source("FOSS4GE 2025 | Opening ceremony").references_for(session("Opening")))
    assert [r.source for r in found] == []
    found = list(
        source("FOSS4GE 2025 | Opening ceremony").references_for(session("Opening ceremony"))
    )
    assert [r.source for r in found] == ["fakeplatform"]


def test_the_shipped_catalogues_name_their_platforms():
    from talx_to_stac.recordings import _PeerTubeChannel, _YouTubePlaylist

    assert _PeerTubeChannel.source == "peertube"
    assert _YouTubePlaylist.source == "youtube"


def test_the_peertube_playlist_unwraps_each_entry():
    data = [
        {"video": {"name": f"FOSS4GE 2025 | Talk {i}", "shortUUID": f"id{i}"}} for i in range(3)
    ]
    client = stub_client({"video-playlists": {"total": len(data), "data": data}})
    src = Recordings.peertube_playlist("https://video.osgeo.org/w/p/abc123", client=client)
    assert urls(src, "Talk 1") == ["https://video.osgeo.org/videos/watch/id1"]


def test_a_playlist_url_and_a_bare_id_name_the_same_playlist():
    from talx_to_stac.recordings import _PEERTUBE_ID

    found = _PEERTUBE_ID.search("https://video.osgeo.org/w/p/abc123?x=1")
    assert found is not None and found.group(1) == "abc123"
    assert _PEERTUBE_ID.search("abc123") is None


def test_the_peertube_channel_pages_through_the_api():
    data = [{"name": f"FOSS4GE 2025 | Talk {i}", "shortUUID": f"id{i}"} for i in range(3)]
    client = stub_client({"video-channels": {"total": len(data), "data": data}})
    src = Recordings.peertube_channel("chan", event="FOSS4GE 2025", client=client)
    assert urls(src, "Talk 1") == ["https://video.osgeo.org/videos/watch/id1"]
    assert [r.source for r in src.references_for(session("Talk 1"))] == ["peertube"]
