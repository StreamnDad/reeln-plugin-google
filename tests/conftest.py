"""Shared test fixtures for reeln-plugin-google."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest


@dataclass
class FakeGameInfo:
    """Minimal stand-in for ``reeln.models.game.GameInfo``."""

    date: str = "2026-01-15"
    home_team: str = "Eagles"
    away_team: str = "Hawks"
    sport: str = "hockey"
    game_number: int = 1
    venue: str = ""
    game_time: str = ""
    description: str = ""
    thumbnail: str = ""


@pytest.fixture()
def game_info() -> FakeGameInfo:
    return FakeGameInfo()


@pytest.fixture()
def client_secrets_file(tmp_path: Path) -> Path:
    """Return a temporary client secrets file path."""
    secrets = tmp_path / "client_secrets.json"
    secrets.write_text('{"installed": {"client_id": "test"}}')
    return secrets


@pytest.fixture()
def credentials_cache(tmp_path: Path) -> Path:
    """Return a temporary credentials cache path."""
    return tmp_path / "google" / "oauth.json"


@pytest.fixture()
def plugin_config(client_secrets_file: Path, credentials_cache: Path) -> dict[str, Any]:
    """Return a minimal valid plugin config."""
    return {
        "client_secrets_file": str(client_secrets_file),
        "credentials_cache": str(credentials_cache),
    }


@pytest.fixture()
def mock_youtube_service() -> MagicMock:
    """Return a MagicMock YouTube API service."""
    return MagicMock()
