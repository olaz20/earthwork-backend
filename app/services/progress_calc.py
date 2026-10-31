"""Pure progress logic (no database): turns computation rows into chart points and a summary."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Sequence

from app.schemas.progress import ProgressPoint, ProgressSummary


@dataclass(frozen=True)
class SurveyRun:
    """Latest completed computation for one progress survey."""

    computation_id: int
    survey_id: int
    surveyed_on: date
    method: str | None
    site_area: float
    fill_area: float
    fill_volume: float
    cut_volume: float


def percent_of(part: float, whole: float | None, clamp: bool) -> float | None:
    if not whole or whole <= 0:
        return None
    pct = part / whole * 100.0
    if clamp:
        pct = min(max(pct, 0.0), 100.0)
    return round(pct, 2)


def build_points(runs: Sequence[SurveyRun]) -> list[ProgressPoint]:
    """``runs`` must be ordered by survey date ascending."""
    points: list[ProgressPoint] = []
    prev: SurveyRun | None = None
    for r in runs:
        points.append(
            ProgressPoint(
                date=r.surveyed_on,
                survey_id=r.survey_id,
                computation_id=r.computation_id,
                method=r.method,
                site_area=r.site_area,
                fill_area=r.fill_area,
                fill_volume=r.fill_volume,
                cut_volume=r.cut_volume,
                net_volume=r.fill_volume - r.cut_volume,
                percent_complete_area=percent_of(r.fill_area, r.site_area, clamp=True) or 0.0,
                fill_volume_change=None if prev is None else r.fill_volume - prev.fill_volume,
                fill_area_change=None if prev is None else r.fill_area - prev.fill_area,
                days_since_previous=None if prev is None else (r.surveyed_on - prev.surveyed_on).days,
            )
        )
        prev = r
    return points


def build_summary(
    *,
    project_id: int,
    length_unit: str,
    points: Sequence[ProgressPoint],
    last_survey: tuple[int, date] | None,
    initial_survey_date: date | None,
    progress_surveys: int,
    target_volume: float | None,
) -> ProgressSummary:
    latest = points[-1] if points else None
    return ProgressSummary(
        project_id=project_id,
        length_unit=length_unit,
        has_data=latest is not None,
        latest=latest,
        percent_complete_area=latest.percent_complete_area if latest else None,
        target_volume=target_volume,
        percent_complete_volume=(
            percent_of(latest.fill_volume, target_volume, clamp=False) if latest else None
        ),
        initial_survey_date=initial_survey_date,
        last_survey_date=last_survey[1] if last_survey else None,
        last_survey_id=last_survey[0] if last_survey else None,
        latest_survey_computed=(
            last_survey is None or (latest is not None and latest.survey_id == last_survey[0])
        ),
        days_since_start=(
            (latest.date - initial_survey_date).days if latest and initial_survey_date else None
        ),
        progress_surveys=progress_surveys,
        computed_surveys=len(points),
        fill_volume_change=latest.fill_volume_change if latest else None,
        fill_area_change=latest.fill_area_change if latest else None,
    )