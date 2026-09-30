"""Start a project from the raw survey: take what the drawing shows, ask only what it cannot.

`extract` reads what a survey gives: the plot and its areas, the levels, the roads measured
across themselves, the line work near the plot, and what is written on the sheet: marks such as
ROAD WIDENING, NALA or HT LINE, and the village, mandal and district. `questions` lists what is
still open, the facts no drawing settles (the road's legal width, land given up, whose rules
apply) and the brief, showing what the drawing suggests without choosing it: on Suchitra's
sheet the line nearest the word "Nala" is grey, so a nearest-line guess would pick wrong.
`build_project` turns the answers into the project file and records where each value came
from. The firm's flat and amenity libraries and its floor heights are workspace defaults.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

from pydantic import BaseModel, PositiveFloat
from shapely.geometry import Point

from siteplan import rules
from siteplan.max_floors import max_floors
from siteplan.pdf_survey import PdfProfile, colour_hex
from siteplan.project import Project
from siteplan.roads import Road, roads_near
from siteplan.runner import read_survey
from siteplan.survey import LineGroup
from siteplan.units import M_PER_FT, sqft_to_sqm, sqyd_to_sqm
from siteplan.wizard import AUTHORITIES, Question, parse_length, parse_mix

WORKSPACE_FILE = "siteplan.workspace.json"
MARKS = {
    "road widening": re.compile(r"ROAD\s*WIDEN|WIDENING|\bR\.?\s?W\.?\s?LINE\b|PROPOSED\s+ROAD|"
                                r"MASTER\s*PLAN\s*ROAD|SURRENDER", re.I),
    "water": re.compile(r"\bNALA[H]?\b|\bNALLA\b|\bCANAL\b|\bDRAIN\b|\bSTREAM\b|\bVAGU\b|"
                        r"\bKUNTA\b|\bCHERUVU\b|\bLAKE\b|\bF\.?\s?T\.?\s?L\b|FULL\s+TANK|\bRIVER\b",
                        re.I),
    "HT line": re.compile(r"\bH\.?\s?T\.?\s*LINE\b|^\s*H\.?\s?T\.?\s*$|HIGH\s*TENSION|"
                          r"TRANSMISSION|\bPYLON\b|\b\d+\s*KV\b", re.I),
}
PLACE = re.compile(r"\((?:V|M)\)|\bDIST\b\.?|\bDISTRICT\b|\bMANDAL\b|\bVILLAGE\b", re.I)
COMPASS = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")
_WORDS = {"NORTH": "N", "EAST": "E", "SOUTH": "S", "WEST": "W", "NORTHEAST": "NE",
          "NORTHWEST": "NW", "SOUTHEAST": "SE", "SOUTHWEST": "SW"}
TRISTATE = {"yes": True, "no": False, "unknown": None}
ROW_SOURCES = ("CERTIFIED_ROW", "DECLARED_ON_SITE_PLAN", "UNVERIFIED_DRAWING_VALUE")
WATER_CLASSES = "river, lake 10 ha or more, lake under 10 ha, nala over 10 m, nala up to 10 m"


class WorkspaceDefaults(BaseModel):
    """What a firm sets once for every project: its flats, its amenities, its floor heights."""

    flat_library: str | None = None
    amenities: str | None = None
    floor_height_m: PositiveFloat = 3.0
    stilt_height_m: PositiveFloat = 3.0
    common_area_pct: float = 22.0
    max_tower_length_m: PositiveFloat | None = None  # the firm's longest block; else the engine's


def load_defaults(folder: str | Path) -> WorkspaceDefaults:
    path = Path(folder) / WORKSPACE_FILE
    return WorkspaceDefaults.model_validate_json(path.read_text()) if path.exists() else (
        WorkspaceDefaults())


@dataclass(frozen=True)
class Mark:
    """Something written on the sheet that names a site edge the rules care about."""

    kind: str  # 'road widening', 'water' or 'HT line'
    text: str
    distance_m: float  # from the plot; a long way off usually means the legend
    nearby: tuple[tuple[str, float], ...]  # the colours or layers drawn closest to it


@dataclass(frozen=True)
class Draft:
    """What the survey shows, before anyone is asked anything."""

    survey: str
    gross_area_sqm: float  # the boundary as drawn
    written_area_sqm: float | None
    on_site_levels: int
    roads: tuple[Road, ...]
    marks: tuple[Mark, ...]
    line_work: tuple[LineGroup, ...]  # near the plot, other than its boundary, roads, contours
    place: str  # village, mandal and district as written on the sheet
    warnings: tuple[str, ...]

    @property
    def area_sqm(self) -> float:
        """The written area where there is one (it is the documented one), else the drawn."""
        return self.written_area_sqm or self.gross_area_sqm

    def as_dict(self) -> dict:
        return {
            "survey": self.survey, "gross_area_sqm": self.gross_area_sqm,
            "written_area_sqm": self.written_area_sqm, "on_site_levels": self.on_site_levels,
            "roads": [{"number": i, **road.as_dict()} for i, road in enumerate(self.roads, 1)],
            "marks": [asdict(mark) for mark in self.marks],
            "line_work_near_plot": [asdict(group) for group in self.line_work],
            "place": self.place, "warnings": list(self.warnings),
        }


def extract(path: str | Path) -> Draft:
    """Everything the survey itself can settle, and the clues to what it cannot."""
    survey = read_survey(Path(path))
    marks = tuple(
        Mark(kind, label.text.strip(),
             round(survey.boundary.distance(Point(label.x, label.y)), 1), label.nearby)
        for label in survey.labels for kind, pattern in MARKS.items() if pattern.search(label.text)
    )
    place = ", ".join(dict.fromkeys(
        lb.text.strip(" ,") for lb in survey.labels if PLACE.search(lb.text)))
    written = survey.stated_area_sqm
    return Draft(
        survey=Path(path).name,
        gross_area_sqm=round(survey.area_sqm, 1),
        written_area_sqm=round(written, 1) if written else None,
        on_site_levels=sum(level.on_site for level in survey.levels),
        roads=roads_near(survey),
        marks=marks,
        line_work=tuple(g for g in survey.line_groups if not _known(g.key, survey.boundary_key)),
        place=place,
        warnings=survey.warnings,
    )


def _known(key: str, boundary_key: str | None) -> bool:
    """The boundary, the roads and the contours are read already; the rest may be water."""
    profile = PdfProfile()
    known = {boundary_key, colour_hex(profile.road_colour), colour_hex(profile.contour_colour)}
    return key in known or any(hint in key.upper() for hint in ("ROAD", "CONTOUR"))


def render(draft: Draft) -> str:
    """The survey's facts as an architect would read them."""
    written = (f", written {draft.written_area_sqm:,.1f} m²" if draft.written_area_sqm else
               ", no area written on the sheet")
    lines = [f"From the survey {draft.survey}:",
             f"  plot {draft.gross_area_sqm:,.1f} m² as drawn{written}; "
             f"{draft.on_site_levels} spot levels on the plot"]
    lines += [f"  road {i}: {_road_line(road)}" for i, road in enumerate(draft.roads, 1)]
    lines += [f"  marked: {_mark_line(mark)}" for mark in draft.marks]
    if draft.place:
        lines.append(f"  place: {draft.place}")
    lines += [f"  warning: {w}" for w in draft.warnings]
    return "\n".join(lines)


