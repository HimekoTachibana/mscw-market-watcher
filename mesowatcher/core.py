"""MesoWatcher core: config, listing sources, item database, matching, sound.

Design rules for the network code:
  * Polite: minimum poll interval, backs off on 429/503 (honoring Retry-After).
  * If the site serves a Cloudflare challenge or a 403, polling PAUSES and the UI says so.
    It never tries to solve, spoof or route around the challenge.
  * Listings are read by a real browser (browser.py) that clicks through the site like a person.
    The JSON ListingSource below is only used if config "source_mode" is set to "api".
"""
from __future__ import annotations

import json
import math
import os
import platform
import queue
import random
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import time
import wave
from dataclasses import asdict, dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable, Optional

import requests

APP_NAME = "MesoWatcher"
VERSION = "0.4.0"
FULL_NAME = "MSCW Market Watcher"  # used for packaged app / folder names
MIN_INTERVAL_MS = 1000  # hard floor, regardless of settings
MAX_BACKOFF_S = 600


def data_dir() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home()))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    p = base / APP_NAME
    p.mkdir(parents=True, exist_ok=True)
    return p


DEFAULT_CONFIG = {
    "interval_ms": 30000,  # api mode only. Browser mode pauses a random delay_min_ms..delay_max_ms instead
    "delay_min_ms": 500,  # random pause between actions and between passes (never below 500)
    "delay_max_ms": 5000,
    "source_mode": "browser",  # "browser" (click through the site) or "api" (JSON endpoint)
    "browser": {
        "start_url": "https://meso.watch/",
        "channel": {"win32": "msedge", "darwin": "chrome"}.get(sys.platform, "chromium"),
        "headless": True,  # False = show the browser window (needed to pass a Cloudflare check yourself)
        "lookback_min": 180,  # scroll the Newest list down to listings from the last N minutes (3 hours)
        "listing_cap": 200,  # safety cap on listings read per item
        "max_scrolls": 40,
        "page_timeout_ms": 20000,
        "challenge_wait_s": 180,
        "filter_placeholder": "Filter items",  # matched by words, so "..." or the single "\u2026" both work
        "item_selector": "button.item-select",  # item buttons in the table (blank = match by visible text)
        "row_selector": "li.buy-row",  # one listing in the Newest list (blank = find rows by their "each" label)
        "newest_label": "Newest",
        "open_labels": ["Where to buy", "For sale now"],
    },
    "max_age_min": 0,  # extra cap on listing age in minutes (0 = none); lookback_min already limits it
    "only_with_location": False,  # Live Feed: show only listings that have BOTH a channel and a location
    "sold": [],  # keys of listings the user ticked as sold/checked
    "feed_sort": {"col": "listed", "desc": False},  # default: most recent listing on top
    "feed_columns": [],  # saved left-to-right order of the Live Feed columns ([] = default)
    "feed_widths": {},
    "feed_pane": 0,  # saved height (px) of the Live Feed pane
    "source_url": "",  # api mode only: JSON endpoint
    "list_path": "",  # dot path to the array in the JSON, "" = top level
    "field_map": {  # our field -> key (dot path) in each record
        "item_id": "item_id",
        "item_name": "item_name",
        "channel": "channel",
        "location": "location",
        "price": "price",
        "avg24h": "avg_24h",
        "listing_id": "id",
    },
    "custom_headers": {},  # e.g. {"Authorization": "Bearer ..."}
    "contact": "",  # shown in the User-Agent so the owners can reach you
    # Item list: OSMS Data Explorer (ids, names, icons), cross-checked against MeowDB.
    "osms_base": "https://osmsdataexplorer.com/data/current",
    "meowdb_url": "https://meowdb.com/msclassic/item-db/all",
    "meowdb_enabled": True,
    "meowdb_add_missing": True,  # add items that exist only on MeowDB (name only, no icon)
    "volume": 60,
    "muted": False,
    "show_all": False,
    "watchlist": [],  # [{"name": "...", "max_price": 1234 or null}]
}


