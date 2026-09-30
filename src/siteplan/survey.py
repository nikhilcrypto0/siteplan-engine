"""The site survey as the rest of the engine sees it: metres, with y pointing north."""

from __future__ import annotations

import math
from dataclasses import dataclass
from statistics import median

import numpy as np
from shapely.geometry import LineString, Polygon

from siteplan.units import sqm_to_sqft, sqm_to_sqyd

_COMPASS = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")


@dataclass(frozen=True)
class SpotLevel:
    x: float
    y: float
    z: float
    on_site: bool


@dataclass(frozen=True)
class ScaleEstimate:
    """One boundary edge whose written length was matched to its drawn length."""

    written_m: float
    drawn_units: float

    @property
    def metres_per_unit(self) -> float:
        return self.written_m / self.drawn_units


@dataclass(frozen=True)
class Calibration:
    metres_per_unit: float
    agreeing: tuple[ScaleEstimate, ...]
    rejected: tuple[ScaleEstimate, ...]
    fitted_metres_per_unit: float  # the least-squares fit, before any snapping
    snapped_scale: int | None = None  # N of a standard 1:N plot scale, if snapped to it

    @property
    def max_deviation_pct(self) -> float:
        """0 when no labels set the scale (it came from the written area instead)."""
        return max(
            (abs(e.metres_per_unit / self.fitted_metres_per_unit - 1) * 100
             for e in self.agreeing),
            default=0.0,
        )


def calibrate(estimates: list[ScaleEstimate], tolerance_pct: float) -> Calibration | None:
    """Fit the scale most dimension labels agree on; None if fewer than two agree.

    Outliers are dropped against the median, then the rest are fitted by least squares,
    which weights long edges more (a rounded label matters less on a long edge).
    """
    if not estimates:
        return None
    centre = median(e.metres_per_unit for e in estimates)
    agreeing = tuple(
        e for e in estimates if abs(e.metres_per_unit / centre - 1) * 100 <= tolerance_pct
    )
    if len(agreeing) < 2:
        return None
    rejected = tuple(e for e in estimates if e not in agreeing)
    fitted = sum(e.written_m * e.drawn_units for e in agreeing) / sum(
        e.drawn_units**2 for e in agreeing
    )
    return Calibration(fitted, agreeing, rejected, fitted)


@dataclass(frozen=True)
class Terrain:
    """A best-fit plane through the on-site spot levels."""

    lowest: float
    highest: float
    slope_pct: float
    falls_towards: str
    points_used: int


def fit_terrain(levels: tuple[SpotLevel, ...]) -> Terrain | None:
    points = [lv for lv in levels if lv.on_site]
    if len(points) < 3:
        return None
    xy1 = np.array([[p.x, p.y, 1.0] for p in points])
    z = np.array([p.z for p in points])
    (a, b, _), *_ = np.linalg.lstsq(xy1, z, rcond=None)
    # Downhill is against the gradient; bearing is measured clockwise from north (+y).
    bearing = math.degrees(math.atan2(-a, -b)) % 360
    return Terrain(
        lowest=float(z.min()),
        highest=float(z.max()),
        slope_pct=float(math.hypot(a, b) * 100),
        falls_towards=_COMPASS[round(bearing / 45) % 8],
        points_used=len(points),
    )


@dataclass(frozen=True)
class Survey:
    source: str
    boundary: Polygon
    stated_area_sqm: float | None
    calibration: Calibration | None
    levels: tuple[SpotLevel, ...] = ()
    roads: tuple[LineString, ...] = ()
    contours: tuple[LineString, ...] = ()
    water: tuple[LineString, ...] = ()  # only when asked for: its colour or layer is not standard
    warnings: tuple[str, ...] = ()

    @property
    def area_sqm(self) -> float:
        return float(self.boundary.area)

    @property
    def area_difference_pct(self) -> float | None:
        if not self.stated_area_sqm:
            return None
        return (self.area_sqm / self.stated_area_sqm - 1) * 100

    def terrain(self) -> Terrain | None:
        return fit_terrain(self.levels)

    def summary(self) -> dict:
        """Plain numbers for people and for the LLM to quote. No model estimates anything here."""
        from siteplan.roads import roads_near  # roads.py reads a Survey, so import it here

        terrain = self.terrain()
        cal = self.calibration
        return {
            "source": self.source,
            "boundary": {
                "vertices": len(self.boundary.exterior.coords) - 1,
                "perimeter_m": round(self.boundary.length, 2),
                "area_sqm": round(self.area_sqm, 1),
                "area_sqyd": round(sqm_to_sqyd(self.area_sqm), 1),
                "area_sqft": round(sqm_to_sqft(self.area_sqm)),
            },
            "stated_area_sqm": round(self.stated_area_sqm, 1) if self.stated_area_sqm else None,
            "area_difference_pct": (
                round(self.area_difference_pct, 2) if self.area_difference_pct is not None else None
            ),
            "scale": None
            if cal is None
            else {
                "metres_per_drawing_unit": round(cal.metres_per_unit, 6),
                "fitted_metres_per_drawing_unit": round(cal.fitted_metres_per_unit, 6),
                "snapped_to_standard_scale": (
                    f"1:{cal.snapped_scale}" if cal.snapped_scale else None
                ),
                "labels_agreeing": [e.written_m for e in cal.agreeing],
                "labels_rejected": [e.written_m for e in cal.rejected],
                "max_deviation_pct": round(cal.max_deviation_pct, 2),
            },
            "spot_levels": {
                "on_site": sum(lv.on_site for lv in self.levels),
                "off_site": sum(not lv.on_site for lv in self.levels),
            },
            "terrain": None
            if terrain is None
            else {
                "lowest_m": round(terrain.lowest, 2),
                "highest_m": round(terrain.highest, 2),
                "average_slope_pct": round(terrain.slope_pct, 2),
                "falls_towards": terrain.falls_towards,
            },
            "roads": [road.as_dict() for road in roads_near(self)],
            "contours": len(self.contours),
            "warnings": list(self.warnings),
        }
