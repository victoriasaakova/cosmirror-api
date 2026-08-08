"""
Редакционный второй проход для всех LLM-текстов, видимых пользователю.

После генерации черновика тексты проходят через Cosmirror Editorial Writing System
(core/prompts/cosmirror_editorial.md) и только потом отдаются на фронт / в продукт.
"""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

from core.services import llm_client

logger = logging.getLogger(__name__)

_PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"
_EDITORIAL_PATH = _PROMPTS_DIR / "cosmirror_editorial.md"

# Поля инсайта, которые видит пользователь и которые должен править редактор.
USER_FACING_INSIGHT_KEYS = (
    "opening",
    "body",
    "influences",
    "cycles",
    "product_pitch",
    "outcomes",
    "offer",
)

EDIT_TASK = """\
Ты — штатный редактор Cosmirror. Ниже — EDITORIAL & WRITING SYSTEM.
Тебе дан черновик JSON с текстами для пользователя. Перепиши пользовательские тексты
строго по системе: динамика вместо описания, паттерн/функция/цена где уместно,
астрология как факт + интерпретация, без прогнозов, диагнозов и self-help клише.

Жёсткие ограничения формы (НЕ ломай структуру продукта):
- Верни ТОЛЬКО JSON того же shape, что на входе.
- opening.bridge — НЕ меняй (это фиксированная связка из списка).
- opening.insight — отредактируй смысл, оставь строчную клаузу после «что», до 90 символов.
- body — один абзац, 4–6 предложений; формат onboarding deep insight (короче full Deep Insight).
- influences / cycles: key НЕ МЕНЯЙ; title и text можно переписать.
- product_pitch: title до 70 символов; text 2–3 предложения.
- outcomes.cards: key НЕ МЕНЯЙ; label/before/after/hint можно переписать; after > before.
- offer.title оставь ТОЧНО «Стань ближе к своему истинному я через подробный разбор»;
  cta ТОЧНО «Получить за 777»; price ТОЧНО «777 ₽/мес»; text — 2 строки через \\n.
- Не добавляй новых ключей. Не удаляй существующие элементы списков.
- Имя пользователя в текстах не пиши (его покажут отдельно).
- Язык: русский. Обращение на «ты».

content_type: {content_type}
"""


@lru_cache(maxsize=1)
def load_editorial_system() -> str:
    if not _EDITORIAL_PATH.exists():
        raise FileNotFoundError(f"Editorial system prompt not found: {_EDITORIAL_PATH}")
    return _EDITORIAL_PATH.read_text(encoding="utf-8").strip()


def editorial_system_prompt(*, content_type: str = "onboarding_insight") -> str:
    return EDIT_TASK.format(content_type=content_type) + "\n\n---\n\n" + load_editorial_system()


def extract_user_facing_copy(insight: dict[str, Any]) -> dict[str, Any]:
    """Вырезать только пользовательские тексты для редактуры."""
    payload: dict[str, Any] = {}
    for key in USER_FACING_INSIGHT_KEYS:
        if key in insight and insight[key] is not None:
            payload[key] = copy_json(insight[key])
    return payload


def copy_json(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False))