def _road_line(road: Road) -> str:
    where = "touching the plot" if road.distance_m < 1 else f"{road.distance_m:.1f} m off"
    divided = ", divided" if road.divided else ""
    return (f"to the {road.side}, {road.width_m:.2f} m drawn ({road.width_ft:.0f} ft){divided}, "
            f"{where}")


def _mark_line(mark: Mark) -> str:
    near = ", ".join(f"{key} {m:g} m" for key, m in mark.nearby) or "none within reach"
    return f"{mark.kind} '{mark.text}', {mark.distance_m:g} m from the plot (nearest lines: {near})"


def questions(draft: Draft) -> tuple[Question, ...]:
    """What the survey leaves open, then the brief. Each shows what the drawing suggests."""
    return (*_road_questions(draft), *_edge_questions(draft), Question(
        "authority", f"Whose building rules apply ({', '.join(AUTHORITIES)})" + (
            f". The survey says: {draft.place}" if draft.place else ""),
        default="HMDA", parse=_authority,
    ), Question(
        "inside_cure", "Is the site inside the Core Urban Region, CURE (yes, no or unknown)? "
        "There GHMC's rules apply and parking is 30%", default="unknown", parse=_tristate,
    ), *_brief(draft))


def _road_questions(draft: Draft) -> list[Question]:
    roads = draft.roads
    if roads:
        listing = "\n".join(f"    {i}: {_road_line(r)}" for i, r in enumerate(roads, 1))
        first = Question("main_road", f"Which road does the site take its access from?\n"
                         f"{listing}\n  Its number", default="1" if len(roads) == 1 else "",
                         example="1", parse=lambda v: _pick(v, len(roads)))
    else:
        first = Question("main_road", "No road was found on the survey. Which side does the "
                         "access road run along (N, NE, E ... NW)", example="W", parse=_side)
    return [first, Question(
        "road_row", "Its legal right of way, e.g. '60 ft' or '18.3 m', or 'as drawn' to use the "
        "survey's measure (it then stays an unverified drawing value)",
        example="60 ft", parse=_row,
    ), Question(
        "road_row_source", "Where does that width come from: 1 a certified right of way, "
        "2 declared on the site plan, 3 no document yet", default="3",
        parse=lambda v: _pick(v, len(ROW_SOURCES)),
        when=lambda a: not _as_drawn(a.get("road_row", "")),
    ), Question(
        "dead_end", "Does that road end at the plot (yes, no or unknown)? Above 30 m a "
        "residential block may not stand on a dead end", default="unknown", parse=_tristate,
    )]


