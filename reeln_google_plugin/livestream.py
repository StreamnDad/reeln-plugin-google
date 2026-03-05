"""YouTube livestream creation and stream management."""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any

log: logging.Logger = logging.getLogger(__name__)


class LivestreamError(Exception):
    """Raised when a livestream operation fails."""


def find_default_stream(youtube: Any) -> str | None:
    """Find the user's existing live stream (e.g. the one OBS uses).

    Returns the first stream's ID, or None if no streams exist.
    """
    request = youtube.liveStreams().list(part="id,snippet,cdn", mine=True, maxResults=10)
    response = request.execute()
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
    broadcast_id = broadcast_response.get("id")
    if not broadcast_id:
        raise LivestreamError("Failed to create livestream broadcast")

    # Bind broadcast to stream
    youtube.liveBroadcasts().bind(
        id=broadcast_id, part="id,contentDetails", streamId=stream_id
    ).execute()

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
