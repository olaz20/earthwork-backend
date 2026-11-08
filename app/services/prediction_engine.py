"""Forecast engine: fits a trend to the computation history and projects it forward.

Pure numpy/scipy: no database, no FastAPI.

Model: ordinary least squares line  value = a + b * days_since_first_survey.
  * linear       uses every survey
  * recent_rate  uses only the last ``recent_points`` surveys (current pace, not the average)

Prediction intervals use Student's t with n - 2 degrees of freedom, so they widen as the
forecast moves away from the data and need at least 3 surveys. Forecast values are clamped to
physical limits (>= 0 for volumes and areas, <= site area for fill area).

A completion date is the first day the trend reaches ``target_value``; the earliest/latest
dates come from where the upper/lower interval bounds reach it.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Literal

import numpy as np
from scipy.optimize import brentq
from scipy.stats import t as student_t

SEARCH_LIMIT_DAYS = 3650  # do not look for a completion date more than 10 years past the data
MAX_FORECAST_POINTS = 500
_STALE_AFTER_DAYS = 60


class PredictionError(ValueError):
    """The history cannot support a forecast (too few surveys, same dates, ...)."""


@dataclass(frozen=True)
class Observation:
    date: date
    value: float
    computation_id: int


@dataclass(frozen=True)
class ForecastParams:
    method: Literal["linear", "recent_rate"] = "linear"
    recent_points: int = 3
    horizon_days: int = 90
    step_days: int = 7
    confidence: float = 0.9
    target_value: float | None = None
    nonnegative: bool = True
    cap: float | None = None  # physical upper limit (e.g. site area for fill area)


class _Line:
    def __init__(self, x: np.ndarray, y: np.ndarray, confidence: float) -> None:
        n = len(x)
        self.n = n
        self.xbar = float(x.mean())
        ybar = float(y.mean())
        self.sxx = float(((x - self.xbar) ** 2).sum())
        if n < 2 or self.sxx <= 1e-12:
            raise PredictionError("the surveys used must be on at least two different dates")
        self.b = float(((x - self.xbar) * (y - ybar)).sum() / self.sxx)
        self.a = ybar - self.b * self.xbar
        sse = float(((y - (self.a + self.b * x)) ** 2).sum())
        sst = float(((y - ybar) ** 2).sum())
        self.r2 = None if sst <= 1e-12 else max(0.0, 1.0 - sse / sst)
        self.dof = n - 2
        self.s = math.sqrt(sse / self.dof) if self.dof > 0 else None
        self.tcrit = float(student_t.ppf((1 + confidence) / 2, self.dof)) if self.dof > 0 else None

    @property
    def has_interval(self) -> bool:
        return self.s is not None

    def predict(self, x) -> np.ndarray:
        return self.a + self.b * np.asarray(x, dtype=float)

    def halfwidth(self, x) -> np.ndarray:
        x = np.asarray(x, dtype=float)
        return self.tcrit * self.s * np.sqrt(1.0 + 1.0 / self.n + (x - self.xbar) ** 2 / self.sxx)


def _first_crossing(f, lo: float, hi: float, samples: int = 4000) -> float | None:
    """Smallest x in [lo, hi] where f(x) >= 0, refined with Brent's method."""
    xs = np.linspace(lo, hi, samples)
    idx = np.nonzero(f(xs) >= 0)[0]
    if idx.size == 0:
        return None
    i = int(idx[0])
    if i == 0:
        return float(xs[0])
    return float(brentq(lambda v: float(f(np.array([v]))[0]), xs[i - 1], xs[i]))


def _day(first: date, x: float) -> date:
    return first + timedelta(days=int(round(x)))


def _iso(d: date | None) -> str | None:
    return d.isoformat() if d else None


