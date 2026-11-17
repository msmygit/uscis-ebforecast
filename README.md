# EB priority date estimator

Estimates when an employment-based (EB) green card priority date may become current, using the USCIS `.xlsx` reports in this folder and the State Department visa bulletins. It also builds one interactive page, `eb_priority_dates.html`.

Planning aid only, not legal advice or a prediction. Dates move with demand, policy and law.

## What you need

- Python 3.9+ (nothing to install; standard library only).
- `pdftotext` only if you import bulletin PDFs (`brew install poppler`).

Run every command from any folder **other than** the data folder, with `python3 -I` (isolated mode, so downloaded files are never executed):

```
cd ~
python3 -I /Users/mrkr/Downloads/uscis/tool/eb.py <command>
```

Below, `eb` is shorthand for that whole command.

## 1. Estimate

```
eb estimate EB2:India:2014-06-15 EB3:China:2021-03-15 EB1:ROW:2025-01-01
```

Each query is `CATEGORY:COUNTRY:YYYY-MM-DD`; give as many as you like.

| Part | Allowed values |
|---|---|
| Category | `EB1` `EB2` `EB3` `EW3` (other workers) `EB4` `CRW` (religious workers) `EB5` (= unreserved) `EB5-RURAL` `EB5-HIGH-UNEMPLOYMENT` `EB5-INFRASTRUCTURE` |
| Country | `India` `China` `Mexico` `Philippines` `ROW` (all other countries) |
| Date | your priority date, `YYYY-MM-DD` |

Options: `--json` for machine-readable output; `--set key=value` to change an assumption, e.g. `--set eb_annual_limit=150000`.

### Reading the output

- **Estimated final action**: base date, with an early-to-late range and a confidence label. This is when your date may be reached by the Final Action Dates chart (green card approval).
- **Estimated filing eligibility**: when the Dates for Filing chart may reach you (only usable for adjustment of status when USCIS designates that chart that month).
- **Queue method**: people ahead of you divided by visas available per year, for early / base / late assumptions.
- **Trend method**: how fast the cutoff has moved historically. It appears only once enough bulletin history is cached (see step 3).
- **Note** lines: caveats for that query. Read them; they matter (for example, a priority date later than the inventory covers).

"Current now" means your date is already earlier than the cutoff.

## 2. Open the interactive page

Double-click `eb_priority_dates.html`. Choose a category, country and full priority date (day included); the estimate, "people ahead" chart, cutoffs, waiting petitions and I-485 trends update. It works offline.

Rebuild it after new data arrives:

```
eb page
```

## 3. Keep the data current

**USCIS reports** (`.xlsx`): download new files into this folder, keeping their names (`eb_inventory_*`, `eb_i140_i360_i526_performancedata_*`, `i485_performance_data_*`). The newest inventory is used automatically. Check what loaded:

```
eb data
```

**Visa bulletins**: travel.state.gov blocks scripts, so save each month's bulletin from your browser (PDF or "Save page as" HTML) and import it:

```
eb import visabulletin_December2026.pdf
```

The month is read from the file. If it can't be detected, add `--month 2026-12`.

Optionally, `eb refresh` downloads older bulletins from the Internet Archive and USCIS monthly pages into `tool/cache/bulletins.json`. This needs internet access. The more months cached, the better the trend method works. After importing or refreshing, run `eb page` again.

## 4. Use it from Claude Code

A project skill, `eb-priority-date`, is in `.claude/skills/`. In Claude Code, open this folder and ask, for example, "when will EB2 India 2014-06-15 be current?"

## Files the tool reads

