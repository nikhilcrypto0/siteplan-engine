"""uv run python -m siteplan.prototypes FLAT_LIBRARY.json [--mix ...] [--out ...] [--dxf ...]

Compose the prototype kit from a flat library file, say what came out, and optionally save it as
a prototype library (JSON) and as DXF blocks. See the package docstring for the example file.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from siteplan.contracts.common import SourceKind
from siteplan.library import FlatLibrary
from siteplan.prototypes.compose import COMPOSED_SOURCES, compose_library
from siteplan.prototypes.draw import write_library_dxf
from siteplan.prototypes.library import save_library


def parse_mix(text: str) -> dict[str, float]:
    """'2BHK=0.7,3BHK=0.3' as a unit mix."""
    try:
        pairs = [item.split("=") for item in text.split(",")]
        return {category.strip(): float(share) for category, share in pairs}
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"{text!r} is not a unit mix; write it like 2BHK=0.7,3BHK=0.3") from None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m siteplan.prototypes",
        description="Compose the prototype kit from a flat library file.")
    parser.add_argument("flat_library", type=Path, help="a flat library JSON file")
    parser.add_argument("--mix", type=parse_mix,
                        help="unit mix to compose for, e.g. 2BHK=0.7,3BHK=0.3 (default: an even "
                        "share of every category in the library)")
    parser.add_argument("--source-kind", default=SourceKind.ENGINE_DEFAULT.value,
                        choices=[kind.value for kind in COMPOSED_SOURCES],
                        help="whose library it is: the engine's example flats (the default) or "
                        "the firm's own")
    parser.add_argument("--out", type=Path, help="save the prototype library (JSON) here")
    parser.add_argument("--dxf", type=Path, help="save one DXF block per prototype here")
    args = parser.parse_args(argv)
    library = FlatLibrary.model_validate_json(args.flat_library.read_text())
    prototypes = compose_library(library, args.mix, source_kind=SourceKind(args.source_kind))
    for p in prototypes:
        print(f"{p.id}: {p.family.value}, {p.per_floor.flats} flats a floor "
              f"{dict(sorted(p.per_floor.flats_by_type.items()))}, {p.cores} "
              f"{'core' if p.cores == 1 else 'cores'}, {p.length_m:g} x {p.depth_m:g} m")
    for path, write in ((args.out, save_library), (args.dxf, write_library_dxf)):
        if path is not None:
            print(f"written to {write(prototypes, path)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
