import csv
import io
import math
from array import array
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import BinaryIO

from app.core.config import settings
from app.core.exceptions import FileValidationError

# Accepted header names (case-insensitive) for each coordinate
COLUMN_ALIASES = {
    "x": {"x", "e", "easting"},
    "y": {"y", "n", "northing"},
    "z": {"z", "elevation", "elev", "h", "height"},
}
DELIMITERS = ",;\t"
MAX_REPORTED_ERRORS = 10


@dataclass
class ParsedPoints:
    # array('d') stores raw 8-byte floats: ~24 bytes/point versus
    # hundreds of bytes for a list of tuples.
    xs: array = field(default_factory=lambda: array("d"))
    ys: array = field(default_factory=lambda: array("d"))
    zs: array = field(default_factory=lambda: array("d"))

    def __len__(self) -> int:
        return len(self.xs)

    def append(self, x: float, y: float, z: float) -> None:
        self.xs.append(x)
        self.ys.append(y)
        self.zs.append(z)

    def iter_chunks(self, size: int) -> Iterator[list[tuple[float, float, float]]]:
        for start in range(0, len(self), size):
            end = start + size
            yield list(zip(self.xs[start:end], self.ys[start:end], self.zs[start:end]))


def _to_float(value: str, name: str) -> float:
    try:
        number = float(value.strip())
    except ValueError:
        raise ValueError(f"{name} is not a number: {value!r}") from None
    if not math.isfinite(number):  # float() happily accepts "nan" and "inf"
        raise ValueError(f"{name} must be a finite number: {value!r}")
    return number


def _map_header(row: list[str]) -> dict[str, int]:
    names = [cell.strip().lower() for cell in row]
    mapping: dict[str, int] = {}
    for target, aliases in COLUMN_ALIASES.items():
        for index, name in enumerate(names):
            if name in aliases:
                mapping[target] = index
                break
    missing = [c for c in COLUMN_ALIASES if c not in mapping]
    if missing:
        raise FileValidationError(
            f"Missing required column(s): {', '.join(missing)}. "
            f"The first row must be a header containing x, y, z "
            f"(also accepted: easting/northing/elevation). Found: {row}"
        )
    return mapping


def parse_survey_csv(stream: BinaryIO) -> ParsedPoints:
    """Parse an x,y,z file. All-or-nothing: any bad row rejects the whole file."""
    text = io.TextIOWrapper(stream, encoding="utf-8-sig", newline="")  # strips a BOM
    try:
        sample = text.read(8192)
        text.seek(0)
        first_line = next((ln for ln in sample.splitlines() if ln.strip()), "")
        delimiter = max(DELIMITERS, key=first_line.count)  # comma, semicolon or tab

        reader = csv.reader(text, delimiter=delimiter)
        points = ParsedPoints()
        errors: list[dict] = []
        columns: dict[str, int] | None = None

        for row in reader:
            if not row or all(not cell.strip() for cell in row):
                continue  # blank line
            if columns is None:
                columns = _map_header(row)
                continue

            line = reader.line_num
            needed = max(columns.values()) + 1
            if len(row) < needed:
                errors.append({"line": line, "error": f"expected {needed} columns, got {len(row)}"})
            else:
                try:
                    points.append(
                        _to_float(row[columns["x"]], "x"),
                        _to_float(row[columns["y"]], "y"),
                        _to_float(row[columns["z"]], "z"),
                    )
                except ValueError as exc:
                    errors.append({"line": line, "error": str(exc)})

            if len(errors) >= MAX_REPORTED_ERRORS:
                break
            if len(points) > settings.max_survey_points:
                raise FileValidationError(
                    f"File has more than {settings.max_survey_points:,} points"
                )
    except UnicodeDecodeError as exc:
        raise FileValidationError("File must be UTF-8 encoded text") from exc
    except csv.Error as exc:
        raise FileValidationError(f"Malformed CSV: {exc}") from exc
    finally:
        text.detach()  # don't let the wrapper close the caller's file

    if columns is None:
        raise FileValidationError("File is empty")
    if errors:
        raise FileValidationError(
            f"File has invalid rows (showing up to {MAX_REPORTED_ERRORS})", errors=errors
        )
    return points