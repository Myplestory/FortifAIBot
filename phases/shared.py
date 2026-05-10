from __future__ import annotations

import functools
import json
import re
from pathlib import Path


ROOT = Path(__file__).parent.parent
TEMPLATES_ROOT = ROOT / "templates"
DEFAULT_INDUSTRY = "swe"
SCORE_GRADER_SEPARATOR = "\n\n---\n\n"


@functools.lru_cache(maxsize=32)
def _load_template(industry: str, name: str) -> str:
    p = TEMPLATES_ROOT / industry / f"{name}.md"
    if not p.exists() or p.stat().st_size == 0:
        raise RuntimeError(
            f"Template {p} is missing or empty. Add it before running this industry."
        )
    return p.read_text()


@functools.lru_cache(maxsize=8)
def _load_root_template(name: str) -> str:
    """Load a cross-domain template (e.g. dreyfus.md) from `templates/<name>.md`.
    Used for skill-acquisition foundations that apply across all industries
    and get stitched on top of every domain-specific score template.
    """
    p = TEMPLATES_ROOT / f"{name}.md"
    if not p.exists() or p.stat().st_size == 0:
        raise RuntimeError(
            f"Cross-domain template {p} is missing or empty."
        )
    return p.read_text()


def list_industries() -> list[str]:
    if not TEMPLATES_ROOT.exists():
        return []
    out: list[str] = []
    for p in sorted(TEMPLATES_ROOT.iterdir()):
        if p.is_dir() and (p / "generation.md").exists() and (p / "refine.md").exists():
            out.append(p.name)
    return out


def _strip_json_fences(text: str) -> str:
    s = text.strip()
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z]*\n", "", s)
        if s.endswith("```"):
            s = s[: -len("```")].rstrip()
    return s


_JSON_DECODER = json.JSONDecoder()


def _extract_first_json_object(text: str) -> str:
    """Return the first balanced top-level JSON object found in `text`,
    tolerant of leading markdown fences, prelude prose, and trailing commentary
    that would otherwise break `json.loads`. Uses the stdlib `JSONDecoder.raw_decode`
    to delegate brace/string/escape tracking to the real JSON grammar — replaces a
    hand-rolled state machine. We scan for `{` candidates and try `raw_decode` at
    each; the first one that parses to a balanced object wins. A stray `{` inside
    prose (e.g. "the result was something like {1, 2, 3}") raises JSONDecodeError
    and the scan continues to the next candidate.
    """
    s = _strip_json_fences(text)
    for i, c in enumerate(s):
        if c != "{":
            continue
        try:
            _, end = _JSON_DECODER.raw_decode(s, i)
        except json.JSONDecodeError:
            continue
        return s[i:end]
    raise ValueError("no balanced JSON object found in LLM output")
