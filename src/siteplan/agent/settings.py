"""What the agent loop runs with: the model to ask, the limits on a run, and the architect's brief.

    settings = Settings.build(config, brief, model_id=..., limits={...})  # the launcher's side
    settings.write(scratch)    # the hand-off into the sandbox: one file in the scratch folder
    Settings.read(scratch)     # the loop's side, inside the sandbox

The launcher builds and checks the settings before anything starts, from its arguments and an
optional JSON file (`load_config`): an argument wins over the file, the file over the default. The
model's endpoint is not in the hand-off: the sandbox's policy opens its one port and gives the loop
the address (SITEPLAN_MODEL_ENDPOINT), so the two cannot disagree. A key nobody knows is refused,
never ignored, so a misspelt limit cannot leave the default silently in force.

None of these numbers is a number of a layout: they bound the agent's run (tests/test_constraints.py
exempts the package, with the reason).
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any

HANDOFF = "agent.json"  # in the scratch folder: the one file the launcher gives the loop
MAX_MODEL_ID_CHARS = 200
MAX_BRIEF_CHARS = 20_000
# What the loop itself sets in every request; the configuration may not.
RESERVED_OPTIONS = frozenset({"model", "messages", "tools", "stream", "n"})
CONFIG_KEYS = frozenset({"model_endpoint", "model_id", "request_options", "limits"})


@dataclass(frozen=True)
class Limits:
    """The hard limits on one run (MEANING says what each bounds). Each is a stop, never a
    warning."""

    max_turns: int = 30
    max_tool_calls: int = 40
    max_failed_tool_calls: int = 4
    max_identical_calls: int = 3
    request_timeout_s: float = 600.0
    run_timeout_s: float = 3600.0
    max_response_bytes: int = 1_048_576
    max_tool_result_chars: int = 64_000
    model_retries: int = 0


MEANING = {
    "max_turns": "model requests in one run (retries aside); a last turn's tool calls are not run",
    "max_tool_calls": "tool calls the model may ask for in one run",
    "max_failed_tool_calls": "tool calls in a row that were refused or failed",
    "max_identical_calls": "times the same tool may be asked for with the same arguments; that "
                           "many stops the run, the last not run",
    "request_timeout_s": "seconds for one model request, from sending it to its last byte",
    "run_timeout_s": "seconds for the whole run, the architect's approvals included",
    "max_response_bytes": "bytes of one model response; a larger one stops the run",
    "max_tool_result_chars": "characters of one tool result as the model gets it; a longer one "
                             "is cut, with a marker saying so",
    "model_retries": "extra attempts at a failed model request; a tool call is never retried",
}


# The least each limit may be set to: a run must be able to take one step.
LEAST = {"max_turns": 1, "max_tool_calls": 1, "max_failed_tool_calls": 1,
         "max_identical_calls": 2, "max_response_bytes": 1024, "max_tool_result_chars": 256,
         "model_retries": 0}


def check_limits(values: Mapping[str, Any]) -> Limits:
    """Limits from a mapping of overrides; ValueError names the first that is wrong."""
    known = {f.name: f for f in fields(Limits)}
    unknown = sorted(set(values) - set(known))
    if unknown:
        raise ValueError(f"Unknown limit {unknown[0]!r}; the limits are {', '.join(known)}.")
    checked = {}
    for name, value in values.items():
        number = known[name].type == "float"
        if isinstance(value, bool) or not isinstance(value, int | float if number else int):
            kind = "a number" if number else "a whole number"
            raise ValueError(f"The limit {name} must be {kind}, not {value!r}.")
        if number and not value > 0:
            raise ValueError(f"The limit {name} must be more than 0 seconds, not {value!r}.")
        if not number and value < LEAST[name]:
            raise ValueError(f"The limit {name} must be at least {LEAST[name]}, not {value!r}.")
        checked[name] = float(value) if number else value
    return Limits(**checked)


def check_options(options: Any) -> dict[str, Any]:
    """Extra request fields for the model server (sampling, `max_tokens`, a chat template's
    switches), passed as given: the loop's own fields may not be overridden."""
    if not isinstance(options, dict):
        raise ValueError("request_options must be a JSON object.")
    reserved = sorted(RESERVED_OPTIONS & set(options))
    if reserved:
        raise ValueError(f"request_options may not set {reserved[0]!r}: the loop sets it.")
    try:
        json.dumps(options)
    except (TypeError, ValueError):
        raise ValueError("request_options must hold JSON values only.") from None
    return dict(options)


def _text(name: str, value: Any, most: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"The {name} is missing.")
    if len(value) > most:
        raise ValueError(f"The {name} is longer than {most:,} characters.")
    if name == "model id" and any(ord(c) < 32 for c in value):
        raise ValueError("The model id holds a control character.")
    return value


def load_config(path: Path) -> dict[str, Any]:
    """The JSON configuration file: model_endpoint, model_id, request_options and limits."""
    try:
        config = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ValueError(f"The configuration {path} cannot be read: {error}") from None
    if not isinstance(config, dict):
        raise ValueError(f"The configuration {path} is not a JSON object.")
    unknown = sorted(set(config) - CONFIG_KEYS)
    if unknown:
        raise ValueError(f"Unknown key {unknown[0]!r} in {path}; the keys are "
                         f"{', '.join(sorted(CONFIG_KEYS))}.")
    if not isinstance(config.get("limits", {}), dict):
        raise ValueError(f"limits in {path} must be a JSON object.")
    return config


@dataclass(frozen=True)
class Settings:
    """The model, the limits and the brief, as the loop is given them."""

    model_id: str
    brief: str
    limits: Limits = field(default_factory=Limits)
    request_options: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def build(cls, config: Mapping[str, Any], brief: str, *, model_id: str | None = None,
              limits: Mapping[str, Any] | None = None) -> Settings:
        """From a configuration file's contents and the launcher's arguments, which win."""
        merged = {**config.get("limits", {}), **(limits or {})}
        return cls(model_id=_text("model id", model_id or config.get("model_id"),
                                  MAX_MODEL_ID_CHARS),
                   brief=_text("brief", brief, MAX_BRIEF_CHARS), limits=check_limits(merged),
                   request_options=check_options(config.get("request_options", {})))

    def to_json(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_json(cls, data: Any) -> Settings:
        if not isinstance(data, dict) or set(data) != {f.name for f in fields(cls)}:
            raise ValueError("The settings hand-off is not what the launcher writes.")
        return cls.build({"request_options": data["request_options"]}, data["brief"],
                         model_id=data["model_id"], limits=data["limits"])

    def write(self, scratch: Path) -> Path:
        path = Path(scratch) / HANDOFF
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(self.to_json(), handle)
        return path

    @classmethod
    def read(cls, scratch: Path) -> Settings:
        return cls.from_json(json.loads((Path(scratch) / HANDOFF).read_text(encoding="utf-8")))
