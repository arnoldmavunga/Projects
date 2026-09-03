"""Clickable links for each notice.

Two different things are useful, and they are not the same link:

  notice_url   the published notice on Find a Tender or Contracts Finder -
               what the requirement is, and the closing date.
  portal_url   the buyer's own e-tendering system - where you actually
               register, express interest and submit. For Milton Keynes City
               Council that is In-Tend, not the GOV.UK notice page.

Where an OCID does not yield a canonical notice URL we fall back to a keyword
search on the relevant service, which always resolves to something useful.
"""

from __future__ import annotations

import re
import urllib.parse

from .model import Notice

FTS_NOTICE = "https://www.find-tender.service.gov.uk/Notice/{ref}"
FTS_SEARCH = "https://www.find-tender.service.gov.uk/Search/Results?keywords={q}"
CF_NOTICE = "https://www.contractsfinder.service.gov.uk/Notice/{ref}"
CF_SEARCH = "https://www.contractsfinder.service.gov.uk/Search/Results?keywords={q}"

# Milton Keynes City Council advertises everything over £25k on In-Tend, and
# expression of interest happens there rather than on the GOV.UK notice.
MK_INTEND = "https://in-tendhost.co.uk/milton-keynes/aspx/Tenders/Current"
MK_INTEND_HOME = "https://in-tendhost.co.uk/milton-keynes"
MK_PROCUREMENT_PAGE = "https://www.milton-keynes.gov.uk/business/tenders-and-contracts"

# Buyer name fragment -> (portal label, portal url). Kept deliberately small;
# only buyers whose portal is known are mapped, rather than guessed.
BUYER_PORTALS: tuple[tuple[str, str, str], ...] = (
    ("milton keynes city council", "MK City Council - In-Tend", MK_INTEND),
    ("milton keynes council", "MK City Council - In-Tend", MK_INTEND),
    (
        "thames valley police",
        "Thames Valley Police procurement",
        "https://www.thamesvalley.police.uk/police-forces/thames-valley-police/areas/au/"
        "about-us/our-people/departments-and-teams/procurement/",
    ),
    (
        "thames valley",
        "Thames Valley PCC contracts and tenders",
        "https://www.thamesvalley-pcc.gov.uk/our-information/finances/contracts-and-tenders/",
    ),
)

_FTS_REF = re.compile(r"\b\d{6}-\d{4}\b")
_GUID = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.IGNORECASE
)


def _quote(text: str) -> str:
    return urllib.parse.quote_plus(" ".join(text.split())[:120])


def notice_url(notice: Notice) -> str:
    """Best available link to the published notice."""
    # A URL carried in the notice documents is always the most reliable.
    if notice.url.startswith("http"):
        return notice.url

    identifiers = f"{notice.ocid} {notice.notice_id}"

    guid = _GUID.search(identifiers)
    if guid and ("b5fd17" in notice.ocid or notice.source == "contracts-finder"):
        return CF_NOTICE.format(ref=guid.group(0))

    ref = _FTS_REF.search(identifiers)
    if ref and ("h6vhtk" in notice.ocid or notice.source == "find-a-tender"):
        return FTS_NOTICE.format(ref=ref.group(0))

    if guid:
        return CF_NOTICE.format(ref=guid.group(0))
    if ref:
        return FTS_NOTICE.format(ref=ref.group(0))

    template = CF_SEARCH if notice.source == "contracts-finder" else FTS_SEARCH
    return template.format(q=_quote(notice.title))


def portal(notice: Notice) -> tuple[str, str] | None:
    """(label, url) for the buyer's own e-tendering portal, when known."""
    buyer = notice.buyer.lower()
    for fragment, label, url in BUYER_PORTALS:
        if fragment in buyer:
            return label, url
    return None


def all_links(notice: Notice) -> dict[str, str]:
    links = {"notice": notice_url(notice)}
    found = portal(notice)
    if found:
        links["portal_label"], links["portal"] = found
    return links
