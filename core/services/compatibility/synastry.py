"""Межкарточные аспекты и оверлеи. Долготы приходят из calculate_natal."""

from __future__ import annotations

from typing import Any, Optional

from core.services.natal_common import angular_distance, house_of_longitude

from .policy import (
    ANGLE_ORB_CAP,
    ANGLES,
    ASPECTS,
    BODY_RU,
    CHART_BODIES,
    NODE_ORB_CAP,
    NODES,
    OVERLAY_BODIES,
)


def _round_orb(value: float) -> float:
    return round(float(value), 4)


def allowed_orb(aspect: str, body_a: str, body_b: str) -> float:
    base = next(orb for name, _exact, orb in ASPECTS if name == aspect)
    if body_a in ANGLES or body_b in ANGLES:
        base = min(base, ANGLE_ORB_CAP)
    if body_a in NODES or body_b in NODES:
        base = min(base, NODE_ORB_CAP)
    return base


def aspect_between(lon_a: float, lon_b: float, body_a: str, body_b: str) -> Optional[dict[str, Any]]:
    """Ближайший мажорный аспект внутри synastry_orbs_v1. На границе орб включён."""
    separation = angular_distance(lon_a, lon_b)
    best: Optional[dict[str, Any]] = None
    for name, exact, _base in ASPECTS:
        orb = _round_orb(abs(separation - exact))
        limit = allowed_orb(name, body_a, body_b)
        if orb > limit:
            continue
        if best is None or orb < best["orb_deg"]:
            best = {
                "aspect": name,
                "angle": exact,
                "orb_deg": orb,
                "allowed_orb_deg": limit,
                "normalized_closeness": round(max(0.0, 1.0 - orb / limit), 4) if limit else 0.0,
            }
    return best


def quality_of(aspect: str) -> str:
    if aspect in {"trine", "sextile"}:
        return "harmonizing"
    if aspect in {"square", "opposition"}:
        return "tension"
    return "mixed"


def cross_aspects(points_a: list[dict[str, Any]], points_b: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """A→B и обратная запись B→A. A Венера × B Марс не равен A Марс × B Венера."""
    found: list[dict[str, Any]] = []
    for left in points_a:
        for right in points_b:
            hit = aspect_between(left["longitude"], right["longitude"], left["body"], right["body"])
            if hit is None:
                continue
            eligible = bool(left.get("bond_eligible") and right.get("bond_eligible"))
            forward_id = _aspect_id("A", left["body"], "B", right["body"], hit["aspect"])
            reverse_id = _aspect_id("B", right["body"], "A", left["body"], hit["aspect"])
            common = {
                **hit,
                "person_a_point": left["body"],
                "person_b_point": right["body"],
                "sign_a": left.get("sign"),
                "sign_b": right.get("sign"),
                "quality": quality_of(hit["aspect"]),
                "source_ids": ["natal-A", "natal-B"],
                "bond_eligible": eligible,
            }
            found.append({**common, "id": forward_id, "direction": "A_to_B"})
            found.append({**common, "id": reverse_id, "direction": "B_to_A"})
    found.sort(key=lambda row: row["id"])
    return found


def _aspect_id(owner_1: str, body_1: str, owner_2: str, body_2: str, aspect: str) -> str:
    return f"cross-{owner_1}-{body_1}-{owner_2}-{body_2}-{aspect}"


def positions_for(points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for point in points:
        rows.append(
            {
                "body": point["body"],
                "sign": point.get("sign"),
                "degree": point.get("degree"),
                "longitude": round(float(point["longitude"]), 4),
                "house_if_known": point.get("house"),
            }
        )
    return rows


def aspect_matrix(points_a: list[dict[str, Any]], points_b: list[dict[str, Any]], aspects: list[dict[str, Any]]) -> dict[str, Any]:
    by_pair = {
        (row["person_a_point"], row["person_b_point"]): row
        for row in aspects
        if row["direction"] == "A_to_B"
    }
    rows = [point["body"] for point in points_a]
    columns = [point["body"] for point in points_b]
    cells: list[list[Optional[dict[str, Any]]]] = []
    for body_a in rows:
        row_cells: list[Optional[dict[str, Any]]] = []
        for body_b in columns:
            hit = by_pair.get((body_a, body_b))
            if hit is None:
                row_cells.append(None)
            else:
                row_cells.append(
                    {
                        "aspect": hit["aspect"],
                        "orb_deg": hit["orb_deg"],
                        "quality": hit["quality"],
                    }
                )
        cells.append(row_cells)
    return {"rows": rows, "columns": columns, "cells": cells}


def house_overlays(
    points_a: list[dict[str, Any]],
    points_b: list[dict[str, Any]],
    cusps_a: Optional[list[float]],
    cusps_b: Optional[list[float]],
) -> dict[str, list[dict[str, Any]]]:
    return {
        "A_in_B": _overlay(points_a, cusps_b),
        "B_in_A": _overlay(points_b, cusps_a),
    }


def _overlay(points: list[dict[str, Any]], cusps: Optional[list[float]]) -> list[dict[str, Any]]:
    if not cusps or len(cusps) != 12:
        return []
    rows = []
    for point in points:
        if point["body"] not in OVERLAY_BODIES:
            continue
        if not point.get("overlay_eligible", True):
            continue
        rows.append(
            {
                "body": point["body"],
                "house": house_of_longitude(point["longitude"], cusps),
                "longitude": round(float(point["longitude"]), 4),
            }
        )
    return rows


def chart_point_order(points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    order = {body: index for index, body in enumerate(CHART_BODIES + ("asc", "mc"))}
    return sorted(points, key=lambda point: order.get(point["body"], 100))


def body_label(body: str) -> str:
    return BODY_RU.get(body, body)
