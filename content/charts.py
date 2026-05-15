from __future__ import annotations

import logging
import tempfile
from collections import Counter
from datetime import datetime
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt

from content.shared import BG_DARK_HEX, FG_MUTED_HEX, FG_TEXT_HEX


log = logging.getLogger(__name__)

BLUE_HEX = "#7289DA"
GREEN_HEX = "#43B581"
RED_HEX = "#F04747"


def apply_style() -> None:
    plt.rcParams.update(
        {
            "axes.facecolor": BG_DARK_HEX,
            "figure.facecolor": BG_DARK_HEX,
            "savefig.facecolor": BG_DARK_HEX,
            "text.color": FG_TEXT_HEX,
            "axes.labelcolor": FG_TEXT_HEX,
            "xtick.color": FG_TEXT_HEX,
            "ytick.color": FG_TEXT_HEX,
            "axes.edgecolor": FG_MUTED_HEX,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.titlecolor": FG_TEXT_HEX,
            "font.family": "DejaVu Sans",
            "font.size": 10,
            "figure.dpi": 110,
            "axes.grid": True,
            "grid.color": FG_MUTED_HEX,
            "grid.alpha": 0.25,
            "grid.linewidth": 0.5,
        }
    )


apply_style()


def _save_temp(fig) -> Path:
    fd, path = tempfile.mkstemp(prefix="fortifai-chart-", suffix=".png")
    import os

    os.close(fd)
    fig.savefig(path, bbox_inches="tight", facecolor=BG_DARK_HEX)
    plt.close(fig)
    return Path(path)


def empty_state(title: str, message: str) -> Path:
    fig, ax = plt.subplots(figsize=(6, 2.5))
    ax.set_axis_off()
    ax.text(
        0.5,
        0.5,
        message,
        ha="center",
        va="center",
        color=FG_MUTED_HEX,
        fontsize=11,
        wrap=True,
    )
    ax.set_title(title, color=FG_TEXT_HEX)
    return _save_temp(fig)


def runs_over_time(timestamps: list[str], granularity: str = "day", title: str = "Runs over time") -> Path:
    if not timestamps:
        return empty_state(title, "No runs recorded yet.")
    fmt_short = "%Y-%m-%d" if granularity == "day" else "%Y-W%W"
    buckets: Counter[str] = Counter()
    for ts in timestamps:
        try:
            dt = datetime.fromisoformat(ts)
        except ValueError:
            continue
        buckets[dt.strftime(fmt_short)] += 1
    if not buckets:
        return empty_state(title, "No parseable run timestamps.")
    keys = sorted(buckets.keys())
    values = [buckets[k] for k in keys]
    fig, ax = plt.subplots(figsize=(7, 3.2))
    ax.plot(keys, values, color=BLUE_HEX, linewidth=2, marker="o", markersize=4)
    ax.set_title(title)
    ax.set_ylabel("Runs")
    ax.tick_params(axis="x", rotation=30)
    fig.tight_layout()
    return _save_temp(fig)


def field_distribution(field_counts: dict[str, int], title: str = "Runs by field") -> Path:
    if not field_counts:
        return empty_state(title, "No field activity yet.")
    items = sorted(field_counts.items(), key=lambda kv: kv[1], reverse=True)
    labels = [k for k, _ in items]
    values = [v for _, v in items]
    fig, ax = plt.subplots(figsize=(7, max(2.5, 0.45 * len(labels) + 1.0)))
    ax.barh(labels, values, color=BLUE_HEX, alpha=0.85)
    ax.invert_yaxis()
    ax.set_title(title)
    ax.set_xlabel("Question count")
    fig.tight_layout()
    return _save_temp(fig)


def score_progression(
    pre_scores: list[float | None],
    post_scores: list[float | None],
    title: str = "Score progression",
) -> Path:
    """Two-line trajectory of per-run aggregated_score_pre and aggregated_score_post.
    Lists are indexed by run order (oldest → newest); None entries become NaN so
    matplotlib renders a gap (typical for legacy runs that only stored a
    post-refinement score under aggregated_score).
    """
    if not pre_scores and not post_scores:
        return empty_state(title, "No graded runs.")
    n = max(len(pre_scores), len(post_scores))
    xs = list(range(1, n + 1))
    pre_y = [s if s is not None else float("nan") for s in pre_scores]
    post_y = [s if s is not None else float("nan") for s in post_scores]
    fig, ax = plt.subplots(figsize=(7, 3.4))
    ax.plot(xs, pre_y, color=BLUE_HEX, linewidth=2, marker="o", markersize=5, label="Unassisted (pre)")
    ax.plot(
        xs,
        post_y,
        color=GREEN_HEX,
        linewidth=1.6,
        marker="s",
        markersize=4,
        alpha=0.85,
        label="With refinement (post)",
    )
    ax.set_title(title)
    ax.set_xlabel("Run")
    ax.set_ylabel("Aggregated score")
    ax.set_xticks(xs)
    ax.set_ylim(0.5, 5.5)
    ax.legend(
        loc="best",
        facecolor=BG_DARK_HEX,
        edgecolor=FG_MUTED_HEX,
        labelcolor=FG_TEXT_HEX,
    )
    fig.tight_layout()
    return _save_temp(fig)


def delta_diverging(deltas: dict[str, float], title: str = "Field deltas") -> Path:
    if not deltas:
        return empty_state(title, "No deltas to display.")
    items = sorted(deltas.items(), key=lambda kv: kv[1])
    labels = [k for k, _ in items]
    values = [v for _, v in items]
    colors = [GREEN_HEX if v > 0 else (RED_HEX if v < 0 else FG_MUTED_HEX) for v in values]
    fig, ax = plt.subplots(figsize=(7, max(2.5, 0.4 * len(labels) + 1.0)))
    ax.barh(labels, values, color=colors)
    ax.axvline(0, color=FG_MUTED_HEX, linewidth=0.8)
    ax.invert_yaxis()
    ax.set_title(title)
    fig.tight_layout()
    return _save_temp(fig)