def merge_edited_copy(insight: dict[str, Any], edited: dict[str, Any]) -> dict[str, Any]:
    """Аккуратно влить отредактированные тексты, сохранив служебные поля."""
    out = copy_json(insight)

    if isinstance(edited.get("opening"), dict) and isinstance(out.get("opening"), dict):
        bridge = str(out["opening"].get("bridge") or "").strip()
        clause = str(edited["opening"].get("insight") or out["opening"].get("insight") or "").strip()
        if clause:
            clause = clause[0].lower() + clause[1:] if len(clause) > 1 else clause.lower()
        out["opening"] = {
            "bridge": bridge or str(edited["opening"].get("bridge") or "").strip(),
            "insight": clause[:120],
        }

    body = str(edited.get("body") or "").strip()
    if len(body) >= 40:
        out["body"] = body[:1000]

    for section in ("influences", "cycles"):
        if isinstance(edited.get(section), list) and isinstance(out.get(section), list):
            out[section] = _merge_keyed_items(out[section], edited[section], key_field="key")

    if isinstance(edited.get("product_pitch"), dict):
        pitch = edited["product_pitch"]
        base_pitch = out.get("product_pitch") if isinstance(out.get("product_pitch"), dict) else {}
        p_title = str(pitch.get("title") or base_pitch.get("title") or "").strip()
        p_text = str(pitch.get("text") or base_pitch.get("text") or "").strip()
        if p_title and p_text:
            out["product_pitch"] = {"title": p_title[:120], "text": p_text[:500]}

    outcomes = edited.get("outcomes")
    if isinstance(outcomes, dict):
        title = str(outcomes.get("title") or "").strip()
        cards = outcomes.get("cards")
        if title and isinstance(cards, list):
            merged_cards: list[dict[str, str]] = []
            base_cards = (
                (out.get("outcomes") or {}).get("cards")
                if isinstance(out.get("outcomes"), dict)
                else []
            ) or []
            for idx, card in enumerate(cards[:4]):
                if not isinstance(card, dict):
                    continue
                base = base_cards[idx] if idx < len(base_cards) and isinstance(base_cards[idx], dict) else {}
                key = str(card.get("key") or base.get("key") or f"metric_{idx}")
                label = str(card.get("label") or base.get("label") or "").strip()
                before = str(card.get("before") or base.get("before") or "").strip()
                after = str(card.get("after") or base.get("after") or "").strip()
                hint = str(card.get("hint") or base.get("hint") or "").strip()
                if label and before and after:
                    merged_cards.append(
                        {
                            "key": key[:40],
                            "label": label[:40],
                            "before": before[:12],
                            "after": after[:12],
                            "hint": hint[:80],
                        }
                    )
            if len(merged_cards) >= 4:
                out["outcomes"] = {"title": title[:120], "cards": merged_cards}

    offer = edited.get("offer")
    if isinstance(offer, dict) and isinstance(out.get("offer"), dict):
        base = out["offer"]
        text = str(offer.get("text") or base.get("text") or "").strip()
        cta = str(offer.get("cta") or base.get("cta") or "").strip()
        out["offer"] = {
            "title": "Стань ближе к своему истинному я через подробный разбор",
            "text": text[:500] if text else base.get("text", ""),
            "cta": "Получить за 777",
            "price": "777 ₽/мес",
        }

    out["editorial_passed"] = True
    return out


def _merge_keyed_items(
    original: list[dict[str, Any]],
    edited_items: list[Any],
    *,
    key_field: str,
) -> list[dict[str, Any]]:
    by_key: dict[str, dict[str, Any]] = {}
    for item in edited_items:
        if not isinstance(item, dict):
            continue
        key = str(item.get(key_field) or "").strip()
        if key:
            by_key[key] = item

    merged: list[dict[str, Any]] = []
    for src in original:
        key = str(src.get(key_field) or "")
        llm = by_key.get(key)
        if not llm:
            merged.append(src)
            continue
        row = dict(src)
        if "title" in src or "title" in llm:
            title = str(llm.get("title") or src.get("title") or "").strip()
            if title:
                row["title"] = title[:120]
        if "text" in src or "text" in llm:
            text = str(llm.get("text") or src.get("text") or "").strip()
            if text:
                row["text"] = text[:600]
        merged.append(row)
    return merged


def edit_user_facing_texts(
    *,
    draft: dict[str, Any],
    content_type: str = "onboarding_insight",
    context: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """
    Второй проход LLM: редактура пользовательских текстов.

    draft — полный insight или уже вырезанный user-facing payload.
    При ошибке / отсутствии LLM возвращает draft без изменений (editorial_passed не ставит).
    """
    if not llm_client.is_configured():
        return draft

    payload = extract_user_facing_copy(draft) if "influences" in draft or "body" in draft else copy_json(draft)
    if not payload:
        return draft

    user_parts = [
        "Отредактируй эти тексты по Editorial Writing System. Верни тот же JSON shape.",
        json.dumps(payload, ensure_ascii=False),
    ]
    if context:
        user_parts.insert(
            1,
            "Контекст (не копируй дословно в текст, используй для точности):\n"
            + json.dumps(context, ensure_ascii=False),
        )
    user = "\n\n".join(user_parts)

    try:
        edited = llm_client.chat_json(
            system=editorial_system_prompt(content_type=content_type),
            user=user,
            temperature=0.45,
            max_tokens=3500,
        )
    except Exception:
        logger.warning("Editorial pass failed; keeping draft copy", exc_info=False)
        return draft

    if not isinstance(edited, dict) or not edited:
        logger.warning("Editorial pass returned empty/non-object; keeping draft")
        return draft

    return merge_edited_copy(draft, edited)