class Config:
    def __init__(self, path: Optional[Path] = None):
        self.path = path or (data_dir() / "config.json")
        self.data = json.loads(json.dumps(DEFAULT_CONFIG))
        self.load()

    def load(self):
        if self.path.exists():
            try:
                saved = json.loads(self.path.read_text(encoding="utf-8"))
                for k, v in saved.items():
                    if isinstance(v, dict) and isinstance(self.data.get(k), dict):
                        self.data[k].update(v)
                    else:
                        self.data[k] = v
            except (OSError, ValueError):
                pass

    def save(self):
        self.path.write_text(json.dumps(self.data, indent=2), encoding="utf-8")

    def __getitem__(self, k):
        return self.data[k]

    def __setitem__(self, k, v):
        self.data[k] = v


# ----------------------------------------------------------------- listings
@dataclass
class Listing:
    key: str
    item_id: str
    item_name: str
    channel: str
    location: str
    price: int
    avg24h: Optional[float]
    seller: str = ""
    listed: str = ""  # e.g. "3m ago"
    age_min: Optional[float] = None  # age (minutes) when it was read from the site
    observed: float = 0.0  # time.time() of that reading, so the age keeps growing while saved

    def age_now(self, now: Optional[float] = None) -> Optional[float]:
        if self.age_min is None:
            return None
        if not self.observed:
            return self.age_min
        return self.age_min + max((now or time.time()) - self.observed, 0) / 60.0

    @property
    def discount(self) -> Optional[float]:
        """% below the 24h average (positive = cheaper than average)."""
        if not self.avg24h or self.avg24h <= 0:
            return None
        return (self.avg24h - self.price) / self.avg24h * 100.0


class RateLimited(Exception):
    def __init__(self, retry_after: float):
        super().__init__(f"rate limited, retry in {retry_after:.0f}s")
        self.retry_after = retry_after


class ChallengeDetected(Exception):
    pass


def _dig(obj, path: str):
    if path in ("", None):
        return obj
    for part in path.split("."):
        if isinstance(obj, list):
            obj = obj[int(part)]
        elif isinstance(obj, dict):
            obj = obj.get(part)
        else:
            return None
        if obj is None:
            return None
    return obj


def parse_number(v) -> Optional[float]:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().lower().replace(",", "").replace(" ", "")
    m = re.fullmatch(r"([0-9]*\.?[0-9]+)([kmb]?)", s)
    if not m:
        return None
    mult = {"": 1, "k": 1e3, "m": 1e6, "b": 1e9}[m.group(2)]
    return float(m.group(1)) * mult


class ListingSource:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.session = requests.Session()

    def _headers(self) -> dict:
        contact = self.cfg["contact"].strip()
        ua = f"{APP_NAME}/{VERSION}" + (f" (contact: {contact})" if contact else "")
        h = {"User-Agent": ua, "Accept": "application/json"}
        h.update(self.cfg["custom_headers"] or {})
        return h

    def fetch_raw(self):
        url = self.cfg["source_url"].strip()
        if not url:
            raise ValueError("No source URL set (Settings -> Source URL).")
        r = self.session.get(url, headers=self._headers(), timeout=20)
        body_head = r.text[:2000].lower() if r.headers.get("content-type", "").startswith("text/") else ""
        if r.headers.get("cf-mitigated", "").lower() == "challenge" or "just a moment" in body_head:
            raise ChallengeDetected("The site returned a Cloudflare challenge.")
        if r.status_code in (429, 503):
            ra = r.headers.get("Retry-After", "")
            raise RateLimited(float(ra) if ra.isdigit() else 60.0)
        if r.status_code in (401, 403):
            raise ChallengeDetected(
                f"HTTP {r.status_code}: access refused. Ask the site owners to allowlist you "
                "or provide an API key (Settings -> Custom headers)."
            )
        r.raise_for_status()
        return r.json()

    def parse(self, payload) -> list[Listing]:
        rows = _dig(payload, self.cfg["list_path"])
        if not isinstance(rows, list):
            raise ValueError("list_path does not point to an array in the response.")
        fm = self.cfg["field_map"]
        out = []
        for row in rows:
            price = parse_number(_dig(row, fm["price"]))
            name = _dig(row, fm["item_name"])
            if price is None or name is None:
                continue
            item_id = _dig(row, fm["item_id"])
            channel = _dig(row, fm["channel"])
            location = _dig(row, fm["location"])
            lid = _dig(row, fm.get("listing_id", ""))
            key = str(lid) if lid is not None else f"{item_id}|{channel}|{location}|{int(price)}"
            out.append(Listing(
                key=key,
                item_id=str(item_id) if item_id is not None else "",
                item_name=str(name),
                channel=str(channel if channel is not None else ""),
                location=str(location if location is not None else ""),
                price=int(price),
                avg24h=parse_number(_dig(row, fm["avg24h"])),
            ))
        return out

    def fetch(self) -> list[Listing]:
        return self.parse(self.fetch_raw())


