from __future__ import annotations

import functools
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


def _extract_first_json_object(text: str) -> str:
    """Return the first balanced top-level JSON object found in `text`,
    tolerant of leading markdown fences, prelude prose, and trailing
    commentary that would otherwise break `json.loads`. Tracks string state
    so braces inside string literals aren't counted.
    """
    s = _strip_json_fences(text)
    depth = 0
    start = -1
    in_string = False
    escape = False
    for i, c in enumerate(s):
        if escape:
            escape = False
            continue
        if in_string:
            if c == "\\":
                escape = True
            elif c == '"':
                in_string = False
            continue
        if c == '"':
            in_string = True
            continue
        if c == "{":
            if depth == 0:
                start = i
            depth += 1
        elif c == "}":
            if depth == 0:
                continue
            depth -= 1
            if depth == 0 and start >= 0:
                return s[start : i + 1]
    raise ValueError("no balanced JSON object found in LLM output")
