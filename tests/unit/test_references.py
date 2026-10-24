import datetime as dt

import pytest

from talx_to_stac.references import (
    AbstractReferences,
    BiographyReferences,
    Kind,
    Reference,
    SubmissionReferences,
    combine,
)
from talx_to_stac.schedule import Event, Person, Resource, Schedule, Session

START = dt.datetime(2025, 7, 16, 9, tzinfo=dt.UTC)


def session(**overrides) -> Session:
    return Session(
        code="AAA111",
        guid="g",
        title="A talk",
        room="Hall",
        start=START,
        end=START + dt.timedelta(minutes=30),
        url="https://x.org/talk/AAA111/",
        **overrides,
    )


def within(session: Session) -> Schedule:
    event = Event(acronym="e", title="E", schedule_url="https://x.org/e/schedule/")
    return Schedule(event=event, rooms=(), sessions=(session,))


def references(source, session: Session):
    return source.references_for(session, within(session))


def test_submission_resources_become_resource_references():
    found = list(
        references(
            SubmissionReferences(),
            session(resources=(Resource(title="Slides", url="https://x.org/s.pdf"),)),
        )
    )
    assert found == [
        Reference(
            url="https://x.org/s.pdf",
            title="Slides",
            kind=Kind.RESOURCE,
            media_type="application/pdf",
        )
    ]


@pytest.mark.parametrize(
    ("prose", "url", "title"),
    [
        ("see [my slides](https://x.org/a) for more", "https://x.org/a", "my slides"),
        ('see <a href="https://x.org/a">my slides</a>', "https://x.org/a", "my slides"),
        ("see https://x.org/a for more", "https://x.org/a", "x.org/a"),
        ("ends a sentence https://x.org/a.", "https://x.org/a", "x.org/a"),
    ],
)
def test_links_are_found_in_markdown_html_and_bare_prose(prose, url, title):
    found = list(references(AbstractReferences(), session(abstract=prose)))
    assert [(r.url, r.title, r.kind) for r in found] == [(url, title, Kind.MENTION)]


def test_prose_without_links_yields_nothing():
    assert list(references(AbstractReferences(), session(abstract="no links here"))) == []


def test_the_same_url_in_abstract_and_description_is_one_mention():
    found = list(
        references(
            AbstractReferences(),
            session(abstract="[a](https://x.org/a)", description="[a again](https://x.org/a)"),
        )
    )
    assert len(found) == 1


def test_speaker_biographies_are_mined_too():
    speaker = Person(code="p", name="P", biography="I work at [ACME](https://acme.example)")
    found = list(references(BiographyReferences(), session(persons=(speaker,))))
    assert [r.url for r in found] == ["https://acme.example"]


def test_a_url_named_in_prose_and_attached_as_a_resource_collapses_to_the_resource():
    combined = combine(SubmissionReferences(), AbstractReferences())
    found = list(
        references(
            combined,
            session(
                resources=(Resource(title="Slides", url="https://x.org/s.pdf"),),
                abstract="my slides are at https://x.org/s.pdf#page=1",
            ),
        )
    )
    assert [(r.title, r.kind) for r in found] == [("Slides", Kind.RESOURCE)]


def test_a_source_that_raises_is_isolated():
    class Broken:
        def references_for(self, session, schedule):
            raise RuntimeError("upstream is down")

    found = list(
        references(
            combine(Broken(), SubmissionReferences()),
            session(resources=(Resource(title="Slides", url="https://x.org/s.pdf"),)),
        )
    )
    assert [r.title for r in found] == ["Slides"]


def test_media_type_is_guessed_from_the_url():
    media_type = Reference("https://x.org/a.pptx", "A", Kind.RESOURCE).media_type
    assert media_type is not None and media_type.endswith("presentationml.presentation")
    assert Reference("https://x.org/a", "A", Kind.RESOURCE).media_type is None
