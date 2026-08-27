"""Versioned natal orb policy. Not claimed as The Pattern's unpublished orbs."""

from __future__ import annotations

ORB_POLICY_VERSION = "natal-orbs-v1"

NATAL_ORBS: dict[str, float] = {
    "conjunction": 6.0,
    "sextile": 4.0,
    "square": 6.0,
    "trine": 6.0,
    "opposition": 6.0,
}

ASPECT_ANGLES: dict[str, float] = {
    "conjunction": 0.0,
    "sextile": 60.0,
    "square": 90.0,
    "trine": 120.0,
    "opposition": 180.0,
}

HARD_ASPECTS = frozenset({"conjunction", "square", "opposition"})

LUMINARY_IDS = frozenset({"sun", "moon"})
ANGLE_IDS = frozenset({"asc", "dsc", "mc", "ic", "vertex", "antivertex", "ascendant", "midheaven"})
NODE_IDS = frozenset({"north_node", "south_node"})

LUMINARY_BONUS = 2.0
ANGLE_MAX_ORB = 5.0
NODE_MAX_ORB = 4.0
NEAR_CUSP_DEG = 1.0
APPLYING_STEP_DAYS = 5.0 / (24.0 * 60.0)

# Axis pairs are always 180°; do not emit them as natal aspects.
SKIP_ASPECT_PAIRS = frozenset(
    {
        frozenset({"north_node", "south_node"}),
        frozenset({"asc", "dsc"}),
        frozenset({"mc", "ic"}),
        frozenset({"vertex", "antivertex"}),
    }
)


def allowed_orb(aspect: str, id_a: str, id_b: str) -> float:
    orb = float(NATAL_ORBS[aspect])
    if id_a in LUMINARY_IDS or id_b in LUMINARY_IDS:
        orb += LUMINARY_BONUS
    if id_a in ANGLE_IDS or id_b in ANGLE_IDS:
        orb = min(orb, ANGLE_MAX_ORB)
    if id_a in NODE_IDS or id_b in NODE_IDS:
        orb = min(orb, NODE_MAX_ORB)
    return orb
