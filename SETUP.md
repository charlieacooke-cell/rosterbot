# How to publish "Is Charlie Working?" 🏥

This guide will get the website live on a free URL in about 15 minutes.

---

## What you've got in this folder

| File | What it does |
|------|-------------|
| `generate_site.py` | The script that reads the roster and builds the website |
| `index.html` | The website (auto-generated — don't edit by hand) |
| `shifts.ics` | Calendar subscription file (auto-generated) |
| `2026 ICU Roster…csv` | Your copy of the roster |

---

## Step 1 — Install Python (if you haven't already)

Download from **python.org** → Install → tick "Add to PATH" during install.

Test it worked: open a terminal and type `python3 --version` (or `python --version` on Windows).

---

## Step 2 — Publish to GitHub Pages (free hosting)

1. Create a free account at **github.com** if you don't have one.

2. Click **New repository** → name it something like `charlie-shifts` → set it to **Public** → click **Create**.

3. On your computer, open a terminal in this folder and run:
   ```
   git init
   git add index.html shifts.ics
   git commit -m "Initial shift site"
   git branch -M main
   git remote add origin https://github.com/YOUR-USERNAME/charlie-shifts.git
   git push -u origin main
   ```
   (Replace `YOUR-USERNAME` with your GitHub username)

4. In GitHub, go to **Settings → Pages → Source** → select **Deploy from branch: main** → Save.

5. After a minute, your site will be live at:
   ```
   https://YOUR-USERNAME.github.io/charlie-shifts/
   ```

6. The calendar subscription URL will be:
   ```
   https://YOUR-USERNAME.github.io/charlie-shifts/shifts.ics
   ```

That's it! Share the URL with family.

---

## Step 3 (optional) — Use a custom domain like ischarlieworking.net

1. Buy the domain from a registrar (e.g. Namecheap, Cloudflare Registrar, Google Domains).
2. In GitHub Pages settings → Custom domain → enter your domain.
3. Follow the registrar's instructions to add a CNAME record pointing to `YOUR-USERNAME.github.io`.

---

## Updating the site when the roster changes

The roster updates infrequently, so this is easy to do manually:

### 1. Get the new file from SharePoint

- Open SharePoint and navigate to the roster file
- Click **Download** (or **Export to CSV** if it's an Excel file online)
- Replace the CSV in this folder with the new one
- **Make sure the filename matches** what's in `generate_site.py` (the `CSV_FILE` line near the top)

### 2. Run the generator

Open a terminal in this folder and run:
```
python3 generate_site.py
```

You'll see something like:
```
✓ Parsed 96 shift entries for Charlie
✓ index.html written
✓ shifts.ics written
```

### 3. Push the update to GitHub

```
git add index.html shifts.ics
git commit -m "Update shifts — new roster"
git push
```

The website updates within a minute. Anyone subscribed to the calendar will get the new data automatically within 24 hours (or immediately if they refresh in their calendar app).

---

## Sharing with family

Send them:
- **Website:** `https://YOUR-USERNAME.github.io/charlie-shifts/` (or your custom domain)
- **Calendar (Google):** Add the webcal link via the button on the website
- **Calendar (iPhone/iPad):** Tap the Apple Calendar button on the website
- **Calendar (Outlook):** Tap the Outlook button on the website

---

## Adjusting shift times

Open `generate_site.py` and edit the CONFIG section at the top:

```python
NIGHT_START_HOUR = 20   # 8pm
NIGHT_END_HOUR   = 8    # 8am next day
DAY_START_HOUR   = 7    # 7am
DAY_END_HOUR     = 19   # 7pm
```

Then re-run the generator and push again.

---

## Troubleshooting

**"Column 'Charlie' not found"** — Open the CSV and check the exact spelling of your column header. Update `CHARLIE_COLUMN_NAME` in `generate_site.py`.

**"CSV not found"** — Make sure the CSV filename in `generate_site.py` (`CSV_FILE = "..."`) exactly matches the actual filename.

**Site not updating** — GitHub Pages can take 1–2 minutes. Hard-refresh with Ctrl+Shift+R.

**Calendar not updating** — Most calendar apps check for updates once per day. Force-refresh in your app's calendar settings.
