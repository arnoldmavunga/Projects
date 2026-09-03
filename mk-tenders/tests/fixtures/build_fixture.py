"""Generate an OCDS fixture with deadlines relative to today.

Shapes mirror real Find a Tender / Contracts Finder releases: a light digital
package, a light advisory piece, a mid-weight works lot, a heavy re-let with
TUPE, a care contract that should fall outside the chosen capability areas,
and a non-MK notice that the geography filter must reject.
"""

import datetime as dt
import json
import pathlib

UTC = dt.timezone.utc
NOW = dt.datetime.now(UTC)


def days(n: int) -> str:
    return (NOW + dt.timedelta(days=n)).strftime("%Y-%m-%dT%H:%M:%SZ")


def ago(n: int) -> str:
    return (NOW - dt.timedelta(days=n)).strftime("%Y-%m-%dT%H:%M:%SZ")


def release(ocid, title, description, buyer, cpv, value, deadline, **kw):
    tender = {
        "id": ocid,
        "title": title,
        "description": description,
        "status": kw.get("status", "active"),
        "value": {"amount": value, "currency": "GBP"} if value is not None else None,
        "procurementMethod": kw.get("method", "open"),
        "procurementMethodDetails": kw.get("method_details", "Open procedure"),
        "mainProcurementCategory": kw.get("category", "services"),
        "tenderPeriod": {"endDate": deadline} if deadline else {},
        "items": [
            {
                "id": "1",
                "classification": {"scheme": "CPV", "id": cpv, "description": title},
                "deliveryAddress": kw.get("address", {"postalCode": "MK9 3EJ",
                                                      "region": "Milton Keynes"}),
            }
        ],
        "suitability": {"sme": kw.get("sme"), "vcse": kw.get("vcse")},
        "documents": [{"id": "d1", "url": f"https://example.gov.uk/notice/{ocid}"}],
    }
    if kw.get("lots"):
        tender["lots"] = [{"id": str(i)} for i in range(kw["lots"])]
    if kw.get("contract_period"):
        tender["contractPeriod"] = kw["contract_period"]
    if kw.get("techniques"):
        tender["techniques"] = kw["techniques"]
    tender = {k: v for k, v in tender.items() if v is not None}

    rel = {
        "ocid": ocid,
        "id": f"{ocid}-1",
        "date": kw.get("published", ago(5)),
        "tag": kw.get("tag", ["tender"]),
        "buyer": {"name": buyer},
        "parties": [{"name": buyer, "roles": ["buyer"],
                     "address": kw.get("buyer_address", {"postalCode": "MK9 3EJ",
                                                         "region": "Milton Keynes"})}],
        "tender": tender,
    }
    if kw.get("awards"):
        rel["awards"] = kw["awards"]
    return rel


