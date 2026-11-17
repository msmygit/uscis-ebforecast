"""Visa bulletin cache: download, parse and store employment-based cutoff dates.

Sources, in order:
  1. travel.state.gov (the State Department bulletin). It usually refuses automated
     requests with HTTP 403; when it does we do not try to get around it.
  2. The Internet Archive's saved copy of the same bulletin page.
  3. The USCIS monthly "when to file" page, which shows only the chart USCIS designated
     for that month.
A bulletin page saved from a browser can also be loaded with import_file().
"""
import datetime as dt
import gzip
import html
import json
import os
import re
import shutil
import subprocess
import time
import urllib.error
import urllib.request

UA = "eb-priority-date-estimator/1.0 (personal research script)"
MONTHS = ["january", "february", "march", "april", "may", "june", "july",
          "august", "september", "october", "november", "december"]
MON3 = [m[:3].upper() for m in MONTHS]
DOS = "https://travel.state.gov/content/travel/en/legal/visa-law0/visa-bulletin/{fy}/visa-bulletin-for-{month}-{year}.html"
WAYBACK = "http://web.archive.org/web/{ts}id_/{url}"
USCIS_INDEX = ("https://www.uscis.gov/green-card/green-card-processes-and-procedures/"
               "visa-availability-priority-dates/adjustment-of-status-filing-charts-from-the-visa-bulletin")


def fetch(url, timeout=40):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Encoding": "gzip"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    return raw.decode("utf-8", errors="replace")


def _text(fragment):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", fragment)).replace("\xa0", " ")).strip()


def parse_cutoff(s):
    """'01JUN23' -> '2023-06-01'; 'C'/'U' pass through; anything else -> None."""
    s = s.strip().upper()
    if s in ("C", "U"):
        return s
    m = re.fullmatch(r"(\d{2})([A-Z]{3})(\d{2})", s)
    if not m or m.group(2) not in MON3:
        return None
    yy = int(m.group(3))
    year = 2000 + yy if yy <= 40 else 1900 + yy
    try:
        return dt.date(year, MON3.index(m.group(2)) + 1, int(m.group(1))).isoformat()
    except ValueError:
        return None


def _country(label):
    u = label.upper()
    if "ALL CHARGEABILITY" in u:
        return "ROW"
    for key, name in (("CHINA", "China"), ("INDIA", "India"), ("MEXICO", "Mexico"), ("PHILIPPINES", "Philippines")):
        if u.startswith(key):
            return name
    return None


def _category(label):
    u = label.upper()
    if u.startswith("1ST"):
        return "EB1"
    if u.startswith("2ND"):
        return "EB2"
    if u.startswith("3RD"):
        return "EB3"
    if u.startswith("OTHER WORKERS"):
        return "EW3"
    if u.startswith("4TH"):
        return "EB4"
    if u.startswith("CERTAIN RELIGIOUS"):
        return "CRW"
    if u.startswith("5TH"):
        if "RURAL" in u:
            return "EB5-RURAL"
        if "HIGH UNEMPLOYMENT" in u:
            return "EB5-HIGH-UNEMPLOYMENT"
        if "INFRASTRUCTURE" in u:
            return "EB5-INFRASTRUCTURE"
        if "UNRESERVED" in u or "NON-REGIONAL" in u or u.strip() == "5TH":
            return "EB5-UNRESERVED"
    return None


def _eb_tables(page):
    """Yield (table_dict, text_before, caption) for each employment-based cutoff table."""
    for m in re.finditer(r"<table.*?</table>", page, re.S | re.I):
        t = m.group(0)
        rows = [[_text(c) for c in re.findall(r"<t[dh].*?</t[dh]>", r, re.S | re.I)]
                for r in re.findall(r"<tr.*?</tr>", t, re.S | re.I)]
        rows = [r for r in rows if r]
        if not rows or not any(r[0].upper().startswith("OTHER WORKERS") for r in rows):
            continue
        cols = [_country(c) for c in rows[0]]
        table = {}
        for r in rows[1:]:
            cat = _category(r[0])
            if not cat:
                continue
            for c, v in zip(cols[1:], r[1:]):
                if c and parse_cutoff(v):
                    table.setdefault(cat, {})[c] = parse_cutoff(v)
        cap = re.search(r"<caption.*?</caption>", t, re.S | re.I)
        yield table, _text(page[max(0, m.start() - 2500):m.start()]), _text(cap.group(0)) if cap else ""


def parse_dos(page):
    """State Department bulletin HTML -> {'fad': {...}, 'dff': {...}} (either may be missing)."""
    out = {}
    for table, before, _ in _eb_tables(page):
        tail = before[-700:].lower()
        chart = "dff" if ("may file" in tail or "dates for filing" in tail) else "fad"
        if table and chart not in out:
            out[chart] = table
    return out


