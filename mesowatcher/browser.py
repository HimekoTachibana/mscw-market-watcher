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
from urllib.parse import unquote, urlparse

from . import errorlog
from .core import (ChallengeDetected, Listing, RateLimited, data_dir, fmt_age, norm, parse_number,
                   random_pause_s)

_AGO_RE = re.compile(r"(\d+)\s*(seconds?|secs?|minutes?|mins?|hours?|hrs?|days?|[smhd])\b\s*ago|just now", re.I)
_CH_RE = re.compile(r"(?<![A-Za-z])CH\s*\.?\s*(\d+)(?!\d)", re.I)
_FM_RE = re.compile(r"(?<![A-Za-z])FM\s*(\d+)(?!\d)", re.I)
_PRICE_RE = re.compile(r"(\d[\d.,]*\s*[KMB]?)\s*each\b", re.I)
_BARE_PRICE_RE = re.compile(r"(?m)^[ \t]*(\d[\d.,]*[ \t]*[KMB]?)[ \t]*$", re.I)  # "For sale now" rows: the price alone on a line
# hidden status text the site puts in every row for screen readers ("Likely still up", "Seller not confirmed"); never a place
_STATUS_RE = re.compile(r"still\s+up|not\s+confirmed|unconfirmed|may\s+have\s+(?:closed|moved)|(?:likely|probably)\s+(?:closed|gone)", re.I)
_TAG_RE = re.compile(r"%|^(?:fair|deal|high|low)$", re.I)  # price tags: "High +18%", "Deal -5%", "Fair"
_TYPICAL_RE = re.compile(r"^\d[\d.,]*\s*[KMB]?$", re.I)
_SEEN_RE = re.compile(r"seen\s+([A-Z][a-z]{2})\s+(\d{1,2}),\s+(\d{1,2}):(\d{2})\s*([AP]M)", re.I)
_MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
_MESOS_TITLE_RE = re.compile(r"^\s*([\d,]+)\s*mesos\s*$", re.I)  # tooltip: "44,999 mesos"

RELOAD_EVERY = 10  # full page reload every N cycles, to recover from a stale page
MAX_RESULTS_TRIED = 6  # default for "most search results opened, one after the other, to find the item" (Settings)
_ICON_ID_RE = re.compile(r"(?<!\d)(\d{5,9})(?!\d)")


def icon_ids(src: str) -> list[str]:
    """Item ids written in an icon's file name, e.g. '/icons/02040000.png' or 'item_2040000@2x.webp'.
    Only the file name counts (not the folders or the ?query), so cache-busters like '?v=20261104' are ignored."""
    if not src:
        return []
    m = re.search(r"url\(\s*[\"']?([^\"')]+)", src)  # a CSS background-image
    path = unquote(urlparse(m.group(1) if m else src).path)
    name = path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    return _ICON_ID_RE.findall(name)


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
    if not pm:  # the "For sale now" rows show the price alone ("167K", exact value in the tooltip), no "each"
        bare = list(_BARE_PRICE_RE.finditer(t))
        pm = bare[-1] if bare else None  # the price comes after the seller and the badges
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
    left = [ln for ln in left if re.search(r"\w", ln) and not _STATUS_RE.search(ln)
            and not _TAG_RE.search(ln)]  # drops empty lines, dots, status text, price tags
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
# Scroll the Newest list down by about one screen (frac) or to the very bottom (frac >= 99). The scrolling
# box is found by looking for the nearest scrollable ancestor of the last row, so it works whatever the
# site calls it. Returns where it is now, so Python can tell "still travelling" from "reached the bottom".
_SCROLL_STEP_JS = r"""
([sel, frac]) => {
  const rows = Array.from(document.querySelectorAll(sel));
  if (!rows.length) return null;
  const last = rows[rows.length - 1];
  const scrollable = el => { const s = getComputedStyle(el);
    return /(auto|scroll|overlay)/.test(s.overflowY) && el.scrollHeight > el.clientHeight + 2; };
  let box = last.parentElement;
  while (box && box !== document.body && box !== document.documentElement && !scrollable(box)) box = box.parentElement;
  const useWin = !box || box === document.body || box === document.documentElement;
  const el = useWin ? (document.scrollingElement || document.documentElement) : box;
  const h = useWin ? window.innerHeight : el.clientHeight;
  const before = el.scrollTop;
  el.scrollTop = Math.min(frac >= 99 ? el.scrollHeight : before + Math.max(h * frac, 120), el.scrollHeight);
  if (el.scrollTop === before) last.scrollIntoView({block: 'end'});  // not scrollable by us: let the browser do it
  const r = useWin ? {left: 0, top: 0, width: window.innerWidth, height: window.innerHeight} : el.getBoundingClientRect();
  const cls = String(el.className && el.className.baseVal !== undefined ? el.className.baseVal : el.className || '').trim();
  return {moved: el.scrollTop - before, atBottom: el.scrollTop + h >= el.scrollHeight - 2, rows: rows.length,
          tag: useWin ? 'page' : el.tagName.toLowerCase() + (el.id ? '#' + el.id : '') +
               (cls ? '.' + cls.split(/\s+/).slice(0, 3).join('.') : ''),
          x: r.left + r.width / 2, y: r.top + r.height / 2, w: r.width, h: r.height};
}
"""

