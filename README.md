# Roll Call

A BJJ competition journal for tracking kids' matches, opponents, competitions, medals and weight classes, built from their Jits.gg and Smoothcomp profiles.

- **Live site:** https://alain-labrada.github.io/bjj-journal/
- **How it works:** `sync_data.py` reads each kid's profiles in Chrome and writes `sync-output.json`. The web app shows that file's matches, opponents and reports.

> **Personal data stays on your computer.** `kids.json` (names and profile links) and `sync-output.json` (all matches and medals) are in `.gitignore`, so they are never pushed to GitHub or published. The website is just the app: it starts empty, and you import `sync-output.json` into each browser you use. Anyone with the link can open the site, but they see no data.

---

## 1. One-time setup

You need macOS with Google Chrome, Python 3, and git.

```sh
cd ~/_projects/bjj-journal
python3 -m pip install -r requirements.txt
python3 -m playwright install chromium
```

No passwords are stored in the project. You log in to Jits.gg and Smoothcomp yourself, in the Chrome window the sync opens.

## 2. Add competitors

Competitors are listed in `kids.json`, which stays on your computer. On a fresh copy of the project, create it from the example first:

```sh
cp kids.example.json kids.json
```

Add one entry per kid:

```json
[
  {
    "id": "alex",
    "name": "Alex Example",
    "jitsUrl": "https://jits.gg/fighter/alex-example-12345",
    "smoothcompUrl": "https://smoothcomp.com/en/profile/1234567"
  },
  {
    "id": "sam",
    "name": "Sam Example",
    "jitsUrl": "https://jits.gg/fighter/sam-example-67890"
  }
]
```

- `id`: short, lowercase, no spaces. Don't change it later; matches are linked to it.
- `jitsUrl` / `smoothcompUrl`: copy them from the address bar on each profile page. Either one can be left out.
- Separate entries with a comma, and keep the `[` and `]` around the list.
- Adding a kid with **Add kid** in the web app does not change `kids.json`, so the sync won't pick them up.

## 3. Get the data

**a. Open the profiles:**

```sh
python3 sync_data.py --open
```

A Chrome window opens with a Jits.gg and a Smoothcomp tab for every kid. If the window is already open, only missing tabs are added. In that window, the first time only:

- Log in to Jits.gg and Smoothcomp.
- Clear any Cloudflare "Verify you are human" check in each tab.

Leave the window open. It keeps its logins between runs (in `sync-chrome-profile/`, which is not committed).

**b. Run the sync:**

```sh
python3 sync_data.py
```

It reads each tab without reloading it:

- **Jits.gg:** clicks **View All** to load every match, then reads the **Tournaments** tab for medals.
- **Smoothcomp:** goes through every page (**1, 2, 3, Next**) for matches and division results.

It writes `sync-output.json` and prints a summary. Check for lines like:

- `read 26 match rows`: each Jits.gg count should match the profile's recorded matches. A `WARNING ... only N rows were read` usually means Jits.gg is logged out in that window.
- `Wrote sync-output.json with N matches`

If a site asks you to log in or pass a check, the script says so and waits. Do it in the Chrome window, then press **Enter** in the terminal if asked.

Syncing never loses data: matches and medals found by earlier syncs are kept, even if a later run sees fewer.

## 4. Check it locally (optional)

```sh
./start.command
```

This starts a local server and opens http://localhost:4173, which loads `sync-output.json` automatically. You can also double-click `start.command` in Finder. It serves files with caching turned off, so a reload always shows the latest code and data.

If a server from an older version is still running on port 4173, restart it once:

```sh
kill $(lsof -tiTCP:4173 -sTCP:LISTEN)
./start.command
```

## 5. See the data on the website

1. Open https://alain-labrada.github.io/bjj-journal/.
2. Click **⇧** at the top right, or go to **Sources & sync → Import JSON**.
3. Choose `sync-output.json` from your project folder (`~/_projects/bjj-journal/`).

