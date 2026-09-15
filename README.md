# Roll Call

A private, local-first BJJ competition journal for tracking kids, opponents, competitions, divisions, weights, and repeat matchups.

## Run it

Open `index.html` directly in a browser, or serve the folder with any static web server:

```sh
python3 -m http.server 4173
```

Then visit http://localhost:4173.

## Import format

The app accepts a JSON file shaped like this:

```json
{
  "kids": [{ "id": "maya", "name": "Maya Alabrada", "belt": "Green belt" }],
  "matches": [{
    "id": "m1",
    "kidId": "maya",
    "date": "2026-08-30",
    "opponent": "Sofia Mendes",
    "event": "West Coast Open",
    "division": "Girls 13-14 / Gi",
    "weight": "-52 kg",
    "result": "win",
    "source": "jits.gg"
  }]
}
```

Credentials are not stored in this project: you log in to Jits.gg and Smoothcomp by hand in the sync's Chrome window. Since passwords were shared in chat earlier, rotate them.

## Local sync script

`kids.json` contains the profile URLs to sync (copy `kids.example.json` to start). Install the browser dependency once:

```sh
python3 -m pip install -r requirements.txt
python3 -m playwright install chromium
```

Then run the sync:

```sh
python3 sync_data.py
```

The script opens Google Chrome as a normal app with its own saved profile (`sync-chrome-profile/`, ignored by git) and attaches to it through a local debugging port (9223, change with `ROLL_CALL_DEBUG_PORT`). Chrome is not started in automation mode, which keeps Cloudflare from re-checking every page after you have passed its check. The first time, it opens the Jits.gg and Smoothcomp login pages: log in to both in that window (finishing any Cloudflare check or email code), then press **Enter** in the terminal. The whole sync runs in that window, and later runs reuse the saved logins, so you only log in again when a session expires. If a Cloudflare check appears on a profile page, complete it in the window; the script waits up to five minutes.

### Competitors that need a different login

A Chrome window can be logged in to one Jits.gg and one Smoothcomp account at a time. For a competitor whose profiles need another login, add an `"account"` name to their entry in `kids.json`:

```json
{
  "id": "maria",
  "name": "Maria Lopez",
  "account": "Lopez family",
  "jitsUrl": "https://jits.gg/fighter/...",
  "smoothcompUrl": "https://smoothcomp.com/en/profile/..."
}
```

Each account gets its own Chrome window with its own saved logins (`sync-chrome-profile-lopez-family/`). Competitors without an account share the default window. `--open` opens one window per account, and the sync works through them one at a time, asking you to log in to any window that needs it.

### Sync from tabs you already have open

If Cloudflare keeps checking profile pages, open them yourself first:

```sh
python3 sync_data.py --open   # opens the Roll Call Chrome window with a tab per kid per site, then exits
```

Log in and clear any check in each tab, leave the window open, then run `python3 sync_data.py`. Tabs already showing a profile are read in place without reloading, the login check is skipped for them, and the window stays open afterwards. Only tabs in this Roll Call window can be read; Chrome does not let scripts attach to your everyday browser profile.

On Jits.gg the script follows **View All** (or **See more**) until every match row is loaded, and warns if it read fewer rows than the profile's recorded match count. On Smoothcomp it clicks **Next** through the numbered pages and joins them, so an event that continues onto the next page keeps its name and date. Afterwards each tab is put back on the profile's first page, so the next sync recognises it. Medals come from Smoothcomp's division results ("WON GOLD", "Placement 4") and the Jits.gg profile's **Tournaments** tab, which the script opens after reading the matches. Once both sites stay signed in you can try `python3 sync_data.py --hidden`, but Cloudflare usually needs the visible window.

### Reuse an already-open Chrome login

Chrome does not allow remote debugging on the normal profile in recent versions. Use a separate Roll Call browser profile. Quit the debug Chrome window if it is open, then start this profile:

```sh
open -na "Google Chrome" --args --remote-debugging-port=9222 --user-data-dir="$HOME/Library/Application Support/Roll Call Chrome"
```

Log in to Jits.gg and Smoothcomp in that new Chrome window. This is a one-time login; the profile keeps its cookies. Then run the sync from another Terminal:

```sh
ROLL_CALL_CDP_URL=http://127.0.0.1:9222 python3 sync_data.py
```

If you see `ECONNREFUSED`, check the debugging port:

```sh
curl http://127.0.0.1:9222/json/version
```

If that command fails, Chrome was not started with debugging enabled. Quit Chrome completely with `Command + Q`, run the `open -na` command above, and try again.

In this mode the script uses that Chrome's logins and reuses tabs already showing a profile. Do not use this mode while another sync process is using the same browser.

The script writes `sync-output.json`. Import that file from **Sources & sync** in the webpage. Imports merge into the journal: kids are matched by id (or name), matches keep stable ids so re-importing never duplicates them, and matches an older sync found are kept even if a newer one sees fewer rows. A match reported by both Jits.gg and Smoothcomp (same day, opponent, result and Gi/No-Gi) is shown once, labelled with both sources.

When a source fails, the script saves a screenshot to `sync-debug/`. Both parsers read page text, so they may need adjusting if Jits.gg or Smoothcomp change their profile layout.
