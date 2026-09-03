"""Three scores per notice: capability fit, ease of lift, and incumbent risk.

Lift is the headline ranking axis - it estimates how much work standing up a
credible bid and then delivering would cost you. Lower is lighter.

Incumbent risk answers the separate 'is anyone already servicing this?'
question: a re-let with a TUPE population and a happy incumbent is a very
different proposition from a genuinely new requirement.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass

from .model import Notice

_UTC = dt.timezone.utc

# ---------------------------------------------------------------------------
# Capability areas
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CapabilityArea:
    key: str
    label: str
    cpv_divisions: tuple[str, ...]      # leading 2 digits of the CPV code
    cpv_groups: tuple[str, ...]         # leading 4 digits, a tighter match
    strong_keywords: tuple[str, ...]
    weak_keywords: tuple[str, ...]


CAPABILITY_AREAS: dict[str, CapabilityArea] = {
    "it": CapabilityArea(
        key="it",
        label="IT, digital & data",
        cpv_divisions=("48", "72"),
        cpv_groups=("3020", "3021", "3023", "3200", "3242", "3252", "511", "5031", "5032", "7935"),
        strong_keywords=(
            "software", "digital", "website", "web application", "data platform",
            "system integration", "it support", "managed service", "cyber security",
            "cloud", "saas", "application development", "data analysis", "analytics",
            "database", "api", "hosting", "network infrastructure", "ict", "crm",
            "case management system", "business intelligence", "automation",
        ),
        weak_keywords=("system", "platform", "data", "online", "portal", "technology", "licence"),
    ),
    "professional": CapabilityArea(
        key="professional",
        label="Professional & advisory",
        cpv_divisions=("66", "73", "79", "80", "85312"),
        cpv_groups=("7141", "7124", "7135", "7924", "7941", "7942", "7952", "7995", "8053", "8056"),
        strong_keywords=(
            "consultancy", "consulting", "advisory", "feasibility study", "strategy",
            "business case", "training", "programme management", "project management",
            "research", "evaluation", "review", "audit", "communications",
            "engagement", "market testing", "policy", "workshop", "coaching",
            "recruitment", "interim", "financial advice", "legal services",
        ),
        weak_keywords=("support services", "professional services", "development", "framework", "adviser"),
    ),
    "facilities": CapabilityArea(
        key="facilities",
        label="Facilities, works & maintenance",
        cpv_divisions=("45", "50", "90", "77", "44", "09", "34", "71"),
        cpv_groups=("7031", "9891", "5570", "6010", "7952"),
        strong_keywords=(
            "maintenance", "repairs", "refurbishment", "construction", "installation",
            "cleaning", "grounds maintenance", "landscaping", "highways", "surfacing",
            "waste", "recycling", "mechanical and electrical", "m&e", "hvac",
            "roofing", "fencing", "painting", "decorating", "plumbing", "electrical",
            "fire safety", "asbestos", "legionella", "building services", "fabric",
            "street lighting", "drainage", "groundworks", "fit out", "facilities management",
        ),
        weak_keywords=("works", "building", "site", "premises", "vehicle", "plant", "estate"),
    ),
    "care": CapabilityArea(
        key="care",
        label="Care, health & community",
        cpv_divisions=("85", "98"),
        cpv_groups=("8531", "8532", "8514", "8000", "9851"),
        strong_keywords=(
            "social care", "domiciliary", "supported living", "residential care",
            "safeguarding", "mental health", "substance misuse", "youth service",
            "wellbeing", "advocacy", "respite", "fostering", "homelessness",
            "public health", "nursing", "therapeutic",
        ),
        weak_keywords=("care", "health", "community", "support", "family", "children"),
    ),
}


def _cpv_hit(notice: Notice, area: CapabilityArea) -> tuple[bool, bool]:
    """Return (division_match, group_match)."""
    division = group = False
    for code in notice.cpv_codes:
        digits = re.sub(r"\D", "", code)
        if len(digits) < 2:
            continue
        if digits[:2] in area.cpv_divisions:
            division = True
        if any(digits.startswith(g) for g in area.cpv_groups):
            division = True
            group = True
    return division, group


def score_fit(notice: Notice, areas: list[str]) -> tuple[float, list[str]]:
    """0-100 confidence that this sits inside the given capability areas."""
    best = 0.0
    matched: list[str] = []

    for key in areas:
        area = CAPABILITY_AREAS.get(key)
        if area is None:
            continue
        score = 0.0
        title = notice.title.lower()
        body = notice.haystack

        division, group = _cpv_hit(notice, area)
        if division:
            score += 45.0
        if group:
            score += 15.0

        strong_title = sum(1 for kw in area.strong_keywords if kw in title)
        strong_body = sum(1 for kw in area.strong_keywords if kw in body)
        weak_body = sum(1 for kw in area.weak_keywords if kw in body)

        score += min(strong_title, 2) * 22.0
        score += min(max(strong_body - strong_title, 0), 3) * 8.0
        score += min(weak_body, 3) * 3.0

        score = min(score, 100.0)
        if score >= 30.0:
            matched.append(area.label)
        best = max(best, score)

    return round(best, 1), matched


# ---------------------------------------------------------------------------
# Lift
# ---------------------------------------------------------------------------

# Keyword -> (points, human-readable reason). Points are added to the lift score.
_ACCREDITATION_BURDENS: tuple[tuple[str, float, str], ...] = (
    ("cyber essentials plus", 6.0, "Cyber Essentials Plus required"),
    ("iso 27001", 7.0, "ISO 27001 certification required"),
    ("iso 9001", 4.0, "ISO 9001 certification required"),
    ("iso 14001", 4.0, "ISO 14001 certification required"),
    ("chas", 5.0, "CHAS accreditation required"),
    ("safecontractor", 5.0, "SafeContractor accreditation required"),
    ("constructionline", 5.0, "Constructionline registration required"),
    ("nicex", 5.0, "NICEIC registration required"),
    ("niceic", 5.0, "NICEIC registration required"),
    ("gas safe", 5.0, "Gas Safe registration required"),
    ("cqc", 9.0, "CQC registration required"),
    ("ofsted", 9.0, "Ofsted registration required"),
    ("sia licen", 5.0, "SIA licensing required"),
    ("dbs", 4.0, "DBS-checked workforce required"),
    ("enhanced dbs", 5.0, "Enhanced DBS required"),
    ("professional indemnity", 3.0, "Professional indemnity cover specified"),
    ("performance bond", 8.0, "Performance bond required"),
    ("parent company guarantee", 6.0, "Parent company guarantee required"),
)

_MOBILISATION_BURDENS: tuple[tuple[str, float, str], ...] = (
    ("tupe", 10.0, "TUPE transfer of staff"),
    ("24/7", 6.0, "24/7 cover required"),
    ("24 hours a day", 6.0, "24/7 cover required"),
    ("out of hours", 4.0, "Out-of-hours cover required"),
    ("on-site", 4.0, "On-site presence required"),
    ("on site", 3.0, "On-site presence required"),
    ("depot", 5.0, "Depot or premises required"),
    ("fleet", 5.0, "Vehicle fleet required"),
    ("plant and equipment", 5.0, "Plant and equipment required"),
    ("mobilisation", 4.0, "Explicit mobilisation phase"),
    ("novation", 4.0, "Contract novation involved"),
    ("consortium", 5.0, "Consortium or partnering expected"),
    ("prime contractor", 5.0, "Prime contractor model"),
    ("multiple sites", 4.0, "Multi-site delivery"),
    ("borough-wide", 4.0, "Area-wide delivery"),
    ("city-wide", 4.0, "Area-wide delivery"),
)


def _value_points(value: float | None) -> tuple[float, str]:
    if value is None:
        return 10.0, "Value not stated (assumed mid-range)"
    if value < 25_000:
        return 0.0, "Under £25k - light-touch procurement"
    if value < 100_000:
        return 4.0, "£25k-£100k - proportionate process"
    if value < 500_000:
        return 11.0, "£100k-£500k - full tender expected"
    if value < 2_000_000:
        return 18.0, "£500k-£2m - substantial bid effort"
    return 25.0, "Over £2m - major bid, likely incumbent-defended"


def _window_points(days: float | None) -> tuple[float, str]:
    if days is None:
        return 5.0, "No stated deadline (rolling or DPS entry)"
    if days < 7:
        return 20.0, f"Only {days:.0f} days to deadline"
    if days < 14:
        return 13.0, f"{days:.0f} days to deadline - tight"
    if days < 21:
        return 7.0, f"{days:.0f} days to deadline"
    if days < 35:
        return 3.0, f"{days:.0f} days to deadline - comfortable"
    return 0.0, f"{days:.0f} days to deadline - ample"


def _procedure_points(notice: Notice) -> tuple[float, str]:
    method = notice.procurement_method
    details = notice.procurement_method_details.lower()
    if notice.is_dps:
        return 0.0, "Dynamic purchasing system - rolling, low-cost entry"
    if "open" in method or "open" in details:
        return 4.0, "Open procedure - single-stage submission"
    if "selective" in method or "restricted" in details or "two stage" in details:
        return 12.0, "Restricted procedure - SQ then ITT"
    if "dialogue" in details or "negotiat" in details or "limited" in method:
        return 15.0, "Dialogue/negotiated - long, resource-heavy process"
    if notice.is_framework:
        return 7.0, "Framework - multi-lot submission"
    return 6.0, "Procedure not clearly stated"


def score_lift(notice: Notice, now: dt.datetime | None = None) -> tuple[float, list[str]]:
    """0-100 estimate of bid-and-deliver effort. Lower is lighter."""
    now = now or dt.datetime.now(_UTC)
    total = 0.0
    reasons: list[str] = []

    for points, reason in (
        _value_points(notice.value),
        _window_points(notice.days_to_deadline(now)),
        _procedure_points(notice),
    ):
        total += points
        reasons.append(reason)

    body, _ = _scrub_negations(notice.haystack)

    accreditation = 0.0
    for keyword, points, reason in _ACCREDITATION_BURDENS:
        if keyword in body:
            accreditation += points
            reasons.append(reason)
    total += min(accreditation, 25.0)

    mobilisation = 0.0
    for keyword, points, reason in _MOBILISATION_BURDENS:
        if keyword in body:
            mobilisation += points
            reasons.append(reason)
    total += min(mobilisation, 20.0)

    # Long contracts demand more assurance evidence up front.
    if notice.contract_start and notice.contract_end:
        months = (notice.contract_end - notice.contract_start).days / 30.44
        if months > 48:
            total += 6.0
            reasons.append(f"{months / 12:.0f}-year term - heavy assurance expected")
        elif months > 24:
            total += 3.0
            reasons.append(f"{months / 12:.0f}-year term")

    # Discounts for deliberately SME-accessible packaging.
    if notice.sme_suitable:
        total -= 8.0
        reasons.append("Flagged suitable for SMEs")
    if notice.vcse_suitable:
        total -= 3.0
        reasons.append("Flagged suitable for VCSEs")
    if notice.lot_count > 1:
        total -= 6.0
        reasons.append(f"Split into {notice.lot_count} lots - can bid one")
    if notice.is_dps:
        total -= 5.0
        reasons.append("DPS entry can be submitted once and reused")

    return round(max(0.0, min(100.0, total)), 1), reasons


# ---------------------------------------------------------------------------
# Incumbent risk - "is this already being serviced?"
# ---------------------------------------------------------------------------

_INCUMBENT_SIGNALS: tuple[tuple[str, float, str], ...] = (
    ("tupe", 35.0, "TUPE mentioned - an incumbent workforce exists"),
    ("existing provider", 25.0, "References an existing provider"),
    ("current provider", 25.0, "References a current provider"),
    ("current supplier", 25.0, "References a current supplier"),
    ("current contractor", 25.0, "References a current contractor"),
    ("incumbent", 25.0, "References an incumbent"),
    ("re-tender", 20.0, "Described as a re-tender"),
    ("retender", 20.0, "Described as a re-tender"),
    ("replacement contract", 18.0, "Replacement for an existing contract"),
    ("successor", 18.0, "Successor to an existing contract"),
    ("expiry of the current", 20.0, "Triggered by an existing contract expiring"),
    ("existing contract", 15.0, "References an existing contract"),
    ("continuation", 12.0, "Framed as a continuation"),
)

_GREENFIELD_SIGNALS: tuple[tuple[str, float, str], ...] = (
    ("new service", 20.0, "Described as a new service"),
    ("newly established", 20.0, "Newly established requirement"),
    ("first time", 18.0, "First-time requirement"),
    ("pilot", 15.0, "Pilot - no established incumbent"),
    ("proof of concept", 15.0, "Proof of concept"),
    ("newly created", 18.0, "Newly created requirement"),
)

# Phrases that explicitly negate an incumbent signal. Each is worth greenfield
# credit AND is scrubbed from the text before the positive scan, so that
# "there is no incumbent" cannot register as "references an incumbent" and
# "TUPE does not apply" cannot register as a staff transfer.
_NEGATIONS: tuple[tuple[str, float, str], ...] = (
    ("no incumbent", 25.0, "States there is no incumbent"),
    ("without an incumbent", 25.0, "States there is no incumbent"),
    ("there is no existing provider", 25.0, "States there is no existing provider"),
    ("no existing provider", 22.0, "States there is no existing provider"),
    ("no current provider", 22.0, "States there is no current provider"),
    ("no current supplier", 22.0, "States there is no current supplier"),
    ("tupe does not apply", 20.0, "Confirms TUPE does not apply"),
    ("tupe will not apply", 20.0, "Confirms TUPE does not apply"),
    ("tupe is not expected to apply", 18.0, "TUPE not expected to apply"),
    ("no tupe", 18.0, "Confirms TUPE does not apply"),
    ("not a re-tender", 18.0, "Explicitly not a re-tender"),
    ("no existing contract", 20.0, "States there is no existing contract"),
)


def _scrub_negations(body: str) -> tuple[str, list[tuple[float, str]]]:
    """Remove negated phrases from the text and report the credit they earn."""
    credits: list[tuple[float, str]] = []
    for phrase, points, reason in _NEGATIONS:
        if phrase in body:
            credits.append((points, reason))
            body = body.replace(phrase, " ")
    return body, credits

_STOPWORDS = {
    "the", "and", "for", "of", "to", "a", "in", "on", "at", "with", "services",
    "service", "contract", "supply", "provision", "council", "tender", "framework",
    "milton", "keynes", "city", "works", "new", "re", "and/or", "agreement",
}


def _title_tokens(title: str) -> set[str]:
    words = re.findall(r"[a-z0-9]{3,}", title.lower())
    return {w for w in words if w not in _STOPWORDS}


def _similar_title(a: str, b: str) -> float:
    ta, tb = _title_tokens(a), _title_tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def score_incumbent_risk(
    notice: Notice, prior_awards: list[Notice] | None = None
) -> tuple[float, list[str]]:
    """0-100. High means someone is very likely already delivering this."""
    total = 0.0
    reasons: list[str] = []
    seen: set[str] = set()

    # Negations are scrubbed first so a denial cannot read as an assertion.
    body, negation_credits = _scrub_negations(notice.haystack)
    for points, reason in negation_credits:
        if reason not in seen:
            total -= points
            reasons.append(reason)
            seen.add(reason)

    for keyword, points, reason in _INCUMBENT_SIGNALS:
        if keyword in body and reason not in seen:
            total += points
            reasons.append(reason)
            seen.add(reason)

    for keyword, points, reason in _GREENFIELD_SIGNALS:
        if keyword in body and reason not in seen:
            total -= points
            reasons.append(reason)
            seen.add(reason)

    # Cross-reference historic award notices from the same buyer.
    if prior_awards:
        buyer = notice.buyer.lower().strip()
        best_match: Notice | None = None
        best_similarity = 0.0
        for award in prior_awards:
            if not buyer or award.buyer.lower().strip() != buyer:
                continue
            similarity = _similar_title(notice.title, award.title)
            if similarity > best_similarity:
                best_similarity, best_match = similarity, award
        if best_match is not None and best_similarity >= 0.34:
            total += 30.0
            when = best_match.published.strftime("%b %Y") if best_match.published else "previously"
            reasons.append(
                f"Same buyer awarded a closely-matching contract {when}: "
                f"\"{best_match.title[:70]}\""
            )

    # A DPS or a framework being established has no single incumbent to displace.
    if notice.is_dps:
        total -= 15.0
        reasons.append("DPS - open to join, no single incumbent to displace")

    if not reasons:
        reasons.append("No incumbent signals either way in the notice text")

    return round(max(0.0, min(100.0, total)), 1), reasons


def apply_scores(
    notices: list[Notice],
    areas: list[str],
    prior_awards: list[Notice] | None = None,
    now: dt.datetime | None = None,
) -> list[Notice]:
    for notice in notices:
        notice.fit_score, notice.fit_areas = score_fit(notice, areas)
        notice.lift_score, notice.lift_reasons = score_lift(notice, now)
        notice.incumbent_risk, notice.incumbent_reasons = score_incumbent_risk(notice, prior_awards)
    return notices


def lift_band(score: float) -> str:
    if score < 20:
        return "Very light"
    if score < 35:
        return "Light"
    if score < 55:
        return "Moderate"
    if score < 75:
        return "Heavy"
    return "Very heavy"
