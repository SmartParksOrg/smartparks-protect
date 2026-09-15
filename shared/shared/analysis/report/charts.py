"""The charts of a result document drawn for paper: the same kinds the interface draws (a
line or bar over time or categories, a stacked bar, a rose of directions), in the brand
palette, as SVG so they stay crisp at any size."""

from __future__ import annotations

import io
from datetime import UTC, datetime
from typing import Any

import matplotlib

matplotlib.use("Agg")

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.figure import Figure

#: The frontend's `PALETTE` in `lib/chartStyle.ts`; the first entry is the brand green.
PALETTE = [
    "#52735E",
    "#D9825F",
    "#5C7FA3",
    "#B39A4A",
    "#8A6BA3",
    "#B86B5C",
    "#3E8E7E",
    "#8A7A4F",
    "#3E5A48",
    "#C48A9E",
]
TEXT = "#3F4A44"
GRID = "#DCE3DE"

plt.rcParams.update(
    {
        "font.family": "DejaVu Sans",
        "font.size": 7.5,
        "axes.edgecolor": GRID,
        "axes.labelcolor": TEXT,
        "xtick.color": TEXT,
        "ytick.color": TEXT,
        "text.color": TEXT,
        "axes.grid": True,
        "grid.color": GRID,
        "grid.linewidth": 0.5,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "svg.fonttype": "none",
    }
)


def _x_values(xs: list[Any]) -> tuple[list[Any], str]:
    """Numbers above 10^11 are epoch milliseconds, above 10^8 epoch seconds (a time axis);
    anything else is a category."""
    if xs and all(isinstance(x, int | float) for x in xs):
        first = float(xs[0])
        if first > 1e11:
            return [datetime.fromtimestamp(float(x) / 1000, tz=UTC) for x in xs], "time"
        if first > 1e8:
            return [datetime.fromtimestamp(float(x), tz=UTC) for x in xs], "time"
    return [str(x) for x in xs], "category"


def series_name(series: dict[str, Any], labels: dict[str, str]) -> str:
    if series.get("name"):
        return labels.get(series["name"], str(series["name"]))
    parts = [labels.get(series.get("subject", ""), series.get("subject"))]
    if series.get("herd"):
        parts.append(f"herd {series['herd']}")
    if series.get("period") == "comparison":
        parts.append("before")
    name = " · ".join(str(p) for p in parts if p)
    return name[:40] + "…" if len(name) > 41 else name


def chart_svg(
    chart: dict[str, Any],
    labels: dict[str, str],
    colors: dict[str, str],
    *,
    width_in: float = 3.4,
    height_in: float = 2.2,
) -> str:
    """One chart of the document as an SVG string; the caller sets the heading."""
    kind = chart.get("kind", "line")
    series: list[dict[str, Any]] = chart.get("series", [])
    fig = Figure(figsize=(width_in, height_in), dpi=100)
    if kind == "rose":
        _rose(fig, series, labels, colors)
    else:
        _cartesian(fig, kind, series, chart.get("unit"), labels, colors)
    buffer = io.StringIO()
    fig.savefig(buffer, format="svg", bbox_inches="tight", pad_inches=0.05)
    plt.close(fig)
    return buffer.getvalue()


def _color(series: dict[str, Any], index: int, colors: dict[str, str]) -> str:
    subject = series.get("subject")
    if subject and subject in colors:
        return colors[subject]
    return PALETTE[index % len(PALETTE)]


