# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/).

## [0.13.0] - 2026-04-20

### Added

- Upload capability with UploaderSkipped support
- Regenerate image guard — skip on_game_init when `regenerate_image_only` is set
- Playlist video insertion and broadcast update improvements

## [0.12.0] - 2026-04-07

### Added

- `auth_check()` and `auth_refresh()` methods implementing the `Authenticator` protocol — enables `reeln plugins auth google` for credential verification and token renewal

## [0.11.0] - 2026-04-03

### Added

- `get_input_schema()` — declares `thumbnail_image` input for `game_init` when `create_livestream` is enabled
- Reads thumbnail from `plugin_inputs` (new reeln-cli input contribution system) with fallback to `game_info.thumbnail`

### Changed

- `min_reeln_version` bumped to `0.0.37` (requires plugin input contribution support)

## [0.10.0] - 2026-03-25

### Changed

- `_resolve_short_metadata()` renamed to `_resolve_render_metadata()` — reads from `context.shared["render_metadata"]` instead of `context.shared["uploads"]["google"]`
- Decoupled from OpenAI plugin's internal shared context structure for LLM-generated Shorts/video metadata

## [0.9.0] - 2026-03-23

### Added

- Landscape vs portrait upload detection: `POST_RENDER` now checks `plan.width` vs `plan.height` to call `upload_video()` for landscape renders or `upload_short()` for portrait renders — previously all uploads were treated as Shorts
- Shorts now auto-added to game playlist after upload when `manage_playlists` is enabled — matches existing highlights playlist insertion behavior

## [0.8.1] - 2026-03-15

### Fixed

- Default `scheduledStartTime` fallback uses `now + 1 minute` instead of `now` — YouTube rejects start times that aren't in the future

## [0.8.0] - 2026-03-14

### Added

- `ON_POST_GAME_FINISH` hook handler — appends chapter markers (from game events) to the YouTube broadcast description
- `get_broadcast_snippet()` in `livestream.py` — reusable helper to fetch broadcast snippet, refactored out of `update_broadcast()`
- State reset (`_game_info`, `_youtube`, `_playlist_id`) moved from `ON_GAME_FINISH` to `ON_POST_GAME_FINISH` to allow sibling plugins to write shared context during FINISH
- `min_reeln_version` bumped to `0.0.31` (requires reeln-cli with `ON_POST_GAME_FINISH` hook support)

## [0.7.0] - 2026-03-11

### Added

- `ON_GAME_READY` hook handler — updates broadcast and playlist metadata with AI-enriched content from sibling plugins (title, description, translations, thumbnail)
- `update_broadcast()` in `livestream.py` — update existing broadcast snippet, localizations, and thumbnail
- `update_playlist()` in `playlist.py` — update existing playlist snippet and localizations
- `min_reeln_version` set to `0.0.19` (requires reeln-cli with `ON_GAME_READY` hook support)

### Fixed

- Wrap `HttpError` from YouTube API in `LivestreamError` / `PlaylistError` so plugin-level `except` handlers catch API failures instead of letting raw `HttpError` propagate
- Guard against past or near-future (<5 min) scheduled start times in `_build_scheduled_start()` — returns `None` to fall back to `datetime.now()` instead of sending an invalid time to the API
- Skip duplicate-video check when inserting into a just-created playlist — YouTube API returns 404 on `playlistItems.list` due to eventual consistency race

## [0.6.0] - 2026-03-06

### Added

- `upload.py` module — YouTube video upload (highlights and Shorts) with resumable MediaFileUpload
- `upload_highlights` feature flag (default `false`) — upload merged highlights on `ON_HIGHLIGHTS_MERGED`
- `upload_shorts` feature flag (default `false`) — upload Shorts on `POST_RENDER` (detected via `filter_complex`)
- LLM metadata flow — reads title/description/tags from `context.shared["uploads"]["google"]` when present
- Auto-add uploaded highlights to playlist when both `upload_highlights` and `manage_playlists` enabled
- `set_localizations()` for applying video translations in a separate API call
- Instance state caching (`_game_info`, `_youtube`, `_playlist_id`) across hooks within a game session
- `_ensure_youtube()` helper — shared auth with lazy caching
- `ON_GAME_FINISH` handler to reset cached state between games

## [0.5.0] - 2026-03-05

### Added

- `playlist.py` module — find, create, and populate YouTube playlists with deduplication
- `manage_playlists` feature flag (default `false`) — game-specific playlist creation on `ON_GAME_INIT`
- Playlist-only mode supported (without livestream); when both flags are on, livestream video is auto-added to playlist
- Playlist ID written to `context.shared["playlists"]["google"]` for sibling plugins

## [0.4.0] - 2026-03-05

### Added

- `create_livestream` feature flag (default `false`) — livestream creation on `ON_GAME_INIT` now requires explicit opt-in
- All capabilities must be feature-flagged per plugin convention

## [0.3.0] - 2026-03-04

### Added

- Pass `description` and `thumbnail` from `GameInfo` to `create_livestream()` during `ON_GAME_INIT`
- Broadcast description and thumbnail image are now configurable via `reeln game init --description` / `--thumbnail`

## [0.2.0] - 2026-03-04

### Added

- Use game date and time for YouTube livestream `scheduledStartTime` instead of `datetime.now()`
- Added `python-dateutil` dependency for robust time parsing (handles timezone abbreviations like CST, EST)

### Fixed

- Livestream URL now persisted to `game.json` via new `livestreams` field on `GameState` (reeln-cli change)

## [0.1.1] - 2026-03-04

### Fixed

- Set `chmod 600` on OAuth credentials cache file to prevent world-readable tokens (skipped on Windows where NTFS uses ACLs)

## [0.1.0] - 2026-03-04

### Added

- Initial plugin scaffolding with `GooglePlugin` class
- OAuth 2.0 credential management (`auth.py`) — cache, refresh, browser flow
- YouTube livestream creation (`livestream.py`) — find/create stream, create broadcast, bind, thumbnail
- `ON_GAME_INIT` hook handler — authenticates, creates livestream, writes URL to `context.shared["livestreams"]["google"]`
- Plugin config schema with `client_secrets_file`, `credentials_cache`, `privacy_status`, `category_id`, `tags`, `scopes`
- 100% line + branch test coverage