class Poller(threading.Thread):
    """Polls at the configured interval; backs off; pauses on challenges."""

    def __init__(self, source, cfg: Config,
                 on_listings: Callable[[list[Listing]], None],
                 on_status: Callable[[str], None]):
        super().__init__(daemon=True)
        self.source, self.cfg = source, cfg
        self.on_listings, self.on_status = on_listings, on_status
        self._halt = threading.Event()  # not "_stop": Thread uses that name internally
        self._backoff = 0.0
        if hasattr(source, "on_status"):
            source.on_status = on_status  # lets a browser source say "waiting for you..."

    def stop(self):
        self._halt.set()

    def run(self):
        try:
            self._loop()
        finally:
            close = getattr(self.source, "close", None)
            if close:
                close()

    def _loop(self):
        floor = getattr(self.source, "min_interval_ms", MIN_INTERVAL_MS)
        while not self._halt.is_set():
            pause = getattr(self.source, "pause_s", None)  # browser source: random 0.5-5 s like a person
            wait = pause() if pause else max(self.cfg["interval_ms"], floor) / 1000.0
            try:
                listings = self.source.fetch()
                self._backoff = 0.0
                self.on_listings(listings)
                note = getattr(self.source, "note", "")
                self.on_status(f"OK - {len(listings)} listings @ {time.strftime('%H:%M:%S')}"
                               + (f" - {note}" if note else ""))
            except RateLimited as e:
                self._backoff = min(max(self._backoff * 2, e.retry_after), MAX_BACKOFF_S)
                wait = self._backoff
                self.on_status(f"Rate limited - waiting {wait:.0f}s")
            except ChallengeDetected as e:
                self.on_status(f"PAUSED: {e}")
                return  # never try to get around it
            except Exception as e:  # network error, bad page, bad mapping...
                self._backoff = min(max(self._backoff * 2, 10.0), MAX_BACKOFF_S)
                wait = self._backoff
                self.on_status(f"Error: {e} (retry in {wait:.0f}s)")
            self._halt.wait(wait)


# ------------------------------------------------------------------ listing helpers
def random_pause_s(cfg: "Config") -> float:
    """A random wait between delay_min_ms and delay_max_ms (floor 500 ms), like a person clicking around."""
    lo = max(int(cfg["delay_min_ms"]), 500)
    hi = max(int(cfg["delay_max_ms"]), lo)
    return random.uniform(lo, hi) / 1000.0


def effective_window(cfg: "Config") -> float:
    """Newest listings only: the look-back window (minutes), tightened by the optional max_age_min cap."""
    look = float(cfg["browser"].get("lookback_min") or 0)
    cap = float(cfg["max_age_min"] or 0)
    vals = [v for v in (look, cap) if v > 0]
    return min(vals) if vals else 0.0


def fmt_age(minutes: Optional[float]) -> str:
    if minutes is None:
        return "-"
    m = int(minutes)
    if m < 1:
        return "just now"
    if m < 60:
        return f"{m}m ago"
    h, r = divmod(m, 60)
    return f"{h}h ago" if r == 0 else f"{h}h {r}m ago"


_DUR_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(hours?|hrs?|h|minutes?|mins?|m)?", re.I)


