"""Estimate when an employment-based priority date becomes current.

Two independent methods are run and reported side by side:

  queue  - count the people ahead in line (USCIS pending I-485 inventory, plus approved
           petitions that have not yet filed an I-485) and divide by the visas the law
           makes available each year to that category/country.
  trend  - measure how fast the Visa Bulletin cutoff has actually moved over several
           look-back windows and extrapolate.

Every judgment number lives in DEFAULT_ASSUMPTIONS and can be overridden.
"""
import datetime as dt
import statistics

CATEGORIES = ["EB1", "EB2", "EB3", "EW3", "EB4", "CRW", "EB5-UNRESERVED",
              "EB5-RURAL", "EB5-HIGH-UNEMPLOYMENT", "EB5-INFRASTRUCTURE"]
COUNTRIES = ["India", "China", "Mexico", "Philippines", "ROW"]
CAPPED = ["India", "China", "Mexico", "Philippines"]

DEFAULT_ASSUMPTIONS = {
    # INA 201(d): 140,000 plus unused family-sponsored numbers from the prior fiscal year.
    "eb_annual_limit": 140000,
    # INA 203(b) shares of the worldwide EB limit.
    "category_share": {"EB1": 0.286, "EB2": 0.286, "EB3": 0.286, "EB4": 0.071, "EB5": 0.071},
    # Other Workers: 10,000 inside EB-3, less the NACARA offset (about 150 in FY2026
    # per the July 2026 Visa Bulletin).
    "ew3_limit": 9850,
    # EB-5 Reform and Integrity Act split of the EB-5 limit.
    "eb5_split": {"EB5-UNRESERVED": 0.68, "EB5-RURAL": 0.20,
                  "EB5-HIGH-UNEMPLOYMENT": 0.10, "EB5-INFRASTRUCTURE": 0.02},
    # INA 202(a)(2) per-country ceiling.
    "per_country_share": 0.07,
    # Visas used per approved principal petition (principal + spouse + children).
    "family_multiplier": {"early": 1.8, "base": 2.0, "late": 2.2},
    # Share of counted people who really take a visa in this line (the rest are duplicate
    # petitions, EB-2/EB-3 double filings, abandonments, people who got a card another way).
    "queue_realisation": {"early": 0.70, "base": 0.85, "late": 1.00},
    # Multiple of the 7% floor a capped country really receives. When the rest of the world
    # is "Current" in the category, its unused numbers flow to the oldest priority dates
    # (INA 202(a)(5)); when the rest of the world also has a cutoff, little or nothing flows.
    "spill_when_row_current": {"early": 3.5, "base": 2.0, "late": 1.0},
    "spill_when_row_backlogged": {"early": 1.3, "base": 1.0, "late": 1.0},
    # Share of the line's visas issued through USCIS adjustment of status rather than
    # consulates (the inventory files do not show consular cases). Background-knowledge
    # defaults, not taken from the .xlsx files.
    "aos_share": {"default": 0.90, "EB3": 0.80, "EW3": 0.60, "EB4": 0.80, "CRW": 0.80,
                  "Philippines/EB3": 0.35, "China/EB5-UNRESERVED": 0.50},
    "trend_windows_months": [12, 24, 36, 60, 120],
}
SCENARIOS = ["early", "base", "late"]


def parse_date(s):
    if isinstance(s, dt.date):
        return s
    return dt.date.fromisoformat(s)


def add_years(d, years):
    try:
        return d + dt.timedelta(days=years * 365.25)
    except OverflowError:
        return dt.date.max


def add_months(d, n):
    y, m = divmod(d.year * 12 + d.month - 1 + n, 12)
    return dt.date(y, m + 1, 1)


def category_limit(cat, a):
    lim, sh = a["eb_annual_limit"], a["category_share"]
    if cat in ("EB1", "EB2"):
        return lim * sh[cat]
    if cat == "EB3":
        return lim * sh["EB3"] - a["ew3_limit"]
    if cat == "EW3":
        return a["ew3_limit"]
    if cat in ("EB4", "CRW"):
        return lim * sh["EB4"]
    if cat in a["eb5_split"]:
        return lim * sh["EB5"] * a["eb5_split"][cat]
    raise ValueError("unknown category %r" % cat)


# ---------------------------------------------------------------- bulletin helpers

def latest_month(bulletins, chart="fad"):
    """Newest bulletin month that actually carries the given chart."""
    have = [m for m in bulletins if bulletins[m].get(chart)]
    return max(have) if have else None


