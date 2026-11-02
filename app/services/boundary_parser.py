"""Parse an uploaded vertex file (CSV / TXT) into [(x, y), ...]. Pure: no database, no FastAPI.

Accepted layouts (comma, semicolon, tab or whitespace separated; '#' lines are comments):

    x,y                       easting,northing            (header, any column order/extras)
    500000.0,700000.0         500010.5 700000.2           (no header: exactly two columns)

Headers may name the coordinates x/y, e/n, east/north, easting/northing. Without a header the
file must have exactly two columns, so an ID column is never mistaken for X.
"""
from __future__ import annotations

import math

_X_NAMES = {"x", "e", "east", "easting", "eastings"}
_Y_NAMES = {"y", "n", "north", "northing", "northings"}
_DELIMITERS = (",", ";", "\t")
_MAX_REPORTED_ERRORS = 5


class BoundaryFileError(ValueError):
    """The file cannot be read as a list of vertices."""


def _decode(data: bytes) -> str:
    if not data.strip():
        raise BoundaryFileError("the file is empty")
    if b"\x00" in data[:4096]:
        raise BoundaryFileError("the file looks binary; upload a CSV or TXT file of x,y vertices")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("latin-1")


def _split(line: str, delimiter: str | None) -> list[str]:
    parts = line.split() if delimiter is None else line.split(delimiter)
    return [p.strip().strip('"').strip("'") for p in parts]


def _to_float(token: str) -> float | None:
    try:
        value = float(token)
    except ValueError:
        return None
    return value if math.isfinite(value) else None


def parse_vertices(data: bytes) -> list[tuple[float, float]]:
    text = _decode(data)
    lines = [
        (no, raw.strip())
        for no, raw in enumerate(text.splitlines(), start=1)
        if raw.strip() and not raw.strip().startswith(("#", "//"))
    ]
    if not lines:
        raise BoundaryFileError("the file contains no data rows")

    sample = lines[0][1]
    counts = {d: sample.count(d) for d in _DELIMITERS}
    best = max(counts, key=counts.get)
    delimiter = best if counts[best] > 0 else None  # None -> split on whitespace

    rows = [(no, _split(line, delimiter)) for no, line in lines]

    first_no, first = rows[0]
    has_header = not all(_to_float(c) is not None for c in first[:2])
    if has_header:
        names = [c.lower() for c in first]
        xs = [i for i, n in enumerate(names) if n in _X_NAMES]
        ys = [i for i, n in enumerate(names) if n in _Y_NAMES]
        if not xs or not ys:
            raise BoundaryFileError(
                f"line {first_no}: header must name the coordinate columns "
                "(x/y, e/n, easting/northing)"
            )
        xi, yi = xs[0], ys[0]
        rows = rows[1:]
    else:
        if len(first) != 2:
            raise BoundaryFileError(
                f"line {first_no}: found {len(first)} columns without a header; add a header "
                "row (e.g. id,x,y) or upload exactly two columns: x,y"
            )
        xi, yi = 0, 1

    vertices: list[tuple[float, float]] = []
    problems: list[str] = []
    need = max(xi, yi) + 1
    for no, cells in rows:
        if len(cells) < need:
            problems.append(f"line {no}: expected at least {need} columns, found {len(cells)}")
        else:
            x, y = _to_float(cells[xi]), _to_float(cells[yi])
            if x is None or y is None:
                bad = cells[xi] if x is None else cells[yi]
                problems.append(f"line {no}: '{bad}' is not a valid number")
            else:
                vertices.append((x, y))
        if len(problems) >= _MAX_REPORTED_ERRORS:
            break
    if problems:
        raise BoundaryFileError("; ".join(problems))
    if len(vertices) < 3:
        raise BoundaryFileError(f"found {len(vertices)} vertices; a boundary needs at least 3")
    return vertices