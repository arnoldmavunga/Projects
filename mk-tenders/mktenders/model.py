"""Normalisation of OCDS releases into a flat Notice record.

Find a Tender and Contracts Finder both publish Open Contracting Data Standard
release packages, but they populate different corners of the schema. Everything
downstream works off Notice so the differences stay in one place.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field
from typing import Any, Iterable

_UTC = dt.timezone.utc


def parse_date(value: Any) -> dt.datetime | None:
    """Parse the assorted ISO-8601 spellings the two services emit."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    # Some notices carry a fractional-second component of unusual length.
    text = re.sub(r"\.(\d{1,6})\d*", r".\1", text)
    try:
        parsed = dt.datetime.fromisoformat(text)
    except ValueError:
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
            try:
                parsed = dt.datetime.strptime(text[: len(fmt) + 2], fmt)
                break
            except ValueError:
                continue
        else:
            return None
    return parsed.replace(tzinfo=_UTC) if parsed.tzinfo is None else parsed.astimezone(_UTC)


def _amount(block: Any) -> float | None:
    if isinstance(block, dict):
        value = block.get("amount")
        if isinstance(value, (int, float)):
            return float(value)
    return None


def _text(*parts: Any) -> str:
    return " ".join(str(p) for p in parts if isinstance(p, str)).strip()


@dataclass
class Notice:
    """One procurement opportunity, flattened."""

    ocid: str
    notice_id: str
    source: str
    title: str
    description: str
    buyer: str
    stage: str                      # tender | award | planning
    status: str                     # OCDS tender.status
    url: str
    published: dt.datetime | None
    deadline: dt.datetime | None
    value: float | None
    contract_start: dt.datetime | None
    contract_end: dt.datetime | None
    cpv_codes: list[str] = field(default_factory=list)
    procurement_method: str = ""
    procurement_method_details: str = ""
    category: str = ""
    lot_count: int = 0
    sme_suitable: bool | None = None
    vcse_suitable: bool | None = None
    is_framework: bool = False
    is_dps: bool = False
    postcodes: list[str] = field(default_factory=list)
    regions: list[str] = field(default_factory=list)

    # Populated by the scoring pass.
    fit_score: float = 0.0
    fit_areas: list[str] = field(default_factory=list)
    lift_score: float = 0.0
    lift_reasons: list[str] = field(default_factory=list)
    incumbent_risk: float = 0.0
    incumbent_reasons: list[str] = field(default_factory=list)

    @property
    def haystack(self) -> str:
        """Lowercased free text used for every keyword probe."""
        return f"{self.title} {self.description} {self.procurement_method_details}".lower()

    def days_to_deadline(self, now: dt.datetime | None = None) -> float | None:
        if self.deadline is None:
            return None
        now = now or dt.datetime.now(_UTC)
        return (self.deadline - now).total_seconds() / 86400.0

    def is_open(self, now: dt.datetime | None = None) -> bool:
        """Open = a tender-stage notice whose deadline has not passed."""
        if self.stage != "tender":
            return False
        if self.status in {"complete", "cancelled", "unsuccessful", "withdrawn"}:
            return False
        remaining = self.days_to_deadline(now)
        # A tender notice with no stated deadline is kept; DPS entries often omit one.
        return True if remaining is None else remaining > 0


def _collect_addresses(release: dict, tender: dict) -> tuple[list[str], list[str]]:
    postcodes: list[str] = []
    regions: list[str] = []

    def take(address: Any) -> None:
        if not isinstance(address, dict):
            return
        code = address.get("postalCode")
        if isinstance(code, str) and code.strip():
            postcodes.append(code.strip().upper())
        for key in ("region", "countryName", "locality", "streetAddress"):
            val = address.get(key)
            if isinstance(val, str) and val.strip():
                regions.append(val.strip())

    for party in release.get("parties") or []:
        if isinstance(party, dict):
            take(party.get("address"))
    take((release.get("buyer") or {}).get("address"))
    for item in tender.get("items") or []:
        if isinstance(item, dict):
            take(item.get("deliveryAddress"))
            for addr in item.get("deliveryAddresses") or []:
                take(addr)
    for location in tender.get("deliveryLocations") or []:
        if isinstance(location, dict):
            take(location.get("address"))
            desc = location.get("description")
            if isinstance(desc, str):
                regions.append(desc)
    return postcodes, regions


