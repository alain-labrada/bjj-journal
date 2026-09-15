#!/usr/bin/env python3
"""Fetch fighter source pages into a local Roll Call sync artifact.

The sync runs in one Chrome window with its own saved profile. If Jits.gg or
Smoothcomp is not signed in, the script opens the login page and waits while you
log in by hand (and clear any Cloudflare check); the session is kept for later runs.
Without Playwright, only Jits.gg profile statistics can be read.
"""
from __future__ import annotations

import html
import json
import os
import re
import subprocess
import sys
import time
import unicodedata
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ENV_FILE = ROOT / ".env.local"
PROFILE_FILE = ROOT / "kids.json"
OUTPUT_FILE = ROOT / "sync-output.json"
DEBUG_DIR = ROOT / "sync-debug"
BROWSER_PROFILE_DIR = ROOT / "sync-chrome-profile"
CHROME_APP = Path("/Applications/Google Chrome.app")
CHROME_BINARY = CHROME_APP / "Contents" / "MacOS" / "Google Chrome"
CHROME_DEBUG_PORT = int(os.getenv("ROLL_CALL_DEBUG_PORT", "9223"))
SITES = {
    "Jits.gg": {"login": "https://jits.gg/login", "url_key": "jitsUrl"},
    "Smoothcomp": {"login": "https://smoothcomp.com/en/auth/login", "url_key": "smoothcompUrl"},
}
MAX_PAGES = 30
JITS_MORE_CONTROL = re.compile(r"^\s*((load|show|see|view) (more|all)( matches)?|more matches|next( page)?)\s*[→›»]?\s*$", re.IGNORECASE)
SMOOTHCOMP_NEXT_CONTROL = re.compile(r"^\s*(next( page)?\s*[→›»]?|[›»])\s*$", re.IGNORECASE)
FIRST_PAGE_CONTROL = re.compile(r"^\s*(1|first|«)\s*$", re.IGNORECASE)
PREVIOUS_PAGE_CONTROL = re.compile(r"^\s*([←‹«]\s*)?(previous|prev)( page)?\s*$|^\s*‹\s*$", re.IGNORECASE)
JITS_SIGNED_OUT = re.compile(r"more matches available|sign in or create a free account", re.IGNORECASE)
CHALLENGE_PATTERN = r"security verification|just a moment|verify you are human|checking your browser|performance and security by cloudflare"
MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"
SHORT_MONTHS = "Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec"
WEIGHT_PATTERN = re.compile(
    r"\(?\d+(?:\.\d+)?\s*-\s*\d+(?:\.\d+)?\s*(?:lbs?|kg)\.?\)?"
    r"|(?:under|over|up to)\s*\d+(?:\.\d+)?\s*(?:lbs?|kg)\.?"
    r"|[-+]?\d+(?:\.\d+)?\s*(?:lbs?|kg)\b\.?",
    re.IGNORECASE,
)


