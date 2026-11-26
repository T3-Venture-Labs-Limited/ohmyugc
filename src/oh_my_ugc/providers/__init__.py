"""Provider adapters. Use :func:`get` to reach one by name."""

from __future__ import annotations

from oh_my_ugc.providers.base import DISPLAY, Output, PollResult, Provider, Submission

_instances: dict[str, Provider] = {}
# Tests register fakes here.
overrides: dict[str, Provider] = {}


def get(name: str) -> Provider:
    if name in overrides:
        return overrides[name]
    if name not in _instances:
        if name == "replicate":
            from oh_my_ugc.providers.replicate import Replicate as cls
        elif name == "fal":
            from oh_my_ugc.providers.fal import Fal as cls
        elif name == "openrouter":
            from oh_my_ugc.providers.openrouter import OpenRouter as cls
        elif name == "elevenlabs":
            from oh_my_ugc.providers.speech import ElevenLabs as cls
        elif name == "fish":
            from oh_my_ugc.providers.speech import Fish as cls
        else:
            from oh_my_ugc.errors import OmuError

            raise OmuError(f"Unknown provider '{name}'.")
        _instances[name] = cls()
    return _instances[name]


def connected() -> list[str]:
    from oh_my_ugc import config

    return [p for p in config.PROVIDERS if config.get_key(p) or p in overrides]


__all__ = ["DISPLAY", "Output", "PollResult", "Provider", "Submission", "connected", "get"]
