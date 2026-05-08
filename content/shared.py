from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Iterable

import discord


log = logging.getLogger(__name__)

ROOT = Path(__file__).parent.parent
ICON_DIR = ROOT / "assets" / "icons"

def _color(hex_str: str) -> int:
    """Convert a `#RRGGBB` CSS-style hex string into the packed 24-bit int
    that discord.py's Embed/Colour APIs require.
    """
    return int(hex_str.lstrip("#"), 16)


BLUE_PRIMARY = _color("#7289DA")
OK_GREEN = _color("#43B581")
WARN_AMBER = _color("#FAA61A")
ALERT_RED = _color("#F04747")

BG_DARK_HEX = "#1E1F22"
FG_TEXT_HEX = "#DCDDDE"
FG_MUTED_HEX = "#72767D"

DEFAULT_FOOTER = "FortifAI · Knowledge Hardening"

ICON_NAMES = {
    # Quiz flow — each embed now has a distinct icon.
    "knowledgeharden": "target",
    "question": "circle-question-mark",
    "refinement": "microscope",
    "skip": "square",
    "grading": "graduation-cap",
    "results": "trophy",
    "results_deferred": "triangle-alert",
    "literature": "book-marked",
    "timer": "timer",
    "exercises": "wrench",
    # Session lifecycle.
    "sessionbegin": "play",
    "sessionend": "square",
    # Stats & analyze.
    "stats": "chart-column",
    "stats_timeline": "clock",
    "analyze": "trending-up",
    "analyze_bias": "scale",
    "analyze_gaps": "search-x",
    # Reference / navigation.
    "help": "circle-question-mark",
    "rubric": "book-open",
    "directory": "folder-tree",
    "schedule": "calendar-clock",
    # Housekeeping.
    "sweep": "trash-2",
    "regrade": "recycle",
    "retry": "list-restart",
    "error": "triangle-alert",
    "ok": "circle-check",
    # Multi-session.
    "sessionlist": "list",
    "sessionswitch": "arrow-right-left",
    "session_tag": "tag",
}

COUNTDOWN_FIELD_NAME = "Time remaining"


def format_remaining(seconds: int) -> str:
    seconds = max(0, int(seconds))
    mins, secs = divmod(seconds, 60)
    if mins >= 60:
        h, m = divmod(mins, 60)
        return f"{h}h {m:02d}m"
    return f"{mins}m {secs:02d}s"


def _icon_path(name: str) -> Path:
    return ICON_DIR / f"{name}.png"


def _attach_icon(name: str | None) -> tuple[discord.File | None, str | None]:
    if not name:
        return None, None
    p = _icon_path(name)
    if not p.exists():
        log.warning("icon %s missing at %s; rendering without it", name, p)
        return None, None
    return discord.File(str(p), filename=f"{name}.png"), f"attachment://{name}.png"


def build(
    *,
    title: str,
    description: str | None = None,
    fields: Iterable[tuple[str, str, bool]] | None = None,
    icon: str | None = None,
    color: int = BLUE_PRIMARY,
    footer: str | None = DEFAULT_FOOTER,
    chart: Path | None = None,
    thumbnail: Path | None = None,
    author: str | None = None,
) -> tuple[discord.Embed, list[discord.File]]:
    embed = discord.Embed(title=title, description=description or None, color=color)

    files: list[discord.File] = []

    icon_file, icon_url = _attach_icon(icon)
    if icon_file:
        files.append(icon_file)
    if author or icon_url:
        embed.set_author(name=author or title, icon_url=icon_url) if icon_url else embed.set_author(name=author or title)

    if thumbnail and thumbnail.exists():
        thumb_file = discord.File(str(thumbnail), filename=thumbnail.name)
        files.append(thumb_file)
        embed.set_thumbnail(url=f"attachment://{thumbnail.name}")

    if chart and chart.exists():
        chart_file = discord.File(str(chart), filename="chart.png")
        files.append(chart_file)
        embed.set_image(url="attachment://chart.png")

    for name, value, inline in fields or []:
        embed.add_field(name=name, value=value, inline=inline)

    if footer:
        embed.set_footer(text=footer)

    return embed, files


def error_embed(message: str, *, icon: str | None = None) -> tuple[discord.Embed, list[discord.File]]:
    return build(
        title="Unable to proceed",
        description=message,
        icon=icon,
        color=ALERT_RED,
    )


def info_embed(title: str, description: str, *, icon: str | None = None) -> tuple[discord.Embed, list[discord.File]]:
    return build(title=title, description=description, icon=icon)


def confirm_embed(action: str, detail: str, *, icon: str | None = None) -> tuple[discord.Embed, list[discord.File]]:
    return build(
        title=f"Confirm: {action}",
        description=detail,
        icon=icon,
        color=WARN_AMBER,
    )


def _format_lit_entry(e: dict[str, Any]) -> str:
    title = e.get("title", "?")
    url = e.get("url") or ""
    titled = f"[{title}]({url})" if url else f"**{title}**"
    why = e.get("why", "")
    section = e.get("section", "")
    rt = e.get("reading_time_estimate", "")
    parts = [f"{titled} — {why}"]
    if section:
        parts.append(f"  ↳ {section}")
    if rt:
        parts.append(f"  ⏱ {rt}")
    return "\n".join(parts)


def _chunk_field(name: str, body: str, *, limit: int = 1024) -> list[tuple[str, str, bool]]:
    """Discord caps each embed field value at 1024 chars. Split on newline boundaries."""
    if len(body) <= limit:
        return [(name, body or "—", False)]
    out: list[tuple[str, str, bool]] = []
    chunk: list[str] = []
    size = 0
    idx = 1
    for line in body.split("\n"):
        line_len = len(line) + 1
        if size + line_len > limit and chunk:
            out.append((f"{name} ({idx})", "\n".join(chunk), False))
            idx += 1
            chunk, size = [], 0
        chunk.append(line)
        size += line_len
    if chunk:
        out.append((f"{name} ({idx})", "\n".join(chunk), False))
    return out