| File (in this folder) | Used for | If missing |
|---|---|---|
| `eb_inventory_<month>_<year>_v1.xlsx` (USCIS pending I-485 inventory) | People ahead of you, by category, country and priority-date month. The newest "As of" date is used; older ones are loaded but not used for the estimate. | Estimate fails: this file is required |
| `eb_i140_i360_i526_performancedata_*.xlsx` (approved petitions awaiting a visa) | Principals who haven't filed an I-485 yet; used for priority dates beyond what the inventory reaches. Newest file wins. | Queue estimate ignores these people |
| `i485_performance_data_*.xlsx` (quarterly I-485 totals) | Page only: employment-based received/approved/pending charts | Chart empty |
| `visabulletin_*.pdf` or saved bulletin `.html`, imported into `tool/cache/bulletins.json` | Current cutoffs (Final Action and Dates for Filing), trend method, cross-checks | Queue method only, no cutoffs shown |

Not used: the two `i765_*` files and `net_backlog_frontlog_*.xlsx` (context only). Files are matched by name pattern, so keep USCIS's original names.

## Assumptions the tool makes

All live in `DEFAULT_ASSUMPTIONS` in `tool/ebforecast/model.py`. Override one run with `--set key=value` (JSON values).

| Assumption | Value | Basis |
|---|---|---|
| Annual EB limit | 140,000 | Statutory floor (INA 201). Unused family numbers can raise it; FY2027's figure isn't published in the sources used |
| Category shares | EB-1/2/3 28.6% each, EB-4 7.1%, EB-5 7.1% | INA 203(b) |
| EB-3 Other Workers | 9,850 (10,000 less ~150 NACARA offset) | Visa bulletin footnote |
| EB-5 split | 68% unreserved, 20% rural, 10% high unemployment, 2% infrastructure | EB-5 Reform and Integrity Act |
| Per-country ceiling | 7% of the category limit | INA 202(a)(2) |
| Visas per approved principal | 1.8 / 2.0 / 2.2 (early / base / late) | **My judgment**: principal plus family |
| Share of counted people who actually take a visa | 70% / 85% / 100% | **My judgment**: duplicates, abandonments |
| Spillover multiple for capped countries | 3.5 / 2.0 / 1.0 when the rest of the world is current; 1.3 / 1.0 / 1.0 when it is not | **My judgment** (INA 202(a)(5)) |
| Share handled by USCIS rather than consulates | 90% default; lower for EB-3 (80%), Other Workers (60%), Philippines EB-3 (35%), China EB-5 (50%) | **My judgment**; the inventory has no consular data |
| Masked "D" cells | counted as 5 | USCIS discloses nothing under 11 |
| Trend windows | 12, 24, 36, 60, 120 months | Needs cached bulletin history |

The estimate is a range because the "early" and "late" columns vary these judgment values.

## How to load new files

1. **New USCIS reports**: download the `.xlsx` into this folder with its original name. Run `eb data` to confirm it loaded and shows the right "as of" date.
2. **New visa bulletin**: save it from travel.state.gov (PDF or HTML), put it in this folder, run `eb import <file>`.
3. **Rebuild the page**: `eb page`.

Run these each month when the bulletin and the USCIS inventory update.

## How the estimate works

1. **Queue**: pending I-485 applications with earlier priority dates (USCIS inventory; masked "D" cells counted as 5), plus approved petitions that have not filed yet, divided by yearly visas for that line (140,000 limit, category shares, 7% per-country floor, spillover when the rest of the world is current).
2. **Trend**: speed of past cutoff movement over 1 to 10 year windows.
3. **Cross-check**: the inventory's Available / Awaiting flags, used when the cached bulletin is older than the inventory.

## Known limits

- The inventory excludes consular cases and people who haven't filed an I-485. India EB-2/EB-3 inventory stops around early 2015, so later India dates lean on petition totals.
- Family size, drop-out and spillover are assumptions (listed in `tool/ebforecast/model.py`, `DEFAULT_ASSUMPTIONS`).
- The FY2027 annual limit isn't published in the sources used; 140,000 is assumed.
- Retrogression, new proclamations or legislation can change everything.

## Files

```
eb_priority_dates.html        interactive page (generated)
tool/eb.py                    command-line entry point
tool/ebforecast/              xlsx reader, data loaders, model, bulletin parser, page builder
tool/cache/bulletins.json     cached visa bulletins
.claude/skills/eb-priority-date/   Claude Code skill
```
