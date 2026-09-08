import datetime as dt

import pytest

from talx_to_stac.schedule import Schedule, ScheduleError, export_url

BASE = {"url": "https://x.org/e/schedule/", "base_url": "https://x.org", "version": "1.0"}


def build(session: dict, *, nested: bool = False, rooms: list | None = None) -> Schedule:
    core = {"days": [{"rooms": {"Hall": [session]}}], "rooms": rooms or []}
    conference = {"acronym": "e", "title": "E", "time_zone_name": "UTC"}
    body = (
        {**BASE, "conference": {**conference, **core}}
        if nested
        else {**BASE, "conference": conference, **core}
    )
    return Schedule.from_payload({"schedule": body})


def session(**overrides) -> dict:
    return {
        "code": "AAA111",
        "guid": "g-1",
        "title": "A talk",
        "date": "2025-07-16T09:00:00+02:00",
        "duration": "00:45",
        "url": "https://x.org/e/talk/AAA111/",
        **overrides,
    }


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ("https://x.org/e/schedule/", "https://x.org/e/schedule/export/schedule.json"),
        ("https://x.org/e", "https://x.org/e/schedule/export/schedule.json"),
        (
            "https://x.org/e/schedule/export/schedule.json",
            "https://x.org/e/schedule/export/schedule.json",
        ),
    ],
)
def test_export_url_is_derived_from_any_url_in_the_event(given, expected):
    assert export_url(given) == expected


@pytest.mark.parametrize("nested", [False, True])
def test_both_export_layouts_parse_the_same(nested):
    """Pretalx nests days under the schedule in some events, the conference in others."""
    parsed = build(session(), nested=nested)
    assert [s.code for s in parsed.sessions] == ["AAA111"]
    assert parsed.event.acronym == "e"


def test_end_is_derived_from_the_duration_the_export_states():
    only = build(session(duration="01:30")).sessions[0]
    assert only.end - only.start == dt.timedelta(minutes=90)


def test_start_keeps_the_events_own_offset():
    assert build(session()).sessions[0].start.utcoffset() == dt.timedelta(hours=2)


def test_midpoint_is_halfway_through():
    only = build(session(duration="00:30")).sessions[0]
    assert only.midpoint == only.start + dt.timedelta(minutes=15)


def test_a_session_listed_under_several_days_appears_once():
    one = session()
    payload = {
        "schedule": {
            **BASE,
            "conference": {"acronym": "e", "title": "E"},
            "days": [{"rooms": {"Hall": [one]}}, {"rooms": {"Hall": [one], "Annex": [one]}}],
        }
    }
    assert len(Schedule.from_payload(payload).sessions) == 1


def test_empty_and_null_fields_become_none():
    only = build(session(subtitle="", track=None, abstract="  ")).sessions[0]
    assert (only.subtitle, only.track, only.abstract) == (None, None, None)


def test_attachments_and_links_merge_into_resources_with_absolute_urls():
    only = build(
        session(
            attachments=[{"title": "Slides", "url": "/media/slides.pdf"}],
            links=[{"title": "Repo", "url": "https://github.com/a/b"}],
        )
    ).sessions[0]
    assert [r.url for r in only.resources] == [
        "https://x.org/media/slides.pdf",
        "https://github.com/a/b",
    ]


def test_rooms_fall_back_to_the_ones_sessions_mention():
    """Some events omit the room block entirely."""
    assert [r.name for r in build(session()).rooms] == ["Hall"]


def test_declared_rooms_keep_their_capacity():
    rooms = [{"name": "Hall", "slug": "1-hall", "capacity": 300}]
    room = build(session(), rooms=rooms).room("Hall")
    assert room is not None and room.capacity == 300


def test_a_payload_without_days_is_rejected():
    with pytest.raises(ScheduleError):
        Schedule.from_payload({"schedule": {"conference": {"acronym": "e"}}})
