#!/usr/bin/env python3
"""
Tests for rosterlib. Run with:  python3 test_rosterlib.py

These exist because the failures this project has actually had were all silent:
a parser that returned 81 shifts instead of 159, a guard that never fired, a
date column read a day out. Each test below is one of those.
"""

import json
import sys
import tempfile
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import rosterlib as R

passed = failed = 0


def check(name, fn):
    global passed, failed
    try:
        fn()
        passed += 1
        print(f"  ✓ {name}")
    except AssertionError as e:
        failed += 1
        print(f"  ✗ {name}: {e}")
    except Exception as e:
        failed += 1
        print(f"  ✗ {name}: {type(e).__name__}: {e}")


TABLE = {
    "default_day": ["08:00", "20:30"],
    "default_night": ["20:00", "08:30"],
    "blank_weekday": "A",
    "aliases": {"D10 WE": "D10WE"},
    "codes": {
        "A":     {"hours": ["08:00", "16:30"], "type": "day",   "label": "Wards"},
        "N":     {"hours": ["20:00", "08:30"], "type": "night", "label": "Night"},
        "D10WE": {"hours": ["07:00", "17:30"], "type": "day",   "label": "Day WE"},
        "AL":    {"type": "off", "label": "Leave"},
    },
}


# ── the near-miss of 2026-11-12 ───────────────────────────────

def t_merge_only_touches_its_own_span():
    archive = {"2026-03-01": {"code": "N"}, "2026-09-01": {"code": "A"}}
    new     = {"2026-03-01": {"code": "A"}}        # a sheet covering March only
    merged, _, _ = R.merge_source(archive, new)
    assert merged["2026-03-01"]["code"] == "A", "March should be overwritten"
    assert "2026-09-01" in merged, "September must survive a March-only sheet"


def t_resupplying_a_source_clears_what_it_used_to_say():
    """Term 5's last cell was misread as 1 Feb; when it was corrected to 31 Jan
    the 1 Feb event stayed, because it sat past everything the fixed sheet
    covers. A source now clears its own previous entries."""
    archive = {"2027-02-01": {"code": "A", "source": "Term 5"},
               "2026-01-01": {"code": "A", "source": "Term 1"}}
    new = {"2027-01-31": {"code": "A", "source": "Term 5"}}
    merged, _, _ = R.merge_source(archive, new, source="Term 5")
    assert "2027-02-01" not in merged, "a corrected date must not linger"
    assert "2027-01-31" in merged
    assert "2026-01-01" in merged, "another source's dates must survive"


def t_guard_refuses_a_shrinking_build():
    before = {"2026-03-01": {}, "2026-09-01": {}}
    after  = {"2026-03-01": {}}
    try:
        R.check_not_shrinking(before, after)
    except SystemExit:
        return
    raise AssertionError("a build that drops a published shift must stop")


def t_guard_allows_a_shrink_when_told():
    R.check_not_shrinking({"2026-03-01": {}}, {}, allow_shrink=True)


def t_empty_parse_cannot_wipe_the_archive():
    archive = {"2026-03-01": {"code": "N"}}
    merged, _, _ = R.merge_source(dict(archive), {})
    assert merged == archive, "an empty parse must change nothing"


# ── the calendar, verified rather than assumed ───────────────

def t_weekday_mismatch_is_fatal():
    try:
        R.verify_weekdays([(date(2027, 1, 14), 4)], "test")   # a Thursday called Friday
    except SystemExit:
        return
    raise AssertionError("dates that disagree with the sheet's day names must stop a build")


def t_weekday_agreement_passes():
    R.verify_weekdays([(date(2027, 1, 14), 3)], "test")       # Thursday is Thursday


def t_stale_year_snaps_forward_but_later_years_do_not():
    assert R.as_date("31-Aug-03", year_hint=2026).year == 2026
    assert R.as_date(date(2027, 1, 15), year_hint=2026).year == 2027


# ── codes ────────────────────────────────────────────────────

def t_blank_weekday_is_a_working_day_weekend_is_not():
    got, _ = R.resolve({"2026-11-16": "", "2026-11-21": ""}, TABLE)   # Mon, Sat
    assert got["2026-11-16"]["code"] == "A", got
    assert "2026-11-21" not in got, "a blank weekend is not a shift"


def t_blank_public_holiday_is_not_a_working_day():
    """Emily's JMO roster: blank weekday = ward day, but a blank on a public
    holiday is a day off. Christmas 2026 is a Friday; Boxing Day is a Saturday,
    so Monday 28 Dec is the additional day."""
    got, _ = R.resolve({"2026-12-25": "", "2026-12-28": "", "2026-12-29": "",
                        "2027-01-26": "", "2026-06-08": ""}, TABLE)
    for d in ("2026-12-25", "2026-12-28", "2027-01-26", "2026-06-08"):
        assert d not in got or got[d]["type"] == "off", f"{d}: {got.get(d)}"
    assert got["2026-12-29"]["code"] == "A", "an ordinary weekday is still a ward day"


def t_typed_shift_on_a_public_holiday_still_counts():
    got, _ = R.resolve({"2026-12-25": "N"}, TABLE)
    assert got["2026-12-25"]["code"] == "N"


def t_extra_holidays_such_as_picnic_day():
    table = dict(TABLE, extra_holidays={"2026-11-18": "Picnic Day"})
    got, _ = R.resolve({"2026-11-18": ""}, table)
    assert "2026-11-18" not in got, got


