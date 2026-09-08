"""Everything a session points at.

A talk names URLs in four different places -- its attached resources, its
abstract, its speakers' biographies, and whatever video platform later hosts the
recording -- and more places will appear. One concept covers them all: a
:class:`Reference`, a URL that belongs to a session, carrying enough
classification for the STAC layer to decide where it goes. Sources deliberately
know nothing about STAC.
"""

from __future__ import annotations

import html
import logging
import re
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Protocol
from urllib.parse import urlsplit, urlunsplit

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from talx_to_stac.schedule import Session

_LOG = logging.getLogger(__name__)

_MARKDOWN_LINK = re.compile(r"\[([^\]]*)\]\((https?://[^)\s]+)\)")
_HTML_LINK = re.compile(r"<a\b[^>]*\bhref=[\"'](https?://[^\"']+)[\"'][^>]*>(.*?)</a>", re.I | re.S)
_BARE_URL = re.compile(r"(?<![\"'(\]=])\bhttps?://[^\s<>\"')\]]+")
_TAGS = re.compile(r"<[^>]+>")
_TRAILING_PUNCTUATION = ".,;:!?"

_MEDIA_TYPES = {
    "pdf": "application/pdf",
    "ppt": "application/vnd.ms-powerpoint",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "odp": "application/vnd.oasis.opendocument.presentation",
    "doc": "application/msword",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "zip": "application/zip",
    "mp4": "video/mp4",
    "webm": "video/webm",
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "svg": "image/svg+xml",
}


class Kind(Enum):
    """What a reference is, which decides where it lands in a STAC Item."""

    RECORDING = "recording"
    """The talk itself, filmed."""

    RESOURCE = "resource"
    """An artifact of the talk: slides, a poster, a paper."""

    MENTION = "mention"
    """A URL the talk or its speaker merely names in prose."""


_PRECEDENCE = {Kind.RECORDING: 3, Kind.RESOURCE: 2, Kind.MENTION: 1}


@dataclass(frozen=True, slots=True)
class Reference:
    """A URL belonging to a session."""

    url: str
    title: str
    kind: Kind
    media_type: str | None = None
    source: str | None = None
    """The platform hosting this, e.g. ``peertube`` or ``youtube``.

    Left unset when the URL has no host worth naming -- a file attached to the
    submission is just a file, wherever pretalx happens to keep it.
    """

    def __post_init__(self) -> None:
        """Fill in the media type from the URL when the source did not know it."""
        if self.media_type is None:
            object.__setattr__(self, "media_type", media_type_of(self.url))


class ReferenceSource(Protocol):
    """Something that finds URLs belonging to a session."""

    def references_for(self, session: Session) -> Iterable[Reference]:
        """Return the references this source can find for one session."""
        ...


class SubmissionReferences:
    """The resources a speaker attached to their submission.

    This is exactly the "Resources" section of the pretalx talk page.
    """

    def references_for(self, session: Session) -> Iterable[Reference]:
        """Return one resource reference per attachment or link."""
        return [Reference(url=r.url, title=r.title, kind=Kind.RESOURCE) for r in session.resources]


class AbstractReferences:
    """URLs a speaker wrote into the abstract or description.

    In practice this is where most links live: speakers rarely fill in the
    resources form, but routinely paste links into their text.
    """

    def references_for(self, session: Session) -> Iterable[Reference]:
        """Return one mention per URL found in the session's prose."""
        return _mentions(session.abstract, session.description)


class BiographyReferences:
    """URLs a speaker wrote into their biography."""

    def references_for(self, session: Session) -> Iterable[Reference]:
        """Return one mention per URL found in any speaker biography."""
        return _mentions(*(p.biography for p in session.persons))


def combine(*sources: ReferenceSource) -> ReferenceSource:
    """Merge several sources into one.

    A source that fails is skipped rather than allowed to fail the transform,
    and references duplicated across sources collapse to the strongest kind, so
    a slide deck named both in the abstract and in the resources is one
    resource, not a resource plus a stray mention.

    Args:
        *sources: The sources to merge, in priority order.

    Returns:
        A single source over all of them.
    """
    return _Combined(sources)


def media_type_of(url: str) -> str | None:
    """Guess an IANA media type from a URL's file extension."""
    suffix = urlsplit(url).path.rsplit(".", 1)
    return _MEDIA_TYPES.get(suffix[-1].lower()) if len(suffix) == 2 else None


@dataclass(frozen=True, slots=True)
class _Combined:
    sources: Sequence[ReferenceSource]

    def references_for(self, session: Session) -> Iterable[Reference]:
        best: dict[str, Reference] = {}
        for source in self.sources:
            for reference in self._safely(source, session):
                key = _canonical(reference.url)
                current = best.get(key)
                if current is None or _PRECEDENCE[reference.kind] > _PRECEDENCE[current.kind]:
                    best[key] = reference
        return list(best.values())

    def _safely(self, source: ReferenceSource, session: Session) -> Iterable[Reference]:
        try:
            return list(source.references_for(session))
        except Exception:
            _LOG.warning(
                "%s found no references for %s", type(source).__name__, session.code, exc_info=True
            )
            return []


def _mentions(*texts: str | None) -> list[Reference]:
    found: dict[str, Reference] = {}
    for text in texts:
        for url, title in _links(text or ""):
            found.setdefault(_canonical(url), Reference(url=url, title=title, kind=Kind.MENTION))
    return list(found.values())


def _links(text: str) -> list[tuple[str, str]]:
    """Extract (url, label) pairs from markdown, HTML and bare-URL prose."""
    links = [(url, _label(label, url)) for label, url in _MARKDOWN_LINK.findall(text)]
    links += [(url, _label(_TAGS.sub("", label), url)) for url, label in _HTML_LINK.findall(text)]
    known = {url for url, _ in links}
    links += [
        (url, _label("", url))
        for url in (_trim(m) for m in _BARE_URL.findall(text))
        if url not in known
    ]
    return links


def _label(text: str, url: str) -> str:
    label = html.unescape(" ".join(text.split())).strip()
    if label:
        return label
    parts = urlsplit(url)
    return f"{parts.netloc}{parts.path}".rstrip("/") or url


def _trim(url: str) -> str:
    return url.rstrip(_TRAILING_PUNCTUATION)


def _canonical(url: str) -> str:
    """A comparison key that ignores fragments, trailing slashes and case of host."""
    parts = urlsplit(url.strip())
    return urlunsplit(
        (parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), parts.query, "")
    )
