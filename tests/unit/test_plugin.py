"""Tests for plugin module."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from reeln.plugins.hooks import Hook, HookContext
from reeln.plugins.registry import HookRegistry

from reeln_google_plugin.auth import AuthError
from reeln_google_plugin.livestream import LivestreamError
from reeln_google_plugin.plugin import GooglePlugin
from tests.conftest import FakeGameInfo


class TestGooglePluginAttributes:
    def test_name(self) -> None:
        plugin = GooglePlugin()
        assert plugin.name == "google"

    def test_version(self) -> None:
        plugin = GooglePlugin()
        assert plugin.version == "0.3.0"

    def test_api_version(self) -> None:
        plugin = GooglePlugin()
        assert plugin.api_version == 1


class TestGooglePluginConfigSchema:
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


class TestGooglePluginRegister:
    def test_registers_on_game_init(self) -> None:
        plugin = GooglePlugin()
        registry = HookRegistry()
        plugin.register(registry)
        assert registry.has_handlers(Hook.ON_GAME_INIT)

    def test_does_not_register_other_hooks(self) -> None:
        plugin = GooglePlugin()
        registry = HookRegistry()
        plugin.register(registry)
        assert not registry.has_handlers(Hook.ON_GAME_FINISH)


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
        game_info = FakeGameInfo(date="2026-03-04", game_time="7:00 PM CST")
        result = plugin._build_scheduled_start(game_info)
        assert result is not None
        assert "2026-03-04" in result
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
        game_info = FakeGameInfo(date="2026-03-04", game_time="7:00 PM EST")
        result = plugin._build_scheduled_start(game_info)
        assert result is not None
        assert "19:00:00" in result

    def test_no_timezone(self) -> None:
        plugin = GooglePlugin()
        game_info = FakeGameInfo(date="2026-03-04", game_time="7:00 PM")
        result = plugin._build_scheduled_start(game_info)
        assert result is not None
        assert "19:00:00" in result


class TestOnGameInit:
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
        game_info = FakeGameInfo(date="2026-03-04", game_time="7:00 PM CST")
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
        assert "2026-03-04" in scheduled
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
        plugin = GooglePlugin({})
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
        config = {"client_secrets_file": str(client_secrets_file)}
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
