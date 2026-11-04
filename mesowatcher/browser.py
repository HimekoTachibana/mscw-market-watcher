"""Browser-based listing source: opens the site in a real browser, clicks each watched item
and reads the "Newest" listings (seller, channel, location, price, time since listing).

What this does and does not do:
  * It is an ordinary browser (Edge/Chrome through Playwright) with its own saved profile.
    No stealth plugins, no fingerprint spoofing, no CAPTCHA solving.
  * It acts like a person would: type in the filter box, click the item, read the list, with a
    pause (default 1.5 s, never under 0.5 s) between actions. One item at a time.
  * If Cloudflare shows a "Just a moment" check, it STOPS. Turn on "Show browser window" in
    Settings, press Start and complete the check yourself; it carries on when the page loads.
  * Rows are recognised by their visible text (a price followed by "each", "3m ago", "CH 14",
    "FM5"), not by CSS class names, so small layout changes on the site do not break it.
"""
from __future__ import annotations

import os
import random
import re
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Optional

from .core import (ChallengeDetected, Listing, RateLimited, data_dir, fmt_age, norm, parse_number,
                   random_pause_s)

_AGO_RE = re.compile(r"(\d+)\s*(seconds?|secs?|minutes?|mins?|hours?|hrs?|days?|[smhd])\b\s*ago|just now", re.I)
_CH_RE = re.compile(r"(?<![A-Za-z])CH\s*\.?\s*(\d+)(?!\d)", re.I)
_FM_RE = re.compile(r"(?<![A-Za-z])FM\s*(\d+)(?!\d)", re.I)
_PRICE_RE = re.compile(r"(\d[\d.,]*\s*[KMB]?)\s*each\b", re.I)
_TYPICAL_RE = re.compile(r"^\d[\d.,]*\s*[KMB]?$", re.I)
_SEEN_RE = re.compile(r"seen\s+([A-Z][a-z]{2})\s+(\d{1,2}),\s+(\d{1,2}):(\d{2})\s*([AP]M)", re.I)
_MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
_MESOS_TITLE_RE = re.compile(r"^\s*([\d,]+)\s*mesos\s*$", re.I)  # tooltip: "44,999 mesos"

RELOAD_EVERY = 10  # full page reload every N cycles, to recover from a stale page


# ----------------------------------------------------------------- pure parsing
def age_minutes(m: re.Match) -> float:
    if m.group(1) is None:  # "just now"
        return 0.0
    n, unit = int(m.group(1)), m.group(2).lower()[0]
    return {"s": n / 60.0, "m": float(n), "h": n * 60.0, "d": n * 1440.0}[unit]


def _refine_age(ago: re.Match, coarse: float, titles, now: datetime) -> float:
    """The site says "3h ago" for anything from 3h00 to 3h59. Its row tooltip has the exact time
    ("seen Nov 3, 6:39 AM"), so use that when it agrees with the rounded text (guards against a
    different time zone on the site)."""
    unit = (ago.group(2) or "").lower()[:1]
    if unit not in ("h", "d"):
        return coarse
    for ti in titles:
        m = _SEEN_RE.search(ti or "")
        if not m:
            continue
        hour = int(m.group(3)) % 12 + (12 if m.group(5).upper() == "PM" else 0)
        try:
            dt = datetime(now.year, _MONTHS[m.group(1).lower()], int(m.group(2)), hour, int(m.group(4)))
        except (KeyError, ValueError):
            return coarse
        if dt > now + timedelta(days=1):  # "Dec 31" seen from early January
            dt = dt.replace(year=dt.year - 1)
        exact = (now - dt).total_seconds() / 60.0
        step = 60.0 if unit == "h" else 1440.0
        if coarse - 2 <= exact < coarse + step + 2:
            return round(exact, 1)
        return coarse
    return coarse


