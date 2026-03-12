"""Tests for plugin module."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from reeln.plugins.hooks import Hook, HookContext
from reeln.plugins.registry import HookRegistry

from reeln_google_plugin.auth import AuthError
from reeln_google_plugin.livestream import LivestreamError
from reeln_google_plugin.playlist import PlaylistError
from reeln_google_plugin.plugin import GooglePlugin
from reeln_google_plugin.upload import UploadError
from tests.conftest import FakeGameInfo


class TestGooglePluginAttributes:
    def test_name(self) -> None:
        plugin = GooglePlugin()
        assert plugin.name == "google"

    def test_version(self) -> None:
        plugin = GooglePlugin()
        assert plugin.version == "0.7.0"

    def test_api_version(self) -> None:
        plugin = GooglePlugin()
        assert plugin.api_version == 1

    def test_min_reeln_version(self) -> None:
        plugin = GooglePlugin()
        assert plugin.min_reeln_version == "0.0.19"


class TestGooglePluginConfigSchema:
    def test_create_livestream_default_false(self) -> None:
        schema = GooglePlugin.config_schema
        field = schema.field_by_name("create_livestream")
        assert field is not None
        assert field.default is False

    def test_manage_playlists_default_false(self) -> None:
        schema = GooglePlugin.config_schema
        field = schema.field_by_name("manage_playlists")
        assert field is not None
        assert field.default is False

    def test_upload_highlights_default_false(self) -> None:
        schema = GooglePlugin.config_schema
        field = schema.field_by_name("upload_highlights")
        assert field is not None
        assert field.default is False

    def test_upload_shorts_default_false(self) -> None:
        schema = GooglePlugin.config_schema
        field = schema.field_by_name("upload_shorts")
        assert field is not None
        assert field.default is False

    def test_client_secrets_file_required(self) -> None:
        schema = GooglePlugin.config_schema
        field = schema.field_by_name("client_secrets_file")
        assert field is not None
        assert field.required is True

    def test_privacy_status_default(self) -> None:
        schema = GooglePlugin.config_schema
        field = schema.field_by_name("privacy_status")
        assert field is not None
        assert field.default == "unlisted"

    def test_category_id_default(self) -> None:
        schema = GooglePlugin.config_schema
        field = schema.field_by_name("category_id")
        assert field is not None
        assert field.default == "20"

    def test_tags_default(self) -> None:
        schema = GooglePlugin.config_schema
        field = schema.field_by_name("tags")
        assert field is not None
        assert field.default == []

    def test_credentials_cache_optional(self) -> None:
        schema = GooglePlugin.config_schema
        field = schema.field_by_name("credentials_cache")
        assert field is not None
        assert field.required is False

    def test_scopes_optional(self) -> None:
        schema = GooglePlugin.config_schema
        field = schema.field_by_name("scopes")
        assert field is not None
        assert field.required is False


class TestGooglePluginInit:
    def test_no_config(self) -> None:
        plugin = GooglePlugin()
        assert plugin._config == {}

    def test_empty_config(self) -> None:
        plugin = GooglePlugin({})
        assert plugin._config == {}

    def test_with_config(self, plugin_config: dict[str, Any]) -> None:
        plugin = GooglePlugin(plugin_config)
        assert plugin._config == plugin_config

    def test_initial_state(self) -> None:
        plugin = GooglePlugin()
        assert plugin._game_info is None
        assert plugin._youtube is None
        assert plugin._playlist_id is None


class TestGooglePluginRegister:
    def test_registers_on_game_init(self) -> None:
        plugin = GooglePlugin()
        registry = HookRegistry()
        plugin.register(registry)
        assert registry.has_handlers(Hook.ON_GAME_INIT)

    def test_registers_on_highlights_merged(self) -> None:
        plugin = GooglePlugin()
        registry = HookRegistry()
        plugin.register(registry)
        assert registry.has_handlers(Hook.ON_HIGHLIGHTS_MERGED)

    def test_registers_post_render(self) -> None:
        plugin = GooglePlugin()
        registry = HookRegistry()
        plugin.register(registry)
        assert registry.has_handlers(Hook.POST_RENDER)

    def test_registers_on_game_finish(self) -> None:
        plugin = GooglePlugin()
        registry = HookRegistry()
        plugin.register(registry)
        assert registry.has_handlers(Hook.ON_GAME_FINISH)

    def test_registers_on_game_ready(self) -> None:
        plugin = GooglePlugin()
        registry = HookRegistry()
        plugin.register(registry)
        assert registry.has_handlers(Hook.ON_GAME_READY)

    def test_does_not_register_other_hooks(self) -> None:
        plugin = GooglePlugin()
        registry = HookRegistry()
        plugin.register(registry)
        assert not registry.has_handlers(Hook.ON_SEGMENT_START)


class TestBuildTitle:
    def test_basic_title(self) -> None:
        plugin = GooglePlugin()
        game_info = FakeGameInfo(home_team="Eagles", away_team="Hawks", date="2026-01-15")
        title = plugin._build_title(game_info)
        assert title == "Eagles vs Hawks - 2026-01-15"

    def test_title_with_venue(self) -> None:
        plugin = GooglePlugin()
        game_info = FakeGameInfo(
            home_team="Eagles", away_team="Hawks", date="2026-01-15", venue="Main Arena"
        )
        title = plugin._build_title(game_info)
        assert title == "Eagles vs Hawks - 2026-01-15 @ Main Arena"

    def test_title_empty_venue(self) -> None:
        plugin = GooglePlugin()
        game_info = FakeGameInfo(
            home_team="Eagles", away_team="Hawks", date="2026-01-15", venue=""
        )
        title = plugin._build_title(game_info)
        assert title == "Eagles vs Hawks - 2026-01-15"

    def test_title_missing_attributes(self) -> None:
        plugin = GooglePlugin()

        class Bare:
            pass

        title = plugin._build_title(Bare())
        assert title == " vs  - "


class TestBuildScheduledStart:
    def test_with_date_and_game_time(self) -> None:
        plugin = GooglePlugin()
        future = datetime.now().astimezone() + timedelta(days=30)
        date_str = future.strftime("%Y-%m-%d")
        game_info = FakeGameInfo(date=date_str, game_time="7:00 PM CST")
        result = plugin._build_scheduled_start(game_info)
        assert result is not None
        assert date_str in result
        assert "19:00:00" in result

    def test_without_game_time(self) -> None:
        plugin = GooglePlugin()
        game_info = FakeGameInfo(date="2026-03-04", game_time="")
        result = plugin._build_scheduled_start(game_info)
        assert result is None

    def test_without_date(self) -> None:
        plugin = GooglePlugin()
        game_info = FakeGameInfo(date="", game_time="7:00 PM CST")
        result = plugin._build_scheduled_start(game_info)
        assert result is None

    def test_unparseable_game_time(self, caplog: pytest.LogCaptureFixture) -> None:
        plugin = GooglePlugin()
        game_info = FakeGameInfo(date="2026-03-04", game_time="not-a-time")
        with caplog.at_level(logging.WARNING):
            result = plugin._build_scheduled_start(game_info)
        assert result is None
        assert "could not parse game time" in caplog.text

    def test_missing_attributes(self) -> None:
        plugin = GooglePlugin()

        class Bare:
            pass

        result = plugin._build_scheduled_start(Bare())
        assert result is None

    def test_est_timezone(self) -> None:
        plugin = GooglePlugin()
        future = datetime.now().astimezone() + timedelta(days=30)
        date_str = future.strftime("%Y-%m-%d")
        game_info = FakeGameInfo(date=date_str, game_time="7:00 PM EST")
        result = plugin._build_scheduled_start(game_info)
        assert result is not None
        assert "19:00:00" in result

    def test_no_timezone(self) -> None:
        plugin = GooglePlugin()
        future = datetime.now().astimezone() + timedelta(days=30)
        date_str = future.strftime("%Y-%m-%d")
        game_info = FakeGameInfo(date=date_str, game_time="7:00 PM")
        result = plugin._build_scheduled_start(game_info)
        assert result is not None
        assert "19:00:00" in result

    def test_past_time_returns_none(self, caplog: pytest.LogCaptureFixture) -> None:
        plugin = GooglePlugin()
        game_info = FakeGameInfo(date="2020-01-01", game_time="7:00 PM CST")
        with caplog.at_level(logging.WARNING):
            result = plugin._build_scheduled_start(game_info)
        assert result is None
        assert "in the past or <5 min away" in caplog.text

    def test_near_future_time_returns_none(self, caplog: pytest.LogCaptureFixture) -> None:
        plugin = GooglePlugin()
        now = datetime.now().astimezone()
        near = now + timedelta(minutes=2)
        date_str = near.strftime("%Y-%m-%d")
        time_str = near.strftime("%-I:%M %p")
        game_info = FakeGameInfo(date=date_str, game_time=time_str)
        with caplog.at_level(logging.WARNING):
            result = plugin._build_scheduled_start(game_info)
        assert result is None
        assert "in the past or <5 min away" in caplog.text

    def test_future_time_returns_iso_string(self) -> None:
        plugin = GooglePlugin()
        now = datetime.now().astimezone()
        future = now + timedelta(hours=2)
        date_str = future.strftime("%Y-%m-%d")
        time_str = future.strftime("%-I:%M %p")
        game_info = FakeGameInfo(date=date_str, game_time=time_str)
        result = plugin._build_scheduled_start(game_info)
        assert result is not None
        assert date_str in result


class TestOnGameInit:
    def test_disabled_by_default(self) -> None:
        """When create_livestream is not set (default False), on_game_init is a no-op."""
        plugin = GooglePlugin({"client_secrets_file": "/tmp/secrets.json"})
        game_info = FakeGameInfo()
        context = HookContext(hook=Hook.ON_GAME_INIT, data={"game_info": game_info})

        plugin.on_game_init(context)

        assert "livestreams" not in context.shared

    def test_explicitly_disabled(self, plugin_config: dict[str, Any]) -> None:
        """When create_livestream is explicitly False, on_game_init is a no-op."""
        plugin_config["create_livestream"] = False
        plugin = GooglePlugin(plugin_config)
        game_info = FakeGameInfo()
        context = HookContext(hook=Hook.ON_GAME_INIT, data={"game_info": game_info})

        plugin.on_game_init(context)

        assert "livestreams" not in context.shared

    def test_full_flow(self, plugin_config: dict[str, Any]) -> None:
        plugin = GooglePlugin(plugin_config)
        game_info = FakeGameInfo()
        context = HookContext(hook=Hook.ON_GAME_INIT, data={"game_info": game_info})

        mock_creds = MagicMock()
        mock_youtube = MagicMock()

        with (
            patch("reeln_google_plugin.plugin.auth.get_credentials", return_value=mock_creds),
            patch("reeln_google_plugin.plugin.auth.build_youtube_service", return_value=mock_youtube),
            patch(
                "reeln_google_plugin.plugin.livestream.create_livestream",
                return_value="https://youtube.com/live/test123",
            ) as mock_create,
        ):
            plugin.on_game_init(context)

        assert context.shared["livestreams"]["google"] == "https://youtube.com/live/test123"
        # Default FakeGameInfo has no game_time → scheduled_start=None
        assert mock_create.call_args[1]["scheduled_start"] is None

    def test_full_flow_with_scheduled_start(self, plugin_config: dict[str, Any]) -> None:
        plugin = GooglePlugin(plugin_config)
        future = datetime.now().astimezone() + timedelta(days=30)
        date_str = future.strftime("%Y-%m-%d")
        game_info = FakeGameInfo(date=date_str, game_time="7:00 PM CST")
        context = HookContext(hook=Hook.ON_GAME_INIT, data={"game_info": game_info})

        with (
            patch("reeln_google_plugin.plugin.auth.get_credentials", return_value=MagicMock()),
            patch("reeln_google_plugin.plugin.auth.build_youtube_service", return_value=MagicMock()),
            patch(
                "reeln_google_plugin.plugin.livestream.create_livestream",
                return_value="https://youtube.com/live/test123",
            ) as mock_create,
        ):
            plugin.on_game_init(context)

        scheduled = mock_create.call_args[1]["scheduled_start"]
        assert scheduled is not None
        assert date_str in scheduled
        assert "19:00:00" in scheduled

    def test_no_game_info_logs_warning(
        self, plugin_config: dict[str, Any], caplog: pytest.LogCaptureFixture
    ) -> None:
        plugin = GooglePlugin(plugin_config)
        context = HookContext(hook=Hook.ON_GAME_INIT, data={})

        with caplog.at_level(logging.WARNING):
            plugin.on_game_init(context)

        assert "no game_info" in caplog.text
        assert "livestreams" not in context.shared

    def test_no_client_secrets_logs_warning(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        plugin = GooglePlugin({"create_livestream": True})
        game_info = FakeGameInfo()
        context = HookContext(hook=Hook.ON_GAME_INIT, data={"game_info": game_info})

        with caplog.at_level(logging.WARNING):
            plugin.on_game_init(context)

        assert "client_secrets_file not configured" in caplog.text

    def test_auth_error_logs_warning(
        self, plugin_config: dict[str, Any], caplog: pytest.LogCaptureFixture
    ) -> None:
        plugin = GooglePlugin(plugin_config)
        game_info = FakeGameInfo()
        context = HookContext(hook=Hook.ON_GAME_INIT, data={"game_info": game_info})

        with (
            patch(
                "reeln_google_plugin.plugin.auth.get_credentials",
                side_effect=AuthError("auth failed"),
            ),
            caplog.at_level(logging.WARNING),
        ):
            plugin.on_game_init(context)

        assert "authentication failed" in caplog.text
        assert "livestreams" not in context.shared

    def test_livestream_error_logs_warning(
        self, plugin_config: dict[str, Any], caplog: pytest.LogCaptureFixture
    ) -> None:
        plugin = GooglePlugin(plugin_config)
        game_info = FakeGameInfo()
        context = HookContext(hook=Hook.ON_GAME_INIT, data={"game_info": game_info})

        with (
            patch("reeln_google_plugin.plugin.auth.get_credentials", return_value=MagicMock()),
            patch("reeln_google_plugin.plugin.auth.build_youtube_service", return_value=MagicMock()),
            patch(
                "reeln_google_plugin.plugin.livestream.create_livestream",
                side_effect=LivestreamError("stream failed"),
            ),
            caplog.at_level(logging.WARNING),
        ):
            plugin.on_game_init(context)

        assert "livestream creation failed" in caplog.text
        assert "livestreams" not in context.shared

    def test_uses_default_credentials_cache(
        self, client_secrets_file: Path
    ) -> None:
        """When no credentials_cache in config, uses default_credentials_path()."""
        config = {"create_livestream": True, "client_secrets_file": str(client_secrets_file)}
        plugin = GooglePlugin(config)
        game_info = FakeGameInfo()
        context = HookContext(hook=Hook.ON_GAME_INIT, data={"game_info": game_info})

        mock_creds = MagicMock()
        mock_youtube = MagicMock()

        with (
            patch("reeln_google_plugin.plugin.auth.get_credentials", return_value=mock_creds) as mock_get_creds,
            patch("reeln_google_plugin.plugin.auth.build_youtube_service", return_value=mock_youtube),
            patch(
                "reeln_google_plugin.plugin.livestream.create_livestream",
                return_value="https://youtube.com/live/x",
            ),
            patch("reeln_google_plugin.plugin.auth.default_credentials_path") as mock_default_path,
        ):
            mock_default_path.return_value = Path("/default/oauth.json")
            plugin.on_game_init(context)

        call_args = mock_get_creds.call_args
        assert call_args[0][1] == Path("/default/oauth.json")

    def test_custom_privacy_status(
        self, plugin_config: dict[str, Any]
    ) -> None:
        plugin_config["privacy_status"] = "public"
        plugin = GooglePlugin(plugin_config)
        game_info = FakeGameInfo()
        context = HookContext(hook=Hook.ON_GAME_INIT, data={"game_info": game_info})

        with (
            patch("reeln_google_plugin.plugin.auth.get_credentials", return_value=MagicMock()),
            patch("reeln_google_plugin.plugin.auth.build_youtube_service", return_value=MagicMock()),
            patch(
                "reeln_google_plugin.plugin.livestream.create_livestream",
                return_value="https://youtube.com/live/x",
            ) as mock_create,
        ):
            plugin.on_game_init(context)

        mock_create.assert_called_once()
        assert mock_create.call_args[1]["privacy_status"] == "public"

    def test_custom_scopes_passed_to_auth(
        self, plugin_config: dict[str, Any]
    ) -> None:
        plugin_config["scopes"] = ["https://www.googleapis.com/auth/youtube"]
        plugin = GooglePlugin(plugin_config)
        game_info = FakeGameInfo()
        context = HookContext(hook=Hook.ON_GAME_INIT, data={"game_info": game_info})

        with (
            patch("reeln_google_plugin.plugin.auth.get_credentials", return_value=MagicMock()) as mock_get_creds,
            patch("reeln_google_plugin.plugin.auth.build_youtube_service", return_value=MagicMock()),
            patch(
                "reeln_google_plugin.plugin.livestream.create_livestream",
                return_value="https://youtube.com/live/x",
            ),
        ):
            plugin.on_game_init(context)

        assert mock_get_creds.call_args[1]["scopes"] == ["https://www.googleapis.com/auth/youtube"]

    def test_description_passed_to_create_livestream(
        self, plugin_config: dict[str, Any]
    ) -> None:
        plugin = GooglePlugin(plugin_config)
        game_info = FakeGameInfo(description="Big game tonight")
        context = HookContext(hook=Hook.ON_GAME_INIT, data={"game_info": game_info})

        with (
            patch("reeln_google_plugin.plugin.auth.get_credentials", return_value=MagicMock()),
            patch("reeln_google_plugin.plugin.auth.build_youtube_service", return_value=MagicMock()),
            patch(
                "reeln_google_plugin.plugin.livestream.create_livestream",
                return_value="https://youtube.com/live/x",
            ) as mock_create,
        ):
            plugin.on_game_init(context)

        assert mock_create.call_args[1]["description"] == "Big game tonight"

    def test_thumbnail_passed_to_create_livestream(
        self, plugin_config: dict[str, Any], tmp_path: Path
    ) -> None:
        thumb = tmp_path / "thumb.jpg"
        thumb.write_text("fake")
        plugin = GooglePlugin(plugin_config)
        game_info = FakeGameInfo(thumbnail=str(thumb))
        context = HookContext(hook=Hook.ON_GAME_INIT, data={"game_info": game_info})

        with (
            patch("reeln_google_plugin.plugin.auth.get_credentials", return_value=MagicMock()),
            patch("reeln_google_plugin.plugin.auth.build_youtube_service", return_value=MagicMock()),
            patch(
                "reeln_google_plugin.plugin.livestream.create_livestream",
                return_value="https://youtube.com/live/x",
            ) as mock_create,
        ):
            plugin.on_game_init(context)

        assert mock_create.call_args[1]["thumbnail_path"] == thumb

    def test_empty_thumbnail_passes_none(
        self, plugin_config: dict[str, Any]
    ) -> None:
        plugin = GooglePlugin(plugin_config)
        game_info = FakeGameInfo(thumbnail="")
        context = HookContext(hook=Hook.ON_GAME_INIT, data={"game_info": game_info})

        with (
            patch("reeln_google_plugin.plugin.auth.get_credentials", return_value=MagicMock()),
            patch("reeln_google_plugin.plugin.auth.build_youtube_service", return_value=MagicMock()),
            patch(
                "reeln_google_plugin.plugin.livestream.create_livestream",
                return_value="https://youtube.com/live/x",
            ) as mock_create,
        ):
            plugin.on_game_init(context)

        assert mock_create.call_args[1]["thumbnail_path"] is None

    def test_missing_description_attribute_defaults_empty(
        self, plugin_config: dict[str, Any]
    ) -> None:
        """game_info without description attribute still works (backward compat)."""
        plugin = GooglePlugin(plugin_config)

        class BareGameInfo:
            date = "2026-01-15"
            home_team = "Eagles"
            away_team = "Hawks"
            sport = "hockey"
            venue = ""
            game_time = ""

        context = HookContext(hook=Hook.ON_GAME_INIT, data={"game_info": BareGameInfo()})

        with (
            patch("reeln_google_plugin.plugin.auth.get_credentials", return_value=MagicMock()),
            patch("reeln_google_plugin.plugin.auth.build_youtube_service", return_value=MagicMock()),
            patch(
                "reeln_google_plugin.plugin.livestream.create_livestream",
                return_value="https://youtube.com/live/x",
            ) as mock_create,
        ):
            plugin.on_game_init(context)

        assert mock_create.call_args[1]["description"] == ""
        assert mock_create.call_args[1]["thumbnail_path"] is None

    def test_logs_info_on_success(
        self, plugin_config: dict[str, Any], caplog: pytest.LogCaptureFixture
    ) -> None:
        plugin = GooglePlugin(plugin_config)
        game_info = FakeGameInfo()
        context = HookContext(hook=Hook.ON_GAME_INIT, data={"game_info": game_info})

        with (
            patch("reeln_google_plugin.plugin.auth.get_credentials", return_value=MagicMock()),
            patch("reeln_google_plugin.plugin.auth.build_youtube_service", return_value=MagicMock()),
            patch(
                "reeln_google_plugin.plugin.livestream.create_livestream",
                return_value="https://youtube.com/live/test123",
            ),
            caplog.at_level(logging.INFO),
        ):
            plugin.on_game_init(context)

        assert "created livestream" in caplog.text


class TestOnGameReady:
    def _make_plugin_with_youtube(
        self, config: dict[str, Any]
    ) -> tuple[GooglePlugin, MagicMock]:
        """Create a plugin with a pre-injected mock YouTube service."""
        plugin = GooglePlugin(config)
        mock_youtube = MagicMock()
        plugin._youtube = mock_youtube
        return plugin, mock_youtube

    def test_noop_when_no_metadata(self, plugin_config: dict[str, Any]) -> None:
        plugin, _ = self._make_plugin_with_youtube(plugin_config)
        context = HookContext(hook=Hook.ON_GAME_READY, data={})

        plugin.on_game_ready(context)
        # No error, no-op

    def test_noop_when_no_livestream_url(self, plugin_config: dict[str, Any]) -> None:
        plugin, _ = self._make_plugin_with_youtube(plugin_config)
        context = HookContext(hook=Hook.ON_GAME_READY, data={})
        context.shared["livestream_metadata"] = {"title": "AI Title", "description": "AI Desc"}

        plugin.on_game_ready(context)
        # No error — returns early because no livestream URL

    def test_updates_broadcast_with_metadata(self, plugin_config: dict[str, Any]) -> None:
        plugin, mock_youtube = self._make_plugin_with_youtube(plugin_config)
        context = HookContext(hook=Hook.ON_GAME_READY, data={})
        context.shared["livestreams"] = {"google": "https://youtube.com/live/b1"}
        context.shared["livestream_metadata"] = {
            "title": "AI Title",
            "description": "AI Desc",
            "translations": {"es": {"title": "Titulo", "description": "Desc ES"}},
        }

        with patch(
            "reeln_google_plugin.plugin.livestream.update_broadcast"
        ) as mock_update:
            plugin.on_game_ready(context)

        mock_update.assert_called_once_with(
            mock_youtube,
            broadcast_id="b1",
            title="AI Title",
            description="AI Desc",
            thumbnail_path=None,
            localizations={"es": {"title": "Titulo", "description": "Desc ES"}},
        )

    def test_updates_playlist_with_metadata(self, plugin_config: dict[str, Any]) -> None:
        plugin, mock_youtube = self._make_plugin_with_youtube(plugin_config)
        plugin._playlist_id = "PL-1"
        context = HookContext(hook=Hook.ON_GAME_READY, data={})
        context.shared["livestreams"] = {"google": "https://youtube.com/live/b1"}
        context.shared["livestream_metadata"] = {"title": "AI Title", "description": "AI Desc"}
        context.shared["playlist_metadata"] = {
            "title": "Playlist Title",
            "description": "Playlist Desc",
            "translations": {"fr": {"title": "Titre", "description": "Desc FR"}},
        }

        with (
            patch("reeln_google_plugin.plugin.livestream.update_broadcast"),
            patch(
                "reeln_google_plugin.plugin.playlist.update_playlist"
            ) as mock_update_pl,
        ):
            plugin.on_game_ready(context)

        mock_update_pl.assert_called_once_with(
            mock_youtube,
            playlist_id="PL-1",
            title="Playlist Title",
            description="Playlist Desc",
            localizations={"fr": {"title": "Titre", "description": "Desc FR"}},
        )

    def test_no_playlist_update_without_playlist_id(self, plugin_config: dict[str, Any]) -> None:
        plugin, _ = self._make_plugin_with_youtube(plugin_config)
        # _playlist_id is None (no playlist was created during init)
        context = HookContext(hook=Hook.ON_GAME_READY, data={})
        context.shared["livestreams"] = {"google": "https://youtube.com/live/b1"}
        context.shared["livestream_metadata"] = {"title": "AI Title", "description": "AI Desc"}
        context.shared["playlist_metadata"] = {"title": "PL Title", "description": "PL Desc"}

        with (
            patch("reeln_google_plugin.plugin.livestream.update_broadcast"),
            patch(
                "reeln_google_plugin.plugin.playlist.update_playlist"
            ) as mock_update_pl,
        ):
            plugin.on_game_ready(context)

        mock_update_pl.assert_not_called()

    def test_updates_thumbnail_from_game_image(
        self, plugin_config: dict[str, Any], tmp_path: Path
    ) -> None:
        plugin, _mock_youtube = self._make_plugin_with_youtube(plugin_config)
        thumb = tmp_path / "game_thumb.png"
        thumb.write_bytes(b"\x89PNG")

        context = HookContext(hook=Hook.ON_GAME_READY, data={})
        context.shared["livestreams"] = {"google": "https://youtube.com/live/b1"}
        context.shared["livestream_metadata"] = {"title": "AI Title", "description": "AI Desc"}
        context.shared["game_image"] = {"image_path": str(thumb)}

        with patch(
            "reeln_google_plugin.plugin.livestream.update_broadcast"
        ) as mock_update:
            plugin.on_game_ready(context)

        mock_update.assert_called_once()
        assert mock_update.call_args[1]["thumbnail_path"] == thumb

    def test_livestream_error_non_fatal(
        self, plugin_config: dict[str, Any], caplog: pytest.LogCaptureFixture
    ) -> None:
        plugin, _ = self._make_plugin_with_youtube(plugin_config)
        context = HookContext(hook=Hook.ON_GAME_READY, data={})
        context.shared["livestreams"] = {"google": "https://youtube.com/live/b1"}
        context.shared["livestream_metadata"] = {"title": "AI Title", "description": "AI Desc"}

        with (
            patch(
                "reeln_google_plugin.plugin.livestream.update_broadcast",
                side_effect=LivestreamError("update failed"),
            ),
            caplog.at_level(logging.WARNING),
        ):
            plugin.on_game_ready(context)

        assert "broadcast update failed" in caplog.text

    def test_playlist_error_non_fatal(
        self, plugin_config: dict[str, Any], caplog: pytest.LogCaptureFixture
    ) -> None:
        plugin, _ = self._make_plugin_with_youtube(plugin_config)
        plugin._playlist_id = "PL-1"
        context = HookContext(hook=Hook.ON_GAME_READY, data={})
        context.shared["livestreams"] = {"google": "https://youtube.com/live/b1"}
        context.shared["livestream_metadata"] = {"title": "AI Title", "description": "AI Desc"}
        context.shared["playlist_metadata"] = {"title": "PL Title", "description": "PL Desc"}

        with (
            patch("reeln_google_plugin.plugin.livestream.update_broadcast"),
            patch(
                "reeln_google_plugin.plugin.playlist.update_playlist",
                side_effect=PlaylistError("update failed"),
            ),
            caplog.at_level(logging.WARNING),
        ):
            plugin.on_game_ready(context)

        assert "playlist update failed" in caplog.text

    def test_noop_when_no_youtube_service(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """When auth fails (no youtube service), on_game_ready returns silently."""
        plugin = GooglePlugin({"create_livestream": True})
        context = HookContext(hook=Hook.ON_GAME_READY, data={})
        context.shared["livestreams"] = {"google": "https://youtube.com/live/b1"}
        context.shared["livestream_metadata"] = {"title": "AI Title", "description": "AI Desc"}

        with caplog.at_level(logging.WARNING):
            plugin.on_game_ready(context)
        # No crash — _ensure_youtube returned None

    def test_bad_livestream_url_logs_warning(
        self, plugin_config: dict[str, Any], caplog: pytest.LogCaptureFixture
    ) -> None:
        plugin, _ = self._make_plugin_with_youtube(plugin_config)
        context = HookContext(hook=Hook.ON_GAME_READY, data={})
        context.shared["livestreams"] = {"google": "https://youtube.com/channel/bad"}
        context.shared["livestream_metadata"] = {"title": "AI Title", "description": "AI Desc"}

        with caplog.at_level(logging.WARNING):
            plugin.on_game_ready(context)

        assert "could not extract broadcast ID" in caplog.text

    def test_registered(self) -> None:
        plugin = GooglePlugin()
        registry = HookRegistry()
        plugin.register(registry)
        assert registry.has_handlers(Hook.ON_GAME_READY)


class TestIntegrationWithRegistry:
    def test_full_lifecycle(self, plugin_config: dict[str, Any]) -> None:
        """Simulate the full plugin lifecycle: init -> register -> emit."""
        plugin = GooglePlugin(plugin_config)
        registry = HookRegistry()
        plugin.register(registry)

        game_info = FakeGameInfo(home_team="Storm", away_team="Thunder")
        context = HookContext(hook=Hook.ON_GAME_INIT, data={"game_info": game_info})

        with (
            patch("reeln_google_plugin.plugin.auth.get_credentials", return_value=MagicMock()),
            patch("reeln_google_plugin.plugin.auth.build_youtube_service", return_value=MagicMock()),
            patch(
                "reeln_google_plugin.plugin.livestream.create_livestream",
                return_value="https://youtube.com/live/lifecycle-test",
            ),
        ):
            registry.emit(Hook.ON_GAME_INIT, context)

        assert context.shared["livestreams"]["google"] == "https://youtube.com/live/lifecycle-test"


class TestOnGameInitPlaylist:
    def test_disabled_by_default(self) -> None:
        """When manage_playlists is not set (default False), no playlist created."""
        plugin = GooglePlugin({"client_secrets_file": "/tmp/secrets.json"})
        game_info = FakeGameInfo()
        context = HookContext(hook=Hook.ON_GAME_INIT, data={"game_info": game_info})

        plugin.on_game_init(context)

        assert "playlists" not in context.shared

    def test_enabled_creates_playlist(self, playlist_config: dict[str, Any]) -> None:
        plugin = GooglePlugin(playlist_config)
        game_info = FakeGameInfo()
        context = HookContext(hook=Hook.ON_GAME_INIT, data={"game_info": game_info})

        with (
            patch("reeln_google_plugin.plugin.auth.get_credentials", return_value=MagicMock()),
            patch("reeln_google_plugin.plugin.auth.build_youtube_service", return_value=MagicMock()),
            patch(
                "reeln_google_plugin.plugin.playlist.setup_playlist",
                return_value="PL-GAME",
            ) as mock_setup,
        ):
            plugin.on_game_init(context)

        assert context.shared["playlists"]["google"] == "PL-GAME"
        mock_setup.assert_called_once()
        assert mock_setup.call_args[1]["video_id"] is None

    def test_both_flags_extracts_video_id(self, plugin_config: dict[str, Any]) -> None:
        """When both create_livestream and manage_playlists are True, video ID is extracted."""
        plugin_config["manage_playlists"] = True
        plugin = GooglePlugin(plugin_config)
        game_info = FakeGameInfo()
        context = HookContext(hook=Hook.ON_GAME_INIT, data={"game_info": game_info})

        with (
            patch("reeln_google_plugin.plugin.auth.get_credentials", return_value=MagicMock()),
            patch("reeln_google_plugin.plugin.auth.build_youtube_service", return_value=MagicMock()),
            patch(
                "reeln_google_plugin.plugin.livestream.create_livestream",
                return_value="https://youtube.com/live/vid123",
            ),
            patch(
                "reeln_google_plugin.plugin.playlist.setup_playlist",
                return_value="PL-BOTH",
            ) as mock_setup,
        ):
            plugin.on_game_init(context)

        assert context.shared["livestreams"]["google"] == "https://youtube.com/live/vid123"
        assert context.shared["playlists"]["google"] == "PL-BOTH"
        assert mock_setup.call_args[1]["video_id"] == "vid123"

    def test_playlist_only_no_livestream(self, playlist_config: dict[str, Any]) -> None:
        """Playlist-only mode: create_livestream=False, manage_playlists=True."""
        plugin = GooglePlugin(playlist_config)
        game_info = FakeGameInfo()
        context = HookContext(hook=Hook.ON_GAME_INIT, data={"game_info": game_info})

        with (
            patch("reeln_google_plugin.plugin.auth.get_credentials", return_value=MagicMock()),
            patch("reeln_google_plugin.plugin.auth.build_youtube_service", return_value=MagicMock()),
            patch(
                "reeln_google_plugin.plugin.playlist.setup_playlist",
                return_value="PL-ONLY",
            ) as mock_setup,
        ):
            plugin.on_game_init(context)

        assert "livestreams" not in context.shared
        assert context.shared["playlists"]["google"] == "PL-ONLY"
        assert mock_setup.call_args[1]["video_id"] is None

    def test_invalid_url_logs_warning(
        self, plugin_config: dict[str, Any], caplog: pytest.LogCaptureFixture
    ) -> None:
        """Invalid livestream URL logs warning but still creates playlist."""
        plugin_config["manage_playlists"] = True
        plugin = GooglePlugin(plugin_config)
        game_info = FakeGameInfo()
        context = HookContext(hook=Hook.ON_GAME_INIT, data={"game_info": game_info})

        with (
            patch("reeln_google_plugin.plugin.auth.get_credentials", return_value=MagicMock()),
            patch("reeln_google_plugin.plugin.auth.build_youtube_service", return_value=MagicMock()),
            patch(
                "reeln_google_plugin.plugin.livestream.create_livestream",
                return_value="https://youtube.com/channel/bad",
            ),
            patch(
                "reeln_google_plugin.plugin.playlist.setup_playlist",
                return_value="PL-WARN",
            ) as mock_setup,
            caplog.at_level(logging.WARNING),
        ):
            plugin.on_game_init(context)

        assert "could not extract video ID" in caplog.text
        assert context.shared["playlists"]["google"] == "PL-WARN"
        assert mock_setup.call_args[1]["video_id"] is None

    def test_playlist_error_logs_warning(
        self, playlist_config: dict[str, Any], caplog: pytest.LogCaptureFixture
    ) -> None:
        plugin = GooglePlugin(playlist_config)
        game_info = FakeGameInfo()
        context = HookContext(hook=Hook.ON_GAME_INIT, data={"game_info": game_info})

        with (
            patch("reeln_google_plugin.plugin.auth.get_credentials", return_value=MagicMock()),
            patch("reeln_google_plugin.plugin.auth.build_youtube_service", return_value=MagicMock()),
            patch(
                "reeln_google_plugin.plugin.playlist.setup_playlist",
                side_effect=PlaylistError("api error"),
            ),
            caplog.at_level(logging.WARNING),
        ):
            plugin.on_game_init(context)

        assert "playlist creation failed" in caplog.text
        assert "playlists" not in context.shared

    def test_playlist_only_authenticates(self, playlist_config: dict[str, Any]) -> None:
        """Playlist-only mode still performs authentication."""
        plugin = GooglePlugin(playlist_config)
        game_info = FakeGameInfo()
        context = HookContext(hook=Hook.ON_GAME_INIT, data={"game_info": game_info})

        with (
            patch("reeln_google_plugin.plugin.auth.get_credentials", return_value=MagicMock()) as mock_get_creds,
            patch("reeln_google_plugin.plugin.auth.build_youtube_service", return_value=MagicMock()),
            patch(
                "reeln_google_plugin.plugin.playlist.setup_playlist",
                return_value="PL-AUTH",
            ),
        ):
            plugin.on_game_init(context)

        mock_get_creds.assert_called_once()

    def test_neither_flag_returns_early(self) -> None:
        """When both flags are False, on_game_init returns immediately."""
        plugin = GooglePlugin({
            "client_secrets_file": "/tmp/secrets.json",
            "create_livestream": False,
            "manage_playlists": False,
        })
        game_info = FakeGameInfo()
        context = HookContext(hook=Hook.ON_GAME_INIT, data={"game_info": game_info})

        plugin.on_game_init(context)

        assert "livestreams" not in context.shared
        assert "playlists" not in context.shared

    def test_logs_info_on_success(
        self, playlist_config: dict[str, Any], caplog: pytest.LogCaptureFixture
    ) -> None:
        plugin = GooglePlugin(playlist_config)
        game_info = FakeGameInfo()
        context = HookContext(hook=Hook.ON_GAME_INIT, data={"game_info": game_info})

        with (
            patch("reeln_google_plugin.plugin.auth.get_credentials", return_value=MagicMock()),
            patch("reeln_google_plugin.plugin.auth.build_youtube_service", return_value=MagicMock()),
            patch(
                "reeln_google_plugin.plugin.playlist.setup_playlist",
                return_value="PL-LOG",
            ),
            caplog.at_level(logging.INFO),
        ):
            plugin.on_game_init(context)

        assert "playlist ready" in caplog.text

    def test_caches_playlist_id(self, playlist_config: dict[str, Any]) -> None:
        plugin = GooglePlugin(playlist_config)
        game_info = FakeGameInfo()
        context = HookContext(hook=Hook.ON_GAME_INIT, data={"game_info": game_info})

        with (
            patch("reeln_google_plugin.plugin.auth.get_credentials", return_value=MagicMock()),
            patch("reeln_google_plugin.plugin.auth.build_youtube_service", return_value=MagicMock()),
            patch(
                "reeln_google_plugin.plugin.playlist.setup_playlist",
                return_value="PL-CACHED",
            ),
        ):
            plugin.on_game_init(context)

        assert plugin._playlist_id == "PL-CACHED"


class TestEnsureYoutube:
    def test_cached_returns_existing(self, plugin_config: dict[str, Any]) -> None:
        plugin = GooglePlugin(plugin_config)
        mock_yt = MagicMock()
        plugin._youtube = mock_yt

        result = plugin._ensure_youtube()

        assert result is mock_yt

    def test_auth_on_miss(self, plugin_config: dict[str, Any]) -> None:
        plugin = GooglePlugin(plugin_config)

        with (
            patch("reeln_google_plugin.plugin.auth.get_credentials", return_value=MagicMock()),
            patch("reeln_google_plugin.plugin.auth.build_youtube_service", return_value=MagicMock()) as mock_build,
        ):
            result = plugin._ensure_youtube()

        assert result is mock_build.return_value
        assert plugin._youtube is result

    def test_none_on_auth_error(self, plugin_config: dict[str, Any]) -> None:
        plugin = GooglePlugin(plugin_config)

        with patch(
            "reeln_google_plugin.plugin.auth.get_credentials",
            side_effect=AuthError("fail"),
        ):
            result = plugin._ensure_youtube()

        assert result is None
        assert plugin._youtube is None

    def test_none_on_missing_client_secrets(self) -> None:
        plugin = GooglePlugin({})
        result = plugin._ensure_youtube()
        assert result is None


class TestOnHighlightsMerged:
    def test_disabled_by_default(self) -> None:
        plugin = GooglePlugin({})
        context = HookContext(hook=Hook.ON_HIGHLIGHTS_MERGED, data={"output": "/tmp/out.mp4"})
        plugin.on_highlights_merged(context)
        assert "uploads" not in context.shared

    def test_full_upload_flow(self, upload_config: dict[str, Any], tmp_path: Path) -> None:
        video_file = tmp_path / "highlights.mp4"
        video_file.write_text("fake")

        plugin = GooglePlugin(upload_config)
        plugin._game_info = FakeGameInfo()
        mock_yt = MagicMock()
        plugin._youtube = mock_yt

        context = HookContext(
            hook=Hook.ON_HIGHLIGHTS_MERGED, data={"output": str(video_file)}
        )

        with patch(
            "reeln_google_plugin.plugin.upload.upload_video",
            return_value=("vid1", "https://youtube.com/watch?v=vid1"),
        ):
            plugin.on_highlights_merged(context)

        assert context.shared["uploads"]["google"]["video_id"] == "vid1"
        assert context.shared["uploads"]["google"]["url"] == "https://youtube.com/watch?v=vid1"

    def test_no_output_logs_warning(
        self, upload_config: dict[str, Any], caplog: pytest.LogCaptureFixture
    ) -> None:
        plugin = GooglePlugin(upload_config)
        context = HookContext(hook=Hook.ON_HIGHLIGHTS_MERGED, data={})

        with caplog.at_level(logging.WARNING):
            plugin.on_highlights_merged(context)

        assert "no output" in caplog.text

    def test_auth_failure(self, upload_config: dict[str, Any]) -> None:
        plugin = GooglePlugin(upload_config)
        context = HookContext(
            hook=Hook.ON_HIGHLIGHTS_MERGED, data={"output": "/tmp/out.mp4"}
        )

        with patch(
            "reeln_google_plugin.plugin.auth.get_credentials",
            side_effect=AuthError("fail"),
        ):
            plugin.on_highlights_merged(context)

        assert "uploads" not in context.shared

    def test_upload_error(
        self, upload_config: dict[str, Any], caplog: pytest.LogCaptureFixture
    ) -> None:
        plugin = GooglePlugin(upload_config)
        plugin._youtube = MagicMock()
        context = HookContext(
            hook=Hook.ON_HIGHLIGHTS_MERGED, data={"output": "/tmp/out.mp4"}
        )

        with (
            patch(
                "reeln_google_plugin.plugin.upload.upload_video",
                side_effect=UploadError("upload failed"),
            ),
            caplog.at_level(logging.WARNING),
        ):
            plugin.on_highlights_merged(context)

        assert "highlights upload failed" in caplog.text
        assert "uploads" not in context.shared

    def test_metadata_from_shared(self, upload_config: dict[str, Any], tmp_path: Path) -> None:
        video_file = tmp_path / "highlights.mp4"
        video_file.write_text("fake")

        plugin = GooglePlugin(upload_config)
        plugin._youtube = MagicMock()

        context = HookContext(
            hook=Hook.ON_HIGHLIGHTS_MERGED,
            data={"output": str(video_file)},
            shared={
                "uploads": {
                    "google": {
                        "title": "LLM Title",
                        "description": "LLM Desc",
                        "tags": ["llm"],
                    }
                }
            },
        )

        with patch(
            "reeln_google_plugin.plugin.upload.upload_video",
            return_value=("vid1", "https://youtube.com/watch?v=vid1"),
        ) as mock_upload:
            plugin.on_highlights_merged(context)

        call_kwargs = mock_upload.call_args[1]
        assert call_kwargs["title"] == "LLM Title"
        assert call_kwargs["description"] == "LLM Desc"
        assert call_kwargs["tags"] == ["llm"]

    def test_metadata_fallback_to_game_info(
        self, upload_config: dict[str, Any], tmp_path: Path
    ) -> None:
        video_file = tmp_path / "highlights.mp4"
        video_file.write_text("fake")

        plugin = GooglePlugin(upload_config)
        plugin._youtube = MagicMock()
        plugin._game_info = FakeGameInfo(description="Game desc")

        context = HookContext(
            hook=Hook.ON_HIGHLIGHTS_MERGED, data={"output": str(video_file)}
        )

        with patch(
            "reeln_google_plugin.plugin.upload.upload_video",
            return_value=("vid1", "https://youtube.com/watch?v=vid1"),
        ) as mock_upload:
            plugin.on_highlights_merged(context)

        call_kwargs = mock_upload.call_args[1]
        assert call_kwargs["title"] == "Eagles vs Hawks - 2026-01-15"
        assert call_kwargs["description"] == "Game desc"

    def test_auto_add_to_playlist(self, upload_config: dict[str, Any], tmp_path: Path) -> None:
        video_file = tmp_path / "highlights.mp4"
        video_file.write_text("fake")

        upload_config["manage_playlists"] = True
        plugin = GooglePlugin(upload_config)
        plugin._youtube = MagicMock()
        plugin._playlist_id = "PL-123"

        context = HookContext(
            hook=Hook.ON_HIGHLIGHTS_MERGED, data={"output": str(video_file)}
        )

        with (
            patch(
                "reeln_google_plugin.plugin.upload.upload_video",
                return_value=("vid1", "https://youtube.com/watch?v=vid1"),
            ),
            patch(
                "reeln_google_plugin.plugin.playlist.insert_video_into_playlist"
            ) as mock_insert,
        ):
            plugin.on_highlights_merged(context)

        mock_insert.assert_called_once_with(
            plugin._youtube, playlist_id="PL-123", video_id="vid1"
        )

    def test_playlist_error_non_fatal(
        self, upload_config: dict[str, Any], tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        video_file = tmp_path / "highlights.mp4"
        video_file.write_text("fake")

        upload_config["manage_playlists"] = True
        plugin = GooglePlugin(upload_config)
        plugin._youtube = MagicMock()
        plugin._playlist_id = "PL-123"

        context = HookContext(
            hook=Hook.ON_HIGHLIGHTS_MERGED, data={"output": str(video_file)}
        )

        with (
            patch(
                "reeln_google_plugin.plugin.upload.upload_video",
                return_value=("vid1", "https://youtube.com/watch?v=vid1"),
            ),
            patch(
                "reeln_google_plugin.plugin.playlist.insert_video_into_playlist",
                side_effect=PlaylistError("insert failed"),
            ),
            caplog.at_level(logging.WARNING),
        ):
            plugin.on_highlights_merged(context)

        assert "playlist insert failed" in caplog.text
        assert context.shared["uploads"]["google"]["video_id"] == "vid1"

    def test_config_values_passed(self, upload_config: dict[str, Any], tmp_path: Path) -> None:
        video_file = tmp_path / "highlights.mp4"
        video_file.write_text("fake")

        upload_config["category_id"] = "17"
        upload_config["privacy_status"] = "public"
        plugin = GooglePlugin(upload_config)
        plugin._youtube = MagicMock()

        context = HookContext(
            hook=Hook.ON_HIGHLIGHTS_MERGED, data={"output": str(video_file)}
        )

        with patch(
            "reeln_google_plugin.plugin.upload.upload_video",
            return_value=("vid1", "https://youtube.com/watch?v=vid1"),
        ) as mock_upload:
            plugin.on_highlights_merged(context)

        call_kwargs = mock_upload.call_args[1]
        assert call_kwargs["category_id"] == "17"
        assert call_kwargs["privacy_status"] == "public"

    def test_recording_date_from_game_info(
        self, upload_config: dict[str, Any], tmp_path: Path
    ) -> None:
        video_file = tmp_path / "highlights.mp4"
        video_file.write_text("fake")

        plugin = GooglePlugin(upload_config)
        plugin._youtube = MagicMock()
        plugin._game_info = FakeGameInfo(date="2026-03-06")

        context = HookContext(
            hook=Hook.ON_HIGHLIGHTS_MERGED, data={"output": str(video_file)}
        )

        with patch(
            "reeln_google_plugin.plugin.upload.upload_video",
            return_value=("vid1", "https://youtube.com/watch?v=vid1"),
        ) as mock_upload:
            plugin.on_highlights_merged(context)

        assert mock_upload.call_args[1]["recording_date"] == "2026-03-06"

    def test_no_playlist_insert_when_flag_off(
        self, upload_config: dict[str, Any], tmp_path: Path
    ) -> None:
        video_file = tmp_path / "highlights.mp4"
        video_file.write_text("fake")

        plugin = GooglePlugin(upload_config)
        plugin._youtube = MagicMock()
        plugin._playlist_id = "PL-123"

        context = HookContext(
            hook=Hook.ON_HIGHLIGHTS_MERGED, data={"output": str(video_file)}
        )

        with (
            patch(
                "reeln_google_plugin.plugin.upload.upload_video",
                return_value=("vid1", "https://youtube.com/watch?v=vid1"),
            ),
            patch(
                "reeln_google_plugin.plugin.playlist.insert_video_into_playlist"
            ) as mock_insert,
        ):
            plugin.on_highlights_merged(context)

        mock_insert.assert_not_called()

    def test_no_playlist_insert_when_no_playlist_id(
        self, upload_config: dict[str, Any], tmp_path: Path
    ) -> None:
        video_file = tmp_path / "highlights.mp4"
        video_file.write_text("fake")

        upload_config["manage_playlists"] = True
        plugin = GooglePlugin(upload_config)
        plugin._youtube = MagicMock()

        context = HookContext(
            hook=Hook.ON_HIGHLIGHTS_MERGED, data={"output": str(video_file)}
        )

        with (
            patch(
                "reeln_google_plugin.plugin.upload.upload_video",
                return_value=("vid1", "https://youtube.com/watch?v=vid1"),
            ),
            patch(
                "reeln_google_plugin.plugin.playlist.insert_video_into_playlist"
            ) as mock_insert,
        ):
            plugin.on_highlights_merged(context)

        mock_insert.assert_not_called()


class TestOnPostRender:
    def test_disabled_by_default(self) -> None:
        plugin = GooglePlugin({})
        context = HookContext(hook=Hook.POST_RENDER, data={})
        plugin.on_post_render(context)
        assert "uploads" not in context.shared

    def test_non_short_skipped(self, shorts_config: dict[str, Any]) -> None:
        """When plan.filter_complex is None, skip (not a short)."""
        plugin = GooglePlugin(shorts_config)
        plugin._youtube = MagicMock()

        plan = MagicMock()
        plan.filter_complex = None
        result = MagicMock()

        context = HookContext(
            hook=Hook.POST_RENDER, data={"plan": plan, "result": result}
        )

        plugin.on_post_render(context)
        assert "uploads" not in context.shared

    def test_full_short_upload_flow(
        self, shorts_config: dict[str, Any], tmp_path: Path
    ) -> None:
        video_file = tmp_path / "short.mp4"
        video_file.write_text("fake short")

        plugin = GooglePlugin(shorts_config)
        plugin._youtube = MagicMock()

        plan = MagicMock()
        plan.filter_complex = "some_filter"
        plan.output = MagicMock()
        plan.output.stem = "clip_001"
        result = MagicMock()
        result.output = str(video_file)

        context = HookContext(
            hook=Hook.POST_RENDER, data={"plan": plan, "result": result}
        )

        with patch(
            "reeln_google_plugin.plugin.upload.upload_short",
            return_value=("short1", "https://youtube.com/watch?v=short1"),
        ):
            plugin.on_post_render(context)

        shorts_list = context.shared["uploads"]["google"]["shorts"]
        assert len(shorts_list) == 1
        assert shorts_list[0]["video_id"] == "short1"

    def test_no_plan_skipped(self, shorts_config: dict[str, Any]) -> None:
        plugin = GooglePlugin(shorts_config)
        context = HookContext(hook=Hook.POST_RENDER, data={"result": MagicMock()})
        plugin.on_post_render(context)
        assert "uploads" not in context.shared

    def test_no_result_skipped(self, shorts_config: dict[str, Any]) -> None:
        plugin = GooglePlugin(shorts_config)
        context = HookContext(hook=Hook.POST_RENDER, data={"plan": MagicMock()})
        plugin.on_post_render(context)
        assert "uploads" not in context.shared

    def test_file_not_found(
        self, shorts_config: dict[str, Any], caplog: pytest.LogCaptureFixture
    ) -> None:
        plugin = GooglePlugin(shorts_config)
        plugin._youtube = MagicMock()

        plan = MagicMock()
        plan.filter_complex = "filter"
        result = MagicMock()
        result.output = "/nonexistent/short.mp4"

        context = HookContext(
            hook=Hook.POST_RENDER, data={"plan": plan, "result": result}
        )

        with caplog.at_level(logging.WARNING):
            plugin.on_post_render(context)

        assert "output missing" in caplog.text

    def test_upload_error(
        self, shorts_config: dict[str, Any], tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        video_file = tmp_path / "short.mp4"
        video_file.write_text("fake short")

        plugin = GooglePlugin(shorts_config)
        plugin._youtube = MagicMock()

        plan = MagicMock()
        plan.filter_complex = "filter"
        result = MagicMock()
        result.output = str(video_file)

        context = HookContext(
            hook=Hook.POST_RENDER, data={"plan": plan, "result": result}
        )

        with (
            patch(
                "reeln_google_plugin.plugin.upload.upload_short",
                side_effect=UploadError("short failed"),
            ),
            caplog.at_level(logging.WARNING),
        ):
            plugin.on_post_render(context)

        assert "short upload failed" in caplog.text

    def test_shorts_list_appended(
        self, shorts_config: dict[str, Any], tmp_path: Path
    ) -> None:
        video_file = tmp_path / "short.mp4"
        video_file.write_text("fake short")

        plugin = GooglePlugin(shorts_config)
        plugin._youtube = MagicMock()

        plan = MagicMock()
        plan.filter_complex = "filter"
        plan.output = MagicMock()
        plan.output.stem = "clip_001"
        result = MagicMock()
        result.output = str(video_file)

        context = HookContext(
            hook=Hook.POST_RENDER, data={"plan": plan, "result": result}
        )

        with patch(
            "reeln_google_plugin.plugin.upload.upload_short",
            return_value=("s1", "https://youtube.com/watch?v=s1"),
        ):
            plugin.on_post_render(context)

        with patch(
            "reeln_google_plugin.plugin.upload.upload_short",
            return_value=("s2", "https://youtube.com/watch?v=s2"),
        ):
            plugin.on_post_render(context)

        shorts_list = context.shared["uploads"]["google"]["shorts"]
        assert len(shorts_list) == 2
        assert shorts_list[0]["video_id"] == "s1"
        assert shorts_list[1]["video_id"] == "s2"

    def test_metadata_resolution(
        self, shorts_config: dict[str, Any], tmp_path: Path
    ) -> None:
        video_file = tmp_path / "short.mp4"
        video_file.write_text("fake short")

        plugin = GooglePlugin(shorts_config)
        plugin._youtube = MagicMock()
        plugin._game_info = FakeGameInfo()

        plan = MagicMock()
        plan.filter_complex = "filter"
        plan.output = MagicMock()
        plan.output.stem = "goal_1"
        result = MagicMock()
        result.output = str(video_file)

        context = HookContext(
            hook=Hook.POST_RENDER, data={"plan": plan, "result": result}
        )

        with patch(
            "reeln_google_plugin.plugin.upload.upload_short",
            return_value=("s1", "https://youtube.com/watch?v=s1"),
        ) as mock_upload:
            plugin.on_post_render(context)

        call_kwargs = mock_upload.call_args[1]
        assert call_kwargs["title"] == "Eagles vs Hawks - 2026-01-15 - goal_1"

    def test_metadata_from_shared(
        self, shorts_config: dict[str, Any], tmp_path: Path
    ) -> None:
        video_file = tmp_path / "short.mp4"
        video_file.write_text("fake short")

        plugin = GooglePlugin(shorts_config)
        plugin._youtube = MagicMock()

        plan = MagicMock()
        plan.filter_complex = "filter"
        result_obj = MagicMock()
        result_obj.output = str(video_file)

        context = HookContext(
            hook=Hook.POST_RENDER,
            data={"plan": plan, "result": result_obj},
            shared={
                "uploads": {
                    "google": {
                        "short_title": "Custom Short",
                        "short_description": "Custom Desc",
                    }
                }
            },
        )

        with patch(
            "reeln_google_plugin.plugin.upload.upload_short",
            return_value=("s1", "https://youtube.com/watch?v=s1"),
        ) as mock_upload:
            plugin.on_post_render(context)

        call_kwargs = mock_upload.call_args[1]
        assert call_kwargs["title"] == "Custom Short"
        assert call_kwargs["description"] == "Custom Desc"

    def test_auth_failure(self, shorts_config: dict[str, Any], tmp_path: Path) -> None:
        video_file = tmp_path / "short.mp4"
        video_file.write_text("fake short")

        plugin = GooglePlugin(shorts_config)

        plan = MagicMock()
        plan.filter_complex = "filter"
        result = MagicMock()
        result.output = str(video_file)

        context = HookContext(
            hook=Hook.POST_RENDER, data={"plan": plan, "result": result}
        )

        with patch(
            "reeln_google_plugin.plugin.auth.get_credentials",
            side_effect=AuthError("fail"),
        ):
            plugin.on_post_render(context)

        assert "uploads" not in context.shared

    def test_result_output_none(self, shorts_config: dict[str, Any], caplog: pytest.LogCaptureFixture) -> None:
        plugin = GooglePlugin(shorts_config)
        plugin._youtube = MagicMock()

        plan = MagicMock()
        plan.filter_complex = "filter"
        result = MagicMock()
        result.output = None

        context = HookContext(
            hook=Hook.POST_RENDER, data={"plan": plan, "result": result}
        )

        with caplog.at_level(logging.WARNING):
            plugin.on_post_render(context)

        assert "output missing" in caplog.text


class TestOnGameFinish:
    def test_resets_cached_state(self) -> None:
        plugin = GooglePlugin()
        plugin._game_info = FakeGameInfo()
        plugin._youtube = MagicMock()
        plugin._playlist_id = "PL-123"

        context = HookContext(hook=Hook.ON_GAME_FINISH, data={})
        plugin.on_game_finish(context)

        assert plugin._game_info is None
        assert plugin._youtube is None
        assert plugin._playlist_id is None


class TestResolveUploadMetadata:
    def test_shared_context_preferred(self) -> None:
        plugin = GooglePlugin()
        plugin._game_info = FakeGameInfo()
        context = HookContext(
            hook=Hook.ON_HIGHLIGHTS_MERGED,
            data={},
            shared={
                "uploads": {
                    "google": {
                        "title": "LLM Title",
                        "description": "LLM Desc",
                        "tags": ["tag1"],
                    }
                }
            },
        )

        metadata = plugin._resolve_upload_metadata(context)
        assert metadata["title"] == "LLM Title"
        assert metadata["description"] == "LLM Desc"
        assert metadata["tags"] == ["tag1"]

    def test_fallback_to_game_info(self) -> None:
        plugin = GooglePlugin()
        plugin._game_info = FakeGameInfo(description="Game desc")
        context = HookContext(hook=Hook.ON_HIGHLIGHTS_MERGED, data={})

        metadata = plugin._resolve_upload_metadata(context)
        assert metadata["title"] == "Eagles vs Hawks - 2026-01-15"
        assert metadata["description"] == "Game desc"
        assert metadata["tags"] is None

    def test_no_game_info_default(self) -> None:
        plugin = GooglePlugin()
        context = HookContext(hook=Hook.ON_HIGHLIGHTS_MERGED, data={})

        metadata = plugin._resolve_upload_metadata(context)
        assert metadata["title"] == "Highlights"
        assert metadata["description"] == ""
        assert metadata["tags"] is None


class TestResolveShortMetadata:
    def test_shared_context(self) -> None:
        plugin = GooglePlugin()
        context = HookContext(
            hook=Hook.POST_RENDER,
            data={},
            shared={
                "uploads": {
                    "google": {
                        "short_title": "Custom",
                        "short_description": "Desc",
                        "tags": ["t1"],
                    }
                }
            },
        )

        metadata = plugin._resolve_short_metadata(context)
        assert metadata["title"] == "Custom"
        assert metadata["description"] == "Desc"
        assert metadata["tags"] == ["t1"]

    def test_fallback_game_info_with_plan_stem(self) -> None:
        plugin = GooglePlugin()
        plugin._game_info = FakeGameInfo()
        plan = MagicMock()
        plan.output = MagicMock()
        plan.output.stem = "goal_1"
        context = HookContext(
            hook=Hook.POST_RENDER, data={"plan": plan}
        )

        metadata = plugin._resolve_short_metadata(context)
        assert metadata["title"] == "Eagles vs Hawks - 2026-01-15 - goal_1"
        assert metadata["description"] == ""

    def test_no_game_info_no_plan(self) -> None:
        plugin = GooglePlugin()
        context = HookContext(hook=Hook.POST_RENDER, data={})

        metadata = plugin._resolve_short_metadata(context)
        assert metadata["title"] == "Highlight"
        assert metadata["description"] == ""

    def test_game_info_no_stem(self) -> None:
        plugin = GooglePlugin()
        plugin._game_info = FakeGameInfo()
        plan = MagicMock()
        plan.output = None
        context = HookContext(
            hook=Hook.POST_RENDER, data={"plan": plan}
        )

        metadata = plugin._resolve_short_metadata(context)
        assert metadata["title"] == "Eagles vs Hawks - 2026-01-15"


class TestResolveRecordingDate:
    def test_with_game_info(self) -> None:
        plugin = GooglePlugin()
        plugin._game_info = FakeGameInfo(date="2026-03-06")
        assert plugin._resolve_recording_date() == "2026-03-06"

    def test_without_game_info(self) -> None:
        plugin = GooglePlugin()
        assert plugin._resolve_recording_date() is None

    def test_empty_date(self) -> None:
        plugin = GooglePlugin()
        plugin._game_info = FakeGameInfo(date="")
        assert plugin._resolve_recording_date() is None
