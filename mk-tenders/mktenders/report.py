"""Output: ranked console table, CSV, and JSON."""

from __future__ import annotations

import csv
import json
import sys
from typing import Iterable, TextIO

from .links import all_links, notice_url, portal
from .model import Notice
from .scoring import lift_band

CSV_COLUMNS = [
    "rank", "lift_score", "lift_band", "fit_score", "fit_areas", "incumbent_risk",
    "title", "buyer", "value_gbp", "deadline", "days_left", "source",
    "procurement_method", "lots", "sme_suitable", "cpv", "notice_url", "portal", "portal_url",
    "lift_reasons", "incumbent_reasons",
]


def _money(value: float | None) -> str:
    if value is None:
        return "-"
    if value >= 1_000_000:
        return f"£{value / 1_000_000:.1f}m"
    if value >= 1_000:
        return f"£{value / 1_000:.0f}k"
    return f"£{value:.0f}"


def _clip(text: str, width: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= width else text[: width - 1] + "…"


def rank(notices: list[Notice], min_fit: float) -> list[Notice]:
    """Suitable notices only, lightest lift first.

    Ties break towards the lower incumbent risk, then the larger contract -
    between two equally easy bids, prefer the one nobody is already servicing.
    """
    suitable = [n for n in notices if n.fit_score >= min_fit]
    return sorted(
        suitable,
        key=lambda n: (n.lift_score, n.incumbent_risk, -(n.value or 0.0)),
    )


def write_table(notices: list[Notice], stream: TextIO = sys.stdout, top: int = 25) -> None:
    if not notices:
        stream.write(
            "\nNo open notices matched your capability areas in this window.\n"
            "Try --min-fit 25, a longer --days, or --areas all.\n\n"
        )
        return

    header = (
        f"{'#':>3}  {'BAND':<11} {'INCUMB':<18} {'VALUE':>7}  {'CLOSES':<12}  TITLE"
    )
    stream.write("\n" + header + "\n")
    stream.write("-" * 110 + "\n")

    for index, notice in enumerate(notices[:top], start=1):
        days = notice.days_to_deadline()
        closes = notice.deadline.strftime("%Y-%m-%d") if notice.deadline else "rolling"
        if days is not None and days < 14:
            closes += "!"
        held = ("already held" if notice.incumbent_risk >= 60
                else "possible incumbent" if notice.incumbent_risk >= 30
                else "-")
        stream.write(
            f"{index:>3}  {lift_band(notice.lift_score):<11} {held:<18} "
            f"{_money(notice.value):>7}  {closes:<12}  {_clip(notice.title, 68)}\n"
            f"{'':>3}  {'':<11} {'':<18} {'':>7}  {'':<12}  {_clip(notice.buyer, 68)}\n"
        )

    stream.write(
        f"\n{len(notices)} suitable open notice(s); showing top {min(top, len(notices))}, "
        "easiest bid first.\n"
        "'!' marks a deadline inside 14 days. Use --html for the readable version.\n\n"
    )


def write_detail(notices: list[Notice], stream: TextIO = sys.stdout, top: int = 8) -> None:
    """The reasoning behind the top-ranked rows."""
    if not notices:
        return
    stream.write("=" * 78 + "\nWHY THESE RANK AS LIGHT\n" + "=" * 78 + "\n")
    for index, notice in enumerate(notices[:top], start=1):
        stream.write(f"\n{index}. {notice.title}\n")
        stream.write(f"   Buyer:    {notice.buyer or 'not stated'}\n")
        stream.write(
            f"   Lift:     {notice.lift_score:.1f} ({lift_band(notice.lift_score)})"
            f"   Fit: {notice.fit_score:.0f}"
            f"   Incumbent risk: {notice.incumbent_risk:.0f}\n"
        )
        if notice.fit_areas:
            stream.write(f"   Matches:  {', '.join(notice.fit_areas)}\n")
        stream.write(f"   Value:    {_money(notice.value)}\n")
        if notice.deadline:
            days = notice.days_to_deadline()
            suffix = f" ({days:.0f} days)" if days is not None else ""
            stream.write(
                f"   Closes:   {notice.deadline.strftime('%d %b %Y %H:%M')}{suffix}\n"
            )
        else:
            stream.write("   Closes:   rolling / not stated\n")
        stream.write("   Lift drivers:\n")
        for reason in notice.lift_reasons:
            stream.write(f"     - {reason}\n")
        stream.write("   Incumbent read:\n")
        for reason in notice.incumbent_reasons:
            stream.write(f"     - {reason}\n")
        stream.write(f"   Notice:   {notice_url(notice)}\n")
        found = portal(notice)
        if found:
            stream.write(f"   Bid via:  {found[0]} - {found[1]}\n")
    stream.write("\n")


def write_csv(notices: list[Notice], path: str) -> None:
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for index, notice in enumerate(notices, start=1):
            days = notice.days_to_deadline()
            writer.writerow(
                {
                    "rank": index,
                    "lift_score": notice.lift_score,
                    "lift_band": lift_band(notice.lift_score),
                    "fit_score": notice.fit_score,
                    "fit_areas": "; ".join(notice.fit_areas),
                    "incumbent_risk": notice.incumbent_risk,
                    "title": notice.title,
                    "buyer": notice.buyer,
                    "value_gbp": "" if notice.value is None else f"{notice.value:.0f}",
                    "deadline": notice.deadline.isoformat() if notice.deadline else "",
                    "days_left": "" if days is None else f"{days:.1f}",
                    "source": notice.source,
                    "procurement_method": notice.procurement_method_details
                    or notice.procurement_method,
                    "lots": notice.lot_count,
                    "sme_suitable": "" if notice.sme_suitable is None else notice.sme_suitable,
                    "cpv": "; ".join(notice.cpv_codes),
                    "notice_url": notice_url(notice),
                    "portal": (portal(notice) or ("", ""))[0],
                    "portal_url": (portal(notice) or ("", ""))[1],
                    "lift_reasons": " | ".join(notice.lift_reasons),
                    "incumbent_reasons": " | ".join(notice.incumbent_reasons),
                }
            )


def write_json(notices: list[Notice], path: str) -> None:
    payload = []
    for index, notice in enumerate(notices, start=1):
        payload.append(
            {
                "rank": index,
                "title": notice.title,
                "buyer": notice.buyer,
                "source": notice.source,
                "notice_url": notice_url(notice),
                "links": all_links(notice),
                "value_gbp": notice.value,
                "deadline": notice.deadline.isoformat() if notice.deadline else None,
                "days_left": notice.days_to_deadline(),
                "lift": {
                    "score": notice.lift_score,
                    "band": lift_band(notice.lift_score),
                    "reasons": notice.lift_reasons,
                },
                "fit": {"score": notice.fit_score, "areas": notice.fit_areas},
                "incumbent": {
                    "risk": notice.incumbent_risk,
                    "reasons": notice.incumbent_reasons,
                },
                "cpv": notice.cpv_codes,
                "lots": notice.lot_count,
                "sme_suitable": notice.sme_suitable,
            }
        )
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)