def parse_listing_text(text: str, titles=(), now: Optional[datetime] = None) -> Optional[dict]:
    """One row of the Newest list (its visible text) -> fields, or None if it isn't a listing."""
    t = text.replace("\u00a0", " ").replace("·", " ").replace("•", " ")  # the site puts &nbsp; before the time
    pm = _PRICE_RE.search(t)
    if not pm:
        return None
    price = parse_number(pm.group(1).replace(" ", ""))
    if price is None:
        return None
    for ti in titles:  # the site shows "45K" but the tooltip has the exact price
        tm = _MESOS_TITLE_RE.match(ti or "")
        if tm:
            exact = int(tm.group(1).replace(",", ""))
            if exact and abs(exact - price) <= max(price * 0.06, 1):
                price = exact
            break
    ch, fm, ago = _CH_RE.search(t), _FM_RE.search(t), _AGO_RE.search(t)
    rest = t
    for a, b in sorted((m.span() for m in (pm, ch, fm, ago) if m), reverse=True):
        rest = rest[:a] + "\n" + rest[b:]
    left = [ln.strip(" \t-") for ln in rest.splitlines()]
    left = [ln for ln in left if re.search(r"\w", ln)]  # drops empty lines and status dots
    seller = left[0] if left else ""
    loc_text = left[1] if len(left) > 1 else ""
    if loc_text.endswith(("…", "...")):  # truncated badge: the full text is often in a title
        prefix = loc_text.rstrip("….").strip()
        for ti in titles:
            if ti and ti.startswith(prefix) and len(ti) > len(prefix):
                loc_text = ti
                break
    # a row shows either CH + FM badges or a single map-name badge
    location = f"FM {fm.group(1)}" if fm else loc_text
    return {
        "seller": seller,
        "channel": ch.group(1) if ch else "",
        "location": location,
        "price": int(price),
        "listed": re.sub(r"\s+", " ", ago.group(0)).strip() if ago else "",
        "age_min": _refine_age(ago, age_minutes(ago), titles, now or datetime.now()) if ago else None,
    }


def parse_typical(row_text: str, name: str) -> Optional[float]:
    """The TYPICAL price in an item's row of the left-hand list (first price-like line)."""
    lines = [ln.strip() for ln in row_text.splitlines() if ln.strip()]
    start = 0
    for i, ln in enumerate(lines):
        if norm(ln) == norm(name):
            start = i + 1
            break
    for ln in lines[start:]:
        if _TYPICAL_RE.match(ln):
            return parse_number(ln.replace(" ", ""))
    return None


# ------------------------------------------------------------------ page scripts
_READ_ROWS_JS = r"""
(sel) => {
  const pack = r => ({text: r.innerText,
    titles: [r.getAttribute('title') || ''].concat(
      Array.from(r.querySelectorAll('[title]')).map(e => e.getAttribute('title')))});
  if (sel) {
    const found = Array.from(document.querySelectorAll(sel));
    if (found.length) return found.map(pack);
  }
  // fallback when the site's markup changes: find rows by their "each" price label
  const norm = s => (s || '').replace(/\s+/g, ' ').trim();
  const isEach = e => e.children.length === 0 && /(^|\s)each$/i.test(norm(e.textContent))
                      && norm(e.textContent).length < 30;
  const stop = /(your shop here|list my shop|newest|cheapest|item info|for sale now|where to buy)/i;
  const leaves = Array.from(document.querySelectorAll('body *')).filter(isEach);
  const rows = [];
  for (const leaf of leaves) {
    let best = null, el = leaf;
    for (let i = 0; i < 7 && el.parentElement; i++) {
      const p = el.parentElement;
      if (Array.from(p.querySelectorAll('*')).filter(isEach).length !== 1) break;
      if (stop.test(p.innerText || '')) break;
      best = p; el = p;
    }
    if (best && /ago|just now/i.test(best.innerText || '') && !rows.includes(best)) rows.push(best);
  }
  return rows.map(pack);
}
"""

