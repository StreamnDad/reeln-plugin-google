"""GooglePlugin — reeln-cli plugin for Google platform integration."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from reeln.models.plugin_schema import ConfigField, PluginConfigSchema
from reeln.plugins.hooks import Hook, HookContext
from reeln.plugins.registry import HookRegistry

from reeln_google_plugin import auth, livestream, playlist, upload
from reeln_google_plugin.livestream import LivestreamError
from reeln_google_plugin.playlist import PlaylistError
from reeln_google_plugin.upload import UploadError

log: logging.Logger = logging.getLogger(__name__)


class GooglePlugin:
    """Plugin that provides Google platform integration for reeln-cli.

    Subscribes to ``ON_GAME_INIT`` to create a YouTube livestream broadcast
    and writes the livestream URL to ``context.shared["livestreams"]["google"]``.
    """

    name: str = "google"
    version: str = "0.8.0"
    api_version: int = 1

    config_schema: PluginConfigSchema = PluginConfigSchema(
        fields=(
            ConfigField(
                name="create_livestream",
                field_type="bool",
                default=False,
                description="Enable YouTube livestream creation on game init",
            ),
            ConfigField(
                name="manage_playlists",
                field_type="bool",
                default=False,
                description="Enable game-specific playlist creation on game init",
            ),
            ConfigField(
                name="upload_highlights",
                field_type="bool",
                default=False,
                description="Enable YouTube highlights upload on highlights merged",
            ),
            ConfigField(
                name="upload_shorts",
                field_type="bool",
                default=False,
                description="Enable YouTube Shorts upload after short render",
            ),
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
        self._game_info: object | None = None
        self._youtube: Any = None
        self._playlist_id: str | None = None

    min_reeln_version: str = "0.0.31"

    def register(self, registry: HookRegistry) -> None:
        """Register hook handlers with the reeln plugin registry."""
        registry.register(Hook.ON_GAME_INIT, self.on_game_init)
        registry.register(Hook.ON_GAME_READY, self.on_game_ready)
        registry.register(Hook.ON_HIGHLIGHTS_MERGED, self.on_highlights_merged)
        registry.register(Hook.POST_RENDER, self.on_post_render)
        registry.register(Hook.ON_GAME_FINISH, self.on_game_finish)
        registry.register(Hook.ON_POST_GAME_FINISH, self.on_post_game_finish)

    def _ensure_youtube(self) -> Any:
        """Return cached YouTube service, or authenticate and cache.

        Returns ``None`` on auth failure or missing config.
        """
        if self._youtube is not None:
            return self._youtube

        client_secrets = self._config.get("client_secrets_file")
        if not client_secrets:
            log.warning("Google plugin: client_secrets_file not configured, skipping")
            return None

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
            self._youtube = auth.build_youtube_service(creds)
        except auth.AuthError as exc:
            log.warning("Google plugin: authentication failed: %s", exc)
            return None

        return self._youtube

    def on_game_init(self, context: HookContext) -> None:
        """Handle ``ON_GAME_INIT`` — create livestream and/or playlist."""
        create_ls = self._config.get("create_livestream", False)
        manage_pl = self._config.get("manage_playlists", False)
        if not create_ls and not manage_pl:
            return

        game_info = context.data.get("game_info")
        if game_info is None:
            log.warning("Google plugin: no game_info in context, skipping")
            return

        self._game_info = game_info
        title = self._build_title(game_info)
        privacy_status = self._config.get("privacy_status", "unlisted")

        youtube = self._ensure_youtube()
        if youtube is None:
            return

        if create_ls:
            from pathlib import Path

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

        if manage_pl:
            video_id = None
            livestream_url = context.shared.get("livestreams", {}).get("google")
            if livestream_url:
                try:
                    video_id = playlist.extract_video_id(livestream_url)
                except PlaylistError:
                    log.warning(
                        "Google plugin: could not extract video ID from %s, "
                        "playlist will be created without video",
                        livestream_url,
                    )

            try:
                playlist_id = playlist.setup_playlist(
                    youtube,
                    title=title,
                    privacy_status=privacy_status,
                    video_id=video_id,
                )
            except PlaylistError as exc:
                log.warning("Google plugin: playlist creation failed: %s", exc)
                return

            self._playlist_id = playlist_id
            context.shared["playlists"] = context.shared.get("playlists", {})
            context.shared["playlists"]["google"] = playlist_id
            log.info("Google plugin: playlist ready %s", playlist_id)

    def on_game_ready(self, context: HookContext) -> None:
        """Handle ``ON_GAME_READY`` — update broadcast/playlist with enriched metadata."""
        livestream_metadata = context.shared.get("livestream_metadata")
        if not livestream_metadata:
            return

        livestream_url = context.shared.get("livestreams", {}).get("google")
        if not livestream_url:
            return

        youtube = self._ensure_youtube()
        if youtube is None:
            return

        try:
            broadcast_id = playlist.extract_video_id(livestream_url)
        except PlaylistError:
            log.warning(
                "Google plugin: could not extract broadcast ID from %s, skipping update",
                livestream_url,
            )
            return

        from pathlib import Path

        # Resolve thumbnail from game_image
        game_image = context.shared.get("game_image", {})
        image_path_str = game_image.get("image_path", "") if isinstance(game_image, dict) else ""
        thumbnail_path = Path(image_path_str) if image_path_str else None

        try:
            livestream.update_broadcast(
                youtube,
                broadcast_id=broadcast_id,
                title=livestream_metadata.get("title", ""),
                description=livestream_metadata.get("description", ""),
                thumbnail_path=thumbnail_path,
                localizations=livestream_metadata.get("translations"),
            )
        except LivestreamError as exc:
            log.warning("Google plugin: broadcast update failed (non-fatal): %s", exc)

        # Update playlist if metadata is available
        playlist_metadata = context.shared.get("playlist_metadata")
        if playlist_metadata and self._playlist_id:
            try:
                playlist.update_playlist(
                    youtube,
                    playlist_id=self._playlist_id,
                    title=playlist_metadata.get("title", ""),
                    description=playlist_metadata.get("description", ""),
                    localizations=playlist_metadata.get("translations"),
                )
            except PlaylistError as exc:
                log.warning("Google plugin: playlist update failed (non-fatal): %s", exc)

    def on_highlights_merged(self, context: HookContext) -> None:
        """Handle ``ON_HIGHLIGHTS_MERGED`` — upload merged highlights video."""
        if not self._config.get("upload_highlights", False):
            return

        output = context.data.get("output")
        if output is None:
            log.warning("Google plugin: no output in highlights merged context, skipping")
            return

        youtube = self._ensure_youtube()
        if youtube is None:
            return

        from pathlib import Path

        metadata = self._resolve_upload_metadata(context)
        recording_date = self._resolve_recording_date()

        try:
            video_id, url = upload.upload_video(
                youtube,
                file_path=Path(output),
                title=metadata["title"],
                description=metadata["description"],
                tags=metadata["tags"],
                category_id=self._config.get("category_id", "20"),
                privacy_status=self._config.get("privacy_status", "unlisted"),
                recording_date=recording_date,
                made_for_kids=False,
            )
        except UploadError as exc:
            log.warning("Google plugin: highlights upload failed: %s", exc)
            return

        context.shared["uploads"] = context.shared.get("uploads", {})
        context.shared["uploads"]["google"] = {"video_id": video_id, "url": url}
        log.info("Google plugin: uploaded highlights %s", url)

        if self._config.get("manage_playlists", False) and self._playlist_id:
            try:
                playlist.insert_video_into_playlist(
                    youtube,
                    playlist_id=self._playlist_id,
                    video_id=video_id,
                )
            except PlaylistError as exc:
                log.warning("Google plugin: playlist insert failed (non-fatal): %s", exc)

    def on_post_render(self, context: HookContext) -> None:
        """Handle ``POST_RENDER`` — upload Shorts after render."""
        if not self._config.get("upload_shorts", False):
            return

        plan = context.data.get("plan")
        result = context.data.get("result")
        if plan is None or result is None:
            return

        if getattr(plan, "filter_complex", None) is None:
            return

        from pathlib import Path

        output = getattr(result, "output", None)
        if output is None or not Path(output).exists():
            log.warning("Google plugin: short render output missing or not found, skipping")
            return

        youtube = self._ensure_youtube()
        if youtube is None:
            return

        metadata = self._resolve_short_metadata(context)

        try:
            video_id, url = upload.upload_short(
                youtube,
                file_path=Path(output),
                title=metadata["title"],
                description=metadata["description"],
                tags=metadata.get("tags"),
                category_id=self._config.get("category_id", "20"),
                privacy_status=self._config.get("privacy_status", "unlisted"),
                made_for_kids=False,
            )
        except UploadError as exc:
            log.warning("Google plugin: short upload failed: %s", exc)
            return

        context.shared["uploads"] = context.shared.get("uploads", {})
        google = context.shared["uploads"].setdefault("google", {})
        google.setdefault("shorts", []).append({"video_id": video_id, "url": url})
        log.info("Google plugin: uploaded short %s", url)

    def on_game_finish(self, context: HookContext) -> None:
        """Handle ``ON_GAME_FINISH`` — no-op, state reset moved to ON_POST_GAME_FINISH."""

    def on_post_game_finish(self, context: HookContext) -> None:
        """Handle ``ON_POST_GAME_FINISH`` — update broadcast with chapters, then reset state."""
        try:
            self._update_chapters(context)
        finally:
            self._game_info = None
            self._youtube = None
            self._playlist_id = None

    def _update_chapters(self, context: HookContext) -> None:
        """Append chapter markers from game events to the broadcast description."""
        game_events = context.shared.get("game_events")
        if not game_events:
            return

        livestream_url = context.shared.get("livestreams", {}).get("google")
        if not livestream_url:
            return

        youtube = self._youtube
        if youtube is None:
            return

        try:
            broadcast_id = playlist.extract_video_id(livestream_url)
        except PlaylistError:
            log.warning(
                "Google plugin: could not extract broadcast ID from %s, skipping chapters",
                livestream_url,
            )
            return

        try:
            item = livestream.get_broadcast_snippet(youtube, broadcast_id)
        except LivestreamError as exc:
            log.warning("Google plugin: failed to fetch broadcast snippet (non-fatal): %s", exc)
            return

        existing_snippet = item.get("snippet", {})
        current_title = existing_snippet.get("title", "")
        existing_description = existing_snippet.get("description", "")

        chapters = "\n".join(
            f"{evt['timestamp']} {evt['description']}" for evt in game_events
        )
        new_description = (
            f"{existing_description}\n\nChapters:\n{chapters}"
            if existing_description
            else f"Chapters:\n{chapters}"
        )

        try:
            livestream.update_broadcast(
                youtube,
                broadcast_id=broadcast_id,
                title=current_title,
                description=new_description,
            )
        except LivestreamError as exc:
            log.warning("Google plugin: chapter update failed (non-fatal): %s", exc)

    def _resolve_upload_metadata(self, context: HookContext) -> dict[str, Any]:
        """Read upload metadata from shared context, fall back to GameInfo template."""
        shared = context.shared.get("uploads", {}).get("google", {})
        title = shared.get("title") or (
            self._build_title(self._game_info) if self._game_info else "Highlights"
        )
        description = shared.get("description", "")
        if not description and self._game_info:
            description = getattr(self._game_info, "description", "")
        tags = shared.get("tags")
        return {"title": title, "description": description, "tags": tags}

    def _resolve_short_metadata(self, context: HookContext) -> dict[str, Any]:
        """Build Short title from shared context or GameInfo + plan stem."""
        shared = context.shared.get("uploads", {}).get("google", {})
        if shared.get("short_title"):
            return {
                "title": shared["short_title"],
                "description": shared.get("short_description", ""),
                "tags": shared.get("tags"),
            }
        base = self._build_title(self._game_info) if self._game_info else "Highlight"
        plan = context.data.get("plan")
        stem = getattr(getattr(plan, "output", None), "stem", "")
        title = f"{base} - {stem}" if stem else base
        return {"title": title, "description": "", "tags": None}

    def _resolve_recording_date(self) -> str | None:
        """Extract recording date from cached game info."""
        if self._game_info is None:
            return None
        date = getattr(self._game_info, "date", None)
        return date if date else None

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
            now = datetime.now(tz=dt.tzinfo)
            if dt < now + timedelta(minutes=5):
                log.warning(
                    "Google plugin: scheduled start '%s' is in the past or <5 min away, using default",
                    combined,
                )
                return None
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
