"""
prompt_registry.py
==================
Loads prompt variant files from data/prompts/.
Used by eval_prompts.py to test prompt variants without changing production code.

USAGE:
    from src.prompt_registry import PromptVariant, load_variant
    variant = load_variant("A1C1")
    # variant.prompt_text — the full prompt template (with {placeholders})
    # variant.self_check_mode — "separate" | "embedded" | "none"
"""

import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

PROMPTS_DIR = Path(__file__).resolve().parents[1] / "data" / "prompts"

# Valid self_check_mode values and their meaning:
#   "separate"  — call _self_check() after main response (current production behaviour)
#   "embedded"  — single LLM call with self-verification inside the prompt
#   "none"      — skip self-check entirely, return parsed directly

@dataclass
class PromptVariant:
    variant_id:      str   # e.g. "A1C1"
    dimension_a:     str   # "decision_table" | "chain_of_thought" | "few_shot"
    dimension_c:     str   # "separate" | "embedded" | "none"
    self_check_mode: str   # same as dimension_c — kept for clarity
    prompt_text:     str   # full prompt template with {placeholders}
    description:     str   # human-readable variant description


# Cache loaded variants — production path calls load_variant("A1C1") on every
# explain_risk(); caching avoids a disk read per Groq call.
_variant_cache: dict[str, PromptVariant] = {}

_VARIANT_META = {
    "A1C1": {
        "dimension_a": "decision_table",
        "dimension_c": "separate",
        "self_check_mode": "separate",
        "description": "Baseline: decision table + separate self-check (current production)",
    },
    "A2C1": {
        "dimension_a": "chain_of_thought",
        "dimension_c": "separate",
        "self_check_mode": "separate",
        "description": "Chain-of-thought reasoning + separate self-check",
    },
    "A3C1": {
        "dimension_a": "few_shot",
        "dimension_c": "separate",
        "self_check_mode": "separate",
        "description": "Few-shot examples only (no explicit rules) + separate self-check",
    },
    "A1C2": {
        "dimension_a": "decision_table",
        "dimension_c": "embedded",
        "self_check_mode": "embedded",
        "description": "Decision table + embedded self-verification (single API call)",
    },
    "A1C3": {
        "dimension_a": "decision_table",
        "dimension_c": "none",
        "self_check_mode": "none",
        "description": "Decision table + no self-check (baseline cost measurement)",
    },
}


def load_variant(variant_id: str) -> PromptVariant:
    """
    Load a prompt variant by ID. Reads prompt text from data/prompts/explain_{variant_id}.txt.
    Results are cached — production path (A1C1) avoids disk read on every explain_risk call.
    Raises FileNotFoundError if prompt file not found.
    Raises ValueError if variant_id not in registry.
    """
    if variant_id in _variant_cache:
        return _variant_cache[variant_id]

    if variant_id not in _VARIANT_META:
        raise ValueError(
            f"Unknown variant '{variant_id}'. "
            f"Valid: {list(_VARIANT_META.keys())}"
        )

    prompt_path = PROMPTS_DIR / f"explain_{variant_id}.txt"
    if not prompt_path.exists():
        raise FileNotFoundError(
            f"Prompt file not found: {prompt_path}. "
            f"Run Step A.2 to create prompt files."
        )

    prompt_text = prompt_path.read_text(encoding="utf-8")
    meta = _VARIANT_META[variant_id]
    variant = PromptVariant(
        variant_id=variant_id,
        prompt_text=prompt_text,
        **meta,
    )
    _variant_cache[variant_id] = variant
    return variant


def list_variants() -> list[str]:
    """Return all registered variant IDs."""
    return list(_VARIANT_META.keys())
