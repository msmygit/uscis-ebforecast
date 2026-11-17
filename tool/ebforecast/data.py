"""Load the USCIS .xlsx reports found in a data directory into plain Python structures."""
import datetime as dt
import glob
import os
import re

from .xlsx import read_workbook

MONTHS = ["January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December"]
COUNTRIES = ["India", "China", "Mexico", "Philippines", "ROW"]
# Midpoint used for cells USCIS masks as "D" (smallest disclosed value in the files is 11).
SUPPRESSED_ESTIMATE = 5


def norm_country(s):
    s = (s or "").strip()
    return "ROW" if s.lower().startswith("rest") else s


def norm_category(s):
    """Map the long USCIS label to a short code."""
    s = s or ""
    if "(EW3)" in s:
        return "EW3"
    if "(CRW)" in s:
        return "CRW"
    if "(EB5)" in s:
        if "Unreserved" in s:
            return "EB5-UNRESERVED"
        if "Rural" in s:
            return "EB5-RURAL"
        if "High Unemployment" in s:
            return "EB5-HIGH-UNEMPLOYMENT"
        if "Infrastructure" in s:
            return "EB5-INFRASTRUCTURE"
        return "EB5"
    m = re.search(r"\((EB[1-4])\)", s)
    return m.group(1) if m else s


def _parse_asof(text):
    m = re.search(r"As of (\w+) (\d+), (\d{4})", text or "")
    if not m:
        return None
    return dt.date(int(m.group(3)), MONTHS.index(m.group(1)) + 1, int(m.group(2)))


def load_inventory_file(path):
    """Pending I-485 inventory -> {"as_of": date, "rows": [dict]}.

    Each row: country, category, status ("Available"/"Awaiting Availability"),
    year (int, or None for the "Prior Years" bucket), first_year (first year
    column of the sheet, so "prior" means before it), month (1-12), count,
    suppressed (True when the cell was "D" and count is an estimate).
    """
    wb = read_workbook(path)
    rows, as_of = [], None
    for name, sheet in wb.items():
        if name.lower().startswith("how to read"):
            continue
        hdr = next((i for i, r in enumerate(sheet) if r and r[0] == "Country Of Chargeability"), None)
        if hdr is None:
            continue
        for r in sheet[:hdr]:
            as_of = as_of or _parse_asof(r[0] if r else None)
        years = []
        for h in sheet[hdr][4:]:
            m = re.search(r"(\d{4})\s*$", h or "")
            years.append(int(m.group(1)) if m else None)
        first_year = min(y for y in years if y)
        country = None
        for r in sheet[hdr + 1:]:
            if len(r) < 5 or r[3] not in MONTHS:
                continue
            country = norm_country(r[0]) if r[0] else country  # one row has a blank country cell
            for y, v in zip(years, r[4:]):
                if v in (None, 0, "-"):
                    continue
                sup = not isinstance(v, (int, float))
                rows.append({
                    "country": country, "category": norm_category(r[1]), "status": r[2],
                    "year": y, "first_year": first_year, "month": MONTHS.index(r[3]) + 1,
                    "count": SUPPRESSED_ESTIMATE if sup else int(v), "suppressed": sup,
                })
    return {"as_of": as_of, "rows": rows, "file": os.path.basename(path)}


def load_inventories(data_dir):
    out = [load_inventory_file(p) for p in glob.glob(os.path.join(data_dir, "eb_inventory_*.xlsx"))]
    out = [x for x in out if x["as_of"]]
    out.sort(key=lambda x: x["as_of"])
    return out


AWAITING_COLS = ["EB1", "EB2", "EB3", "EW3", "EB4", "CRW", "EB5-UNRESERVED", "EB5-SET-ASIDE"]


def load_awaiting(data_dir):
    """Approved petitions awaiting visa availability (principals only), latest file.

    Returns {"as_of": "June 2026", "counts": {country: {category: n}}} or None.
    """
    files = sorted(glob.glob(os.path.join(data_dir, "eb_i140_i360_i526_performancedata_*.xlsx")))
    if not files:
        return None
    sheet = next(iter(read_workbook(files[-1]).values()))
    as_of = next((r[0][6:] for r in sheet if r and isinstance(r[0], str) and r[0].startswith("As of ")), None)
    counts = {}
    for r in sheet:
        if r and isinstance(r[0], str) and len(r) >= 9 and isinstance(r[1], int) and r[0] != "TOTAL":
            counts[norm_country(r[0])] = dict(zip(AWAITING_COLS, r[1:9]))
    return {"as_of": as_of, "counts": counts, "file": os.path.basename(files[-1])}


def load_i485_quarterly(data_dir):
    """Employment-based I-485 national totals per quarter: received/approved/denied/pending."""
    out = []
    for p in sorted(glob.glob(os.path.join(data_dir, "i485_performance_data_*.xlsx"))):
        sheet = next(iter(read_workbook(p).values()))
        period = sheet[2][0] if len(sheet) > 2 and sheet[2] else None
        total = next((r for r in sheet[6:] if len(r) > 9 and all(isinstance(x, int) for x in r[6:10])), None)
        m = re.search(r"fy(\d{4})_q(\d)", os.path.basename(p))
        if total and m:
            out.append({"fy": int(m.group(1)), "q": int(m.group(2)), "period": period,
                        "received": total[6], "approved": total[7], "denied": total[8],
                        "pending": total[9], "file": os.path.basename(p)})
    return out
