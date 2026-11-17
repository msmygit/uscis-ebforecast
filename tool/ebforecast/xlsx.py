"""Minimal .xlsx reader using only the standard library (no openpyxl needed)."""
import re
import zipfile
import xml.etree.ElementTree as ET

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
RNS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
PNS = "{http://schemas.openxmlformats.org/package/2006/relationships}"


def _col_index(ref):
    letters = re.match(r"[A-Z]+", ref).group(0)
    n = 0
    for ch in letters:
        n = n * 26 + (ord(ch) - 64)
    return n - 1


def read_workbook(path):
    """Return {sheet_name: [[cell, ...], ...]}; cells are str, int, float or None."""
    out = {}
    with zipfile.ZipFile(path) as z:
        shared = []
        if "xl/sharedStrings.xml" in z.namelist():
            root = ET.fromstring(z.read("xl/sharedStrings.xml"))
            for si in root.findall("m:si", NS):
                shared.append("".join(t.text or "" for t in si.iter("{%s}t" % NS["m"])))
        rels = {}
        for r in ET.fromstring(z.read("xl/_rels/workbook.xml.rels")).findall(PNS + "Relationship"):
            target = r.get("Target").lstrip("/")
            rels[r.get("Id")] = target if target.startswith("xl/") else "xl/" + target
        wb = ET.fromstring(z.read("xl/workbook.xml"))
        for sh in wb.find("m:sheets", NS).findall("m:sheet", NS):
            rows = []
            root = ET.fromstring(z.read(rels[sh.get(RNS + "id")]))
            for row in root.iter("{%s}row" % NS["m"]):
                idx = int(row.get("r")) - 1
                while len(rows) <= idx:
                    rows.append([])
                cells = rows[idx]
                for c in row.findall("m:c", NS):
                    ci = _col_index(c.get("r"))
                    while len(cells) <= ci:
                        cells.append(None)
                    t = c.get("t")
                    v = c.find("m:v", NS)
                    if t == "inlineStr":
                        val = "".join(x.text or "" for x in c.iter("{%s}t" % NS["m"]))
                    elif v is None or v.text is None:
                        val = None
                    elif t == "s":
                        val = shared[int(v.text)]
                    elif t in ("str", "b", "e"):
                        val = v.text
                    else:
                        f = float(v.text)
                        val = int(f) if f.is_integer() else f
                    if isinstance(val, str):
                        val = val.strip()
                    cells[ci] = val
            out[sh.get("name")] = rows
    return out
