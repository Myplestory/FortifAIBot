"""Public facade for the embed-builder layer. Implementations live in
`content/`, segmented by surface: shared primitives, quiz flow, session
rollup, stats, analyze. This module re-exports the names callers depend on
so the import path stays stable.
"""

from __future__ import annotations

from content.quiz import (
    question_embed,
    refinement_embed,
    run_complete_embeds,
    skip_embed,
)
from content.session import session_rollup_embed
from content.shared import (
    ALERT_RED,
    BG_DARK_HEX,
    BLUE_PRIMARY,
    COUNTDOWN_FIELD_NAME,
    DEFAULT_FOOTER,
    FG_MUTED_HEX,
    FG_TEXT_HEX,
    ICON_DIR,
    ICON_NAMES,
    OK_GREEN,
    ROOT,
    WARN_AMBER,
    build,
    confirm_embed,
    error_embed,
    format_remaining,
    info_embed,
)


__all__ = [
    "ALERT_RED",
    "BG_DARK_HEX",
    "BLUE_PRIMARY",
    "COUNTDOWN_FIELD_NAME",
    "DEFAULT_FOOTER",
    "FG_MUTED_HEX",
    "FG_TEXT_HEX",
    "ICON_DIR",
    "ICON_NAMES",
    "OK_GREEN",
    "ROOT",
    "WARN_AMBER",
    "build",
    "confirm_embed",
    "error_embed",
    "format_remaining",
    "info_embed",
    "question_embed",
    "refinement_embed",
    "run_complete_embeds",
    "session_rollup_embed",
    "skip_embed",
]
