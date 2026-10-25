"""Recordings of the talks, wherever they are published.

Conference video collections all look the same from a distance: entries titled
``EVENT | Talk title``, truncated near a hundred characters, with several years
of one series sharing a collection. So the matching rule lives once, in
:class:`Recordings`, and each platform contributes only a list of videos.
"""

from __future__ import annotations

import logging
import math
import os
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from enum import IntEnum
from typing import TYPE_CHECKING, Any, ClassVar, Protocol, cast

import httpx

from talx_to_stac.references import Kind, Reference

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence

    from talx_to_stac.schedule import Schedule, Session

_LOG = logging.getLogger(__name__)
_PEERTUBE_ID = re.compile(r"/w/p/([A-Za-z0-9]+)")
_PAGE = 100
_TIMEOUT = 30.0
_LIMIT = 5000
_MIN_PREFIX = 24
"""Shortest title trusted when it merely resembles another."""
_NAME = 3
"""Shortest word taken for part of a speaker's name when no dash announces one."""
_CLOSE = 0.65
"""Share of a video title's word weight its session must contain to be close."""
_COVERED = 0.4
"""Share of the session title's word weight the video must keep to be close."""
_EVENT_PREFIX = re.compile(
    r"^\s*(?:foss4g\w*\s+)?(?:19|20)\d\d\b(?:\s+keynote)?\s*[:\-\u2013\u2014]?\s*", re.I
)
_SPEAKER_SUFFIX = re.compile(r"\s*[-\u2013\u2014]\s*([^-\u2013\u2014]+)$")

VIDEO_OSGEO = "https://video.osgeo.org"


@dataclass(frozen=True, slots=True)
class Video:
    """One published video."""

    title: str
    url: str


class VideoCatalogue(Protocol):
    """A place recordings are published."""

    @property
    def source(self) -> str:
        """The platform these videos live on, e.g. ``peertube`` or ``youtube``."""
        ...

    def videos(self) -> Iterable[Video]:
        """Return every video in the collection."""
        ...


