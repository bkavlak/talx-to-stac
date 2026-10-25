import datetime as dt

from talx_to_stac.references import Kind, Reference, SubmissionReferences, combine
from talx_to_stac.schedule import Event, Person, Room, Schedule, Session
from talx_to_stac.stac import build_collection
from talx_to_stac.venue import Venue

START = dt.datetime(2025, 7, 16, 9, tzinfo=dt.timezone(dt.timedelta(hours=2)))


class Fixed:
    def __init__(self, *references: Reference) -> None:
        self._references = references

    def references_for(self, session, schedule):
        return self._references


def session(**overrides) -> Session:
    fields = {
        "code": "AAA111",
        "guid": "g",
        "title": "A talk",
        "room": "Hall",
        "start": START,
        "end": START + dt.timedelta(minutes=30),
        "url": "https://x.org/e/talk/AAA111/",
        "track": "Academic",
        "type": "Talk",
        "language": "en",
    }
    return Session(**{**fields, **overrides})


def collection(*sessions, venue=None, references=None, rooms=()):
    schedule = Schedule(
        event=Event(
            acronym="e", title="E", schedule_url="https://x.org/e/schedule/", timezone="UTC"
        ),
        rooms=tuple(rooms) or tuple({Room(name=s.room) for s in sessions}),
        sessions=tuple(sessions),
    )
    return build_collection(
        schedule,
        venue or Venue.from_mapping({"Hall": [43.0, 17.0]}),
        references or combine(SubmissionReferences()),
    )


def only_item(*args, **kwargs):
    return next(collection(*args, **kwargs).get_items())


def test_the_item_id_is_the_session_code():
    assert only_item(session()).id == "AAA111"


def test_datetime_is_the_midpoint_and_the_range_is_stated_alongside_it():
    properties = only_item(session()).to_dict()["properties"]
    assert properties["datetime"] == "2025-07-16T07:15:00Z"
    assert properties["start_datetime"] == "2025-07-16T07:00:00Z"
    assert properties["end_datetime"] == "2025-07-16T07:30:00Z"


def test_the_item_sits_at_its_room():
    assert only_item(session()).geometry["coordinates"] == [17.0, 43.0]


def test_a_room_without_coordinates_still_produces_a_geometry():
    item = only_item(session(room="Elsewhere"), venue=Venue.anywhere())
    assert item.geometry["coordinates"] == [0.0, 0.0]


def test_a_schedule_with_no_sessions_still_has_a_valid_extent():
    """An event can publish its schedule before it has any sessions."""
    extent = collection().extent
    assert extent.spatial.bboxes == [[-180.0, -90.0, 180.0, 90.0]]
    assert extent.temporal.intervals == [[None, None]]


def test_empty_properties_are_left_out_rather_than_written_as_null():
    assert "talk:subtitle" not in only_item(session()).properties


def test_room_capacity_is_carried_over_when_the_event_declares_it():
    item = only_item(session(), rooms=[Room(name="Hall", capacity=300)])
    assert item.properties["talk:room_capacity"] == 300


def test_the_talk_page_is_always_an_asset():
    assert only_item(session()).assets["schedule"].href == "https://x.org/e/talk/AAA111/"


def test_resources_and_recordings_become_assets():
    item = only_item(
        session(),
        references=Fixed(
            Reference("https://x.org/s.pdf", "Slides", Kind.RESOURCE),
            Reference("https://v.org/w/1", "The talk", Kind.RECORDING, "text/html", "peertube"),
        ),
    )
    assert item.assets["slides"].roles == ["presentation"]
    assert item.assets["recording-peertube"].href == "https://v.org/w/1"
    assert item.assets["recording-peertube"].roles == ["data", "video", "peertube"]


def test_a_mention_becomes_a_related_link_not_an_asset():
    item = only_item(
        session(), references=Fixed(Reference("https://acme.example", "ACME", Kind.MENTION))
    )
    assert "https://acme.example" in [link.href for link in item.links if link.rel == "related"]
    assert list(item.assets) == ["schedule"]


def test_speakers_appear_as_properties_and_as_related_links():
    speaker = Person(code="p", name="P", url="https://x.org/e/speaker/p/")
    item = only_item(session(persons=(speaker,)))
    assert item.properties["talk:speakers"] == [
        {"code": "p", "name": "P", "url": "https://x.org/e/speaker/p/"}
    ]
    assert "https://x.org/e/speaker/p/" in [
        link.href for link in item.links if link.rel == "related"
    ]


def test_assets_with_the_same_name_do_not_overwrite_each_other():
    item = only_item(
        session(),
        references=Fixed(
            Reference("https://x.org/1.pdf", "Slides", Kind.RESOURCE),
            Reference("https://x.org/2.pdf", "Slides", Kind.RESOURCE),
        ),
    )
    assert {"slides", "slides-2"} <= set(item.assets)


def test_the_spatial_extent_covers_every_item():
    built = collection(
        session(code="A", room="Hall"),
        session(code="B", room="Annex"),
        venue=Venue.from_mapping({"Hall": [43.0, 17.0], "Annex": [44.0, 18.0]}),
    )
    assert built.extent.spatial.bboxes == [[17.0, 43.0, 18.0, 44.0]]


def test_the_temporal_extent_spans_first_start_to_last_end():
    built = collection(
        session(code="A"),
        session(code="B", start=START + dt.timedelta(hours=3), end=START + dt.timedelta(hours=4)),
    )
    start, end = built.extent.temporal.intervals[0]
    assert (start.hour, end.hour) == (7, 11)


def test_summaries_offer_the_fields_worth_filtering_on():
    built = collection(session(code="A", track="Academic"), session(code="B", track="Plenary"))
    assert built.summaries.to_dict()["talk:track"] == ["Academic", "Plenary"]
