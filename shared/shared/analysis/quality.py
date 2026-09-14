"""Data quality checks both modules show as warnings (plan, section 8.8): what the fixes
allow the reader to trust, said plainly."""

from __future__ import annotations

import uuid

import numpy as np

from shared.analysis.base import Warning
from shared.analysis.primitives.trajectory import Steps, Trajectory


def quality_report(
    trajectory: Trajectory,
    s: Steps,
    *,
    subject_id: uuid.UUID,
    window_seconds: float,
    excluded: int,
    few_fixes: int = 30,
) -> tuple[list[Warning], dict[str, float]]:
    """Warnings for one subject and the figures behind them (the document's provenance)."""
    warnings: list[Warning] = []
    figures: dict[str, float] = {"fixes": float(len(trajectory)), "excluded": float(excluded)}
    n = len(trajectory)
    if n < few_fixes:
        warnings.append(
            Warning(
                code="few_fixes",
                subject_id=subject_id,
                text=(
                    f"Only {n} fixes in the period; home range and clusters are left out "
                    f"below {few_fixes}."
                ),
            )
        )
        return warnings, figures
    dt = s.dt_s[s.dt_s > 0]
    median = float(np.median(dt)) if dt.size else 0.0
    p90 = float(np.percentile(dt, 90)) if dt.size else 0.0
    figures["median_interval_s"] = median
    figures["p90_interval_s"] = p90
    if median > 0:
        expected = window_seconds / median
        missing = max(0.0, 1 - n / expected) if expected > 0 else 0.0
        figures["missing_share"] = round(missing, 3)
        if missing > 0.2:
            warnings.append(
                Warning(
                    code="missing_fixes",
                    subject_id=subject_id,
                    text=(
                        f"{round(missing * 100)}% of the expected fixes are missing in this period."
                    ),
                )
            )
        elif missing > 0.05:
            warnings.append(
                Warning(
                    code="missing_fixes",
                    level="notice",
                    subject_id=subject_id,
                    text=(
                        f"{round(missing * 100)}% of the expected fixes are missing in this period."
                    ),
                )
            )
    gap_seconds = float(s.dt_s[s.gap].sum()) if len(s) else 0.0
    gap_share = gap_seconds / window_seconds if window_seconds > 0 else 0.0
    figures["gap_share"] = round(gap_share, 3)
    if gap_share > 0.25:
        warnings.append(
            Warning(
                code="gaps",
                subject_id=subject_id,
                text=(
                    f"{round(gap_share * 100)}% of the period lies in gaps; large gaps make "
                    "residence time and home range estimates unreliable."
                ),
            )
        )
    if median > 0 and p90 > 3 * median:
        warnings.append(
            Warning(
                code="irregular_sampling",
                level="notice",
                subject_id=subject_id,
                text=(
                    "The sampling is irregular; residence time on a grid is biased by "
                    "uneven intervals."
                ),
            )
        )
    if excluded:
        warnings.append(
            Warning(
                code="impossible_speed",
                level="notice",
                subject_id=subject_id,
                text=f"{excluded} fixes were left out for an impossible speed.",
            )
        )
    if trajectory.duplicates:
        warnings.append(
            Warning(
                code="duplicates",
                level="notice",
                subject_id=subject_id,
                text=(
                    f"{trajectory.duplicates} fixes shared a moment with another and were "
                    "collapsed."
                ),
            )
        )
    poor = int(np.sum(trajectory.accuracy_m > 100)) + int(np.sum(trajectory.satellites < 4))
    if poor:
        figures["poor_gnss"] = float(poor)
        warnings.append(
            Warning(
                code="poor_gnss",
                level="notice",
                subject_id=subject_id,
                text=(
                    f"{poor} fixes report a poor GNSS quality (accuracy above 100 m or fewer "
                    "than 4 satellites)."
                ),
            )
        )
    return warnings, figures
