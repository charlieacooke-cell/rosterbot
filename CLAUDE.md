# Is Charlie Working? — Project Handoff

## What this is
A system that reads Charlie's ICU roster from a CSV and generates:
- `index.html` — a public website ("Is Charlie Working?") for family to check Charlie's shifts
- `shifts.ics` — a calendar subscription file (webcal/Google/Apple/Outlook)

The site is designed to go on **GitHub Pages** (free). See `SETUP.md` for deploy instructions.

## How to regenerate after a roster update
```bash
python3 generate_site.py
# then push to GitHub:
git add index.html shifts.ics
git commit -m "Update shifts"
git push
```

## Files
| File | Purpose |
|------|---------|
| `generate_site.py` | Main script — reads CSV, outputs index.html + shifts.ics |
| `index.html` | Generated website (do not edit by hand) |
| `shifts.ics` | Generated calendar file (do not edit by hand) |
| `SETUP.md` | GitHub Pages setup instructions |
| `.gitignore` | Keeps the CSV off GitHub (has colleagues' personal data) |

The CSV (`2026 ICU Roster - Charlie Copy CSV.csv`) is gitignored and stays local only.

## Shift codes (from the "Shifts" sheet in the xlsx)
Sourced from the actual Excel Shifts sheet. Charlie is a **registrar**, not a fellow.

| Code | Full name | Type | Hours |
|------|-----------|------|-------|
| NN | North POD Night | night | 20:00–08:30 |
| SN | South POD Night | night | 20:00–08:30 |
| NFLOAT | Night Float Reg | night | 20:00–08:30 |
| SD | South POD Day | day | 08:00–20:30 |
| ND | North POD Day | day | 08:00–20:30 |
| DFLOAT | Day Float Reg | day | 08:00–20:30 |
| NICU | NICU Rotation | day | 08:00–17:00 |
| Anaes/SR | Anaesthetics | day | 07:30–17:30 |
| SR | Sick Relief | relief | (special state, see below) |
| AL | Annual Leave | off | — |
| ADO | Rostered Day Off | off | — |
| SICK | Sick Day | off | — |
| NIGHT | Fellow Night | **ignore** | Fellow only — not Charlie |
| DAY | Fellow Day | **ignore** | Fellow only — not Charlie |

**Important:** `ND` = North POD **Day** (08:00–20:30), NOT night. Easy to mistake for "night duty".

## Website status logic
The site is time-aware — it checks the current time, not just the date.

| Situation | Display |
|-----------|---------|
| Currently on shift | **Yes** · "Charlie is at work right now · [label] until [time]" |
| Shift later today (not started) | **Today/Tonight** · "Charlie starts work at [time]" |
| Day shift finished | **No** · "Charlie has finished for the day · Shift ended at [time]" |
| Sick relief | **On Sick Relief** · "Available to cover if needed" |
| Off | **No** · "Charlie is not working today" |

Night shifts span midnight — the site checks yesterday's shift too, so at 3am it correctly shows the overnight shift as still active.

## Calendar subscription
The `shifts.ics` file includes `REFRESH-INTERVAL;VALUE=DURATION:P1D` (daily refresh hint).
- Apple Calendar and Outlook respect this well
- Google Calendar is slow (~12–24h lag) — known Google limitation, nothing to fix
- Subscription links on the website are built from `window.location.href` so they only work when hosted (not opened as a local file)

## Key Python functions in generate_site.py
- `parse_roster(csv_path)` — reads the CSV, returns `{ISO-date: {code, type, label}}`
- `classify(code)` — maps shift code to type (night/day/relief/off)
- `get_hours(code, type)` — returns (start_decimal, end_decimal) for a code
- `generate_ics(shifts)` — builds the VCALENDAR string
- `generate_html(shifts, generated_at)` — fills the HTML template with embedded JSON

## Roster spreadsheet structure
- Excel file has multiple sheets: Registrar, Fellow, Shifts, Bio, etc.
- The **Shifts** sheet defines all codes and their hours
- The **Registrar** sheet is the main roster grid: rows=dates, columns=staff
- Charlie is column index 9 (0-based) in the CSV export
- Header row 0, role row 1, data starts row 2
- Date format in CSV: `2-Feb-26` (parsed with `%d-%b-%y`)
- Summary rows at the bottom of the CSV are not date rows — safely ignored by the parser

## Night shift count
- Charlie has **38 night shifts** (NN + SN + NFLOAT)
- The Excel COUNTIF formula `=COUNTIF(range,"SN")+COUNTIF(range,"NN")+COUNTIF(range,"NFLOAT")` is correct
- ND is NOT a night shift despite the N prefix

## What still could be done
- Set up GitHub Pages and custom domain (ischarlieworking.net) — see SETUP.md
- Confirm NICU hours (roster says 08:00, end time unclear — currently set to 17:00)
- Automate the CSV download from SharePoint (currently manual)
- Write a one-click update script (generate + git push in one command)
