from __future__ import annotations

import os
import secrets
import sys
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _default_data_dir() -> Path:
    app_name = "TuneForge"
    if sys.platform == "win32":
        return Path(os.environ["LOCALAPPDATA"]) / app_name
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / app_name
    # Linux and anything else POSIX-like: XDG Base Directory spec.
    xdg_data_home = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg_data_home) if xdg_data_home else Path.home() / ".local" / "share"
    return base / app_name


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TUNEFORGE_")

    host: Literal["127.0.0.1"] = "127.0.0.1"
    port: int = 8420
    app_version: str = "0.1.0"
    data_dir: Path = Field(default_factory=_default_data_dir)


def generate_session_token() -> str:
    """Return a 256-bit, hex-encoded token held only in memory."""
    return secrets.token_hex(32)
