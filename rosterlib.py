#!/usr/bin/env python3
"""
rosterlib — read any roster spreadsheet, keep a permanent archive of shifts.

Two jobs, and they map onto the two ways this project has broken before.

1. READ A SHEET WE HAVE NEVER SEEN.
   Hospital rosters arrive in a new shape every term. Four layouts have turned
   up so far and every one got its own bespoke parser bolted onto the
   generator, keyed to a hardcoded filename and column number. This module
   reads the shape off the sheet instead:

     vertical    dates run DOWN a column, people ACROSS the header
     horizontal  dates run ACROSS a row, people DOWN column A or B
     day-numbers dates are bare integers (1..31) with a month name nearby

   Nothing is positional. The date cells are found by looking for dates, the
   person's row or column by looking for their name.

2. NEVER LOSE A SHIFT.
   On 2026-11-12 regenerating Charlie's feed produced 81 events against the
   159 that were live, because the August-December source had never been
   committed and the ICS was the only copy. The archive is the fix: every
   shift ever published is kept in history.json, and a rebuild merges onto it
   rather than replacing it. A source only overwrites the span of dates it
   actually covers, so adding next term cannot delete last term.

   Shrinking the feed therefore takes --allow-shrink and says so out loud.
"""

import csv
import json
import re
from datetime import datetime, date, timedelta
from pathlib import Path

try:
    import openpyxl
except ImportError:
    openpyxl = None

MONTHS = {m.lower(): i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july",
     "august", "september", "october", "november", "december"], 1)}

# Date formats seen in CSV exports of these rosters.
DATE_FORMATS = ("%d-%b-%y", "%d-%b-%Y", "%Y-%m-%d", "%d/%m/%Y", "%d/%m/%y")


# ============================================================
# CELL HELPERS
# ============================================================

def as_date(v, year_hint=None):
    """Return a date if this cell holds one, else None."""
    if isinstance(v, datetime):
        d = v.date()
    elif isinstance(v, date):
        d = v
    elif isinstance(v, str):
        s = v.strip()
        if not s:
            return None
        d = None
        for fmt in DATE_FORMATS:
            try:
                d = datetime.strptime(s, fmt).date()
                break
            except ValueError:
                continue
        if d is None:
            return None
    else:
        return None
    # Rosters are built from last term's workbook, so stale years survive in
    # cells nobody retyped: Emily's Term 2 sheet dates itself 2003. A roster is
    # always for now or later, never for the past, so anything earlier than the
    # expected year is that artefact and gets snapped forward. Later years are
    # left alone — a term really can run into January.
    if year_hint and d.year < year_hint:
        try:
            d = d.replace(year=year_hint)
        except ValueError:          # 29 Feb in a non-leap year
            d = d.replace(year=year_hint, day=28)
    return d


def text(v):
    return str(v).strip() if v is not None else ""


def name_matches(cell_text, person):
    """Does this cell name the person? First name alone is enough."""
    if not cell_text:
        return False
    t = cell_text.lower()
    if "reliever for" in t:      # a cover line, not the person's own row
        return False
    parts = [p for p in person.lower().split() if p]
    return t == person.lower() or all(p in t for p in parts) or (
        len(parts) > 1 and parts[0] in t.split()
    )


# ============================================================
# SHEET LOADING — everything becomes a list of rows of values
# ============================================================

def load_rows(path, sheet=None):
    """Read an xlsx sheet or a csv into a list-of-lists of cell values."""
    path = Path(path)
    if path.suffix.lower() in (".csv", ".tsv", ".txt"):
        delim = "\t" if path.suffix.lower() == ".tsv" else ","
        with open(path, encoding="utf-8-sig", newline="") as f:
            return [list(r) for r in csv.reader(f, delimiter=delim)], path.name

    if openpyxl is None:
        raise SystemExit("Missing dependency: pip3 install openpyxl")

    wb = openpyxl.load_workbook(path, data_only=True)
    ws = pick_sheet(wb, sheet)
    rows = [[c.value for c in row] for row in
            ws.iter_rows(min_row=1, max_row=ws.max_row, max_col=ws.max_column)]
    return rows, ws.title