# the item's row in the table: exact TYPICAL price is in the tooltip of its price cell
_SCROLL_LIST_JS = r"""
(sel) => {
  const rows = Array.from(document.querySelectorAll(sel));
  if (!rows.length) return false;
  const last = rows[rows.length - 1];
  last.scrollIntoView({block: 'end'});
  const box = last.closest('.scroll') || last.parentElement;
  if (box) box.scrollTop = box.scrollHeight;
  return true;
}
"""

_READ_PRICE_CELL_JS = r"""
(needle) => {
  const norm = s => (s || '').replace(/\s+/g, ' ').trim().toLowerCase();
  const names = Array.from(document.querySelectorAll('button.item-select, .item-name'))
      .filter(b => norm(b.textContent) === needle || norm(b.getAttribute('title')) === needle);
  for (const b of names) {
    const tr = b.closest('tr');
    const m = tr && tr.querySelector('td[data-col="price"] .meso');
    if (m) return {title: m.getAttribute('title') || '', text: (m.textContent || '').trim()};
  }
  return null;
}
"""

_READ_TYPICAL_JS = r"""
(needle) => {
  const norm = s => (s || '').replace(/\s+/g, ' ').trim().toLowerCase();
  const leaves = Array.from(document.querySelectorAll('body *'))
      .filter(e => e.children.length === 0 && norm(e.textContent) === needle);
  for (const leaf of leaves) {
    let el = leaf;
    for (let i = 0; i < 8 && el.parentElement; i++) {
      el = el.parentElement;
      const t = el.innerText || '';
      if (t.length < 500 && /sales/i.test(t) && /%/.test(t)) return t;
    }
  }
  return null;
}
"""


def _short(e: Exception) -> str:
    return str(e).strip().splitlines()[0][:160] if str(e).strip() else e.__class__.__name__