def parse_duration(text: str) -> Optional[int]:
    """"45", "45 min", "1 hour", "1h30", "1.5h", "2 hours 15 minutes" -> minutes (None if unreadable).
    A bare number means minutes."""
    t = (text or "").strip().lower()
    if not t:
        return None
    total, pos, any_ = 0.0, 0, False
    for m in _DUR_RE.finditer(t):
        if t[pos:m.start()].strip(" ,&+and"):
            return None
        unit = (m.group(2) or "").lower()
        total += float(m.group(1)) * (60 if unit.startswith("h") else 1)
        pos, any_ = m.end(), True
    if not any_ or t[pos:].strip(" ,&+and"):
        return None
    return max(int(round(total)), 1)


def fmt_duration(minutes: float) -> str:
    m = int(round(minutes))
    if m < 60:
        return f"{m} minute" + ("" if m == 1 else "s")
    h, r = divmod(m, 60)
    out = f"{h} hour" + ("" if h == 1 else "s")
    return out if r == 0 else f"{out} {r} minute" + ("" if r == 1 else "s")


def merge_listings(old: list["Listing"], new: list["Listing"]) -> list["Listing"]:
    """Keep earlier listings (they persist until they age out) but let a fresh reading replace
    anything from the same seller for the same item."""
    fresh = {(l.item_name.lower(), l.seller.lower()) for l in new if l.seller}
    keep = [l for l in old if (l.item_name.lower(), l.seller.lower()) not in fresh]
    return keep + list(new)


def prune_listings(listings: list["Listing"], window_min: float, now: Optional[float] = None) -> list["Listing"]:
    if not window_min:
        return list(listings)
    out = []
    for l in listings:
        a = l.age_now(now)
        if a is None or a <= window_min:
            out.append(l)
    return out


def listings_path() -> Path:
    return data_dir() / "listings.json"


def save_listings(listings: list["Listing"], path: Optional[Path] = None):
    p = path or listings_path()
    try:
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps([asdict(l) for l in listings]), encoding="utf-8")
        tmp.replace(p)
    except OSError:
        pass


def load_listings(path: Optional[Path] = None) -> list["Listing"]:
    p = path or listings_path()
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    out = []
    for r in raw if isinstance(raw, list) else []:
        try:
            out.append(Listing(**{k: r[k] for k in Listing.__dataclass_fields__ if k in r}))
        except (TypeError, KeyError):
            continue
    return out


# ------------------------------------------------------------------ matching
class Watchlist:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.alerted: set[str] = set()

    @property
    def entries(self) -> list[dict]:
        return self.cfg["watchlist"]

    def add(self, name: str, max_price: Optional[int]):
        name = name.strip()
        if not name:
            return
        for e in self.entries:
            if e["name"].lower() == name.lower():
                e["max_price"] = max_price
                return
        self.entries.append({"name": name, "max_price": max_price})

    def remove(self, name: str):
        self.cfg["watchlist"] = [e for e in self.entries if e["name"].lower() != name.lower()]

    def matches(self, l: Listing) -> bool:
        limit = effective_window(self.cfg)
        age = l.age_now()
        if limit and age is not None and age > limit:
            return False  # outside the chosen time window
        for e in self.entries:
            if e["name"].lower() == l.item_name.lower():
                mp = e.get("max_price")
                if mp is None or l.price <= mp:
                    return True
        return False

    def new_matches(self, listings: list[Listing]) -> list[Listing]:
        fresh = []
        for l in listings:
            if self.matches(l) and l.key not in self.alerted:
                self.alerted.add(l.key)
                fresh.append(l)
        return fresh


# ------------------------------------------------------------------ item DB
MEOW_MIN_ENTRIES = 500  # below this, the MeowDB page is treated as unreadable
_LV_RE = re.compile(r"\s*\(?\s*lv\.?\s*\d+\s*\)?\s*$", re.I)

