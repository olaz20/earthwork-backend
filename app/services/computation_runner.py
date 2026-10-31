"""Surface model: interpolation inside the survey, extrapolation out to the boundary.

A ``SurfaceModel`` turns scattered (x, y, z) survey points into a function z = f(x, y)
that is defined *everywhere* the site polygon reaches, not only inside the convex hull
of the survey points.

* Inside the hull of the data:  linear TIN (default), IDW or nearest neighbour.
* Outside the hull (between the data and the site boundary): extrapolation by IDW or
  nearest neighbour. For the linear model the site-boundary vertices are given an
  extrapolated elevation and joined to the hull in a "collar" TIN, so the surface ramps
  continuously from the last survey points to the boundary instead of jumping.

Everything is computed on coordinates centred on the data (UTM-sized eastings/northings
lose precision in Qhull otherwise).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
from scipy.interpolate import LinearNDInterpolator
from scipy.spatial import ConvexHull, Delaunay, QhullError, cKDTree

Interpolation = Literal["linear", "idw", "nearest"]
Extrapolation = Literal["idw", "nearest", "none"]

_DEDUPE_DECIMALS = 6


class SurfaceError(ValueError):
    """The survey points cannot form a usable surface, or coverage is insufficient."""


@dataclass(frozen=True)
class SurfaceConfig:
    interpolation: Interpolation = "linear"
    extrapolation: Extrapolation = "idw"
    idw_power: float = 2.0
    idw_neighbors: int = 12
    # Fail instead of extrapolating further than this from the nearest survey point
    max_extrapolation_distance: float | None = None


@dataclass(frozen=True)
class Evaluation:
    z: np.ndarray
    extrapolated: np.ndarray  # bool: point lies outside the hull of the survey points
    distance: np.ndarray  # distance to nearest survey point (0 when not extrapolated)


def clean_points(xyz: np.ndarray) -> tuple[np.ndarray, int]:
    """Drop non-finite rows and merge coincident XY (average Z). Returns (points, merged)."""
    a = np.asarray(xyz, dtype=float)
    if a.ndim != 2 or a.shape[1] != 3:
        raise SurfaceError("survey points must be an (N, 3) array")
    a = a[np.isfinite(a).all(axis=1)]
    if len(a) < 3:
        raise SurfaceError("at least 3 valid survey points are required")
    keys = np.round(a[:, :2], _DEDUPE_DECIMALS)
    _, inverse = np.unique(keys, axis=0, return_inverse=True)
    inverse = inverse.ravel()
    counts = np.bincount(inverse)
    merged = np.column_stack(
        [np.bincount(inverse, weights=a[:, i]) / counts for i in range(3)]
    )
    if len(merged) < 3:
        raise SurfaceError("survey points collapse to fewer than 3 distinct locations")
    return merged, len(a) - len(merged)


def point_spacing(xy: np.ndarray) -> float:
    """Characteristic point spacing: sqrt(hull area / point count)."""
    xy = np.asarray(xy, dtype=float)[:, :2]
    try:
        area = ConvexHull(xy - xy.mean(axis=0)).volume  # 2-D "volume" is area
    except QhullError as exc:
        raise SurfaceError("survey points are collinear or degenerate") from exc
    return float(np.sqrt(area / len(xy)))


class SurfaceModel:
    def __init__(
        self,
        xyz: np.ndarray,
        config: SurfaceConfig,
        conform_to_xy: np.ndarray | None = None,
    ) -> None:
        pts, self.duplicates_merged = clean_points(xyz)
        self.cfg = config
        self._origin = pts[:, :2].mean(axis=0)
        self._xy = pts[:, :2] - self._origin
        self._z = pts[:, 2]
        self._tree = cKDTree(self._xy)
        self._tin = self._triangulate(self._xy)
        self._linear = (
            LinearNDInterpolator(self._tin, self._z)
            if config.interpolation == "linear"
            else None
        )
        self._collar: LinearNDInterpolator | None = None
        if conform_to_xy is not None and len(conform_to_xy):
            self._collar = self._build_collar(
                np.asarray(conform_to_xy, dtype=float) - self._origin
            )
        self.point_count = len(pts)
        self.spacing = point_spacing(pts)

    # ---- public -----------------------------------------------------------------
    @property
    def xy(self) -> np.ndarray:
        return self._xy + self._origin

    def evaluate(self, xy: np.ndarray) -> Evaluation:
        q = np.asarray(xy, dtype=float).reshape(-1, 2) - self._origin
        n = len(q)
        z = np.full(n, np.nan)
        dist = np.zeros(n)
        inside = self._tin.find_simplex(q) >= 0
        outside = ~inside

        if inside.any():
            qi = q[inside]
            if self._linear is not None:
                z[inside] = self._linear(qi)
            elif self.cfg.interpolation == "idw":
                z[inside] = self._idw(qi)
            else:
                z[inside] = self._nearest(qi)

        if outside.any():
            if self.cfg.extrapolation == "none":
                raise SurfaceError(
                    "computation area extends beyond the survey coverage and "
                    "extrapolation is disabled"
                )
            qo = q[outside]
            d = self._tree.query(qo)[0]
            self._check_distance(d)
            dist[outside] = d
            z[outside] = self._extrapolate(qo)

        # Linear interpolation can return NaN for points on hull edges
        bad = np.isnan(z)
        if bad.any():
            z[bad] = self._direct(q[bad])
        return Evaluation(z=z, extrapolated=outside, distance=dist)

    # ---- internals --------------------------------------------------------------
    @staticmethod
    def _triangulate(xy: np.ndarray) -> Delaunay:
        try:
            return Delaunay(xy)
        except QhullError as exc:
            raise SurfaceError("survey points are collinear or degenerate") from exc

    def _check_distance(self, d: np.ndarray) -> None:
        limit = self.cfg.max_extrapolation_distance
        if limit is not None and d.size and float(d.max()) > limit:
            raise SurfaceError(
                f"extrapolation of {float(d.max()):.2f} exceeds the allowed "
                f"maximum of {limit:.2f}; survey does not cover the site"
            )

    def _nearest(self, q: np.ndarray) -> np.ndarray:
        return self._z[self._tree.query(q)[1]]

    def _idw(self, q: np.ndarray) -> np.ndarray:
        k = min(self.cfg.idw_neighbors, len(self._z))
        d, idx = self._tree.query(q, k=k)
        if k == 1:
            d, idx = d[:, None], idx[:, None]
        with np.errstate(divide="ignore"):
            w = 1.0 / np.power(d, self.cfg.idw_power)
        exact = d < 1e-12
        hit = exact.any(axis=1)
        if hit.any():
            w[hit] = exact[hit].astype(float)
        return (w * self._z[idx]).sum(axis=1) / w.sum(axis=1)

    def _direct(self, q: np.ndarray) -> np.ndarray:
        """Point-wise extrapolation with the configured method (no collar)."""
        if self.cfg.extrapolation == "nearest":
            return self._nearest(q)
        return self._idw(q)

    def _extrapolate(self, q: np.ndarray) -> np.ndarray:
        if self._collar is None:
            return self._direct(q)
        z = self._collar(q)
        bad = np.isnan(z)
        if bad.any():
            z[bad] = self._direct(q[bad])
        return z

    def _build_collar(self, boundary: np.ndarray) -> LinearNDInterpolator | None:
        """TIN of (hull vertices + extrapolated boundary vertices) for the ring around the data."""
        if self.cfg.interpolation != "linear" or self.cfg.extrapolation == "none":
            return None
        outside = self._tin.find_simplex(boundary) < 0
        b_out = boundary[outside]
        if not len(b_out):
            return None
        self._check_distance(self._tree.query(b_out)[0])
        zb = self._direct(b_out)
        hull = np.unique(self._tin.convex_hull)
        pts = np.vstack([self._xy[hull], b_out])
        zz = np.concatenate([self._z[hull], zb])
        _, first = np.unique(np.round(pts, _DEDUPE_DECIMALS), axis=0, return_index=True)
        first = np.sort(first)  # data hull vertices win over coincident boundary vertices
        try:
            tri = Delaunay(pts[first])
        except QhullError:
            return None
        return LinearNDInterpolator(tri, zz[first])