class Recordings:
    """Attaches each session's recordings from a catalogue of videos.

    Example:
        >>> to_stac(url, references=[
        ...     Recordings.peertube_channel("foss4geurope", event="FOSS4GE 2025"),
        ...     Recordings.youtube("PLqa06jy1NEM0Ss-CMTP4LrOw0f5aeVHdk", event="FOSS4GE 2025"),
        ... ])
    """

    def __init__(self, catalogue: VideoCatalogue, *, event: str | None = None) -> None:
        """Initialise the source.

        Args:
            catalogue: Where the videos are published.
            event: Consider only videos whose title contains this tag, e.g.
                ``FOSS4GE 2025``. Needed for a channel, which usually holds
                every year of a series; unnecessary for a playlist, which is
                already one conference.
        """
        self._catalogue = catalogue
        self._event = event
        self._eligible: _Eligible | None = None
        self._owned: tuple[Schedule, Mapping[str, frozenset[str]]] | None = None

    @property
    def source(self) -> str:
        """The platform these recordings come from, e.g. ``peertube``."""
        return self._catalogue.source

    @property
    def videos(self) -> tuple[Video, ...]:
        """Every video this source may match: the catalogue, less other events.

        Read once and remembered; empty if the catalogue cannot be read.
        """
        return self._catalogued().videos

    @classmethod
    def peertube_channel(
        cls,
        channel: str,
        *,
        event: str | None = None,
        host: str = VIDEO_OSGEO,
        client: httpx.Client | None = None,
    ) -> Recordings:
        """Recordings from a PeerTube channel.

        A channel usually spans several years of a series, so pass ``event``.

        Args:
            channel: The channel handle, e.g. ``foss4geurope``.
            event: The tag the video titles carry.
            host: The PeerTube instance, video.osgeo.org by default.
            client: An httpx client to reuse.

        Returns:
            The configured source.
        """
        return cls(_PeerTube(host.rstrip("/"), f"video-channels/{channel}", client), event=event)

    @classmethod
    def peertube_playlist(
        cls,
        playlist: str,
        *,
        event: str | None = None,
        host: str = VIDEO_OSGEO,
        client: httpx.Client | None = None,
    ) -> Recordings:
        """Recordings from a PeerTube playlist.

        Args:
            playlist: A playlist id or any ``/w/p/<id>`` URL carrying one.
            event: Rarely needed; a playlist is already one conference.
            host: The PeerTube instance, video.osgeo.org by default.
            client: An httpx client to reuse.

        Returns:
            The configured source.
        """
        found = _PEERTUBE_ID.search(playlist)
        identifier = found.group(1) if found else playlist
        listing = f"video-playlists/{identifier}"
        return cls(_PeerTube(host.rstrip("/"), listing, client), event=event)

    @classmethod
    def youtube(cls, playlist: str, *, event: str | None = None) -> Recordings:
        """Recordings from a YouTube playlist.

        Args:
            playlist: A playlist id or any YouTube URL carrying one.
            event: Rarely needed; a playlist is already one conference.

        Returns:
            The configured source.
        """
        return cls(_YouTubePlaylist(playlist), event=event)

    def references_for(self, session: Session, schedule: Schedule) -> Iterable[Reference]:
        """Return the session's recordings, or nothing if none can be matched.

        Evidence is ranked: an identical title beats one that continues or
        contains the other, which beats one that shares the title's distinctive
        words. Only the strongest kind found counts. Several identical titles
        are several recordings of one session and all belong to it; weaker
        evidence must point at one title, since several only mean the titles
        were too alike to tell apart. The same title uploaded twice is still
        one title.

        A video titled exactly as another session of ``schedule`` belongs to
        that session, so no weaker evidence can take it. That is what keeps
        ``GeoNetwork Orientation and Demo`` off the GeoServer recording.
        """
        talk = _Talk.of(session)
        if not talk.title:
            return []
        catalogue = self._catalogued()
        owners = self._owners(schedule)

        best: list[Video] = []
        strongest = _Evidence.NONE
        for video in catalogue.videos:
            owner = owners.get(video.url)
            if owner and session.code not in owner:
                continue
            evidence = max(
                (_evidence(c, talk, catalogue.weight) for c in _titles_of(video.title, talk)),
                default=_Evidence.NONE,
            )
            if evidence > strongest:
                best, strongest = [video], evidence
            elif evidence is strongest and evidence is not _Evidence.NONE:
                best.append(video)

        distinct = {_normalise(v.title) for v in best}
        found = best if strongest is _Evidence.SAME or len(distinct) == 1 else []
        return [
            Reference(
                url=v.url,
                title=v.title,
                kind=Kind.RECORDING,
                media_type="text/html",
                source=self._catalogue.source,
            )
            for v in sorted(found, key=lambda v: v.url)
        ]

    def _owners(self, schedule: Schedule) -> Mapping[str, frozenset[str]]:
        """The sessions each video is titled exactly as, by video URL.

        Worked out once per schedule: every session asks the same question.
        """
        if self._owned is None or self._owned[0] is not schedule:
            videos = self._catalogued().videos
            owned: dict[str, set[str]] = {}
            for session in schedule.sessions:
                talk = _Talk.of(session)
                for video in videos:
                    if talk.title and talk.title in _titles_of(video.title, talk):
                        owned.setdefault(video.url, set()).add(session.code)
            self._owned = (schedule, {url: frozenset(codes) for url, codes in owned.items()})
        return self._owned[1]

    def _catalogued(self) -> _Eligible:
        """The videos this source may match, read once, empty if unreachable."""
        if self._eligible is None:
            try:
                videos = tuple(self._catalogue.videos())
            except Exception:
                _LOG.warning("could not read %s; no recordings", self._catalogue, exc_info=True)
                videos = ()
            tag = _normalise(self._event or "")
            self._eligible = _Eligible.of(v for v in videos if tag in _normalise(v.title))
        return self._eligible


class _Evidence(IntEnum):
    """How strongly a video's title says it is a given session."""

    NONE = 0
    CLOSE = 1
    """The same distinctive words, give or take an abbreviation or a rewording,
    or exactly the session's heading -- which another talk may share."""
    CONTINUES = 2
    """One title carries on where the other stops, or holds it whole."""
    SAME = 3


