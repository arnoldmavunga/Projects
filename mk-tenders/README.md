# mk-tenders

Finds open Milton Keynes public-sector tenders that match what you can deliver,
and ranks them **lightest lift first**.

Three scores per opportunity:

| Score | Range | Meaning |
|---|---|---|
| **Lift** | 0–100, lower is lighter | How much work bidding *and then delivering* would cost you. The ranking axis. |
| **Fit** | 0–100, higher is better | Confidence it sits inside your capability areas. Used as a filter, not a rank. |
| **Incumbent risk** | 0–100, lower is better | Whether somebody is already servicing this. A TUPE re-let is a very different proposition from a genuinely new requirement. |

## Quick start

No dependencies beyond Python 3.10+.

```bash
python -m mktenders
```

That queries both official notice services for the last 60 days, keeps the
Milton Keynes ones, filters to IT/digital, professional/advisory and
facilities/works, and prints them lightest first.

```bash
# Only genuinely light work that nobody is already delivering
python -m mktenders --max-lift 35 --max-incumbent 40

# Clickable page — good for triaging on a phone
python -m mktenders --html report.html && open report.html

# Widen the net
python -m mktenders --days 90 --areas all --min-fit 25

# Spreadsheet for your pipeline
python -m mktenders --csv pipeline.csv
```

Run `python -m mktenders --help` for every flag.

## Where the data comes from

| Service | Covers | API |
|---|---|---|
| [Find a Tender](https://www.find-tender.service.gov.uk/) | Above-threshold notices (£139k+ services) | [`GET /api/1.0/ocdsReleasePackages`](https://www.find-tender.service.gov.uk/apidocumentation/1.0/GET-ocdsReleasePackages) |
| [Contracts Finder](https://www.contractsfinder.service.gov.uk/) | Below-threshold notices, incl. the £25k–£139k band | [`GET Published/Notices/OCDS/Search`](https://www.contractsfinder.service.gov.uk/apidocumentation) |

Both are open, unauthenticated, and publish
[OCDS](https://standard.open-contracting.org/) release packages. Both are queried
by default because most genuinely light-lift council work sits *below* threshold
and therefore never appears on Find a Tender.

**Notices are not the whole picture.** Milton Keynes City Council advertises
everything over £25k on its own In-Tend portal, and that is where you register
and submit — the GOV.UK notice is only the advert. Every result links to both.

- [MKCC In-Tend portal (current tenders)](https://in-tendhost.co.uk/milton-keynes/aspx/Tenders/Current)
- [MKCC tenders and contracts guidance](https://www.milton-keynes.gov.uk/business/tenders-and-contracts)

Registration on In-Tend is free, and you can express interest without being an
approved supplier. Set your In-Tend *Classifications* carefully — that is what
drives the alert emails.

## Running it live, with no laptop

`.github/workflows/mk-tenders.yml` runs the whole thing on GitHub's runners every
weekday at 06:30 UTC and publishes the ranked list to GitHub Pages. GitHub's
runners reach the GOV.UK APIs directly, so nothing has to run locally.

**One-time setup:** in the repository, go to **Settings → Pages** and set
*Source* to **GitHub Actions**. Then **Actions → MK tenders → Run workflow** to
build it immediately rather than waiting for the schedule.

The workflow also uploads the report as a downloadable build artifact, so the
CSV and JSON are available from the Actions run even before Pages is switched on.

Run it on demand with different settings from the **Run workflow** button —
`days`, `areas` and `min_fit` are all inputs. The test suite runs first, so a
broken change fails the build instead of publishing a wrong list.

## How lift is scored

Added (heavier):

- **Contract value** — 0 pts under £25k, rising to 25 pts over £2m.
- **Bid window** — 20 pts if under 7 days left, 0 pts if over 35.
- **Procedure** — DPS 0, open 4, framework 7, restricted 12, dialogue 15.
- **Accreditation burden** (capped 25) — CQC, Ofsted, ISO 27001, Cyber Essentials
  Plus, CHAS, Constructionline, Gas Safe, SIA, DBS, performance bonds, PCGs.
- **Mobilisation burden** (capped 20) — TUPE, 24/7 cover, depots, fleet, plant,
  consortium or prime-contractor models, multi-site delivery.
- **Term length** — 3 pts over 2 years, 6 pts over 4.

Subtracted (lighter):

- Flagged suitable for SMEs (−8) or VCSEs (−3)
- Split into lots, so you can bid just one (−6)
- A DPS, where entry is written once and reused (−5)

## How "already being serviced" is judged

The question the ranking cannot answer on its own, handled two ways:

1. **Notice text.** TUPE (+35) is the strongest tell that an incumbent workforce
   exists. "Existing/current provider", "re-tender", "expiry of the current
   contract" all add. "New service", "pilot", "no incumbent" subtract.
2. **Award history.** Six years of award notices from the same buyer are pulled
   and title-matched (Jaccard overlap on significant tokens, ≥0.34). A close
   match means this is a re-let and somebody is holding it today.

Negations are scrubbed before scoring, so "there is **no** incumbent" and "TUPE
does **not** apply" cannot register as positive incumbent signals — a mistake
that would otherwise bury exactly the opportunities you want.

## Geography

A notice qualifies as Milton Keynes if it has an MK-area buyer, an MK postcode,
or names an MK settlement. County-wide and regional buyers (Thames Valley Police,
Buckinghamshire Council, Central Bedfordshire) only qualify with local
corroboration, so a Slough-only police contract will not appear.

Buyers covered include MK City Council, MK University Hospital NHS FT, the Open
University, MK College, Thames Valley Police, Bucks Fire & Rescue and the town
and parish councils.

## Tests

```bash
python tests/test_pipeline.py     # no pytest needed
python -m pytest tests -q         # if you have it
```

27 tests over parsing, geography, open/closed handling, all three scores,
negation handling, link building and rank ordering. They run against
`tests/fixtures/`, which is generated with deadlines relative to today:

```bash
python tests/fixtures/build_fixture.py
python -m mktenders --offline tests/fixtures/tenders.json tests/fixtures/awards.json
```

## Caveats

- Scores are heuristics over notice text. They triage; they do not decide.
  Always read the notice before committing bid time.
- Buyers write notices inconsistently. A notice that omits TUPE may still carry
  it — check the ITT.
- Below-threshold work under £25k often never gets advertised at all. For that,
  the In-Tend classification alerts and direct contact with the category team
  matter more than any notice feed.
