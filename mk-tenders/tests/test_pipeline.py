"""End-to-end checks on the filter, scoring and ranking logic.

Run: python -m pytest tests -q     (or: python tests/test_pipeline.py)
"""

from __future__ import annotations

import pathlib
import sys
import datetime as dt
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from mktenders.filters import filter_milton_keynes, milton_keynes_relevance
from mktenders.model import notices_from_packages, parse_date
from mktenders.report import rank
from mktenders.scoring import apply_scores, lift_band, score_fit
from mktenders import sources
from mktenders.sources import load_local

FIXTURES = pathlib.Path(__file__).parent / "fixtures"
AREAS = ["it", "professional", "facilities"]


def load(name: str):
    return notices_from_packages(load_local([str(FIXTURES / name)]), "test")


def pipeline():
    tenders = filter_milton_keynes(load("tenders.json"))
    awards = filter_milton_keynes(load("awards.json"))
    open_only = [n for n in tenders if n.is_open()]
    apply_scores(open_only, AREAS, prior_awards=awards)
    return open_only, rank(open_only, min_fit=35.0)


def by_title(notices, fragment):
    hits = [n for n in notices if fragment.lower() in n.title.lower()]
    assert hits, f"no notice matching {fragment!r}"
    return hits[0]


# --- parsing ---------------------------------------------------------------

def test_date_parsing_variants():
    assert parse_date("2026-09-30T12:00:00Z") is not None
    assert parse_date("2026-09-30") is not None
    assert parse_date("2026-09-30T12:00:00.123456789Z") is not None
    assert parse_date("") is None
    assert parse_date(None) is None


def test_releases_normalise():
    notices = load("tenders.json")
    assert len(notices) == 11
    site = by_title(notices, "Website Accessibility Audit")
    assert site.buyer == "Milton Keynes City Council"
    assert site.value == 38000
    assert "72420000" in site.cpv_codes
    assert site.sme_suitable is True


# --- geography -------------------------------------------------------------

def test_geography_keeps_mk_and_drops_others():
    kept = {n.title for n in filter_milton_keynes(load("tenders.json"))}
    assert "Website Accessibility Audit and Remediation Plan" in kept
    assert "Website Redesign and Content Migration" not in kept, "Sunderland must be excluded"


def test_regional_buyer_needs_local_corroboration():
    cctv = by_title(load("tenders.json"), "Public Space CCTV")
    relevant, reason = milton_keynes_relevance(cctv)
    assert relevant, "TVP notice names Milton Keynes so should qualify"
    assert "regional buyer" in reason


def test_nhs_trust_in_mk_qualifies():
    training = by_title(load("tenders.json"), "Staff Training Programme")
    assert milton_keynes_relevance(training)[0]


# --- open / closed ---------------------------------------------------------

def test_closed_notice_excluded():
    open_only, _ = pipeline()
    assert not any("Data Migration Support" in n.title for n in open_only), \
        "a past deadline must be filtered out"


def test_dps_without_deadline_stays_open():
    open_only, _ = pipeline()
    assert any("Dynamic Purchasing System" in n.title for n in open_only)


# --- fit -------------------------------------------------------------------

def test_care_contract_scores_low_on_chosen_areas():
    care = by_title(load("tenders.json"), "Supported Living")
    score, _ = score_fit(care, AREAS)
    assert score < 35, f"care work should not be suitable, got {score}"


def test_care_contract_scores_high_when_care_selected():
    care = by_title(load("tenders.json"), "Supported Living")
    score, areas = score_fit(care, ["care"])
    assert score >= 60 and areas


def test_digital_notice_matches_it_area():
    site = by_title(load("tenders.json"), "Website Accessibility Audit")
    score, areas = score_fit(site, AREAS)
    assert score >= 60
    assert "IT, digital & data" in areas


# --- lift ------------------------------------------------------------------

def test_small_new_digital_job_is_lighter_than_major_fm_relet():
    open_only, _ = pipeline()
    site = by_title(open_only, "Website Accessibility Audit")
    fm = by_title(open_only, "Integrated Facilities Management")
    assert site.lift_score < fm.lift_score
    assert site.lift_score < 25, f"expected a very light score, got {site.lift_score}"
    assert fm.lift_score > 70, f"expected a very heavy score, got {fm.lift_score}"