def _edge_questions(draft: Draft) -> list[Question]:
    widening = [m for m in draft.marks if m.kind == "road widening"]
    seen = ("The survey marks " + "; ".join(_mark_line(m) for m in widening) + ". "
            if widening else "The survey marks no road widening. ")
    water = [m for m in draft.marks if m.kind in ("water", "HT line")]
    marked = ("The survey marks " + "; ".join(_mark_line(m) for m in water) + ". "
              if water else "The survey marks no water or HT line. ")
    work = ", ".join(f"{g.key} {g.length_m:g} m{' crossing' if g.crosses_plot else ''}"
                     for g in draft.line_work) or "none"
    return [Question(
        "surrender", f"{seen}Is land given up for road widening or a new road? 'no', or the net "
        "plot area or the area given up, and the side it comes off",
        example="net 22686 sq yd, E", parse=_surrender,
    ), Question(
        "water", f"{marked}Other line work near the plot: {work}. Is a lake, nala or river near "
        f"the plot? 'no', or its colour (PDF) or 'layer NAME,' (DXF) and class ({WATER_CLASSES})",
        default="" if water else "no", example="#00FFFF nala over 10 m", parse=_water,
    )]


def _brief(draft: Draft) -> tuple[Question, ...]:
    return (
        Question("name", "Project name", default=Path(draft.survey).stem.replace("_", " ")),
        Question("mix", "What mix of flats", default="70% 2BHK, 30% 3BHK", parse=parse_mix),
        Question("floors", "Floors above the stilt, or 'max' for the height that sells most",
                 default="max", parse=_floors),
        Question("club_house", "Include the club house and amenities (yes or no)",
                 default="yes", parse=_yes_no),
    )


def missing(draft: Draft, answers: dict[str, str]) -> list[str]:
    """Questions a scripted set of answers leaves unanswered or answers wrongly."""
    problems, seen = [], {}
    for question in questions(draft):
        if question.when is not None and not question.when(seen):
            continue
        value = (answers.get(question.key) or question.default).strip()
        seen[question.key] = value
        if not value and not question.optional:
            problems.append(f"{question.key}: not answered ({question.prompt.splitlines()[0]})")
            continue
        try:
            if value and question.parse:
                question.parse(value)
        except ValueError as exc:
            problems.append(f"{question.key}: {exc}")
    return problems


