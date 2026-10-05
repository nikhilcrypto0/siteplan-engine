"""The boundary a future model-facing transport holds: the nine operations as tools, nothing else.

    host = ToolHost(workspace, out, PageApprover(), mode=Mode.BLIND)  # the host, at startup
    host.tools()                          # each tool's name, description, input and output schema
    host.call("open_project", {"project_file": "site.project.json"})  # JSON in, JSON out

There is no transport and no model here. Whatever process one day connects a model holds a
ToolHost and only that: not the Service, not the optimizer or the validator, not a test profile,
a readings override, a `_status` or `_source` map, a validator to inject, a file to write or a
legacy route. A call reaches one of the nine operations through its frozen request model, which
refuses a field it does not know; a caller can neither approve, nor set a firm standard, nor
pick the mode.

What construction enforces, because a model must not answer its own approval or write where the
architect's files are:
- the approver is the approval page itself (`PageApprover`, not a subclass): a terminal a model
  could type into, or any other object with an approve method, is refused;
- `out` lies neither inside the workspace nor around it: the service writes only to `out`, so the
  survey, the project files and the firm's libraries stay as the architect left them.

A request the host will not serve raises ServiceError with a message safe to show the caller; the
reason, and any failure inside an operation, goes to the log, never back.
"""

from __future__ import annotations

import inspect
import logging
import typing
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, ValidationError

from siteplan.service.approvers import PageApprover
from siteplan.service.models import Mode, ServiceError
from siteplan.service.service import Service

log = logging.getLogger("siteplan.service")

OPERATIONS = ("start_project", "open_project", "resolve_rules", "inspect_envelope",
              "list_prototypes", "propose_layouts", "validate_candidate", "compare_candidates",
              "export_candidate")


@dataclass(frozen=True)
class _Tool:
    name: str
    description: str
    request: type[BaseModel]
    response: type[BaseModel]


def _tool(name: str) -> _Tool:
    """An operation as a tool: its docstring, and the models its signature names."""
    method = getattr(Service, name)
    hints = typing.get_type_hints(method)
    return _Tool(name, inspect.getdoc(method) or "", hints["request"], hints["return"])


TOOLS = {name: _tool(name) for name in OPERATIONS}


class ToolHost:
    def __init__(self, workspace: Path, out: Path, approver: PageApprover, *,
                 mode: Mode = Mode.BLIND) -> None:
        if type(approver) is not PageApprover:
            raise TypeError("The host asks the architect on the approval page only "
                            f"(PageApprover), not a {type(approver).__name__}: a model could "
                            "answer any other channel.")
        root, target = Path(workspace).resolve(), Path(out).resolve()
        if not root.is_dir():
            raise ValueError(f"The workspace {root} is not a folder.")
        if target.is_relative_to(root) or root.is_relative_to(target):
            raise ValueError(f"out ({target}) must lie neither inside the workspace ({root}) nor "
                             "around it: the service writes only there, and the architect's "
                             "files stay untouched.")
        self._service = Service(root, target, approver, mode=Mode(mode))

    def tools(self) -> list[dict]:
        """Every tool: its name, what it does, and the JSON schemas of what it takes and gives."""
        return [{"name": t.name, "description": t.description,
                 "input_schema": t.request.model_json_schema(),
                 "output_schema": t.response.model_json_schema()} for t in TOOLS.values()]

    def call(self, name: str, arguments: dict) -> dict:
        """One operation: the arguments checked against its request model, the answer as JSON."""
        tool = TOOLS.get(name) if isinstance(name, str) else None
        if tool is None:
            log.warning("tool refused: %r", name)
            raise ServiceError("There is no such tool; tools() lists the nine there are.")
        if not isinstance(arguments, dict):
            log.warning("%s refused: arguments of type %s", name, type(arguments).__name__)
            raise ServiceError(f"{name} takes a JSON object of arguments.")
        try:
            request = tool.request.model_validate(arguments)
        except ValidationError as error:
            log.warning("%s refused: %s", name, error)  # the reason stays in the log
            raise ServiceError(f"The arguments do not fit {name}'s input schema "
                               "(tools() gives it).") from None
        try:
            result = getattr(self._service, name)(request)
        except ServiceError:
            raise
        except Exception:
            log.exception("%s failed", name)
            raise ServiceError(f"{name} failed; the reason is in the service's log.") from None
        return result.model_dump(mode="json")
