"""Tests for livestream module."""

from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from googleapiclient.errors import HttpError
from httplib2 import Response

from reeln_google_plugin.livestream import (
    LivestreamError,
    create_livestream,
    create_stream,
    find_default_stream,
    get_broadcast_snippet,
    update_broadcast,
)


def _make_http_error(status: int = 400, reason: str = "Bad Request") -> HttpError:
    """Build an HttpError for testing."""
    resp = Response({"status": str(status)})
    return HttpError(resp, b"error")


class TestFindDefaultStream:
    def test_returns_first_stream_id(self, mock_youtube_service: MagicMock) -> None:
        mock_youtube_service.liveStreams().list().execute.return_value = {
            "items": [{"id": "stream-123"}]
        }

        result = find_default_stream(mock_youtube_service)
        assert result == "stream-123"

    def test_returns_none_when_no_streams(self, mock_youtube_service: MagicMock) -> None:
        mock_youtube_service.liveStreams().list().execute.return_value = {"items": []}

        result = find_default_stream(mock_youtube_service)
        assert result is None

    def test_returns_none_when_no_items_key(self, mock_youtube_service: MagicMock) -> None:
        mock_youtube_service.liveStreams().list().execute.return_value = {}

        result = find_default_stream(mock_youtube_service)
        assert result is None


class TestCreateStream:
    def test_returns_stream_id(self, mock_youtube_service: MagicMock) -> None:
        mock_youtube_service.liveStreams().insert().execute.return_value = {
            "id": "new-stream-456"
        }

        result = create_stream(mock_youtube_service)
        assert result == "new-stream-456"

    def test_raises_on_missing_id(self, mock_youtube_service: MagicMock) -> None:
        mock_youtube_service.liveStreams().insert().execute.return_value = {}

        with pytest.raises(LivestreamError, match="Failed to create live stream"):
            create_stream(mock_youtube_service)