def test_lift_reasons_are_populated_and_specific():
    open_only, _ = pipeline()
    fm = by_title(open_only, "Integrated Facilities Management")
    joined = " ".join(fm.lift_reasons).lower()
    assert "tupe" in joined
    assert "performance bond" in joined
    assert "restricted" in joined


def test_lot_split_and_sme_flag_reduce_lift():
    open_only, _ = pipeline()
    grounds = by_title(open_only, "Grounds Maintenance")
    joined = " ".join(grounds.lift_reasons).lower()
    assert "lots" in joined and "sme" in joined


def test_lift_band_boundaries():
    assert lift_band(10) == "Very light"
    assert lift_band(30) == "Light"
    assert lift_band(50) == "Moderate"
    assert lift_band(60) == "Heavy"
    assert lift_band(90) == "Very heavy"


def test_scores_stay_in_range():
    open_only, _ = pipeline()
    for notice in open_only:
        assert 0 <= notice.lift_score <= 100
        assert 0 <= notice.fit_score <= 100
        assert 0 <= notice.incumbent_risk <= 100


# --- incumbent risk --------------------------------------------------------

def test_tupe_relet_flagged_as_serviced():
    open_only, _ = pipeline()
    fm = by_title(open_only, "Integrated Facilities Management")
    assert fm.incumbent_risk >= 80, f"got {fm.incumbent_risk}"
    joined = " ".join(fm.incumbent_reasons).lower()
    assert "tupe" in joined


def test_prior_award_lifts_incumbent_risk():
    open_only, _ = pipeline()
    grounds = by_title(open_only, "Grounds Maintenance")
    joined = " ".join(grounds.incumbent_reasons).lower()
    assert "awarded a closely-matching contract" in joined, \
        "the historic grounds maintenance award should be matched"


def test_new_service_reads_as_unserviced():
    open_only, _ = pipeline()
    site = by_title(open_only, "Website Accessibility Audit")
    assert site.incumbent_risk <= 10, f"got {site.incumbent_risk}"


def test_dps_discounted_for_incumbency():
    open_only, _ = pipeline()
    dps = by_title(open_only, "Dynamic Purchasing System")
    assert dps.incumbent_risk == 0


def test_negated_incumbent_phrase_is_not_a_positive_signal():
    """'There is no incumbent' must not read as 'references an incumbent'."""
    open_only, _ = pipeline()
    site = by_title(open_only, "Website Accessibility Audit")
    joined = " ".join(site.incumbent_reasons).lower()
    assert "references an incumbent" not in joined
    assert "no incumbent" in joined
    assert site.incumbent_risk == 0


def test_tupe_denial_adds_no_incumbent_risk_or_lift():
    from mktenders.model import notice_from_release
    from mktenders.scoring import score_incumbent_risk, score_lift

    def build(description):
        return notice_from_release(
            {
                "ocid": "x", "id": "x-1", "date": "2026-08-01T00:00:00Z", "tag": ["tender"],
                "buyer": {"name": "Milton Keynes City Council"},
                "tender": {
                    "title": "Cleaning Services", "description": description,
                    "status": "active", "value": {"amount": 50000, "currency": "GBP"},
                    "tenderPeriod": {"endDate": "2099-01-01T00:00:00Z"},
                },
            },
            "test",
        )

    denied = build("A new requirement. TUPE does not apply to this contract.")
    applies = build("TUPE applies to this contract.")

    denied_risk, denied_reasons = score_incumbent_risk(denied)
    applies_risk, _ = score_incumbent_risk(applies)
    assert denied_risk < applies_risk
    assert "tupe mentioned" not in " ".join(denied_reasons).lower()

    denied_lift, denied_lift_reasons = score_lift(denied)
    applies_lift, _ = score_lift(applies)
    assert denied_lift < applies_lift, "a TUPE denial must not add mobilisation burden"
    assert "tupe" not in " ".join(denied_lift_reasons).lower()