def _cartesian(
    fig: Figure,
    kind: str,
    series: list[dict[str, Any]],
    unit: str | None,
    labels: dict[str, str],
    colors: dict[str, str],
) -> None:
    ax = fig.add_subplot(111)
    ax.grid(axis="x", visible=False)
    if not series:
        ax.text(0.5, 0.5, "no data", ha="center", va="center", transform=ax.transAxes)
        ax.set_axis_off()
        return
    xs_raw = [d[0] for d in series[0].get("data", [])]
    xs, axis = _x_values(xs_raw)
    legend = len(series) > 1
    if kind == "line":
        for i, s in enumerate(series):
            data = s.get("data", [])
            x, _ = _x_values([d[0] for d in data])
            y = np.array([np.nan if d[1] is None else float(d[1]) for d in data])
            comparison = s.get("period") == "comparison"
            ax.plot(
                x,
                y,
                color=_color(s, i, colors),
                linewidth=1.2,
                linestyle="--" if comparison else "-",
                alpha=0.55 if comparison else 1.0,
                label=series_name(s, labels),
            )
            if len(series) == 1:
                ax.fill_between(x, 0, np.nan_to_num(y), color=_color(s, i, colors), alpha=0.1)
    else:
        n = len(series)
        positions = np.arange(len(xs))
        width = 0.8 / (1 if kind == "stacked" else n)
        bottom = np.zeros(len(xs))
        for i, s in enumerate(series):
            y = np.array(
                [0.0 if d[1] is None else float(d[1]) for d in s.get("data", [])],
                dtype=float,
            )
            if len(y) != len(xs):
                y = np.resize(y, len(xs))
            if kind == "stacked":
                ax.bar(
                    positions,
                    y,
                    width,
                    bottom=bottom,
                    color=_color(s, i, colors),
                    label=series_name(s, labels),
                )
                bottom += y
            else:
                ax.bar(
                    positions - 0.4 + width * (i + 0.5),
                    y,
                    width,
                    color=_color(s, i, colors),
                    alpha=0.55 if s.get("period") == "comparison" else 1.0,
                    label=series_name(s, labels),
                )
        ax.set_xticks(positions)
        if axis == "time":
            ax.set_xticklabels([x.strftime("%d %b") for x in xs], rotation=0)
        else:
            # a category may be a subject's id: its name then
            ax.set_xticklabels([labels.get(x, x) for x in xs])
        if len(xs) > 12:
            for i, tick in enumerate(ax.get_xticklabels()):
                tick.set_visible(i % max(1, len(xs) // 8) == 0)
        else:
            for tick in ax.get_xticklabels():
                tick.set_rotation(20)
                tick.set_horizontalalignment("right")
    if kind == "line" and axis == "time":
        locator = mdates.AutoDateLocator(minticks=3, maxticks=7)  # type: ignore[no-untyped-call]
        ax.xaxis.set_major_locator(locator)
        ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(locator))  # type: ignore[no-untyped-call]
    if unit:
        ax.set_ylabel(unit)
    ax.set_ylim(bottom=min(0.0, ax.get_ylim()[0]))
    if legend:
        # below the plot, so the lines stay clear
        ax.legend(
            loc="upper center",
            bbox_to_anchor=(0.5, -0.22 if axis == "category" else -0.18),
            fontsize=6.5,
            frameon=False,
            ncol=2,
        )


def _rose(
    fig: Figure,
    series: list[dict[str, Any]],
    labels: dict[str, str],
    colors: dict[str, str],
) -> None:
    ax: Any = fig.add_subplot(111, projection="polar")
    ax.set_theta_zero_location("N")
    ax.set_theta_direction(-1)
    ax.grid(color=GRID, linewidth=0.5)
    ax.set_yticklabels([])
    if not series:
        return
    categories = [str(d[0]) for d in series[0].get("data", [])]
    n = len(categories)
    if n == 0:
        return
    theta = np.linspace(0, 2 * np.pi, n, endpoint=False)
    width = 2 * np.pi / n
    for i, s in enumerate(series):
        values = np.array([0.0 if d[1] is None else float(d[1]) for d in s.get("data", [])])
        if len(values) != n:
            values = np.resize(values, n)
        ax.bar(
            theta,
            values,
            width=width * 0.9,
            bottom=0,
            color=_color(s, i, colors),
            alpha=0.5 if s.get("period") == "comparison" else 0.85,
            label=series_name(s, labels),
        )
    ax.set_xticks(theta)
    ax.set_xticklabels(categories, fontsize=6)
    if len(series) > 1:
        ax.legend(loc="upper right", bbox_to_anchor=(1.3, 1.1), fontsize=6.5, frameon=False)
