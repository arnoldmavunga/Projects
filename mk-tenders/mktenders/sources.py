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
from typing import Any, Iterator

_UTC = dt.timezone.utc

FTS_BASE = "https://www.find-tender.service.gov.uk/api/1.0/ocdsReleasePackages"
CF_BASE = "https://www.contractsfinder.service.gov.uk/Published/Notices/OCDS/Search"

USER_AGENT = "mk-tenders/1.0 (+public procurement analysis; stdlib urllib)"
MAX_RETRIES = 4
PAGE_LIMIT = 100


class FetchError(RuntimeError):
    pass


def _get_json(url: str, timeout: float = 45.0) -> dict[str, Any]:
    """GET with exponential backoff on transient failures."""
    delay = 2.0
    last: Exception | None = None
    for attempt in range(MAX_RETRIES):
        request = urllib.request.Request(
            url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"}
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            # 4xx other than rate-limiting will not improve on retry.
            if exc.code not in (408, 429, 500, 502, 503, 504):
                raise FetchError(f"HTTP {exc.code} from {url}") from exc
            last = exc
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
