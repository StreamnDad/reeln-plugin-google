"""YouTube livestream creation and stream management."""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from googleapiclient.errors import HttpError

log: logging.Logger = logging.getLogger(__name__)


class LivestreamError(Exception):
    """Raised when a livestream operation fails."""


def find_default_stream(youtube: Any) -> str | None:
    """Find the user's existing live stream (e.g. the one OBS uses).

    Returns the first stream's ID, or None if no streams exist.
    """
    request = youtube.liveStreams().list(part="id,snippet,cdn", mine=True, maxResults=10)
    try:
        response = request.execute()
    except HttpError as exc:
        raise LivestreamError(f"Failed to list live streams: {exc}") from exc
    items = response.get("items", [])
    if items:
        return items[0]["id"]  # type: ignore[no-any-return]
    return None


def create_stream(youtube: Any) -> str:
    """Create a default RTMP live stream.

    Returns the new stream ID.

    Raises:
        LivestreamError: If stream creation fails.
    """
    try:
        response = (
            youtube.liveStreams()
            .insert(
                part="snippet,cdn",
                body={
                    "snippet": {"title": "Default Stream"},
                    "cdn": {
                        "frameRate": "variable",
                        "ingestionType": "rtmp",
                        "resolution": "variable",
                    },
                },
            )
            .execute()
        )
    except HttpError as exc:
        raise LivestreamError(f"Failed to create live stream: {exc}") from exc
    stream_id = response.get("id")
    if not stream_id:
        raise LivestreamError("Failed to create live stream")
    return stream_id  # type: ignore[no-any-return]


def create_livestream(
    youtube: Any,
    *,
    title: str,
    description: str = "",
    privacy_status: str = "unlisted",
    scheduled_start: str | None = None,
    thumbnail_path: Path | None = None,
) -> str:
    """Create a YouTube livestream broadcast and bind it to a stream.

    Full workflow: find/create stream, create broadcast with autoStart/autoStop,
    bind stream to broadcast, optionally set thumbnail.

    Args:
        youtube: YouTube API service resource.
        title: Broadcast title.
        description: Broadcast description.
        privacy_status: Privacy status (public, unlisted, private).
        scheduled_start: ISO 8601 datetime for broadcast start. Defaults to now.
        thumbnail_path: Optional path to thumbnail image.

    Returns:
        Livestream URL (https://youtube.com/live/{broadcast_id}).

    Raises:
        LivestreamError: If broadcast creation or binding fails.
    """
    # Find or create stream
    stream_id = find_default_stream(youtube)
    if not stream_id:
        stream_id = create_stream(youtube)

    # Create broadcast
    start_time = scheduled_start or datetime.now().astimezone().isoformat()
    try:
        broadcast_response = (
            youtube.liveBroadcasts()
            .insert(
                part="snippet,contentDetails,status",
                body={
                    "snippet": {
                        "title": title,
                        "description": description,
                        "scheduledStartTime": start_time,
                    },
                    "contentDetails": {
                        "enableAutoStart": True,
                        "enableAutoStop": True,
                    },
                    "status": {
                        "privacyStatus": privacy_status,
                    },
                },
            )
            .execute()
        )
    except HttpError as exc:
        raise LivestreamError(f"Failed to create broadcast: {exc}") from exc
    broadcast_id = broadcast_response.get("id")
    if not broadcast_id:
        raise LivestreamError("Failed to create livestream broadcast")

    # Bind broadcast to stream
    try:
        youtube.liveBroadcasts().bind(
            id=broadcast_id, part="id,contentDetails", streamId=stream_id
        ).execute()
    except HttpError as exc:
        raise LivestreamError(f"Failed to bind broadcast to stream: {exc}") from exc

    # Set thumbnail (non-fatal)
    if thumbnail_path and thumbnail_path.exists():
        try:
            from googleapiclient.http import MediaFileUpload

            media = MediaFileUpload(str(thumbnail_path), mimetype="image/png")
            youtube.thumbnails().set(
                videoId=broadcast_id, media_body=media
            ).execute()
        except Exception as exc:
            log.warning("Thumbnail upload failed (non-fatal): %s", exc)

    return f"https://youtube.com/live/{broadcast_id}"


def update_broadcast(
    youtube: Any,
    *,
    broadcast_id: str,
    title: str,
    description: str = "",
    thumbnail_path: Path | None = None,
    localizations: dict[str, dict[str, str]] | None = None,
) -> None:
    """Update an existing YouTube livestream broadcast's metadata.

    Fetches the current snippet (to preserve ``scheduledStartTime``), then
    updates with the new title, description, and optional localizations.
    Optionally sets a thumbnail image.

    Args:
        youtube: YouTube API service resource.
        broadcast_id: ID of the broadcast to update.
        title: New broadcast title.
        description: New broadcast description.
        thumbnail_path: Optional path to thumbnail image.
        localizations: Optional ``{lang: {"title": ..., "description": ...}}`` dict.

    Raises:
        LivestreamError: If the API call fails.
    """
    # Fetch existing snippet to preserve scheduledStartTime
    try:
        list_response = (
            youtube.liveBroadcasts()
            .list(id=broadcast_id, part="snippet")
            .execute()
        )
    except HttpError as exc:
        raise LivestreamError(f"Failed to fetch broadcast {broadcast_id}: {exc}") from exc

    items = list_response.get("items", [])
    if not items:
        raise LivestreamError(f"Broadcast {broadcast_id} not found")

    existing_snippet = items[0].get("snippet", {})
    scheduled_start = existing_snippet.get("scheduledStartTime")

    snippet: dict[str, Any] = {
        "title": title,
        "description": description,
    }
    if scheduled_start:
        snippet["scheduledStartTime"] = scheduled_start

    parts = ["snippet"]
    body: dict[str, Any] = {"id": broadcast_id, "snippet": snippet}

    if localizations:
        parts.append("localizations")
        snippet["defaultLanguage"] = "en"
        body["localizations"] = localizations

    try:
        youtube.liveBroadcasts().update(
            part=",".join(parts),
            body=body,
        ).execute()
    except HttpError as exc:
        raise LivestreamError(f"Failed to update broadcast {broadcast_id}: {exc}") from exc

    # Set thumbnail (non-fatal)
    if thumbnail_path and thumbnail_path.exists():
        try:
            from googleapiclient.http import MediaFileUpload

            media = MediaFileUpload(str(thumbnail_path), mimetype="image/png")
            youtube.thumbnails().set(
                videoId=broadcast_id, media_body=media
            ).execute()
        except Exception as exc:
            log.warning("Thumbnail upload failed (non-fatal): %s", exc)
