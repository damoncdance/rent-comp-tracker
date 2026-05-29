"""Pricing recommendation engine for the subject property.

Computes recommended rents for each available unit at the subject property
by analyzing comp set data. Uses an adjusted PSF (price per square foot)
methodology with quality, amenity, inventory pressure, and unit-level
adjustments.

Usage:
    from src.pricing import generate_recommendations
    recs = generate_recommendations()
    # recs is a PricingReport with per-unit recommendations and summary stats
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from collections import defaultdict

from src.amenities import AMENITIES
from src.ner import calculate_ner
from src.storage import db


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class UnitRecommendation:
    unit_code: str
    floorplan_name: str
    beds: int
    baths: float
    sqft: int
    listed_rent: float
    recommended_rent: float
    aggressive_rent: float
    conservative_rent: float
    delta: float              # recommended - listed (positive = underpriced)
    delta_pct: float          # delta as % of listed
    signal: str               # "underpriced", "market", "overpriced", "well_above"
    market_psf: float         # comp market PSF for this bed type
    unit_psf: float           # this unit's listed PSF
    recommended_psf: float    # recommended PSF after adjustments
    adjustments: dict = field(default_factory=dict)


@dataclass
class PricingReport:
    subject_name: str
    subject_slug: str
    units: list[UnitRecommendation]
    summary: dict
    market_psf_by_bed: dict[int, float]
    comp_count: int
    generated_at: str


# ---------------------------------------------------------------------------
# Quality scoring
# ---------------------------------------------------------------------------

# Management company tiers (higher = more premium/institutional)
_MGMT_TIERS = {
    "Greystar": 3, "Bozzuto": 3, "Marquette Management": 2,
    "Cagan": 2, "Lg Development Group": 2, "Tandem": 2,
    "Flats": 2, "Continuum Real Estate Brokers, Inc.": 1,
    "Luxury Living Chicago Realty": 1, "Turbotenant": 1,
}

# Baseline unit features — missing any of these is a penalty
_BASELINE_FEATURES = {
    "in-unit w/d", "quartz countertops", "stainless",
}

# Weight multiplier for units whose per-unit rent was interpolated rather than
# observed (e.g. SecureCafe tier ranges). They still inform the market but are
# trusted less than real observed prices.
_ESTIMATED_WEIGHT = 0.5


def _quality_score(prop: dict, amenity_data: dict | None) -> float:
    """Compute a 1-10 quality score for a property."""
    score = 5.0  # start at midpoint

    # Year built: newer is better, diminishing returns
    year = prop.get("year_built")
    if year:
        if year >= 2024:
            score += 1.5
        elif year >= 2022:
            score += 1.2
        elif year >= 2020:
            score += 0.8
        elif year >= 2018:
            score += 0.4
        elif year >= 2015:
            score += 0.0
        else:
            score -= 0.5

    # Stories (proxy for construction quality)
    stories = prop.get("stories") or 0
    if stories >= 20:
        score += 0.8
    elif stories >= 10:
        score += 0.5
    elif stories >= 7:
        score += 0.2

    # Management tier
    mgmt = prop.get("management_company", "")
    tier = _MGMT_TIERS.get(mgmt, 1)
    score += (tier - 1) * 0.3  # tier 3 = +0.6, tier 2 = +0.3, tier 1 = 0

    if amenity_data:
        # Amenity breadth
        building = amenity_data.get("building_amenities", [])
        score += min(len(building) / 4, 1.5)  # up to +1.5 for 6+ amenities

        # Premium features
        if amenity_data.get("pool"):
            score += 0.5
        if amenity_data.get("doorman_concierge"):
            score += 0.3
        if "Peloton" in amenity_data.get("fitness", "") or \
           "Premium" in amenity_data.get("fitness", ""):
            score += 0.3

        # Note: baseline feature penalties (missing W/D, quartz, stainless)
        # are applied in _compute_amenity_adjustment() to avoid double-counting.

    return max(1.0, min(10.0, round(score, 1)))


# ---------------------------------------------------------------------------
# Core pricing algorithm
# ---------------------------------------------------------------------------

_cached_report: PricingReport | None = None
_cache_valid = False


def generate_recommendations(*, force: bool = False) -> PricingReport | None:
    """Generate pricing recommendations for the subject property.

    Returns a PricingReport, or None if insufficient data.
    Results are cached within the same process — call with force=True to refresh.
    """
    global _cached_report, _cache_valid
    if _cache_valid and not force:
        return _cached_report

    report = _generate_recommendations_impl()
    _cached_report = report
    _cache_valid = True
    return report


def _generate_recommendations_impl() -> PricingReport | None:
    from datetime import datetime, timezone

    with db() as conn:
        # Find subject property
        subject = conn.execute(
            "SELECT * FROM properties WHERE is_subject = 1 AND active = 1"
        ).fetchone()
        if not subject:
            return None
        subject = dict(subject)
        subject_id = subject["id"]
        subject_slug = subject["slug"]

        # Get all active properties
        all_props = [dict(r) for r in conn.execute(
            "SELECT * FROM properties WHERE active = 1 ORDER BY is_subject DESC, name"
        ).fetchall()]

        # Get latest snapshot for each property
        prop_units: dict[int, list[dict]] = {}
        prop_snaps: dict[int, dict] = {}
        for p in all_props:
            snap = conn.execute(
                "SELECT * FROM snapshots WHERE property_id = ? "
                "AND fetch_status = 'success' ORDER BY id DESC LIMIT 1",
                (p["id"],),
            ).fetchone()
            if not snap:
                prop_units[p["id"]] = []
                continue
            snap = dict(snap)
            prop_snaps[p["id"]] = snap
            units = [dict(r) for r in conn.execute(
                "SELECT * FROM units WHERE snapshot_id = ? "
                "ORDER BY beds, floorplan_name, unit_code",
                (snap["id"],),
            ).fetchall()]
            prop_units[p["id"]] = units

    subject_units = prop_units.get(subject_id, [])
    # Filter out $0 rent units (hold/unavailable)
    subject_units = [u for u in subject_units if u["min_rent"] and u["min_rent"] > 0]
    if not subject_units:
        return None

    # Comp units (everything except subject)
    comp_props = [p for p in all_props if p["id"] != subject_id]
    all_comp_units = []
    for p in comp_props:
        for u in prop_units.get(p["id"], []):
            if u["min_rent"] and u["min_rent"] > 0 and u["sqft"] and u["sqft"] > 0:
                u["_prop"] = p
                all_comp_units.append(u)

    if not all_comp_units:
        return None

    # --- Step 1: Market PSF by bed type ---
    market_psf_by_bed = _compute_market_psf(all_comp_units, comp_props, prop_snaps)

    # --- Step 2: Quality scores ---
    subject_amenities = AMENITIES.get(subject_slug)
    subject_quality = _quality_score(subject, subject_amenities)

    comp_qualities = []
    for p in comp_props:
        am = AMENITIES.get(p["slug"])
        comp_qualities.append(_quality_score(p, am))
    comp_avg_quality = statistics.mean(comp_qualities) if comp_qualities else 5.0

    quality_adj = 1 + (subject_quality - comp_avg_quality) * 0.03
    quality_adj = max(0.85, min(1.15, quality_adj))

    # --- Step 3: Amenity adjustment ---
    amenity_adj = _compute_amenity_adjustment(subject_slug, comp_props)

    # --- Step 4: Inventory pressure ---
    subject_total = subject.get("unit_count_total") or len(subject_units) or 1
    subject_exposure = len(subject_units) / subject_total

    comp_exposures = []
    for p in comp_props:
        avail = len(prop_units.get(p["id"], []))
        total = p.get("unit_count_total") or avail or 1
        comp_exposures.append(avail / total)
    comp_avg_exposure = statistics.mean(comp_exposures) if comp_exposures else 0.1

    # Per-bed-type inventory pressure
    bed_exposure_subject = defaultdict(float)
    bed_exposure_comp = defaultdict(list)

    for u in subject_units:
        bed_exposure_subject[u["beds"]] += 1
    for u in all_comp_units:
        bed_exposure_comp[u["beds"]].append(u)

    # --- Step 5 & 6: Generate per-unit recommendations ---
    recommendations = []
    for u in subject_units:
        beds = u["beds"]
        sqft = u["sqft"]
        listed = u["min_rent"]

        if sqft <= 0 or listed <= 0:
            continue

        # Market PSF for this bed type
        m_psf = market_psf_by_bed.get(beds)
        if m_psf is None:
            # Fall back to overall market PSF
            all_psfs = [cu["min_rent"] / cu["sqft"] for cu in all_comp_units
                        if cu["sqft"] > 0]
            m_psf = statistics.mean(all_psfs) if all_psfs else listed / sqft

        # Inventory pressure for this bed type
        subj_bed_count = bed_exposure_subject.get(beds, 0)
        comp_bed_units = bed_exposure_comp.get(beds, [])
        if comp_bed_units:
            # Average comp availability for this bed type as % of their total units
            comp_bed_avail = defaultdict(int)
            comp_bed_total = defaultdict(int)
            for cu in comp_bed_units:
                pid = cu["_prop"]["id"]
                comp_bed_avail[pid] += 1
            for p in comp_props:
                comp_bed_total[p["id"]] = p.get("unit_count_total") or 1

            comp_bed_exposures = []
            for pid in comp_bed_avail:
                comp_bed_exposures.append(comp_bed_avail[pid] / comp_bed_total[pid])
            avg_comp_bed_exp = statistics.mean(comp_bed_exposures) if comp_bed_exposures else 0.1

            subj_bed_exp = subj_bed_count / subject_total
            pressure_adj = 1 - (subj_bed_exp - avg_comp_bed_exp) * 0.5
            pressure_adj = max(0.90, min(1.05, pressure_adj))
        else:
            pressure_adj = 1.0

        # Size adjustment: discount when subject units are smaller than
        # comp average for the same bed type (e.g. IWT 2BRs at 830 sqft
        # vs comp avg ~1,020 sqft).  Smaller units command lower PSF
        # because renters perceive less value even at the same $/ft².
        size_adj = _size_adjustment(sqft, beds, all_comp_units)

        # Unit-level adjustments
        unit_adj = _unit_level_adjustment(u)

        # NER context: check if comps are offering concessions
        conc_adj = _concession_adjustment(all_comp_units, beds, u)

        # Compute recommended
        adj_psf = m_psf * quality_adj * amenity_adj * pressure_adj * size_adj * unit_adj * conc_adj
        recommended = round(adj_psf * sqft)

        # Confidence band
        aggressive = round(recommended * 1.05)
        conservative = round(recommended * 0.95)

        # Delta and signal
        delta = recommended - listed
        delta_pct = delta / listed if listed > 0 else 0

        if delta_pct > 0.03:
            signal = "underpriced"
        elif delta_pct < -0.08:
            signal = "well_above"
        elif delta_pct < -0.03:
            signal = "overpriced"
        else:
            signal = "market"

        recommendations.append(UnitRecommendation(
            unit_code=u["unit_code"],
            floorplan_name=u["floorplan_name"],
            beds=beds,
            baths=u["baths"],
            sqft=sqft,
            listed_rent=listed,
            recommended_rent=recommended,
            aggressive_rent=aggressive,
            conservative_rent=conservative,
            delta=delta,
            delta_pct=round(delta_pct, 4),
            signal=signal,
            market_psf=round(m_psf, 2),
            unit_psf=round(listed / sqft, 2),
            recommended_psf=round(adj_psf, 2),
            adjustments={
                "quality": round(quality_adj, 3),
                "amenity": round(amenity_adj, 3),
                "pressure": round(pressure_adj, 3),
                "size": round(size_adj, 3),
                "unit": round(unit_adj, 3),
                "concession": round(conc_adj, 3),
            },
        ))

    # Sort by beds then sqft
    recommendations.sort(key=lambda r: (r.beds, r.sqft))

    # Summary stats
    if recommendations:
        listed_total = sum(r.listed_rent for r in recommendations)
        rec_total = sum(r.recommended_rent for r in recommendations)
        over = sum(1 for r in recommendations if r.signal in ("overpriced", "well_above"))
        under = sum(1 for r in recommendations if r.signal == "underpriced")
        at_market = sum(1 for r in recommendations if r.signal == "market")
        avg_delta = statistics.mean(r.delta for r in recommendations)
        avg_delta_pct = statistics.mean(r.delta_pct for r in recommendations)
    else:
        listed_total = rec_total = over = under = at_market = 0
        avg_delta = avg_delta_pct = 0

    summary = {
        "total_units": len(recommendations),
        "overpriced_count": over,
        "underpriced_count": under,
        "market_count": at_market,
        "avg_listed": round(listed_total / len(recommendations)) if recommendations else 0,
        "avg_recommended": round(rec_total / len(recommendations)) if recommendations else 0,
        "avg_delta": round(avg_delta),
        "avg_delta_pct": round(avg_delta_pct, 3),
        "monthly_revenue_impact": round(rec_total - listed_total),
        "subject_quality_score": subject_quality,
        "comp_avg_quality_score": round(comp_avg_quality, 1),
        "subject_exposure": round(subject_exposure * 100, 1),
        "comp_avg_exposure": round(comp_avg_exposure * 100, 1),
        "estimated_comp_units": sum(1 for cu in all_comp_units if cu.get("is_estimated")),
        "total_comp_units": len(all_comp_units),
    }

    return PricingReport(
        subject_name=subject["name"],
        subject_slug=subject_slug,
        units=recommendations,
        summary=summary,
        market_psf_by_bed={b: round(v, 2) for b, v in market_psf_by_bed.items()},
        comp_count=len(comp_props),
        generated_at=datetime.now(timezone.utc).isoformat(),
    )


def _compute_market_psf(
    comp_units: list[dict],
    comp_props: list[dict],
    prop_snaps: dict[int, dict],
) -> dict[int, float]:
    """Compute weighted market PSF by bed type.

    Weight: inverse of property exposure % (tighter buildings weigh more).
    Outlier removal: exclude below P10 and above P90.
    """
    by_bed: dict[int, list[tuple[float, float]]] = defaultdict(list)

    for u in comp_units:
        if u["sqft"] <= 0:
            continue
        psf = u["min_rent"] / u["sqft"]
        prop = u["_prop"]
        snap = prop_snaps.get(prop["id"])
        avail = snap.get("unit_count", 1) if snap else 1
        total = prop.get("unit_count_total") or avail or 1
        exposure = max(avail / total, 0.01)
        # Cap weight so one very-tight building can't dominate
        weight = min(1 / exposure, 20.0)
        # Trust interpolated (non-observed) rents less.
        if u.get("is_estimated"):
            weight *= _ESTIMATED_WEIGHT
        by_bed[u["beds"]].append((psf, weight))

    result = {}
    for beds, pairs in by_bed.items():
        psfs = [p[0] for p in pairs]
        if len(psfs) < 3:
            result[beds] = statistics.mean(psfs) if psfs else 0
            continue

        # Remove outliers using proper quantiles
        quantiles = statistics.quantiles(psfs, n=10)
        p10 = quantiles[0]   # 10th percentile
        p90 = quantiles[-1]  # 90th percentile
        filtered = [(p, w) for p, w in pairs if p10 <= p <= p90]

        if not filtered:
            filtered = pairs

        # Weighted average
        total_weight = sum(w for _, w in filtered)
        if total_weight > 0:
            result[beds] = sum(p * w for p, w in filtered) / total_weight
        else:
            result[beds] = statistics.mean(psfs)

    return result


def _compute_amenity_adjustment(subject_slug: str, comp_props: list[dict]) -> float:
    """Compute amenity-based price adjustment.

    Two parts:
    - Penalty for missing baseline amenities (-2% each)
    - Premium for extras above comp average (+1% each, capped at +10%)
    """
    subject_am = AMENITIES.get(subject_slug, {})
    if not subject_am:
        return 1.0

    # Count amenity categories for subject
    subj_score = _amenity_count(subject_am)

    # Comp average
    comp_scores = []
    for p in comp_props:
        am = AMENITIES.get(p["slug"], {})
        if am:
            comp_scores.append(_amenity_count(am))

    comp_avg = statistics.mean(comp_scores) if comp_scores else subj_score

    # Premium for extras
    extra = subj_score - comp_avg
    premium = extra * 0.01  # 1% per extra amenity category
    premium = max(-0.10, min(0.10, premium))

    # Baseline penalty
    features_text = " ".join(f.lower() for f in subject_am.get("unit_features", []))
    penalty = 0.0
    for baseline in _BASELINE_FEATURES:
        if baseline not in features_text:
            penalty -= 0.02  # -2% per missing baseline

    adj = 1.0 + premium + penalty
    return max(0.85, min(1.15, round(adj, 3)))


def _amenity_count(am: dict) -> int:
    """Count distinct amenity categories for scoring."""
    count = len(am.get("building_amenities", []))
    count += len(am.get("unit_features", []))
    if am.get("pool"):
        count += 3  # pool is high-value
    if am.get("doorman_concierge"):
        count += 2
    if "Premium" in am.get("fitness", "") or "Peloton" in am.get("fitness", ""):
        count += 2
    if am.get("rooftop"):
        count += 1
    return count


def _size_adjustment(sqft: int, beds: int, comp_units: list[dict]) -> float:
    """Adjust for units that are materially smaller than the comp average.

    Renters shopping a bed type compare total space, not just PSF.  A 2BR
    at 830 sqft competes differently than one at 1,020 sqft — the smaller
    unit must price at a lower PSF to hit a palatable gross rent.

    Methodology: -1% for every 5% the unit is below the comp-set average
    sqft for that bed type.  No bonus for being larger (captured by PSF).
    Capped at -10%.
    """
    bed_comps = [u for u in comp_units if u["beds"] == beds and u["sqft"] and u["sqft"] > 0]
    if not bed_comps:
        return 1.0

    comp_avg_sqft = statistics.mean(u["sqft"] for u in bed_comps)
    if comp_avg_sqft <= 0:
        return 1.0

    pct_below = (comp_avg_sqft - sqft) / comp_avg_sqft

    if pct_below <= 0:
        # Unit is at or above comp average — no adjustment
        return 1.0

    # -1% for every 5% below average (i.e., -0.2 × pct_below)
    discount = pct_below * 0.20
    adj = 1.0 - discount
    return max(0.90, round(adj, 3))


def _unit_level_adjustment(unit: dict) -> float:
    """Compute unit-specific price adjustment from floorplan features."""
    adj = 1.0
    fp = (unit.get("floorplan_name") or "").lower()
    code = (unit.get("unit_code") or "").upper()

    # Balcony premium
    if "balcony" in fp or "balc" in fp or "terrace" in fp:
        adj += 0.03

    # Infer floor from unit code.  Handles both formats:
    #   "L8-101" style  →  floor 8
    #   "816"    style  →  floor 8 (first digit(s) = floor for 3-digit codes)
    floor = _infer_floor(code)

    # Top floor / penthouse
    if "penthouse" in fp or "ph" in fp:
        adj += 0.05
    elif floor and floor >= 8:
        adj += 0.04
    elif floor == 7:
        adj += 0.02

    # Lower floor discount
    if floor and floor <= 2:
        adj -= 0.02

    # Den / office bonus
    if "den" in fp or "office" in fp:
        adj += 0.02

    return round(adj, 3)


def _infer_floor(code: str) -> int | None:
    """Infer floor number from a unit code.

    Supports:
      "L8-101", "L10" → strip L prefix, take number
      "816"           → floor 8 (first digit of 3-digit code)
      "1204"          → floor 12 (first two digits of 4-digit code)
    """
    import re
    if not code:
        return None
    # "L8", "L10-xxx" format
    m = re.match(r"L(\d+)", code, re.IGNORECASE)
    if m:
        return int(m.group(1))
    # Pure numeric: 3 digits → first digit is floor, 4 digits → first two
    if code.isdigit():
        if len(code) == 3:
            return int(code[0])
        if len(code) == 4:
            return int(code[:2])
    return None


def _concession_adjustment(comp_units: list[dict], beds: int, subject_unit: dict) -> float:
    """Adjust for concession pressure from comp set.

    If comps offer concessions but subject doesn't, subject should price lower
    to remain competitive on net effective rent.
    """
    # Check if subject unit has concessions
    subj_conc = (subject_unit.get("concession_text") or "").strip()
    subj_has_conc = bool(subj_conc)

    # Check comp concessions for this bed type
    bed_comps = [u for u in comp_units if u["beds"] == beds]
    if not bed_comps:
        return 1.0

    conc_pcts = []
    for u in bed_comps:
        conc_text = (u.get("concession_text") or "").strip()
        if conc_text and u["min_rent"] > 0:
            nr = calculate_ner(u["min_rent"], conc_text)
            if nr.concession_pct > 0:
                conc_pcts.append(nr.concession_pct)

    if not conc_pcts:
        return 1.0

    avg_conc_pct = statistics.mean(conc_pcts)

    # If subject has no concessions but comps do, adjust down
    if not subj_has_conc and avg_conc_pct > 0.01:
        # Halve the effect — don't fully match concessions
        adj = 1 - (avg_conc_pct * 0.5)
        return max(0.90, round(adj, 3))

    return 1.0


# ---------------------------------------------------------------------------
# Signal helpers (for display)
# ---------------------------------------------------------------------------

_SIGNAL_LABELS = {
    "underpriced": "↑ Underpriced",
    "market": "≈ Market",
    "overpriced": "↓ Overpriced",
    "well_above": "⚠ Well Above",
}

_SIGNAL_COLORS = {
    "underpriced": "#3fb950",
    "market": "#8a8f98",
    "overpriced": "#d29922",
    "well_above": "#f85149",
}


def signal_label(signal: str) -> str:
    return _SIGNAL_LABELS.get(signal, signal)


def signal_color(signal: str) -> str:
    return _SIGNAL_COLORS.get(signal, "#8a8f98")