def parse_uscis(page):
    """USCIS monthly page -> (month 'YYYY-MM' or None, chart 'fad'/'dff' or None, table)."""
    month = None
    for h in re.findall(r"<h[1-3][^>]*>(.*?)</h[1-3]>", page, re.S | re.I):
        m = re.fullmatch(r"(\w+) (\d{4})", _text(h))
        if m and m.group(1).lower() in MONTHS:
            month = "%s-%02d" % (m.group(2), MONTHS.index(m.group(1).lower()) + 1)
            break
    for table, before, caption in _eb_tables(page):
        label = (caption or before[-300:]).lower()
        chart = "dff" if "dates for filing" in label else ("fad" if "final action" in label else None)
        if table:
            return month, chart, table
    return month, None, None


def dos_url(month):
    y, m = int(month[:4]), int(month[5:7])
    return DOS.format(fy=y + 1 if m >= 10 else y, month=MONTHS[m - 1], year=y)


def month_range(since, until):
    y, m = int(since[:4]), int(since[5:7])
    while "%04d-%02d" % (y, m) <= until:
        yield "%04d-%02d" % (y, m)
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def load(cache_path):
    if os.path.exists(cache_path):
        with open(cache_path) as f:
            return json.load(f)
    return {"bulletins": {}}


def save(cache_path, cache):
    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
    cache["updated"] = dt.date.today().isoformat()
    tmp = cache_path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(cache, f, indent=1, sort_keys=True)
    os.replace(tmp, cache_path)


def _merge(entry, chart, table, source):
    if table and chart and chart not in entry:
        entry[chart] = table
        entry.setdefault("sources", {})[chart] = source


def refresh(cache_path, since="2015-10", force=False, log=print, pause=1.0):
    cache = load(cache_path)
    b = cache["bulletins"]
    today = dt.date.today()
    nxt = (today.replace(day=1) + dt.timedelta(days=32)).strftime("%Y-%m")  # next month's bulletin may be out
    months = list(month_range(since, nxt))
    if force:
        for m in months:
            b.pop(m, None)
    need = [m for m in months if not {"fad", "dff"} <= set(b.get(m, {}))]
    log("%d months to check (%s to %s)" % (len(need), since, nxt))

    # 1. State Department directly: one attempt tells us whether automated access is allowed.
    direct_ok = True
    for m in sorted(need, reverse=True):
        if not direct_ok:
            break
        try:
            got = parse_dos(fetch(dos_url(m)))
            for chart, table in got.items():
                _merge(b.setdefault(m, {}), chart, table, "travel.state.gov")
            time.sleep(pause)
        except urllib.error.HTTPError as e:
            if e.code == 403:
                direct_ok = False
                log("travel.state.gov refuses automated requests (HTTP 403); using the Internet Archive and USCIS instead.")
            elif e.code != 404:
                log("  %s: travel.state.gov HTTP %s" % (m, e.code))
        except Exception as e:  # network trouble: stop trying direct, fall through
            direct_ok = False
            log("travel.state.gov not reachable (%s)" % e)

    # 2. Internet Archive copy of the State Department page.
    need = [m for m in months if not {"fad", "dff"} <= set(b.get(m, {}))]
    for i, m in enumerate(need):
        url = WAYBACK.format(ts=m.replace("-", "") + "20", url=dos_url(m))
        for attempt in range(3):
            try:
                got = parse_dos(fetch(url))
                for chart, table in got.items():
                    _merge(b.setdefault(m, {}), chart, table, "web.archive.org copy of travel.state.gov")
                break
            except urllib.error.HTTPError as e:
                if e.code in (429, 500, 502, 503, 504) and attempt < 2:
                    time.sleep(10 * (attempt + 1))
                    continue
                break
            except Exception:
                time.sleep(5)
        if (i + 1) % 20 == 0:
            log("  archive: %d/%d" % (i + 1, len(need)))
            save(cache_path, cache)
        time.sleep(pause)
    save(cache_path, cache)

    # 3. USCIS monthly pages: which chart USCIS designated, plus that chart's dates.
    need_uscis = [m for m in months if "uscis_chart" not in b.get(m, {}) or not {"fad", "dff"} <= set(b.get(m, {}))]
    if need_uscis:
        try:
            index = fetch(USCIS_INDEX)
            links = []
            for href in re.findall(r'href="([^"]*when-to-file-your-adjustment-of-status-application[^"]*)"', index):
                href = re.sub(r"^https?://[^/]+", "", href)
                if href not in links:
                    links.append(href)
            known = {b[m].get("uscis_url") for m in b}
            for i, href in enumerate(links):
                if href in known and not force:
                    continue
                try:
                    month, chart, table = parse_uscis(fetch("https://www.uscis.gov" + href))
                except Exception as e:
                    log("  USCIS page failed: %s (%s)" % (href[-12:], e))
                    continue
                if month and since <= month <= nxt:
                    entry = b.setdefault(month, {})
                    entry["uscis_url"] = href
                    if chart:
                        entry["uscis_chart"] = chart
                        _merge(entry, chart, table, "uscis.gov monthly filing chart")
                if (i + 1) % 20 == 0:
                    log("  USCIS: %d/%d" % (i + 1, len(links)))
                    save(cache_path, cache)
                time.sleep(pause / 2)
        except Exception as e:
            log("USCIS index not reachable (%s)" % e)
    save(cache_path, cache)
    have = sorted(m for m in b if "fad" in b[m] or "dff" in b[m])
    fad = sorted(m for m in b if "fad" in b[m])
    dff = sorted(m for m in b if "dff" in b[m])
    log("Cache now holds %d bulletins. Final action dates through %s; dates for filing through %s."
        % (len(have), fad[-1] if fad else "n/a", dff[-1] if dff else "n/a"))
    return cache


