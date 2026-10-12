"""The engine's end of the FreeCAD bridge: XML-RPC to the server `cad/siteplan_live.FCMacro` runs
inside FreeCAD, on 127.0.0.1 only, each call carrying the token that server wrote beside its
drawings (so another program on this machine, or a web page, cannot drive it).

Units: the engine works in metres, FreeCAD in millimetres. `to_cad` and `from_cad` are the only
conversions, exact up to floating point; XML-RPC carries a float as its full decimal repr, so a
coordinate comes back as it went."""

from __future__ import annotations

import os
import xmlrpc.client
from pathlib import Path

HOST = "127.0.0.1"  # the server never listens anywhere else
PORT = int(os.environ.get("SITEPLAN_CAD_PORT", "9877"))
TOKEN_FILE = ".bridge-token"
MM_PER_M = 1000.0  # a unit: FreeCAD's length unit is the millimetre


class NoBridge(Exception):
    """FreeCAD is not running the siteplan live macro, or its token cannot be read."""


def default_folder() -> Path:
    """Where the macro keeps its drawings and token: SITEPLAN_CAD_ROOT, else out/cad in the
    repository the macro was run from."""
    env = os.environ.get("SITEPLAN_CAD_ROOT")
    if env:
        return Path(env).resolve()
    return (Path(__file__).resolve().parents[3] / "out" / "cad").resolve()


def to_cad(xy: tuple[float, float]) -> list[float]:
    return [float(xy[0]) * MM_PER_M, float(xy[1]) * MM_PER_M]


def from_cad(xy: list[float]) -> tuple[float, float]:
    return (float(xy[0]) / MM_PER_M, float(xy[1]) / MM_PER_M)


class Bridge:
    """A connection to the running FreeCAD. Every call is one request; FreeCAD does the drawing
    on its own thread and answers when it is done."""

    def __init__(self, folder: Path | None = None, port: int = PORT):
        self.folder = (folder or default_folder()).resolve()
        token = self.folder / TOKEN_FILE
        try:
            self._token = token.read_text().strip()
        except OSError as problem:
            raise NoBridge(f"FreeCAD's live link is not running: no token at {token}. Open "
                           "FreeCAD and run cad/siteplan_live.FCMacro.") from problem
        self._proxy = xmlrpc.client.ServerProxy(f"http://{HOST}:{port}/RPC2", allow_none=True)

    def _call(self, name: str, *args):
        try:
            return getattr(self._proxy, name)(self._token, *args)
        except ConnectionError as problem:
            raise NoBridge("FreeCAD's live link does not answer: is FreeCAD open with "
                           "cad/siteplan_live.FCMacro run?") from problem

    def ping(self) -> dict:
        return self._call("ping")

    def document(self, name: str) -> str:
        return self._call("document", name)

    def upsert(self, items: list[dict], styles: dict[str, dict]) -> list[dict]:
        return self._call("upsert", items, styles)

    def remove(self, ids: list[str]) -> int:
        return self._call("remove", ids)

    def listing(self) -> list[dict]:
        return self._call("listing")

    def read(self, ident: str) -> dict | None:
        return self._call("read", ident)

    def move(self, ident: str, east_m: float, north_m: float) -> str:
        """Shift an object in FreeCAD only, as a person dragging it there would."""
        dx, dy = to_cad((east_m, north_m))
        return self._call("move", ident, dx, dy)

    def save(self, name: str) -> str:
        return self._call("save", name)

    def reopen(self, name: str) -> str:
        return self._call("reopen", name)

    def show_layer(self, name: str, visible: bool) -> int:
        return self._call("show_layer", name, visible)

    def layers(self) -> list[dict]:
        return self._call("layers")

    def view(self, fit: bool = True) -> bool:
        return self._call("view", fit)

    def snapshot(self, name: str, width: int, height: int) -> str:
        return self._call("snapshot", name, width, height)
