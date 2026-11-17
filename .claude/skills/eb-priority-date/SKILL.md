---
name: eb-priority-date
description: Estimate when employment-based green card priority dates (EB-1 to EB-5; India, China, Mexico, Philippines, rest of world) become current, using the USCIS .xlsx reports and visa bulletins in this folder. Use when the user gives a category, country and priority date, or asks to refresh bulletins or rebuild the dynamic page.
---

# EB priority date estimator

Everything runs through `tool/eb.py` (standard library only; always call with `python3 -I`, from outside the data folder).

## Estimate
`python3 -I tool/eb.py estimate EB2:India:2014-06-15 EB3:China:2021-03-15`
- Category: EB1 EB2 EB3 EW3 EB4 CRW EB5-UNRESERVED EB5-RURAL EB5-HIGH-UNEMPLOYMENT EB5-INFRASTRUCTURE (`EB5` = unreserved)
- Country: India, China, Mexico, Philippines, ROW. Date: full YYYY-MM-DD priority date including the day (cutoffs have day precision, e.g. 15JAN15; never round to the month). Add `--json` for raw output, `--set key=value` to override an assumption (e.g. `eb_annual_limit=150000`).

When reporting, always give: the base estimate and early/late range, both charts' current cutoffs, how many are ahead, and which method each number came from. State the confidence and the caveats printed under "Note". Never present the date as a prediction or legal advice.

## Keep data current
- New USCIS reports: drop the `.xlsx` files in the folder (names `eb_inventory_*`, `eb_i140_*`, `i485_performance_data_*`), then `python3 -I tool/eb.py data` to confirm they load.
- Bulletins: `python3 -I tool/eb.py import <file.pdf|file.html>` for a bulletin saved from a browser (PDFs need `pdftotext`; travel.state.gov blocks scripts, so never try to bypass it). `refresh` pulls Internet Archive and USCIS copies into `tool/cache/bulletins.json` and needs network permission, which may be denied: ask the user to run it rather than working around the denial.
- Rebuild the page: `python3 -I tool/eb.py page` -> `eb_priority_dates.html`. Always rebuild after importing bulletins or adding reports. The page takes a full date; estimates are precomputed per month and interpolated by day, so it can differ slightly from the CLI.
- `README.md` in the data folder documents files used, assumptions and loading steps; keep it in sync if you change `DEFAULT_ASSUMPTIONS` or commands.

## Method (see tool/ebforecast/model.py)
1. Queue: pending I-485s with earlier priority dates (September/October inventory; "D" cells = 5) plus approved I-140s not yet filed, divided by annual visas for the line (140,000 x category share, 7% per-country floor, spillover when rest of world is current).
2. Trend: speed the final action cutoff moved over 12-120 month windows (needs a bulletin history; sparse until `refresh` is run).
3. Cross-check against the inventory's Available/Awaiting flags when the bulletin cache is older than the inventory.
Judgment values (family size, drop-out, spillover, USCIS share of adjudications) are the author's assumptions, not from the data: say so when reporting a range. Other Workers limit is 9,850 (NACARA offset ~150).
Known limits: the inventory omits consular cases and India EB-2/EB-3 beyond early 2015; EB-1/2/3 fall-down and FY2027 limits are assumptions.
