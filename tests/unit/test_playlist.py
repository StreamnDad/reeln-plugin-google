"""Tests for playlist module."""

from __future__ import annotations

import logging
from unittest.mock import MagicMock

import pytest
from googleapiclient.errors import HttpError
from httplib2 import Response

from reeln_google_plugin.playlist import (
    PlaylistError,
    create_playlist,
    ensure_playlist,
    extract_video_id,
    find_playlist_by_title,
    insert_video_into_playlist,
    playlist_has_video,
    setup_playlist,
    update_playlist,
)


class TestExtractVideoId:
    def test_live_url(self) -> None:
        assert extract_video_id("https://youtube.com/live/abc123") == "abc123"

    def test_www_live_url(self) -> None:
        assert extract_video_id("https://www.youtube.com/live/def456") == "def456"

    def test_watch_url(self) -> None:
        assert extract_video_id("https://www.youtube.com/watch?v=xyz789") == "xyz789"

    def test_invalid_url_raises(self) -> None:
        with pytest.raises(PlaylistError, match="Could not extract video ID"):
            extract_video_id("https://youtube.com/channel/123")

    def test_empty_url_raises(self) -> None:
        with pytest.raises(PlaylistError, match="Empty URL"):
            extract_video_id("")

    def test_live_url_with_trailing_slash(self) -> None:
        assert extract_video_id("https://youtube.com/live/abc123/") == "abc123"

    def test_live_path_empty_id_raises(self) -> None:
        with pytest.raises(PlaylistError, match="Could not extract video ID"):
            extract_video_id("https://youtube.com/live/")


class TestFindPlaylistByTitle:
    def test_found(self, mock_youtube_service: MagicMock) -> None:
        mock_youtube_service.playlists().list().execute.return_value = {
            "items": [{"id": "PL001", "snippet": {"title": "My Playlist"}}]
        }
        mock_youtube_service.playlists().list_next.return_value = None

        result = find_playlist_by_title(mock_youtube_service, title="My Playlist")
        assert result == "PL001"

    def test_case_insensitive(self, mock_youtube_service: MagicMock) -> None:
        mock_youtube_service.playlists().list().execute.return_value = {
            "items": [{"id": "PL002", "snippet": {"title": "Eagles vs Hawks - 2026-01-15"}}]
        }
        mock_youtube_service.playlists().list_next.return_value = None

        result = find_playlist_by_title(
            mock_youtube_service, title="eagles vs hawks - 2026-01-15"
        )
        assert result == "PL002"

    def test_not_found(self, mock_youtube_service: MagicMock) -> None:
        mock_youtube_service.playlists().list().execute.return_value = {
            "items": [{"id": "PL003", "snippet": {"title": "Other"}}]
        }
        mock_youtube_service.playlists().list_next.return_value = None

        result = find_playlist_by_title(mock_youtube_service, title="Nonexistent")
        assert result is None

    def test_empty_items(self, mock_youtube_service: MagicMock) -> None:
        mock_youtube_service.playlists().list().execute.return_value = {"items": []}
        mock_youtube_service.playlists().list_next.return_value = None

        result = find_playlist_by_title(mock_youtube_service, title="Any")
        assert result is None

    def test_pagination(self, mock_youtube_service: MagicMock) -> None:
        # First page: no match
        first_request = MagicMock()
        first_response = {
            "items": [{"id": "PL-A", "snippet": {"title": "Other"}}]
        }
        first_request.execute.return_value = first_response
        mock_youtube_service.playlists().list.return_value = first_request

        # Second page: match
        second_request = MagicMock()
        second_response = {
            "items": [{"id": "PL-B", "snippet": {"title": "Target"}}]
        }
        second_request.execute.return_value = second_response

        mock_youtube_service.playlists().list_next.side_effect = [
            second_request,
            None,
        ]

        result = find_playlist_by_title(mock_youtube_service, title="Target")
        assert result == "PL-B"

    def test_missing_items_key(self, mock_youtube_service: MagicMock) -> None:
        mock_youtube_service.playlists().list().execute.return_value = {}
        mock_youtube_service.playlists().list_next.return_value = None

        result = find_playlist_by_title(mock_youtube_service, title="Any")
        assert result is None


