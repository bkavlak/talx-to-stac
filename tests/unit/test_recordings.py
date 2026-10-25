import datetime as dt

import pytest

from talx_to_stac.recordings import Recordings, Video
from talx_to_stac.schedule import Event, Person, Schedule, Session
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


def session(title: str, *speakers: str, code: str = "A") -> Session:
    return Session(
        code=code,
        guid="g",
        title=title,
        room="Hall",
        start=START,
        end=START + dt.timedelta(minutes=30),
        url="https://x.org/t/",
        persons=tuple(Person(code=f"P{i}", name=n) for i, n in enumerate(speakers)),
    )


def schedule(*sessions: Session) -> Schedule:
    event = Event(acronym="e", title="E", schedule_url="https://x.org/e/schedule/")
    return Schedule(event=event, rooms=(), sessions=sessions)


def found(src: Recordings, wanted: Session, *others: Session) -> list[str]:
    return [r.url for r in src.references_for(wanted, schedule(wanted, *others))]


def urls(src: Recordings, title: str, *speakers: str) -> list[str]:
    return found(src, session(title, *speakers))


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
        urls(src, "Opening ceremony")
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
def test_a_youtube_playlist_is_named_by_id_or_by_any_url_carrying_one(given, expected, monkeypatch):
    yt_dlp = pytest.importorskip("yt_dlp")
    asked = []

    def extract_info(self, url, download):
        asked.append(url)
        return {"entries": [{"id": "abc", "title": "FOSS4GE 2025 | Talk 1"}]}

    monkeypatch.setattr(yt_dlp.YoutubeDL, "extract_info", extract_info)
    assert urls(Recordings.youtube(given), "Talk 1") == ["https://www.youtube.com/watch?v=abc"]
    assert asked == [expected]


def test_a_recording_names_the_platform_it_came_from():
    talk = session("Opening ceremony")
    found = source("FOSS4GE 2025 | Opening ceremony").references_for(talk, schedule(talk))
    assert [r.source for r in found] == ["fakeplatform"]


def test_the_shipped_catalogues_name_their_platforms():
    assert Recordings.peertube_channel("chan").source == "peertube"
    assert Recordings.peertube_playlist("abc123").source == "peertube"
    assert Recordings.youtube("PL123").source == "youtube"


def test_the_peertube_playlist_unwraps_each_entry():
    data = [
        {"video": {"name": f"FOSS4GE 2025 | Talk {i}", "shortUUID": f"id{i}"}} for i in range(3)
    ]
    client = stub_client({"video-playlists": {"total": len(data), "data": data}})
    src = Recordings.peertube_playlist("https://video.osgeo.org/w/p/abc123", client=client)
    assert urls(src, "Talk 1") == ["https://video.osgeo.org/videos/watch/id1"]


@pytest.mark.parametrize("playlist", ["abc123", "https://video.osgeo.org/w/p/abc123?x=1"])
def test_a_peertube_playlist_is_named_by_id_or_by_its_url(playlist):
    data = [{"video": {"name": "FOSS4GE 2025 | Talk 1", "shortUUID": "id1"}}]
    client = stub_client({"video-playlists/abc123/": {"total": 1, "data": data}})
    src = Recordings.peertube_playlist(playlist, client=client)
    assert urls(src, "Talk 1") == ["https://video.osgeo.org/videos/watch/id1"]


def test_the_peertube_channel_pages_through_the_api():
    data = [{"name": f"FOSS4GE 2025 | Talk {i}", "shortUUID": f"id{i}"} for i in range(3)]
    client = stub_client({"video-channels": {"total": len(data), "data": data}})
    src = Recordings.peertube_channel("chan", event="FOSS4GE 2025", client=client)
    assert urls(src, "Talk 1") == ["https://video.osgeo.org/videos/watch/id1"]
    talk = session("Talk 1")
    assert [r.source for r in src.references_for(talk, schedule(talk))] == ["peertube"]


def test_a_short_title_matches_once_the_speakers_name_is_set_aside():
    """FOSS4G 2023 appends the speaker, which no prefix rule can see past on a short title."""
    src = source("2023 | Valhalla Routing Engine - Nils Nolde", event=None)
    assert urls(src, "Valhalla Routing Engine", "Nils Nolde") == ["https://v.example/0"]


def test_a_dash_that_does_not_name_a_speaker_stays_part_of_the_title():
    """Set aside, both would be this session's title; kept, they are two other talks."""
    src = source(
        "FOSS4G 2024 | Plugins to the rescue - Natural catastrophe mapping",
        "FOSS4G 2024 | Plugins to the rescue - Flood response",
        event=None,
    )
    assert urls(src, "Plugins to the rescue", "Jane Doe") == []


