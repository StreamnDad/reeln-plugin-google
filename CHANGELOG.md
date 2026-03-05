# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/).

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
