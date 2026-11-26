"""The shape of a model catalog entry (design D5)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

TASKS = (
    "image_generation",
    "image_edit",
    "image_to_video",
    "talking_avatar",
    "lipsync",
    "speech",
    "background_removal",
    "llm",
    "vision_check",
)

# Workflow slots a model can accept. Slots that carry files are uploaded before submission.
FILE_SLOTS = {
    "first_frame",
    "last_frame",
    "reference_images",
    "reference_audio",
    "reference_video",
    "image",
    "audio",
    "video",
}

# A model needs at least these slots mapped to be usable for the task.
REQUIRED = {
    "image_generation": ["prompt"],
    "image_edit": ["prompt", "reference_images"],
    "image_to_video": ["first_frame"],
    "talking_avatar": ["first_frame", "audio"],
    "lipsync": ["video", "audio"],
    "speech": ["text"],
    "background_removal": ["image"],
    "llm": [],
    "vision_check": [],
}

# Which providers can serve each task (shown when a step has no usable model).
SERVED_BY = {
    "llm": ["openrouter"],
    "vision_check": ["openrouter"],
    "speech": ["elevenlabs", "fish", "fal", "replicate"],
}


class PriceRow(BaseModel):
    when: dict[str, Any] = Field(default_factory=dict)
    price: float


class Price(BaseModel):
    # second: per second of output video; image: per image; 1k_chars; token; run; predict_second;
    # minute: per minute of media; free
    unit: Literal["second", "image", "1k_chars", "token", "run", "predict_second", "minute", "free"] = "run"
    default: float | None = None
    table: list[PriceRow] = Field(default_factory=list)
    typical_seconds: float = 8.0  # for predict_second estimates
    token_fps: float = 24.0  # token-priced video: tokens = width * height * fps * seconds / 1024
    note: str = ""
    source: Literal["curated", "metadata", "page"] = "curated"


class InputSpec(BaseModel):
    param: str
    # int, float, str, bool, list, seconds_str ("8s"), image_url_list (OpenRouter references)
    as_: str | None = Field(None, alias="as")
    role: str | None = None  # OpenRouter frame_images: first_frame / last_frame

    model_config = {"populate_by_name": True}


class Limits(BaseModel):
    durations: list[float] | None = None
    resolutions: list[str] | None = None
    aspect_ratios: list[str] | None = None
    max_references: int = 0
    max_duration: float | None = None


class Entry(BaseModel):
    id: str
    provider: str
    model: str
    name: str
    task: str
    inputs: dict[str, str | InputSpec] = Field(default_factory=dict)
    extra: dict[str, Any] = Field(default_factory=dict)
    limits: Limits = Field(default_factory=Limits)
    multi_shot: bool = False
    native_audio: bool = False  # the model can produce speech/sound itself
    silent_option: bool = True  # audio can be switched off
    reference_audio: bool = False  # accepts a voice sample
    price: Price | None = None
    version: str | None = None
    timeout_minutes: int = 20
    notes: str = ""
    # Filled in by loading / discovery
    discovered: bool = False
    available: bool = True
    unavailable_reason: str = ""

    def spec(self, slot: str) -> InputSpec | None:
        value = self.inputs.get(slot)
        if value is None:
            return None
        return InputSpec(param=value) if isinstance(value, str) else value

    def public(self) -> dict[str, Any]:
        data = self.model_dump(by_alias=True, exclude_none=True)
        data["slots"] = sorted(self.inputs)
        return data