def build_project(draft: Draft, answers: dict[str, str],
                  defaults: WorkspaceDefaults | None = None) -> dict:
    """The project file from the survey and the answers, with every value's source noted."""
    defaults = defaults or WorkspaceDefaults()
    problems = missing(draft, answers)
    if problems:
        raise ValueError("Unanswered or unclear: " + "; ".join(problems))
    given = {q.key: (answers.get(q.key) or q.default).strip() for q in questions(draft)}
    site, sources = _road_site(draft, given)
    surrender = _surrender(given["surrender"])
    site["gross_area_sqm"] = round(draft.area_sqm, 1)
    sources["gross_area_sqm"] = "survey: written area" if draft.written_area_sqm else (
        "survey: drawn boundary")
    if surrender:
        kind, area, side = surrender
        site["net_area_sqm"] = round(area if kind == "net" else draft.area_sqm - area, 1)
        sources["net_area_sqm"] = f"architect: {given['surrender']}"
        if side:
            site["road_strip_side"] = side
    water = _water(given["water"])
    if water:
        site["water"] = water
        sources["water"] = f"architect: {given['water']}"
    if given["authority"].upper() != "OTHER":
        site["authority"] = given["authority"].upper()
    site["inside_cure"] = TRISTATE[given["inside_cure"].lower()]
    layout = {
        "unit_mix": parse_mix(given["mix"]),
        "floor_height_m": defaults.floor_height_m,
        "stilt_height_m": defaults.stilt_height_m,
        "common_area_pct": defaults.common_area_pct,
        "club_house": _yes_no(given["club_house"]),
        "options": 3,
    }
    if defaults.max_tower_length_m:
        layout["max_tower_length_m"] = defaults.max_tower_length_m
    if given["floors"].lower() == "max":
        layout["floors"] = _most_floors(site, draft, defaults)
        layout["maximise"] = True
    else:
        layout["floors"] = int(given["floors"])
    project = {"name": given["name"], "site": site, "layout": layout, "sources": sources}
    Project.model_validate(project)  # an impossible answer fails here, not in the solver
    return project


def _road_site(draft: Draft, given: dict[str, str]) -> tuple[dict, dict[str, str]]:
    road = draft.roads[int(given["main_road"]) - 1] if draft.roads else None
    site: dict = {"road_dead_end": TRISTATE[given["dead_end"].lower()]}
    sources: dict[str, str] = {}
    if _as_drawn(given["road_row"]):
        if road is None:
            raise ValueError("No road was measured on the survey, so give its width.")
        site["abutting_road_m"] = round(road.width_m, 2)
        site["abutting_road_status"] = "UNVERIFIED_DRAWING_VALUE"
        sources["abutting_road"] = f"survey: the road to the {road.side}, as drawn"
    else:
        unit, width = parse_length(given["road_row"])
        site[f"abutting_road_{unit}"] = width
        site["abutting_road_status"] = ROW_SOURCES[int(given.get("road_row_source") or 3) - 1]
        sources["abutting_road"] = f"architect: {given['road_row']}"
    if road is not None:
        site["measured_carriageway_m"] = round(road.width_m, 2)
        sources["measured_carriageway_m"] = (
            f"survey: the road to the {road.side}, {road.distance_m:.1f} m off")
    return site, sources


def _most_floors(site: dict, draft: Draft, defaults: WorkspaceDefaults) -> int:
    road_m = site.get("abutting_road_m") or site["abutting_road_ft"] * M_PER_FT
    limit = max_floors(site.get("net_area_sqm") or draft.area_sqm, road_m,
                       defaults.floor_height_m, defaults.stilt_height_m, site["road_dead_end"])
    if not limit.high_rise:
        raise ValueError(f"This plot cannot take a high-rise ({limit.limited_by}), and layouts "
                         "are drawn for high-rise only so far: give a number of floors.")
    if limit.floors_stilt_counted is None:
        raise ValueError("The road sets no height limit here, so 'max' has no top: give a "
                         "number of floors.")
    return limit.floors_stilt_counted  # our reading of rule 2(e): the stilt counts


def save(project: dict, path: str | Path) -> Path:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(project, indent=2) + "\n")
    return out


# Answers are checked as they are typed; each parser says what it wanted.