def test_links_resolve_for_every_notice():
    from mktenders.links import notice_url, portal

    open_only, _ = pipeline()
    for notice in open_only:
        url = notice_url(notice)
        assert url.startswith("https://"), f"{notice.title} has no usable link"

    mkcc = by_title(open_only, "Website Accessibility Audit")
    found = portal(mkcc)
    assert found is not None, "MKCC notices should point at the In-Tend portal"
    assert "in-tendhost.co.uk/milton-keynes" in found[1]


def test_contracts_finder_guid_builds_a_canonical_url():
    from mktenders.links import notice_url
    from mktenders.model import Notice

    notice = Notice(
        ocid="ocds-b5fd17-0d7d0d3a-1f4c-4d2e-9b3a-3f9a1c2b4d5e",
        notice_id="0d7d0d3a-1f4c-4d2e-9b3a-3f9a1c2b4d5e",
        source="contracts-finder", title="Test", description="", buyer="",
        stage="tender", status="active", url="", published=None, deadline=None,
        value=None, contract_start=None, contract_end=None,
    )
    assert notice_url(notice) == (
        "https://www.contractsfinder.service.gov.uk/Notice/"
        "0d7d0d3a-1f4c-4d2e-9b3a-3f9a1c2b4d5e"
    )


def test_find_a_tender_reference_builds_a_canonical_url():
    from mktenders.links import notice_url
    from mktenders.model import Notice

    notice = Notice(
        ocid="ocds-h6vhtk-013350-2026", notice_id="013350-2026",
        source="find-a-tender", title="Test", description="", buyer="",
        stage="tender", status="active", url="", published=None, deadline=None,
        value=None, contract_start=None, contract_end=None,
    )
    assert notice_url(notice) == "https://www.find-tender.service.gov.uk/Notice/013350-2026"


def test_link_falls_back_to_a_search_url():
    from mktenders.links import notice_url
    from mktenders.model import Notice

    notice = Notice(
        ocid="unknown", notice_id="", source="find-a-tender",
        title="Grounds Maintenance Lot 2", description="", buyer="",
        stage="tender", status="active", url="", published=None, deadline=None,
        value=None, contract_start=None, contract_end=None,
    )
    url = notice_url(notice)
    assert url.startswith("https://www.find-tender.service.gov.uk/Search/Results?keywords=")
    assert "Grounds+Maintenance" in url


# --- ranking ---------------------------------------------------------------

def test_ranking_is_lightest_first_and_excludes_unsuitable():
    _, ranked = pipeline()
    scores = [n.lift_score for n in ranked]
    assert scores == sorted(scores), "ranking must ascend by lift"
    assert not any("Supported Living" in n.title for n in ranked), \
        "care work is outside the selected areas"
    assert ranked, "expected at least one suitable opportunity"


def test_top_ranked_is_a_light_unserviced_fit():
    _, ranked = pipeline()
    top = ranked[0]
    assert top.lift_score < 30
    assert top.fit_score >= 35
    assert top.incumbent_risk < 40


