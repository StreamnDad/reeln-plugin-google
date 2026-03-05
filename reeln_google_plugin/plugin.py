"""GooglePlugin — reeln-cli plugin for Google platform integration."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from reeln.models.plugin_schema import ConfigField, PluginConfigSchema
from reeln.plugins.hooks import Hook, HookContext
from reeln.plugins.registry import HookRegistry

from reeln_google_plugin import auth, livestream

log: logging.Logger = logging.getLogger(__name__)


class GooglePlugin:
    """Plugin that provides Google platform integration for reeln-cli.

    Subscribes to ``ON_GAME_INIT`` to create a YouTube livestream broadcast
    and writes the livestream URL to ``context.shared["livestreams"]["google"]``.
    """

    name: str = "google"
    version: str = "0.3.0"
    api_version: int = 1

    config_schema: PluginConfigSchema = PluginConfigSchema(
        fields=(
            ConfigField(
                name="client_secrets_file",
                field_type="str",
                required=True,
                description="Path to GCP OAuth client secrets JSON",
            ),
            ConfigField(
                name="credentials_cache",
                field_type="str",
                description="OAuth credentials cache path (default: data_dir/google/oauth.json)",
            ),
            ConfigField(
                name="privacy_status",
                field_type="str",
                default="unlisted",
                description="Livestream privacy status (public, unlisted, private)",
            ),
            ConfigField(
                name="category_id",
                field_type="str",
                default="20",
                description="YouTube category ID (20 = Gaming)",
            ),
            ConfigField(
                name="tags",
                field_type="list",
                default=[],
                description="Default video tags",
            ),
            ConfigField(
                name="scopes",
                field_type="list",
                description="OAuth scopes (default: youtube, youtube.upload, youtube.force-ssl)",
            ),
        )
    )

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self._config: dict[str, Any] = config or {}

    def register(self, registry: HookRegistry) -> None:
        """Register hook handlers with the reeln plugin registry."""
        registry.register(Hook.ON_GAME_INIT, self.on_game_init)

    def on_game_init(self, context: HookContext) -> None:
        """Handle ``ON_GAME_INIT`` — create a YouTube livestream broadcast."""
        game_info = context.data.get("game_info")
        if game_info is None:
            log.warning("Google plugin: no game_info in context, skipping")
            return

        title = self._build_title(game_info)
        privacy_status = self._config.get("privacy_status", "unlisted")

        client_secrets = self._config.get("client_secrets_file")
        if not client_secrets:
            log.warning("Google plugin: client_secrets_file not configured, skipping")
            return

        from pathlib import Path

        client_secrets_path = Path(client_secrets)
        credentials_cache_str = self._config.get("credentials_cache")
        credentials_cache = (
            Path(credentials_cache_str) if credentials_cache_str else auth.default_credentials_path()
        )
        scopes = self._config.get("scopes")

        try:
            creds = auth.get_credentials(
                client_secrets_path,
                credentials_cache,
                scopes=scopes,
            )
            youtube = auth.build_youtube_service(creds)
        except auth.AuthError as exc:
            log.warning("Google plugin: authentication failed: %s", exc)
            return

        description = getattr(game_info, "description", "")
        thumbnail_str = getattr(game_info, "thumbnail", "")
        thumbnail_path = Path(thumbnail_str) if thumbnail_str else None
        scheduled_start = self._build_scheduled_start(game_info)

        try:
            url = livestream.create_livestream(
                youtube,
                title=title,
                description=description,
                privacy_status=privacy_status,
                scheduled_start=scheduled_start,
                thumbnail_path=thumbnail_path,
            )
        except livestream.LivestreamError as exc:
            log.warning("Google plugin: livestream creation failed: %s", exc)
            return

        context.shared["livestreams"] = context.shared.get("livestreams", {})
        context.shared["livestreams"]["google"] = url
        log.info("Google plugin: created livestream %s", url)

    def _build_scheduled_start(self, game_info: object) -> str | None:
        """Build an ISO 8601 scheduled start time from game info.

        Combines ``game_info.date`` and ``game_info.game_time`` (e.g.
        ``"2026-03-04"`` + ``"7:00 PM CST"``) into an ISO 8601 string.
        Returns ``None`` if the fields are missing or cannot be parsed,
        which causes ``livestream.py`` to fall back to ``datetime.now()``.
        """
        date_str = getattr(game_info, "date", "")
        game_time = getattr(game_info, "game_time", "")
        if not date_str or not game_time:
            return None

        try:
            from dateutil import parser as dateutil_parser

            combined = f"{date_str} {game_time}"
            dt: datetime = dateutil_parser.parse(combined)
            return dt.isoformat()
        except Exception:
            log.warning("Google plugin: could not parse game time '%s %s', using default", date_str, game_time)
            return None

    def _build_title(self, game_info: object) -> str:
        """Build a livestream title from game info."""
        home_team = getattr(game_info, "home_team", "")
        away_team = getattr(game_info, "away_team", "")
        date = getattr(game_info, "date", "")
        venue = getattr(game_info, "venue", "")

        title = f"{home_team} vs {away_team} - {date}"
        if venue:
            title += f" @ {venue}"
        return title
