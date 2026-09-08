"""Recordings of the talks, wherever they are published.

Conference video collections all look the same from a distance: entries titled
``EVENT | Talk title``, truncated near a hundred characters, with several years
of one series sharing a collection. So the matching rule lives once, in
:class:`Recordings`, and each platform contributes only a list of videos.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, ClassVar, Protocol, cast

import httpx

from talx_to_stac.references import Kind, Reference

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

    from talx_to_stac.schedule import Session

_LOG = logging.getLogger(__name__)
_PEERTUBE_ID = re.compile(r"/w/p/([A-Za-z0-9]+)")
_PAGE = 100
_LIMIT = 5000
_MIN_PREFIX = 24
"""Shortest overlap trusted when one title merely continues the other."""

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
        ...     Recordings.video_osgeo("foss4geurope", event="FOSS4GE 2025"),
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
        self._videos: tuple[Video, ...] | None = None

    @classmethod
    def peertube_channel(
        cls,
        channel: str,
        *,
        event: str | None = None,
        host: str = VIDEO_OSGEO,
        client: httpx.Client | None = None,
        timeout: float = 30.0,
    ) -> Recordings:
        """Recordings from a PeerTube channel.

        A channel usually spans several years of a series, so pass ``event``.

        Args:
            channel: The channel handle, e.g. ``foss4geurope``.
            event: The tag the video titles carry.
            host: The PeerTube instance, video.osgeo.org by default.
            client: An httpx client to reuse.
            timeout: Request timeout in seconds when creating a client.

        Returns:
            The configured source.
        """
        return cls(_PeerTubeChannel(channel, host.rstrip("/"), client, timeout), event=event)

    @classmethod
    def peertube_playlist(
        cls,
        playlist: str,
        *,
        event: str | None = None,
        host: str = VIDEO_OSGEO,
        client: httpx.Client | None = None,
        timeout: float = 30.0,
    ) -> Recordings:
        """Recordings from a PeerTube playlist.

        Args:
            playlist: A playlist id or any ``/w/p/<id>`` URL carrying one.
            event: Rarely needed; a playlist is already one conference.
            host: The PeerTube instance, video.osgeo.org by default.
            client: An httpx client to reuse.
            timeout: Request timeout in seconds when creating a client.

        Returns:
            The configured source.
        """
        found = _PEERTUBE_ID.search(playlist)
        identifier = found.group(1) if found else playlist
        return cls(_PeerTubePlaylist(identifier, host.rstrip("/"), client, timeout), event=event)

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

    def references_for(self, session: Session) -> Iterable[Reference]:
        """Return the session's recordings, or nothing if none can be matched."""
        tag = _normalise(self._event or "")
        wanted = _normalise(session.title)
        if not wanted:
            return []

        exact: list[Video] = []
        partial: list[Video] = []
        for video in self._catalogued():
            if tag and tag not in _normalise(video.title):
                continue
            for candidate in _titles_of(video.title):
                if candidate == wanted:
                    exact.append(video)
                    break
                if _continues(candidate, wanted):
                    partial.append(video)
                    break

        # Several exact matches are several recordings of one session and all
        # belong to it. Several inexact ones only mean the titles were too alike
        # to tell apart, which is not evidence of anything.
        found = exact if exact else (partial if len(partial) == 1 else [])
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

    def _catalogued(self) -> tuple[Video, ...]:
        """The catalogue's videos, fetched once and remembered, empty if unreachable."""
        if self._videos is None:
            try:
                self._videos = tuple(self._catalogue.videos())
            except Exception:
                _LOG.warning("could not read %s; no recordings", self._catalogue, exc_info=True)
                self._videos = ()
        return self._videos


@dataclass(frozen=True, slots=True)
class _PeerTubeChannel:
    """Every video a PeerTube channel holds."""

    channel: str
    host: str
    client: httpx.Client | None
    timeout: float

    source: ClassVar[str] = "peertube"

    def videos(self) -> Iterator[Video]:
        """List the channel."""
        url = f"{self.host}/api/v1/video-channels/{self.channel}/videos"
        for item in _peertube_items(url, self.client, self.timeout):
            yield _peertube_video(item, self.host)

    def __str__(self) -> str:
        """Name the channel, for the warning when it cannot be read."""
        return f"{self.host} channel {self.channel!r}"


@dataclass(frozen=True, slots=True)
class _PeerTubePlaylist:
    """A PeerTube playlist, which wraps each entry around its video."""

    playlist: str
    host: str
    client: httpx.Client | None
    timeout: float

    source: ClassVar[str] = "peertube"

    def videos(self) -> Iterator[Video]:
        """List the playlist."""
        url = f"{self.host}/api/v1/video-playlists/{self.playlist}/videos"
        for item in _peertube_items(url, self.client, self.timeout):
            yield _peertube_video(item.get("video") or {}, self.host)

    def __str__(self) -> str:
        """Name the playlist, for the warning when it cannot be read."""
        return f"{self.host} playlist {self.playlist!r}"


def _peertube_items(
    url: str, client: httpx.Client | None, timeout: float
) -> Iterator[dict[str, Any]]:
    """Page through a PeerTube listing until every entry has been seen."""
    owned = client or httpx.Client(timeout=timeout, follow_redirects=True)
    try:
        start = 0
        while start < _LIMIT:
            page: dict[str, Any] = (
                owned.get(url, params={"count": _PAGE, "start": start}).raise_for_status().json()
            )
            items = page.get("data") or []
            yield from items
            start += len(items)
            if not items or start >= int(page.get("total", 0)):
                return
    finally:
        if client is None:
            owned.close()


def _peertube_video(raw: dict[str, Any], host: str) -> Video:
    identifier = raw.get("shortUUID") or raw.get("uuid") or ""
    return Video(title=str(raw.get("name") or ""), url=f"{host}/videos/watch/{identifier}")


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


def _titles_of(name: str) -> tuple[str, ...]:
    """The normalised titles a video name might be.

    Entries are usually ``EVENT | Talk title``, so the part after the first bar
    is the better candidate -- but a talk title may itself contain a bar, so the
    whole name stays a candidate too.
    """
    whole = _normalise(name)
    if "|" not in name:
        return (whole,)
    return (_normalise(name.split("|", 1)[1]), whole)


def _continues(one: str, other: str) -> bool:
    """Whether one title carries on where the other stops, at a word boundary.

    Collections truncate long titles and some append the speaker's name, so a
    real match often has one title extending the other rather than equalling it.
    Normalisation has already reduced both to words separated by single spaces,
    which is what makes the boundary check a plain prefix test.
    """
    if min(len(one), len(other)) < _MIN_PREFIX:
        return False
    return one.startswith(f"{other} ") or other.startswith(f"{one} ")


def _normalise(text: str) -> str:
    """Fold case, accents and punctuation so two spellings of a title compare equal."""
    folded = unicodedata.normalize("NFKD", text)
    stripped = "".join(c for c in folded if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^0-9a-z]+", " ", stripped.lower()).split())