def forecast(observations: list[Observation], params: ForecastParams, today: date) -> dict:
    obs = sorted(observations, key=lambda o: (o.date, o.computation_id))
    if len(obs) < 2:
        raise PredictionError(
            "a forecast needs at least 2 completed computations on different survey dates "
            f"(found {len(obs)})"
        )
    first, last = obs[0].date, obs[-1].date
    x_all = np.array([(o.date - first).days for o in obs], dtype=float)
    y_all = np.array([o.value for o in obs], dtype=float)
    warnings: list[str] = []

    if params.method == "recent_rate":
        k = max(2, min(params.recent_points, len(obs)))
        if len(obs) < params.recent_points:
            warnings.append(f"only {len(obs)} surveys exist; the recent-rate fit uses all of them")
        x_fit, y_fit = x_all[-k:], y_all[-k:]
    else:
        x_fit, y_fit = x_all, y_all
    line = _Line(x_fit, y_fit, params.confidence)

    def clamp(v):
        v = np.asarray(v, dtype=float)
        if params.nonnegative:
            v = np.maximum(v, 0.0)
        if params.cap is not None:
            v = np.minimum(v, params.cap)
        return v

    # ---- forecast dates: every step after the last survey, up to horizon days past today
    end = max(last, today) + timedelta(days=params.horizon_days)
    dates: list[date] = []
    d = last + timedelta(days=params.step_days)
    while d <= end:
        dates.append(d)
        d += timedelta(days=params.step_days)
    if not dates or dates[-1] < end:
        dates.append(end)
    if len(dates) > MAX_FORECAST_POINTS:
        raise PredictionError(
            f"this would produce {len(dates)} forecast points (limit {MAX_FORECAST_POINTS}); "
            "reduce horizon_days or increase step_days"
        )
    x_f = np.array([(dd - first).days for dd in dates], dtype=float)
    center = line.predict(x_f)
    if line.has_interval:
        hw = line.halfwidth(x_f)
        lower, upper = clamp(center - hw), clamp(center + hw)
    else:
        lower = upper = None
    center = clamp(center)

    forecast_rows = [
        {
            "date": _iso(dates[i]),
            "value": float(center[i]),
            "lower": None if lower is None else float(lower[i]),
            "upper": None if upper is None else float(upper[i]),
        }
        for i in range(len(dates))
    ]
    fitted = line.predict(x_all)
    history_rows = [
        {"date": _iso(o.date), "computation_id": o.computation_id, "actual": float(o.value), "fitted": float(fitted[i])}
        for i, o in enumerate(obs)
    ]

    # ---- completion date
    completion = None
    if params.target_value is not None:
        completion = _completion(params, line, obs, first, float(x_all[-1]), today)
        if completion["status"] == "unreachable" and line.b <= 0:
            warnings.append("the trend is flat or decreasing, so the target is not reached")

    # ---- warnings
    n = len(obs)
    if n == 2:
        warnings.append("only 2 surveys: the line passes through both exactly, so no confidence interval is available")
    elif n < 5 and params.method == "linear":
        warnings.append(f"only {n} surveys: treat the forecast as rough")
    if line.r2 is not None and n >= 3 and line.r2 < 0.7:
        warnings.append(f"the history is not very linear (R² = {line.r2:.2f}); a straight-line trend may mislead")
    if (today - last).days > _STALE_AFTER_DAYS:
        warnings.append(f"the last survey is {(today - last).days} days old; the forecast starts from it")
    span = max((last - first).days, 1)
    if params.horizon_days > 2 * span:
        warnings.append(f"the forecast reaches {params.horizon_days} days ahead on only {span} days of history")

    summary = {
        "points_used": n,
        "points_in_fit": int(len(x_fit)),
        "first_observation": _iso(first),
        "last_observation": _iso(last),
        "last_value": float(y_all[-1]),
        "rate_per_day": line.b,
        "rate_per_week": line.b * 7.0,
        "r_squared": line.r2,
        "residual_std": line.s,
        "confidence": params.confidence,
        "interval_available": line.has_interval,
        "warnings": warnings,
    }
    return {"history": history_rows, "forecast": forecast_rows, "summary": summary, "completion": completion}


def _completion(params: ForecastParams, line: _Line, obs: list[Observation], first: date,
                x_last: float, today: date) -> dict:
    target = float(params.target_value)
    out = {"target_value": target, "status": "projected", "estimate": None,
           "earliest": None, "latest": None, "days_remaining": None}

    hit = next((o for o in obs if o.value >= target), None)
    if hit is not None:  # already reached in the data
        out.update(status="reached", estimate=_iso(hit.date), earliest=_iso(hit.date),
                   latest=_iso(hit.date), days_remaining=0)
        return out
    if (params.cap is not None and target > params.cap) or line.b <= 0:
        out["status"] = "unreachable"
        return out

    hi = x_last + SEARCH_LIMIT_DAYS
    x_est = _first_crossing(lambda x: line.predict(x) - target, x_last, hi)
    if x_est is None:
        out["status"] = "beyond_limit"
        return out
    est = _day(first, x_est)
    out.update(estimate=_iso(est), days_remaining=(est - today).days)

    if line.has_interval:
        x_early = _first_crossing(lambda x: line.predict(x) + line.halfwidth(x) - target, x_last, hi)
        x_late = _first_crossing(lambda x: line.predict(x) - line.halfwidth(x) - target, x_last, hi)
        out["earliest"] = _iso(_day(first, x_early)) if x_early is not None else None
        out["latest"] = _iso(_day(first, x_late)) if x_late is not None else None  # None: not bounded within limit
    return out