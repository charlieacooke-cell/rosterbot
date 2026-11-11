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