class TestCreatePlaylist:
    def test_returns_id(self, mock_youtube_service: MagicMock) -> None:
        mock_youtube_service.playlists().insert().execute.return_value = {
            "id": "PL-NEW"
        }
        result = create_playlist(mock_youtube_service, title="New Playlist")
        assert result == "PL-NEW"

    def test_raises_on_missing_id(self, mock_youtube_service: MagicMock) -> None:
        mock_youtube_service.playlists().insert().execute.return_value = {}

        with pytest.raises(PlaylistError, match="Failed to create playlist"):
            create_playlist(mock_youtube_service, title="Bad")

    def test_passes_body_params(self, mock_youtube_service: MagicMock) -> None:
        mock_youtube_service.playlists().insert().execute.return_value = {"id": "PL-X"}

        create_playlist(
            mock_youtube_service,
            title="Test",
            description="Desc",
            privacy_status="public",
        )

        mock_youtube_service.playlists().insert.assert_called_with(
            part="snippet,status",
            body={
                "snippet": {"title": "Test", "description": "Desc"},
                "status": {"privacyStatus": "public"},
            },
        )


class TestEnsurePlaylist:
    def test_finds_existing(self, mock_youtube_service: MagicMock) -> None:
        mock_youtube_service.playlists().list().execute.return_value = {
            "items": [{"id": "PL-EXIST", "snippet": {"title": "Game"}}]
        }
        mock_youtube_service.playlists().list_next.return_value = None

        pid, created = ensure_playlist(mock_youtube_service, title="Game")
        assert pid == "PL-EXIST"
        assert created is False

    def test_creates_new(self, mock_youtube_service: MagicMock) -> None:
        mock_youtube_service.playlists().list().execute.return_value = {"items": []}
        mock_youtube_service.playlists().list_next.return_value = None
        mock_youtube_service.playlists().insert().execute.return_value = {
            "id": "PL-CREATED"
        }

        pid, created = ensure_playlist(mock_youtube_service, title="New Game")
        assert pid == "PL-CREATED"
        assert created is True


class TestPlaylistHasVideo:
    def test_present(self, mock_youtube_service: MagicMock) -> None:
        mock_youtube_service.playlistItems().list().execute.return_value = {
            "items": [{"contentDetails": {"videoId": "vid-1"}}]
        }
        mock_youtube_service.playlistItems().list_next.return_value = None

        assert playlist_has_video(
            mock_youtube_service, playlist_id="PL-1", video_id="vid-1"
        ) is True

    def test_not_present(self, mock_youtube_service: MagicMock) -> None:
        mock_youtube_service.playlistItems().list().execute.return_value = {
            "items": [{"contentDetails": {"videoId": "vid-2"}}]
        }
        mock_youtube_service.playlistItems().list_next.return_value = None

        assert playlist_has_video(
            mock_youtube_service, playlist_id="PL-1", video_id="vid-1"
        ) is False

    def test_empty_playlist(self, mock_youtube_service: MagicMock) -> None:
        mock_youtube_service.playlistItems().list().execute.return_value = {
            "items": []
        }
        mock_youtube_service.playlistItems().list_next.return_value = None

        assert playlist_has_video(
            mock_youtube_service, playlist_id="PL-1", video_id="vid-1"
        ) is False

    def test_pagination(self, mock_youtube_service: MagicMock) -> None:
        first_request = MagicMock()
        first_response = {"items": [{"contentDetails": {"videoId": "vid-other"}}]}
        first_request.execute.return_value = first_response
        mock_youtube_service.playlistItems().list.return_value = first_request

        second_request = MagicMock()
        second_response = {"items": [{"contentDetails": {"videoId": "vid-target"}}]}
        second_request.execute.return_value = second_response

        mock_youtube_service.playlistItems().list_next.side_effect = [
            second_request,
            None,
        ]

        assert playlist_has_video(
            mock_youtube_service, playlist_id="PL-1", video_id="vid-target"
        ) is True


