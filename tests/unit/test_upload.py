"""Tests for upload module."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from reeln_google_plugin.upload import (
    UploadError,
    _build_video_body,
    set_localizations,
    upload_short,
    upload_video,
)


class TestBuildVideoBody:
    def test_basic_body(self) -> None:
        body = _build_video_body(
            title="Test",
            description="Desc",
            tags=None,
            category_id="20",
            privacy_status="unlisted",
            made_for_kids=False,
            recording_date=None,
            location=None,
        )
        assert body["snippet"]["title"] == "Test"
        assert body["snippet"]["description"] == "Desc"
        assert body["snippet"]["categoryId"] == "20"
        assert body["status"]["privacyStatus"] == "unlisted"
        assert body["status"]["selfDeclaredMadeForKids"] is False
        assert "tags" not in body["snippet"]
        assert "recordingDetails" not in body

    def test_with_tags(self) -> None:
        body = _build_video_body(
            title="T",
            description="",
            tags=["a", "b"],
            category_id="20",
            privacy_status="unlisted",
            made_for_kids=False,
            recording_date=None,
            location=None,
        )
        assert body["snippet"]["tags"] == ["a", "b"]

    def test_with_recording_date(self) -> None:
        body = _build_video_body(
            title="T",
            description="",
            tags=None,
            category_id="20",
            privacy_status="unlisted",
            made_for_kids=False,
            recording_date="2026-01-15",
            location=None,
        )
        assert body["recordingDetails"]["recordingDate"] == "2026-01-15"
        assert "location" not in body["recordingDetails"]

    def test_with_location(self) -> None:
        loc = {"latitude": 40.0, "longitude": -74.0}
        body = _build_video_body(
            title="T",
            description="",
            tags=None,
            category_id="20",
            privacy_status="unlisted",
            made_for_kids=False,
            recording_date=None,
            location=loc,
        )
        assert body["recordingDetails"]["location"] == loc
        assert "recordingDate" not in body["recordingDetails"]

    def test_with_recording_date_and_location(self) -> None:
        loc = {"latitude": 40.0, "longitude": -74.0}
        body = _build_video_body(
            title="T",
            description="",
            tags=None,
            category_id="20",
            privacy_status="unlisted",
            made_for_kids=False,
            recording_date="2026-01-15",
            location=loc,
        )
        assert body["recordingDetails"]["recordingDate"] == "2026-01-15"
        assert body["recordingDetails"]["location"] == loc

    def test_made_for_kids_true(self) -> None:
        body = _build_video_body(
            title="T",
            description="",
            tags=None,
            category_id="20",
            privacy_status="unlisted",
            made_for_kids=True,
            recording_date=None,
            location=None,
        )
        assert body["status"]["selfDeclaredMadeForKids"] is True

    def test_custom_privacy_and_category(self) -> None:
        body = _build_video_body(
            title="T",
            description="",
            tags=None,
            category_id="17",
            privacy_status="public",
            made_for_kids=False,
            recording_date=None,
            location=None,
        )
        assert body["snippet"]["categoryId"] == "17"
        assert body["status"]["privacyStatus"] == "public"


class TestUploadVideo:
    def test_returns_video_id_and_url(self, tmp_path: Path) -> None:
        video_file = tmp_path / "highlights.mp4"
        video_file.write_text("fake video")

        mock_yt = MagicMock()
        mock_yt.videos().insert().execute.return_value = {"id": "vid123"}

        with patch("googleapiclient.http.MediaFileUpload"):
            video_id, url = upload_video(
                mock_yt, file_path=video_file, title="Test Upload"
            )

        assert video_id == "vid123"
        assert url == "https://youtube.com/watch?v=vid123"

    def test_raises_on_missing_id(self, tmp_path: Path) -> None:
        video_file = tmp_path / "highlights.mp4"
        video_file.write_text("fake video")

        mock_yt = MagicMock()
        mock_yt.videos().insert().execute.return_value = {}

        with (
            patch("googleapiclient.http.MediaFileUpload"),
            pytest.raises(UploadError, match="missing video ID"),
        ):
            upload_video(mock_yt, file_path=video_file, title="Test")

    def test_file_not_found_raises(self, tmp_path: Path) -> None:
        missing = tmp_path / "nope.mp4"

        with pytest.raises(UploadError, match="File not found"):
            upload_video(MagicMock(), file_path=missing, title="Test")

    def test_passes_metadata_body(self, tmp_path: Path) -> None:
        video_file = tmp_path / "highlights.mp4"
        video_file.write_text("fake video")

        mock_yt = MagicMock()
        mock_yt.videos().insert().execute.return_value = {"id": "v1"}

        with patch("googleapiclient.http.MediaFileUpload"):
            upload_video(
                mock_yt,
                file_path=video_file,
                title="My Title",
                description="My Desc",
                tags=["tag1"],
                category_id="20",
                privacy_status="unlisted",
            )

        call_kwargs = mock_yt.videos().insert.call_args[1]
        body = call_kwargs["body"]
        assert body["snippet"]["title"] == "My Title"
        assert body["snippet"]["description"] == "My Desc"
        assert body["snippet"]["tags"] == ["tag1"]
        assert body["snippet"]["categoryId"] == "20"
        assert body["status"]["privacyStatus"] == "unlisted"

    def test_recording_details_included(self, tmp_path: Path) -> None:
        video_file = tmp_path / "highlights.mp4"
        video_file.write_text("fake video")

        mock_yt = MagicMock()
        mock_yt.videos().insert().execute.return_value = {"id": "v1"}

        with patch("googleapiclient.http.MediaFileUpload"):
            upload_video(
                mock_yt,
                file_path=video_file,
                title="T",
                recording_date="2026-01-15",
                location={"latitude": 40.0, "longitude": -74.0},
            )

        call_kwargs = mock_yt.videos().insert.call_args[1]
        assert "recordingDetails" in call_kwargs["body"]
        assert ",recordingDetails" in call_kwargs["part"]

    def test_recording_details_omitted(self, tmp_path: Path) -> None:
        video_file = tmp_path / "highlights.mp4"
        video_file.write_text("fake video")

        mock_yt = MagicMock()
        mock_yt.videos().insert().execute.return_value = {"id": "v1"}

        with patch("googleapiclient.http.MediaFileUpload"):
            upload_video(mock_yt, file_path=video_file, title="T")

        call_kwargs = mock_yt.videos().insert.call_args[1]
        assert "recordingDetails" not in call_kwargs["body"]
        assert "recordingDetails" not in call_kwargs["part"]

    def test_resumable_media_upload(self, tmp_path: Path) -> None:
        video_file = tmp_path / "highlights.mp4"
        video_file.write_text("fake video")

        mock_yt = MagicMock()
        mock_yt.videos().insert().execute.return_value = {"id": "v1"}

        with patch("googleapiclient.http.MediaFileUpload") as mock_mfu:
            upload_video(mock_yt, file_path=video_file, title="T")

        mock_mfu.assert_called_once_with(str(video_file), chunksize=-1, resumable=True)

    def test_made_for_kids_false(self, tmp_path: Path) -> None:
        video_file = tmp_path / "highlights.mp4"
        video_file.write_text("fake video")

        mock_yt = MagicMock()
        mock_yt.videos().insert().execute.return_value = {"id": "v1"}

        with patch("googleapiclient.http.MediaFileUpload"):
            upload_video(mock_yt, file_path=video_file, title="T")

        call_kwargs = mock_yt.videos().insert.call_args[1]
        assert call_kwargs["body"]["status"]["selfDeclaredMadeForKids"] is False

    def test_custom_privacy_and_category(self, tmp_path: Path) -> None:
        video_file = tmp_path / "highlights.mp4"
        video_file.write_text("fake video")

        mock_yt = MagicMock()
        mock_yt.videos().insert().execute.return_value = {"id": "v1"}

        with patch("googleapiclient.http.MediaFileUpload"):
            upload_video(
                mock_yt,
                file_path=video_file,
                title="T",
                privacy_status="public",
                category_id="17",
            )

        call_kwargs = mock_yt.videos().insert.call_args[1]
        assert call_kwargs["body"]["status"]["privacyStatus"] == "public"
        assert call_kwargs["body"]["snippet"]["categoryId"] == "17"

    def test_tags_passed(self, tmp_path: Path) -> None:
        video_file = tmp_path / "highlights.mp4"
        video_file.write_text("fake video")

        mock_yt = MagicMock()
        mock_yt.videos().insert().execute.return_value = {"id": "v1"}

        with patch("googleapiclient.http.MediaFileUpload"):
            upload_video(
                mock_yt,
                file_path=video_file,
                title="T",
                tags=["hockey", "highlights"],
            )

        call_kwargs = mock_yt.videos().insert.call_args[1]
        assert call_kwargs["body"]["snippet"]["tags"] == ["hockey", "highlights"]

    def test_api_exception_wrapped(self, tmp_path: Path) -> None:
        video_file = tmp_path / "highlights.mp4"
        video_file.write_text("fake video")

        mock_yt = MagicMock()
        mock_yt.videos().insert().execute.side_effect = RuntimeError("API error")

        with (
            patch("googleapiclient.http.MediaFileUpload"),
            pytest.raises(UploadError, match="Upload failed"),
        ):
            upload_video(mock_yt, file_path=video_file, title="T")


class TestUploadShort:
    def test_returns_video_id_and_url(self, tmp_path: Path) -> None:
        video_file = tmp_path / "short.mp4"
        video_file.write_text("fake short")

        mock_yt = MagicMock()
        mock_yt.videos().insert().execute.return_value = {"id": "short1"}

        with patch("googleapiclient.http.MediaFileUpload"):
            video_id, url = upload_short(
                mock_yt, file_path=video_file, title="Cool Play"
            )

        assert video_id == "short1"
        assert url == "https://youtube.com/watch?v=short1"

    def test_appends_shorts_hashtag(self, tmp_path: Path) -> None:
        video_file = tmp_path / "short.mp4"
        video_file.write_text("fake short")

        mock_yt = MagicMock()
        mock_yt.videos().insert().execute.return_value = {"id": "s1"}

        with patch("googleapiclient.http.MediaFileUpload"):
            upload_short(mock_yt, file_path=video_file, title="Cool Play")

        call_kwargs = mock_yt.videos().insert.call_args[1]
        assert call_kwargs["body"]["snippet"]["title"] == "Cool Play #Shorts"

    def test_preserves_existing_shorts_hashtag(self, tmp_path: Path) -> None:
        video_file = tmp_path / "short.mp4"
        video_file.write_text("fake short")

        mock_yt = MagicMock()
        mock_yt.videos().insert().execute.return_value = {"id": "s2"}

        with patch("googleapiclient.http.MediaFileUpload"):
            upload_short(
                mock_yt, file_path=video_file, title="Cool Play #Shorts"
            )

        call_kwargs = mock_yt.videos().insert.call_args[1]
        assert call_kwargs["body"]["snippet"]["title"] == "Cool Play #Shorts"

    def test_raises_on_missing_id(self, tmp_path: Path) -> None:
        video_file = tmp_path / "short.mp4"
        video_file.write_text("fake short")

        mock_yt = MagicMock()
        mock_yt.videos().insert().execute.return_value = {}

        with (
            patch("googleapiclient.http.MediaFileUpload"),
            pytest.raises(UploadError, match="missing video ID"),
        ):
            upload_short(mock_yt, file_path=video_file, title="T")

    def test_file_not_found_raises(self, tmp_path: Path) -> None:
        missing = tmp_path / "nope.mp4"

        with pytest.raises(UploadError, match="File not found"):
            upload_short(MagicMock(), file_path=missing, title="T")

    def test_no_recording_details(self, tmp_path: Path) -> None:
        video_file = tmp_path / "short.mp4"
        video_file.write_text("fake short")

        mock_yt = MagicMock()
        mock_yt.videos().insert().execute.return_value = {"id": "s3"}

        with patch("googleapiclient.http.MediaFileUpload"):
            upload_short(mock_yt, file_path=video_file, title="T")

        call_kwargs = mock_yt.videos().insert.call_args[1]
        assert "recordingDetails" not in call_kwargs["body"]


class TestSetLocalizations:
    def test_applies_localizations(self) -> None:
        mock_yt = MagicMock()
        localizations = {
            "es": {"title": "Titulo", "description": "Desc es"},
            "fr": {"title": "Titre", "description": "Desc fr"},
        }

        set_localizations(mock_yt, video_id="vid1", localizations=localizations)

        mock_yt.videos().update.assert_called_once_with(
            part="localizations",
            body={"id": "vid1", "localizations": localizations},
        )

    def test_raises_on_failure(self) -> None:
        mock_yt = MagicMock()
        mock_yt.videos().update().execute.side_effect = RuntimeError("API error")

        with pytest.raises(UploadError, match="Failed to set localizations"):
            set_localizations(
                mock_yt,
                video_id="vid1",
                localizations={"es": {"title": "T", "description": "D"}},
            )