def t_nsw_holidays_known_dates():
    h = R.nsw_public_holidays(2026)
    for d in ("2026-01-01", "2026-01-26", "2026-04-03", "2026-04-06",
              "2026-06-08", "2026-10-05", "2026-12-25", "2026-12-28"):
        assert date.fromisoformat(d) in h, d
    assert date(2026, 4, 27) not in h, "Anzac Day has no substitute in NSW"
    assert date(2027, 3, 26) in R.nsw_public_holidays(2027), "Good Friday 2027"


def t_alias_and_sloppy_spacing_resolve():
    got, unk = R.resolve({"2026-08-01": "D10 WE", "2026-08-02": " d10we "}, TABLE)
    assert not unk, f"should not be unknown: {unk}"
    assert got["2026-08-01"]["code"] == "D10WE"
    assert got["2026-08-02"]["code"] == "D10WE"


def t_unknown_code_is_reported_but_never_dropped():
    got, unk = R.resolve({"2026-08-03": "ZZZ"}, TABLE)
    assert "ZZZ" in unk, "an unknown code must be reported"
    assert "2026-08-03" in got, "an unknown code must still reach the website"
    assert got["2026-08-03"]["start"] == "08:00", "it falls back to default day hours"


def t_night_hours_survive_resolution():
    got, _ = R.resolve({"2026-08-04": "N"}, TABLE)
    assert (got["2026-08-04"]["start"], got["2026-08-04"]["end"]) == ("20:00", "08:30")


def t_off_codes_carry_no_hours():
    got, _ = R.resolve({"2026-08-05": "AL"}, TABLE)
    assert "start" not in got["2026-08-05"]


def t_overrides_win_over_every_source():
    shifts = {"2026-07-14": {"code": "A", "type": "day", "label": "Wards"}}
    out = R.apply_overrides(shifts, [{"from": "2026-07-13", "to": "2026-07-15",
                                      "code": "AL", "note": "holiday"}], TABLE)
    assert out["2026-07-14"]["code"] == "AL", "an override must beat the sheet"
    assert out["2026-07-13"]["code"] == "AL" and out["2026-07-15"]["code"] == "AL"


# ── archive round trip ───────────────────────────────────────

def t_archive_round_trip():
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "history.json"
        R.save_archive(p, {"2026-08-06": {"code": "A"}}, ["a source"])
        assert R.load_archive(p) == {"2026-08-06": {"code": "A"}}
        assert "sources" in json.loads(p.read_text())


def _day_number_grid(rows_of_people):
    """A day-number sheet for December 2026: month name, weekday letters,
    day numbers, then one row per (team, name, {day: code})."""
    letters = ["M", "Tu", "W", "Th", "F", "Sa", "Su"]
    days = list(range(1, 19))
    head = ["", "", "December 2026"] + [""] * (len(days) - 1)
    wd = ["", ""] + [letters[date(2026, 12, d).weekday()] for d in days]
    nums = ["", ""] + days
    out = [head, wd, nums]
    for team, name, codes in rows_of_people:
        out.append([team, name] + [codes.get(d, "") for d in days])
    return out


def t_a_colleague_with_the_same_first_name_is_not_her():
    """The Term 5 sheet has Emily Greenberg nine rows above Emily Cooke."""
    assert R.name_matches("Emily Cooke", "Emily Cooke")
    assert R.name_matches("Emily", "Emily Cooke"), "first names only is a layout"
    assert R.name_matches("Emily C", "Emily Cooke")
    assert R.name_matches("Emily Cooke / Charlie Nasra", "Emily Cooke")
    assert not R.name_matches("Emily Greenberg", "Emily Cooke")
    assert not R.name_matches("Charlie Nasra / Anna Lubomski Reliever for "
                             "Emily Cooke", "Emily Cooke")


def t_the_other_emilys_row_is_not_read():
    """The 2026-11-13 failure: her whole term came off row 39 instead of 48,
    so Christmas read as a surgical shift when her own row says PH."""
    rows = _day_number_grid([
        ("Surgery C", "Emily Greenberg", {3: "S", 4: "S"}),
        ("Community Psychiatry", "Emily Cooke", {3: "PH"}),
    ])
    got = R._read_day_numbers(rows, "Emily Cooke", 2026)
    assert got["2026-12-03"] == "PH", got["2026-12-03"]
    assert got["2026-12-04"] == "", "that S is Greenberg's"


def t_two_names_that_fit_equally_well_stop_the_build():
    rows = _day_number_grid([
        ("Surgery C", "Emily", {3: "S"}),
        ("Community Psychiatry", "Emily C", {3: "PH"}),
    ])
    try:
        R._read_day_numbers(rows, "Emily Cooke", 2026)
    except SystemExit as e:
        assert "different names" in str(e), e
    else:
        assert False, "an ambiguous name must not be guessed at"


# ── the real sheets, if they are on this machine ─────────────

def t_real_sheets_still_parse():
    root = Path(__file__).parent
    for person in ("charlie", "emily"):
        man = json.loads((root / person / "sources.json").read_text())
        for src in man["sources"]:
            path = root / src["file"]
            if not path.exists():
                continue
            got = R.read_grid(path, man["person"], sheet=src.get("sheet"),
                              year_hint=man.get("year_hint"), verbose=False)
            assert got, f"{src['file']} parsed empty for {man['person']}"


if __name__ == "__main__":
    print("rosterlib tests")
    for name, fn in sorted(globals().items()):
        if name.startswith("t_"):
            check(name[2:].replace("_", " "), fn)
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
