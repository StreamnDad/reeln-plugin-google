"""Tests for auth module."""

from __future__ import annotations

import stat
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from reeln_google_plugin.auth import (
    DEFAULT_SCOPES,
    AuthError,
    build_youtube_service,
    default_credentials_path,
    get_credentials,
)


class TestDefaultCredentialsPath:
    def test_returns_path(self) -> None:
        result = default_credentials_path()
        assert isinstance(result, Path)
        assert result.name == "oauth.json"
        assert "google" in str(result)


class TestDefaultScopes:
    def test_contains_youtube(self) -> None:
        assert "https://www.googleapis.com/auth/youtube" in DEFAULT_SCOPES

    def test_contains_upload(self) -> None:
        assert "https://www.googleapis.com/auth/youtube.upload" in DEFAULT_SCOPES

    def test_contains_force_ssl(self) -> None:
        assert "https://www.googleapis.com/auth/youtube.force-ssl" in DEFAULT_SCOPES


class TestGetCredentials:
    def test_loads_from_cache(
        self, client_secrets_file: Path, credentials_cache: Path
    ) -> None:
        fake_creds = MagicMock()
        fake_creds.valid = True

        mock_creds_cls = MagicMock()
        mock_creds_cls.from_authorized_user_file.return_value = fake_creds
        credentials_cache.parent.mkdir(parents=True, exist_ok=True)
        credentials_cache.write_text("{}")

        with patch.dict("sys.modules", {
            "google.oauth2.credentials": MagicMock(Credentials=mock_creds_cls),
            "google_auth_oauthlib.flow": MagicMock(),
        }):
            result = get_credentials(client_secrets_file, credentials_cache)

        assert result is fake_creds
        mock_creds_cls.from_authorized_user_file.assert_called_once_with(
            str(credentials_cache), DEFAULT_SCOPES
        )

    def test_refreshes_expired_token(
        self, client_secrets_file: Path, credentials_cache: Path
    ) -> None:
        fake_creds = MagicMock()
        fake_creds.valid = False
        fake_creds.expired = True
        fake_creds.refresh_token = "refresh_tok"
        fake_creds.to_json.return_value = '{"refreshed": true}'

        mock_creds_cls = MagicMock()
        mock_creds_cls.from_authorized_user_file.return_value = fake_creds
        mock_request_cls = MagicMock()
        mock_request = MagicMock()
        mock_request_cls.return_value = mock_request

        credentials_cache.parent.mkdir(parents=True, exist_ok=True)
        credentials_cache.write_text("{}")

        with patch.dict("sys.modules", {
            "google.oauth2.credentials": MagicMock(Credentials=mock_creds_cls),
            "google_auth_oauthlib.flow": MagicMock(),
            "google.auth.transport.requests": MagicMock(Request=mock_request_cls),
            "google.auth.transport": MagicMock(),
            "google.auth": MagicMock(),
            "google": MagicMock(),
        }):
            result = get_credentials(client_secrets_file, credentials_cache)

        assert result is fake_creds
        fake_creds.refresh.assert_called_once_with(mock_request)
        assert credentials_cache.read_text() == '{"refreshed": true}'
        mode = credentials_cache.stat().st_mode
        assert mode & 0o777 == stat.S_IRUSR | stat.S_IWUSR

    def test_browser_flow_when_no_cache(
        self, client_secrets_file: Path, credentials_cache: Path
    ) -> None:
        fake_creds = MagicMock()
        fake_creds.to_json.return_value = '{"new": true}'

        mock_flow = MagicMock()
        mock_flow.run_local_server.return_value = fake_creds

        mock_flow_cls = MagicMock()
        mock_flow_cls.from_client_secrets_file.return_value = mock_flow

        with patch.dict("sys.modules", {
            "google.oauth2.credentials": MagicMock(Credentials=MagicMock),
            "google_auth_oauthlib.flow": MagicMock(InstalledAppFlow=mock_flow_cls),
            "google_auth_oauthlib": MagicMock(),
        }):
            result = get_credentials(client_secrets_file, credentials_cache)

        assert result is fake_creds
        mock_flow_cls.from_client_secrets_file.assert_called_once_with(
            str(client_secrets_file), DEFAULT_SCOPES
        )
        mock_flow.run_local_server.assert_called_once_with(port=0)
        assert credentials_cache.exists()
        assert credentials_cache.read_text() == '{"new": true}'
        mode = credentials_cache.stat().st_mode
        assert mode & 0o777 == stat.S_IRUSR | stat.S_IWUSR

    def test_browser_flow_when_creds_invalid_no_refresh(
        self, client_secrets_file: Path, credentials_cache: Path
    ) -> None:
        """Cached creds invalid with no refresh token -> browser flow."""
        cached_creds = MagicMock()
        cached_creds.valid = False
        cached_creds.expired = True
        cached_creds.refresh_token = None

        new_creds = MagicMock()
        new_creds.to_json.return_value = '{"new": true}'

        mock_creds_cls = MagicMock()
        mock_creds_cls.from_authorized_user_file.return_value = cached_creds

        mock_flow = MagicMock()
        mock_flow.run_local_server.return_value = new_creds
        mock_flow_cls = MagicMock()
        mock_flow_cls.from_client_secrets_file.return_value = mock_flow

        credentials_cache.parent.mkdir(parents=True, exist_ok=True)
        credentials_cache.write_text("{}")

        with patch.dict("sys.modules", {
            "google.oauth2.credentials": MagicMock(Credentials=mock_creds_cls),
            "google_auth_oauthlib.flow": MagicMock(InstalledAppFlow=mock_flow_cls),
            "google_auth_oauthlib": MagicMock(),
        }):
            result = get_credentials(client_secrets_file, credentials_cache)

        assert result is new_creds

    def test_fresh_deletes_cache(
        self, client_secrets_file: Path, credentials_cache: Path
    ) -> None:
        credentials_cache.parent.mkdir(parents=True, exist_ok=True)
        credentials_cache.write_text('{"old": true}')

        fake_creds = MagicMock()
        fake_creds.to_json.return_value = '{"fresh": true}'
        mock_flow = MagicMock()
        mock_flow.run_local_server.return_value = fake_creds
        mock_flow_cls = MagicMock()
        mock_flow_cls.from_client_secrets_file.return_value = mock_flow

        with patch.dict("sys.modules", {
            "google.oauth2.credentials": MagicMock(Credentials=MagicMock),
            "google_auth_oauthlib.flow": MagicMock(InstalledAppFlow=mock_flow_cls),
            "google_auth_oauthlib": MagicMock(),
        }):
            get_credentials(client_secrets_file, credentials_cache, fresh=True)

        assert credentials_cache.read_text() == '{"fresh": true}'
        mode = credentials_cache.stat().st_mode
        assert mode & 0o777 == stat.S_IRUSR | stat.S_IWUSR

    def test_creates_parent_dirs(
        self, client_secrets_file: Path, tmp_path: Path
    ) -> None:
        deep_cache = tmp_path / "a" / "b" / "c" / "oauth.json"
        fake_creds = MagicMock()
        fake_creds.to_json.return_value = "{}"
        mock_flow = MagicMock()
        mock_flow.run_local_server.return_value = fake_creds
        mock_flow_cls = MagicMock()
        mock_flow_cls.from_client_secrets_file.return_value = mock_flow

        with patch.dict("sys.modules", {
            "google.oauth2.credentials": MagicMock(Credentials=MagicMock),
            "google_auth_oauthlib.flow": MagicMock(InstalledAppFlow=mock_flow_cls),
            "google_auth_oauthlib": MagicMock(),
        }):
            get_credentials(client_secrets_file, deep_cache)

        assert deep_cache.exists()

    def test_custom_scopes(
        self, client_secrets_file: Path, credentials_cache: Path
    ) -> None:
        custom_scopes = ["https://www.googleapis.com/auth/youtube"]
        fake_creds = MagicMock()
        fake_creds.to_json.return_value = "{}"
        mock_flow = MagicMock()
        mock_flow.run_local_server.return_value = fake_creds
        mock_flow_cls = MagicMock()
        mock_flow_cls.from_client_secrets_file.return_value = mock_flow

        with patch.dict("sys.modules", {
            "google.oauth2.credentials": MagicMock(Credentials=MagicMock),
            "google_auth_oauthlib.flow": MagicMock(InstalledAppFlow=mock_flow_cls),
            "google_auth_oauthlib": MagicMock(),
        }):
            get_credentials(
                client_secrets_file, credentials_cache, scopes=custom_scopes
            )

        mock_flow_cls.from_client_secrets_file.assert_called_once_with(
            str(client_secrets_file), custom_scopes
        )

    def test_skips_chmod_on_windows(
        self, client_secrets_file: Path, credentials_cache: Path
    ) -> None:
        fake_creds = MagicMock()
        fake_creds.to_json.return_value = "{}"
        mock_flow = MagicMock()
        mock_flow.run_local_server.return_value = fake_creds
        mock_flow_cls = MagicMock()
        mock_flow_cls.from_client_secrets_file.return_value = mock_flow

        with (
            patch.dict("sys.modules", {
                "google.oauth2.credentials": MagicMock(Credentials=MagicMock),
                "google_auth_oauthlib.flow": MagicMock(InstalledAppFlow=mock_flow_cls),
                "google_auth_oauthlib": MagicMock(),
            }),
            patch("reeln_google_plugin.auth.os.name", "nt"),
        ):
            get_credentials(client_secrets_file, credentials_cache)

        assert credentials_cache.exists()
        # On "nt", chmod is skipped — file keeps default permissions
        mode = credentials_cache.stat().st_mode
        assert mode & 0o777 != 0  # file is accessible

    def test_import_error_raises_auth_error(
        self, client_secrets_file: Path, credentials_cache: Path
    ) -> None:
        with (
            patch.dict("sys.modules", {
                "google.oauth2.credentials": None,
                "google_auth_oauthlib.flow": None,
            }),
            pytest.raises(AuthError, match="Google auth libraries not installed"),
        ):
            get_credentials(client_secrets_file, credentials_cache)


class TestBuildYoutubeService:
    def test_builds_service(self) -> None:
        fake_creds = MagicMock()
        mock_service = MagicMock()
        mock_build = MagicMock(return_value=mock_service)

        with patch.dict("sys.modules", {
            "googleapiclient.discovery": MagicMock(build=mock_build),
            "googleapiclient": MagicMock(),
        }):
            result = build_youtube_service(fake_creds)

        assert result is mock_service
        mock_build.assert_called_once_with("youtube", "v3", credentials=fake_creds)

    def test_import_error_raises_auth_error(self) -> None:
        with (
            patch.dict("sys.modules", {"googleapiclient.discovery": None}),
            pytest.raises(AuthError, match="Google API client library not installed"),
        ):
            build_youtube_service(MagicMock())