def pick_sheet(wb, sheet=None):
    """
    Choose the sheet to read. Named sheet wins. Otherwise the sheet holding
    the most date cells — the roster grid — not simply the first one, because
    these workbooks lead with contacts, bios and teaching programs.
    """
    if sheet:
        for name in wb.sheetnames:
            if name.lower() == sheet.lower():
                return wb[name]
        raise SystemExit(f"Sheet {sheet!r} not in workbook: {wb.sheetnames}")

    # Guessing is only safe in a small workbook. The November roster has 21
    # sheets; "most date cells" lands on 'Pall Care + APS Allocation', whose
    # cells hold colleagues' names, and "most cells for this person" lands on
    # 'Weekly Master Roster', which is the same roster transposed and runs five
    # weeks past the end of the real one. Neither is 'Registrar'. No scoring
    # rule reliably tells a roster grid from its neighbours, so above a handful
    # of sheets this stops and asks instead of picking one and looking certain.
    dated = []
    for name in wb.sheetnames:
        ws = wb[name]
        n = 0
        for row in ws.iter_rows(min_row=1, max_row=min(ws.max_row, 200),
                                max_col=min(ws.max_column, 120)):
            for c in row:
                if isinstance(c.value, (datetime, date)):
                    n += 1
        if n:
            dated.append((ws, n))

    if not dated:
        return wb[wb.sheetnames[0]]
    if len(dated) > 3:
        names = ", ".join(ws.title for ws, _ in dated[:8])
        raise SystemExit(
            f"\n❌ This workbook has {len(wb.sheetnames)} sheets and "
            f"{len(dated)} of them hold dates, so the roster grid cannot be "
            f"picked safely.\n   Name it: --sheet \"Registrar\", or set "
            f'"sheet_hint" in sources.json.\n   Sheets with dates: {names}')
    return max(dated, key=lambda d: d[1])[0]


# ============================================================
# GRID READING
# ============================================================

def read_grid(path, person, sheet=None, year_hint=None, verbose=True):
    """
    Read one roster file and return {iso-date: raw-code} for `person`.

    Works out the layout from the content. Raises SystemExit with a useful
    message if the person or the dates cannot be found, rather than quietly
    returning an empty roster — an empty parse is what deletes a feed.
    """
    rows, sheet_name = load_rows(path, sheet)
    if not rows:
        raise SystemExit(f"{Path(path).name}: sheet {sheet_name!r} is empty")

    # Where do the dates live: one column, or one row?
    per_col, per_row = {}, {}
    for ri, row in enumerate(rows):
        for ci, v in enumerate(row):
            if as_date(v, year_hint):
                per_col[ci] = per_col.get(ci, 0) + 1
                per_row[ri] = per_row.get(ri, 0) + 1

    best_col_n = max(per_col.values()) if per_col else 0
    best_row_n = max(per_row.values()) if per_row else 0

    if best_col_n >= 10 and best_col_n >= best_row_n:
        shifts = _read_vertical(rows, person, year_hint)
        layout = "vertical (dates down a column)"
    elif best_row_n >= 3:
        shifts = _read_horizontal(rows, person, year_hint)
        layout = "horizontal (dates across a row)"
    else:
        shifts = _read_day_numbers(rows, person, year_hint)
        layout = "day numbers (integers with a month name)"

    if verbose:
        if shifts:
            lo, hi = min(shifts), max(shifts)
            print(f"  ✓ {Path(path).name} [{sheet_name}] {layout}")
            print(f"    {len(shifts)} dated cells for {person}: {lo} to {hi}")
        else:
            print(f"  ⚠️  {Path(path).name} [{sheet_name}] {layout}: nothing for {person}")
    return shifts