@dataclass(frozen=True, slots=True)
class _Talk:
    """What matching needs to know about a session, normalised once."""

    title: str
    heading: str
    """The title up to its first colon, which some videos use on its own; empty if none."""
    speakers: str
    """Every speaker's name run together, so ``ShogoHirasawa`` and ``Shogo Hirasawa`` agree."""

    @classmethod
    def of(cls, session: Session) -> _Talk:
        title = _normalise(session.title)
        heading = _normalise(session.title.split(":", 1)[0]) if ":" in session.title else ""
        names = _normalise(" ".join(p.name for p in session.persons)).replace(" ", "")
        return cls(title, "" if heading == title else heading, names)


@dataclass(frozen=True, slots=True)
class _Eligible:
    """A catalogue's videos, with how much each word distinguishes one from another.

    A word that appears in many titles -- ``state``, ``of``, ``project`` -- says
    little about which talk a video is; a project name says nearly everything.
    Weighting words by rarity is what stops ``State of PDAL`` matching
    ``State of deegree`` while still letting ``R.S.`` stand in for ``Remote
    Sensing``.
    """

    videos: tuple[Video, ...]
    frequency: Mapping[str, int]

    @classmethod
    def of(cls, videos: Iterable[Video]) -> _Eligible:
        kept = tuple(videos)
        frequency = Counter(w for v in kept for w in set(_titles_of(v.title)[0].split()))
        return cls(kept, frequency)

    def weight(self, word: str) -> float:
        return math.log((len(self.videos) + 1) / (self.frequency.get(word, 0) + 0.5))


@dataclass(frozen=True, slots=True)
class _PeerTube:
    """A PeerTube listing: a channel's videos or a playlist's entries."""

    host: str
    listing: str
    """The API path below ``/api/v1``, e.g. ``video-channels/foss4geurope``."""
    client: httpx.Client | None

    source: ClassVar[str] = "peertube"

    def videos(self) -> Iterator[Video]:
        """Page through the listing until every entry has been seen.

        A playlist wraps each entry around its video, which is null once the
        video is deleted; a channel lists videos bare.
        """
        url = f"{self.host}/api/v1/{self.listing}/videos"
        client = self.client or httpx.Client(timeout=_TIMEOUT, follow_redirects=True)
        try:
            start = 0
            while start < _LIMIT:
                params = {"count": _PAGE, "start": start}
                page: dict[str, Any] = client.get(url, params=params).raise_for_status().json()
                items = page.get("data") or []
                for item in items:
                    video = item.get("video", item) or {}
                    identifier = video.get("shortUUID") or video.get("uuid") or ""
                    yield Video(
                        title=str(video.get("name") or ""),
                        url=f"{self.host}/videos/watch/{identifier}",
                    )
                start += len(items)
                if not items or start >= int(page.get("total", 0)):
                    return
        finally:
            if self.client is None:
                client.close()

    def __str__(self) -> str:
        """Name the listing, for the warning when it cannot be read."""
        return f"{self.host} {self.listing}"


@dataclass(frozen=True, slots=True)
class _YouTubePlaylist:
    """A YouTube playlist, listed through yt-dlp.

    YouTube offers no stable key-free listing: the RSS feed stops at fifteen
    entries and the page markup is rewritten regularly. yt-dlp exists to absorb
    exactly that churn, so it is an optional dependency rather than something
    reimplemented here.
    """

    playlist: str

    source: ClassVar[str] = "youtube"

    def videos(self) -> Iterator[Video]:
        """List the playlist without downloading anything.

        Raises:
            ImportError: If yt-dlp is not installed.
        """
        try:
            import yt_dlp
        except ImportError as exc:  # pragma: no cover - depends on the environment
            msg = "YouTube recordings need yt-dlp: pip install 'talx-to-stac[youtube]'"
            raise ImportError(msg) from exc

        # yt-dlp types its options as a private TypedDict, so a plain literal
        # cannot satisfy it; the keys below are all documented options.
        options = cast(
            "Any",
            {
                "extract_flat": "in_playlist",
                "quiet": True,
                "no_warnings": True,
                "skip_download": True,
            },
        )
        with yt_dlp.YoutubeDL(options) as downloader:
            listing = downloader.extract_info(_playlist_url(self.playlist), download=False) or {}

        entries = cast("Iterable[dict[str, Any]]", listing.get("entries") or ())
        for entry in entries:
            identifier = entry.get("id")
            if identifier:
                yield Video(
                    title=str(entry.get("title") or ""),
                    url=f"https://www.youtube.com/watch?v={identifier}",
                )

    def __str__(self) -> str:
        """Name the playlist, for the warning when it cannot be read."""
        return f"YouTube playlist {self.playlist!r}"


