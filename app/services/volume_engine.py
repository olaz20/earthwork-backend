"""Area / cut-fill volume engine. Pure numpy/scipy/shapely: no database, no FastAPI.

Two methods share one surface model (see ``surface_model``):

grid  Regular grid anchored at the site's lower-left corner. Cells straddling the site
      (or fill) boundary are clipped exactly with shapely, weighted by the clipped area
      and sampled at the centroid of the clipped piece, so no boundary area is lost or
      double counted.

tin   Both surfaces are evaluated on one common Delaunay triangulation (union of both
      surveys' vertices + the densified site boundary). The difference surface dz is
      linear inside every triangle, so each triangle is split exactly along the dz = 0
      line into fill and cut pieces, clipped to the region, and integrated exactly
      (area x dz at the centroid of a linear function).

Sign convention: dz = progress - initial.  dz > 0 is fill, dz < 0 is cut.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Literal

import numpy as np
import shapely
from scipy.spatial import Delaunay, QhullError

from .surface_model import (
    SurfaceConfig,
    SurfaceModel,
    clean_points,
    point_spacing,
)

_TARGET_CELLS = 250_000
_MAX_BOUNDARY_VERTICES = 50_000
_TRI_CHUNK = 200_000
_MIN_PIECE_AREA = 1e-12


class EngineError(ValueError):
    """Inputs are geometrically unusable (bad polygon, no overlap, grid too large...)."""


@dataclass(frozen=True)
class EngineParams:
    method: Literal["grid", "tin"] = "grid"
    cell_size: float | None = None
    boundary_spacing: float | None = None
    dz_tolerance: float = 0.0
    cut_scope: Literal["site", "fill_boundary"] = "site"
    max_cells: int = 4_000_000
    surface: SurfaceConfig = field(default_factory=SurfaceConfig)


@dataclass
class EngineResult:
    site_area: float
    fill_area: float
    fill_volume: float
    cut_volume: float
    resolved: dict
    diagnostics: dict


@dataclass
class _Integral:
    area: float = 0.0
    fill_area: float = 0.0
    cut_area: float = 0.0
    fill_volume: float = 0.0
    cut_volume: float = 0.0
    max_fill_depth: float = 0.0
    max_cut_depth: float = 0.0
    extrapolated_area: float = 0.0
    max_extrapolation_distance: float = 0.0
    pieces: int = 0

    def add(self, area, dz, tol, extrapolated=None, distance=None) -> None:
        pos, neg = dz > tol, dz < -tol
        self.area += float(area.sum())
        self.fill_area += float(area[pos].sum())
        self.cut_area += float(area[neg].sum())
        self.fill_volume += float((area * dz)[pos].sum())
        self.cut_volume += float(-(area * dz)[neg].sum())
        self.max_fill_depth = max(self.max_fill_depth, float(dz[pos].max(initial=0.0)))
        self.max_cut_depth = max(self.max_cut_depth, float((-dz[neg]).max(initial=0.0)))
        self.pieces += len(area)
        if extrapolated is not None:
            self.extrapolated_area += float(area[extrapolated].sum())
            if distance is not None and distance.size:
                self.max_extrapolation_distance = max(
                    self.max_extrapolation_distance, float(distance.max())
                )


# ---------------------------------------------------------------------------- geometry
def build_region(xy: np.ndarray, label: str) -> tuple[shapely.Geometry, list[str]]:
    """Polygon from ordered vertices; repairs self-intersections instead of failing."""
    pts = np.asarray(xy, dtype=float)
    pts = pts[np.isfinite(pts).all(axis=1)]
    if len(pts) > 1 and np.allclose(pts[0], pts[-1]):
        pts = pts[:-1]
    if len(pts) < 3:
        raise EngineError(f"{label} needs at least 3 distinct vertices")
    poly = shapely.Polygon(pts)
    warnings: list[str] = []
    if not poly.is_valid:
        parts = [
            g
            for g in shapely.get_parts(shapely.make_valid(poly))
            if g.geom_type in ("Polygon", "MultiPolygon") and g.area > 0
        ]
        if not parts:
            raise EngineError(f"{label} is degenerate (zero area)")
        poly = shapely.union_all(parts)
        warnings.append(f"{label} was self-intersecting and was repaired automatically")
    if poly.area <= 0:
        raise EngineError(f"{label} has zero area")
    return poly, warnings


def _clip(geoms: np.ndarray, region: shapely.Geometry) -> np.ndarray:
    out = geoms.copy()
    inside = shapely.contains(region, geoms)
    if (~inside).any():
        out[~inside] = shapely.intersection(geoms[~inside], region)
    return out


# ------------------------------------------------------------------------------- grid
def _grid_integrate(region, origin, cell, m0, m1, tol, max_cells) -> _Integral:
    ox, oy = origin
    bx0, by0, bx1, by1 = region.bounds
    i0, i1 = math.floor((bx0 - ox) / cell), math.ceil((bx1 - ox) / cell)
    j0, j1 = math.floor((by0 - oy) / cell), math.ceil((by1 - oy) / cell)
    nx, ny = max(i1 - i0, 1), max(j1 - j0, 1)
    if nx * ny > max_cells:
        raise EngineError(
            f"grid would have {nx * ny:,} cells (limit {max_cells:,}); increase cell_size"
        )
    shapely.prepare(region)
    out = _Integral()
    xs = ox + (i0 + np.arange(nx)) * cell
    rows = max(1, 250_000 // nx)
    for r in range(0, ny, rows):
        ys = oy + (j0 + np.arange(r, min(ny, r + rows))) * cell
        gx, gy = np.meshgrid(xs, ys)
        x0, y0 = gx.ravel(), gy.ravel()
        boxes = shapely.box(x0, y0, x0 + cell, y0 + cell)
        hit = shapely.intersects(region, boxes)
        if not hit.any():
            continue
        boxes, x0, y0 = boxes[hit], x0[hit], y0[hit]
        area = np.full(len(boxes), cell * cell)
        cx, cy = x0 + cell / 2, y0 + cell / 2
        partial = ~shapely.contains(region, boxes)
        if partial.any():
            piece = shapely.intersection(boxes[partial], region)
            area[partial] = shapely.area(piece)
            c = shapely.centroid(piece)
            cx[partial], cy[partial] = shapely.get_x(c), shapely.get_y(c)
        keep = (area > _MIN_PIECE_AREA) & np.isfinite(cx) & np.isfinite(cy)
        area, cx, cy = area[keep], cx[keep], cy[keep]
        if not len(area):
            continue
        q = np.column_stack([cx, cy])
        e0, e1 = m0.evaluate(q), m1.evaluate(q)
        out.add(
            area,
            e1.z - e0.z,
            tol,
            extrapolated=e0.extrapolated | e1.extrapolated,
            distance=np.maximum(e0.distance, e1.distance),
        )
    return out


# -------------------------------------------------------------------------------- tin
@dataclass
class _Mesh:
    P: np.ndarray  # (T, 3, 2) absolute vertex coordinates
    d: np.ndarray  # (T, 3) dz at vertices
    x0: np.ndarray
    y0: np.ndarray
    d0: np.ndarray
    a: np.ndarray  # d(dz)/dx
    b: np.ndarray  # d(dz)/dy
    extrapolated_vertex_fraction: float
    max_extrapolation_distance: float
    vertex_count: int


def _build_mesh(m0, m1, boundary_xy, site, spacing) -> _Mesh:
    pts = np.vstack([m0.xy, m1.xy, boundary_xy])
    _, first = np.unique(np.round(pts, 6), axis=0, return_index=True)
    pts = pts[np.sort(first)]
    # Only vertices inside the integrated region (or on its boundary) can influence the result;
    # evaluating the others would demand extrapolation for no reason.
    inside = shapely.covers(site.buffer(1e-6), shapely.points(pts))
    pts = pts[inside]
    if len(pts) < 3:
        raise EngineError("too few vertices inside the site to build a TIN")
    try:
        tri = Delaunay(pts - pts.mean(axis=0))
    except QhullError as exc:
        raise EngineError("vertices are collinear; cannot build a TIN") from exc

    e0, e1 = m0.evaluate(pts), m1.evaluate(pts)
    dz = e1.z - e0.z
    in_site = shapely.covers(site, shapely.points(pts))
    extrap = e0.extrapolated | e1.extrapolated
    frac = float(extrap[in_site].mean()) if in_site.any() else 0.0
    dist = np.maximum(e0.distance, e1.distance)
    max_dist = float(dist[in_site].max()) if in_site.any() else 0.0

    P, d = pts[tri.simplices], dz[tri.simplices]
    ux, uy = P[:, 1, 0] - P[:, 0, 0], P[:, 1, 1] - P[:, 0, 1]
    vx, vy = P[:, 2, 0] - P[:, 0, 0], P[:, 2, 1] - P[:, 0, 1]
    det = ux * vy - uy * vx
    ok = np.abs(det) > 1e-10
    P, d, ux, uy, vx, vy, det = (arr[ok] for arr in (P, d, ux, uy, vx, vy, det))
    du, dv = d[:, 1] - d[:, 0], d[:, 2] - d[:, 0]
    return _Mesh(
        P=P,
        d=d,
        x0=P[:, 0, 0],
        y0=P[:, 0, 1],
        d0=d[:, 0],
        a=(du * vy - uy * dv) / det,
        b=(ux * dv - du * vx) / det,
        extrapolated_vertex_fraction=frac,
        max_extrapolation_distance=max_dist,
        vertex_count=len(pts),
    )


def _clip_halfplane(P: np.ndarray, d: np.ndarray, keep_pos: bool) -> list[np.ndarray]:
    """Sutherland-Hodgman clip of one triangle against dz >= 0 (or dz <= 0)."""
    ring = []
    for i in range(3):
        j = (i + 1) % 3
        di, dj = d[i], d[j]
        if (di >= 0) if keep_pos else (di <= 0):
            ring.append(P[i])
        if (di > 0 > dj) or (di < 0 < dj):
            t = di / (di - dj)
            ring.append(P[i] + t * (P[j] - P[i]))
    return ring


def _tin_integrate(mesh: _Mesh, region, tol) -> _Integral:
    shapely.prepare(region)
    out = _Integral()
    total = len(mesh.P)
    for s in range(0, total, _TRI_CHUNK):
        P, d = mesh.P[s : s + _TRI_CHUNK], mesh.d[s : s + _TRI_CHUNK]
        tris = shapely.polygons(P)
        hit = np.nonzero(shapely.intersects(region, tris))[0]
        if not len(hit):
            continue
        P, d, tris, owner = P[hit], d[hit], tris[hit], s + hit
        pure_pos = (d >= 0).all(axis=1)
        pure = pure_pos | (d <= 0).all(axis=1)
        geoms = [tris[pure]]
        owners = [owner[pure]]
        extra_g, extra_o = [], []
        for k in np.nonzero(~pure)[0]:  # triangles crossed by the dz = 0 line
            for keep_pos in (True, False):
                ring = _clip_halfplane(P[k], d[k], keep_pos)
                if len(ring) >= 3:
                    extra_g.append(shapely.Polygon(ring))
                    extra_o.append(owner[k])
        if extra_g:
            eg = np.empty(len(extra_g), dtype=object)
            eg[:] = extra_g
            geoms.append(eg)
            owners.append(np.asarray(extra_o))
        geoms, owners = np.concatenate(geoms), np.concatenate(owners)
        big = shapely.area(geoms) > _MIN_PIECE_AREA
        geoms, owners = geoms[big], owners[big]
        if not len(geoms):
            continue
        clipped = _clip(geoms, region)
        area = shapely.area(clipped)
        m = area > _MIN_PIECE_AREA
        if not m.any():
            continue
        c = shapely.centroid(clipped[m])
        cx, cy, own = shapely.get_x(c), shapely.get_y(c), owners[m]
        dz = mesh.d0[own] + mesh.a[own] * (cx - mesh.x0[own]) + mesh.b[own] * (cy - mesh.y0[own])
        out.add(area[m], dz, tol)
    return out


# ------------------------------------------------------------------------ orchestration
def compute_earthwork(
    initial_xyz: np.ndarray,
    progress_xyz: np.ndarray,
    site_xy: np.ndarray,
    fill_xy: np.ndarray | None,
    params: EngineParams,
) -> EngineResult:
    warnings: list[str] = []

    site, w = build_region(site_xy, "site boundary")
    warnings += w
    fill_region = None
    if fill_xy is not None:
        fill, w = build_region(fill_xy, "fill boundary")
        warnings += w
        fill_region = shapely.intersection(fill, site)
        if fill_region.is_empty or fill_region.area <= 0:
            raise EngineError("fill boundary does not overlap the site boundary")
        if fill_region.area < 0.999 * fill.area:
            warnings.append("part of the fill boundary lies outside the site and was clipped")

    p0, _ = clean_points(initial_xyz)
    p1, _ = clean_points(progress_xyz)
    spacing = min(point_spacing(p0), point_spacing(p1))

    # With a fill boundary and cut_scope="fill_boundary" nothing outside the fill polygon is
    # integrated, so the surveys only need to cover the fill area (not the whole site).
    only_fill = fill_region is not None and params.cut_scope == "fill_boundary"
    work = fill_region if only_fill else site

    cell = None
    if params.method == "grid":
        cell = params.cell_size or max(math.sqrt(work.area / _TARGET_CELLS), 0.25 * spacing)
    b_spacing = params.boundary_spacing or (cell if cell else spacing)
    b_spacing = max(b_spacing, work.length / _MAX_BOUNDARY_VERTICES)
    boundary_xy = shapely.get_coordinates(shapely.segmentize(work, b_spacing))

    m0 = SurfaceModel(initial_xyz, params.surface, conform_to_xy=boundary_xy, label="initial survey")
    m1 = SurfaceModel(progress_xyz, params.surface, conform_to_xy=boundary_xy, label="progress survey")
    tol = params.dz_tolerance

    if params.method == "grid":
        origin = work.bounds[:2]

        def integrate(region):
            return _grid_integrate(region, origin, cell, m0, m1, tol, params.max_cells)
    else:
        mesh = _build_mesh(m0, m1, boundary_xy, work, spacing)

        def integrate(region):
            return _tin_integrate(mesh, region, tol)

    site_int = None if only_fill else integrate(site)
    region_int = integrate(fill_region) if fill_region is not None else None

    main = site_int if site_int is not None else region_int  # what the diagnostics describe
    if region_int is None:
        fill_area, fill_volume, cut_volume = (
            site_int.fill_area,
            site_int.fill_volume,
            site_int.cut_volume,
        )
    else:
        fill_area, fill_volume = region_int.area, region_int.fill_volume
        cut_volume = (
            site_int.cut_volume if params.cut_scope == "site" else region_int.cut_volume
        )

    diag: dict = {
        "integrated_region": "fill_boundary" if only_fill else "site",
        "integrated_area": main.area,
        "pieces_integrated": main.pieces,
        "survey_point_spacing": spacing,
        "initial_points_used": m0.point_count,
        "progress_points_used": m1.point_count,
        "duplicate_points_merged": m0.duplicates_merged + m1.duplicates_merged,
        "max_fill_depth": main.max_fill_depth,
        "max_cut_depth": main.max_cut_depth,
        "cut_area": main.cut_area,
    }
    if params.method == "grid":
        frac = main.extrapolated_area / main.area if main.area else 0.0
        diag["extrapolated_area_fraction"] = frac
        diag["max_extrapolation_distance"] = main.max_extrapolation_distance
    else:
        frac = mesh.extrapolated_vertex_fraction
        diag["extrapolated_vertex_fraction"] = frac
        diag["max_extrapolation_distance"] = mesh.max_extrapolation_distance
        diag["mesh_vertices"] = mesh.vertex_count
    if frac > 0.10:
        warnings.append(
            f"{frac:.0%} of the site lies outside the survey coverage and was extrapolated; "
            "check the volumes near the boundary"
        )
    if diag["max_extrapolation_distance"] > 3 * spacing:
        warnings.append(
            "boundary extrapolated more than 3x the survey point spacing from the nearest point"
        )
    diag["warnings"] = warnings

    resolved = {
        "method": params.method,
        "cell_size": cell,
        "boundary_spacing": b_spacing,
        "dz_tolerance": tol,
        "cut_scope": params.cut_scope,
        "interpolation": params.surface.interpolation,
        "extrapolation": params.surface.extrapolation,
        "idw_power": params.surface.idw_power,
        "idw_neighbors": params.surface.idw_neighbors,
        "max_extrapolation_distance": params.surface.max_extrapolation_distance,
    }
    return EngineResult(
        site_area=site.area,
        fill_area=fill_area,
        fill_volume=fill_volume,
        cut_volume=cut_volume,
        resolved=resolved,
        diagnostics=diag,
    )
