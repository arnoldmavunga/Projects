"""Deciding which notices count as 'Milton Keynes' opportunities.

A notice qualifies on any one of: a known MK-area buyer, an MK postcode,
or a place name from the MK travel-to-work area in the free text.
"""

from __future__ import annotations

import re

from .model import Notice

# Public bodies that buy for delivery in or around Milton Keynes. Matched as
# case-insensitive substrings against the OCDS buyer name.
MK_BUYERS = (
    "milton keynes",
    "open university",
    "cranfield university",
    "milton keynes university hospital",
    "thames valley police",
    "buckinghamshire fire",
    "buckinghamshire council",
    "central bedfordshire council",
    "bedford borough council",
    "mk college",
    "milton keynes college",
    "south east midlands",
    "england's economic heartland",
    "bletchley",
    "wolverton",
    "newport pagnell",
    "olney town council",
    "woburn sands",
    "stony stratford",
)

# Settlements inside or adjoining the MK urban area, for free-text matching.
MK_PLACES = (
    "milton keynes",
    "bletchley",
    "wolverton",
    "stony stratford",
    "newport pagnell",
    "woburn sands",
    "olney",
    "walnut tree",
    "westcroft",
    "kingston",
    "shenley",
    "furzton",
    "broughton",
    "campbell park",
    "central milton keynes",
)

_MK_POSTCODE = re.compile(r"\bMK\d{1,2}\b", re.IGNORECASE)

# Neighbouring-authority names that on their own are too broad to imply MK
# delivery; they need a postcode or place name as corroboration.
_WIDE_AREA_BUYERS = (
    "thames valley police",
    "buckinghamshire council",
    "buckinghamshire fire",
    "central bedfordshire council",
    "bedford borough council",
    "cranfield university",
    "south east midlands",
    "england's economic heartland",
)


def _mentions_place(text: str) -> bool:
    lowered = text.lower()
    return any(place in lowered for place in MK_PLACES)


def _has_mk_postcode(notice: Notice) -> bool:
    if any(_MK_POSTCODE.match(pc.replace(" ", "")) for pc in notice.postcodes):
        return True
    return bool(_MK_POSTCODE.search(" ".join(notice.regions)))


def milton_keynes_relevance(notice: Notice) -> tuple[bool, str]:
    """Return (is_relevant, reason)."""
    buyer = notice.buyer.lower()
    text = f"{notice.title} {notice.description} {' '.join(notice.regions)}"

    postcode_hit = _has_mk_postcode(notice)
    place_hit = _mentions_place(text)

    matched_buyer = next((b for b in MK_BUYERS if b in buyer), None)
    if matched_buyer:
        if matched_buyer in _WIDE_AREA_BUYERS:
            # A county-wide or regional buyer only counts with local corroboration.
            if postcode_hit:
                return True, f"regional buyer ({matched_buyer}) with MK postcode"
            if place_hit:
                return True, f"regional buyer ({matched_buyer}) naming an MK location"
            return False, ""
        return True, f"MK-area buyer ({matched_buyer})"

    if postcode_hit:
        return True, "MK postcode in delivery or buyer address"
    if place_hit:
        return True, "MK location named in the notice text"
    return False, ""


def filter_milton_keynes(notices: list[Notice]) -> list[Notice]:
    return [n for n in notices if milton_keynes_relevance(n)[0]]