def cell(bulletins, month, chart, cat, country):
    return ((bulletins.get(month, {}).get(chart) or {}).get(cat) or {}).get(country)


def cutoff_date(value, month):
    """Effective cutoff: 'C' means everything before the bulletin month is current."""
    if value == "C":
        return dt.date.fromisoformat(month + "-01")
    if not value or value == "U":
        return None
    return dt.date.fromisoformat(value)


def series(bulletins, chart, cat, country):
    out = []
    for month in sorted(bulletins):
        c = cutoff_date(cell(bulletins, month, chart, cat, country), month)
        if c:
            out.append((dt.date.fromisoformat(month + "-01"), c))
    return out


def is_current(value, pd):
    if value == "C":
        return True
    if not value or value == "U":
        return False
    return pd < dt.date.fromisoformat(value)


def trend(bulletins, chart, cat, country, pd, a):
    """Extrapolate the cutoff's historical speed over several look-back windows."""
    s = series(bulletins, chart, cat, country)
    if len(s) < 2:
        return None
    now_month, now_cut = s[-1]
    by_month = dict(s)
    windows = []
    for w in a["trend_windows_months"]:
        then = by_month.get(add_months(now_month, -w))
        if then is None:
            continue
        rate = (now_cut - then).days / w  # days of priority date cleared per calendar month
        eta = None
        if rate > 0:
            eta = add_years(now_month, max(0, (pd - now_cut).days) / rate / 12)
        windows.append({"months": w, "from_cutoff": then.isoformat(),
                        "days_per_month": round(rate, 1), "eta": eta.isoformat() if eta else None})
    etas = sorted(dt.date.fromisoformat(w["eta"]) for w in windows if w["eta"])
    res = {"cutoff_now": now_cut.isoformat(), "as_of_bulletin": now_month.isoformat()[:7],
           "windows": windows}
    if etas:
        res.update(early=etas[0].isoformat(), late=etas[-1].isoformat(),
                   base=etas[len(etas) // 2].isoformat() if len(etas) % 2
                   else add_years(etas[len(etas) // 2 - 1],
                                  (etas[len(etas) // 2] - etas[len(etas) // 2 - 1]).days / 730.5).isoformat())
    return res


def filing_lead_months(bulletins, cat, country):
    """Median months by which the Dates for Filing chart reached a date before Final Action did."""
    fad = series(bulletins, "fad", cat, country)
    dff = series(bulletins, "dff", cat, country)
    if len(fad) < 12 or len(dff) < 12:
        return None  # too little history to say anything
    leads = []
    probe = min(c for _, c in fad)
    end = max(c for _, c in fad)
    while probe < end:
        f = next((m for m, c in fad if c > probe), None)
        d = next((m for m, c in dff if c > probe), None)
        if f and d and d >= dff[0][0] and f > fad[0][0] and d > dff[0][0]:
            leads.append((f.year - d.year) * 12 + f.month - d.month)
        probe = add_months(probe, 3)
    return statistics.median(leads) if leads else None


# ---------------------------------------------------------------- queue method

def _row_date(r):
    """First day of the priority-date month a row covers ('Prior Years' -> very old)."""
    if r["year"] is None:
        return dt.date(r["first_year"] - 1, 1, 1)
    return dt.date(r["year"], r["month"], 1)


def pool_for(bulletins, cat, country):
    """Countries that share one line: those with the same Final Action cutoff as the rest of the world."""
    month = latest_month(bulletins)
    if not month or country == "ROW":
        mine = row = cell(bulletins, month, "fad", cat, "ROW") if month else None
    else:
        mine = cell(bulletins, month, "fad", cat, country)
        row = cell(bulletins, month, "fad", cat, "ROW")
    if month and mine == row:
        return [c for c in COUNTRIES if cell(bulletins, month, "fad", cat, c) == row], row
    return [country], row


def queue(inventory, awaiting, bulletins, cat, country, pd, a):
    if inventory is None:
        return None
    pool, row_value = pool_for(bulletins, cat, country)
    cats = ["EB4", "CRW"] if cat in ("EB4", "CRW") else [cat]  # religious workers draw on EB-4
    rows = [r for r in inventory["rows"] if r["country"] in pool and r["category"] in cats]
    as_of = inventory["as_of"]
    total = sum(r["count"] for r in rows)

    ahead_inv = suppressed = 0
    for r in rows:
        start = _row_date(r)
        end = add_months(start, 1) if r["year"] else dt.date(r["first_year"], 1, 1)
        if end <= pd:
            frac = 1.0
        elif start >= pd:
            frac = 0.0
        else:
            frac = (pd - start).days / (end - start).days
        ahead_inv += r["count"] * frac
        suppressed += r["count"] * frac if r["suppressed"] else 0

    # Horizon: the latest priority-date month by which 98% of the pending applications fall.
    horizon, run = None, 0
    for r in sorted(rows, key=_row_date):
        run += r["count"]
        horizon = add_months(_row_date(r), 1)
        if run >= 0.98 * total:
            break

    # Approved petitions (principals) that have not filed an I-485 yet.
    aw_cat = {"EB5-UNRESERVED": "EB5-UNRESERVED"}.get(cat, "EB5-SET-ASIDE" if cat.startswith("EB5") else cat)
    aw_principals = sum((awaiting or {}).get("counts", {}).get(c, {}).get(k, 0)
                        for c in pool for k in (["EB4", "CRW"] if cat in ("EB4", "CRW") else [aw_cat]))
    inv_awaiting = sum(r["count"] for r in rows if r["status"].startswith("Awaiting"))
    aw_end = dt.date(as_of.year, as_of.month, 1)
    # Cutoff implied by the inventory's own Available / Awaiting flags (this country only):
    # the first priority-date month where more applications are awaiting than available.
    av, aw_m = {}, {}
    for r in inventory["rows"]:
        if r["country"] == country and r["category"] in cats and r["year"]:
            d = (av if r["status"] == "Available" else aw_m)
            d[_row_date(r)] = d.get(_row_date(r), 0) + r["count"]
    flips = sorted(m for m in aw_m if aw_m[m] > av.get(m, 0))
    implied = flips[0] if flips else None
    out = {"pool": pool, "inventory_as_of": as_of.isoformat(), "inventory_total": total,
           "inventory_implied_cutoff": implied.isoformat() if implied else None,
           "ahead_in_inventory": round(ahead_inv), "of_which_masked_estimate": round(suppressed),
           "inventory_horizon": horizon.isoformat() if horizon else None,
           "approved_petitions_waiting": aw_principals, "scenarios": {}}

    limit = category_limit(cat, a)
    share = a["aos_share"].get("%s/%s" % (country, cat), a["aos_share"].get(cat, a["aos_share"]["default"]))
    if "ROW" in pool:
        outside = [c for c in CAPPED if c not in pool]
        supply_floor = limit * (1 - a["per_country_share"] * len(outside))
        spill = {s: 1.0 for s in SCENARIOS}
    else:
        supply_floor = limit * a["per_country_share"]
        spill = a["spill_when_row_current"] if row_value == "C" else a["spill_when_row_backlogged"]
    out["statutory_supply_per_year"] = round(supply_floor)
    out["adjustment_share"] = share

    for s in SCENARIOS:
        mult = a["family_multiplier"][s]
        unfiled_people = max(0.0, aw_principals - inv_awaiting / mult) * mult
        beyond = 0.0
        if horizon and pd > horizon and aw_end > horizon:
            beyond = unfiled_people * min(1.0, (pd - horizon).days / (aw_end - horizon).days)
        ahead = (ahead_inv + beyond) * a["queue_realisation"][s]
        supply = supply_floor * spill[s]
        # Consular cases are invisible in the inventory, so only the adjustment share of the
        # supply works down the people counted from it; petition counts cover both routes.
        years = (ahead_inv * a["queue_realisation"][s]) / (supply * share) + \
                (beyond * a["queue_realisation"][s]) / supply if supply else float("inf")
        out["scenarios"][s] = {"people_ahead": round(ahead), "visas_per_year": round(supply),
                               "years": round(years, 1), "eta": add_years(as_of, years).isoformat()}
    return out


# ---------------------------------------------------------------- top level

def estimate(cat, country, pd, bulletins, inventory, awaiting, assumptions=None):
    a = dict(DEFAULT_ASSUMPTIONS)
    a.update(assumptions or {})
    pd = parse_date(pd)
    cat, notes = cat.upper(), []
    if cat not in CATEGORIES:
        raise ValueError("category must be one of %s" % ", ".join(CATEGORIES))
    if country not in COUNTRIES:
        raise ValueError("country must be one of %s" % ", ".join(COUNTRIES))

    month = latest_month(bulletins, "fad")
    fmonth = latest_month(bulletins, "dff")
    fad_now = cell(bulletins, month, "fad", cat, country) if month else None
    dff_now = cell(bulletins, fmonth, "dff", cat, country) if fmonth else None
    res = {"category": cat, "country": country, "priority_date": pd.isoformat(),
           "bulletin": month, "filing_bulletin": fmonth,
           "final_action_cutoff": fad_now, "filing_cutoff": dff_now,
           "final_action_current_now": is_current(fad_now, pd) if month else None,
           "filing_current_now": is_current(dff_now, pd) if fmonth else None}

    q = queue(inventory, awaiting, bulletins, cat, country, pd, a)
    t = trend(bulletins, "fad", cat, country, pd, a) if month else None
    tf = trend(bulletins, "dff", cat, country, pd, a) if month else None
    lead = filing_lead_months(bulletins, cat, country) if month else None
    res.update(queue=q, trend_final_action=t, trend_filing=tf, filing_lead_months=lead)

    # The inventory can be newer than the newest final-action chart we hold; its
    # Available / Awaiting flags then say more about today than the stale bulletin does.
    stale = bool(q) and (month is None or month < q["inventory_as_of"][:7])
    implied = dt.date.fromisoformat(q["inventory_implied_cutoff"]) if q and q["inventory_implied_cutoff"] else None
    res["notes"] = notes
    if stale and implied and res["final_action_current_now"] and pd >= implied:
        res["final_action_current_now"] = False
        notes.append("The cached bulletin (%s) shows this date as current, but the newer USCIS inventory (%s) marks "
                     "priority dates from about %s as awaiting a visa, so it is treated as not current."
                     % (month, q["inventory_as_of"], implied.strftime("%b %Y")))
    elif stale and q and not res["final_action_current_now"] and q["ahead_in_inventory"] > 0 and \
            pd < (implied or dt.date.max) and (implied or month is None) and \
            pd < dt.date.fromisoformat(q["inventory_horizon"]):
        if implied:
            res["final_action_current_now"] = True
            notes.append("The USCIS inventory as of %s marks this priority-date month as visa-available (awaiting "
                         "starts about %s); the cached final action chart (%s) is older."
                         % (q["inventory_as_of"], implied.strftime("%b %Y"), month or "none"))
    if res["final_action_current_now"]:
        res["headline"] = {"status": "current", "text": "Final action date is current now."}
        return res

    newest = max([m for m in (month, fmonth) if m], default=None)
    today = dt.date.fromisoformat(newest + "-01") if newest else (inventory["as_of"] if inventory else dt.date.today())
    cands = {s: [] for s in SCENARIOS}
    if q:
        for s in SCENARIOS:
            cands[s].append(max(today, dt.date.fromisoformat(q["scenarios"][s]["eta"])))
    if t and t.get("base"):
        for s in SCENARIOS:
            cands[s].append(dt.date.fromisoformat(t[s]))
    if not any(cands.values()):
        res["headline"] = {"status": "unknown", "text": "Not enough data to estimate."}
        return res
    # Base case: the queue method when it has data (it reflects the law), else the trend.
    base = dt.date.fromisoformat(q["scenarios"]["base"]["eta"]) if q else dt.date.fromisoformat(t["base"])
    base = max(base, today)
    early = min(cands["early"] + cands["base"])
    late = max(cands["late"] + cands["base"])
    spread = (late - early).days / 365.25
    wait = (base - today).days / 365.25
    if q and t and t.get("base"):
        tb = dt.date.fromisoformat(t["base"])
        gap = abs((tb - base).days) / 365.25
        agree = gap <= max(1.0, 0.35 * wait)
    else:
        agree = None
    confidence = "low" if (agree is False or wait > 15) else ("medium" if (agree is None or wait > 4) else "higher")
    res["headline"] = {"status": "waiting", "early": early.isoformat(), "base": base.isoformat(),
                       "late": late.isoformat(), "years_from_now": round(wait, 1),
                       "range_years": round(spread, 1), "methods_agree": agree, "confidence": confidence}
    if lead is not None and month:
        res["headline"]["filing_base"] = max(today, add_months(base, -int(round(lead)))).isoformat()
    if q and q["of_which_masked_estimate"] > 0.15 * max(1, q["ahead_in_inventory"]):
        notes.append("More than 15% of the people counted ahead come from cells USCIS masks as 'D'; "
                     "each is assumed to be 5.")
    if q and q["inventory_horizon"] and pd > dt.date.fromisoformat(q["inventory_horizon"]):
        notes.append("This priority date is later than the pending I-485 inventory reaches (%s). People ahead "
                     "beyond that point are estimated by spreading approved-petition totals evenly over "
                     "priority dates, which is an assumption." % q["inventory_horizon"])
    if wait > 15:
        notes.append("A wait this long means the estimate is really a statement that the line does not clear "
                     "under current law; a law or policy change would dominate it.")
    return res