def _find_person_column(rows, person, first_date_row):
    """A person's column, from any header row above the first date row."""
    for ri in range(0, max(first_date_row, 1)):
        for ci, v in enumerate(rows[ri]):
            if name_matches(text(v), person):
                return ci
    # Some sheets repeat the header mid-grid; widen the search.
    for ri, row in enumerate(rows):
        for ci, v in enumerate(row):
            if name_matches(text(v), person):
                return ci
    return None


def _read_vertical(rows, person, year_hint):
    """Dates down one column, one column per person."""
    counts = {}
    for row in rows:
        for ci, v in enumerate(row):
            if as_date(v, year_hint):
                counts[ci] = counts.get(ci, 0) + 1
    date_col = max(counts, key=counts.get)
    first_date_row = next(ri for ri, row in enumerate(rows)
                          if len(row) > date_col and as_date(row[date_col], year_hint))

    col = _find_person_column(rows, person, first_date_row)
    if col is None:
        header = [text(v) for v in rows[max(first_date_row - 1, 0)] if text(v)]
        raise SystemExit(f"{person!r} not found. Names on this sheet: {header}")

    # A weekday-name column ("Monday", "Tuesday", ...) next to the dates is a
    # free check on whether we are reading the right column of the right rows.
    wd_col, wd_hits = None, 0
    for ci in range(min(len(rows[first_date_row]) if rows else 0, 12)):
        n = sum(1 for row in rows
                if ci < len(row) and text(row[ci]).lower() in WEEKDAY_NAMES)
        if n > wd_hits:
            wd_col, wd_hits = ci, n

    out, pairs = {}, []
    for row in rows:
        if len(row) <= date_col:
            continue
        d = as_date(row[date_col], year_hint)
        if not d or len(row) <= col:
            continue
        if wd_col is not None and wd_hits >= 10 and wd_col < len(row):
            want = WEEKDAY_NAMES.get(text(row[wd_col]).lower())
            if want is not None:
                pairs.append((d, want))
        code = text(row[col])
        if code and code not in ("0", "1", "None"):
            out[d.isoformat()] = code
    verify_weekdays(pairs, "vertical sheet")
    return out


def _read_horizontal(rows, person, year_hint):
    """
    Dates across a row, people down the first columns. Handles sheets built
    from repeated two-week blocks: each person row takes the dates from the
    nearest date row above it.
    """
    out = {}
    colmap = {}
    for row in rows:
        dates_here = {ci: as_date(v, year_hint) for ci, v in enumerate(row)
                      if as_date(v, year_hint)}
        if len(dates_here) >= 3:
            colmap = dates_here            # a new date row resets the mapping
            continue
        if not colmap:
            continue
        # Person rows name themselves in one of the first few columns.
        if not any(name_matches(text(v), person) for v in row[:3]):
            continue
        for ci, d in colmap.items():
            if ci >= len(row):
                continue
            code = text(row[ci])
            if code and code not in ("0", "1", "None"):
                out[d.isoformat()] = code
    return out


WEEKDAY_NAMES = {n.lower(): i for i, n in enumerate(
    ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
     "Saturday", "Sunday"])}

WEEKDAY_LETTERS = {
    "m": 0, "mo": 0, "mon": 0, "tu": 1, "tue": 1, "t": 1,
    "w": 2, "we": 2, "wed": 2, "th": 3, "thu": 3,
    "f": 4, "fr": 4, "fri": 4, "sa": 5, "sat": 5, "s": 6,
    "su": 6, "sun": 6,
}


def verify_weekdays(pairs, what):
    """
    Check dates against the roster's own weekday column or row.

    This is the project's "verify the artefact" rule applied to the calendar:
    the dates come out of one part of the sheet and the day names out of
    another, so when they agree the reading is confirmed rather than merely
    plausible. A mismatch means the layout has been misread, which is how a
    whole term quietly lands a day out.
    """
    bad = [(d, want) for d, want in pairs if d.weekday() != want]
    if bad:
        names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
                 "Saturday", "Sunday"]
        shown = ", ".join(f"{d} reads {names[d.weekday()]}, sheet says {names[w]}"
                          for d, w in bad[:3])
        raise SystemExit(
            f"\n❌ {what}: {len(bad)} of {len(pairs)} dates disagree with the "
            f"sheet's own day names.\n   {shown}\n"
            "   The layout has been misread — do not publish this.")
    if pairs:
        print(f"    ✓ all {len(pairs)} dates agree with the sheet's day names")