def test_an_event_prefix_without_a_bar_is_still_an_event_prefix():
    title = "Field mapping: an open source platform based on QGIS for data collection"
    src = source(f"FOSS4G 2024 -{title}", event=None)
    assert urls(src, title) == ["https://v.example/0"]


def test_an_ampersand_and_the_word_and_are_the_same_title():
    src = source(
        "2023 | Lessons from Enterprise GIS Implementations with QGIS & PostGIS", event=None
    )
    assert urls(src, "Lessons from Enterprise GIS Implementations with QGIS and PostGIS") == [
        "https://v.example/0"
    ]


def test_an_abbreviated_title_matches_its_session():
    src = source(
        "FOSS4G 2024 | How to Bridge the Gaps Between R.S. AI Research and Industry Challenges",
        "FOSS4G 2024 | Open Forest Observatory: drone-based forest mapping tools",
        event=None,
    )
    assert urls(
        src, "How to Bridge the Gaps Between Remote Sensing AI Research and Industry Challenges"
    ) == ["https://v.example/0"]


def test_titles_alike_in_everything_but_the_project_name_do_not_match():
    """Common words say little; the one that differs is the one that matters."""
    src = source(
        "FOSS4G 2024 | pygeometa project status and roadmap update",
        "FOSS4G 2024 | GeoServer project status and roadmap update",
        "FOSS4G 2024 | QGIS project status and roadmap update",
        event=None,
    )
    assert urls(src, "pygeoapi project status and roadmap update") == []


def test_two_equally_close_videos_are_dropped_rather_than_guessed():
    src = source(
        "2023 | Modernising Tasking Manager infrastructure with Terraform and good sense",
        "2023 | Modernising Tasking Manager infrastructure using Terraform and good sense",
        event=None,
    )
    assert urls(src, "Modernising Tasking Manager infrastructure via Terraform, good sense") == []


def test_a_video_named_by_the_talks_heading_alone_matches():
    """FOSS4G 2024 titled some videos with only the part before the colon."""
    src = source("FOSS4G 2024 | OpenGeoSGB", "FOSS4G 2024 | Overture Maps", event=None)
    assert urls(src, "OpenGeoSGB: State of the art of transition to open source") == [
        "https://v.example/0"
    ]


def test_a_video_holding_the_whole_session_title_matches_however_short():
    src = source("2023 | FOSS4G 2023 Closing session", "2023 | OSGeo AGM Session", event=None)
    assert urls(src, "Closing session") == ["https://v.example/0"]


def test_a_speaker_written_without_a_space_is_still_the_speaker():
    src = source(
        '2023 | Offline web map server "UNVT Portable" - Shogo Hirasawa',
        '2023 | Offline web map server "UNVT Portable" - Taichi Furuhashi & Shogo Hirasawa',
        event=None,
    )
    assert urls(src, 'Offline web map server "UNVT Portable"', "ShogoHirasawa") == [
        "https://v.example/0"
    ]


def test_one_talk_uploaded_twice_is_not_ambiguous():
    src = source(
        "2023 | Modernising Tasking Manager infrastructure using Terraform & good sense",
        "2023 | Modernising Tasking Manager infrastructure using Terraform and good sense",
        event=None,
    )
    assert len(urls(src, "Modernising Tasking Manager Infrastructure")) == 2


def test_a_video_title_left_empty_by_its_event_prefix_matches_nothing():
    assert urls(source("FOSS4G 2022", event=None), "EODAG (Earth Observation Data Access)") == []


def test_speakers_appended_without_a_dash_are_still_set_aside():
    src = source(
        "2023 | Transit Access to Essential Services Erin Stein & Kaushik Mohan", event=None
    )
    talk = session("Transit Access to Essential Services", "Erin Stein", "Kaushik Mohan")
    assert found(src, talk) == ["https://v.example/0"]


def test_a_video_titled_exactly_as_another_session_is_never_borrowed():
    """Alike in all but the project name, and the other session has the exact title."""
    src = source(
        "2023 | GeoServer Orientation and Demo - Jody Garnett",
        "2023 | Cartographic design for vector tiles",
        event=None,
    )
    geonetwork = session("GeoNetwork Orientation and Demo", "Jody Garnett", code="N")
    geoserver = session("GeoServer Orientation and Demo", "Jody Garnett", code="S")
    assert found(src, geonetwork, geoserver) == []
    assert found(src, geoserver, geonetwork) == ["https://v.example/0"]


def test_a_workshop_does_not_take_the_recording_of_the_talk_it_is_named_after():
    src = source("FOSS4G 2025 | Building Spatial APIs in PostgreSQL with PostgREST", event=None)
    talk = session("Building Spatial APIs in PostgreSQL with PostgREST", code="T")
    workshop = session("Building Spatial APIs in PostgreSQL with PostgREST Workshop", code="W")
    assert found(src, workshop, talk) == []
    assert found(src, talk, workshop) == ["https://v.example/0"]
