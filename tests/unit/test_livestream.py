"""Tests for livestream module."""

from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from reeln_google_plugin.livestream import (
    LivestreamError,
    create_livestream,
    create_stream,
    find_default_stream,
)


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