# Some lists end with a "Load more" / "Show more" button instead of loading by themselves.
_LOAD_MORE_JS = r"""
(sel) => {
  const rows = Array.from(document.querySelectorAll(sel));
  const last = rows[rows.length - 1];
  const re = /^\s*(load|show|see|view)\s+(more|older|next)\b|^\s*more\s*(listings|results|shops)?\s*$/i;
  // look around the list, nearest first: the button usually sits just under it
  let node = last ? last.parentElement : null;
  for (let up = 0; up < 6 && node; up++, node = node.parentElement) {
    for (const b of node.querySelectorAll('button, a, [role="button"]')) {
      if (!(b.offsetWidth || b.offsetHeight) || b.disabled) continue;
      if (re.test((b.innerText || b.textContent || '').trim())) { b.click(); return true; }
    }
  }
  return false;
}
"""

# The right-hand panel: every visible heading outside the item table / ticker, with the icon nearest to it.
_DETAIL_JS = r"""
() => {
  const vis = e => !!(e.offsetWidth || e.offsetHeight || e.getClientRects().length);
  const skip = e => e.closest('table, .megaphone, [class*="ticker"], #ticker, nav, footer');
  const txt = e => (e.innerText || e.textContent || '').replace(/\s+/g, ' ').trim();
  const urlOf = el => {
    const tag = el.tagName.toLowerCase();
    if (tag === 'img') return el.currentSrc || el.getAttribute('src') || '';
    if (tag === 'image' || tag === 'use') return el.getAttribute('href') || el.getAttribute('xlink:href') || '';
    const bg = getComputedStyle(el).backgroundImage;
    const m = bg && bg !== 'none' && /url\(["']?([^"')]+)["']?\)/.exec(bg);
    return m ? m[1] : '';
  };
  const iconNear = h => {
    let node = h;
    for (let up = 0; up < 4 && node; up++, node = node.parentElement) {
      if (node.matches('body, main') || node.querySelector('table, .megaphone, li.buy-row, ul.buy-list')) break;
      for (const el of node.querySelectorAll('img, image, [style*="background"], [class*="icon"], [class*="thumb"], [class*="sprite"]')) {
        const u = urlOf(el);
        if (u && (vis(el) || el.tagName.toLowerCase() === 'image')) return {src: u, alt: el.getAttribute('alt') || el.getAttribute('title') || ''};
      }
    }
    return null;
  };
  const sel = 'h1, h2, h3, h4, [role="heading"], [class*="detail"] [class*="title"], [class*="detail"] [class*="name"], [id*="detail"] [class*="name"]';
  return Array.from(document.querySelectorAll(sel))
      .filter(h => vis(h) && !skip(h) && txt(h).length > 0 && txt(h).length < 160)
      .slice(0, 10).map(h => ({text: txt(h), icon: iconNear(h)}));
}
"""

# The icon of a search result (the item table row around the clicked name), so the right-hand panel's icon can be
# compared with it: the very same picture must show up on the right.
_RESULT_ICON_JS = r"""
(el) => {
  const row = el.closest('tr, li, .item-cell, [class*="row"]') || el.parentElement;
  const img = row && row.querySelector('img, image, [style*="background"]');
  if (!img) return '';
  if (img.tagName.toLowerCase() === 'img') return img.currentSrc || img.getAttribute('src') || '';
  const bg = getComputedStyle(img).backgroundImage;
  const m = bg && /url\(["']?([^"')]+)["']?\)/.exec(bg);
  return m ? m[1] : (img.getAttribute('href') || '');
}
"""

