"""Paths and settings.

Settings live in the local SQLite database so the web app and CLI can edit them. Environment
variables take precedence (handy for Docker and CI). API keys are never returned in full.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent


def home() -> Path:
    """Root folder for the database, media and projects (``OMU_HOME``)."""
    path = Path(os.environ.get("OMU_HOME", Path.home() / ".oh-my-ugc")).expanduser()
    path.mkdir(parents=True, exist_ok=True)
    return path


def media_dir() -> Path:
    path = home() / "media"
    path.mkdir(parents=True, exist_ok=True)
    return path


def projects_dir() -> Path:
    path = home() / "projects"
    path.mkdir(parents=True, exist_ok=True)
    return path


def user_catalog_dir() -> Path:
    path = home() / "catalog"
    path.mkdir(parents=True, exist_ok=True)
    return path


def cache_dir() -> Path:
    path = home() / "cache"
    path.mkdir(parents=True, exist_ok=True)
    return path


@dataclass(frozen=True, slots=True)
class SettingSpec:
    envs: tuple[str, ...] = ()
    default: str = ""
    secret: bool = False
    description: str = ""


PROVIDERS = ("replicate", "fal", "openrouter", "elevenlabs", "fish")

SETTINGS: dict[str, SettingSpec] = {
    "replicate_api_key": SettingSpec(
        ("REPLICATE_API_TOKEN", "REPLICATE_API_KEY"), secret=True, description="Replicate API token"
    ),
    "fal_api_key": SettingSpec(("FAL_KEY", "FAL_API_KEY"), secret=True, description="fal API key"),
    "openrouter_api_key": SettingSpec(("OPENROUTER_API_KEY",), secret=True, description="OpenRouter API key"),
    "elevenlabs_api_key": SettingSpec(("ELEVENLABS_API_KEY",), secret=True, description="ElevenLabs API key"),
    "fish_api_key": SettingSpec(
        ("FISH_API_KEY", "FISH_AUDIO_API_KEY"), secret=True, description="Fish Audio key"
    ),
    "default_models": SettingSpec(default="{}", description="Default model per task (JSON)"),
    "concurrency": SettingSpec(("OMU_CONCURRENCY",), "2", description="Parallel jobs per provider"),
    "default_budget": SettingSpec(default="", description="Budget in dollars for new projects"),
    "caption_style": SettingSpec(default="punch", description="Caption style for new projects"),
}


def key_name(provider: str) -> str:
    return f"{provider}_api_key"


def get_setting(key: str) -> str:
    """Environment variable, then database value, then default."""
    from oh_my_ugc import db

    spec = SETTINGS[key]
    for env in spec.envs:
        if os.environ.get(env):
            return os.environ[env]
    return db.get_setting(key) or spec.default


def setting_source(key: str) -> str:
    from oh_my_ugc import db

    spec = SETTINGS[key]
    if any(os.environ.get(env) for env in spec.envs):
        return "environment"
    return "settings" if db.get_setting(key) else ""


def get_key(provider: str) -> str:
    return get_setting(key_name(provider))


def mask(value: str) -> str:
    """Only the last four characters of a key are ever shown."""
    if not value:
        return ""
    return "••••" + value[-4:] if len(value) > 8 else "••••"


def concurrency(provider: str) -> int:
    try:
        return max(1, min(16, int(get_setting("concurrency"))))
    except ValueError:
        return 2