PDF_ROWS = ["EB1", "EB2", "EB3", "EW3", "EB4", "CRW", "EB5-UNRESERVED", "EB5-RURAL",
            "EB5-HIGH-UNEMPLOYMENT", "EB5-INFRASTRUCTURE"]
_TOK = r"(C|U|\d{2}[A-Z]{3}\d{2})"
_ROW = re.compile(r"^\s*\S.*?\s+" + r"\s+".join([_TOK] * 5) + r"\s*$")
_COLS = ["ROW", "China", "India", "Mexico", "Philippines"]


def parse_pdf_text(text):
    """Text from `pdftotext -layout` of a State Department bulletin -> (month, {'fad','dff'})."""
    month = None
    m = re.search(r"Immigrant Numbers for (\w+) (\d{4})", text)
    if m and m.group(1).lower() in MONTHS:
        month = "%s-%02d" % (m.group(2), MONTHS.index(m.group(1).lower()) + 1)
    a = re.search(r"A\.\s+Final Action Dates for Employment-Based", text)
    b = re.search(r"B\.\s+Dates for Filing of Employment-Based", text)
    out = {}
    for chart, start, end in (("fad", a, b), ("dff", b, None)):
        if not start:
            continue
        chunk = text[start.end():end.start() if end else len(text)]
        rows = []
        for line in chunk.splitlines():
            r = _ROW.match(line)
            if r:
                rows.append(r.groups())
            if len(rows) == len(PDF_ROWS):
                break
        if len(rows) == len(PDF_ROWS):
            out[chart] = {cat: {c: parse_cutoff(v) for c, v in zip(_COLS, vals)}
                          for cat, vals in zip(PDF_ROWS, rows)}
    return month, out


def import_pdf(cache_path, path, month=None, log=print):
    exe = shutil.which("pdftotext")
    if not exe:
        raise SystemExit("Reading PDFs needs pdftotext (brew install poppler); or save the web page as .html instead.")
    text = subprocess.run([exe, "-layout", path, "-"], capture_output=True, text=True, check=True).stdout
    pm, got = parse_pdf_text(text)
    month = month or pm
    if not month or len(got) < 2:
        raise SystemExit("Could not read both employment tables from %s." % path)
    cache = load(cache_path)
    entry = cache["bulletins"].setdefault(month, {})
    for chart, table in got.items():
        entry[chart] = table
        entry.setdefault("sources", {})[chart] = "State Department PDF " + os.path.basename(path)
    save(cache_path, cache)
    log("Imported %s from PDF: %s" % (month, ", ".join(sorted(got))))


def import_file(cache_path, path, month=None, log=print):
    if path.lower().endswith(".pdf"):
        return import_pdf(cache_path, path, month, log)
    """Load a bulletin page saved from a browser (State Department or USCIS)."""
    with open(path, "rb") as f:
        raw = f.read()
    page = (gzip.decompress(raw) if raw[:2] == b"\x1f\x8b" else raw).decode("utf-8", errors="replace")
    cache = load(cache_path)
    if not month:
        m = re.search(r"Visa Bulletin [Ff]or (\w+) (\d{4})", _text(page))
        if m and m.group(1).lower() in MONTHS:
            month = "%s-%02d" % (m.group(2), MONTHS.index(m.group(1).lower()) + 1)
    got = parse_dos(page)
    if len(got) < 2:
        um, chart, table = parse_uscis(page)
        month = month or um
        got = {chart: table} if chart and table and not got else got
    if not month or not got:
        raise SystemExit("Could not read a bulletin from %s (pass --month YYYY-MM if the month was not detected)." % path)
    entry = cache["bulletins"].setdefault(month, {})
    for chart, table in got.items():
        entry[chart] = table
        entry.setdefault("sources", {})[chart] = "imported file " + os.path.basename(path)
    save(cache_path, cache)
    log("Imported %s: %s" % (month, ", ".join(sorted(got))))
