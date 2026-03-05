"""OAuth 2.0 credential management for Google APIs."""

from __future__ import annotations

import logging
import os
import stat
from pathlib import Path
from typing import Any

from reeln.core.config import data_dir

log: logging.Logger = logging.getLogger(__name__)

DEFAULT_SCOPES: list[str] = [
    "https://www.googleapis.com/auth/youtube",
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.force-ssl",
]


class AuthError(Exception):
    """Raised when OAuth authentication fails."""


def default_credentials_path() -> Path:
    """Return the default OAuth credentials cache path."""
    return Path(data_dir() / "google" / "oauth.json")


def get_credentials(
    client_secrets_file: Path,
    credentials_cache: Path,
    scopes: list[str] | None = None,
    *,
    fresh: bool = False,
) -> Any:
    """Load, obtain, or refresh OAuth credentials.

    On first use, opens a browser for the OAuth consent flow.
    Subsequent calls load from the credentials cache and refresh if expired.

    Args:
        client_secrets_file: Path to GCP OAuth client secrets JSON.
        credentials_cache: Path to store/load cached credentials.
        scopes: OAuth scopes. Defaults to ``DEFAULT_SCOPES``.
        fresh: If True, delete cached credentials and re-authenticate.

    Returns:
        Google OAuth2 Credentials object.

    Raises:
        AuthError: If authentication fails.
    """
    try:
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError as exc:
        raise AuthError(f"Google auth libraries not installed: {exc}") from exc

    effective_scopes = scopes or DEFAULT_SCOPES

    if fresh and credentials_cache.exists():
        credentials_cache.unlink()
        log.info("Cleared OAuth cache: %s", credentials_cache)

    creds: Credentials | None = None

    if credentials_cache.exists():
        creds = Credentials.from_authorized_user_file(  # type: ignore[no-untyped-call]
            str(credentials_cache), effective_scopes
        )

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            from google.auth.transport.requests import Request

            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                str(client_secrets_file), effective_scopes
            )
            creds = flow.run_local_server(port=0)

        credentials_cache.parent.mkdir(parents=True, exist_ok=True)
        credentials_cache.write_text(creds.to_json())
        if os.name != "nt":
            credentials_cache.chmod(stat.S_IRUSR | stat.S_IWUSR)

    return creds


def build_youtube_service(credentials: Any) -> Any:
    """Build a YouTube Data API v3 service client.

    Args:
        credentials: Google OAuth2 Credentials object.

    Returns:
        YouTube API service resource.

    Raises:
        AuthError: If service creation fails.
    """
    try:
        from googleapiclient.discovery import build
    except ImportError as exc:
        raise AuthError(f"Google API client library not installed: {exc}") from exc

    return build("youtube", "v3", credentials=credentials)
