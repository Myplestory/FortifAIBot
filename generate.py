"""Public facade for the LLM phases. Implementations live in `phases/`,
segmented by phase: generation (Phase 0), refinement (Phase 2), grading
(Phase 4). This module re-exports the names callers depend on so the
import path stays stable.
"""

from __future__ import annotations

from phases.generation import (
    GenerationError,
    build_generation_system,
    generate,
)
from phases.grading import (
    GradingError,
    build_question_grader_system,
    build_stitch_grader_system,
    grade,
)
from phases.movement import (
    build_comparison_points,
    build_entry_state,
)
from phases.refinement import (
    RefinementError,
    _deterministic_fallback,
    refine,
)
from phases.shared import DEFAULT_INDUSTRY, list_industries


__all__ = [
    "DEFAULT_INDUSTRY",
    "GenerationError",
    "GradingError",
    "RefinementError",
    "_deterministic_fallback",
    "build_comparison_points",
    "build_entry_state",
    "build_generation_system",
    "build_question_grader_system",
    "build_stitch_grader_system",
    "generate",
    "grade",
    "list_industries",
    "refine",
]