class TestCreateLivestream:
    def test_full_flow_with_existing_stream(self, mock_youtube_service: MagicMock) -> None:
        # find_default_stream returns existing stream
        mock_youtube_service.liveStreams().list().execute.return_value = {
            "items": [{"id": "existing-stream"}]
        }
        # create broadcast
        mock_youtube_service.liveBroadcasts().insert().execute.return_value = {
            "id": "broadcast-789"
        }
        # bind (returns something)
        mock_youtube_service.liveBroadcasts().bind().execute.return_value = {}

        url = create_livestream(
            mock_youtube_service,
            title="Eagles vs Hawks - 2026-01-15",
            privacy_status="unlisted",
            scheduled_start="2026-01-15T19:00:00-05:00",
        )

        assert url == "https://youtube.com/live/broadcast-789"

    def test_creates_stream_when_none_exists(self, mock_youtube_service: MagicMock) -> None:
        # find_default_stream returns no items
        mock_youtube_service.liveStreams().list().execute.return_value = {"items": []}
        # create_stream returns new stream
        mock_youtube_service.liveStreams().insert().execute.return_value = {
            "id": "new-stream"
        }
        # create broadcast
        mock_youtube_service.liveBroadcasts().insert().execute.return_value = {
            "id": "broadcast-new"
        }
        # bind
        mock_youtube_service.liveBroadcasts().bind().execute.return_value = {}

        url = create_livestream(
            mock_youtube_service,
            title="Test Game",
        )

        assert url == "https://youtube.com/live/broadcast-new"

    def test_raises_on_broadcast_creation_failure(self, mock_youtube_service: MagicMock) -> None:
        mock_youtube_service.liveStreams().list().execute.return_value = {
            "items": [{"id": "stream-1"}]
        }
        mock_youtube_service.liveBroadcasts().insert().execute.return_value = {}

        with pytest.raises(LivestreamError, match="Failed to create livestream broadcast"):
            create_livestream(mock_youtube_service, title="Test")

    def test_thumbnail_upload_success(
        self, mock_youtube_service: MagicMock, tmp_path: Path
    ) -> None:
        thumbnail = tmp_path / "thumb.png"
        thumbnail.write_bytes(b"\x89PNG")

        mock_youtube_service.liveStreams().list().execute.return_value = {
            "items": [{"id": "s1"}]
        }
        mock_youtube_service.liveBroadcasts().insert().execute.return_value = {
            "id": "b1"
        }
        mock_youtube_service.liveBroadcasts().bind().execute.return_value = {}
        mock_youtube_service.thumbnails().set().execute.return_value = {}

        with patch("googleapiclient.http.MediaFileUpload") as mock_upload:
            mock_upload.return_value = MagicMock()
            url = create_livestream(
                mock_youtube_service,
                title="Test",
                thumbnail_path=thumbnail,
            )

        assert url == "https://youtube.com/live/b1"
        mock_upload.assert_called_once_with(str(thumbnail), mimetype="image/png")

    def test_thumbnail_upload_failure_non_fatal(
        self, mock_youtube_service: MagicMock, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        thumbnail = tmp_path / "thumb.png"
        thumbnail.write_bytes(b"\x89PNG")

        mock_youtube_service.liveStreams().list().execute.return_value = {
            "items": [{"id": "s1"}]
        }
        mock_youtube_service.liveBroadcasts().insert().execute.return_value = {
            "id": "b1"
        }
        mock_youtube_service.liveBroadcasts().bind().execute.return_value = {}

        with patch("googleapiclient.http.MediaFileUpload") as mock_upload:
            mock_upload.side_effect = Exception("upload failed")
            with caplog.at_level(logging.WARNING):
                url = create_livestream(
                    mock_youtube_service,
                    title="Test",
                    thumbnail_path=thumbnail,
                )

        assert url == "https://youtube.com/live/b1"
        assert "Thumbnail upload failed" in caplog.text

    def test_thumbnail_skipped_when_file_missing(self, mock_youtube_service: MagicMock, tmp_path: Path) -> None:
        thumbnail = tmp_path / "nonexistent.png"

        mock_youtube_service.liveStreams().list().execute.return_value = {
            "items": [{"id": "s1"}]
        }
        mock_youtube_service.liveBroadcasts().insert().execute.return_value = {
            "id": "b1"
        }
        mock_youtube_service.liveBroadcasts().bind().execute.return_value = {}

        url = create_livestream(
            mock_youtube_service,
            title="Test",
            thumbnail_path=thumbnail,
        )

        assert url == "https://youtube.com/live/b1"
        mock_youtube_service.thumbnails().set.assert_not_called()

    def test_thumbnail_skipped_when_none(self, mock_youtube_service: MagicMock) -> None:
        mock_youtube_service.liveStreams().list().execute.return_value = {
            "items": [{"id": "s1"}]
        }
        mock_youtube_service.liveBroadcasts().insert().execute.return_value = {
            "id": "b1"
        }
        mock_youtube_service.liveBroadcasts().bind().execute.return_value = {}

        url = create_livestream(
            mock_youtube_service,
            title="Test",
            thumbnail_path=None,
        )

        assert url == "https://youtube.com/live/b1"

    def test_default_scheduled_start(self, mock_youtube_service: MagicMock) -> None:
        mock_youtube_service.liveStreams().list().execute.return_value = {
            "items": [{"id": "s1"}]
        }
        mock_youtube_service.liveBroadcasts().insert().execute.return_value = {
            "id": "b1"
        }
        mock_youtube_service.liveBroadcasts().bind().execute.return_value = {}

        url = create_livestream(mock_youtube_service, title="Test")
        assert url == "https://youtube.com/live/b1"

    def test_description_passed_through(self, mock_youtube_service: MagicMock) -> None:
        mock_youtube_service.liveStreams().list().execute.return_value = {
            "items": [{"id": "s1"}]
        }
        mock_youtube_service.liveBroadcasts().insert().execute.return_value = {
            "id": "b1"
        }
        mock_youtube_service.liveBroadcasts().bind().execute.return_value = {}

        create_livestream(
            mock_youtube_service,
            title="Test",
            description="A test description",
        )

        mock_youtube_service.liveBroadcasts().insert.assert_called()


class TestHttpErrorWrapping:
    def test_find_default_stream_http_error(self, mock_youtube_service: MagicMock) -> None:
        mock_youtube_service.liveStreams().list().execute.side_effect = _make_http_error()

        with pytest.raises(LivestreamError, match="Failed to list live streams"):
            find_default_stream(mock_youtube_service)

    def test_create_stream_http_error(self, mock_youtube_service: MagicMock) -> None:
        mock_youtube_service.liveStreams().insert().execute.side_effect = _make_http_error()

        with pytest.raises(LivestreamError, match="Failed to create live stream"):
            create_stream(mock_youtube_service)

    def test_create_livestream_broadcast_http_error(self, mock_youtube_service: MagicMock) -> None:
        mock_youtube_service.liveStreams().list().execute.return_value = {
            "items": [{"id": "s1"}]
        }
        mock_youtube_service.liveBroadcasts().insert().execute.side_effect = _make_http_error()

        with pytest.raises(LivestreamError, match="Failed to create broadcast"):
            create_livestream(mock_youtube_service, title="Test")

    def test_create_livestream_bind_http_error(self, mock_youtube_service: MagicMock) -> None:
        mock_youtube_service.liveStreams().list().execute.return_value = {
            "items": [{"id": "s1"}]
        }
        mock_youtube_service.liveBroadcasts().insert().execute.return_value = {
            "id": "b1"
        }
        mock_youtube_service.liveBroadcasts().bind().execute.side_effect = _make_http_error()

        with pytest.raises(LivestreamError, match="Failed to bind broadcast"):
            create_livestream(mock_youtube_service, title="Test")


class TestGetBroadcastSnippet:
    def test_returns_snippet(self, mock_youtube_service: MagicMock) -> None:
        item = {"id": "b1", "snippet": {"title": "Title", "description": "Desc"}}
        mock_youtube_service.liveBroadcasts().list().execute.return_value = {
            "items": [item]
        }

        result = get_broadcast_snippet(mock_youtube_service, "b1")
        assert result == item

    def test_not_found_raises(self, mock_youtube_service: MagicMock) -> None:
        mock_youtube_service.liveBroadcasts().list().execute.return_value = {"items": []}

        with pytest.raises(LivestreamError, match="not found"):
            get_broadcast_snippet(mock_youtube_service, "b1")

    def test_http_error_raises(self, mock_youtube_service: MagicMock) -> None:
        mock_youtube_service.liveBroadcasts().list().execute.side_effect = _make_http_error()

        with pytest.raises(LivestreamError, match="Failed to fetch broadcast"):
            get_broadcast_snippet(mock_youtube_service, "b1")


class TestUpdateBroadcast:
    def _setup_list(self, mock_youtube_service: MagicMock) -> None:
        """Set up the liveBroadcasts().list() response with a valid snippet."""
        mock_youtube_service.liveBroadcasts().list().execute.return_value = {
            "items": [
                {
                    "id": "b1",
                    "snippet": {
                        "title": "Old Title",
                        "scheduledStartTime": "2026-01-15T19:00:00Z",
                    },
                }
            ]
        }

    def test_updates_title_and_description(self, mock_youtube_service: MagicMock) -> None:
        self._setup_list(mock_youtube_service)
        mock_youtube_service.liveBroadcasts().update().execute.return_value = {}

        update_broadcast(
            mock_youtube_service,
            broadcast_id="b1",
            title="New Title",
            description="New Desc",
        )

        mock_youtube_service.liveBroadcasts().update.assert_called_with(
            part="snippet",
            body={
                "id": "b1",
                "snippet": {
                    "title": "New Title",
                    "description": "New Desc",
                    "scheduledStartTime": "2026-01-15T19:00:00Z",
                },
            },
        )

    def test_updates_with_localizations(self, mock_youtube_service: MagicMock) -> None:
        self._setup_list(mock_youtube_service)
        mock_youtube_service.liveBroadcasts().update().execute.return_value = {}

        localizations = {"es": {"title": "Titulo", "description": "Desc ES"}}

        update_broadcast(
            mock_youtube_service,
            broadcast_id="b1",
            title="New Title",
            description="New Desc",
            localizations=localizations,
        )

        mock_youtube_service.liveBroadcasts().update.assert_called_with(
            part="snippet,localizations",
            body={
                "id": "b1",
                "snippet": {
                    "title": "New Title",
                    "description": "New Desc",
                    "scheduledStartTime": "2026-01-15T19:00:00Z",
                    "defaultLanguage": "en",
                },
                "localizations": localizations,
            },
        )

    def test_updates_with_thumbnail(
        self, mock_youtube_service: MagicMock, tmp_path: Path
    ) -> None:
        self._setup_list(mock_youtube_service)
        mock_youtube_service.liveBroadcasts().update().execute.return_value = {}
        mock_youtube_service.thumbnails().set().execute.return_value = {}

        thumbnail = tmp_path / "thumb.png"
        thumbnail.write_bytes(b"\x89PNG")

        with patch("googleapiclient.http.MediaFileUpload") as mock_upload:
            mock_upload.return_value = MagicMock()
            update_broadcast(
                mock_youtube_service,
                broadcast_id="b1",
                title="New Title",
                thumbnail_path=thumbnail,
            )

        mock_upload.assert_called_once_with(str(thumbnail), mimetype="image/png")

    def test_thumbnail_missing_skipped(
        self, mock_youtube_service: MagicMock, tmp_path: Path
    ) -> None:
        self._setup_list(mock_youtube_service)
        mock_youtube_service.liveBroadcasts().update().execute.return_value = {}

        nonexistent = tmp_path / "missing.png"

        update_broadcast(
            mock_youtube_service,
            broadcast_id="b1",
            title="New Title",
            thumbnail_path=nonexistent,
        )

        mock_youtube_service.thumbnails().set.assert_not_called()

    def test_http_error_raises_livestream_error(self, mock_youtube_service: MagicMock) -> None:
        self._setup_list(mock_youtube_service)
        mock_youtube_service.liveBroadcasts().update().execute.side_effect = _make_http_error()

        with pytest.raises(LivestreamError, match="Failed to update broadcast"):
            update_broadcast(
                mock_youtube_service,
                broadcast_id="b1",
                title="New Title",
            )

    def test_list_http_error(self, mock_youtube_service: MagicMock) -> None:
        mock_youtube_service.liveBroadcasts().list().execute.side_effect = _make_http_error()

        with pytest.raises(LivestreamError, match="Failed to fetch broadcast"):
            update_broadcast(
                mock_youtube_service,
                broadcast_id="b1",
                title="New Title",
            )

    def test_broadcast_not_found_raises(self, mock_youtube_service: MagicMock) -> None:
        mock_youtube_service.liveBroadcasts().list().execute.return_value = {"items": []}

        with pytest.raises(LivestreamError, match="not found"):
            update_broadcast(
                mock_youtube_service,
                broadcast_id="b1",
                title="New Title",
            )

    def test_no_scheduled_start_time(self, mock_youtube_service: MagicMock) -> None:
        """When existing snippet has no scheduledStartTime, it's omitted from update."""
        mock_youtube_service.liveBroadcasts().list().execute.return_value = {
            "items": [{"id": "b1", "snippet": {"title": "Old"}}]
        }
        mock_youtube_service.liveBroadcasts().update().execute.return_value = {}

        update_broadcast(
            mock_youtube_service,
            broadcast_id="b1",
            title="New Title",
        )

        call_body = mock_youtube_service.liveBroadcasts().update.call_args[1]["body"]
        assert "scheduledStartTime" not in call_body["snippet"]

    def test_thumbnail_upload_failure_non_fatal(
        self, mock_youtube_service: MagicMock, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        self._setup_list(mock_youtube_service)
        mock_youtube_service.liveBroadcasts().update().execute.return_value = {}

        thumbnail = tmp_path / "thumb.png"
        thumbnail.write_bytes(b"\x89PNG")

        with patch("googleapiclient.http.MediaFileUpload") as mock_upload:
            mock_upload.side_effect = Exception("upload failed")
            with caplog.at_level(logging.WARNING):
                update_broadcast(
                    mock_youtube_service,
                    broadcast_id="b1",
                    title="New Title",
                    thumbnail_path=thumbnail,
                )

        assert "Thumbnail upload failed" in caplog.text
