#!/usr/bin/env python3
"""Employment-based priority date estimator.

  python3 -I tool/eb.py estimate EB2:India:2015-06-01 EB3:China:2021-03-15
  python3 -I tool/eb.py refresh          # pull new visa bulletins into the local cache
  python3 -I tool/eb.py import saved.html  # load a bulletin page saved from your browser
  python3 -I tool/eb.py page             # rebuild eb_priority_dates.html
  python3 -I tool/eb.py data             # show which USCIS files and bulletins are loaded
"""
import argparse
import datetime as dt
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)  # only the tool folder, never the folder holding downloaded files

from ebforecast import data, model  # noqa: E402

DATA_DIR = os.path.dirname(HERE)
CACHE = os.path.join(HERE, "cache", "bulletins.json")
ALIASES = {"row": "ROW", "world": "ROW", "all": "ROW", "india": "India", "china": "China",
           "mexico": "Mexico", "philippines": "Philippines",
           "eb5": "EB5-UNRESERVED", "eb-5": "EB5-UNRESERVED"}


def load_bulletins():
    if not os.path.exists(CACHE):
        return {}
    with open(CACHE) as f:
        return json.load(f).get("bulletins", {})


def load_all(data_dir):
    invs = data.load_inventories(data_dir)
    return load_bulletins(), (invs[-1] if invs else None), data.load_awaiting(data_dir)


def parse_query(q):
    parts = q.replace(",", ":").split(":")
    if len(parts) != 3:
        raise SystemExit("Query must look like EB2:India:2015-06-01 (got %r)" % q)
    cat = parts[0].upper().replace("EB-", "EB")
    cat = ALIASES.get(cat.lower(), cat)
    country = ALIASES.get(parts[1].strip().lower(), parts[1].strip())
    try:
        pd = dt.date.fromisoformat(parts[2].strip())
    except ValueError:
        raise SystemExit("Priority date must be YYYY-MM-DD (got %r)" % parts[2])
    return cat, country, pd


def fmt(d):
    if not d:
        return "n/a"
    d = dt.date.fromisoformat(d) if isinstance(d, str) else d
    return "after 2100" if d.year > 2100 else d.strftime("%b %Y")


def render(r):
    L = ["", "%s  %s  priority date %s" % (r["category"], r["country"], r["priority_date"]), "-" * 60]
    if r["bulletin"]:
        L.append("Final action cutoff %s (bulletin %s); filing cutoff %s (bulletin %s)"
                 % (r["final_action_cutoff"] or "n/a", r["bulletin"], r["filing_cutoff"] or "n/a",
                    r["filing_bulletin"] or "n/a"))
        if r["filing_bulletin"] and r["filing_bulletin"] > r["bulletin"]:
            L.append("Warning: final action dates in the cache stop at %s; newer bulletins are missing them." % r["bulletin"])
    else:
        L.append("No visa bulletin cache yet (run: eb.py refresh). Queue method only.")
    h = r["headline"]
    if h["status"] != "waiting":
        L.append(h["text"])
    else:
        L.append("Estimated final action: %s  (range %s to %s, about %.1f years, confidence %s)"
                 % (fmt(h["base"]), fmt(h["early"]), fmt(h["late"]), h["years_from_now"], h["confidence"]))
        if r.get("filing_current_now"):
            L.append("You can already file under the Dates for Filing chart when USCIS designates it.")
        elif h.get("filing_base"):
            L.append("Estimated filing eligibility: around %s (filing chart has led by ~%d months)"
                     % (fmt(h["filing_base"]), round(r["filing_lead_months"])))
    q = r.get("queue")
    if q:
        L.append("Queue method (inventory as of %s, line shared by %s):" % (q["inventory_as_of"], ", ".join(q["pool"])))
        L.append("  pending I-485s ahead: {:,}; approved petitions waiting in this line: {:,}".format(
            q["ahead_in_inventory"], q["approved_petitions_waiting"]))
        for s in model.SCENARIOS:
            v = q["scenarios"][s]
            L.append("  {:<5} {:>9,} people ahead / {:>7,} visas a year = {:>6} years -> {}".format(
                s, v["people_ahead"], v["visas_per_year"], v["years"], fmt(v["eta"])))
    t = r.get("trend_final_action")
    if t and t["windows"]:
        L.append("Trend method (final action cutoff now %s):" % t["cutoff_now"])
        for w in t["windows"]:
            L.append("  last %3d months: %6.1f days of priority date per month -> %s"
                     % (w["months"], w["days_per_month"], fmt(w["eta"]) if w["eta"] else "no forward movement"))
    for n in r.get("notes", []):
        L.append("Note: " + n)
    return "\n".join(L)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--data-dir", default=DATA_DIR, help="folder holding the USCIS .xlsx files")
    sub = p.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("estimate", help="estimate when priority dates become current")
    e.add_argument("queries", nargs="+", metavar="CATEGORY:COUNTRY:YYYY-MM-DD")
    e.add_argument("--json", action="store_true")
    e.add_argument("--set", action="append", default=[], metavar="KEY=VALUE",
                   help="override an assumption, e.g. --set eb_annual_limit=150000")
    r = sub.add_parser("refresh", help="download visa bulletins not yet in the cache")
    r.add_argument("--since", default="2015-10", help="earliest bulletin month, YYYY-MM")
    r.add_argument("--force", action="store_true", help="re-download months already cached")
    g = sub.add_parser("page", help="build the single-file HTML page")
    g.add_argument("--out", default=os.path.join(DATA_DIR, "eb_priority_dates.html"))
    sub.add_parser("data", help="summarise loaded data")
    im = sub.add_parser("import", help="load a bulletin page you saved from your browser")
    im.add_argument("file")
    im.add_argument("--month", help="YYYY-MM, if it cannot be read from the page")
    a = p.parse_args(argv)

    if a.cmd == "refresh":
        from ebforecast import bulletin
        bulletin.refresh(CACHE, since=a.since, force=a.force)
        return
    if a.cmd == "import":
        from ebforecast import bulletin
        bulletin.import_file(CACHE, a.file, a.month)
        return
    bulletins, inv, aw = load_all(a.data_dir)
    if a.cmd == "data":
        print("Data folder:", a.data_dir)
        for i in data.load_inventories(a.data_dir):
            print("  inventory %s as of %s: %d rows" % (i["file"], i["as_of"], len(i["rows"])))
        if aw:
            print("  approved petitions waiting: %s (as of %s)" % (aw["file"], aw["as_of"]))
        for q in data.load_i485_quarterly(a.data_dir):
            print("  I-485 FY%d Q%d employment-based: approved %s, pending %s" % (q["fy"], q["q"], f"{q['approved']:,}", f"{q['pending']:,}"))
        print("  visa bulletins cached: %d%s" % (len(bulletins), (" (%s to %s)" % (min(bulletins), max(bulletins))) if bulletins else ""))
        return
    if a.cmd == "page":
        from ebforecast import page
        page.build(a.out, a.data_dir, bulletins)
        print("Wrote", a.out)
        return
    overrides = {}
    for kv in a.set:
        k, _, v = kv.partition("=")
        overrides[k] = json.loads(v)
    results = [model.estimate(*parse_query(q), bulletins, inv, aw, overrides) for q in a.queries]
    print(json.dumps(results, indent=2) if a.json else "\n".join(render(x) for x in results))


if __name__ == "__main__":
    main()