def log(message: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {message}", flush=True)


def headless_mode() -> bool:
    return os.getenv("ROLL_CALL_HEADLESS", "0").lower() not in {"0", "false", "no"}


def playwright_available() -> bool:
    try:
        import playwright.sync_api  # noqa: F401
    except ImportError:
        return False
    return True


def debug_port_ready(cdp_url: str) -> bool:
    try:
        with urllib.request.urlopen(f"{cdp_url}/json/version", timeout=1):
            return True
    except OSError:
        return False


def start_chrome(profile_dir: Path, port: int, extra_args: tuple[str, ...] = ()) -> tuple[str, subprocess.Popen | None]:
    """Start Chrome as a normal app (not in automation mode) with a debugging port the script can attach to."""
    cdp_url = f"http://127.0.0.1:{port}"
    if debug_port_ready(cdp_url):
        log(f"Reusing the Roll Call Chrome window already open on port {port}")
        return cdp_url, None
    log(f"Opening Chrome with the saved Roll Call profile ({profile_dir.name}/)")
    process = subprocess.Popen(
        [str(CHROME_BINARY), f"--remote-debugging-port={port}", f"--user-data-dir={profile_dir}", "--no-first-run", "--no-default-browser-check", *extra_args, "about:blank"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,  # keep the window open if the script exits (used by --open)
    )
    deadline = time.monotonic() + 20
    while not debug_port_ready(cdp_url):
        if process.poll() is not None or time.monotonic() > deadline:
            process.terminate()
            raise RuntimeError(f"Chrome did not open its debugging port {port}. Close any Chrome window using {profile_dir.name}/ and retry.")
        time.sleep(0.3)
    return cdp_url, process


def account_groups(profiles: list[dict]) -> list[dict]:
    """Group profiles by their optional "account" in kids.json.

    Each account gets its own Chrome window (profile folder and debugging port), so it can stay
    logged in to Jits.gg and Smoothcomp with different logins. Profiles without an account share
    the default window.
    """
    groups: dict[str, list[dict]] = {}
    for profile in profiles:
        groups.setdefault(profile.get("account") or "", []).append(profile)
    named = [name for name in groups if name]
    result = []
    if "" in groups:
        result.append({"name": "", "label": "default", "profiles": groups[""], "profile_dir": BROWSER_PROFILE_DIR, "port": CHROME_DEBUG_PORT})
    for index, name in enumerate(named):
        result.append({"name": name, "label": name, "profiles": groups[name], "profile_dir": ROOT / f"sync-chrome-profile-{slug(name)}", "port": CHROME_DEBUG_PORT + 1 + index})
    return result


def connect_browser(playwright, group: dict):
    """Return (context, reuse_tabs, close). reuse_tabs means tabs already showing a profile may be read in place."""
    # ROLL_CALL_CDP_URL points at one Chrome you started yourself; it applies to the default account only.
    cdp_url = os.getenv("ROLL_CALL_CDP_URL") if not group["name"] else None
    process = None
    if not cdp_url and not headless_mode() and CHROME_APP.exists():
        # Cloudflare keeps re-checking a Chrome that Playwright launched in automation mode, so launch it normally and attach.
        cdp_url, process = start_chrome(group["profile_dir"], group["port"])
    if cdp_url:
        try:
            browser = playwright.chromium.connect_over_cdp(cdp_url)
        except Exception as exc:
            if process:
                process.terminate()
            raise RuntimeError(f"Cannot connect to Chrome at {cdp_url}. Quit that Chrome window and retry.") from exc
        context = browser.contexts[0] if browser.contexts else browser.new_context()

        def close() -> None:
            if not process:
                return  # leave a window the user opened (or --open started) running
            try:
                browser.new_browser_cdp_session().send("Browser.close")
                process.wait(timeout=10)
            except Exception:
                process.terminate()

        return context, True, close
    log(f"Opening {'Chrome' if CHROME_APP.exists() else 'Chromium'} with the saved Roll Call profile ({group['profile_dir'].name}/)")
    context = playwright.chromium.launch_persistent_context(str(group["profile_dir"]), channel="chrome" if CHROME_APP.exists() else None, headless=headless_mode(), no_viewport=True)
    return context, False, context.close


def page_text(page) -> str:
    try:
        return page.locator("body").inner_text()
    except Exception:
        return ""


def is_signed_in(page, login_url: str) -> bool:
    """A signed-in session is redirected away from the login page."""
    return page.url.split("?")[0].rstrip("/") != login_url.rstrip("/") and "login" not in page.url.lower()


def ensure_signed_in(context, sites: list[str], window: str = "default") -> None:
    """Open each site's login page; if any is not signed in, wait for the user to log in by hand."""
    pending = {}
    for site in sites:
        login_url = SITES[site]["login"]
        page = context.new_page()
        page.goto(login_url, wait_until="domcontentloaded")
        page.wait_for_timeout(2500)
        if is_signed_in(page, login_url):
            log(f"{site}: already signed in")
            page.close()
        else:
            pending[site] = page
    if not pending:
        return
    names = " and ".join(pending)
    if headless_mode() or not sys.stdin.isatty():
        log(f"WARNING {names} not signed in; run `python3 sync_data.py` in a terminal (without --hidden) to log in")
        return
    pending[next(iter(pending))].bring_to_front()
    log(f"{names}: log in in the Chrome window for the {window!r} account (finish any Cloudflare check or email code there)")
    input(f"    Press Enter here once the {window!r} window is logged in to every site... ")
    for site, page in pending.items():
        page.goto(SITES[site]["login"], wait_until="domcontentloaded")
        page.wait_for_timeout(2500)
        log(f"{site}: {'signed in' if is_signed_in(page, SITES[site]['login']) else 'WARNING still looks signed out; continuing anyway'}")
        page.close()


def same_page(url: str, other: str) -> bool:
    return url.split("#")[0].split("?")[0].rstrip("/") == other.split("#")[0].split("?")[0].rstrip("/")


def profile_urls(profiles: list[dict]) -> list[tuple[str, dict, str]]:
    return [(site, profile, profile[config["url_key"]]) for profile in profiles for site, config in SITES.items() if profile.get(config["url_key"])]


def sites_to_check(context, reuse_tabs: bool, profiles: list[dict]) -> list[str]:
    """Sites that need a login check: those with at least one profile not already open in a tab."""
    open_urls = [page.url for page in context.pages] if reuse_tabs else []
    return sorted({site for site, _, url in profile_urls(profiles) if not any(same_page(open_url, url) for open_url in open_urls)})


def open_profile_tabs(playwright, profiles: list[dict]) -> int:
    """--open: start one Roll Call Chrome window per account, each with a tab per profile, and leave them running."""
    if not CHROME_APP.exists():
        print("--open needs Google Chrome in /Applications.", file=sys.stderr)
        return 1
    for group in account_groups(profiles):
        log(f"Account {group['label']!r}: window uses {group['profile_dir'].name}/")
        cdp_url, _ = start_chrome(group["profile_dir"], group["port"])
        browser = playwright.chromium.connect_over_cdp(cdp_url)
        context = browser.contexts[0] if browser.contexts else browser.new_context()
        for site, profile, url in profile_urls(group["profiles"]):
            if any(same_page(page.url, url) for page in context.pages):
                log(f"{site}: {profile['name']} is already open")
                continue
            context.new_page().goto(url, wait_until="commit")
            log(f"{site}: opened {profile['name']}")
        for page in context.pages:
            if page.url == "about:blank" and len(context.pages) > 1:
                page.close()
    log("In each window, log in with that account and clear any Cloudflare check. Leave the windows open, then run: python3 sync_data.py")
    return 0


def open_profile_page(context, connected: bool, profile_url: str, athlete_name: str):
    """Return (page, created). In a connected Chrome, reuse a tab already showing the profile."""
    if connected:
        tabs = [page for page in context.pages if same_page(page.url, profile_url)]
        if tabs:
            page = max(tabs, key=lambda tab: (athlete_name.lower() in page_text(tab).lower(), len(page_text(tab))))  # noqa: B023
            log(f"Using existing tab for {athlete_name}")
            return page, False
    page = context.new_page()
    page.goto(profile_url, wait_until="domcontentloaded")
    return page, True


def read_after_challenge(page, source: str) -> str:
    seconds = 30 if headless_mode() else 300
    if re.search(CHALLENGE_PATTERN, page_text(page), re.IGNORECASE):
        page.bring_to_front()
        log(f"{source}: Cloudflare check showing; complete it in the browser window (waiting up to {seconds} seconds)")
    try:
        page.wait_for_function(
            """(challengePattern) => {
                const text = document.body?.innerText || '';
                return text.trim().length > 100 && !(new RegExp(challengePattern, 'i')).test(text);
            }""",
            arg=CHALLENGE_PATTERN,
            timeout=seconds * 1000,
        )
    except Exception as exc:
        hint = " Run without --hidden and complete the check in the browser window." if headless_mode() else ""
        raise RuntimeError(f"profile remained behind a Cloudflare challenge after {seconds} seconds: {page.url}.{hint}") from exc
    return page_text(page)


def save_debug_screenshot(page, source: str) -> None:
    try:
        DEBUG_DIR.mkdir(exist_ok=True)
        screenshot_path = (DEBUG_DIR / f"{source}.png").resolve()
        page.screenshot(path=str(screenshot_path), full_page=True)
        log(f"{source}: saved diagnostic screenshot to {screenshot_path} (page was {page.url})")
    except Exception as exc:
        log(f"{source}: could not save diagnostic screenshot: {exc}")


class TextParser(HTMLParser):
    """Extract visible text, keeping block elements on separate lines."""

    BLOCK_TAGS = {"article", "br", "div", "h1", "h2", "h3", "h4", "h5", "h6", "header", "footer", "li", "main", "p", "section", "td", "th", "tr"}
    HIDDEN_TAGS = {"script", "style", "noscript", "template"}

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.hidden_depth = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in self.HIDDEN_TAGS:
            self.hidden_depth += 1
        elif tag in self.BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self.HIDDEN_TAGS:
            self.hidden_depth = max(0, self.hidden_depth - 1)
        elif tag in self.BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        value = " ".join(data.split())
        if value and not self.hidden_depth:
            self.parts.append(value)

    def text(self) -> str:
        lines = (" ".join(line.split()) for line in " ".join(self.parts).split("\n"))
        return "\n".join(line for line in lines if line)


def load_env() -> None:
    if not ENV_FILE.exists():
        return
    for raw_line in ENV_FILE.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def fetch_text(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "RollCall/1.0"})
    with urllib.request.urlopen(request, timeout=30) as response:
        parser = TextParser()
        parser.feed(response.read().decode("utf-8", errors="replace"))
        return html.unescape(parser.text())


def first_number(pattern: str, text: str) -> int | None:
    match = re.search(pattern, text, re.IGNORECASE)
    return int(match.group(1)) if match else None


def _record_from_text(text: str) -> dict | None:
    record = re.search(r"(\d+)\s*-\s*(\d+)\s+competition record", text, re.IGNORECASE)
    return {"wins": int(record.group(1)), "losses": int(record.group(2))} if record else None


def normalize_date(value: str) -> str:
    for pattern in ("%b %d, %Y", "%B %d %Y"):
        try:
            return datetime.strptime(value.strip(), pattern).date().isoformat()
        except ValueError:
            continue
    return value.strip()


def parse_weight(division: str) -> str:
    match = WEIGHT_PATTERN.search(division)
    return match.group(0).strip("() ") if match else ""


def division_format(division: str) -> str:
    if re.search(r"takedown", division, re.IGNORECASE):
        return "Takedowns"
    if re.search(r"no[\s-]?gi", division, re.IGNORECASE):
        return "No-Gi"
    if re.search(r"\bgi\b", division, re.IGNORECASE):
        return "Gi"
    return ""


def tidy_name(name: str) -> str:
    """Title-case words a source wrote in all caps, e.g. 'Mason REINHARDT'."""
    return " ".join(word.capitalize() if len(word) > 1 and word.isupper() else word for word in name.split())


def slug(value: str) -> str:
    ascii_value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", ascii_value.lower()).strip("-")


def assign_ids(matches: list[dict]) -> list[dict]:
    """Give matches (or placements) ids that stay the same when a later sync finds more rows."""
    seen: Counter[str] = Counter()
    for match in matches:
        subject = slug(match["opponent"]) if "opponent" in match else f"place-{slug(match.get('division', ''))}"
        base = f"{match['source'].split('.')[0]}-{match['kidId']}-{match['date']}-{subject}"
        seen[base] += 1
        match["id"] = f"{base}-{seen[base]}"
    return matches


def extract_jits_matches(kid_id: str, text: str) -> list[dict]:
    lines = [line.strip() for line in text.splitlines()]
    start = next((index for index, line in enumerate(lines) if "Result" in line and "Fighter" in line), -1)
    matches = []
    if start < 0:
        return matches
    date_pattern = re.compile(rf"((?:{SHORT_MONTHS}) \d{{1,2}}, \d{{4}})")
    for index in range(start + 1, len(lines)):
        if re.search(r"more matches available", lines[index], re.IGNORECASE):
            break
        result_match = re.match(r"^([WL])\s*(?:\t(.*)|$)", lines[index])
        if not result_match:
            continue
        values = [line for line in lines[index + 1:index + 10] if line]
        date_index = next((i for i, value in enumerate(values) if re.search(rf"(?:{SHORT_MONTHS}|{MONTHS}) \d{{1,2}}[ ,]+\d{{4}}", value)), -1)
        if len(values) < 4 or date_index < 0:
            continue
        date_match = date_pattern.search(values[date_index])
        date = normalize_date(date_match.group(1)) if date_match else normalize_date(values[date_index])
        division = values[date_index - 2] if date_index >= 2 else ""
        event = values[date_index - 1] if date_index >= 1 else ""
        fmt = values[date_index].split(date_match.group(1))[0].strip() if date_match else ""
        matches.append({
            "kidId": kid_id,
            "date": date,
            "opponent": tidy_name(values[0]),
            "event": event,
            "division": division,
            "weight": parse_weight(division),
            "result": "win" if result_match.group(1) == "W" else "loss",
            "source": "jits.gg",
            "format": fmt or division_format(division),
            "method": (result_match.group(2) or "").strip(),
        })
    return assign_ids(matches)


def extract_smoothcomp_matches(kid_id: str, text: str) -> list[dict]:
    """Parse the profile's event list: event name, date line, division lines, then WIN/LOSS rows."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    date_pattern = re.compile(rf"^(?:{MONTHS}) \d{{1,2}} \d{{4}}$")
    outcome_pattern = re.compile(r"^(WIN|LOSS)(.+?)(?:Won|Lost) by (.+)$")
    event = date = division = ""
    matches = []
    for index, line in enumerate(lines):
        if date_pattern.match(line):
            date = normalize_date(line)
            event = lines[index - 1] if index else ""
            division = ""
            continue
        if not date:
            continue
        outcome = outcome_pattern.match(line)
        if outcome:
            result, opponent, method = outcome.groups()
            matches.append({
                "kidId": kid_id,
                "date": date,
                "opponent": tidy_name(opponent.strip()),
                "event": event,
                "division": division,
                "weight": parse_weight(division),
                "result": "win" if result == "WIN" else "loss",
                "source": "smoothcomp",
                "format": division_format(division),
                "method": method.strip(),
            })
        elif " / " in line:
            division = line
    return assign_ids(matches)


MEDALS = {"G": "gold", "S": "silver", "B": "bronze", "GOLD": "gold", "SILVER": "silver", "BRONZE": "bronze"}


def placement(kid_id: str, source: str, date: str, event: str, division: str, medal: str | None, place: int | None) -> dict:
    return {"kidId": kid_id, "date": date, "event": event, "division": division, "format": division_format(division), "medal": medal, "place": place, "source": source}


def extract_smoothcomp_placements(kid_id: str, text: str) -> list[dict]:
    """Division results that follow each division's matches: "WON GOLD" or "Placement 4"."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    date_pattern = re.compile(rf"^(?:{MONTHS}) \d{{1,2}} \d{{4}}$")
    event = date = division = ""
    placements = []
    for index, line in enumerate(lines):
        if date_pattern.match(line):
            date, event, division = normalize_date(line), lines[index - 1] if index else "", ""
        elif date and " / " in line:
            division = line
        elif date and division and (won := re.match(r"^WON (GOLD|SILVER|BRONZE)$", line, re.IGNORECASE)):
            placements.append(placement(kid_id, "smoothcomp", date, event, division, MEDALS[won.group(1).upper()], {"GOLD": 1, "SILVER": 2, "BRONZE": 3}[won.group(1).upper()]))
        elif date and division and (placed := re.match(r"^Placement (\d+)$", line, re.IGNORECASE)):
            placements.append(placement(kid_id, "smoothcomp", date, event, division, None, int(placed.group(1))))
    return assign_ids(placements)


def extract_jits_placements(kid_id: str, text: str) -> list[dict]:
    """Rows of the profile's Tournaments tab: date, tournament, "N matches", medal (G/S/B/-), rating change, division, weight."""
    lines = [line.strip() for line in text.splitlines()]
    start = next((index for index, line in enumerate(lines) if "Tournament" in line and "Medal" in line), -1)
    placements = []
    if start < 0:
        return placements
    for index in range(start + 1, len(lines)):
        if re.search(r"more matches available", lines[index], re.IGNORECASE):
            break
        date_match = re.fullmatch(rf"((?:{SHORT_MONTHS}) \d{{1,2}}, \d{{4}})", lines[index])
        values = [line for line in lines[index + 1:index + 9] if line]
        if not date_match or len(values) < 5 or not re.fullmatch(r"\d+ match(es)?", values[1]):
            continue
        medal = MEDALS.get(values[2].upper())
        division = values[4]
        placements.append(placement(kid_id, "jits.gg", normalize_date(date_match.group(1)), values[0], division, medal, {"gold": 1, "silver": 2, "bronze": 3}.get(medal)))
    return assign_ids(placements)


def match_signatures(rows: list[dict]) -> list[tuple]:
    return [tuple((key, value) for key, value in sorted(row.items()) if key != "id") for row in rows]


def wait_for_text_change(page, before_text: str, source: str, seconds: float = 8) -> str | None:
    """Poll until the page text differs from `before_text` and stops changing, waiting out any Cloudflare check."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        page.wait_for_timeout(500)
        text = page_text(page)
        if re.search(CHALLENGE_PATTERN, text, re.IGNORECASE):
            text = read_after_challenge(page, source)
            deadline = time.monotonic() + seconds
        if text and text != before_text:
            page.wait_for_timeout(700)
            settled = page_text(page)
            if settled == text:
                return text
    return None


def wait_for_first_rows(page, extract, source: str, seconds: float = 15) -> str:
    deadline = time.monotonic() + seconds
    text = page_text(page)
    while not extract(text) and time.monotonic() < deadline:
        page.wait_for_timeout(500)
        text = page_text(page) if not re.search(CHALLENGE_PATTERN, page_text(page), re.IGNORECASE) else read_after_challenge(page, source)
    return text


def paging_controls(page, pattern: re.Pattern) -> list:
    # Controls may be real buttons/links or plain elements with click handlers (an <a> without href has no link role).
    locator = page.get_by_role("button", name=pattern).or_(page.get_by_role("link", name=pattern)).or_(page.get_by_text(pattern))
    return [control for control in locator.all() if control.is_visible() and control.evaluate("el => !el.closest('[disabled], [aria-disabled=\"true\"], .disabled')")]


def return_to(page, url: str) -> None:
    """Put a tab back on the URL it started on, so later syncs still recognise it."""
    for _ in range(MAX_PAGES):
        if page.url == url:
            return
        previous_url = page.url
        try:
            page.go_back(wait_until="domcontentloaded")
        except Exception:
            break
        if page.url == previous_url:
            break
    if page.url != url:
        page.goto(url, wait_until="domcontentloaded")


def rewind_to_first_page(page, source: str) -> None:
    """A reused tab may have been left on a later page; go back to page 1 so no newer rows are skipped."""
    query = urllib.parse.urlsplit(page.url)
    params = urllib.parse.parse_qsl(query.query)
    if any(key.lower() == "page" and value not in {"", "0", "1"} for key, value in params):
        first_url = urllib.parse.urlunsplit(query._replace(query=urllib.parse.urlencode([(k, v) for k, v in params if k.lower() != "page"])))
        log(f"{source}: tab was on a later page; going back to page 1")
        page.goto(first_url, wait_until="domcontentloaded")
        read_after_challenge(page, source)
        return
    if not paging_controls(page, PREVIOUS_PAGE_CONTROL):
        return
    log(f"{source}: tab was on a later page; going back to page 1")
    for _ in range(MAX_PAGES):
        controls = paging_controls(page, FIRST_PAGE_CONTROL) or paging_controls(page, PREVIOUS_PAGE_CONTROL)
        if not controls:
            return
        before = page_text(page)
        try:
            controls[0].click(timeout=5000)
        except Exception:
            return
        if wait_for_text_change(page, before, source) is None or not paging_controls(page, PREVIOUS_PAGE_CONTROL):
            return


def collect_all_rows(page, extract, control_pattern: re.Pattern, source: str) -> tuple[str, list[dict], str]:
    """Return (first page text, rows from every page, joined page text), following "See more", "View All" or "Next" controls.

    `extract` turns page text into rows. Paginated pages are parsed from their joined text, so an
    event that continues onto the next page keeps its name and date. Tabs end where they started.
    """
    rewind_to_first_page(page, source)
    start_url = page.url
    first_text = wait_for_first_rows(page, extract, source)
    if not extract(first_text):
        return first_text, [], first_text
    page_texts = [first_text]
    rows = extract(first_text)
    current = page
    opened_tabs = []
    last_worked = None
    for _ in range(MAX_PAGES):
        controls = paging_controls(current, control_pattern)
        progressed = False
        for index in sorted(range(len(controls)), key=lambda i: i != last_worked):
            tabs_before = list(current.context.pages)
            url_before, text_before = current.url, page_texts[-1]
            try:
                controls[index].scroll_into_view_if_needed(timeout=3000)
                controls[index].click(timeout=5000)
            except Exception:
                continue
            current.wait_for_timeout(300)
            new_tabs = [tab for tab in current.context.pages if tab not in tabs_before]
            target = new_tabs[0] if new_tabs else current
            new_text = wait_for_text_change(target, "" if new_tabs else text_before, source)
            if new_text:
                visible = Counter(match_signatures(extract(text_before)))
                if not visible - Counter(match_signatures(extract(new_text))):
                    candidate = page_texts[:-1] + [new_text]  # the list grew, or "View All" shows everything already read
                else:
                    candidate = page_texts + [new_text]  # a paginated list replaced its rows
                candidate_rows = extract("\n".join(candidate))
                if len(candidate_rows) > len(rows):
                    page_texts, rows, current, progressed = candidate, candidate_rows, target, True
                    last_worked = index if not new_tabs else None
                    opened_tabs.extend(new_tabs)
                    break
            for tab in new_tabs:
                tab.close()
            if current.url != url_before:
                return_to(current, url_before)  # the control led somewhere without new match rows
        if not progressed:
            break
        log(f"{source}: loaded more matches ({len(rows)} so far)")
    for tab in opened_tabs:
        tab.close()
    return_to(page, start_url)
    if len(page_texts) > 1 and page.url == start_url and page_text(page) != first_text:
        # In-page pagination does not change the URL; click back to page 1 so the next sync starts there.
        for control in paging_controls(page, FIRST_PAGE_CONTROL)[:1]:
            control.click(timeout=5000)
            wait_for_text_change(page, page_texts[-1], source, seconds=5)
    return first_text, rows, "\n".join(page_texts)


def read_jits_tournaments(page, kid_id: str) -> list[dict]:
    """Switch the record table to its Tournaments tab, read every row, then switch back to Match View."""
    try:
        page.get_by_role("button", name="Tournaments", exact=True).last.click(timeout=5000)
    except Exception:
        log("Jits.gg: no Tournaments tab found; skipping medals")
        return []
    try:
        _, placements, _ = collect_all_rows(page, lambda text: extract_jits_placements(kid_id, text), JITS_MORE_CONTROL, "Jits.gg")
        return placements
    finally:
        try:
            page.get_by_role("button", name="Match View", exact=True).last.click(timeout=5000)
        except Exception:
            pass


def jits_result(profile: dict, text: str, matches: list[dict], placements: list[dict] | None = None) -> dict:
    record = _record_from_text(text)
    if not record:
        log("Jits.gg: browser page contained no fighter record; using public profile HTML")
        text = fetch_text(profile["jitsUrl"])
        record = _record_from_text(text)
    matches_recorded = first_number(r"across\s+(\d+)\s+recorded matches", text)
    if matches_recorded and len(matches) < matches_recorded:
        log(f"Jits.gg: WARNING {profile['name']} has {matches_recorded} recorded matches but only {len(matches)} rows were read")
    return {
        "source": "jits.gg",
        "url": profile["jitsUrl"],
        "record": record,
        "matchesRecorded": matches_recorded,
        "tournaments": first_number(r"recorded matches and (\d+) recorded tournaments", text),
        "summary": text[:1200],
        "matches": matches,
        "placements": placements or [],
    }


def read_jits_profile(context, connected: bool, profile: dict) -> dict:
    if context is None:
        log("Jits.gg: Playwright is not installed; reading profile statistics only (match rows need a browser)")
        return jits_result(profile, fetch_text(profile["jitsUrl"]), [])
    page, created = open_profile_page(context, connected, profile["jitsUrl"], profile["name"])
    try:
        read_after_challenge(page, "Jits.gg")
        text, matches, _ = collect_all_rows(page, lambda page_text_: extract_jits_matches(profile["id"], page_text_), JITS_MORE_CONTROL, "Jits.gg")
        if JITS_SIGNED_OUT.search(page_text(page)):
            log("Jits.gg: WARNING the profile page looks signed out, so only the latest matches are visible")
        log(f"Jits.gg: read {len(matches)} match rows at {page.url}")
        placements = read_jits_tournaments(page, profile["id"])
        log(f"Jits.gg: read {len(placements)} division placements")
        return jits_result(profile, text, matches, placements)
    except Exception:
        save_debug_screenshot(page, "jits")
        raise
    finally:
        if created:
            page.close()


def read_smoothcomp_profile(context, connected: bool, profile: dict) -> dict:
    if context is None:
        raise RuntimeError("Smoothcomp sync needs Playwright. Run: python3 -m pip install -r requirements.txt")
    page, created = open_profile_page(context, connected, profile["smoothcompUrl"], profile["name"])
    try:
        if not created and len(page_text(page)) < 1000:
            log("Smoothcomp: existing tab is only partially loaded; refreshing profile")
            page.reload(wait_until="domcontentloaded")
        read_after_challenge(page, "Smoothcomp")
        text, matches, all_text = collect_all_rows(page, lambda page_text_: extract_smoothcomp_matches(profile["id"], page_text_), SMOOTHCOMP_NEXT_CONTROL, "Smoothcomp")
        placements = extract_smoothcomp_placements(profile["id"], all_text)
        log(f"Smoothcomp: read {len(matches)} match rows and {len(placements)} division placements at {page.url}")
        return {"source": "smoothcomp", "url": profile["smoothcompUrl"], "summary": text[:2000], "matches": matches, "placements": placements}
    except Exception:
        save_debug_screenshot(page, "smoothcomp")
        raise
    finally:
        if created:
            page.close()


USAGE = """usage: python3 sync_data.py [--open | --hidden]
  Opens Chrome; if a site is not signed in, log in there and press Enter in this terminal.
  Kids with an "account" in kids.json get their own Chrome window, so they can use a different login.
  Profile tabs already open in the Roll Call Chrome window are read in place, without reloading.
  --open    open the Roll Call Chrome window with a tab per profile and exit (then log in, then sync)
  --hidden  run without a window (only works once both sites are signed in and Cloudflare is not asking)"""


def parse_args(argv: list[str]) -> dict | None:
    """Apply command-line options; return None when the arguments are invalid."""
    options = {"open": False}
    for arg in argv:
        if arg == "--open":
            options["open"] = True
        elif arg == "--hidden":
            os.environ["ROLL_CALL_HEADLESS"] = "1"
        elif arg == "--visible":
            os.environ["ROLL_CALL_HEADLESS"] = "0"
        elif arg in {"-h", "--help"}:
            print(USAGE)
            return None
        else:
            hint = f" Environment variables go before the command: `{arg} python3 sync_data.py`." if "=" in arg else ""
            print(f"Unknown argument {arg!r}.{hint}\n{USAGE}", file=sys.stderr)
            return None
    return options


def keep_previous_matches(result: dict, previous: dict) -> None:
    """Keep matches and placements from the last sync that this run did not return, so a failed or signed-out run never loses data."""
    kid_ids = {kid["id"] for kid in result["kids"]}
    for key in ("matches", "placements"):
        new_ids = {row["id"] for row in result[key]}
        carried = [row for row in previous.get(key, []) if row.get("kidId") in kid_ids and row.get("id") not in new_ids and re.search(r"-\d{4}-\d{2}-\d{2}-", row.get("id", ""))]
        if carried:
            log(f"Kept {len(carried)} {key} from the previous {OUTPUT_FILE.name} that this run did not return")
        result[key].extend(carried)
    synced = {(source["kidId"], source["source"]) for source in result["sources"]}
    result["sources"].extend(source for source in previous.get("sources", []) if source.get("kidId") in kid_ids and (source.get("kidId"), source.get("source")) not in synced)
    previous_kids = {kid["id"]: kid for kid in previous.get("kids", [])}
    for kid in result["kids"]:
        if "jitsStats" not in kid and "jitsStats" in previous_kids.get(kid["id"], {}):
            kid["jitsStats"] = previous_kids[kid["id"]]["jitsStats"]


def sync_profiles(profiles: list[dict], context, connected: bool) -> dict:
    result = {"updatedAt": datetime.now(timezone.utc).isoformat(), "kids": [], "matches": [], "placements": [], "sources": []}
    readers = [("jitsUrl", "Jits.gg", read_jits_profile), ("smoothcompUrl", "Smoothcomp", read_smoothcomp_profile)]
    for profile in profiles:
        kid = dict(profile)
        for url_key, label, reader in readers:
            if not profile.get(url_key):
                continue
            log(f"{label}: starting {profile['name']}")
            try:
                source = reader(context, connected, profile)
            except Exception as exc:
                log(f"{label}: failed for {profile['name']}")
                print(f"{label}: {profile['name']}: {exc}", file=sys.stderr)
                continue
            summary = {key: value for key, value in source.items() if key not in {"matches", "placements"}}
            result["sources"].append({"kidId": profile["id"], **summary})
            result["matches"].extend(source["matches"])
            result["placements"].extend(source["placements"])
            if source["source"] == "jits.gg":
                kid["jitsStats"] = summary
        result["kids"].append(kid)
    return result


def merge_results(results: list[dict], profiles: list[dict]) -> dict:
    """Combine per-account results, keeping kids in kids.json order (a kid whose window failed still appears)."""
    merged = {"updatedAt": datetime.now(timezone.utc).isoformat(), "kids": [], "matches": [], "placements": [], "sources": []}
    synced_kids = {}
    for result in results:
        for key in ("matches", "placements", "sources"):
            merged[key].extend(result[key])
        synced_kids.update({kid["id"]: kid for kid in result["kids"]})
    merged["kids"] = [synced_kids.get(profile["id"], dict(profile)) for profile in profiles]
    return merged


def main(argv: list[str]) -> int:
    options = parse_args(argv)
    if options is None:
        return 2
    load_env()
    if not PROFILE_FILE.exists():
        print(f"Missing {PROFILE_FILE.name}. Copy kids.example.json to kids.json first.", file=sys.stderr)
        return 1
    profiles = json.loads(PROFILE_FILE.read_text())
    if options["open"]:
        if not playwright_available():
            print("--open needs Playwright. Run: python3 -m pip install -r requirements.txt", file=sys.stderr)
            return 1
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            return open_profile_tabs(playwright, profiles)
    log(f"Starting Roll Call sync for {len(profiles)} athlete profile(s) ({'hidden' if headless_mode() else 'visible'} browser)")
    try:
        previous = json.loads(OUTPUT_FILE.read_text()) if OUTPUT_FILE.exists() else {}
    except json.JSONDecodeError:
        previous = {}

    if playwright_available():
        from playwright.sync_api import sync_playwright

        results = []
        with sync_playwright() as playwright:
            groups = account_groups(profiles)
            for group in groups:
                if len(groups) > 1:
                    log(f"Account {group['label']!r}: {', '.join(profile['name'] for profile in group['profiles'])}")
                try:
                    context, reuse_tabs, close = connect_browser(playwright, group)
                except Exception as exc:
                    log(f"Account {group['label']!r}: could not open its Chrome window")
                    print(f"Account {group['label']!r}: {exc}", file=sys.stderr)
                    continue
                try:
                    ensure_signed_in(context, sites_to_check(context, reuse_tabs, group["profiles"]), group["label"])
                    results.append(sync_profiles(group["profiles"], context, reuse_tabs))
                finally:
                    close()
        result = merge_results(results, profiles)
    else:
        result = sync_profiles(profiles, None, False)

    keep_previous_matches(result, previous)
    OUTPUT_FILE.write_text(json.dumps(result, indent=2) + "\n")
    log(f"Wrote {OUTPUT_FILE.name} with {len(result['matches'])} matches. Import it from Sources & sync.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