# Words that are page furniture or item categories, never item names.
_NOISE = {
    "items", "item db", "item database", "all items", "equipment", "use", "use items", "etc", "etc items",
    "setup", "cash shop", "cosmetic", "cosmetics", "home", "log in", "login", "discord", "privacy", "terms",
    "search", "loading", "browse", "safe to sell", "weapons", "armor", "other", "menu", "filter", "sort",
    "name", "level", "category", "type", "next", "previous", "back", "top", "new", "hot", "reuse",
    "security", "business", "hat", "gloves", "glove", "cape", "claw", "bow", "crossbow", "dagger", "staff",
    "wand", "earring", "box", "shoes", "shield", "belt", "pendant", "ring", "accessory", "overall",
    "equip top", "equip bottom", "polearm", "spear", "knuckle", "gun", "1h sword", "2h sword", "scroll",
}


def norm(s: str) -> str:
    """Normalise a name for matching: case, quotes and punctuation don't matter."""
    s = s.replace("’", "'").replace("‘", "'").lower().replace("'", "")
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def looks_like_item(name: str, extra_noise: frozenset | set = frozenset()) -> bool:
    """Guard for names that exist only on MeowDB: reject headings, menus and sentences."""
    n = norm(name)
    if len(n) < 3 or not re.search(r"[a-z]", n):
        return False
    if n in _NOISE or n in extra_noise:
        return False
    if re.search(r"\(\s*\d+\s*\)", name) or name.rstrip().endswith(":"):
        return False  # "Equip Bottom ( 175 )", "Sort by:"
    if re.match(r"^[\d,\.]+\s", name):
        return False  # "5,515 items total"
    if len(name.split()) > 8 or re.search(r"\.\s", name):
        return False  # a sentence, not a name
    return True


def bundled(rel: str) -> Path:
    """Path to a file shipped with the app (works from source and from PyInstaller)."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return base / rel


def user_agent(cfg: "Config") -> str:
    contact = cfg["contact"].strip()
    return f"{APP_NAME}/{VERSION}" + (f" (contact: {contact})" if contact else "")


class _TextCollector(HTMLParser):
    """Collects visible text, ignoring scripts, menus, headers, footers and buttons.
    Text inside <main> is also tracked separately so page chrome can be excluded."""

    _SKIP = {"script", "style", "noscript", "nav", "header", "footer", "aside", "button",
             "select", "option", "svg"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.main_parts: list[str] = []
        self._skip = 0
        self._main = 0

    def handle_starttag(self, tag, attrs):
        if tag in self._SKIP:
            self._skip += 1
        elif tag == "main":
            self._main += 1

    def handle_endtag(self, tag):
        if tag in self._SKIP and self._skip:
            self._skip -= 1
        elif tag == "main" and self._main:
            self._main -= 1

    def handle_data(self, data):
        if self._skip:
            return
        t = data.strip()
        if t:
            self.parts.append(t)
            if self._main:
                self.main_parts.append(t)


def parse_meowdb_names(html: str) -> dict[str, str]:
    """normalised name -> display name, from the text of MeowDB's item index page."""
    p = _TextCollector()
    p.feed(html)
    parts = p.main_parts if len(p.main_parts) >= MEOW_MIN_ENTRIES else p.parts
    out: dict[str, str] = {}
    for t in parts:
        t = _LV_RE.sub("", t).strip()
        if 2 <= len(t) <= 60:
            n = norm(t)
            if n:
                out.setdefault(n, t)
    return out


