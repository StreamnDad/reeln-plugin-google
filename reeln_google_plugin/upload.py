"""YouTube video upload — highlights and Shorts."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

log: logging.Logger = logging.getLogger(__name__)


class UploadError(Exception):
    """Raised when a video upload operation fails."""


def _build_video_body(
    *,
    title: str,
    description: str,
    tags: list[str] | None,
    category_id: str,
    privacy_status: str,
    made_for_kids: bool,
    recording_date: str | None,
    location: dict[str, float] | None,
) -> dict[str, Any]:
    """Build the request body for ``videos().insert()``."""
    body: dict[str, Any] = {
        "snippet": {
            "title": title,
            "description": description,
            "categoryId": category_id,
        },
        "status": {
            "privacyStatus": privacy_status,
            "selfDeclaredMadeForKids": made_for_kids,
        },
    }
    if tags:
        body["snippet"]["tags"] = tags

    if recording_date or location:
        recording_details: dict[str, Any] = {}
        if recording_date:
            recording_details["recordingDate"] = recording_date
        if location:
            recording_details["location"] = location
        body["recordingDetails"] = recording_details

    return body


def upload_video(
    youtube: Any,
    *,
    file_path: Path,
    title: str,
    description: str = "",
    tags: list[str] | None = None,
    category_id: str = "20",
    privacy_status: str = "unlisted",
    recording_date: str | None = None,
    location: dict[str, float] | None = None,
    made_for_kids: bool = False,
) -> tuple[str, str]:
    """Upload a video to YouTube.

    Args:
        youtube: YouTube API service resource.
        file_path: Path to the video file.
        title: Video title.
        description: Video description.
        tags: Video tags.
        category_id: YouTube category ID (20 = Gaming).
        privacy_status: Privacy status (public, unlisted, private).
        recording_date: ISO 8601 recording date.
        location: Recording location ``{"latitude": ..., "longitude": ...}``.
        made_for_kids: COPPA self-declaration.

    Returns:
        Tuple of ``(video_id, url)``.

    Raises:
        UploadError: If the file does not exist or the API call fails.
    """
    if not file_path.exists():
        raise UploadError(f"File not found: {file_path}")

    from googleapiclient.http import MediaFileUpload

    body = _build_video_body(
        title=title,
        description=description,
        tags=tags,
        category_id=category_id,
        privacy_status=privacy_status,
        made_for_kids=made_for_kids,
        recording_date=recording_date,
        location=location,
    )

    parts = "snippet,status"
    if "recordingDetails" in body:
        parts += ",recordingDetails"

    media = MediaFileUpload(str(file_path), chunksize=-1, resumable=True)

    try:
        response = (
            youtube.videos()
            .insert(part=parts, body=body, media_body=media)
            .execute()
        )
    except Exception as exc:
        raise UploadError(f"Upload failed: {exc}") from exc

    video_id = response.get("id")
    if not video_id:
        raise UploadError("Upload response missing video ID")

    url = f"https://youtube.com/watch?v={video_id}"
    return video_id, url


def upload_short(
    youtube: Any,
    *,
    file_path: Path,
    title: str,
    description: str = "",
    tags: list[str] | None = None,
    category_id: str = "20",
    privacy_status: str = "unlisted",
    made_for_kids: bool = False,
) -> tuple[str, str]:
    """Upload a YouTube Short.

    Appends ``#Shorts`` to the title if not already present.
    No ``recordingDetails`` are included (not relevant for Shorts).

    Args:
        youtube: YouTube API service resource.
        file_path: Path to the Short video file.
        title: Video title (``#Shorts`` appended if missing).
        description: Video description.
        tags: Video tags.
        category_id: YouTube category ID (20 = Gaming).
        privacy_status: Privacy status (public, unlisted, private).
        made_for_kids: COPPA self-declaration.

    Returns:
        Tuple of ``(video_id, url)``.

    Raises:
        UploadError: If the file does not exist or the API call fails.
    """
    if "#Shorts" not in title:
        title = f"{title} #Shorts"

    return upload_video(
        youtube,
        file_path=file_path,
        title=title,
        description=description,
        tags=tags,
        category_id=category_id,
        privacy_status=privacy_status,
        made_for_kids=made_for_kids,
    )


def set_localizations(
    youtube: Any,
    *,
    video_id: str,
    localizations: dict[str, dict[str, str]],
) -> None:
    """Apply localizations to an uploaded video.

    Localizations are set in a separate call because they are unreliable
    on the initial ``videos().insert()``.

    Args:
        youtube: YouTube API service resource.
        video_id: The YouTube video ID.
        localizations: Mapping of locale to ``{"title": ..., "description": ...}``.

    Raises:
        UploadError: If the API call fails.
    """
    try:
        youtube.videos().update(
            part="localizations",
            body={"id": video_id, "localizations": localizations},
        ).execute()
    except Exception as exc:
        raise UploadError(f"Failed to set localizations: {exc}") from exc
