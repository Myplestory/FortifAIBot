from __future__ import annotations

import functools
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


_ROOT = Path(__file__).parent.parent
_YAML_PATH = _ROOT / "templates" / "band_mappings.yaml"

_BAND_ORDER = ("B1", "B2", "B3", "B4", "B5")


@dataclass(frozen=True)
class SfiaFacets:
    level: str
    label: str
    autonomy: str
    complexity: str
    influence: str
    knowledge: str
    business_skills: str


@dataclass(frozen=True)
class DreyfusStage:
    stage: str
    verbatim: str


@dataclass(frozen=True)
class SwecomLevel:
    level: str
    title: str
    verbatim: str


@dataclass(frozen=True)
class BandRow:
    band: str
    label: str
    yoe_range: str
    dreyfus: DreyfusStage
    swecom: SwecomLevel
    sfia: SfiaFacets
    industry_ladder: str
    blurb: str
    score_keyword_anchor: str


@dataclass(frozen=True)
class ScoreThreshold:
    min: float
    keyword: str
    stage: str


@dataclass(frozen=True)
class CriticalFailureConfig:
    fail_score_threshold: int
    suppress_keyword_at: int


@dataclass(frozen=True)
class BandMappings:
    version: int
    authority: str
    bands: dict[str, BandRow]
    score_thresholds: tuple[ScoreThreshold, ...]
    critical_failure: CriticalFailureConfig


def _coerce_band(band_id: str, raw: dict[str, Any]) -> BandRow:
    dreyfus_raw = raw["dreyfus"]
    swecom_raw = raw["swecom"]
    sfia_raw = raw["sfia"]
    return BandRow(
        band=band_id,
        label=raw["label"],
        yoe_range=raw["yoe_range"],
        dreyfus=DreyfusStage(stage=dreyfus_raw["stage"], verbatim=dreyfus_raw["verbatim"]),
        swecom=SwecomLevel(
            level=swecom_raw["level"],
            title=swecom_raw["title"],
            verbatim=swecom_raw["verbatim"],
        ),
        sfia=SfiaFacets(
            level=sfia_raw["level"],
            label=sfia_raw["label"],
            autonomy=sfia_raw["autonomy"],
            complexity=sfia_raw["complexity"],
            influence=sfia_raw["influence"],
            knowledge=sfia_raw["knowledge"],
            business_skills=sfia_raw["business_skills"],
        ),
        industry_ladder=raw["industry_ladder"],
        blurb=raw["blurb"],
        score_keyword_anchor=raw["score_keyword_anchor"],
    )


@functools.lru_cache(maxsize=1)
def load_band_mappings() -> BandMappings:
    if not _YAML_PATH.exists() or _YAML_PATH.stat().st_size == 0:
        raise RuntimeError(f"band mappings YAML missing or empty: {_YAML_PATH}")
    raw = yaml.safe_load(_YAML_PATH.read_text())
    if not isinstance(raw, dict):
        raise RuntimeError(f"band mappings YAML must be a mapping, got {type(raw).__name__}")
    bands_raw = raw.get("bands") or {}
    missing = [b for b in _BAND_ORDER if b not in bands_raw]
    if missing:
        raise RuntimeError(f"band mappings missing entries: {missing}")
    bands = {b: _coerce_band(b, bands_raw[b]) for b in _BAND_ORDER}

    thr_raw = raw.get("score_thresholds") or []
    thresholds = tuple(
        ScoreThreshold(min=float(t["min"]), keyword=t["keyword"], stage=t["stage"])
        for t in thr_raw
    )
    if not thresholds:
        raise RuntimeError("band mappings missing score_thresholds")
    # Highest-min-first ordering is required by score_to_keyword's first-match logic.
    if list(thresholds) != sorted(thresholds, key=lambda t: -t.min):
        raise RuntimeError("score_thresholds must be ordered highest min first")

    cf_raw = raw.get("critical_failure") or {}
    if "fail_score_threshold" not in cf_raw or "suppress_keyword_at" not in cf_raw:
        raise RuntimeError("band mappings missing critical_failure config")
    cf = CriticalFailureConfig(
        fail_score_threshold=int(cf_raw["fail_score_threshold"]),
        suppress_keyword_at=int(cf_raw["suppress_keyword_at"]),
    )

    return BandMappings(
        version=int(raw.get("version", 1)),
        authority=str(raw.get("authority", "")),
        bands=bands,
        score_thresholds=thresholds,
        critical_failure=cf,
    )


def get_band(band: str) -> BandRow:
    return load_band_mappings().bands[band]


def score_to_keyword(score: float) -> tuple[str, str]:
    """Returns (career_level keyword, Dreyfus stage label).

    Uses the YAML's score_thresholds (highest-min-first). Behaviour-preserving
    vs. the pre-remediation commands/bands.py:_score_to_keyword: thresholds
    >=4.5 expert, >=3.5 proficient, >=2.5 competent, >=1.5 developing, else entry.
    """
    for t in load_band_mappings().score_thresholds:
        if score >= t.min:
            return t.keyword, t.stage
    # Defensive: should not be reachable because YAML enforces a 0.0 floor.
    return "entry", "Novice"


def critical_failure_config() -> CriticalFailureConfig:
    return load_band_mappings().critical_failure


def render_band_table_md() -> str:
    """Render the verbatim-band table that's stitched into templates/swe/grader.md.
    Replaces the literal table at grader.md:9-15.
    """
    m = load_band_mappings()
    lines = [
        "| Band | Label | YOE | Dreyfus | SWECOM | SFIA |",
        "|---|---|---|---|---|---|",
    ]
    for b in _BAND_ORDER:
        row = m.bands[b]
        dreyfus_cell = f'{row.dreyfus.stage}: "{row.dreyfus.verbatim}"'
        swecom_cell = f'{row.swecom.level} {row.swecom.title}: "{row.swecom.verbatim}"'
        sfia_cell = (
            f"{row.sfia.level} ({row.sfia.label}): "
            f'"{row.sfia.autonomy}"'
        )
        lines.append(
            f"| {row.band} | {row.label} | {row.yoe_range} | {dreyfus_cell} "
            f"| {swecom_cell} | {sfia_cell} |"
        )
    return "\n".join(lines)


def render_sfia_facets_md() -> str:
    """Render the 7-column SFIA all-facets table that replaces templates/swe/score.md:53-58.
    Adds Influence, Knowledge, and Business skills columns the prior 4-column
    table omitted (Finding D).
    """
    m = load_band_mappings()
    lines = [
        "| SFIA Level | Autonomy | Complexity | Influence | Knowledge | Business skills | Band |",
        "|---|---|---|---|---|---|---|",
    ]
    for b in _BAND_ORDER:
        row = m.bands[b]
        lines.append(
            f"| {row.sfia.level} ({row.sfia.label}) "
            f"| \"{row.sfia.autonomy}\" "
            f"| \"{row.sfia.complexity}\" "
            f"| \"{row.sfia.influence}\" "
            f"| \"{row.sfia.knowledge}\" "
            f"| \"{row.sfia.business_skills}\" "
            f"| {row.band} ({row.label}) |"
        )
    return "\n".join(lines)
