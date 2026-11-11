# rosterbot — hand it a spreadsheet, get a website

Two public sites, each a roster turned into a page anyone can check and a
calendar feed they can subscribe to.

| Site | Netlify ID | Built from |
|---|---|---|
| ischarlieworking.netlify.app | `fd64f128-1b0c-4a4f-9372-f365257efd47` | `charlie/` |
| isemilyworking.netlify.app | `a119c7a4-05b6-4919-9c62-3fce55f0721e` | `emily/` |
| reg-swap-board | `fff29d84-edba-4ea5-96e3-1c71ad8ff6a0` | `swaps/` (separate, see `generate_swapboard.py`) |

---

## The whole job, in one command

```bash
python3 roster.py add emily ~/Downloads/"JMO Roster Term 6.xlsx"
```

That copies the sheet in, records it, works out the layout, reads Emily's row,
merges it onto everything already published, rebuilds the page and the feed,
and tells you what changed. Then deploy (see below).

Other commands:

```bash
python3 roster.py build charlie      # rebuild from the sheets already recorded
python3 roster.py build all
python3 roster.py check emily        # parse and show the diff, write nothing
python3 test_rosterlib.py            # 15 tests, run before trusting a change
```

⚠️ **Never run `generate_site.py` or `generate_emily_site.py` to publish.** They
are renderers now; running either just calls `roster.py` for you.

---

## The files

| File | Purpose |
|---|---|
| `roster.py` | the command: read sources → merge → render |
| `rosterlib.py` | sheet reading, the archive, the safety checks |
| `<person>/sources.json` | which spreadsheets to read, **oldest first**, plus manual overrides |
| `<person>/history.json` | **every shift ever published** — the safety net |
| `codes/<person>.json` | hours, type and label per shift code, plus aliases |
| `generate_*_site.py` | the HTML template and the ICS writer. Rendering only |
| `test_rosterlib.py` | one test per failure this project has actually had |

A new spreadsheet needs **no code change**. A new shift *code* needs one line
in `codes/<person>.json` — and the build tells you which code and on what dates.

---

## Why it is built this way

Three real failures, each now designed out.

**1. The feed that nearly lost 78 shifts (2026-11-12).** `generate_site.py` read
one hardcoded CSV covering February to August. The August–December roster had
been parsed once in July and written *straight into `charlie/shifts.ics`*, and
its source was never committed, so the published file was the only copy.
Regenerating produced 81 events against the 159 that were live. It was caught
by counting events before deploying.

→ `history.json` is now the record, committed, and a rebuild merges onto it. A
source only overwrites **the span of dates it actually covers**, so adding next
term cannot touch last term. A build that would drop a published shift stops
dead and says which dates, unless given `--allow-shrink`.

**2. A bespoke parser per term.** Emily's roster arrives in a new shape every
three to six months: two-week blocks down the sheet, a PDF of weekly columns, a
77-column grid running left to right. Each got its own function nailed to a
hardcoded filename, and terms whose file was lost were pasted in as a literal
dict of 31 dates.

→ `rosterlib.read_grid` reads the shape off the sheet. It finds the dates by
looking for dates and the person by looking for their name — no column numbers,
no row offsets. Three layouts are handled: dates down a column, dates across a
row, and bare day numbers with a month name nearby.

**3. Dates that were plausible but wrong.** The day-number layout has no real
dates in it, only integers, and the columns are not a contiguous run of days.

→ Every date is now checked against the roster's **own weekday row or column**
before anything is published. The sheet says which day of the week each column
is; if the dates disagree the build stops. On Term 5 this caught a typo — the
sheet's last cell reads `1` under "Su" after Sat 30 January, which reads as
1 February, a Monday. The published feed had it as 1 February. It is 31 January,
and the weekday row is what proves it.

**The general rule behind all three: verify the artefact, not the name.** Count
the events, diff the feed, check the dates against a second property of the same
sheet. A parser that returns 81 shifts looks exactly like a parser that returns
159, right up until someone misses work.

---

## Shift codes

`codes/<person>.json` is the single source of truth: the website's hours table,
the calendar feed and the parser all read it.

```json
"NFLOAT": { "hours": ["20:00", "08:30"], "type": "night", "label": "Night Float" }
```

- **Night shifts** end the next morning, so `end` < `start`. The ICS writer adds
  the day.
- **`type`** drives the wording and the icon: `day`, `night`, `afternoon`,
  `evening`, `relief`, `off`, `holiday`. Codes with `off` or `holiday` carry no
  hours and make no calendar event — they still show on the page, so a rostered
  day off reads as a day off rather than as nothing at all.
- **`blank_weekday`** is the quiet one. On Emily's JMO roster a blank weekday
  means a normal ward day and the codes mark the *exceptions*; reading blanks as
  "not working" gives her four shifts in eleven weeks. On Charlie's it is `null`.
- **`aliases`** absorb hand-typed variants (`"D10 WE" → "D10WE"`,
  `"E10 (1100 - 2100)" → "E10S"`) without touching any code.
- An **unknown code is never dropped.** It is published as an ordinary day with
  default hours and reported at the end of the build. A missing shift is
  invisible; a shift with the wrong label gets noticed and fixed.

## Overrides

Facts no spreadsheet knows — leave the roster still shows as working, a swap
agreed in the tearoom — go in `<person>/sources.json`:

```json
"overrides": [
  { "from": "2026-07-13", "to": "2026-07-26", "code": "AL", "note": "holidays" }
]
```

They are applied **last**, above every source, so widening a term sheet to cover
those dates cannot quietly undo them. That is exactly what happened to Emily's
July holiday the first time.

---

## Deploying

The repo is linked to `isemilyworking`, so Charlie's site needs its ID spelled
out. Draft first, look at it, then promote:

```bash
npx netlify deploy --dir charlie --site fd64f128-1b0c-4a4f-9372-f365257efd47
```

```bash
npx netlify deploy --prod --dir charlie --site fd64f128-1b0c-4a4f-9372-f365257efd47
```

```bash
npx netlify deploy --prod --dir emily --site a119c7a4-05b6-4919-9c62-3fce55f0721e
```

Google Calendar re-reads a subscribed feed roughly daily; Apple is faster. That
lag is Google's, not ours.

---

## Things that bite

- **The spreadsheets are gitignored and must stay that way.** They carry every
  colleague's shifts and this repo is public on GitHub. `history.json` holds
  only Charlie's or Emily's own shifts, which the feed already publishes.
- **Several copies of the same roster end up on disk, and the newest filename is
  not the newest roster.** Charlie had four copies of the first-half sheet; the
  one that matched what was published was a 29 June download, not the 19 April
  CSV the generator was reading and not the 11 July workbook, whose `Registrar
  S1` tab is a carried-over historical copy. `sources.json` records which one and
  why.
- **An ICS needs CRLF line endings.** Patching the file as text with Python
  silently converts them to LF — which is what happened on 2026-11-11. It still
  worked, but regenerating is the right fix, not editing the artefact.
- **Floating times are a trap.** A `DTSTART` with no `TZID` and no `VTIMEZONE`
  renders as local in Apple and as UTC in Google — eleven hours out in AEDT, so
  a day shift reads 19:00–07:30. Both feeds now declare `Australia/Sydney`
  properly. Do not remove the `VTIMEZONE` block.
- **`pick_sheet` chooses the sheet with the most dates**, because these workbooks
  lead with contacts, bios and teaching programs. Name the sheet explicitly in
  `sources.json` when that guess is wrong.