# The CSS is kept out of .format() entirely so it needs no brace escaping.
_CSS = """
.warn{margin:.6rem 0 0;padding:.6rem .75rem;border-radius:6px;
 border:1px solid #b45309;background:#fef3c7;color:#7c2d12;font-size:.85rem}
@media (prefers-color-scheme:dark){
 .warn{background:#3f2d0b;color:#fde68a;border-color:#b45309}}

:root{
  --paper:#f7f8f6; --surface:#fff; --ink:#14171a; --slate:#5c6660;
  --line:#dfe3de; --line-soft:#eef1ec;
  --accent:#2f6f4f; --accent-soft:#e8f0ea;
  --amber:#a9682a; --amber-soft:#f8efe4;
  --red:#a33a2a; --red-soft:#f8e8e4;
}
@media (prefers-color-scheme:dark){
  :root:not([data-theme="light"]){
    --paper:#121513; --surface:#191d1a; --ink:#e9ece8; --slate:#9aa39c;
    --line:#2b312d; --line-soft:#222722;
    --accent:#7fc4a0; --accent-soft:#1b2a22;
    --amber:#d69a5f; --amber-soft:#2a2119;
    --red:#e08b78; --red-soft:#2c1d19;
  }
}
:root[data-theme="dark"]{
  --paper:#121513; --surface:#191d1a; --ink:#e9ece8; --slate:#9aa39c;
  --line:#2b312d; --line-soft:#222722;
  --accent:#7fc4a0; --accent-soft:#1b2a22;
  --amber:#d69a5f; --amber-soft:#2a2119;
  --red:#e08b78; --red-soft:#2c1d19;
}
*{box-sizing:border-box}
body{margin:0;padding:0;background:var(--paper);color:var(--ink);
     font:17px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
     -webkit-font-smoothing:antialiased}
.wrap{max-width:820px;margin:0 auto;padding:28px 18px 80px}
header{border-bottom:2px solid var(--ink);padding-bottom:18px;margin-bottom:8px}
h1{font-size:1.7rem;line-height:1.15;letter-spacing:-.02em;margin:0 0 8px;text-wrap:balance}
.meta{color:var(--slate);font-size:.9rem;margin:0}
.meta b{color:var(--ink);font-weight:600}

.band{margin-top:38px}
.band-head{display:flex;align-items:baseline;gap:10px;flex-wrap:wrap;
           border-bottom:1px solid var(--line);padding-bottom:8px;margin-bottom:4px}
.band-name{font-size:1.15rem;font-weight:700;letter-spacing:-.01em}
.band-note{color:var(--slate);font-size:.88rem}
.band-count{margin-left:auto;color:var(--slate);font-size:.85rem;
            font-variant-numeric:tabular-nums}

.item{padding:20px 0;border-bottom:1px solid var(--line-soft)}
.item:last-child{border-bottom:none}
.rank{color:var(--slate);font-size:.8rem;font-variant-numeric:tabular-nums;
      letter-spacing:.06em;margin-bottom:5px}
.item h2{font-size:1.18rem;line-height:1.3;margin:0 0 5px;font-weight:650;
         letter-spacing:-.01em;text-wrap:balance}
.item h2 a{color:inherit;text-decoration:none;
           border-bottom:2px solid var(--accent-soft)}
.item h2 a:hover{border-bottom-color:var(--accent)}
.buyer{color:var(--slate);font-size:.92rem;margin:0 0 12px}

.facts{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px}
.fact{font-size:.85rem;padding:4px 11px;border-radius:4px;background:var(--surface);
      border:1px solid var(--line);white-space:nowrap}
.fact b{font-weight:650}
.fact.soon{background:var(--red-soft);border-color:var(--red);color:var(--red)}
.fact.warn{background:var(--amber-soft);border-color:var(--amber);color:var(--amber)}
.fact.good{background:var(--accent-soft);border-color:var(--accent);color:var(--accent)}

.why{margin:0 0 12px;font-size:.95rem;color:var(--slate)}
.why b{color:var(--ink);font-weight:600}

details{margin:0 0 12px}
summary{cursor:pointer;color:var(--accent);font-size:.88rem;padding:2px 0}
summary::marker{color:var(--slate)}
details ul{margin:8px 0 0;padding-left:20px;color:var(--slate);font-size:.9rem}
details li{margin-bottom:3px}
.cols{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:4px 24px}

.go{display:flex;gap:16px;flex-wrap:wrap;font-size:.92rem}
.go a{color:var(--accent);font-weight:600;text-decoration:none}
.go a:hover{text-decoration:underline}
a:focus-visible,summary:focus-visible{outline:2px solid var(--accent);outline-offset:3px;
                                      border-radius:3px}

.empty{background:var(--surface);border:1px solid var(--line);border-radius:8px;
       padding:24px;margin-top:28px}
.empty p{margin:0 0 10px}
.empty code{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:.88em;
            background:var(--accent-soft);padding:2px 6px;border-radius:3px}
footer{margin-top:48px;border-top:1px solid var(--line);padding-top:18px;
       color:var(--slate);font-size:.85rem}
footer p{margin:0 0 8px}
@media (prefers-reduced-motion:reduce){*{transition:none!important;animation:none!important}}
"""

