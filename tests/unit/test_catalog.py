import datetime as dt

import pytest

from talx_to_stac.catalog import Conference, Programme, to_catalog

TALKS = {
    "schedule": {
        "url": "https://x.org/e/schedule/",
        "base_url": "https://x.org",
        "conference": {"acronym": "e", "title": "E talks"},
        "days": [
            {
                "rooms": {
                    "Hall": [
                        {
                            "code": "T1",
                            "guid": "g1",
                            "title": "A talk",
                            "date": "2025-07-16T09:00:00+02:00",
                            "duration": "00:30",
                            "url": "https://x.org/e/talk/T1/",
                        }
                    ]
                }
            }
        ],
    }
}
WORKSHOPS = {
    "schedule": {
        "url": "https://x.org/w/schedule/",
        "base_url": "https://x.org",
        "conference": {"acronym": "e-workshops", "title": "E workshops"},
        "days": [
            {
                "rooms": {
                    "Lab": [
                        {
                            "code": "W1",
                            "guid": "g2",
                            "title": "A workshop",
                            "date": "2025-07-14T09:00:00+02:00",
                            "duration": "04:00",
                            "url": "https://x.org/w/talk/W1/",
                        }
                    ]
                }
            }
        ],
    }
}


@pytest.fixture
def catalog(monkeypatch):
    """One conference with two programmes, served from canned payloads."""
    from talx_to_stac import schedule as schedule_module

    payloads = {"/e/": TALKS, "/w/": WORKSHOPS}

    def fake_from_url(cls, /, event_url, **kwargs):
        return cls.from_payload(next(v for k, v in payloads.items() if k in event_url))

    monkeypatch.setattr(schedule_module.Schedule, "from_url", classmethod(fake_from_url))
    return to_catalog(
        [
            Conference(
                id="e-2025",
                title="E 2025",
                venue={"Hall": [43.0, 17.0], "Lab": [44.0, 18.0]},
                programmes=[
                    Programme("talks", "https://x.org/e/schedule/"),
                    Programme("workshops", "https://x.org/w/schedule/"),
                ],
            )
        ],
        catalog_id="root",
    )


def test_the_tree_is_catalog_conference_programme_item(catalog):
    conference = next(catalog.get_children())
    assert [c.id for c in conference.get_children()] == ["e-2025-talks", "e-2025-workshops"]
    assert [i.id for i in conference.get_children().__next__().get_items()] == ["T1"]


def test_a_programme_is_named_by_the_conference_not_by_its_pretalx_slug(catalog):
    """The talks event's own acronym is the conference id, so it cannot be reused."""
    conference = next(catalog.get_children())
    talks = next(conference.get_children())
    assert conference.id == "e-2025"
    assert talks.id == "e-2025-talks"
    assert next(talks.get_items()).to_dict()["collection"] == "e-2025-talks"


def test_a_programme_says_which_programme_it_is(catalog):
    talks = next(next(catalog.get_children()).get_children())
    assert talks.extra_fields["talk:programme"] == "talks"
    assert talks.title == "Talks"
    assert talks.description.startswith("E talks:")


def test_a_conference_spans_every_programme_it_holds(catalog):
    """Its workshops run before its talks, so the extent has to cover both."""
    conference = next(catalog.get_children())
    start, end = conference.extent.temporal.intervals[0]
    assert start == dt.datetime(2025, 7, 14, 7, tzinfo=dt.UTC)
    assert end == dt.datetime(2025, 7, 16, 7, 30, tzinfo=dt.UTC)
    assert conference.extent.spatial.bboxes == [[17.0, 43.0, 18.0, 44.0]]


def test_the_conference_describes_what_it_holds(catalog):
    conference = next(catalog.get_children())
    assert conference.description == "E 2025: 1 talks, 1 workshops."