class TestInsertVideoIntoPlaylist:
    def test_inserts(self, mock_youtube_service: MagicMock) -> None:
        # Not already present
        mock_youtube_service.playlistItems().list().execute.return_value = {
            "items": []
        }
        mock_youtube_service.playlistItems().list_next.return_value = None
        # Insert succeeds
        mock_youtube_service.playlistItems().insert().execute.return_value = {
            "id": "PLI-1"
        }

        insert_video_into_playlist(
            mock_youtube_service, playlist_id="PL-1", video_id="vid-1"
        )

        mock_youtube_service.playlistItems().insert.assert_called_with(
            part="snippet",
            body={
                "snippet": {
                    "playlistId": "PL-1",
                    "resourceId": {
                        "kind": "youtube#video",
                        "videoId": "vid-1",
                    },
                }
            },
        )

    def test_skips_duplicate(
        self, mock_youtube_service: MagicMock, caplog: pytest.LogCaptureFixture
    ) -> None:
        mock_youtube_service.playlistItems().list().execute.return_value = {
            "items": [{"contentDetails": {"videoId": "vid-1"}}]
        }
        mock_youtube_service.playlistItems().list_next.return_value = None

        with caplog.at_level(logging.INFO):
            insert_video_into_playlist(
                mock_youtube_service, playlist_id="PL-1", video_id="vid-1"
            )

        assert "already in playlist" in caplog.text

    def test_raises_on_failure(self, mock_youtube_service: MagicMock) -> None:
        mock_youtube_service.playlistItems().list().execute.return_value = {
            "items": []
        }
        mock_youtube_service.playlistItems().list_next.return_value = None
        mock_youtube_service.playlistItems().insert().execute.return_value = {}

        with pytest.raises(PlaylistError, match="Failed to insert video"):
            insert_video_into_playlist(
                mock_youtube_service, playlist_id="PL-1", video_id="vid-1"
            )

    def test_skip_dedup_skips_has_video_check(self, mock_youtube_service: MagicMock) -> None:
        mock_youtube_service.playlistItems().insert().execute.return_value = {
            "id": "PLI-1"
        }

        insert_video_into_playlist(
            mock_youtube_service, playlist_id="PL-1", video_id="vid-1", skip_dedup=True
        )

        # list should NOT be called when skip_dedup=True
        mock_youtube_service.playlistItems().list.assert_not_called()

    def test_skip_dedup_false_checks_has_video(self, mock_youtube_service: MagicMock) -> None:
        mock_youtube_service.playlistItems().list().execute.return_value = {"items": []}
        mock_youtube_service.playlistItems().list_next.return_value = None
        mock_youtube_service.playlistItems().insert().execute.return_value = {
            "id": "PLI-1"
        }

        insert_video_into_playlist(
            mock_youtube_service, playlist_id="PL-1", video_id="vid-1", skip_dedup=False
        )

        mock_youtube_service.playlistItems().list.assert_called()


class TestSetupPlaylist:
    def test_create_and_add_video(self, mock_youtube_service: MagicMock) -> None:
        # ensure_playlist: not found → create
        mock_youtube_service.playlists().list().execute.return_value = {"items": []}
        mock_youtube_service.playlists().list_next.return_value = None
        mock_youtube_service.playlists().insert().execute.return_value = {
            "id": "PL-NEW"
        }
        # insert_video: skip_dedup=True (created=True), so no list call
        mock_youtube_service.playlistItems().insert().execute.return_value = {
            "id": "PLI-1"
        }

        result = setup_playlist(
            mock_youtube_service, title="Game", video_id="vid-1"
        )
        assert result == "PL-NEW"
        # Dedup check skipped for newly created playlists
        mock_youtube_service.playlistItems().list.assert_not_called()

    def test_existing_playlist(self, mock_youtube_service: MagicMock) -> None:
        mock_youtube_service.playlists().list().execute.return_value = {
            "items": [{"id": "PL-EXIST", "snippet": {"title": "Game"}}]
        }
        mock_youtube_service.playlists().list_next.return_value = None

        result = setup_playlist(mock_youtube_service, title="Game")
        assert result == "PL-EXIST"

    def test_no_video_id(self, mock_youtube_service: MagicMock) -> None:
        mock_youtube_service.playlists().list().execute.return_value = {"items": []}
        mock_youtube_service.playlists().list_next.return_value = None
        mock_youtube_service.playlists().insert().execute.return_value = {
            "id": "PL-SOLO"
        }

        result = setup_playlist(mock_youtube_service, title="Solo")
        assert result == "PL-SOLO"
        # playlistItems().insert should not be called
        mock_youtube_service.playlistItems().insert.assert_not_called()

    def test_existing_playlist_with_video_checks_dedup(
        self, mock_youtube_service: MagicMock
    ) -> None:
        # ensure_playlist: found existing
        mock_youtube_service.playlists().list().execute.return_value = {
            "items": [{"id": "PL-EXIST", "snippet": {"title": "Game"}}]
        }
        mock_youtube_service.playlists().list_next.return_value = None
        # playlist_has_video check (dedup not skipped for existing playlists)
        mock_youtube_service.playlistItems().list().execute.return_value = {"items": []}
        mock_youtube_service.playlistItems().list_next.return_value = None
        mock_youtube_service.playlistItems().insert().execute.return_value = {
            "id": "PLI-1"
        }

        result = setup_playlist(
            mock_youtube_service, title="Game", video_id="vid-1"
        )
        assert result == "PL-EXIST"
        # Dedup check runs for existing playlists
        mock_youtube_service.playlistItems().list.assert_called()

    def test_error_propagation(self, mock_youtube_service: MagicMock) -> None:
        mock_youtube_service.playlists().list().execute.return_value = {"items": []}
        mock_youtube_service.playlists().list_next.return_value = None
        mock_youtube_service.playlists().insert().execute.return_value = {}

        with pytest.raises(PlaylistError, match="Failed to create playlist"):
            setup_playlist(mock_youtube_service, title="Bad")