# What each lift band means in practice, shown next to the band heading.
_BAND_NOTES = {
    "Very light": "bid these first",
    "Light": "worth a look",
    "Moderate": "a real piece of work",
    "Heavy": "only with a reason",
    "Very heavy": "probably not yours",
}

_BAND_ORDER = ["Very light", "Light", "Moderate", "Heavy", "Very heavy"]


def _closes_fact(notice: Notice) -> str:
    """A deadline people can read at a glance, colour-coded by urgency."""
    days = notice.days_to_deadline()
    if notice.deadline is None:
        return '<span class="fact good">Rolling entry &mdash; <b>no deadline</b></span>'
    when = notice.deadline.strftime("%-d %b") if hasattr(notice.deadline, "strftime") else ""
    if days is None:
        return f'<span class="fact">Closes <b>{when}</b></span>'
    if days < 1:
        return '<span class="fact soon">Closes <b>today</b></span>'
    if days < 7:
        return f'<span class="fact soon">Closes in <b>{days:.0f} days</b> &middot; {when}</span>'
    if days < 21:
        return f'<span class="fact warn">Closes in <b>{days:.0f} days</b> &middot; {when}</span>'
    return f'<span class="fact">Closes in <b>{days:.0f} days</b> &middot; {when}</span>'


def _incumbent_fact(notice: Notice) -> str:
    risk = notice.incumbent_risk
    if risk >= 60:
        return '<span class="fact warn">Someone <b>already holds this</b></span>'
    if risk >= 30:
        return '<span class="fact">Possible incumbent</span>'
    return '<span class="fact good">No incumbent signals</span>'


