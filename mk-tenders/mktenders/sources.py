"""HTTP clients for the two official UK notice services.

Both publish OCDS release packages over an open, unauthenticated API:

  Find a Tender      https://www.find-tender.service.gov.uk/apidocumentation/1.0/GET-ocdsReleasePackages
  Contracts Finder   https://www.contractsfinder.service.gov.uk/apidocumentation

Find a Tender carries above-threshold notices; Contracts Finder carries
below-threshold ones (including the £25k-£214k band where most genuinely
light-lift council work sits). Query both.

Only the standard library is used, so this runs anywhere Python 3.10+ does.
urllib honours HTTPS_PROXY and SSL_CERT_FILE from the environment.
"""

from __future__ import annotations

import datetime as dt
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable, Iterator

_UTC = dt.timezone.utc

FTS_BASE = "https://www.find-tender.service.gov.uk/api/1.0/ocdsReleasePackages"
CF_BASE = "https://www.contractsfinder.service.gov.uk/Published/Notices/OCDS/Search"

USER_AGENT = "mk-tenders/1.0 (+public procurement analysis; stdlib urllib)"
MAX_RETRIES = 4
PAGE_LIMIT = 100
# Both services 429 under a fast burst of page requests. A small gap between
# calls is cheaper than the backoff a rate-limit response forces on us.
MIN_REQUEST_INTERVAL = 1.2
RATE_LIMIT_BACKOFF = 10.0
MAX_RETRY_AFTER = 60.0

_LAST_REQUEST = 0.0


class FetchError(RuntimeError):
    pass


def _retry_after_seconds(exc: urllib.error.HTTPError, fallback: float) -> float:
    """Honour a Retry-After header when the service sends one."""
    header = exc.headers.get("Retry-After") if exc.headers else None
    if not header:
        return fallback
    try:
        return max(fallback, min(float(header.strip()), MAX_RETRY_AFTER))
    except (TypeError, ValueError):
        return fallback


def _get_json(url: str, timeout: float = 45.0) -> dict[str, Any]:
    """GET with pacing and exponential backoff on transient failures.

    Both services rate-limit, and a burst of back-to-back page requests earns
    a 429 that costs far more time than pacing does. _LAST_REQUEST keeps a
    minimum gap between calls across every fetch in the process.
    """
    global _LAST_REQUEST
    delay = 2.0
    last: Exception | None = None
    for attempt in range(MAX_RETRIES):
        gap = MIN_REQUEST_INTERVAL - (time.monotonic() - _LAST_REQUEST)
        if gap > 0:
            time.sleep(gap)
        request = urllib.request.Request(
            url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"}
        )
        try:
            _LAST_REQUEST = time.monotonic()
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            # 4xx other than rate-limiting will not improve on retry.
            if exc.code not in (408, 429, 500, 502, 503, 504):
                raise FetchError(f"HTTP {exc.code} from {url}") from exc
            last = exc
            if exc.code == 429:
                delay = _retry_after_seconds(exc, max(delay, RATE_LIMIT_BACKOFF))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
            last = exc
        if attempt < MAX_RETRIES - 1:
            time.sleep(delay)
            delay *= 2
    raise FetchError(f"giving up on {url}: {last}")


def _iso(moment: dt.datetime) -> str:
    return moment.astimezone(_UTC).strftime("%Y-%m-%dT%H:%M:%S")


def _paginate(first_url: str, max_pages: int, label: str, verbose: bool) -> Iterator[dict]:
    url: str | None = first_url
    for page in range(max_pages):
        if not url:
            return
        if verbose:
            print(f"  [{label}] page {page + 1} ...", file=sys.stderr)
        payload = _get_json(url)
        yield payload
        links = payload.get("links") if isinstance(payload.get("links"), dict) else {}
        nxt = links.get("next")
        if isinstance(nxt, str) and nxt and nxt != url:
            url = nxt
        else:
            return


def fetch_find_a_tender(
    since: dt.datetime,
    until: dt.datetime | None = None,
    stages: str = "tender",
    max_pages: int = 40,
    verbose: bool = False,
) -> list[dict]:
    """Release packages from Find a Tender updated in the given window."""
    until = until or dt.datetime.now(_UTC)
    query = urllib.parse.urlencode(
        {
            "updatedFrom": _iso(since),
            "updatedTo": _iso(until),
            "stages": stages,
            "limit": PAGE_LIMIT,
        }
    )
    return list(_paginate(f"{FTS_BASE}?{query}", max_pages, f"FTS {stages}", verbose))


def fetch_contracts_finder(
    since: dt.datetime,
    until: dt.datetime | None = None,
    stages: str = "tender",
    max_pages: int = 40,
    verbose: bool = False,
) -> list[dict]:
    """Release packages from Contracts Finder published in the given window."""
    until = until or dt.datetime.now(_UTC)
    query = urllib.parse.urlencode(
        {
            "publishedFrom": _iso(since),
            "publishedTo": _iso(until),
            "stages": stages,
            "size": PAGE_LIMIT,
        }
    )
    return list(_paginate(f"{CF_BASE}?{query}", max_pages, f"CF {stages}", verbose))


def load_local(paths: list[str]) -> list[dict]:
    """Read OCDS release packages from disk - used by tests and offline runs."""
    packages: list[dict] = []
    for path in paths:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        packages.extend(data if isinstance(data, list) else [data])
    return packages


def fetch_award_history(
    fetch: "Callable[..., list[dict]]",
    since: dt.datetime,
    until: dt.datetime,
    chunk_days: int = 365,
    max_pages_per_chunk: int = 3,
    time_budget: float = 120.0,
    verbose: bool = False,
) -> list[dict]:
    """Award packages over a long look-back, newest window first.

    Both services page chronologically from the start of the window, so a
    single six-year query spends its whole page budget in the oldest year and
    never reaches the awards that say who holds a contract *now*. Walking
    backwards in chunks spends the budget where the signal is, and the time
    budget stops a slow service from holding up the whole build.
    """
    packages: list[dict] = []
    started = time.monotonic()
    window_end = until
    while window_end > since:
        if time.monotonic() - started > time_budget:
            if verbose:
                print(
                    f"  [awards] time budget reached; stopping at {_iso(window_end)}",
                    file=sys.stderr,
                )
            break
        window_start = max(since, window_end - dt.timedelta(days=chunk_days))
        try:
            packages += fetch(
                window_start,
                window_end,
                stages="award",
                max_pages=max_pages_per_chunk,
                verbose=verbose,
            )
        except FetchError as exc:
            if verbose:
                print(f"  [awards] {_iso(window_start)} unavailable: {exc}", file=sys.stderr)
        window_end = window_start
    return packages