def _pick(value: str, count: int) -> int:
    if not value.strip().isdigit() or not 1 <= int(value) <= count:
        raise ValueError(f"give a number from 1 to {count}")
    return int(value)


def _side(value: str) -> str:
    side = _WORDS.get(re.sub(r"[\s-]", "", value.upper()), value.strip().upper())
    if side not in COMPASS:
        raise ValueError("give a side: N, NE, E, SE, S, SW, W or NW")
    return side


def _as_drawn(value: str) -> bool:
    return value.strip().lower() in ("as drawn", "drawn", "as measured")


def _row(value: str) -> str:
    if not _as_drawn(value):
        parse_length(value)
    return value


def _tristate(value: str) -> str:
    if value.strip().lower() not in TRISTATE:
        raise ValueError("say yes, no or unknown")
    return value


def _yes_no(value: str) -> bool:
    if value.strip().lower() not in ("yes", "no"):
        raise ValueError("say yes or no")
    return value.strip().lower() == "yes"


def _floors(value: str) -> str:
    if value.strip().lower() != "max" and not (value.strip().isdigit() and int(value) > 0):
        raise ValueError("give a number of floors, or 'max'")
    return value


def _authority(value: str) -> str:
    if value.strip().upper() not in AUTHORITIES:
        raise ValueError(f"one of {', '.join(AUTHORITIES)}")
    return value


_AREA = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*(sq\.?\s*y(?:ar)?ds?|sqyds?|yd2|"
                   r"sq\.?\s*m(?:ts?|etres?)?|sqm|m2|m²|sq\.?\s*ft|sqft|ft2)", re.I)


def _surrender(value: str) -> tuple[str, float, str | None] | None:
    """'no' -> None; 'net 22686 sq yd, E' or '1163 m2 E' -> (net|given, m², side)."""
    if value.strip().lower() in ("no", "none", "nil", "0"):
        return None
    match = _AREA.search(value)
    if not match:
        raise ValueError("write it like 'net 22686 sq yd, E' or '1163 m2, E', or 'no'")
    number, unit = float(match.group(1).replace(",", "")), match.group(2).lower()
    area = (sqyd_to_sqm(number) if "y" in unit else
            sqft_to_sqm(number) if "f" in unit else number)
    rest = (value[:match.start()] + " " + value[match.end():]).upper()
    rest = re.sub(r"(NORTH|SOUTH)[\s-]+(EAST|WEST)", r"\1\2", rest)  # 'north-west' is one side
    sides = [_WORDS.get(word, word) for word in re.findall(r"[A-Z]+", rest)]
    side = next((s for s in sides if s in COMPASS), None)
    return ("net" if "NET" in rest.split() else "given", area, side)


def _water(value: str) -> list[dict]:
    """'no' -> []; '#00FFFF nala over 10 m' or 'layer NALA, nala up to 10 m', ';' between."""
    if value.strip().lower() in ("no", "none"):
        return []
    found = []
    for part in filter(None, (p.strip() for p in value.split(";"))):
        if part.startswith("#"):
            key, _, words = part.partition(" ")
            found.append({"kind": _water_kind(words), "survey_colour": key.upper()})
        elif part.lower().startswith("layer "):
            name, _, words = part[len("layer "):].partition(",")
            found.append({"kind": _water_kind(words), "survey_layer": name.strip()})
        else:
            raise ValueError("start with the colour, e.g. '#00FFFF nala over 10 m', or "
                             "'layer NALA, nala up to 10 m'")
    return found


def _water_kind(words: str) -> str:
    text = re.sub(r"[\s_-]", "", words.lower())
    if text in rules.WATER_BUFFER_M:
        return text
    if "river" in text:
        return "river"
    lake = "lake" in text or "tank" in text or "cheruvu" in text or "kunta" in text
    if lake and re.search(r"under|below|lessthan|<", text):
        return "lake_under_10ha"
    if lake:
        return "lake_10ha_or_more"
    if re.search(r"nala|drain|canal|stream", text):
        return "nala_up_to_10m" if re.search(r"upto|under|below|lessthan|<", text) else (
            "nala_over_10m")
    raise ValueError(f"say its class: {WATER_CLASSES}")