# How many shops the "For sale now" view says it has, and how many it shows ("102 of 102 shops shown").
_EXPECT_JS = r"""
() => {
  const num = t => parseInt(String(t || '').replace(/\D/g, ''), 10) || null;
  const foot = document.querySelector('.fsn-foot');
  const m = foot && /(\d[\d,]*)\s+of\s+(\d[\d,]*)\s+(?:shops|listings)/i.exec(foot.innerText || '');
  if (m) return {shown: num(m[1]), total: num(m[2])};
  const c = document.querySelector('.fsn-count');
  return {shown: null, total: c ? num(c.textContent) : null};
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
    last_panels: list = []
    items = None  # optional ItemDB: lets the right-hand icon be checked against the item's id

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
        self.scroll_info: dict = {}
        self.match_info = ""
        self.forsale_info = ""
        self.should_stop: Optional[Callable[[], bool]] = None  # the poller says when Stop was pressed
        self._force_visible = False  # set once the window was opened because something went wrong
        self.mode = ""  # "window", "background (off-screen window)" or "background (headless)"
        self._logged: set = set()

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

    def _act(self, msg: str):
        errorlog.action(msg)

    @staticmethod
    def _can_show() -> bool:
        """Is there a screen to open a (visible or off-screen) window on?"""
        if sys.platform.startswith("linux"):
            return bool(os.environ.get("DISPLAY")) and not os.environ.get("WAYLAND_DISPLAY")
        return True

    @property
    def background(self) -> bool:
        """Running without a visible window (Settings: 'Show browser window' off) and nothing has gone wrong yet."""
        return bool(self.bc["headless"]) and not self._force_visible

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
        # Background work: a normal browser window is opened far off-screen (it behaves exactly like the window you
        # can see; a headless browser is treated differently by many sites). Only without a screen is it truly
        # headless. If something goes wrong the window is opened on screen so you can look at it.
        args, headless = [], False
        if self.background:
            if self._can_show():
                args = ["--window-position=-32000,-32000", "--window-size=1500,900",
                        "--disable-backgrounding-occluded-windows", "--disable-renderer-backgrounding",
                        "--disable-background-timer-throttling",
                        "--disable-features=CalculateNativeWinOcclusion"]
                self.mode = "background (off-screen window)"
            else:
                headless = True
                self.mode = "background (headless, no screen available)"
        else:
            self.mode = "window"
        self._act(f"Opening the browser: {self.mode}, channel '{channel or 'chromium'}'")
        kw = dict(user_data_dir=str(self._profile or (data_dir() / "browser-profile")),
                  headless=headless, viewport={"width": 1500, "height": 900},
                  chromium_sandbox=not no_sandbox)
        if args:
            kw["args"] = args
        if channel not in ("", "chromium"):
            kw["channel"] = channel
        try:
            try:
                self._ctx = self._pw.chromium.launch_persistent_context(**kw)
            except Exception as first:
                if "Executable doesn't exist" not in str(first):
                    raise
                # e.g. "chromium" in the packaged program (no browser is bundled): use one installed on this computer
                self._act(f"Browser '{channel or 'chromium'}' is not installed; trying the installed ones")
                self._ctx = None
                for alt in ("msedge", "chrome"):
                    if alt == channel:
                        continue
                    try:
                        self._ctx = self._pw.chromium.launch_persistent_context(**{**kw, "channel": alt})
                        self._act(f"Using '{alt}' instead of '{channel or 'chromium'}'")
                        self._say(f"'{channel or 'chromium'}' is not installed; using {alt} instead.")
                        break
                    except Exception:
                        continue
                if self._ctx is None:
                    raise first
        except Exception as e:
            self.close()
            errorlog.write("The browser could not be started", e, {"browser": channel or "chromium", "mode": self.mode})
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

    def _clear_challenge(self, page, resp=None) -> bool:
        """If a Cloudflare check is showing: open the browser window (when it was running in the background) and
        wait for YOU to complete it. The program never tries to get past a check by itself."""
        if not self._is_challenge(page, resp):
            return False
        self._act("A Cloudflare check is showing")
        if self.background:
            page = self._escalate("A Cloudflare check appeared; complete it in the browser window") or page
            if self.background:  # no screen to show it on
                raise ChallengeDetected(
                    "A Cloudflare check appeared and there is no screen to show it on. Run MesoWatcher where a "
                    "window can open, press Start and complete the check yourself.")
        limit = int(self.bc["challenge_wait_s"])
        for waited in range(limit):
            self._say(f"Waiting for you to complete the check in the browser window ({limit - waited}s left)...")
            time.sleep(1)
            try:
                closed = page.is_closed()
                if not closed:
                    page.title()  # raises when the window is gone
            except Exception:
                closed = True
            if closed:  # a closed window is not a completed check
                self._act("The browser window was closed before the Cloudflare check was completed")
                raise ChallengeDetected("The browser window was closed before the Cloudflare check was completed. "
                                        "If the check keeps asking again after you click it, the site is not "
                                        "accepting this automated browser; MesoWatcher does not try to get around that.")
            if not self._is_challenge(page):
                self._act("The Cloudflare check was completed")
                return True
        raise ChallengeDetected(f"The Cloudflare check was not completed within {limit} s.")

    def _escalate(self, reason: str, exc: Optional[BaseException] = None, goto: bool = True):
        """Something needs a person: write the error log, then reopen the browser WINDOW on the site. Returns the
        new page (None when there is no screen to open it on)."""
        key = (reason, type(exc).__name__ if exc else "")
        path = None
        if key not in self._logged:
            self._logged.add(key)
            path = errorlog.write(reason, exc, self._context())
        self._say(f"{reason}" + (f" - details saved to {path}" if path else ""))
        if not self.background:
            return self._page
        if not self._can_show():
            return None
        self._act(f"Opening the browser window for you ({reason})")
        self.close()
        self._force_visible = True
        try:
            self._open()
            if goto:
                try:
                    self._page.goto(self.bc["start_url"], wait_until="domcontentloaded")
                except Exception as e:
                    self._act(f"Could not load the page in the window: {_short(e)}")
        except Exception as e:
            self._act(f"Could not open the window: {_short(e)}")
            return None
        return self._page

    def _context(self) -> dict:
        info = {"browser mode": self.mode or "?", "start url": self.bc.get("start_url")}
        try:
            if self._page is not None:
                info["page url"] = self._page.url
                info["page title"] = self._page.title()
                info["user agent"] = self._page.evaluate("navigator.userAgent")
                info["navigator.webdriver"] = self._page.evaluate("String(navigator.webdriver)")
        except Exception:
            pass
        return info

    def hold_open(self, seconds: int = 300):
        """Keep a window that was opened for troubleshooting around until it is closed (or time runs out)."""
        if self._page is None or self.background:
            return
        self._say("The browser window stays open for troubleshooting; close it when you are done.")
        end = time.time() + seconds
        while time.time() < end:
            try:
                if self._page.is_closed() or not self._ctx.pages:
                    return
            except Exception:
                return
            time.sleep(1)

    def _goto_start(self, page):
        self._act(f"Loading {self.bc['start_url']}")
        try:
            resp = page.goto(self.bc["start_url"], wait_until="domcontentloaded")
        except Exception as e:
            if "Timeout" not in type(e).__name__:
                raise
            # a cold browser start can be slow: one more try before calling it an error
            self._act("The page was slow to load; trying once more")
            resp = page.goto(self.bc["start_url"], wait_until="domcontentloaded")
        if self._clear_challenge(page, resp):
            # The check page itself is served with HTTP 403/503. Once the check is completed that first answer is
            # out of date: judge the page that is showing now, not the answer to the first request.
            self._act("Check completed; continuing with the page that loaded afterwards")
            resp = None
            page = self._page or page
        if resp is not None and resp.status in (429, 503):
            ra = resp.headers.get("retry-after", "")
            raise RateLimited(float(ra) if ra.isdigit() else 60.0)
        if resp is not None and resp.status in (401, 403):
            self._act(f"The site answered HTTP {resp.status}")
            e = ChallengeDetected(
                f"HTTP {resp.status}: the site refused the request without showing a check. MesoWatcher does not "
                "try to get around that. Details are in the error log.")
            self._escalate(f"The site refused access (HTTP {resp.status})", e)
            raise e
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

    def _icon_verdict(self, icon: Optional[dict], want: str) -> Optional[bool]:
        """Does the icon in the right-hand panel belong to the wanted item? True / False, or None when it
        cannot be told (no icon, no item id in its file name, or an id this program does not know)."""
        if not icon or self.items is None:
            return None
        for iid in icon_ids(icon.get("src", "")):
            it = self.items.items.get(iid.zfill(8))
            if it:
                return self._key(it["name"]) == want
        return None

    @staticmethod
    def _shown(heads: list) -> str:
        return " | ".join(h["text"] for h in heads[:3])

    def _panel_heads(self, page) -> list:
        try:
            return page.evaluate(_DETAIL_JS) or []
        except Exception:
            return []

    def _panel_matches(self, page, want: str, row_ids: Optional[list] = None) -> tuple[bool, str]:
        """Is the item shown in the right-hand panel the wanted one? Needs the heading to read exactly like the
        wanted name and, as a double check, the icon to be right: the same picture as the search result that was
        clicked, and (when the item database knows the id) that item's own icon."""
        heads = self._panel_heads(page)
        shown = self._shown(heads)
        for h in heads:
            if self._key(h["text"]) != want:
                continue
            icon = h.get("icon")
            panel_ids = icon_ids(icon.get("src", "")) if icon else []
            if row_ids and panel_ids:
                if not set(row_ids) & set(panel_ids):
                    self.match_info = "name matched but the icon differs from the clicked result's icon"
                    return False, f"{h['text']} (wrong icon)"
                verdict, how = True, "name and icon match the clicked result"
            else:
                verdict, how = None, "name matches (icon cannot be compared)"
            db = self._icon_verdict(icon, want)
            if db is False:
                self.match_info = "name matched but the icon belongs to another item"
                return False, f"{h['text']} (wrong icon)"
            if db is True:
                how = "name and icon match"
            self.match_info = how
            return True, shown
        return False, shown

    def _select_item(self, page, name: str) -> Optional[str]:
        """Type the full name in the filter box, then open search results one after the other until the
        RIGHT-HAND PANEL shows the wanted item: its heading reads exactly like the name and its icon is that
        item's icon. A result that opens something else is skipped. Clicks only inside the item table (the page
        also shows item names in a ticker and a header). Returns the text used, or None."""
        box = self._filter_box(page)
        sel = (self.bc.get("item_selector") or "").strip()
        want = self._key(name)
        self.last_candidates, self.last_panels, self.match_info = [], [], ""
        self._act(f"Typing '{name.strip()}' in the filter box")
        box.fill(name.strip())
        self._delay(0.6)
        self._clear_challenge(page)
        self._wait_results(page, want)
        tries = max(int(self.bc.get("max_results_tried") or MAX_RESULTS_TRIED), 1)
        scoped = page.locator(sel) if sel else None
        if scoped is not None and scoped.count() > 0:
            pool = scoped
        else:  # selector missing from the page (layout changed): fall back to visible text
            pool = page.get_by_text(re.compile(re.escape(name.strip()), re.I))
        try:  # the full name is in the button's title (the button text can be shortened)
            texts = [(t or "").strip() for t in pool.evaluate_all(
                "els => els.map(e => e.getAttribute('title') || e.innerText || '')")]
        except Exception:
            texts = [t.strip() for t in pool.all_inner_texts()]
        self.last_candidates = [t for t in texts if t][:5]
        # the results are clicked one by one, top to bottom, until the right-hand panel shows the wanted item
        for i in range(min(len(texts), tries)):
            before = self._shown(self._panel_heads(page))
            try:
                row_ids = icon_ids(pool.nth(i).evaluate(_RESULT_ICON_JS))
            except Exception:
                row_ids = []
            self._act(f"Clicking search result {i + 1}: '{texts[i]}'")
            pool.nth(i).click()
            self._delay(0.3)  # the usual random pause after a click
            t0 = time.time()
            while True:  # the panel may take a moment to show the clicked item
                ok, shown = self._panel_matches(page, want, row_ids)
                if ok or shown != before or time.time() - t0 > 2.0:
                    break  # matched, or the panel now shows something else, or we waited long enough
                time.sleep(0.25)
            if ok:
                return name.strip()
            self.last_panels.append(shown or "(nothing)")
            self._clear_challenge(page)
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

    def _wait_results(self, page, want: str, timeout: float = 8.0):
        """After typing, the site re-draws the result table (for a moment it can be empty or still show the
        previous search). Wait until a result whose full name is the wanted one is there; give up quietly after
        `timeout` seconds (the clicks that follow then report what was really found)."""
        sel = (self.bc.get("item_selector") or "").strip() or "button.item-select"
        end = time.time() + timeout
        n = 0
        while time.time() < end:
            try:
                titles = page.eval_on_selector_all(sel, "els => els.map(e => e.getAttribute('title') || e.innerText || '')")
            except Exception:
                titles = []
            n = len(titles)
            if any(self._key(t) == want for t in titles):
                return
            time.sleep(0.3)
        self._act(f"No search result named exactly '{want}' appeared within {timeout:.0f} s ({n} result(s) shown)")

    def _open_forsale(self, page) -> str:
        """Click the "For sale now" tab at the top of the right-hand panel, which lists every shop selling the
        item. Returns what it opened (e.g. 'For sale now, 102 shops'), or '' when the page has no such tab (older
        layout: the Where to buy / Newest buttons are used instead)."""
        label = (self.bc.get("forsale_label") or "For sale now").strip()
        tab = page.locator('[data-mu="fsn-tab"][data-tab="now"]')
        if tab.count() == 0:
            tab = page.locator('button, [role="tab"]').filter(has_text=re.compile(r"^\s*" + re.escape(label) + r"\b", re.I))
        if tab.count() == 0 or not tab.first.is_visible():
            return ""
        t = tab.first
        on = (t.get_attribute("aria-selected") == "true") or ("on" in (t.get_attribute("class") or "").split())
        if not on:
            self._act(f"Clicking the '{label}' tab")
            t.click()
            self._delay(0.6)
        # The Item Info tab has rows of its own, so "some row exists" proves nothing: wait until the For sale now
        # list is on the page (its own rows, or its footer when the item has no shops) and has drawn its rows.
        deadline = time.time() + 10
        while time.time() < deadline:
            try:
                st = page.evaluate("() => ({rows: document.querySelectorAll('li.fsn-row').length, "
                                   "foot: !!document.querySelector('.fsn-foot')})")
            except Exception:
                st = {"rows": 0, "foot": False}
            exp = self._expected(page)
            want_rows = exp.get("shown") or exp.get("total") or 0
            if st["rows"] and (not want_rows or st["rows"] >= want_rows or time.time() > deadline - 7):
                break
            if st["foot"] and want_rows == 0 and not st["rows"] and time.time() > deadline - 8:
                break
            time.sleep(0.4)
        self._act(f"'{label}' list: {st['rows']} rows on the page")
        n = (self._expected(page).get("total") or 0)
        return f"{label}, {n} shops" if n else label

    def _expected(self, page) -> dict:
        try:
            return page.evaluate(_EXPECT_JS) or {}
        except Exception:
            return {}

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

    def _row_signature(self, page, sel: str) -> tuple:
        """(row count, text of the last row): changes when the site appends or swaps rows."""
        try:
            rows = page.evaluate(_READ_ROWS_JS, sel)
        except Exception:
            return (0, "")
        return (len(rows), rows[-1]["text"] if rows else "")

    def _wait_rows_change(self, page, sel: str, before: tuple, timeout: float) -> bool:
        """Wait (polling) for the site to load more rows after a scroll; True as soon as it did."""
        end = time.time() + timeout
        while time.time() < end:
            time.sleep(0.25)
            if self._row_signature(page, sel) != before:
                return True
        return False

    def _nudge(self, page, sel: str, pos: dict) -> bool:
        """The list is at its bottom and nothing new came. Try what a person would: roll the mouse wheel over
        the list, and press a 'Load more' button if there is one. True if either was done."""
        did = False
        try:
            if pos.get("w"):
                page.mouse.move(pos["x"], pos["y"])  # the page's own pointer; your real mouse is not touched
                page.mouse.wheel(0, 600)
                did = True
        except Exception:
            pass
        try:
            did = bool(page.evaluate(_LOAD_MORE_JS, sel)) or did
        except Exception:
            pass
        return did

    def _read_rows(self, page) -> list[dict]:
        """Read the Newest list, scrolling down a screen at a time until listings are older than the look-back
        window (default 3 hours), the list really ends, or the safety cap is reached. At the bottom it waits for
        the site to load more (it can take seconds), then rolls the wheel / presses 'Load more', and only after
        two such tries calls it the end. What happened is kept in self.scroll_info for the Test report."""
        sel = (self.bc.get("row_selector") or "").strip()
        lookback = float(self.bc.get("lookback_min", 180))
        cap = int(self.bc.get("listing_cap", 200))
        max_steps = max(int(self.bc.get("max_scrolls", 40)), 40) * 4
        out: list[dict] = []
        seen: set = set()
        info = {"steps": 0, "loads": 0, "rows": 0, "container": "", "stop": "", "expected": 0}
        self.scroll_info = info
        stalls = 0
        for step in range(max_steps + 1):
            reached_old, total, parsed = False, 0, 0
            for r in page.evaluate(_READ_ROWS_JS, sel):
                total += 1
                p = parse_listing_text(r["text"], r.get("titles") or ())
                if not p:
                    continue
                parsed += 1
                # "Nh ago" / "Nd ago" are rounded down (1h can be 1h59m), so a row showing exactly the limit is
                # already at or over it
                coarse = bool(re.match(r"\d+\s*[hd]", p.get("listed") or "", re.I))
                if p["age_min"] is None or p["age_min"] > lookback or (coarse and p["age_min"] >= lookback):
                    reached_old = True  # the list is newest-first, so everything below is older
                    continue
                k = (p["seller"], p["channel"], p["location"], p["price"])
                if k not in seen:
                    seen.add(k)
                    out.append(p)
            info["rows"] = max(info["rows"], total)
            if reached_old:
                info["stop"] = "reached listings older than the look-back window"
                break
            if len(out) >= cap:
                info["stop"] = "reached the safety cap"
                break
            if step == 0:
                exp = self._expected(page)
                info["expected"] = exp.get("total") or exp.get("shown") or 0
            if info["expected"] and parsed >= info["expected"]:
                info["stop"] = f"all {parsed} listings were already on the page (no scrolling needed)"
                break
            if step == max_steps:
                info["stop"] = "reached the scroll limit"
                break
            before = self._row_signature(page, sel)
            try:
                pos = page.evaluate(_SCROLL_STEP_JS, [sel or "li.buy-row", 0.9])
            except Exception:
                pos = None
            if not pos:
                info["stop"] = "no rows to scroll"
                break
            info["steps"] += 1
            info["container"] = pos["tag"]
            if pos["moved"] > 1 and not pos["atBottom"]:
                time.sleep(random.uniform(0.15, 0.35))  # moving through rows that are already loaded
                stalls = 0
                continue
            grew = self._wait_rows_change(page, sel, before, 3.0)  # at the bottom: let the site load more
            if not grew and self._nudge(page, sel, pos):
                grew = self._wait_rows_change(page, sel, before, 2.5)
            if grew:
                info["loads"] += 1
                stalls = 0
                self._delay(0.1)
                continue
            stalls += 1
            if stalls >= 2:
                info["stop"] = "the list stopped growing (end of the Newest list)"
                break
        return out[:cap]

    def _monitor(self, page, name: str) -> tuple[list[Listing], str]:
        used = self._select_item(page, name)
        if not used:
            if not self.last_candidates:
                return [], "no item with exactly this name on the site"
            shown = "; ".join(self.last_panels[:3])
            return [], (f"none of the {len(self.last_panels)} search results opened this item "
                        f"(the right-hand panel showed: {shown})")
        typical = self._typical(page, used)
        forsale = self._open_forsale(page)
        self.forsale_info = forsale
        if not self._open_newest(page) and not forsale:
            return [], "could not open the Newest list"
        out = []
        for p in self._read_rows(page):
            key = f"{name}|{p['seller']}|{p['channel']}|{p['location']}|{p['price']}"
            out.append(Listing(key=key, item_id="", item_name=name, channel=p["channel"],
                               location=p["location"], price=p["price"], avg24h=typical,
                               seller=p["seller"], listed=p["listed"], age_min=p["age_min"],
                               observed=time.time()))
        si = self.scroll_info
        self._act(f"Read {len(out)} listing(s) of '{name}' (site says {si.get('expected') or '?'}; "
                  f"{si.get('steps', 0)} scroll step(s); stopped because {si.get('stop') or '?'})")
        return out, ("" if out else "no listings shown")

    # ---- poller interface
    def fetch(self) -> list[Listing]:
        try:
            return self._fetch()
        except RateLimited:
            raise
        except ChallengeDetected as e:
            self._escalate("Stopped by a Cloudflare check / refused access", e)
            raise
        except Exception as e:
            self._escalate(f"An error stopped the scan: {_short(e)}", e)
            raise

    def _fetch(self) -> list[Listing]:
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
            self._act(f"Checking '{name}' ({i + 1}/{len(names)})")
            try:
                ls, note = self._monitor(page, name)
                self._act(f"Result for '{name}': {len(ls)} listing(s)" + (f" - {note}" if note else ""))
                out += ls
                if note:
                    notes.append(f"{name}: {note}")
            except (ChallengeDetected, RateLimited):
                raise
            except Exception as e:
                errors.append(f"{name}: {_short(e)}")
            if self.should_stop and self.should_stop():
                self._act("Stop was pressed: the scan ends after the item that was being read")
                break
            if i < len(names) - 1:
                self._delay()
        if errors and len(errors) == len(names):
            raise RuntimeError("; ".join(errors[:2]))
        self.note = "; ".join((notes + errors)[:3])
        return out

    # ---- settings "Test"
    def diagnose(self, name: str, snapshot: Optional[Path] = None) -> list[str]:
        """Walk through one item step by step and say what worked (see _diagnose). When a step fails the error
        log is written and, if the test ran in the background, the browser window is opened for you."""
        errorlog.action(f"Settings test started for '{name}'")
        log = self._diagnose(name, snapshot)
        bad = [ln for ln in log if ln.startswith(("FAIL", "STOP"))]
        if bad:
            for ln in log:
                errorlog.action("TEST: " + ln.strip())
            was_background = self.background
            self._escalate("The Settings test failed: " + bad[0][:160])
            log.append(f"The error log was saved to: {errorlog.log_path()}  (upload this file for troubleshooting)")
            if was_background and not self.background:
                log.append("The browser window was opened on the site so you can look at it or finish a check by hand.")
        return log

    def _diagnose(self, name: str, snapshot: Optional[Path] = None) -> list[str]:
        """Walk through one item step by step and say what worked. Saves the rendered page to
        `snapshot` so selectors/labels can be adjusted (and shared) without guessing."""
        log: list[str] = []
        try:
            self._open()
            page = self._page
            log.append(f"OK  Browser mode: {self.mode}")
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
                if not self.last_candidates:
                    log.append(f"FAIL The site showed no search result for '{name}'.")
                else:
                    log.append(f"FAIL Opened {len(self.last_panels)} search result(s) ({near}) but the right-hand "
                               f"panel never showed '{name}'. It showed: {'; '.join(self.last_panels[:4])}.")
                return log
            log.append(f"OK  Opened the item (searched '{used}'; right-hand panel: {self.match_info})")
            typ = self._typical(page, used)
            log.append(f"{'OK ' if typ else 'WARN'} Typical price: {typ:,.0f}" if typ
                       else "WARN Typical price not found (Discount column will be blank)")
            forsale = self._open_forsale(page)
            if forsale:
                log.append(f"OK  Clicked the '{forsale}' tab")
            else:
                log.append(f"WARN No '{self.bc.get('forsale_label') or 'For sale now'}' tab found; using the older Where to buy / Newest buttons")
            if not self._open_newest(page) and not forsale:
                log.append(f"FAIL Could not find the '{self.bc['newest_label']}' button/list.")
                return log
            log.append(f"OK  '{self.bc['newest_label']}' list open")
            try:
                upd = page.evaluate("() => { const e = document.querySelector('.fsn-upd'); "
                                    "return e ? (e.innerText + ' | ' + (e.getAttribute('title') || '')) : ''; }")
            except Exception:
                upd = ""
            if upd:
                log.append(f"OK  The site says: {upd.strip()} (listing ages are read as shown; the program then "
                           "adds the time that passes after each reading)")
            rows = self._read_rows(page)
            si = self.scroll_info
            log.append(f"OK  Scrolled the Newest list {si.get('steps', 0)} time(s) in '{si.get('container') or '?'}': "
                       f"{si.get('rows', 0)} rows seen (site says {si.get('expected') or '?'}), {si.get('loads', 0)} time(s) the site loaded more; "
                       f"stopped because {si.get('stop') or '?'}")
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
