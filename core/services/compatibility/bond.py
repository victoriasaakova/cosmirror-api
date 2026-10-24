"""Классификатор Bond. Категорию назначает код, не модель.

Соответствие пар и категорий — рабочий черновик по смыслу bond_taxonomy_v1.
overall_bond_label не вычисляется.
"""

from __future__ import annotations

from typing import Any

from .policy import (
    ANGLES,
    ASPECT_RU,
    ATTRACTION_PAIRS,
    BOND_CATEGORIES,
    CATEGORY_TITLE,
    NODES,
    PERSONAL,
    SLOW,
    SOCIAL,
)
from .synastry import body_label


def _kind(body: str) -> int:
    if body in PERSONAL or body in ANGLES:
        return 3
    if body in SOCIAL or body in NODES:
        return 2
    return 1


def pair_class(body_a: str, body_b: str) -> int:
    left, right = _kind(body_a), _kind(body_b)
    if left == 1 and right == 1:
        return 0
    return min(left, right)


def _pair_key(body_a: str, body_b: str) -> tuple[str, str]:
    return tuple(sorted((body_a, body_b)))


def category_for(aspect: dict[str, Any]) -> str | None:
    body_a = aspect["person_a_point"]
    body_b = aspect["person_b_point"]
    if body_a in SLOW and body_b in SLOW:
        return None
    if not aspect.get("bond_eligible", True):
        return None
    key = _pair_key(body_a, body_b)
    quality = aspect["quality"]
    closeness = float(aspect["normalized_closeness"])
    personal_or_angle = body_a in PERSONAL or body_b in PERSONAL or body_a in ANGLES or body_b in ANGLES
    if key in ATTRACTION_PAIRS:
        return "attraction"
    if "saturn" in key and ("sun" in key or "moon" in key) and quality == "tension":
        return "trials"
    if quality == "tension" and personal_or_angle and ({"mars", "saturn", "pluto"} & set(key)):
        return "frustration"
    slow_personal = personal_or_angle and (body_a in SLOW or body_b in SLOW)
    if slow_personal and (aspect["aspect"] == "conjunction" or closeness >= 0.75):
        return "life_changing"
    both_personal = body_a in PERSONAL and body_b in PERSONAL
    personal_jupiter = "jupiter" in key and personal_or_angle
    if quality == "harmonizing" and (both_personal or personal_jupiter):
        return "amazing"
    return "notables"


def _rank(aspect: dict[str, Any]) -> tuple[float, float, float]:
    return (
        pair_class(aspect["person_a_point"], aspect["person_b_point"]),
        float(aspect["normalized_closeness"]),
        -float(aspect["orb_deg"]),
    )


def _cluster_key(aspect: dict[str, Any]) -> tuple[str, tuple[tuple[str, str], tuple[str, str]]]:
    ends = tuple(
        sorted(
            (
                ("A", aspect["person_a_point"]),
                ("B", aspect["person_b_point"]),
            )
        )
    )
    return (aspect["aspect"], ends)


def build_bond(aspects: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[tuple, list[dict[str, Any]]] = {}
    for aspect in aspects:
        if aspect["direction"] != "A_to_B":
            continue
        category = category_for(aspect)
        if category is None:
            continue
        grouped.setdefault(_cluster_key(aspect), []).append(aspect)

    clusters: list[dict[str, Any]] = []
    for key, rows in grouped.items():
        primary = max(rows, key=_rank)
        evidence_ids = sorted({row["id"] for row in aspects if _cluster_key(row) == key})
        clusters.append(
            {
                "primary": primary,
                "category": category_for(primary),
                "evidence_ids": evidence_ids,
                "rank": _rank(primary),
            }
        )
    clusters.sort(key=lambda item: item["rank"], reverse=True)

    by_category: dict[str, list[dict[str, Any]]] = {code: [] for code in BOND_CATEGORIES}
    for cluster in clusters:
        bucket = by_category[cluster["category"]]
        if len(bucket) >= 3:
            continue
        bucket.append(cluster)

    categories = []
    insights = []
    for code in BOND_CATEGORIES:
        bucket = by_category[code]
        if not bucket:
            continue
        aspect_ids: list[str] = []
        for cluster in bucket:
            aspect_ids.extend(cluster["evidence_ids"])
        categories.append({"id": code, "aspect_ids": aspect_ids})
        for index, cluster in enumerate(bucket, start=1):
            insights.append(_insight(code, index, cluster))

    strongest = next(
        (
            cluster
            for cluster in clusters
            if _involves_personal_or_angle(cluster["primary"])
        ),
        None,
    )
    challenge = next(
        (cluster for cluster in clusters if cluster["primary"]["quality"] == "tension"),
        None,
    )
    return {
        "status": "ready",
        "overall_bond_label": None,
        "strongest_connection_id": strongest["primary"]["id"] if strongest else None,
        "biggest_challenge_id": challenge["primary"]["id"] if challenge else None,
        "categories": categories,
        "insights": insights,
    }


def _involves_personal_or_angle(aspect: dict[str, Any]) -> bool:
    bodies = (aspect["person_a_point"], aspect["person_b_point"])
    return any(body in PERSONAL or body in ANGLES for body in bodies)


def _insight(category: str, index: int, cluster: dict[str, Any]) -> dict[str, Any]:
    aspect = cluster["primary"]
    left = body_label(aspect["person_a_point"])
    right = body_label(aspect["person_b_point"])
    aspect_name = ASPECT_RU[aspect["aspect"]]
    quality = aspect["quality"]
    eyebrow = f"{left} A {aspect_name} {right} B"
    if quality == "harmonizing":
        snapshot = "Такой аспект в астрологии описывают как более лёгкий обмен между двумя функциями."
        deep_read = (
            "Это может ощущаться как более прямой обмен между двумя функциями. "
            "Карта не обещает, что так и есть: это можно проверить на вашем опыте."
        )
    elif quality == "tension":
        snapshot = "Такой аспект в астрологии описывают как разницу ритма, не как плохую совместимость."
        deep_read = (
            "Это может ощущаться как разный ритм в одной и той же ситуации. "
            "Карта не считает такую разницу приговором: это можно проверить на вашем опыте."
        )
    else:
        snapshot = "Соединение делает тему заметнее и само по себе не является плюсом или минусом."
        deep_read = (
            "Соединение показывает, где тема может становиться заметнее. "
            "Как она выглядит у вас, можно проверить на вашем опыте."
        )
    return {
        "id": f"insight-{category}-{index}",
        "category": category,
        "evidence_ids": cluster["evidence_ids"],
        "eyebrow": eyebrow,
        "title": CATEGORY_TITLE[category],
        "snapshot": snapshot,
        "summary": f"Между вами {left} A и {right} B образуют {aspect_name}.",
        "deep_read": deep_read,
        "perspective": "mutual",
        "share_text": "Между вами есть эта связка. Её можно проверить на вашем опыте.",
    }
