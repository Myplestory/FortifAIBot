from __future__ import annotations

import copy
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

EMBED_TOTAL_LIMIT = 6000
MESSAGE_EMBED_LIMIT = 6000
MESSAGE_EMBED_COUNT = 10
EMBED_PACK_MARGIN = 256

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


_CONTINUATION_FIELD_NAME = "​"


def _chunk_field(name: str, body: str, *, limit: int = 1024) -> list[tuple[str, str, bool]]:
    """Discord caps each embed field value at 1024 chars. Split on newline
    boundaries first; when a single line itself exceeds `limit`, hard-split at
    word boundaries (or character boundaries as a last resort) so the cap is
    always respected. Without the hard-split fallback, an unwrapped paragraph
    from an LLM response would overflow and Discord rejects the whole payload.

    The first chunk carries the section name; continuations use a zero-width
    space so the body reads as one stitched block under a single heading
    instead of `Name (1)`, `Name (2)`, ...
    """
    if not body:
        return [(name, "—", False)]
    if len(body) <= limit:
        return [(name, body, False)]

    out: list[tuple[str, str, bool]] = []
    chunk_lines: list[str] = []
    chunk_size = 0

    def _flush() -> None:
        nonlocal chunk_lines, chunk_size
        if chunk_lines:
            field_name = name if not out else _CONTINUATION_FIELD_NAME
            out.append((field_name, "\n".join(chunk_lines), False))
            chunk_lines = []
            chunk_size = 0

    def _split_oversized_line(line: str) -> Iterable[str]:
        """Yield substrings of `line` each ≤ limit, preferring whitespace breaks."""
        while len(line) > limit:
            cut = line.rfind(" ", 0, limit)
            if cut <= 0:
                cut = limit  # no whitespace — hard char split
            yield line[:cut]
            line = line[cut:].lstrip()
        if line:
            yield line

    for raw_line in body.split("\n"):
        for line in _split_oversized_line(raw_line):
            line_len = len(line) + 1  # +1 for the newline join
            if chunk_size + line_len > limit and chunk_lines:
                _flush()
            chunk_lines.append(line)
            chunk_size += line_len

    _flush()
    return out


def _split_oversized_embed(embed: discord.Embed) -> list[discord.Embed]:
    """Redistribute fields across continuation embeds when a single embed
    exceeds Discord's 6000-char per-embed cap. Author/icon/color/footer are
    preserved on every continuation; the first keeps the original title and
    description, continuations get a `(cont.)` suffix and blank description so
    they don't double-count toward the cap.
    """
    if len(embed) <= EMBED_TOTAL_LIMIT:
        return [embed]

    fields = list(embed.fields)
    if not fields:
        # Nothing to redistribute — title/description/footer alone exceed 6000.
        # Caller's content is malformed; return as-is and let Discord reject so
        # the bug surfaces.
        log.warning("embed exceeds %d chars with no fields to redistribute", EMBED_TOTAL_LIMIT)
        return [embed]

    cap = EMBED_TOTAL_LIMIT - EMBED_PACK_MARGIN

    # `Embed.copy()` and `Embed.from_dict(Embed.to_dict())` are both shallow on
    # `_fields` in discord.py 2.7 — they alias the original list. We need true
    # independence between continuation embeds, so use `copy.deepcopy`.
    base = copy.deepcopy(embed)
    base.clear_fields()
    base_len = len(base)

    original_title = embed.title or ""
    cont_title = f"{original_title} (cont.)" if original_title else "(cont.)"

    def _new_continuation() -> discord.Embed:
        c = copy.deepcopy(base)
        c.title = cont_title
        c.description = None
        return c

    out: list[discord.Embed] = []
    cur = copy.deepcopy(base)
    cur_len = base_len

    for f in fields:
        flen = len(f.name) + len(f.value)
        if flen > cap - base_len:
            log.warning(
                "embed field %r at %d chars cannot fit in a continuation; "
                "appending and letting Discord enforce",
                f.name,
                flen,
            )
        if cur.fields and cur_len + flen > cap:
            out.append(cur)
            cur = _new_continuation()
            cur_len = len(cur)
        cur.add_field(name=f.name, value=f.value, inline=f.inline)
        cur_len += flen

    out.append(cur)
    return out


def _attachment_name(url: str | None) -> str | None:
    if not url or not url.startswith("attachment://"):
        return None
    name = url[len("attachment://"):]
    return name or None


def split_embeds_for_messages(embeds: list[discord.Embed]) -> list[list[discord.Embed]]:
    """Group embeds so each outgoing message respects Discord's caps:
    ≤ 6000 chars summed across embeds in the message and ≤ 10 embeds.
    Oversized embeds are first split via `_split_oversized_embed`.
    """
    flat: list[discord.Embed] = []
    for e in embeds:
        flat.extend(_split_oversized_embed(e))

    groups: list[list[discord.Embed]] = []
    cur: list[discord.Embed] = []
    cur_size = 0
    for e in flat:
        size = len(e)
        if cur and (cur_size + size > MESSAGE_EMBED_LIMIT or len(cur) >= MESSAGE_EMBED_COUNT):
            groups.append(cur)
            cur = []
            cur_size = 0
        cur.append(e)
        cur_size += size
    if cur:
        groups.append(cur)
    return groups


def rebuild_files_for_embeds(embeds: list[discord.Embed]) -> list[discord.File]:
    """Open fresh `discord.File` objects for every `attachment://NAME.png`
    referenced by the given embeds (author icon, thumbnail, image). Dedupes by
    filename — Discord matches attachments to embeds by filename within a
    message, so one file satisfies many embeds. Unresolvable references are
    skipped with a warning rather than raising.
    """
    seen: set[str] = set()
    out: list[discord.File] = []
    for e in embeds:
        candidates: list[str | None] = [
            e.author.icon_url,
            e.thumbnail.url,
            e.image.url,
        ]
        for url in candidates:
            name = _attachment_name(url)
            if not name or name in seen:
                continue
            seen.add(name)
            stem = name[:-4] if name.endswith(".png") else name
            f, _ = _attach_icon(stem)
            if f is not None:
                out.append(f)
            else:
                log.warning("could not resolve attachment %s for re-send", name)
    return out


def finalize_footer(
    groups: list[list[discord.Embed]],
    *,
    footer_text: str = DEFAULT_FOOTER,
) -> None:
    """Clear footers across every embed in every group, then set `footer_text`
    on the very last embed of the last group. Mirrors the single-message
    convention of attaching the footer once for visual termination.
    """
    if not groups:
        return
    for group in groups:
        for e in group:
            e.remove_footer()
    last_group = groups[-1]
    if last_group:
        last_group[-1].set_footer(text=footer_text)
