#!/usr/bin/env python3
"""
Charlie's Shift Site Generator — the renderer.

Turns a dict of shifts into:
  - charlie/index.html  (the "Is Charlie Working?" website)
  - charlie/shifts.ics  (the calendar subscription feed)

DO NOT RUN THIS TO PUBLISH A ROSTER UPDATE. Use:

    python3 roster.py build charlie          # rebuild from recorded sources
    python3 roster.py add charlie <file>     # add a new roster sheet, then rebuild

Why: this script used to read one hardcoded CSV. That CSV covered February to
August only, so on 2026-11-12 regenerating the site produced 81 events against
the 159 that were live — the August-December sheet had never been wired in and
the published .ics was the only copy of it. roster.py reads every recorded
source, merges onto charlie/history.json, and refuses to publish a feed that
has lost shifts. Running this file directly now just calls it.

Shift hours, types and labels all come from codes/charlie.json. Add a new code
there, not here.
"""

import json
import uuid
from datetime import datetime, timedelta, date
from pathlib import Path

import rosterlib as R

# ============================================================
# CONFIG
# ============================================================

OUTPUT_HTML = "charlie/index.html"
OUTPUT_ICS  = "charlie/shifts.ics"
CODES_FILE  = "codes/charlie.json"

SITE_TITLE    = "Is Charlie Working?"
PERSON_NAME   = "Charlie"
PERSON_EMOJI  = "🩺"

# ============================================================
# CODE TABLE — loaded, not hardcoded
# ============================================================

_TABLE = R.load_codes(Path(__file__).parent / CODES_FILE)

DEFAULT_DAY_HOURS   = tuple(R.to_decimal(h) for h in _TABLE["default_day"])
DEFAULT_NIGHT_HOURS = tuple(R.to_decimal(h) for h in _TABLE["default_night"])

SHIFT_HOURS = {
    code: tuple(R.to_decimal(h) for h in e["hours"])
    for code, e in _TABLE["codes"].items() if e.get("hours")
}
SHIFT_LABELS = {code: e.get("label", code) for code, e in _TABLE["codes"].items()}
CODE_TYPES   = {code: e.get("type", "day")  for code, e in _TABLE["codes"].items()}


# ============================================================
# CORE LOGIC
# ============================================================

def get_hours(code, shift_type):
    """Hours for a code, falling back to the default for its type."""
    if code in SHIFT_HOURS:
        return SHIFT_HOURS[code]
    return DEFAULT_NIGHT_HOURS if shift_type == "night" else DEFAULT_DAY_HOURS


def hours_of(info):
    """
    Hours for one shift. The archived entry wins, because it was resolved when
    the roster was read and stays right even if the code table later changes or
    a historical code is retired from it.
    """
    if info.get("start") and info.get("end"):
        return R.to_decimal(info["start"]), R.to_decimal(info["end"])
    return get_hours(info["code"], info["type"])


def decimal_to_hm(h):
    """Convert decimal hour to (hour, minute) tuple."""
    return int(h), round((h % 1) * 60)


def classify(code):
    if not code or code in ("0", "1", "OFF"):
        return "off"
    if code in CODE_TYPES:
        return CODE_TYPES[code]
    if code.startswith("Fellow"):
        return "off"          # Fellow shifts — not applicable to a registrar
    return "day"              # an unknown code is a working day until told otherwise


def label(code):
    return SHIFT_LABELS.get(code, code)