TENDERS = [
    release(
        "ocds-mk-0001",
        "Website Accessibility Audit and Remediation Plan",
        "Milton Keynes City Council requires an accessibility audit of its public "
        "website against WCAG 2.2 AA, with a prioritised remediation plan. This is a "
        "new service; there is no incumbent. Suitable for SMEs.",
        "Milton Keynes City Council",
        "72420000", 38000, days(31), sme=True,
    ),
    release(
        "ocds-mk-0002",
        "Dynamic Purchasing System for Digital and Data Consultancy",
        "Establishment of a dynamic purchasing system (DPS) for digital, data and "
        "technology consultancy. Suppliers may apply to join at any time.",
        "Milton Keynes City Council",
        "72000000", 4000000, None,
        method_details="Dynamic purchasing system",
        techniques={"hasDynamicPurchasingSystem": True}, sme=True, lots=4,
    ),
    release(
        "ocds-mk-0003",
        "Feasibility Study - Estate Decarbonisation Options Appraisal",
        "Consultancy support to produce an options appraisal and business case for "
        "decarbonising the council's operational estate. Professional indemnity "
        "insurance required.",
        "Milton Keynes City Council",
        "79314000", 72000, days(24), sme=True,
    ),
    release(
        "ocds-mk-0004",
        "Planned Painting and Decorating Programme - Wolverton",
        "Cyclical external painting and decorating to council housing stock in "
        "Wolverton. CHAS accreditation and Constructionline registration required. "
        "Contractor must hold plant and equipment and operate from a local depot.",
        "Milton Keynes City Council",
        "45442100", 850000, days(19),
        contract_period={"startDate": days(90), "endDate": days(90 + 365 * 4)},
    ),
    release(
        "ocds-mk-0005",
        "Integrated Facilities Management Services - Corporate Estate",
        "Re-tender of the council's integrated facilities management contract "
        "following expiry of the current agreement. TUPE will apply. 24/7 cover "
        "across multiple sites. ISO 9001, ISO 14001 and CHAS required. A "
        "performance bond will be required.",
        "Milton Keynes City Council",
        "79993100", 24000000, days(9),
        method_details="Restricted procedure - two stage",
        method="selective",
        contract_period={"startDate": days(180), "endDate": days(180 + 365 * 7)},
    ),
    release(
        "ocds-mk-0006",
        "Supported Living Services for Adults with Learning Disabilities",
        "Provision of supported living and domiciliary care. CQC registration and "
        "enhanced DBS required. TUPE applies from the existing provider.",
        "Milton Keynes City Council",
        "85310000", 6500000, days(28),
    ),
    release(
        "ocds-mk-0007",
        "Grounds Maintenance - Parish Verges Lot 2",
        "Grass cutting and grounds maintenance across parish verges. Split into "
        "lots; bidders may bid for one or more lots.",
        "Milton Keynes City Council",
        "77310000", 145000, days(27), lots=3, sme=True,
    ),
    release(
        "ocds-mk-0008",
        "Staff Training Programme - Data Protection and Records Management",
        "Delivery of a training programme on data protection and records management "
        "for approximately 200 staff. New requirement.",
        "Milton Keynes University Hospital NHS Foundation Trust",
        "80500000", 26000, days(45), sme=True,
        buyer_address={"postalCode": "MK6 5LD", "region": "Milton Keynes"},
        address={"postalCode": "MK6 5LD", "region": "Milton Keynes"},
    ),
    release(
        "ocds-mk-0009",
        "Public Space CCTV Replacement Programme",
        "Replacement of the public space CCTV estate across Milton Keynes and "
        "Slough. Migration of legacy equipment to a full IP based system. "
        "ISO 27001 and Cyber Essentials Plus required.",
        "Thames Valley Police",
        "35125300", 9500000, days(38),
        method_details="Competitive dialogue",
        buyer_address={"postalCode": "RG2 0GB", "region": "Reading"},
    ),
    # Must be rejected by the geography filter.
    release(
        "ocds-other-001",
        "Website Redesign and Content Migration",
        "Redesign of the council's public website. Suitable for SMEs.",
        "Sunderland City Council",
        "72420000", 40000, days(30), sme=True,
        buyer_address={"postalCode": "SR2 7DN", "region": "Sunderland"},
        address={"postalCode": "SR2 7DN", "region": "Sunderland"},
    ),
    # Must be rejected as closed.
    release(
        "ocds-mk-0010",
        "Data Migration Support for Revenues and Benefits",
        "Short data migration engagement. New requirement.",
        "Milton Keynes City Council",
        "72330000", 30000, days(-4), sme=True,
    ),
]

AWARDS = [
    release(
        "ocds-mk-hist-01",
        "Integrated Facilities Management Services Corporate Estate",
        "Award of the integrated facilities management contract.",
        "Milton Keynes City Council",
        "79993100", 21000000, None,
        tag=["award"], published=ago(365 * 5),
        awards=[{"id": "a1", "status": "active",
                 "value": {"amount": 21000000, "currency": "GBP"},
                 "suppliers": [{"name": "Incumbent FM Ltd"}]}],
    ),
    release(
        "ocds-mk-hist-02",
        "Grounds Maintenance Parish Verges",
        "Award of grounds maintenance contract.",
        "Milton Keynes City Council",
        "77310000", 400000, None,
        tag=["award"], published=ago(365 * 4),
        awards=[{"id": "a2", "status": "active",
                 "value": {"amount": 400000, "currency": "GBP"},
                 "suppliers": [{"name": "Green Verges Ltd"}]}],
    ),
]

if __name__ == "__main__":
    out = pathlib.Path(__file__).parent
    (out / "tenders.json").write_text(json.dumps({"releases": TENDERS}, indent=2))
    (out / "awards.json").write_text(json.dumps({"releases": AWARDS}, indent=2))
    print(f"wrote {len(TENDERS)} tender and {len(AWARDS)} award releases")