def test_award_history_walks_backwards_from_now():
    """Recent awards must be fetched first - they are what prove a live incumbent.

    A single long query pages chronologically from the window start, so it
    burns its page budget in the oldest year and never reaches today.
    """
    seen: list[tuple[str, str]] = []

    def fake_fetch(start, end, stages="award", max_pages=4, verbose=False, deadline=None):
        seen.append((start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")))
        return []

    now = dt.datetime(2026, 9, 4, tzinfo=dt.timezone.utc)
    since = now - dt.timedelta(days=365 * 2)
    sources.fetch_award_history(fake_fetch, since, now, chunk_days=180)

    assert len(seen) >= 4, f"expected several windows, got {seen}"
    ends = [end for _, end in seen]
    assert ends == sorted(ends, reverse=True), f"windows not newest-first: {seen}"
    assert ends[0] == "2026-09-04", f"first window should end today, got {ends[0]}"
    assert seen[-1][0] == since.strftime("%Y-%m-%d"), "last window should reach the look-back start"


def test_award_history_stops_at_its_time_budget():
    """A slow service must not hold up the whole build."""
    calls = {"n": 0}

    def slow_fetch(start, end, stages="award", max_pages=4, verbose=False, deadline=None):
        calls["n"] += 1
        time.sleep(0.05)
        return []

    now = dt.datetime(2026, 9, 4, tzinfo=dt.timezone.utc)
    since = now - dt.timedelta(days=365 * 20)
    sources.fetch_award_history(slow_fetch, since, now, chunk_days=30, time_budget=0.15)

    assert calls["n"] < 20, f"time budget ignored: {calls['n']} calls"


def _notice(title: str, buyer: str, description: str = "") -> "Notice":
    """Build a single Notice through the real OCDS parser."""
    package = {
        "releases": [
            {
                "ocid": "ocds-test-0001",
                "date": "2026-09-01T00:00:00Z",
                "tag": ["tender"],
                "buyer": {"name": buyer},
                "tender": {
                    "id": "T-0001",
                    "title": title,
                    "description": description,
                    "status": "active",
                    "tenderPeriod": {"endDate": "2026-12-01T00:00:00Z"},
                },
            }
        ]
    }
    return notices_from_packages([package], "test")[0]


def test_kingston_upon_thames_is_not_milton_keynes():
    """The first live run ranked a Kingston upon Thames crematorium top.

    "Kingston" is a Milton Keynes district, but as a bare substring it also
    matches Kingston upon Thames and Kingston upon Hull.
    """
    notice = _notice(
        title="Kingston Crematorium",
        buyer="Royal Borough of Kingston upon Thames",
        description="Operation of the crematorium.",
    )
    relevant, reason = milton_keynes_relevance(notice)
    assert not relevant, f"Kingston upon Thames wrongly matched: {reason}"


def test_ambiguous_district_counts_with_mk_corroboration():
    """The same word does qualify when something pins it to Milton Keynes."""
    notice = _notice(
        title="Kingston district centre resurfacing",
        buyer="Milton Keynes City Council",
        description="Works at Kingston, Milton Keynes.",
    )
    assert milton_keynes_relevance(notice)[0]


def test_rate_limited_response_waits_before_retrying():
    """A 429 must back off properly, not hammer straight through the retries."""
    import urllib.error

    err = urllib.error.HTTPError(
        "https://example.test", 429, "Too Many Requests",
        {"Retry-After": "7"}, None,
    )
    assert sources._retry_after_seconds(err, 2.0) == 7.0

    no_header = urllib.error.HTTPError(
        "https://example.test", 429, "Too Many Requests", {}, None,
    )
    assert no_header.headers.get("Retry-After") is None
    assert sources._retry_after_seconds(no_header, 5.0) == 5.0

def test_award_budget_reaches_the_page_loop():
    """A chunk that keeps hitting backoff must not overrun the whole budget.

    The budget was previously only checked between chunks, so a single slow
    chunk could run for minutes after the budget had already expired.
    """
    seen_deadlines = []

    def fetch(start, end, stages="award", max_pages=3, verbose=False, deadline=None):
        seen_deadlines.append(deadline)
        return []

    now = dt.datetime(2026, 9, 4, tzinfo=dt.timezone.utc)
    sources.fetch_award_history(fetch, now - dt.timedelta(days=730), now, time_budget=30.0)

    assert seen_deadlines, "no fetches were made"
    assert all(d is not None for d in seen_deadlines), "deadline not passed to the fetcher"
    assert len(set(seen_deadlines)) == 1, "every chunk should share one budget deadline"


def test_pagination_stops_at_the_deadline():
    """_paginate must check the clock before asking for another page."""
    pages = list(sources._paginate(
        "https://example.test/first", max_pages=5, label="test",
        verbose=False, deadline=time.monotonic() - 1,
    ))
    assert pages == [], "an expired deadline should yield no pages and make no request"


if __name__ == "__main__":
    failures = 0
    tests = [(name, obj) for name, obj in sorted(globals().items())
             if name.startswith("test_") and callable(obj)]
    for name, fn in tests:
        try:
            fn()
            print(f"  PASS  {name}")
        except AssertionError as exc:
            failures += 1
            print(f"  FAIL  {name}: {exc}")
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"  ERROR {name}: {type(exc).__name__}: {exc}")
    print(f"\n{len(tests) - failures}/{len(tests)} passed")
    raise SystemExit(1 if failures else 0)