def _collect_cpv(tender: dict) -> list[str]:
    codes: list[str] = []

    def take(block: Any) -> None:
        if not isinstance(block, dict):
            return
        scheme = str(block.get("scheme") or "").upper()
        code = block.get("id")
        if isinstance(code, (str, int)) and ("CPV" in scheme or not scheme):
            codes.append(str(code).strip())

    take(tender.get("classification"))
    for block in tender.get("additionalClassifications") or []:
        take(block)
    for item in tender.get("items") or []:
        if isinstance(item, dict):
            take(item.get("classification"))
            for block in item.get("additionalClassifications") or []:
                take(block)
    for lot in tender.get("lots") or []:
        if isinstance(lot, dict):
            take(lot.get("classification"))
    # Preserve order, drop duplicates.
    return list(dict.fromkeys(c for c in codes if c))


def _stage_of(release: dict) -> str:
    tags = [str(t).lower() for t in (release.get("tag") or [])]
    if release.get("awards") or any("award" in t for t in tags):
        return "award"
    if any("contract" in t for t in tags) and release.get("contracts"):
        return "award"
    if any("planning" in t for t in tags) or release.get("planning"):
        return "planning"
    return "tender"


def notice_from_release(release: dict, source: str) -> Notice | None:
    """Build a Notice from one OCDS release. Returns None if unusable."""
    if not isinstance(release, dict):
        return None
    tender = release.get("tender") if isinstance(release.get("tender"), dict) else {}
    title = _text(tender.get("title"), release.get("title")) or "(untitled)"

    buyer = ""
    buyer_block = release.get("buyer")
    if isinstance(buyer_block, dict):
        buyer = str(buyer_block.get("name") or "")
    if not buyer:
        for party in release.get("parties") or []:
            if isinstance(party, dict) and "buyer" in [str(r).lower() for r in party.get("roles") or []]:
                buyer = str(party.get("name") or "")
                break

    url = ""
    for doc in tender.get("documents") or []:
        if isinstance(doc, dict) and doc.get("url"):
            url = str(doc["url"])
            break

    method_details = str(tender.get("procurementMethodDetails") or "")
    techniques = tender.get("techniques") if isinstance(tender.get("techniques"), dict) else {}
    blob = f"{title} {tender.get('description') or ''} {method_details}".lower()

    is_framework = bool(techniques.get("hasFrameworkAgreement")) or "framework" in blob
    is_dps = (
        bool(techniques.get("hasDynamicPurchasingSystem"))
        or "dynamic purchasing" in blob
        or " dps" in f" {blob}"
    )

    suitability = tender.get("suitability") if isinstance(tender.get("suitability"), dict) else {}
    postcodes, regions = _collect_addresses(release, tender)

    value = _amount(tender.get("value")) or _amount(tender.get("minValue"))
    if value is None:
        awards = release.get("awards") or []
        if awards and isinstance(awards[0], dict):
            value = _amount(awards[0].get("value"))

    tender_period = tender.get("tenderPeriod") if isinstance(tender.get("tenderPeriod"), dict) else {}
    contract_period = tender.get("contractPeriod") if isinstance(tender.get("contractPeriod"), dict) else {}

    return Notice(
        ocid=str(release.get("ocid") or ""),
        notice_id=str(release.get("id") or tender.get("id") or ""),
        source=source,
        title=title,
        description=str(tender.get("description") or release.get("description") or ""),
        buyer=buyer,
        stage=_stage_of(release),
        status=str(tender.get("status") or "").lower(),
        url=url,
        published=parse_date(release.get("date")),
        deadline=parse_date(tender_period.get("endDate")),
        value=value,
        contract_start=parse_date(contract_period.get("startDate")),
        contract_end=parse_date(contract_period.get("endDate")),
        cpv_codes=_collect_cpv(tender),
        procurement_method=str(tender.get("procurementMethod") or "").lower(),
        procurement_method_details=method_details,
        category=str(tender.get("mainProcurementCategory") or ""),
        lot_count=len(tender.get("lots") or []),
        sme_suitable=suitability.get("sme") if isinstance(suitability.get("sme"), bool) else None,
        vcse_suitable=suitability.get("vcse") if isinstance(suitability.get("vcse"), bool) else None,
        is_framework=is_framework,
        is_dps=is_dps,
        postcodes=postcodes,
        regions=regions,
    )


def notices_from_packages(packages: Iterable[dict], source: str) -> list[Notice]:
    out: list[Notice] = []
    for package in packages:
        for release in (package or {}).get("releases") or []:
            notice = notice_from_release(release, source)
            if notice is not None:
                out.append(notice)
    return out