class ItemDB:
    """Item list built from OSMS Data Explorer (ids, names, icons) and MeowDB's item index.
    Everything is cached on this computer. An update only ever adds or corrects items; it never
    drops what you already have. Nothing from either site is bundled in the app except a small
    list of which icon files exist."""

    def __init__(self, cfg: Config, path: Optional[Path] = None):
        self.cfg = cfg
        self.path = path or (data_dir() / "items_cache.json")
        self.items: dict[str, dict] = {}  # id -> {"name", "cat", "ok", "src"}
        self.meta: dict = {}
        self._icon_hint: set[str] = set()
        self._rows: list[tuple[str, str, str]] = []  # (norm, display, id)
        self._rep_norm: dict[str, str] = {}
        self._load_icon_hint()
        self._load()

    # --- persistence
    def _load_icon_hint(self):
        try:
            txt = bundled("mesowatcher/icon_ids.txt").read_text(encoding="utf-8")
            self._icon_hint = {x.strip() for x in txt.split() if x.strip()}
        except OSError:
            self._icon_hint = set()

    def _load(self):
        if self.path.exists():
            try:
                d = json.loads(self.path.read_text(encoding="utf-8"))
                self.items, self.meta = d.get("items", {}), d.get("meta", {})
            except (OSError, ValueError):
                self.items, self.meta = {}, {}
        self._reindex()

    def _save(self):
        self.path.write_text(json.dumps({"items": self.items, "meta": self.meta}), encoding="utf-8")

    def _reindex(self):
        groups: dict[str, list[str]] = {}
        for iid, it in self.items.items():
            groups.setdefault(norm(it["name"]), []).append(iid)
        self._rows, self._rep_norm = [], {}
        for n, ids in groups.items():
            ids.sort(key=lambda i: (i not in self._icon_hint, i))  # prefer ids that have an icon
            rep = ids[0]
            self._rep_norm[n] = rep
            self._rows.append((n, self.items[rep]["name"], rep))
        self._rows.sort(key=lambda r: r[1].lower())

    # --- queries
    @property
    def report(self) -> list[str]:
        return self.meta.get("report", [])

    @property
    def age_days(self) -> float:
        t = self.meta.get("fetched")
        return (time.time() - t) / 86400 if t else float("inf")

    def names(self) -> list[str]:
        return [d for _, d, _ in self._rows]

    def id_for_name(self, name: str) -> Optional[str]:
        return self._rep_norm.get(norm(name)) if name else None

    def meta_text(self, iid: str) -> str:
        it = self.items.get(iid)
        if not it:
            return ""
        if it.get("src") == "meow":
            return "MeowDB only"
        return (it.get("cat") or "") + (" ✓" if it.get("ok") else "")

    def search(self, query: str, limit: int = 60) -> list[tuple[str, str]]:
        """[(display name, id)] best matches first. Empty query = alphabetical."""
        q = norm(query)
        toks = q.split()
        if not toks:
            return [(d, i) for _, d, i in self._rows[:limit]]
        scored = []
        for n, d, i in self._rows:
            if all(t in n for t in toks):
                words = n.split()
                if n.startswith(q):
                    rank = 0
                elif all(any(w.startswith(t) for w in words) for t in toks):
                    rank = 1
                else:
                    rank = 2
                scored.append((rank, d.lower(), d, i))
        scored.sort()
        return [(d, i) for _, _, d, i in scored[:limit]]

    # --- building
    def _get(self, url: str) -> requests.Response:
        r = requests.get(url, timeout=45, headers={"User-Agent": user_agent(self.cfg)})
        if r.status_code in (401, 403, 429, 503) or "just a moment" in r.text[:600].lower():
            raise RuntimeError(f"HTTP {r.status_code}: the site refused automated access, skipped")
        r.raise_for_status()
        return r

    def _fetch_osms(self) -> tuple[dict[str, str], dict[str, str]]:
        base = self.cfg["osms_base"].rstrip("/")
        names = self._get(f"{base}/lookups.json").json()["item_names"]
        cats: dict[str, str] = {}
        try:  # optional: category labels
            d = self._get(f"{base}/items.json").json()
            for x in d.get("items", []):
                cats[str(x["id"]).zfill(8)] = x.get("sub_category") or x.get("category") or ""
            for x in d.get("scrolls", []):
                cats[str(x["id"]).zfill(8)] = "Scroll"
        except Exception:
            pass
        return {str(k).zfill(8): str(v) for k, v in names.items() if isinstance(v, str)}, cats

    def update(self) -> list[str]:
        """Pull OSMS Data Explorer and MeowDB, add anything missing, cross-check names.
        Existing items are kept. Returns report lines (summary first); also saved."""
        try:
            names, cats = self._fetch_osms()
        except Exception as e:
            self.meta["report"] = [f"Update failed: OSMS Data Explorer could not be read ({e}). "
                                   "Your item list was not changed."]
            if self.items:
                self._save()
            return self.report

        items = {i: dict(it) for i, it in self.items.items()}  # start from what we already have
        added_osms: list[str] = []
        for iid, name in names.items():
            if iid in items:
                items[iid].update(name=name, src="osms")
                if iid in cats:
                    items[iid]["cat"] = cats[iid]
            else:
                items[iid] = {"name": name, "cat": cats.get(iid, ""), "ok": None, "src": "osms"}
                added_osms.append(name)
        # a MeowDB-only entry is superseded once OSMS knows the same name
        osms_norm: dict[str, str] = {}
        for it in items.values():
            if it.get("src") != "meow":
                osms_norm.setdefault(norm(it["name"]), it["name"])
        for iid in [i for i, it in items.items() if it.get("src") == "meow" and norm(it["name"]) in osms_norm]:
            del items[iid]

        detail = [f"OSMS Data Explorer: {len(names):,} item ids, {len(osms_norm):,} unique names."]
        meow: dict[str, str] = {}
        added_meow: list[str] = []
        if self.cfg["meowdb_enabled"] and self.cfg["meowdb_url"].strip():
            try:
                resp = self._get(self.cfg["meowdb_url"].strip())
                # decode as UTF-8 ourselves: requests assumes Latin-1 when no charset is sent,
                # which turns curly apostrophes into mojibake and creates bogus "new" items
                meow = parse_meowdb_names(resp.content.decode("utf-8", errors="replace"))
                if len(meow) < MEOW_MIN_ENTRIES:
                    detail.append(f"MeowDB: the page exposed only {len(meow)} entries (it is probably built by "
                                  "script), so the cross-check and MeowDB additions were skipped.")
                    meow = {}
            except Exception as e:
                detail.append(f"MeowDB: skipped ({e}).")
                meow = {}
        if meow:
            for it in items.values():
                if it.get("src") != "meow":
                    it["ok"] = norm(it["name"]) in meow
            both = osms_norm.keys() & meow.keys()
            only_osms = sorted(osms_norm[n] for n in osms_norm.keys() - meow.keys())
            only_meow = sorted(meow[n] for n in meow.keys() - osms_norm.keys())
            if self.cfg["meowdb_add_missing"]:
                extra = {norm(it.get("cat", "")) for it in items.values()}
                have = {norm(it["name"]) for it in items.values()}
                for n in sorted(meow.keys() - have):
                    if looks_like_item(meow[n], extra):
                        key = "m_" + n.replace(" ", "_")
                        if key not in items:
                            items[key] = {"name": meow[n], "cat": "", "ok": None, "src": "meow"}
                            added_meow.append(meow[n])
            detail.append(f"MeowDB: {len(meow):,} entries read from the item index.")
            detail.append(f"Confirmed by both sites: {len(both):,} of {len(osms_norm):,} unique names "
                          f"({len(both) / max(len(osms_norm), 1) * 100:.1f}%). These show a check mark.")
            detail.append(f"In OSMS but not found on MeowDB: {len(only_osms):,}"
                          + (" - e.g. " + "; ".join(only_osms[:25]) if only_osms else ""))
            detail.append(f"On the MeowDB page but not in OSMS: {len(only_meow):,} "
                          f"({len(added_meow):,} added as MeowDB-only items; the rest looked like page text)"
                          + (" - e.g. " + "; ".join(only_meow[:25]) if only_meow else ""))

        total_new = len(added_osms) + len(added_meow)
        if total_new:
            head = (f"Update complete: {total_new:,} new item{'s' if total_new != 1 else ''} added "
                    f"({len(added_osms):,} from OSMS Data Explorer, {len(added_meow):,} only on MeowDB). "
                    f"The list now has {len(items):,} items.")
        else:
            head = f"Update complete: no new items found. Your list is up to date ({len(items):,} items)."
        report = [head]
        if added_osms:
            report.append("New from OSMS Data Explorer: " + "; ".join(added_osms[:40])
                          + (f" ... and {len(added_osms) - 40} more" if len(added_osms) > 40 else ""))
        if added_meow:
            report.append("New from MeowDB (name only, no icon): " + "; ".join(added_meow[:40])
                          + (f" ... and {len(added_meow) - 40} more" if len(added_meow) > 40 else ""))
        report += detail

        self.items = items
        self.meta = {"fetched": time.time(), "report": report, "unique": len({norm(i["name"]) for i in items.values()}),
                     "meow": len(meow), "added": total_new}
        self._reindex()
        self._save()
        return report

    refresh = update  # older name