def _find_weekday_row(rows, day_row):
    """
    The row of M/Tu/W/Th/F/Sa/Su letters that these rosters print above the day
    numbers. It is a second, independent statement of the calendar, so it is
    what makes the day-number reading checkable instead of merely plausible.
    """
    for r in range(max(day_row - 4, 0), min(day_row + 4, len(rows))):
        if r == day_row:
            continue
        hits = sum(1 for v in rows[r]
                   if text(v).lower() in WEEKDAY_LETTERS and len(text(v)) <= 3)
        if hits >= 5:
            return {ci: WEEKDAY_LETTERS[text(v).lower()]
                    for ci, v in enumerate(rows[r])
                    if text(v).lower() in WEEKDAY_LETTERS and len(text(v)) <= 3}
    return {}


def _read_day_numbers(rows, person, year_hint):
    """
    Dates are bare day numbers across a row, with a month name somewhere in the
    header band. The columns are not a contiguous run of days, so the month is
    rolled over whenever the number drops.

    Every column is then checked against the weekday-letter row. Emily's Term 5
    sheet has 30 January followed by a Sunday typed "1": read literally that is
    1 February, which is a Monday, and it is what the published feed said. The
    weekday row disagrees, so the date is repaired to Sunday 31 January.
    """
    # Day-number row: the row with the most integers in 1..31.
    day_row, best = None, 0
    for ri, row in enumerate(rows[:60]):
        n = sum(1 for v in row if isinstance(v, int) and 1 <= v <= 31)
        if n > best:
            day_row, best = ri, n
    if day_row is None or best < 15:
        raise SystemExit("No date row and no day-number row found on this sheet")

    # First month name at or above the day-number row, and a year if present.
    month = year = None
    for ri in range(day_row, -1, -1):
        for v in rows[ri]:
            t = text(v).lower()
            if not t:
                continue
            if year is None:
                m = re.search(r"(20\d\d)", t)
                if m:
                    year = int(m.group(1))
            if month is None:
                for name, num in MONTHS.items():
                    if len(t) >= 3 and (t.startswith(name[:3]) or name in t):
                        month = num
                        break
        if month:
            break
    if month is None:
        raise SystemExit("Day numbers found but no month name — cannot date them")
    year = year or year_hint or date.today().year

    weekdays = _find_weekday_row(rows, day_row)
    colmap, repairs = {}, []
    prev_num = prev_date = None

    for ci, v in enumerate(rows[day_row]):
        if not isinstance(v, int) or not 1 <= v <= 31:
            continue
        if prev_num is not None and v < prev_num:
            month += 1
            if month == 13:
                month, year = 1, year + 1
        prev_num = v

        want = weekdays.get(ci)
        d = None
        # Candidates: this day number in the current month or either neighbour.
        for ym in ((year, month), (year, month + 1), (year, month - 1)):
            y, mo = ym
            if mo == 13:
                y, mo = y + 1, 1
            elif mo == 0:
                y, mo = y - 1, 12
            try:
                cand = date(y, mo, v)
            except ValueError:
                continue
            if prev_date and cand <= prev_date:
                continue
            if want is None or cand.weekday() == want:
                d = cand
                break

        if d is None and prev_date and want is not None:
            # The day number cannot be reconciled with the weekday row. Walk
            # forward from the previous column to the next matching weekday —
            # a mistyped number, which these sheets do contain.
            step = (want - prev_date.weekday()) % 7 or 7
            d = prev_date + timedelta(days=step)
            repairs.append((v, d))
        if d is None:
            continue

        colmap[ci] = d
        prev_date = d
        year, month = d.year, d.month

    if repairs:
        print(f"    ⓘ {len(repairs)} date(s) repaired from the weekday row "
              f"(the sheet's day number disagreed): "
              + ", ".join(f"typed {n} → {d}" for n, d in repairs[:4]))
    if not colmap:
        return {}
    verify_weekdays([(d, weekdays[ci]) for ci, d in colmap.items()
                     if ci in weekdays], "day-number sheet")

    person_row = None
    for ri, row in enumerate(rows):
        if any(name_matches(text(v), person) for v in row[:3]):
            person_row = ri
            break
    if person_row is None:
        raise SystemExit(f"{person!r} not found in the first three columns of this sheet")

    out = {}
    for ci, d in colmap.items():
        row = rows[person_row]
        code = text(row[ci]) if ci < len(row) else ""
        # A blank cell means different things on different rosters, so it is
        # left for the caller's code table to interpret.
        out[d.isoformat()] = code
    return out