def _playlist_url(playlist: str) -> str:
    """Accept a bare playlist id or any YouTube URL that carries one."""
    if playlist.startswith(("http://", "https://")):
        return playlist
    return f"https://www.youtube.com/playlist?list={playlist}"


def _titles_of(name: str, talk: _Talk | None = None) -> tuple[str, ...]:
    """The normalised titles a video name might be, most likely first.

    Entries are usually ``EVENT | Talk title``, but some drop the bar
    (``FOSS4G 2024 -Talk``) and some append the speaker (``Talk - Jane Doe``),
    which is removed only when it names the ``talk``'s speakers. A talk title
    may itself contain a bar, so the whole name stays a candidate too.
    """
    title = name.split("|", 1)[1] if "|" in name else _EVENT_PREFIX.sub("", name, count=1)
    if talk and talk.speakers:
        title = _without_speakers(title, talk.speakers)
    return (_normalise(title), _normalise(name))


def _without_speakers(title: str, speakers: str) -> str:
    """The title with any trailing speaker names removed, normalised.

    After a dash one name is enough (``Talk - Jane Doe``). Without one, as in
    ``Talk Jane Doe & John Roe``, it takes two words of names, so a title that
    merely ends in a word some speaker's name contains is left alone.
    """
    suffix = _SPEAKER_SUFFIX.search(title)
    if suffix:
        named = set(_normalise(suffix.group(1)).split()) - {"and"}
        if named and all(word in speakers for word in named):
            return _normalise(title[: suffix.start()])
    words = _normalise(title).split()
    kept = len(words)
    while kept and (words[kept - 1] == "and" or words[kept - 1] in speakers):
        kept -= 1
    names = [w for w in words[kept:] if w != "and" and len(w) >= _NAME]
    return " ".join(words[:kept]) if len(names) >= 2 else " ".join(words)


def _evidence(video: str, talk: _Talk, weight: Callable[[str], float]) -> _Evidence:
    """How strongly a normalised video title says it is ``talk``.

    Collections truncate long titles, wrap them in event names, shorten them
    to their heading, abbreviate words and occasionally reword them, so a real
    match often only resembles its session. A video title shorter than
    ``_MIN_PREFIX`` characters says too little to be trusted on resemblance;
    one that holds the session's whole title, or exactly its heading, is a
    deliberate choice and needs no such floor -- though a heading can be shared,
    so it counts only as close.
    """
    if not video:
        return _Evidence.NONE
    if video == talk.title:
        return _Evidence.SAME
    if video == talk.heading:
        return _Evidence.CLOSE
    if " " in talk.title and f" {talk.title} " in f" {video} ":
        return _Evidence.CONTINUES
    if min(len(video), len(talk.title)) < _MIN_PREFIX:
        return _Evidence.NONE
    if talk.title.startswith(f"{video} "):
        return _Evidence.CONTINUES
    a, b = video.split(), talk.title.split()
    if _shared(a, b, weight) >= _CLOSE and _shared(b, a, weight) >= _COVERED:
        return _Evidence.CLOSE
    return _Evidence.NONE


def _shared(words: Sequence[str], others: Sequence[str], weight: Callable[[str], float]) -> float:
    """The share of ``words``, by weight, that ``others`` also contains."""
    total = sum(weight(w) for w in words)
    found = sum(weight(w) for w in words if any(_alike(w, o) for o in others))
    return found / total if total else 0.0


def _alike(one: str, other: str) -> bool:
    """Whether two words are one word, abbreviated or inflected.

    ``prod`` for ``production``, ``introducing`` for ``introduction``.
    """
    if one == other:
        return True
    if min(len(one), len(other)) >= 4 and (one.startswith(other) or other.startswith(one)):
        return True
    return len(os.path.commonprefix([one, other])) >= 6


def _normalise(text: str) -> str:
    """Fold case, accents and punctuation so two spellings of a title compare equal."""
    folded = unicodedata.normalize("NFKD", text)
    stripped = "".join(c for c in folded if not unicodedata.combining(c)).replace("&", " and ")
    return " ".join(re.sub(r"[^0-9a-z]+", " ", stripped.lower()).split())
