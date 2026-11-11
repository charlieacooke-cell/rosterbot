#!/usr/bin/env python3
"""
roster — one command to turn a roster spreadsheet into the website and feed.

    python3 roster.py add emily ~/Downloads/"JMO Roster Term 6.xlsx"
    python3 roster.py build charlie
    python3 roster.py build all
    python3 roster.py check emily            # parse and diff, write nothing

`add` copies the sheet in beside the others, records it in that person's
sources.json, then rebuilds. No code change and no column numbers: the sheet's
layout is read off the sheet (see rosterlib).

Each person has three files of their own:

    <person>/sources.json   the spreadsheets to read, oldest first
    <person>/history.json   every shift ever published — the safety net
    codes/<person>.json     hours, type and label for each shift code

History is why `build` cannot lose shifts the way regenerating Charlie's feed
nearly did on 2026-11-12: a source only overwrites the span of dates it
covers, and a build that would drop a published shift stops and says so.
"""

import argparse
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

import rosterlib as R

ROOT = Path(__file__).parent

PEOPLE = {
    "charlie": {"manifest": "charlie/sources.json", "module": "generate_site"},
    "emily":   {"manifest": "emily/sources.json",   "module": "generate_emily_site"},
}


def load_manifest(person):
    if person not in PEOPLE:
        raise SystemExit(f"Unknown person {person!r}. Known: {', '.join(PEOPLE)}")
    path = ROOT / PEOPLE[person]["manifest"]
    if not path.exists():
        raise SystemExit(f"No manifest at {path}")
    m = json.loads(path.read_text(encoding="utf-8"))
    m["_path"] = path
    return m


def save_manifest(m):
    path = m.pop("_path")
    path.write_text(json.dumps(m, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    m["_path"] = path


def gather(person, verbose=True):
    """Parse every source in the manifest and merge onto the archive."""
    m       = load_manifest(person)
    codes_p = ROOT / m["codes"]
    table   = R.load_codes(codes_p)
    hist_p  = ROOT / m["history"]
    before  = R.load_archive(hist_p)
    working = dict(before)
    unknown = {}
    missing = []

    if verbose:
        print(f"\n📂 Sources for {m['person']}:")

    for src in m["sources"]:
        path = ROOT / src["file"]
        note = src.get("note") or Path(src["file"]).stem
        if not path.exists():
            missing.append(src["file"])
            if verbose:
                print(f"  ⓘ missing, using archive for this span: {src['file']}")
            continue
        raw = R.read_grid(path, m["person"], sheet=src.get("sheet"),
                          year_hint=m.get("year_hint"), verbose=verbose)
        resolved, unk = R.resolve(raw, table, fallback=before, source=note)
        for code, dates in unk.items():
            unknown.setdefault(code, []).extend(dates)
        # The span is the whole range the sheet covers, not just the days that
        # turned into shifts — blank weekends at either end still belong to it.
        span = (min(raw), max(raw)) if raw else None
        working, _, _ = R.merge_source(working, resolved,
                                       note if verbose else "",
                                       source=note, span=span)

    # Overrides go on last, above every source.
    working = R.apply_overrides(working, m.get("overrides"), table)

    if verbose:
        R.report_unknown(unknown, m["codes"])
    return m, table, before, working, hist_p, missing


def describe(before, after):
    added   = sorted(set(after) - set(before))
    removed = sorted(set(before) - set(after))
    changed = sorted(k for k in set(before) & set(after)
                     if {x: before[k].get(x) for x in ("code", "start", "end")}
                     != {x: after[k].get(x) for x in ("code", "start", "end")})
    print(f"\n📊 Archive: {len(before)} → {len(after)} shifts "
          f"(+{len(added)} new, {len(changed)} changed, -{len(removed)} dropped)")
    for title, items in (("new", added), ("changed", changed), ("dropped", removed)):
        if not items:
            continue
        show = items if len(items) <= 8 else items[:4] + ["…"] + items[-3:]
        print(f"   {title}: {', '.join(show)}")
    return added, changed, removed


def cmd_build(person, allow_shrink=False, dry_run=False):
    print(f"\n{'=' * 60}\n🏥 {person}\n{'=' * 60}")
    m, table, before, working, hist_p, missing = gather(person)
    describe(before, working)
    R.check_not_shrinking(before, working, allow_shrink)

    if dry_run:
        print("\n(dry run — nothing written)")
        return

    sources = [s.get("note") or s["file"] for s in m["sources"]]
    R.save_archive(hist_p, working, sources)
    print(f"\n💾 {m['history']}: {len(working)} shifts")

    mod = __import__(PEOPLE[person]["module"])
    mod.render(working, table)


def cmd_add(person, filepath, sheet=None, note=None, allow_shrink=False):
    m   = load_manifest(person)
    src = Path(filepath).expanduser()
    if not src.exists():
        raise SystemExit(f"No such file: {src}")

    dest_dir = ROOT / person
    dest_dir.mkdir(exist_ok=True)
    dest = dest_dir / src.name
    if src.resolve() != dest.resolve():
        shutil.copy2(src, dest)
        print(f"📥 Copied in: {dest.relative_to(ROOT)}")

    rel = str(dest.relative_to(ROOT))
    entry = {"file": rel, "sheet": sheet,
             "note": note or dest.stem,
             "added": datetime.now().strftime("%Y-%m-%d")}
    m["sources"] = [s for s in m["sources"] if s["file"] != rel] + [entry]
    save_manifest(m)
    print(f"📝 Recorded in {m['_path'].name} as the newest source")

    cmd_build(person, allow_shrink=allow_shrink)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("build", help="rebuild the site and feed from recorded sources")
    b.add_argument("person", choices=list(PEOPLE) + ["all"])
    b.add_argument("--allow-shrink", action="store_true",
                   help="permit a build that drops already-published shifts")

    c = sub.add_parser("check", help="parse and show the diff, write nothing")
    c.add_argument("person", choices=list(PEOPLE) + ["all"])

    a = sub.add_parser("add", help="add a new roster file and rebuild")
    a.add_argument("person", choices=list(PEOPLE))
    a.add_argument("file")
    a.add_argument("--sheet", help="sheet name (otherwise the one with the most dates)")
    a.add_argument("--note", help="short label, e.g. 'Term 6'")
    a.add_argument("--allow-shrink", action="store_true")

    args = ap.parse_args()
    people = list(PEOPLE) if args.person == "all" else [args.person]

    if args.cmd == "add":
        cmd_add(args.person, args.file, args.sheet, args.note, args.allow_shrink)
    else:
        for p in people:
            cmd_build(p, allow_shrink=getattr(args, "allow_shrink", False),
                      dry_run=(args.cmd == "check"))
    print()


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))
    main()
