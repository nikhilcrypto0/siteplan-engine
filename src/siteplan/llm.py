"""The local model, reached through an OpenAI-compatible endpoint, under token budgets.

Budgets live in config, not in prompts. Every call is metered per step, per run and per
day; crossing any of the three halts the pipeline (BudgetExceeded) and is logged.
"""

from __future__ import annotations

import fcntl  # POSIX: the Mac and the Linux office server
import json
import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel, Field, PositiveInt


class Budgets(BaseModel):
    per_step_tokens: PositiveInt = 2_000
    per_run_tokens: PositiveInt = 8_000
    per_day_tokens: PositiveInt = 200_000


class AssistantConfig(BaseModel):
    base_url: str = "http://localhost:11434/v1"  # Ollama; vLLM serves the same API
    model: str = "qwen3.5:9b"
    api_key: str = "local"  # local servers ignore it; never a real secret
    timeout_s: PositiveInt = 120
    max_brief_chars: PositiveInt = 2_000
    retries: int = Field(1, ge=0, le=3)
    # Extra request fields that switch thinking off. Ollama: reasoning_effort "none".
    # vLLM + Qwen: {"extra_body": {"chat_template_kwargs": {"enable_thinking": false}}}.
    request_extras: dict[str, Any] = {"reasoning_effort": "none"}
    # Off by default: comparisons are computed in code. When on, the model may add a short
    # commentary, shown separately and dropped if it ranks options or invents a number.
    model_commentary: bool = False
    budgets: Budgets = Budgets()
    ledger_dir: str = "out/usage"
    log_file: str = "out/logs/assistant.log"


@dataclass(frozen=True)
class Usage:
    prompt: int
    completion: int

    @property
    def total(self) -> int:
        return self.prompt + self.completion


class BudgetExceeded(RuntimeError):
    def __init__(self, scope: str, used: int, limit: int):
        super().__init__(f"{scope} token budget reached ({used:,} of {limit:,})")
        self.scope = scope


class ChatModel(Protocol):
    def complete(
        self, messages: list[dict[str, str]], schema: dict | None, max_tokens: int
    ) -> tuple[str, Usage]: ...


class DailyLedger:
    """Tokens used per calendar day, kept in a small local JSON file.

    Two runs on the same day must not lose each other's usage, so updates hold an
    exclusive lock and replace the file atomically (a reader never sees half a write)."""

    def __init__(self, directory: str | Path, today: date | None = None):
        self.path = Path(directory) / f"{(today or date.today()).isoformat()}.json"

    def used(self) -> int:
        try:
            return int(json.loads(self.path.read_text())["tokens"])
        except FileNotFoundError:
            return 0

    def add(self, tokens: int) -> int:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path.with_suffix(".lock"), "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            total = self.used() + tokens
            tmp = self.path.with_suffix(f".{os.getpid()}.tmp")
            tmp.write_text(json.dumps({"tokens": total}))
            os.replace(tmp, self.path)
        return total


class Meter:
    """Charges every model call against the step, run and day budgets."""

    def __init__(self, budgets: Budgets, ledger: DailyLedger):
        self.budgets = budgets
        self.ledger = ledger
        self.run_used = 0
        self.by_step: dict[str, int] = {}

    def allowance(self, step: str, prompt_tokens: int = 0) -> int:
        """Completion tokens this call may use after its prompt; raises before the call if
        the prompt alone would cross a budget, so no tokens are spent on a doomed call."""
        left = min(
            self.budgets.per_step_tokens - self.by_step.get(step, 0),
            self.budgets.per_run_tokens - self.run_used,
            self.budgets.per_day_tokens - self.ledger.used(),
        ) - prompt_tokens
        if left <= 0:
            raise BudgetExceeded(self._tightest(step), *self._state(step))
        return left

    def charge(self, step: str, usage: Usage) -> None:
        self.by_step[step] = self.by_step.get(step, 0) + usage.total
        self.run_used += usage.total
        day = self.ledger.add(usage.total)
        for scope, used, limit in (
            ("per-step", self.by_step[step], self.budgets.per_step_tokens),
            ("per-run", self.run_used, self.budgets.per_run_tokens),
            ("per-day", day, self.budgets.per_day_tokens),
        ):
            if used > limit:
                raise BudgetExceeded(scope, used, limit)

    def _state(self, step: str) -> tuple[int, int]:
        scope = self._tightest(step)
        return {
            "per-step": (self.by_step.get(step, 0), self.budgets.per_step_tokens),
            "per-run": (self.run_used, self.budgets.per_run_tokens),
            "per-day": (self.ledger.used(), self.budgets.per_day_tokens),
        }[scope]

    def _tightest(self, step: str) -> str:
        left = {
            "per-step": self.budgets.per_step_tokens - self.by_step.get(step, 0),
            "per-run": self.budgets.per_run_tokens - self.run_used,
            "per-day": self.budgets.per_day_tokens - self.ledger.used(),
        }
        return min(left, key=left.get)  # type: ignore[arg-type]


def estimate_tokens(messages: list[dict[str, str]]) -> int:
    """A deliberately high estimate (3 characters per token) used only for budget checks."""
    return sum(len(m["content"]) for m in messages) // 3 + 8 * len(messages)


class OpenAICompatibleModel:
    def __init__(self, config: AssistantConfig):
        from openai import OpenAI  # imported here so tests never need a server

        self.config = config
        self.client = OpenAI(
            base_url=config.base_url, api_key=config.api_key, timeout=config.timeout_s
        )

    def complete(
        self, messages: list[dict[str, str]], schema: dict | None, max_tokens: int
    ) -> tuple[str, Usage]:
        kwargs: dict[str, Any] = dict(self.config.request_extras)
        if schema is not None:
            kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "output", "schema": schema},
            }
        response = self.client.chat.completions.create(
            model=self.config.model,
            messages=messages,  # type: ignore[arg-type]
            max_tokens=max_tokens,
            temperature=0,
            **kwargs,
        )
        usage = response.usage
        return (
            response.choices[0].message.content or "",
            Usage(usage.prompt_tokens if usage else 0, usage.completion_tokens if usage else 0),
        )
