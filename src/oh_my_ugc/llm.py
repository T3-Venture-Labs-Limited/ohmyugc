"""Language-model and vision calls through OpenRouter (or any provider with a ``chat`` method)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from oh_my_ugc import costs, providers, runner
from oh_my_ugc.catalog import load
from oh_my_ugc.catalog.schema import Entry
from oh_my_ugc.errors import OmuError
from oh_my_ugc.providers.base import data_uri
from oh_my_ugc.providers.openrouter import parse_json

PROMPTS = Path(__file__).resolve().parent / "prompts"


def prompt(name: str, /, **values: str) -> str:
    text = (PROMPTS / f"{name}.md").read_text(encoding="utf-8")
    for key, value in values.items():
        text = text.replace("{{" + key + "}}", value)
    return text


def pick(task: str, project_models: dict | None = None) -> Entry:
    entry = load.chosen_for(task, project_models)
    if entry is None:
        what = "write with AI" if task == "llm" else "check product accuracy"
        raise OmuError(f"No language model chosen to {what}. {load.requirement(task)}", status=400)
    return entry


def available(task: str = "llm", project_models: dict | None = None) -> bool:
    return load.chosen_for(task, project_models) is not None


def chat_json(
    entry: Entry,
    system: str,
    user: str,
    schema: dict,
    *,
    images: list[Path] | None = None,
    step: str = "write",
    project_id: str | None = None,
    temperature: float | None = 0.7,
) -> Any:
    """One structured-output request; the cost is recorded in the ledger."""
    content: Any = user
    if images:
        content = [{"type": "text", "text": user}] + [
            {"type": "image_url", "image_url": {"url": data_uri(p)}} for p in images
        ]
    messages = [{"role": "system", "content": system}, {"role": "user", "content": content}]
    est = costs.estimate(entry)
    reservation = costs.reserve(project_id or getattr(runner._ctx, "project_id", None), est.amount or 0.0)
    try:
        provider = providers.get(entry.provider)
        text, cost = provider.chat(entry.model, messages, schema=schema, temperature=temperature)  # type: ignore[attr-defined]
    finally:
        costs.release(reservation)
    costs.record(
        project_id=project_id or getattr(runner._ctx, "project_id", None),
        job_id=runner.current_job(),
        step=step,
        entry=entry,
        units="{}",
        estimated=est.amount or 0.0,
        actual=cost,
    )
    return parse_json(text)