def _why_line(notice: Notice) -> str:
    """One sentence a person can act on, built from the strongest signals."""
    import html as _html

    heavy = [r for r in notice.lift_reasons
             if any(k in r.lower() for k in
                    ("required", "tupe", "bond", "cover", "depot", "fleet", "term",
                     "consortium", "prime", "multi-site", "area-wide", "novation"))]
    light = [r for r in notice.lift_reasons
             if any(k in r.lower() for k in ("sme", "vcse", "lots", "dps", "light-touch"))]

    parts = []
    if light:
        parts.append("In your favour: " + "; ".join(_html.escape(r) for r in light[:2]) + ".")
    if heavy:
        parts.append("Watch: " + "; ".join(_html.escape(r) for r in heavy[:3]) + ".")
    if not parts:
        parts.append("Nothing unusual in the notice either way.")
    return " ".join(parts)


def _item_html(notice: Notice, rank_no: int) -> str:
    import html as _html

    found = portal(notice)
    portal_link = (
        f'<a href="{_html.escape(found[1], quote=True)}" target="_blank" rel="noopener">'
        f'Bid via {_html.escape(found[0])} &rarr;</a>'
        if found else ""
    )
    lift_reasons = "".join(f"<li>{_html.escape(r)}</li>" for r in notice.lift_reasons)
    inc_reasons = "".join(f"<li>{_html.escape(r)}</li>" for r in notice.incumbent_reasons)
    areas = f' &middot; {_html.escape(", ".join(notice.fit_areas))}' if notice.fit_areas else ""

    return f"""<article class="item">
  <div class="rank">#{rank_no}</div>
  <h2><a href="{_html.escape(notice_url(notice), quote=True)}" target="_blank" rel="noopener">{_html.escape(notice.title)}</a></h2>
  <p class="buyer">{_html.escape(notice.buyer or "Buyer not stated")}{areas}</p>
  <div class="facts">
    {_closes_fact(notice)}
    <span class="fact">Worth <b>{_money(notice.value)}</b></span>
    {_incumbent_fact(notice)}
  </div>
  <p class="why">{_why_line(notice)}</p>
  <details>
    <summary>Full scoring &mdash; lift {notice.lift_score:.0f}, fit {notice.fit_score:.0f}, incumbent {notice.incumbent_risk:.0f}</summary>
    <div class="cols">
      <div><strong>What makes it this heavy</strong><ul>{lift_reasons}</ul></div>
      <div><strong>Is it already being serviced?</strong><ul>{inc_reasons}</ul></div>
    </div>
  </details>
  <div class="go">
    <a href="{_html.escape(notice_url(notice), quote=True)}" target="_blank" rel="noopener">Read the notice &rarr;</a>
    {portal_link}
  </div>
</article>"""


