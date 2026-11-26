import shutil
from pathlib import Path

import pytest

from oh_my_ugc import db

FIXTURE_MODELS = Path(__file__).parent / "fixtures" / "catalog"


def install_test_models() -> None:
    """Seedance 1.5 Pro is retired, so it is not bundled. Tests keep using it as a user catalog entry."""
    from oh_my_ugc import config

    for source in FIXTURE_MODELS.glob("*.json"):
        shutil.copy(source, config.user_catalog_dir() / source.name)


@pytest.fixture(autouse=True)
def omu_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("OMU_HOME", str(home))
    for var in (
        "REPLICATE_API_TOKEN",
        "REPLICATE_API_KEY",
        "FAL_KEY",
        "FAL_API_KEY",
        "OPENROUTER_API_KEY",
        "ELEVENLABS_API_KEY",
        "FISH_API_KEY",
        "FISH_AUDIO_API_KEY",
    ):
        monkeypatch.delenv(var, raising=False)
    db.reset_for_tests()
    install_test_models()
    yield Path(home)
    db.reset_for_tests()


needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")


# The app never picks a model for the user. Tests that need steps to run choose these, as a user would.
CHOSEN_MODELS = {
    "llm": "openrouter/gemini-3.8-flash",
    "vision_check": "openrouter/gemini-3.8-flash-vision",
    "image_generation": "replicate/seedream-4.5-generate",
    "image_edit": "replicate/seedream-4.5",
    "image_to_video": "replicate/seedance-1.5-pro",
    "speech": "elevenlabs/multilingual-v2",
    "talking_avatar": "replicate/omni-human",
    "background_removal": "replicate/background-remover",
}


def choose_models() -> None:
    from oh_my_ugc.catalog import load

    for task, entry_id in CHOSEN_MODELS.items():
        load.set_global_default(task, entry_id)


@pytest.fixture
def fakes(monkeypatch):
    """Register fake providers for every provider name, mark them connected and choose a model per step."""
    from oh_my_ugc import config, providers, runner
    from tests.fakes import FakeProvider

    monkeypatch.setattr(runner, "sleep", lambda s: None)
    made = {}
    for name in config.PROVIDERS:
        made[name] = FakeProvider(name)
        providers.overrides[name] = made[name]
    choose_models()
    yield made
    providers.overrides.clear()


@pytest.fixture
def small(monkeypatch):
    """Render tests at a quarter of the real size: same code paths, a fraction of the time."""
    from oh_my_ugc import projects

    monkeypatch.setattr(
        projects, "ASPECTS", {"9:16": (270, 480), "1:1": (270, 270), "4:5": (270, 338), "16:9": (480, 270)}
    )
    return projects.ASPECTS
