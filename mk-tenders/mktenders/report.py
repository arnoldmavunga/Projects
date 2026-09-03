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
        f"{'#':>3}  {'LIFT':>5}  {'BAND':<11} {'FIT':>4}  {'INCUMB':>6}  "
        f"{'VALUE':>7}  {'CLOSES':<11}  {'TITLE':<52}  BUYER"
    )
    stream.write("\n" + header + "\n")
    stream.write("-" * len(header) + "\n")

    for index, notice in enumerate(notices[:top], start=1):
        days = notice.days_to_deadline()
        closes = notice.deadline.strftime("%Y-%m-%d") if notice.deadline else "rolling"
        if days is not None and days < 14:
            closes += "!"
        stream.write(
            f"{index:>3}  {notice.lift_score:>5.1f}  {lift_band(notice.lift_score):<11} "
            f"{notice.fit_score:>4.0f}  {notice.incumbent_risk:>6.0f}  "
            f"{_money(notice.value):>7}  {closes:<11}  "
            f"{_clip(notice.title, 52):<52}  {_clip(notice.buyer, 30)}\n"
        )

    stream.write(
        f"\n{len(notices)} suitable open notice(s); showing top {min(top, len(notices))}.\n"
        "LIFT 0-100, lower is lighter. INCUMB 0-100, higher means someone is\n"
        "probably already delivering it. '!' marks a deadline inside 14 days.\n\n"
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


HTML_TEMPLATE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Milton Keynes tenders - ranked by ease of lift</title>
<style>
  :root {{ color-scheme: light dark; --bg:#fbfbfa; --fg:#1a1a18; --muted:#6b6b66;
           --line:#e3e3df; --card:#fff; --accent:#2f6f4f; }}
  @media (prefers-color-scheme: dark) {{
    :root {{ --bg:#161614; --fg:#ebebe7; --muted:#9a9a93; --line:#2e2e2a;
             --card:#1e1e1b; --accent:#7fc4a0; }} }}
  body {{ margin:0; padding:24px 16px 64px; background:var(--bg); color:var(--fg);
         font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif; }}
  .wrap {{ max-width:900px; margin:0 auto; }}
  h1 {{ font-size:1.5rem; margin:0 0 4px; letter-spacing:-0.01em; }}
  .sub {{ color:var(--muted); margin:0 0 28px; font-size:0.9rem; }}
  .card {{ background:var(--card); border:1px solid var(--line); border-radius:10px;
          padding:16px 18px; margin-bottom:12px; }}
  .top {{ display:flex; gap:12px; align-items:baseline; flex-wrap:wrap; }}
  .rank {{ font-variant-numeric:tabular-nums; color:var(--muted); font-size:0.85rem; }}
  .title {{ font-weight:600; flex:1; min-width:220px; }}
  .title a {{ color:inherit; text-decoration:none; border-bottom:1px solid var(--accent); }}
  .buyer {{ color:var(--muted); font-size:0.88rem; margin:4px 0 10px; }}
  .pills {{ display:flex; gap:6px; flex-wrap:wrap; margin-bottom:10px; }}
  .pill {{ font-size:0.75rem; padding:2px 9px; border-radius:99px;
          border:1px solid var(--line); color:var(--muted); white-space:nowrap; }}
  .pill.lift {{ border-color:var(--accent); color:var(--accent); font-weight:600; }}
  .pill.warn {{ border-color:#c0703a; color:#c0703a; }}
  details {{ margin-top:8px; }} summary {{ cursor:pointer; color:var(--muted); font-size:0.85rem; }}
  ul {{ margin:8px 0 0; padding-left:20px; color:var(--muted); font-size:0.87rem; }}
  .links {{ margin-top:10px; font-size:0.87rem; display:flex; gap:14px; flex-wrap:wrap; }}
  .links a {{ color:var(--accent); }}
  footer {{ color:var(--muted); font-size:0.8rem; margin-top:32px;
           border-top:1px solid var(--line); padding-top:14px; }}
</style></head><body><div class="wrap">
<h1>Milton Keynes tenders you can service</h1>
<p class="sub">{count} open opportunit{plural} matching your capability areas, lightest lift first.
Generated {generated}.</p>
{cards}
<footer>LIFT 0&ndash;100, lower is lighter. INCUMBENT 0&ndash;100, higher means someone is
probably already delivering it. Scores are heuristics over notice text &mdash; always read
the notice itself before committing bid time.</footer>
</div></body></html>
"""

CARD_TEMPLATE = """<div class="card">
  <div class="top"><span class="rank">#{rank}</span>
    <span class="title"><a href="{notice_url}" target="_blank" rel="noopener">{title}</a></span></div>
  <div class="buyer">{buyer}</div>
  <div class="pills">
    <span class="pill lift">Lift {lift:.0f} &middot; {band}</span>
    <span class="pill">Fit {fit:.0f}</span>
    <span class="pill{incumbent_class}">Incumbent {incumbent:.0f}</span>
    <span class="pill">{value}</span>
    <span class="pill{deadline_class}">{closes}</span>
  </div>
  <details><summary>Why this scores as {band_lower}</summary>
    <ul>{lift_reasons}</ul>
    <summary style="margin-top:10px">Is it already being serviced?</summary>
    <ul>{incumbent_reasons}</ul>
  </details>
  <div class="links"><a href="{notice_url}" target="_blank" rel="noopener">Read the notice &rarr;</a>{portal_link}</div>
</div>"""


def write_html(notices: list[Notice], path: str) -> None:
    """A clickable ranked page - useful for triaging on a phone."""
    import datetime as _dt
    import html as _html

    cards = []
    for index, notice in enumerate(notices, start=1):
        days = notice.days_to_deadline()
        if notice.deadline:
            closes = notice.deadline.strftime("%d %b %Y")
            if days is not None:
                closes += f" ({days:.0f}d)"
        else:
            closes = "Rolling entry"
        found = portal(notice)
        portal_link = (
            f'<a href="{found[1]}" target="_blank" rel="noopener">Bid via {_html.escape(found[0])} &rarr;</a>'
            if found else ""
        )
        cards.append(
            CARD_TEMPLATE.format(
                rank=index,
                notice_url=_html.escape(notice_url(notice), quote=True),
                title=_html.escape(notice.title),
                buyer=_html.escape(notice.buyer or "Buyer not stated"),
                lift=notice.lift_score,
                band=lift_band(notice.lift_score),
                band_lower=lift_band(notice.lift_score).lower(),
                fit=notice.fit_score,
                incumbent=notice.incumbent_risk,
                incumbent_class=" warn" if notice.incumbent_risk >= 60 else "",
                value=_money(notice.value),
                closes=_html.escape(closes),
                deadline_class=" warn" if (days is not None and days < 14) else "",
                lift_reasons="".join(
                    f"<li>{_html.escape(r)}</li>" for r in notice.lift_reasons
                ),
                incumbent_reasons="".join(
                    f"<li>{_html.escape(r)}</li>" for r in notice.incumbent_reasons
                ),
                portal_link=portal_link,
            )
        )

    with open(path, "w", encoding="utf-8") as handle:
        handle.write(
            HTML_TEMPLATE.format(
                count=len(notices),
                plural="y" if len(notices) == 1 else "ies",
                generated=_dt.datetime.now().strftime("%d %b %Y %H:%M"),
                cards="\n".join(cards) or "<p>No matching opportunities.</p>",
            )
        )