def generate_ics(shifts):
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//IsCharlieWorking//EN",
        f"X-WR-CALNAME:{PERSON_NAME}'s Shifts",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "REFRESH-INTERVAL;VALUE=DURATION:P1D",
        "X-PUBLISHED-TTL:P1D",
        "X-WR-TIMEZONE:Australia/Sydney",
        # Australia/Sydney, declared properly. Without this the DTSTART lines below are
        # FLOATING times: Apple renders them as local (correct), Google imports them as UTC
        # (11 hours out in AEDT, so a day shift reads 19:00-07:30). Found 2026-11-11 when the
        # feed was first subscribed in Google Calendar.
        "BEGIN:VTIMEZONE",
        "TZID:Australia/Sydney",
        "BEGIN:DAYLIGHT",
        "DTSTART:19701004T020000",
        "TZOFFSETFROM:+1000",
        "TZOFFSETTO:+1100",
        "RRULE:FREQ=YEARLY;BYMONTH=10;BYDAY=1SU",
        "TZNAME:AEDT",
        "END:DAYLIGHT",
        "BEGIN:STANDARD",
        "DTSTART:19700405T030000",
        "TZOFFSETFROM:+1100",
        "TZOFFSETTO:+1000",
        "RRULE:FREQ=YEARLY;BYMONTH=4;BYDAY=1SU",
        "TZNAME:AEST",
        "END:STANDARD",
        "END:VTIMEZONE",
    ]

    for date_str, info in sorted(shifts.items()):
        d        = date.fromisoformat(date_str)
        code     = info["code"]
        stype    = info["type"]
        lbl      = info["label"]
        uid      = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"charlie-{date_str}"))

        start, end = hours_of(info)
        sh, sm = decimal_to_hm(start)
        eh, em = decimal_to_hm(end)

        if stype == "night":
            dtstart = datetime(d.year, d.month, d.day, sh, sm)
            dtend   = datetime(d.year, d.month, d.day, eh, em) + timedelta(days=1)
            lines += [
                "BEGIN:VEVENT",
                f"UID:{uid}@ischarlieworking",
                f"DTSTART;TZID=Australia/Sydney:{dtstart.strftime('%Y%m%dT%H%M%S')}",
                f"DTEND;TZID=Australia/Sydney:{dtend.strftime('%Y%m%dT%H%M%S')}",
                f"SUMMARY:\U0001f319 {lbl} ({code})",
                f"DESCRIPTION:{PERSON_NAME} is working: {lbl}",
                "END:VEVENT",
            ]
        elif stype == "day":
            dtstart = datetime(d.year, d.month, d.day, sh, sm)
            dtend   = datetime(d.year, d.month, d.day, eh, em)
            lines += [
                "BEGIN:VEVENT",
                f"UID:{uid}@ischarlieworking",
                f"DTSTART;TZID=Australia/Sydney:{dtstart.strftime('%Y%m%dT%H%M%S')}",
                f"DTEND;TZID=Australia/Sydney:{dtend.strftime('%Y%m%dT%H%M%S')}",
                f"SUMMARY:\u2600\ufe0f {lbl} ({code})",
                f"DESCRIPTION:{PERSON_NAME} is working: {lbl}",
                "END:VEVENT",
            ]
        elif stype == "relief":
            dtstart = datetime(d.year, d.month, d.day, sh, sm)
            dtend   = datetime(d.year, d.month, d.day, eh, em)
            lines += [
                "BEGIN:VEVENT",
                f"UID:{uid}@ischarlieworking",
                f"DTSTART;TZID=Australia/Sydney:{dtstart.strftime('%Y%m%dT%H%M%S')}",
                f"DTEND;TZID=Australia/Sydney:{dtend.strftime('%Y%m%dT%H%M%S')}",
                f"SUMMARY:\U0001f4df {lbl}",
                f"DESCRIPTION:{PERSON_NAME}: {lbl} — on call to cover sick colleagues",
                "END:VEVENT",
            ]

    lines.append("END:VCALENDAR")
    return "\r\n".join(lines)


# ============================================================
# HTML WEBSITE GENERATOR
# ============================================================

HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>__TITLE__</title>
  <link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>__EMOJI__</text></svg>">
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

    body {
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', sans-serif;
      background: #f0f4f8;
      color: #1a202c;
      min-height: 100vh;
    }

    /* ── HEADER ── */
    header {
      background: #fff;
      border-bottom: 1px solid #e2e8f0;
      padding: 1rem 1.5rem;
      display: flex;
      align-items: center;
      gap: 0.6rem;
    }
    header span { font-size: 1.5rem; }
    header h1 {
      font-size: 1.2rem;
      font-weight: 700;
      color: #2d3748;
    }

    /* ── MAIN ── */
    main { max-width: 640px; margin: 0 auto; padding: 1rem 1rem 3rem; }

    /* ── STATUS CARD ── */
    .card {
      background: #fff;
      border-radius: 16px;
      box-shadow: 0 4px 24px rgba(0,0,0,.08);
      padding: 1.1rem 1.5rem 1rem;
      text-align: center;
      margin-bottom: .7rem;
    }

    .today-label {
      font-size: 0.75rem;
      font-weight: 600;
      letter-spacing: .08em;
      text-transform: uppercase;
      color: #718096;
      margin-bottom: .4rem;
    }

    .status-emoji { font-size: 2.8rem; line-height: 1; margin-bottom: .3rem; }

    .status-answer {
      font-size: clamp(1.7rem, 8vw, 2.4rem);
      font-weight: 900;
      line-height: 1.1;
      margin-bottom: .25rem;
    }

    .status-shift {
      font-size: 1rem;
      font-weight: 600;
      margin-bottom: .2rem;
    }

    .status-sub {
      font-size: .85rem;
      color: #718096;
    }

    /* colour themes */
    .theme-night   { background: #1a237e; color: #fff; }
    .theme-night .status-sub { color: #9fa8da; }
    .theme-day     { background: #fff8e1; color: #e65100; }
    .theme-day .status-sub { color: #f57c00; }
    .theme-off     { background: #e8f5e9; color: #2e7d32; }
    .theme-off .status-sub { color: #66bb6a; }
    .theme-relief  { background: #fdf6e3; color: #92610a; border: 2px solid #f6d860; }
    .theme-relief .status-sub { color: #b07d2a; }
    .theme-unknown { background: #f5f5f5; color: #424242; }

    /* ── NEXT SHIFT ── */
    .next-card {
      background: #fff;
      border-radius: 12px;
      box-shadow: 0 2px 12px rgba(0,0,0,.06);
      padding: .8rem 1.2rem;
      margin-bottom: .7rem;
      display: flex;
      align-items: center;
      gap: .75rem;
    }
    .next-icon { font-size: 1.5rem; flex-shrink: 0; }
    .next-title { font-size: .7rem; font-weight: 700; text-transform: uppercase;
                  letter-spacing: .07em; color: #718096; margin-bottom: .1rem; }
    .next-info  { font-size: .95rem; font-weight: 700; color: #2d3748; }
    .next-sub   { font-size: .8rem; color: #718096; }

    /* ── LOOK UP A DATE ── */
    .lookup-card {
      background: #fff;
      border-radius: 12px;
      box-shadow: 0 2px 12px rgba(0,0,0,.06);
      padding: 1rem 1.2rem;
      margin-bottom: .7rem;
    }
    .lookup-card h2 {
      font-size: .9rem; font-weight: 700; color: #2d3748; margin-bottom: .7rem;
    }
    .lookup-row { display: flex; gap: .6rem; }
    .lookup-row input {
      flex: 1; padding: .7rem 1rem; border: 2px solid #e2e8f0;
      border-radius: 10px; font-size: 1rem; outline: none;
      transition: border-color .2s;
    }
    .lookup-row input:focus { border-color: #667eea; }
    .lookup-row button {
      padding: .7rem 1.2rem; background: #667eea; color: #fff;
      border: none; border-radius: 10px; font-size: .95rem; font-weight: 600;
      cursor: pointer; transition: background .2s;
    }
    .lookup-row button:hover { background: #5a67d8; }
    #lookup-result {
      margin-top: 1rem; padding: 1rem; border-radius: 10px;
      display: none; font-weight: 600; font-size: 1rem;
    }

    /* ── CALENDAR ── */
    .cal-card {
      background: #fff;
      border-radius: 12px;
      box-shadow: 0 2px 12px rgba(0,0,0,.06);
      padding: 1rem .8rem;
      margin-bottom: .7rem;
    }
    .cal-header {
      display: flex; align-items: center; justify-content: space-between;
      padding: 0 .5rem; margin-bottom: 1rem;
    }
    .cal-header h2 { font-size: 1rem; font-weight: 700; color: #2d3748; }
    .cal-nav { display: flex; gap: .4rem; }
    .cal-nav button {
      background: #f7fafc; border: 1px solid #e2e8f0; border-radius: 8px;
      padding: .35rem .7rem; cursor: pointer; font-size: 1rem;
      transition: background .15s;
    }
    .cal-nav button:hover { background: #edf2f7; }
    .cal-month-label {
      font-size: 1.1rem; font-weight: 800; color: #2d3748; min-width: 160px;
      text-align: center;
    }

    .cal-grid {
      display: grid; grid-template-columns: repeat(7, 1fr); gap: 3px;
    }
    .cal-day-name {
      text-align: center; font-size: .7rem; font-weight: 700;
      text-transform: uppercase; color: #a0aec0; padding: .3rem 0;
    }
    .cal-day {
      aspect-ratio: 1; display: flex; flex-direction: column;
      align-items: center; justify-content: center;
      border-radius: 8px; cursor: pointer; position: relative;
      transition: transform .1s; font-size: .85rem; font-weight: 500;
      padding: .1rem;
    }
    .cal-day:hover { transform: scale(1.08); z-index: 1; }
    .cal-day.empty { background: transparent; cursor: default; }
    .cal-day.empty:hover { transform: none; }
    .cal-day.off        { background: #f7fafc; color: #a0aec0; }
    .cal-day.night      { background: #1a237e; color: #fff; }
    .cal-day.day        { background: #fff3e0; color: #e65100; }
    .cal-day.relief     { background: #fdf6e3; color: #92610a; border: 1px solid #f6d860; }
    .cal-day.today-ring    { outline: 3px solid #667eea; outline-offset: 1px; }
    .cal-day.selected-ring { outline: 3px solid #f6ad55; outline-offset: 1px; }
    .cal-day .day-num   { font-weight: 700; line-height: 1; }
    .cal-day .day-dot   { font-size: .6rem; line-height: 1; }

    /* ── BACK TO NOW ── */
    .back-to-now-btn {
      margin-top: .8rem;
      background: rgba(0,0,0,.12);
      border: 1px solid rgba(0,0,0,.15);
      color: inherit;
      border-radius: 20px;
      padding: .3rem .9rem;
      font-size: .8rem;
      cursor: pointer;
      font-weight: 600;
      opacity: .75;
    }
    .back-to-now-btn:hover { opacity: 1; }

    /* ── CALENDAR SUBSCRIPTION ── */
    .sub-card {
      background: #fff;
      border-radius: 16px;
      box-shadow: 0 2px 12px rgba(0,0,0,.06);
      padding: 1.4rem 1.5rem;
      margin-bottom: 1.2rem;
    }
    .sub-card h2 { font-size: 1rem; font-weight: 700; color: #2d3748; margin-bottom: .4rem; }
    .sub-card p  { font-size: .9rem; color: #718096; margin-bottom: 1rem; }
    .sub-buttons { display: flex; gap: .6rem; flex-wrap: wrap; }
    .sub-btn {
      padding: .6rem 1rem; border-radius: 10px; font-size: .9rem; font-weight: 600;
      text-decoration: none; display: inline-flex; align-items: center; gap: .4rem;
      transition: opacity .2s;
    }
    .sub-btn:hover { opacity: .85; }
    .sub-btn.google  { background: #4285f4; color: #fff; }
    .sub-btn.apple   { background: #1c1c1e; color: #fff; }
    .sub-btn.outlook { background: #0078d4; color: #fff; }
    .sub-btn.ics     { background: #f0f4f8; color: #4a5568; border: 1px solid #e2e8f0; }

    /* ── LEGEND ── */
    .legend {
      display: flex; flex-wrap: wrap; gap: .5rem;
      padding: .2rem .5rem .5rem;
    }
    .leg-item {
      display: flex; align-items: center; gap: .4rem;
      font-size: .8rem; color: #718096;
    }
    .leg-dot {
      width: 12px; height: 12px; border-radius: 3px; flex-shrink: 0;
    }
    .leg-night  { background: #1a237e; }
    .leg-day    { background: #fff3e0; border: 1px solid #f6ad55; }
    .leg-relief { background: #fdf6e3; border: 1px solid #f6d860; }
    .leg-off    { background: #f7fafc; border: 1px solid #e2e8f0; }

    /* ── TOOLTIP ── */
    .tooltip {
      position: fixed; background: #2d3748; color: #fff;
      padding: .5rem .8rem; border-radius: 8px; font-size: .82rem;
      pointer-events: none; z-index: 100; white-space: nowrap;
      transform: translate(-50%, -120%); display: none;
    }

    /* ── FOOTER ── */
    footer {
      text-align: center; font-size: .78rem; color: #a0aec0;
      margin-top: 1rem;
    }
    footer a { color: #a0aec0; }
  </style>
</head>
<body>
  <header>
    <span>__EMOJI__</span>
    <h1>__TITLE__</h1>
  </header>

  <main>
    <!-- TODAY STATUS -->
    <div class="card" id="status-card">
      <div class="today-label" id="today-label">Today</div>
      <div class="status-emoji" id="status-emoji">⏳</div>
      <div class="status-answer" id="status-answer">Loading…</div>
      <div class="status-shift" id="status-shift"></div>
      <div class="status-sub" id="status-sub"></div>
      <button class="back-to-now-btn" id="back-to-now" onclick="resetToNow()" style="display:none">← Back to now</button>
    </div>

    <!-- NEXT SHIFT -->
    <div class="next-card" id="next-card" style="display:none">
      <div class="next-icon" id="next-icon">📅</div>
      <div>
        <div class="next-title" id="next-title">Next shift</div>
        <div class="next-info" id="next-info"></div>
        <div class="next-sub" id="next-sub"></div>
      </div>
    </div>

    <!-- CALENDAR -->
    <div class="cal-card">
      <div class="cal-header">
        <div class="cal-nav">
          <button onclick="changeMonth(-1)">‹</button>
        </div>
        <div class="cal-month-label" id="cal-month-label"></div>
        <div class="cal-nav">
          <button onclick="changeMonth(1)">›</button>
        </div>
      </div>
      <div class="cal-grid" id="cal-grid"></div>
      <div class="legend" style="margin-top:.8rem">
        <div class="leg-item"><div class="leg-dot leg-night"></div>Night</div>
        <div class="leg-item"><div class="leg-dot leg-day"></div>Day</div>
        <div class="leg-item"><div class="leg-dot leg-relief"></div>Sick Relief</div>
        <div class="leg-item"><div class="leg-dot leg-off"></div>Off</div>
      </div>
    </div>

    <!-- DATE LOOKUP -->
    <div class="lookup-card">
      <h2>🔍 Look up a date</h2>
      <div class="lookup-row">
        <input type="date" id="lookup-input" />
        <button onclick="lookupDate()">Check</button>
      </div>
      <div id="lookup-result"></div>
    </div>

    <!-- CALENDAR SUBSCRIPTION -->
    <div class="sub-card">
      <h2>📅 Add to your calendar</h2>
      <p>Subscribe so Charlie's shifts appear automatically in your calendar app.</p>
      <div class="sub-buttons">
        <a class="sub-btn google" id="gcal-btn" href="#" target="_blank">
          &#x1f4c5; Google Calendar
        </a>
        <a class="sub-btn apple" id="apple-btn" href="shifts.ics">
          🍎 Apple Calendar
        </a>
        <a class="sub-btn outlook" id="outlook-btn" href="#" target="_blank">
          📧 Outlook
        </a>
        <a class="sub-btn ics" href="shifts.ics" download>
          ⬇ Download .ics
        </a>
      </div>
    </div>

    <footer>
      Last updated: <strong>__GENERATED__</strong> ·
      <a href="shifts.ics">shifts.ics</a>
    </footer>
  </main>

  <!-- TOOLTIP -->
  <div class="tooltip" id="tooltip"></div>

<script>
// ── SHIFT DATA (auto-generated) ──────────────────────────
const SHIFTS = __SHIFTS_JSON__;

// ── SHIFT HOURS (per code, mirrors Python SHIFT_HOURS) ────
const HOURS = __HOURS_JSON__;
const DEFAULT_HOURS = { day: __DEFAULT_DAY_HOURS__, night: __DEFAULT_NIGHT_HOURS__ };

// ── HELPERS ─────────────────────────────────────────────
function toISO(d) {
  const y = d.getFullYear();
  const m = String(d.getMonth()+1).padStart(2,'0');
  const day = String(d.getDate()).padStart(2,'0');
  return `${y}-${m}-${day}`;
}

function friendlyDate(iso) {
  const [y,m,d] = iso.split('-').map(Number);
  const dt = new Date(y, m-1, d);
  return dt.toLocaleDateString('en-GB', { weekday:'long', day:'numeric', month:'long', year:'numeric' });
}

function shiftEmoji(type) {
  return { night:'🌙', day:'☀️', relief:'📟', off:'💤' }[type] || '❓';
}

function shiftTheme(type) {
  return { night:'theme-night', day:'theme-day', relief:'theme-relief', off:'theme-off' }[type] || 'theme-unknown';
}

function fmtHour(h) {
  if (h === 0 || h === 24) return 'midnight';
  const wholeH = Math.floor(h);
  const mins   = Math.round((h % 1) * 60);
  const suffix = wholeH < 12 ? 'am' : 'pm';
  const h12    = wholeH === 0 ? 12 : wholeH <= 12 ? wholeH : wholeH - 12;
  return mins > 0 ? `${h12}:${String(mins).padStart(2,'0')}${suffix}` : `${h12}${suffix}`;
}

function getHours(code, type) {
  if (HOURS[code]) return HOURS[code];
  return DEFAULT_HOURS[type] || DEFAULT_HOURS.day;
}

function shiftHoursStr(code, type) {
  const [s, e] = getHours(code, type);
  return type === 'night'
    ? `${fmtHour(s)} – ${fmtHour(e)} tomorrow`
    : `${fmtHour(s)} – ${fmtHour(e)}`;
}

function daysUntil(iso) {
  const today = new Date(); today.setHours(0,0,0,0);
  const [y,m,d] = iso.split('-').map(Number);
  const target = new Date(y, m-1, d);
  const diff = Math.round((target - today) / 86400000);
  if (diff === 0) return 'today';
  if (diff === 1) return 'tomorrow';
  if (diff === 2) return 'in 2 days';
  return `in ${diff} days`;
}

// ── STATUS CARD ──────────────────────────────────────────
function setStatus(emoji, answer, shift, sub, type) {
  const card = document.getElementById('status-card');
  card.classList.remove('theme-night','theme-day','theme-relief','theme-off','theme-unknown');
  card.classList.add(shiftTheme(type));
  document.getElementById('status-emoji').textContent  = emoji;
  document.getElementById('status-answer').textContent = answer;
  document.getElementById('status-shift').textContent  = shift;
  document.getElementById('status-sub').textContent    = sub;
}

function updateStatus() {
  const now      = new Date();
  const hour     = now.getHours() + now.getMinutes() / 60;
  const todayISO = toISO(now);
  const yestISO  = toISO(new Date(now - 86400000));

  const dayStr = now.toLocaleDateString('en-GB', { weekday:'long', day:'numeric', month:'long' });
  document.getElementById('today-label').textContent = `Now: ${dayStr}`;

  // Is yesterday's night shift still running now?
  const yInfo = SHIFTS[yestISO];
  if (yInfo && yInfo.type === 'night') {
    const [, yEnd] = getHours(yInfo.code, 'night');
    if (hour < yEnd) {
      setStatus('🌙', 'Yes', 'Charlie is at work right now',
        `${yInfo.label} · until ${fmtHour(yEnd)}`, 'night');
      return;
    }
  }

  const info = SHIFTS[todayISO];
  const type = info ? info.type : 'off';

  if (type === 'night') {
    const [nStart, nEnd] = getHours(info.code, 'night');
    if (hour >= nStart) {
      setStatus('🌙', 'Yes', 'Charlie is at work right now',
        `${info.label} · until ${fmtHour(nEnd)} tomorrow`, 'night');
    } else if (hour >= 10 && hour < 17) {
      setStatus('😴', 'Sleeping', 'Charlie should be resting right now',
        `Night shift starts at ${fmtHour(nStart)}`, 'night');
    } else if (hour >= 17) {
      setStatus('🌙', 'Tonight', `Charlie starts work at ${fmtHour(nStart)}`,
        info.label, 'night');
    } else {
      setStatus('🌙', 'Off', 'Charlie is between night shifts',
        `Night shift starts at ${fmtHour(nStart)}`, 'night');
    }
  } else if (type === 'day') {
    const [dStart, dEnd] = getHours(info.code, 'day');
    if (hour < dStart) {
      setStatus('☀️', 'Today', `Charlie starts work at ${fmtHour(dStart)}`,
        info.label, 'day');
    } else if (hour >= dEnd) {
      setStatus('✅', 'No', 'Charlie has finished for the day',
        `Shift ended at ${fmtHour(dEnd)}`, 'off');
    } else {
      setStatus('☀️', 'Yes', 'Charlie is at work right now',
        `${info.label} · until ${fmtHour(dEnd)}`, 'day');
    }
  } else if (type === 'relief') {
    setStatus('📟', 'On Sick Relief', 'Available to cover if needed',
      'Not a scheduled shift — covering for sick colleagues', 'relief');
  } else {
    setStatus('✅', 'No', 'Charlie is not working today', '', 'off');
  }
}

// ── NEXT SHIFT ───────────────────────────────────────────
function isWorkShift(type) {
  return type === 'night' || type === 'day' || type === 'relief';
}

function updateNextShift() {
  const now      = new Date();
  const hour     = now.getHours() + now.getMinutes() / 60;
  const todayISO = toISO(now);
  const yestISO  = toISO(new Date(now - 86400000));

  const todayInfo = SHIFTS[todayISO];
  const todayType = todayInfo ? todayInfo.type : 'off';

  // Yesterday's night still running into this morning?
  const yInfo = SHIFTS[yestISO];
  const overnightActive = yInfo && yInfo.type === 'night' && hour < getHours(yInfo.code, 'night')[1];

  // Are we mid-run? Today is a working shift day (any time), or overnight still active.
  const baseISO  = (overnightActive && !isWorkShift(todayType)) ? yestISO : todayISO;
  const baseInfo = SHIFTS[baseISO];
  const baseType = baseInfo ? baseInfo.type : 'off';
  const midRun   = isWorkShift(baseType);

  const card = document.getElementById('next-card');

  if (midRun) {
    // Find the contiguous run block containing baseISO
    const workDates = Object.entries(SHIFTS)
      .filter(([, info]) => isWorkShift(info.type))
      .map(([iso]) => iso)
      .sort();

    const baseIdx = workDates.indexOf(baseISO);
    let end = baseIdx;
    while (end < workDates.length - 1) {
      const gap = (new Date(workDates[end + 1]) - new Date(workDates[end])) / 86400000;
      if (gap <= 1) end++;
      else break;
    }

    // Shifts remaining in the run from baseISO onwards
    let remaining = workDates.slice(baseIdx, end + 1);

    // If today's day shift has already ended, exclude today
    if (baseISO === todayISO && todayType === 'day') {
      const [, dEnd] = getHours(todayInfo.code, 'day');
      if (hour >= dEnd) remaining = remaining.filter(iso => iso > todayISO);
    }

    if (!remaining.length) return;

    card.style.display = 'flex';
    document.getElementById('next-title').textContent = 'This run';
    document.getElementById('next-icon').textContent  = '📋';
    document.getElementById('next-info').textContent  = `${remaining.length} shift${remaining.length !== 1 ? 's' : ''} remaining`;
    const lastISO = workDates[end];
    document.getElementById('next-sub').textContent   = `Run ends ${friendlyDate(lastISO)}`;

  } else {
    // Day off between runs — show next upcoming shift
    const upcoming = Object.entries(SHIFTS)
      .filter(([iso, info]) => iso > todayISO && isWorkShift(info.type))
      .sort(([a],[b]) => a.localeCompare(b));

    if (!upcoming.length) return;
    const [iso, info] = upcoming[0];

    card.style.display = 'flex';
    document.getElementById('next-title').textContent = 'Next shift';
    document.getElementById('next-icon').textContent  = shiftEmoji(info.type);
    document.getElementById('next-info').textContent  = friendlyDate(iso);
    document.getElementById('next-sub').textContent   = `${info.label} · ${shiftHoursStr(info.code, info.type)} · ${daysUntil(iso)}`;
  }
}

// ── DATE LOOKUP ──────────────────────────────────────────
function lookupDate() {
  const input = document.getElementById('lookup-input').value;
  const result = document.getElementById('lookup-result');
  if (!input) { result.style.display='none'; return; }

  const info  = SHIFTS[input];
  const type  = info ? info.type : 'off';
  const fd    = friendlyDate(input);

  const hrs = (info && (type === 'night' || type === 'day')) ? ` · ${shiftHoursStr(info.code, type)}` : '';
  const themes = {
    night:  { bg:'#e8eaf6', color:'#1a237e', text:`🌙 Yes — ${info?.label || 'Night Shift'}${hrs}` },
    day:    { bg:'#fff3e0', color:'#e65100', text:`☀️ Yes — ${info?.label || 'Day Shift'}${hrs}` },
    relief: { bg:'#fdf6e3', color:'#92610a', text:`📟 On Sick Relief — not a scheduled shift` },
    off:    { bg:'#f0fff4', color:'#276749', text:`✅ No — Charlie is off` },
  };
  const t = themes[type] || themes.off;

  result.style.display    = 'block';
  result.style.background = t.bg;
  result.style.color      = t.color;
  result.innerHTML        = `<strong>${fd}</strong><br>${t.text}`;
}

document.getElementById('lookup-input').addEventListener('keydown', e => {
  if (e.key === 'Enter') lookupDate();
});

// ── CALENDAR ─────────────────────────────────────────────
let calYear, calMonth;
const MONTHS = ['January','February','March','April','May','June',
                'July','August','September','October','November','December'];
const DAYS   = ['Mon','Tue','Wed','Thu','Fri','Sat','Sun'];

function renderCalendar(year, month) {
  calYear  = year;
  calMonth = month;
  document.getElementById('cal-month-label').textContent = `${MONTHS[month]} ${year}`;

  const grid    = document.getElementById('cal-grid');
  const todayISO = toISO(new Date());

  // Day names header
  let html = DAYS.map(d => `<div class="cal-day-name">${d}</div>`).join('');

  // First day of month (0=Sun … 6=Sat → adjust to Mon-start)
  const firstDay = new Date(year, month, 1).getDay(); // 0=Sun
  const offset   = (firstDay + 6) % 7;               // Mon=0, Tue=1 …
  for (let i = 0; i < offset; i++) html += `<div class="cal-day empty"></div>`;

  const daysInMonth = new Date(year, month+1, 0).getDate();
  for (let d = 1; d <= daysInMonth; d++) {
    const iso  = `${year}-${String(month+1).padStart(2,'0')}-${String(d).padStart(2,'0')}`;
    const info = SHIFTS[iso];
    const type = info ? info.type : 'off';
    const tip  = info ? info.label : 'No shift';
    const isToday = iso === todayISO ? ' today-ring' : '';
    const dot  = (info && type !== 'off') ? `<div class="day-dot">${shiftEmoji(type)}</div>` : '';
    html += `<div class="cal-day ${type}${isToday}" data-iso="${iso}" data-tip="${tip}" onclick="calClick('${iso}')">
               <div class="day-num">${d}</div>${dot}
             </div>`;
  }
  grid.innerHTML = html;

  // Tooltip logic
  grid.querySelectorAll('.cal-day:not(.empty)').forEach(el => {
    el.addEventListener('mousemove', ev => {
      const tt = document.getElementById('tooltip');
      tt.textContent = `${friendlyDate(el.dataset.iso)}: ${el.dataset.tip}`;
      tt.style.display = 'block';
      tt.style.left    = ev.clientX + 'px';
      tt.style.top     = ev.clientY + 'px';
    });
    el.addEventListener('mouseleave', () => {
      document.getElementById('tooltip').style.display = 'none';
    });
  });
}

let calSelected = null;

function calClick(iso) {
  const todayISO = toISO(new Date());
  // Update selected highlight
  document.querySelectorAll('.cal-day.selected-ring').forEach(el => el.classList.remove('selected-ring'));
  if (iso !== todayISO) {
    document.querySelector(`[data-iso="${iso}"]`)?.classList.add('selected-ring');
  }
  calSelected = iso;
  if (iso === todayISO) {
    resetToNow();
  } else {
    showDateStatus(iso);
    document.getElementById('status-card').scrollIntoView({ behavior:'smooth', block:'nearest' });
  }
}

function resetToNow() {
  calSelected = null;
  document.querySelectorAll('.cal-day.selected-ring').forEach(el => el.classList.remove('selected-ring'));
  document.getElementById('back-to-now').style.display = 'none';
  updateStatus();
}

function showDateStatus(iso) {
  const info = SHIFTS[iso];
  const type = info ? info.type : 'off';
  document.getElementById('today-label').textContent = friendlyDate(iso);
  document.getElementById('back-to-now').style.display = 'inline-block';
  if (type === 'night') {
    const [nStart, nEnd] = getHours(info.code, 'night');
    setStatus('🌙', 'Working', info.label,
      `${fmtHour(nStart)} – ${fmtHour(nEnd)} (next day)`, 'night');
  } else if (type === 'day') {
    const [dStart, dEnd] = getHours(info.code, 'day');
    setStatus('☀️', 'Working', info.label,
      `${fmtHour(dStart)} – ${fmtHour(dEnd)}`, 'day');
  } else if (type === 'relief') {
    setStatus('📟', 'On Sick Relief', 'Available to cover if needed',
      'Not a scheduled shift — covering for sick colleagues', 'relief');
  } else {
    setStatus('✅', 'Day Off', 'Not working this day',
      info ? info.label : '', 'off');
  }
}

function changeMonth(dir) {
  let m = calMonth + dir;
  let y = calYear;
  if (m > 11) { m = 0; y++; }
  if (m < 0)  { m = 11; y--; }
  renderCalendar(y, m);
}

// ── CALENDAR SUBSCRIPTION LINKS ──────────────────────────
function setupCalLinks() {
  const icsUrl = window.location.href.replace(/\/[^/]*$/, '/') + 'shifts.ics';
  const webcal = icsUrl.replace(/^https?/, 'webcal');

  document.getElementById('apple-btn').href = webcal;
  document.getElementById('gcal-btn').href  =
    `https://calendar.google.com/calendar/r?cid=${encodeURIComponent(webcal)}`;
  document.getElementById('outlook-btn').href =
    `https://outlook.live.com/calendar/0/addfromweb?url=${encodeURIComponent(icsUrl)}`;
}

// ── INIT ─────────────────────────────────────────────────
(function init() {
  updateStatus();
  updateNextShift();
  const now = new Date();
  renderCalendar(now.getFullYear(), now.getMonth());
  setupCalLinks();
})();
</script>
</body>
</html>
"""

def generate_html(shifts, generated_at):
    shifts_json = json.dumps(shifts, separators=(',', ':'))
    html = HTML_TEMPLATE
    # Build JS-friendly hours dict: {"CODE": [start, end], ...}
    hours_for_js = {code: list(hrs) for code, hrs in SHIFT_HOURS.items()}
    html = html.replace("__TITLE__",              SITE_TITLE)
    html = html.replace("__EMOJI__",              PERSON_EMOJI)
    html = html.replace("__SHIFTS_JSON__",        shifts_json)
    html = html.replace("__GENERATED__",          generated_at)
    html = html.replace("__HOURS_JSON__",         json.dumps(hours_for_js))
    html = html.replace("__DEFAULT_DAY_HOURS__",  json.dumps(list(DEFAULT_DAY_HOURS)))
    html = html.replace("__DEFAULT_NIGHT_HOURS__",json.dumps(list(DEFAULT_NIGHT_HOURS)))
    return html


# ============================================================
# MAIN
# ============================================================

def render(shifts, table=None):
    """
    Write the website and the calendar feed from `shifts`.

    Called by roster.py, which owns reading the spreadsheets and keeping
    charlie/history.json. This function only renders — it never decides what
    the roster is, which is the separation that makes losing shifts impossible
    here.
    """
    script_dir = Path(__file__).parent
    html_path  = script_dir / OUTPUT_HTML
    ics_path   = script_dir / OUTPUT_ICS

    generated_at = datetime.now().strftime("%d %b %Y at %H:%M")
    html_path.parent.mkdir(exist_ok=True)

    # The page only needs code, type and label; it looks hours up from HOURS by
    # code. Sending the archive's start/end/source as well would put ~10 KB of
    # build bookkeeping into a public page people load on mobile data.
    for_page = {k: {"code": v["code"], "type": v["type"], "label": v["label"]}
                for k, v in shifts.items()}
    html_path.write_text(generate_html(for_page, generated_at), encoding="utf-8")

    ics = generate_ics(shifts)
    ics_path.write_text(ics, encoding="utf-8")

    events = ics.count("BEGIN:VEVENT")
    from collections import Counter
    counts = Counter(v["type"] for v in shifts.values())
    print(f"\n🌐 {OUTPUT_HTML}: {len(shifts)} dated entries")
    print(f"📅 {OUTPUT_ICS}: {events} events "
          f"({', '.join(f'{n} {t}' for t, n in sorted(counts.items()))})")
    print(f"   {generated_at}")
    return events


def main():
    """Running this file directly rebuilds through roster.py, deliberately.

    Typing `python3 generate_site.py` out of habit is how the 81-event feed
    nearly got published, so the old entry point now does the safe thing
    instead of the thing it used to do.
    """
    import subprocess, sys
    print("↪ generate_site.py only renders now — handing over to roster.py\n")
    sys.exit(subprocess.call(
        [sys.executable, str(Path(__file__).parent / "roster.py"), "build", "charlie"]))


if __name__ == "__main__":
    main()
