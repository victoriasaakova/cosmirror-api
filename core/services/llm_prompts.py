"""
Системные промпты и модель для каждого из них.

Это не fallback: разные задачи ходят в разные модели.
Порядок выбора модели:
  1. явный аргумент `model=` в chat_json
  2. env / settings LLM_MODEL_<PROMPT>
  3. поле `model` в YAML-frontmatter файла промпта
  4. POLZA_MODEL / GROQ_MODEL — дефолт провайдера
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Optional

from django.conf import settings

PROMPT_ONBOARDING_INSIGHT = "onboarding_insight"
PROMPT_EDITORIAL = "editorial"
PROMPT_PAID_REPORT = "paid_report"
PROMPT_PAID_REPORT_NATAL = "paid_report_natal"
PROMPT_PAID_REPORT_ASPECTS = "paid_report_aspects"
PROMPT_PAID_REPORT_CYCLES = "paid_report_cycles"
PROMPT_PAID_REPORT_REQUEST = "paid_report_request"
PROMPT_PAID_REPORT_PRACTICE = "paid_report_practice"

_PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"
_FRONTMATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*(?:\n|$)", re.DOTALL)

# path=None — промпт живёт в коде (personalize.SYSTEM_PROMPT).
PROMPTS: dict[str, dict[str, Optional[str]]] = {
    PROMPT_ONBOARDING_INSIGHT: {
        "setting": "LLM_MODEL_ONBOARDING_INSIGHT",
        "path": None,
    },
    PROMPT_EDITORIAL: {
        "setting": "LLM_MODEL_EDITORIAL",
        "path": "cosmirror_editorial.md",
    },
    PROMPT_PAID_REPORT: {
        "setting": "LLM_MODEL_PAID_REPORT",
        "path": "paid_report.md",
    },
    PROMPT_PAID_REPORT_NATAL: {
        "setting": "LLM_MODEL_PAID_REPORT_NATAL",
        "path": "paid_report_natal.md",
    },
    PROMPT_PAID_REPORT_ASPECTS: {
        "setting": "LLM_MODEL_PAID_REPORT_ASPECTS",
        "path": "paid_report_aspects.md",
    },
    PROMPT_PAID_REPORT_CYCLES: {
        "setting": "LLM_MODEL_PAID_REPORT_CYCLES",
        "path": "paid_report_cycles.md",
    },
    PROMPT_PAID_REPORT_REQUEST: {
        "setting": "LLM_MODEL_PAID_REPORT_REQUEST",
        "path": "paid_report_request.md",
    },
    PROMPT_PAID_REPORT_PRACTICE: {
        "setting": "LLM_MODEL_PAID_REPORT_PRACTICE",
        "path": "paid_report_practice.md",
    },
}


class UnknownPromptError(ValueError):
    """prompt_id не зарегистрирован."""


@dataclass(frozen=True)
class PromptFile:
    meta: dict[str, str]
    body: str
    path: Path


def prompt_file_path(prompt_id: str) -> Optional[Path]:
    spec = PROMPTS.get(prompt_id)
    if not spec:
        raise UnknownPromptError(f"Unknown prompt_id: {prompt_id}")
    relative = spec.get("path")
    if not relative:
        return None
    return _PROMPTS_DIR / relative


def parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    match = _FRONTMATTER.match(text)
    if not match:
        return {}, text
    meta: dict[str, str] = {}
    for raw_line in match.group(1).splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        meta[key.strip()] = value.strip().strip("'").strip('"')
    return meta, text[match.end() :].lstrip("\n")


@lru_cache(maxsize=16)
def load_prompt_file(path: str) -> PromptFile:
    file_path = Path(path)
    text = file_path.read_text(encoding="utf-8")
    meta, body = parse_frontmatter(text)
    return PromptFile(meta=meta, body=body.strip() + "\n", path=file_path)


def load_prompt(prompt_id: str) -> PromptFile:
    path = prompt_file_path(prompt_id)
    if path is None:
        raise UnknownPromptError(f"Prompt {prompt_id} has no markdown file")
    if not path.exists():
        raise FileNotFoundError(f"Prompt file not found: {path}")
    return load_prompt_file(str(path))


def default_model() -> str:
    forced = (getattr(settings, "LLM_PROVIDER", "") or "auto").strip().lower()
    polza = (getattr(settings, "POLZA_MODEL", "") or "openai/gpt-5.6-luna-pro").strip()
    groq = (getattr(settings, "GROQ_MODEL", "") or "qwen/qwen3.6-27b").strip()
    polza_key = (getattr(settings, "POLZA_API_KEY", "") or "").strip()
    groq_key = (getattr(settings, "GROQ_API_KEY", "") or "").strip()

    if forced == "groq":
        return groq
    if forced == "polza":
        return polza
    if polza_key:
        return polza
    if groq_key:
        return groq
    return polza


def resolve_model(prompt_id: Optional[str] = None, *, model: Optional[str] = None) -> str:
    if model and model.strip():
        return model.strip()

    if prompt_id:
        spec = PROMPTS.get(prompt_id)
        if spec is None:
            raise UnknownPromptError(f"Unknown prompt_id: {prompt_id}")
        setting_name = spec.get("setting") or ""
        override = (getattr(settings, setting_name, "") or "").strip()
        if override:
            return override
        path = spec.get("path")
        if path:
            from_file = load_prompt(prompt_id).meta.get("model", "").strip()
            if from_file:
                return from_file

    return default_model()