# ============================================================
# ARCHIVE — the permanent record of published shifts
# ============================================================

def load_archive(path):
    path = Path(path)
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("shifts", data)


def save_archive(path, shifts, sources):
    Path(path).write_text(json.dumps({
        "_comment": "Every shift ever published. Rebuilds merge onto this, "
                    "so losing a source spreadsheet cannot lose a shift. "
                    "Generated by roster.py — safe to read, do not hand-edit.",
        "updated":  datetime.now().isoformat(timespec="seconds"),
        "sources":  sources,
        "shifts":   dict(sorted(shifts.items())),
    }, indent=1) + "\n", encoding="utf-8")


def merge_source(archive, new, label="", source=None, span=None):
    """
    Overlay `new` onto `archive` across the span of dates the source covers.
    Dates outside that span are left alone, so a one-term sheet can never wipe
    another term.

    Entries the SAME source put there last time are also cleared first, even
    when they fall outside the new span. Otherwise a date the sheet has since
    corrected lingers for ever: Term 5's last cell was misread as 1 February,
    and when the date was fixed to 31 January the 1 February event stayed in
    the feed, past the end of everything the corrected sheet covers.
    """
    if not new:
        return archive, 0, 0
    lo, hi = span if span else (min(new), max(new))
    lo, hi = min(lo, min(new)), max(hi, max(new))
    before = dict(archive)
    merged = {k: v for k, v in archive.items()
              if not (lo <= k <= hi)
              and not (source and v.get("source") == source)}
    merged.update(new)
    for k, v in before.items():          # keep anything outside the span
        if source and v.get("source") == source and k not in new:
            continue                     # …except what this source has dropped
        merged.setdefault(k, v)
    added   = sum(1 for k in merged if k not in before)
    changed = sum(1 for k in merged if k in before and merged[k] != before[k])
    if label:
        print(f"    merged {label}: span {lo} to {hi}, "
              f"+{added} new, {changed} changed")
    return merged, added, changed


def check_not_shrinking(before, after, allow_shrink=False):
    """
    Refuse to publish fewer shifts than last time unless told to. This is the
    guard that the 2026-11-12 near-miss earned.
    """
    lost = sorted(set(before) - set(after))
    if not lost:
        return
    msg = (f"\n❌ This build drops {len(lost)} shifts that are already "
           f"published:\n   {lost[0]} … {lost[-1]}\n"
           "   A source file is probably missing, or a sheet parsed empty.\n"
           "   Re-run with --allow-shrink if the removal is deliberate.")
    if not allow_shrink:
        raise SystemExit(msg)
    print(msg.replace("❌", "⚠️ ") + "\n   (--allow-shrink given, continuing)")


# ============================================================
# CODE TABLES — hours, type and label, in one file per person
# ============================================================

def load_codes(path):
    t = json.loads(Path(path).read_text(encoding="utf-8"))
    t.setdefault("codes", {})
    t.setdefault("default_day", ["08:00", "20:30"])
    t.setdefault("default_night", ["20:00", "08:30"])
    return t


def to_decimal(hhmm):
    h, m = str(hhmm).split(":")
    return int(h) + int(m) / 60.0


