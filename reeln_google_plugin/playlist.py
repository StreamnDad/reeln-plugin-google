"""YouTube playlist management — find, create, and populate playlists."""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import parse_qs, urlparse

from googleapiclient.errors import HttpError

log: logging.Logger = logging.getLogger(__name__)


class PlaylistError(Exception):
    """Raised when a playlist operation fails."""


def extract_video_id(url: str) -> str:
    """Extract video ID from a YouTube URL.

    Supports ``/live/{id}`` and ``watch?v={id}`` formats.

    Raises:
        PlaylistError: If the URL format is not recognised.
    """
    if not url:
        raise PlaylistError("Empty URL")

    parsed = urlparse(url)

    # /live/{id} format
    if parsed.path.startswith("/live/"):
        video_id = parsed.path.split("/live/", 1)[1].split("/")[0]
        if video_id:
            return video_id

    # watch?v={id} format
    qs = parse_qs(parsed.query)
    if "v" in qs and qs["v"][0]:
        return qs["v"][0]

    raise PlaylistError(f"Could not extract video ID from URL: {url}")


def find_playlist_by_title(youtube: Any, *, title: str) -> str | None:
    """Find a playlist by title (case-insensitive) among the user's playlists.

    Returns the playlist ID if found, or ``None``.
    """
    request = youtube.playlists().list(part="snippet", mine=True, maxResults=50)
    while request is not None:
        try:
            response = request.execute()
        except HttpError as exc:
            raise PlaylistError(f"Failed to list playlists: {exc}") from exc
        for item in response.get("items", []):
            snippet = item.get("snippet", {})
            if snippet.get("title", "").lower() == title.lower():
                return item["id"]  # type: ignore[no-any-return]
        request = youtube.playlists().list_next(request, response)
    return None


def create_playlist(
    youtube: Any,
    *,
    title: str,
    description: str = "",
    privacy_status: str = "unlisted",
) -> str:
    """Create a new YouTube playlist.

    Returns the new playlist ID.

    Raises:
        PlaylistError: If playlist creation fails.
    """
    try:
        response = (
            youtube.playlists()
            .insert(
                part="snippet,status",
                body={
                    "snippet": {"title": title, "description": description},
                    "status": {"privacyStatus": privacy_status},
                },
            )
            .execute()
        )
    except HttpError as exc:
        raise PlaylistError(f"Failed to create playlist: {exc}") from exc
    playlist_id = response.get("id")
    if not playlist_id:
        raise PlaylistError("Failed to create playlist")
    return playlist_id  # type: ignore[no-any-return]


def ensure_playlist(
    youtube: Any,
    *,
    title: str,
    description: str = "",
    privacy_status: str = "unlisted",
) -> tuple[str, bool]:
    """Find an existing playlist by title, or create a new one.

    Returns:
        A tuple of ``(playlist_id, created)`` where *created* is ``True``
        if a new playlist was created.
    """
    existing = find_playlist_by_title(youtube, title=title)
    if existing is not None:
        return existing, False
    new_id = create_playlist(
        youtube, title=title, description=description, privacy_status=privacy_status
    )
    return new_id, True


def playlist_has_video(youtube: Any, *, playlist_id: str, video_id: str) -> bool:
    """Check whether a video is already in a playlist."""
    request = youtube.playlistItems().list(
        part="contentDetails", playlistId=playlist_id, maxResults=50
    )
    while request is not None:
        try:
            response = request.execute()
        except HttpError as exc:
            raise PlaylistError(f"Failed to list playlist items: {exc}") from exc
        for item in response.get("items", []):
            content = item.get("contentDetails", {})
            if content.get("videoId") == video_id:
                return True
        request = youtube.playlistItems().list_next(request, response)
    return False


def insert_video_into_playlist(
    youtube: Any,
    *,
    playlist_id: str,
    video_id: str,
    skip_dedup: bool = False,
) -> None:
    """Add a video to a playlist (skips if already present).

    Args:
        youtube: YouTube API service resource.
        playlist_id: Target playlist ID.
        video_id: Video ID to insert.
        skip_dedup: Skip the duplicate check (use when the playlist was just created).

    Raises:
        PlaylistError: If the insert API call fails.
    """
    if not skip_dedup and playlist_has_video(
        youtube, playlist_id=playlist_id, video_id=video_id
    ):
        log.info("Video %s already in playlist %s, skipping", video_id, playlist_id)
        return

    try:
        response = (
            youtube.playlistItems()
            .insert(
                part="snippet",
                body={
                    "snippet": {
                        "playlistId": playlist_id,
                        "resourceId": {
                            "kind": "youtube#video",
                            "videoId": video_id,
                        },
                    }
                },
            )
            .execute()
        )
    except HttpError as exc:
        raise PlaylistError(
            f"Failed to insert video {video_id} into playlist {playlist_id}: {exc}"
        ) from exc
    if not response.get("id"):
        raise PlaylistError(
            f"Failed to insert video {video_id} into playlist {playlist_id}"
        )


def update_playlist(
    youtube: Any,
    *,
    playlist_id: str,
    title: str,
    description: str = "",
    localizations: dict[str, dict[str, str]] | None = None,
) -> None:
    """Update an existing YouTube playlist's metadata.

    Args:
        youtube: YouTube API service resource.
        playlist_id: ID of the playlist to update.
        title: New playlist title.
        description: New playlist description.
        localizations: Optional ``{lang: {"title": ..., "description": ...}}`` dict.

    Raises:
        PlaylistError: If the API call fails.
    """
    snippet: dict[str, Any] = {"title": title, "description": description}
    parts = ["snippet"]
    body: dict[str, Any] = {"id": playlist_id, "snippet": snippet}

    if localizations:
        parts.append("localizations")
        snippet["defaultLanguage"] = "en"
        body["localizations"] = localizations

    try:
        youtube.playlists().update(
            part=",".join(parts),
            body=body,
        ).execute()
    except HttpError as exc:
        raise PlaylistError(
            f"Failed to update playlist {playlist_id}: {exc}"
        ) from exc


def setup_playlist(
    youtube: Any,
    *,
    title: str,
    description: str = "",
    privacy_status: str = "unlisted",
    video_id: str | None = None,
) -> str:
    """Orchestrate playlist creation and optional video insertion.

    Returns the playlist ID.

    Raises:
        PlaylistError: If playlist creation or video insertion fails.
    """
    playlist_id, created = ensure_playlist(
        youtube, title=title, description=description, privacy_status=privacy_status
    )
    action = "Created" if created else "Found existing"
    log.info("%s playlist '%s' (%s)", action, title, playlist_id)

    if video_id is not None:
        insert_video_into_playlist(
            youtube,
            playlist_id=playlist_id,
            video_id=video_id,
            skip_dedup=created,
        )

    return playlist_id