class IconStore:
    """Downloads item icons in the background (one at a time, politely) and caches them."""

    def __init__(self, cfg: Config, on_ready: Optional[Callable[[str], None]] = None,
                 cache_dir: Optional[Path] = None):
        self.cfg, self.on_ready = cfg, on_ready
        self.dir = cache_dir or (data_dir() / "icons")
        self.dir.mkdir(parents=True, exist_ok=True)
        self._q: queue.Queue = queue.Queue()
        self._pending: set[str] = set()
        self._missing: set[str] = set()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._fail_until = 0.0

    def path(self, iid: str) -> Optional[Path]:
        """Cached file if we have it; otherwise queue a download and return None.
        Only numeric (OSMS) ids have icons; MeowDB-only items never do."""
        if not iid or not iid.isdigit():
            return None
        f = self.dir / f"{iid}.png"
        if f.exists():
            return f
        with self._lock:
            if iid in self._missing or iid in self._pending or time.time() < self._fail_until:
                return None
            self._pending.add(iid)
            self._q.put(iid)
            if self._thread is None:
                self._thread = threading.Thread(target=self._run, daemon=True)
                self._thread.start()
        return None

    def _run(self):
        s = requests.Session()
        s.headers["User-Agent"] = user_agent(self.cfg)
        base = self.cfg["osms_base"].rstrip("/")
        while True:
            try:
                iid = self._q.get(timeout=5)
            except queue.Empty:
                with self._lock:
                    if self._q.empty():
                        self._thread = None
                        return
                continue
            ok = False
            try:
                r = s.get(f"{base}/images/items/{iid}.png", timeout=15)
                if r.status_code == 200 and r.headers.get("content-type", "").startswith("image"):
                    tmp = self.dir / f"{iid}.tmp"
                    tmp.write_bytes(r.content)
                    os.replace(tmp, self.dir / f"{iid}.png")
                    ok = True
                elif r.status_code == 404:
                    self._missing.add(iid)
            except (requests.RequestException, OSError):
                self._fail_until = time.time() + 60  # offline? stop hammering for a minute
            with self._lock:
                self._pending.discard(iid)
            if ok and self.on_ready:
                self.on_ready(iid)
            time.sleep(0.03)


