"""Command line entry point.

Default behaviour answers the question directly: which open Milton Keynes
public-sector opportunities suit me, ranked lightest lift first.
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys

from . import report, sources
from .filters import filter_milton_keynes, milton_keynes_relevance
from .model import Notice, notices_from_packages
from .scoring import CAPABILITY_AREAS, apply_scores

_UTC = dt.timezone.utc
DEFAULT_AREAS = ["it", "professional", "facilities"]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mk-tenders",
        description=(
            "Find open Milton Keynes public-sector tenders that suit you, "
            "ranked by ease of lift (lightest first)."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "examples:\n"
            "  python -m mktenders                       # default: your 3 areas, last 60 days\n"
            "  python -m mktenders --days 90 --top 40\n"
            "  python -m mktenders --areas it professional\n"
            "  python -m mktenders --max-lift 35         # only genuinely light work\n"
            "  python -m mktenders --max-incumbent 40    # skip likely re-lets\n"
            "  python -m mktenders --offline fixtures/*.json\n"
        ),
    )
    parser.add_argument(
        "--areas", nargs="+", default=DEFAULT_AREAS,
        choices=list(CAPABILITY_AREAS) + ["all"],
        help="capability areas to match (default: it professional facilities)",
    )
    parser.add_argument("--days", type=int, default=60,
                        help="how far back to pull notices (default: 60)")
    parser.add_argument("--min-fit", type=float, default=35.0,
                        help="minimum capability-fit score to count as suitable (default: 35)")
    parser.add_argument("--max-lift", type=float, default=None,
                        help="drop anything heavier than this lift score")
    parser.add_argument("--max-incumbent", type=float, default=None,
                        help="drop anything with an incumbent risk above this")
    parser.add_argument("--top", type=int, default=25, help="rows in the table (default: 25)")
    parser.add_argument("--detail", type=int, default=8,
                        help="how many ranked rows to explain in full (default: 8)")
    parser.add_argument("--include-closed", action="store_true",
                        help="keep notices whose deadline has passed")
    parser.add_argument("--no-awards", action="store_true",
                        help="skip the award-history pass used for incumbent detection")
    parser.add_argument("--award-years", type=int, default=4,
                        help="years of award history to search for incumbents (default: 4)")
    parser.add_argument("--award-budget", type=float, default=60.0,
                        help="seconds to spend per service on award history (default: 60)")
    parser.add_argument("--csv", metavar="PATH", help="write the full ranked list to CSV")
    parser.add_argument("--json", metavar="PATH", help="write the full ranked list to JSON")
    parser.add_argument("--html", metavar="PATH",
                        help="write a clickable ranked page (handy on a phone)")
    parser.add_argument("--offline", nargs="+", metavar="FILE",
                        help="read OCDS packages from local files instead of the APIs")
    parser.add_argument("--source", choices=["both", "fts", "cf"], default="both",
                        help="which notice service to query (default: both)")
    parser.add_argument("-q", "--quiet", action="store_true", help="suppress progress output")
    return parser


def _gather(args: argparse.Namespace, verbose: bool) -> tuple[list[Notice], list[Notice]]:
    """Return (open tender notices, historic award notices)."""
    if args.offline:
        loaded = notices_from_packages(sources.load_local(args.offline), "local")
        return (
            [n for n in loaded if n.stage != "award"],
            [n for n in loaded if n.stage == "award"],
        )

    now = dt.datetime.now(_UTC)
    since = now - dt.timedelta(days=args.days)
    tenders: list[Notice] = []
    awards: list[Notice] = []

    def pull(fetch, label, stage, window_start):
        try:
            packages = fetch(window_start, now, stages=stage, verbose=verbose)
            return notices_from_packages(packages, label)
        except sources.FetchError as exc:
            print(f"  ! {label} {stage} unavailable: {exc}", file=sys.stderr)
            return []

    if args.source in ("both", "fts"):
        tenders += pull(sources.fetch_find_a_tender, "find-a-tender", "tender", since)
    if args.source in ("both", "cf"):
        tenders += pull(sources.fetch_contracts_finder, "contracts-finder", "tender", since)

    if not args.no_awards:
        # Award history is what tells us whether a requirement is already
        # being serviced, so it needs a much longer look-back than the
        # live-notice window. It is pulled newest window first, because a
        # recent award is what proves somebody holds the work today.
        award_since = now - dt.timedelta(days=365 * args.award_years)
        if verbose:
            print(
                f"Pulling {args.award_years}y award history for incumbent detection ...",
                file=sys.stderr,
            )

        def pull_awards(fetch, label):
            try:
                packages = sources.fetch_award_history(
                    fetch, award_since, now,
                    time_budget=args.award_budget, verbose=verbose,
                )
                return notices_from_packages(packages, label)
            except sources.FetchError as exc:
                print(f"  ! {label} award history unavailable: {exc}", file=sys.stderr)
                return []

        if args.source in ("both", "fts"):
            awards += pull_awards(sources.fetch_find_a_tender, "find-a-tender")
        if args.source in ("both", "cf"):
            awards += pull_awards(sources.fetch_contracts_finder, "contracts-finder")

    return tenders, awards


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    verbose = not args.quiet
    areas = list(CAPABILITY_AREAS) if "all" in args.areas else args.areas

    if verbose:
        labels = ", ".join(CAPABILITY_AREAS[a].label for a in areas)
        print(f"Capability areas: {labels}", file=sys.stderr)
        print(f"Notice window:    last {args.days} days\n", file=sys.stderr)

    tenders, awards = _gather(args, verbose)
    if verbose:
        print(f"\nRetrieved {len(tenders)} notice(s), {len(awards)} award record(s).",
              file=sys.stderr)

    mk_tenders = filter_milton_keynes(tenders)
    mk_awards = filter_milton_keynes(awards)
    if verbose:
        print(f"{len(mk_tenders)} are Milton Keynes-relevant.", file=sys.stderr)

    # De-duplicate: the same requirement is often on both services.
    unique: dict[str, Notice] = {}
    for notice in mk_tenders:
        key = notice.ocid or f"{notice.buyer}|{notice.title}".lower()
        existing = unique.get(key)
        if existing is None or (notice.published and existing.published
                                and notice.published > existing.published):
            unique[key] = notice
    deduped = list(unique.values())

    if not args.include_closed:
        deduped = [n for n in deduped if n.is_open()]
        if verbose:
            print(f"{len(deduped)} are still open.", file=sys.stderr)

    apply_scores(deduped, areas, prior_awards=mk_awards)

    ranked = report.rank(deduped, args.min_fit)
    if args.max_lift is not None:
        ranked = [n for n in ranked if n.lift_score <= args.max_lift]
    if args.max_incumbent is not None:
        ranked = [n for n in ranked if n.incumbent_risk <= args.max_incumbent]

    report.write_table(ranked, top=args.top)
    if args.detail:
        report.write_detail(ranked, top=args.detail)

    if args.csv:
        report.write_csv(ranked, args.csv)
        print(f"CSV written to {args.csv}", file=sys.stderr)
    if args.json:
        report.write_json(ranked, args.json)
        print(f"JSON written to {args.json}", file=sys.stderr)
    if args.html:
        report.write_html(ranked, args.html)
        print(f"HTML written to {args.html}", file=sys.stderr)

    return 0 if ranked else 1


if __name__ == "__main__":
    raise SystemExit(main())
