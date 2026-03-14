"""Tests for package-level exports."""

from __future__ import annotations


def test_version_is_string() -> None:
    from reeln_google_plugin import __version__

    assert isinstance(__version__, str)
    assert __version__ == "0.8.0"


def test_google_plugin_exported() -> None:
    from reeln_google_plugin import GooglePlugin

    assert GooglePlugin.name == "google"