def resolve(raw, table, fallback=None, source=""):
    """
    Turn {iso: raw-code} into {iso: {code, type, label, start, end}} using the
    code table. Returns (resolved, unknown) where `unknown` lists codes with no
    entry in the table.

    An unknown code is never dropped. It is carried through as a working day
    with default hours and reported, because a missing shift on the website is
    invisible while a shift with the wrong label is obvious and gets fixed.
    """
    codes   = table["codes"]
    out     = {}
    unknown = {}
    fallback = fallback or {}

    for iso, rawcode in sorted(raw.items()):
        d = date.fromisoformat(iso)
        code = (rawcode or "").strip()

        if not code:
            key = "blank_weekend" if d.weekday() >= 5 else "blank_weekday"
            code = table.get(key) or ""
            if not code:
                continue

        if code in ("0", "1", "None"):
            continue

        # Cells are typed by hand, so the same shift arrives as "D10WE",
        # "D10 WE " and "E10 (1100 - 2100)". Aliases absorb that without a
        # parser change; each new term usually adds one or two.
        alias = table.get("aliases", {})
        if code in alias:
            code = alias[code]
        entry = codes.get(code)
        if entry is None:
            squashed = " ".join(code.split())
            for k, v in list(alias.items()) + list(codes.items()):
                if " ".join(k.split()).lower() == squashed.lower():
                    code = alias.get(k, k) if k in alias else k
                    entry = codes.get(code)
                    break
        if entry is None:
            unknown.setdefault(code, []).append(iso)
            prev = fallback.get(iso)
            if prev and prev.get("code") == code:
                out[iso] = dict(prev, source=source or prev.get("source", ""))
                continue
            entry = {"type": "day", "label": code}

        stype = entry.get("type", "day")
        item  = {"code": code, "type": stype, "label": entry.get("label", code)}
        if stype not in ("off", "holiday"):
            hours = entry.get("hours")
            if not hours:
                hours = table["default_night"] if stype == "night" else table["default_day"]
            item["start"], item["end"] = hours[0], hours[1]
        if source:
            item["source"] = source
        out[iso] = item

    return out, unknown


def report_unknown(unknown, codes_path):
    if not unknown:
        return
    print(f"\n  ⚠️  {len(unknown)} code(s) are not in {codes_path}:")
    for code, dates in sorted(unknown.items()):
        span = dates[0] if len(dates) == 1 else f"{dates[0]} … {dates[-1]}"
        print(f"      {code!r} on {len(dates)} day(s): {span}")
    print("      They are published as ordinary day shifts with default hours.")
    print(f"      Add them to {codes_path} to fix the hours and the label.")


def apply_overrides(shifts, overrides, table):
    """
    Apply manual overrides from the manifest, last, on top of every source.

    These are the facts no spreadsheet knows: a fortnight of annual leave that
    the roster still shows as working, a swap agreed in the tearoom. Keeping
    them in the manifest rather than editing a sheet or the archive means a
    rebuild cannot quietly undo them — which is what happened to Emily's July
    holiday the first time her term sheet was widened to cover it.
    """
    if not overrides:
        return shifts
    applied = 0
    for ov in overrides:
        code  = ov["code"]
        entry = table["codes"].get(code, {"type": "off", "label": code})
        start = date.fromisoformat(ov["from"])
        end   = date.fromisoformat(ov.get("to", ov["from"]))
        d = start
        while d <= end:
            item = {"code": code,
                    "type":  entry.get("type", "off"),
                    "label": ov.get("label") or entry.get("label", code),
                    "source": "override: " + ov.get("note", "")}
            if item["type"] not in ("off", "holiday"):
                hours = entry.get("hours") or (
                    table["default_night"] if item["type"] == "night"
                    else table["default_day"])
                item["start"], item["end"] = hours[0], hours[1]
            shifts[d.isoformat()] = item
            applied += 1
            d += timedelta(days=1)
    print(f"    applied {applied} override day(s) from the manifest")
    return shifts