# --------------------------------------------------------------------- sound
class Beeper:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self._dir = Path(tempfile.gettempdir()) / f"{APP_NAME}_sounds"
        self._dir.mkdir(exist_ok=True)

    def _wav(self, volume: int) -> Path:
        f = self._dir / f"beep_{volume}.wav"
        if f.exists():
            return f
        rate, amp = 22050, int(32767 * (volume / 100.0) ** 2)
        frames = bytearray()
        for freq, dur in ((880, 0.12), (0, 0.05), (1175, 0.18)):
            for i in range(int(rate * dur)):
                v = 0 if freq == 0 else int(amp * math.sin(2 * math.pi * freq * i / rate))
                frames += struct.pack("<h", v)
        with wave.open(str(f), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(rate)
            w.writeframes(bytes(frames))
        return f

    def play(self, force: bool = False) -> bool:
        """Returns False if no player was available (caller can fall back to bell)."""
        if self.cfg["muted"] and not force:
            return True
        vol = int(self.cfg["volume"])
        if vol <= 0 and not force:
            return True
        f = str(self._wav(max(vol, 5)))
        try:
            if platform.system() == "Windows":
                import winsound
                winsound.PlaySound(f, winsound.SND_FILENAME | winsound.SND_ASYNC)
                return True
            cmd = ["afplay", f] if sys.platform == "darwin" else None
            if cmd is None:
                for c in ("paplay", "aplay", "play"):
                    if shutil.which(c):
                        cmd = [c, "-q", f] if c == "aplay" else [c, f]
                        break
            if cmd and shutil.which(cmd[0]):
                subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return True
        except Exception:
            pass
        return False