def write_html(notices: list[Notice], path: str, subtitle: str = "") -> None:
    """A ranked page built to be read on a phone: grouped by how hard the bid is."""
    import datetime as _dt
    import html as _html

    generated = _dt.datetime.now().strftime("%-d %B %Y, %H:%M")

    if notices:
        grouped: dict[str, list[tuple[int, Notice]]] = {}
        for index, notice in enumerate(notices, start=1):
            grouped.setdefault(lift_band(notice.lift_score), []).append((index, notice))

        blocks = []
        for band in _BAND_ORDER:
            rows = grouped.get(band)
            if not rows:
                continue
            items = "\n".join(_item_html(n, i) for i, n in rows)
            blocks.append(
                f'<section class="band">\n'
                f'  <div class="band-head">\n'
                f'    <span class="band-name">{band}</span>\n'
                f'    <span class="band-note">{_BAND_NOTES.get(band, "")}</span>\n'
                f'    <span class="band-count">{len(rows)}</span>\n'
                f'  </div>\n{items}\n</section>'
            )
        body = "\n".join(blocks)
        count = len(notices)
        headline = f"<b>{count}</b> open opportunit{'y' if count == 1 else 'ies'} you can service"
    elif subtitle:
        # Nothing matched, but the pull was cut short - so this is not a
        # confident zero and must not be presented as one.
        body = (
            '<div class="empty">'
            "<p><strong>Nothing open matched - but the search was incomplete.</strong></p>"
            "<p>Some notices could not be retrieved, so an opportunity may have been "
            "missed rather than absent. Re-run before drawing any conclusion from "
            "this.</p></div>"
        )
        headline = "No matches, from an incomplete search"
    else:
        body = (
            '<div class="empty">'
            "<p><strong>Nothing open matched your capability areas in this window.</strong></p>"
            "<p>That is a normal result on a quiet week, not a failure. Widen the search with "
            "<code>--days 90</code>, loosen the match with <code>--min-fit 25</code>, or add "
            "areas with <code>--areas all</code>.</p></div>"
        )
        headline = "No open opportunities matched"

    html = (
        "<!doctype html>\n"
        '<html lang="en"><head><meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        "<title>Milton Keynes tenders you can service</title>\n"
        f"<style>{_CSS}</style>\n"
        "</head><body>\n"
        '<div class="wrap">\n'
        "<header>\n"
        "<h1>Milton Keynes tenders you can service</h1>\n"
        f'<p class="meta">{headline}, easiest bid first. '
        f"Updated {generated}.</p>\n"
        + (
            f'<p class="warn">{_html.escape(subtitle)}</p>\n' if subtitle else ""
        )
        + "</header>\n"
        f"{body}\n"
        "<footer>\n"
        "<p><strong>Lift</strong> estimates what bidding and then delivering would cost you: "
        "contract size, time left, procedure, accreditations, mobilisation. Lower is lighter.</p>\n"
        "<p><strong>Incumbent</strong> asks whether anyone already holds the work &mdash; read "
        "from TUPE and re-tender language in the notice, and from the same buyer's award "
        "history.</p>\n"
        "<p>Both are heuristics over notice text. They triage; they do not decide. Read the "
        "notice before committing bid time.</p>\n"
        "</footer>\n"
        "</div></body></html>\n"
    )
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(html)