class BrowserSource:
    """Poller-compatible source: fetch() returns the current Newest listings of every watched item.
    Playwright objects belong to the thread that first calls fetch()/diagnose(), so use one
    BrowserSource per thread."""

    min_interval_ms = 500
    last_candidates: list = []

    def pause_s(self) -> float:
        """Random pause between passes (500-5000 ms by default)."""
        return random_pause_s(self.cfg)

    def __init__(self, cfg, profile_dir: Optional[Path] = None):
        self.cfg = cfg
        self.on_status: Optional[Callable[[str], None]] = None
        self.note = ""
        self._profile = profile_dir
        self._pw = self._ctx = self._page = None
        self._cycles = 0

    # ---- helpers
    @property
    def bc(self) -> dict:
        return self.cfg["browser"]

    def _say(self, msg: str):
        if self.on_status:
            self.on_status(msg)

    def _delay(self, mult: float = 1.0):
        """Wait a random 500-5000 ms (shorter for plain page-render waits, mult < 1)."""
        lo = max(int(self.cfg["delay_min_ms"]), 500)
        hi = max(int(self.cfg["delay_max_ms"]), lo)
        time.sleep(random.uniform(lo, lo + (hi - lo) * min(mult, 1.0)) / 1000.0)

    # ---- browser lifecycle
    def _open(self):
        if self._page is not None:
            return
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise RuntimeError("Playwright is not installed (pip install playwright). "
                               "The packaged .exe already includes it.")
        self._pw = sync_playwright().start()
        channel = (self.bc.get("channel") or "").strip().lower()
        # Playwright adds --no-sandbox by default, which makes Chromium show an "unsupported
        # command-line flag" bar. Keep the sandbox on; only a Linux root user (containers) needs it off.
        no_sandbox = sys.platform.startswith("linux") and hasattr(os, "geteuid") and os.geteuid() == 0
        kw = dict(user_data_dir=str(self._profile or (data_dir() / "browser-profile")),
                  headless=bool(self.bc["headless"]), viewport={"width": 1500, "height": 900},
                  chromium_sandbox=not no_sandbox)
        if channel not in ("", "chromium"):
            kw["channel"] = channel
        try:
            self._ctx = self._pw.chromium.launch_persistent_context(**kw)
        except Exception as e:
            self.close()
            raise RuntimeError(f"Could not start the browser '{channel or 'chromium'}': {_short(e)}. "
                               "Pick another browser in Settings (msedge, chrome or chromium).")
        self._page = self._ctx.pages[0] if self._ctx.pages else self._ctx.new_page()
        self._page.set_default_timeout(int(self.bc["page_timeout_ms"]))

    def close(self):
        for obj, meth in ((self._ctx, "close"), (self._pw, "stop")):
            try:
                if obj is not None:
                    getattr(obj, meth)()
            except Exception:
                pass
        self._pw = self._ctx = self._page = None

    # ---- navigation / challenge handling
    def _is_challenge(self, page, resp=None) -> bool:
        try:
            if resp is not None and resp.headers.get("cf-mitigated", "").lower() == "challenge":
                return True
            title = (page.title() or "").strip().lower()
        except Exception:
            return False
        return title.startswith("just a moment") or title.startswith("attention required")

    def _clear_challenge(self, page, resp=None):
        """If a Cloudflare check is showing: stop (headless) or wait for YOU to complete it (window)."""
        if not self._is_challenge(page, resp):
            return
        if self.bc["headless"]:
            raise ChallengeDetected(
                "A Cloudflare check appeared. Turn on 'Show browser window' in Settings, press Start, "
                "and complete the check yourself; MesoWatcher continues once the page loads.")
        limit = int(self.bc["challenge_wait_s"])
        for waited in range(limit):
            self._say(f"Waiting for you to complete the check in the browser window ({limit - waited}s left)...")
            time.sleep(1)
            if not self._is_challenge(page):
                return
        raise ChallengeDetected(f"The Cloudflare check was not completed within {limit} s.")

    def _goto_start(self, page):
        resp = page.goto(self.bc["start_url"], wait_until="domcontentloaded")
        self._clear_challenge(page, resp)
        if resp is not None and resp.status in (429, 503):
            ra = resp.headers.get("retry-after", "")
            raise RateLimited(float(ra) if ra.isdigit() else 60.0)
        if resp is not None and resp.status in (401, 403):
            raise ChallengeDetected(f"HTTP {resp.status}: the site refused access.")
        try:
            page.wait_for_load_state("networkidle", timeout=10000)
        except Exception:
            pass
        return resp

    def _filter_box(self, page):
        """The item filter input. The placeholder may end in "..." or the single "\u2026" character, so
        match on the words only; fall back to any search box."""
        base = (self.bc["filter_placeholder"] or "").strip().rstrip(".\u2026 ").strip()
        loc = page.get_by_role("searchbox")
        if base:
            loc = page.get_by_placeholder(re.compile(re.escape(base), re.I)).or_(loc)
        return loc.first

    def _ensure_loaded(self, page):
        reload_due = self._cycles % RELOAD_EVERY == 1
        if reload_due or self._filter_box(page).count() == 0:
            self._goto_start(page)
        try:
            self._filter_box(page).wait_for(state="visible")
        except Exception:
            raise RuntimeError(f"Could not find the item filter box ('{self.bc['filter_placeholder']}') "
                               "on the page. Check the start URL and the filter text in Settings.")

    # ---- per-item steps
    @staticmethod
    def _key(s: str) -> str:
        """Comparison key for item names: case, spacing, quotes and punctuation are ignored,
        but every word and number must match (so "Chaos" never equals "Intermediate")."""
        return norm(s.replace(" ", " "))

    def _select_item(self, page, name: str) -> Optional[str]:
        """Type the full name in the filter box and click the row whose name is EXACTLY that item.
        Never clicks a "close enough" first result. Clicks only inside the item table (the page also
        shows item names in a ticker and a header). Returns the text used, or None."""
        box = self._filter_box(page)
        sel = (self.bc.get("item_selector") or "").strip()
        want = self._key(name)
        self.last_candidates = []
        box.fill(name.strip())
        self._delay(0.6)
        self._clear_challenge(page)
        scoped = page.locator(sel) if sel else None
        if scoped is not None and scoped.count() > 0:
            pool = scoped
        else:  # selector missing from the page (layout changed): fall back to visible text
            pool = page.get_by_text(re.compile(re.escape(name.strip()), re.I))
        texts = [t.strip() for t in pool.all_inner_texts()]
        self.last_candidates = [t for t in texts if t][:5]
        for i, t in enumerate(texts):
            if self._key(t) == want:
                pool.nth(i).click()
                self._delay()
                return name.strip()
        return None

    def _typical(self, page, used: str) -> Optional[float]:
        needle = re.sub(r"\s+", " ", used.strip()).lower()
        try:
            cell = page.evaluate(_READ_PRICE_CELL_JS, needle)
            if cell:
                m = _MESOS_TITLE_RE.match(cell.get("title") or "")
                if m:
                    return float(m.group(1).replace(",", ""))
                v = parse_number((cell.get("text") or "").replace(" ", ""))
                if v:
                    return v
        except Exception:
            pass
        try:
            text = page.evaluate(_READ_TYPICAL_JS, re.sub(r"\s+", " ", used.strip()).lower())
        except Exception:
            return None
        return parse_typical(text, used) if text else None

    def _open_newest(self, page) -> bool:
        label = self.bc["newest_label"]
        for step in range(len(self.bc["open_labels"]) + 1):
            btn = page.get_by_text(label, exact=True)
            if btn.count() > 0 and btn.first.is_visible():
                btn.first.click()
                self._delay(0.6)
                return True
            if step < len(self.bc["open_labels"]):
                opener = page.get_by_text(self.bc["open_labels"][step], exact=False)
                if opener.count() > 0 and opener.first.is_visible():
                    opener.first.click()
                    self._delay(0.6)
        return False

    def _scroll_list(self, page, sel: str) -> bool:
        """Scroll the Newest list to its bottom with JavaScript (no real mouse wheel is involved)."""
        try:
            return bool(page.evaluate(_SCROLL_LIST_JS, sel or "li.buy-row"))
        except Exception:
            return False

    def _read_rows(self, page) -> list[dict]:
        """Read the Newest list, scrolling down until listings are older than the look-back window
        (default 3 hours), the list stops growing, or the safety cap is reached."""
        sel = (self.bc.get("row_selector") or "").strip()
        lookback = float(self.bc.get("lookback_min", 180))
        cap = int(self.bc.get("listing_cap", 200))
        out: list[dict] = []
        seen: set = set()
        for step in range(int(self.bc.get("max_scrolls", 40)) + 1):
            new, reached_old = 0, False
            for r in page.evaluate(_READ_ROWS_JS, sel):
                p = parse_listing_text(r["text"], r.get("titles") or ())
                if not p:
                    continue
                if p["age_min"] is None or p["age_min"] > lookback:
                    reached_old = True  # the list is newest-first, so everything below is older
                    continue
                k = (p["seller"], p["channel"], p["location"], p["price"])
                if k not in seen:
                    seen.add(k)
                    out.append(p)
                    new += 1
            if reached_old or len(out) >= cap or (step > 0 and new == 0):
                break
            if not self._scroll_list(page, sel):
                break
            self._delay(0.1)  # just long enough for lazy-loaded rows to appear
        return out[:cap]

    def _monitor(self, page, name: str) -> tuple[list[Listing], str]:
        used = self._select_item(page, name)
        if not used:
            near = ", ".join(self.last_candidates[:3])
            return [], "no item with exactly this name on the site" + (f" (saw: {near})" if near else "")
        typical = self._typical(page, used)
        if not self._open_newest(page):
            return [], "could not open the Newest list"
        out = []
        for p in self._read_rows(page):
            key = f"{name}|{p['seller']}|{p['channel']}|{p['location']}|{p['price']}"
            out.append(Listing(key=key, item_id="", item_name=name, channel=p["channel"],
                               location=p["location"], price=p["price"], avg24h=typical,
                               seller=p["seller"], listed=p["listed"], age_min=p["age_min"],
                               observed=time.time()))
        return out, ("" if out else "no listings shown")

    # ---- poller interface
    def fetch(self) -> list[Listing]:
        names = [e["name"] for e in self.cfg["watchlist"] if e.get("name")]
        self.note = ""
        if not names:
            self.note = "watchlist is empty - add items to monitor"
            return []
        self._open()
        page = self._page
        self._cycles += 1
        self._ensure_loaded(page)
        out: list[Listing] = []
        notes: list[str] = []
        errors: list[str] = []
        for i, name in enumerate(names):
            try:
                ls, note = self._monitor(page, name)
                out += ls
                if note:
                    notes.append(f"{name}: {note}")
            except (ChallengeDetected, RateLimited):
                raise
            except Exception as e:
                errors.append(f"{name}: {_short(e)}")
            if i < len(names) - 1:
                self._delay()
        if errors and len(errors) == len(names):
            raise RuntimeError("; ".join(errors[:2]))
        self.note = "; ".join((notes + errors)[:3])
        return out

    # ---- settings "Test"
    def diagnose(self, name: str, snapshot: Optional[Path] = None) -> list[str]:
        """Walk through one item step by step and say what worked. Saves the rendered page to
        `snapshot` so selectors/labels can be adjusted (and shared) without guessing."""
        log: list[str] = []
        try:
            self._open()
            page = self._page
            resp = self._goto_start(page)
            log.append(f"OK  Opened {self.bc['start_url']} (HTTP {resp.status if resp else '?'}, "
                       f"title '{page.title()}')")
            if self._filter_box(page).count() == 0:
                log.append(f"FAIL Filter box '{self.bc['filter_placeholder']}' not found on the page.")
                return log
            log.append("OK  Filter box found")
            used = self._select_item(page, name)
            if not used:
                near = ", ".join(self.last_candidates[:3])
                log.append(f"FAIL No item named exactly '{name}' in the item list"
                           + (f" (the site showed: {near})." if near else "."))
                return log
            log.append(f"OK  Clicked item (searched '{used}')")
            typ = self._typical(page, used)
            log.append(f"{'OK ' if typ else 'WARN'} Typical price: {typ:,.0f}" if typ
                       else "WARN Typical price not found (Discount column will be blank)")
            if not self._open_newest(page):
                log.append(f"FAIL Could not find the '{self.bc['newest_label']}' button/list.")
                return log
            log.append(f"OK  '{self.bc['newest_label']}' list open")
            rows = self._read_rows(page)
            look = int(self.bc.get("lookback_min", 180))
            if rows:
                log.append(f"OK  Read {len(rows)} listing(s) from the last {look} minutes (scrolled the Newest list)")
            else:
                # nothing inside the window: say whether the list is really empty or just older than the window
                saved = self.bc["lookback_min"]
                self.bc["lookback_min"] = 100000
                try:
                    older = self._read_rows(page)
                finally:
                    self.bc["lookback_min"] = saved
                if older:
                    newest = min(p["age_min"] for p in older)
                    log.append(f"OK  Newest list works: no listings in the last {look} minutes, but it has "
                               f"{len(older)} older one(s); the newest is about {fmt_age(newest)}. "
                               "Nothing is wrong - raise 'Show listings from the last' to see them.")
                    rows = older
                else:
                    log.append("FAIL The Newest list is open but no listing rows could be read.")
            for p in rows[:5]:
                log.append(f"      {p['seller'] or '?'} | CH {p['channel'] or '-'} | {p['location'] or '-'} | "
                           f"{p['price']:,} | {p['listed'] or '-'}")
        except ChallengeDetected as e:
            log.append(f"STOP {e}")
        except Exception as e:
            log.append(f"FAIL {_short(e)}")
        finally:
            if snapshot is not None and self._page is not None:
                try:
                    snapshot.write_text(self._page.content(), encoding="utf-8")
                    log.append(f"Saved page snapshot: {snapshot}")
                except Exception:
                    pass
        return log