A message like "Journal imported: +176 match records" confirms it. The data is saved in that browser only, not on the website. After each new sync, import the file again; new matches are added and nothing is duplicated.

On a phone or another computer, you need a copy of `sync-output.json` on that device (for example via AirDrop or iCloud Drive), then import it the same way. Clearing the browser's site data removes the imported data; import again to restore it.

## 6. Publish app changes

Only code changes need pushing. Your data files are ignored, so they stay out of commits.

```sh
git add -A
git status        # kids.json and sync-output.json must not appear
git commit -m "Describe what changed"
git push
```

GitHub Pages rebuilds within a minute or two; reload the site with **⌘ + Shift + R** to get the new version.

---

## Using the app

- **Athlete:** pick a kid at the top. Every view shows that kid's data.
- **Overview:** totals, frequent opponents, latest matches and the Jits.gg record.
- **All matches:** every match, newest first. A match found on both sites appears once, labeled `smoothcomp + jits.gg`.
- **Opponents:** head-to-head record per opponent. **Met at 2+ competitions** filters to opponents faced at more than one event.
- **Reports:**
  - **Competition history:** each competition's date, wins, losses and medals, with totals.
  - **Weight class over time:** the lightest weight-class limit entered at each competition. The sites don't record actual weights.
  - **Wins and losses per competition:** a bar chart; hover a bar for details. **Show table** under each chart lists the exact numbers.
- **Sources & sync → Import JSON:** loads a sync file into this browser. This is how data gets onto the website.

Locally (`./start.command`), the app loads `sync-output.json` automatically. Data shown in the app is also saved in the browser, and importing or loading the same file again never duplicates anything.

---

## Troubleshooting

**Cloudflare keeps asking to verify.** Use the `--open` steps above: pass the check in each tab, leave the window open, then sync. The tabs are read without reloading, so the check isn't triggered again.

**The app shows old data or a blank Reports page.** The browser is using cached files. Reload with **⌘ + Shift + R**, and restart the local server if it predates the no-cache change (step 4).

**A kid needs a different Jits.gg or Smoothcomp login.** A Chrome window can only be logged in to one account per site. Add an `"account"` name to that kid in `kids.json`:

```json
{ "id": "maria", "name": "Maria Lopez", "account": "Lopez family", "jitsUrl": "...", "smoothcompUrl": "..." }
```

`--open` then opens a separate window for that account (with its own saved logins in `sync-chrome-profile-lopez-family/`). Log in there with the other account. Kids with no account share the main window. Kids your current login can already see don't need this.

**Chrome won't open or the sync can't connect.** Quit any Roll Call Chrome window and run `python3 sync_data.py --open` again. The main window uses debugging port 9223; accounts use 9224 and up.

**A source failed.** The script saves a screenshot of the page to `sync-debug/`. Both sites are read from their page text, so the parser may need updating if Jits.gg or Smoothcomp change their layout.

## Command reference

| Command | What it does |
|---|---|
| `python3 sync_data.py --open` | Opens the Roll Call Chrome window(s) with a tab per profile, then exits |
| `python3 sync_data.py` | Reads every profile and writes `sync-output.json` |
| `python3 sync_data.py --hidden` | Same, with no window. Only works when nothing asks for a login or Cloudflare check |
| `./start.command` | Runs the app at http://localhost:4173 |

## Files

| File | Purpose | Published |
|---|---|---|
| `index.html`, `app.js`, `styles.css` | The web app | Yes |
| `kids.example.json` | Template for `kids.json` | Yes |
| `kids.json` | Competitors to sync | No (ignored) |
| `sync-output.json` | Synced matches, medals and profile stats | No (ignored) |
| `sync_data.py`, `requirements.txt` | The sync script and its dependency | Yes |
| `start.command` | Local server | Yes |
| `sync-chrome-profile*/` | Chrome logins and cookies for the sync | No (ignored) |
| `sync-debug/` | Screenshots from failed syncs | No (ignored) |