class TestUpdatePlaylist:
    def test_updates_title_and_description(self, mock_youtube_service: MagicMock) -> None:
        mock_youtube_service.playlists().update().execute.return_value = {}

        update_playlist(
            mock_youtube_service,
            playlist_id="PL-1",
            title="New Title",
            description="New Desc",
        )

        mock_youtube_service.playlists().update.assert_called_with(
            part="snippet",
            body={
                "id": "PL-1",
                "snippet": {"title": "New Title", "description": "New Desc"},
            },
        )

    def test_updates_with_localizations(self, mock_youtube_service: MagicMock) -> None:
        mock_youtube_service.playlists().update().execute.return_value = {}

        localizations = {"es": {"title": "Titulo", "description": "Desc ES"}}

        update_playlist(
            mock_youtube_service,
            playlist_id="PL-1",
            title="New Title",
            description="New Desc",
            localizations=localizations,
        )

        mock_youtube_service.playlists().update.assert_called_with(
            part="snippet,localizations",
            body={
                "id": "PL-1",
                "snippet": {
                    "title": "New Title",
                    "description": "New Desc",
                    "defaultLanguage": "en",
                },
                "localizations": localizations,
            },
        )

    def test_http_error_raises_playlist_error(self, mock_youtube_service: MagicMock) -> None:
        resp = Response({"status": "400"})
        mock_youtube_service.playlists().update().execute.side_effect = HttpError(resp, b"error")

        with pytest.raises(PlaylistError, match="Failed to update playlist"):
            update_playlist(
                mock_youtube_service,
                playlist_id="PL-1",
                title="New Title",
            )


def _make_http_error(status: int = 400) -> HttpError:
    """Build an HttpError for testing."""
    resp = Response({"status": str(status)})
    return HttpError(resp, b"error")


class TestHttpErrorWrapping:
    def test_find_playlist_by_title_http_error(self, mock_youtube_service: MagicMock) -> None:
        mock_youtube_service.playlists().list().execute.side_effect = _make_http_error()

        with pytest.raises(PlaylistError, match="Failed to list playlists"):
            find_playlist_by_title(mock_youtube_service, title="Test")

    def test_create_playlist_http_error(self, mock_youtube_service: MagicMock) -> None:
        mock_youtube_service.playlists().insert().execute.side_effect = _make_http_error()

        with pytest.raises(PlaylistError, match="Failed to create playlist"):
            create_playlist(mock_youtube_service, title="Test")

    def test_playlist_has_video_http_error(self, mock_youtube_service: MagicMock) -> None:
        mock_youtube_service.playlistItems().list().execute.side_effect = _make_http_error()

        with pytest.raises(PlaylistError, match="Failed to list playlist items"):
            playlist_has_video(mock_youtube_service, playlist_id="PL-1", video_id="v1")

    def test_insert_video_http_error(self, mock_youtube_service: MagicMock) -> None:
        # Not already present
        mock_youtube_service.playlistItems().list().execute.return_value = {"items": []}
        mock_youtube_service.playlistItems().list_next.return_value = None
        # Insert fails with HttpError
        mock_youtube_service.playlistItems().insert().execute.side_effect = _make_http_error()

        with pytest.raises(PlaylistError, match="Failed to insert video"):
            insert_video_into_playlist(
                mock_youtube_service, playlist_id="PL-1", video_id="v1"
            )
