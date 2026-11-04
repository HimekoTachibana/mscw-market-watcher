import json
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from mesowatcher import core

PAYLOAD = {"data": {"listings": [
    {"id": 1, "item_id": "04031027", "item_name": "Hero's Gladius", "channel": 12,
     "location": "FM 3", "price": "900,000", "avg_24h": 1_000_000},
    {"id": 2, "item_id": "2000000", "item_name": "Red Potion", "channel": 3,
     "location": "FM 1", "price": 50, "avg_24h": 40},
]}}

MODE = {"kind": "ok"}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        k = MODE["kind"]
        if k == "ok":
            body = json.dumps(PAYLOAD).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
        elif k == "429":
            body = b"slow down"
            self.send_response(429)
            self.send_header("Retry-After", "7")
        elif k == "challenge":
            body = b"<html><title>Just a moment...</title></html>"
            self.send_response(403)
            self.send_header("Content-Type", "text/html")
            self.send_header("cf-mitigated", "challenge")
        else:
            body = b"nope"
            self.send_response(403)
            self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture(scope="module")
def server():
    s = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{s.server_port}/"
    s.shutdown()


@pytest.fixture()
def cfg(tmp_path, server):
    c = core.Config(tmp_path / "c.json")
    c["source_url"] = server
    c["list_path"] = "data.listings"
    c["contact"] = "test@example.com"
    MODE["kind"] = "ok"
    return c


def test_parse_and_discount(cfg):
    ls = core.ListingSource(cfg).fetch()
    assert len(ls) == 2
    g = ls[0]
    assert g.price == 900000 and g.channel == "12"
    assert round(g.discount, 1) == 10.0
    assert round(ls[1].discount, 1) == -25.0  # pricier than average


def test_watchlist_matching_and_dedupe(cfg):
    ls = core.ListingSource(cfg).fetch()
    w = core.Watchlist(cfg)
    w.add("hero's gladius", 950000)
    w.add("Red Potion", 10)
    assert [l.item_name for l in w.new_matches(ls)] == ["Hero's Gladius"]
    assert w.new_matches(ls) == []  # no repeat alert for the same listing


def test_rate_limit_and_challenge(cfg):
    src = core.ListingSource(cfg)
    MODE["kind"] = "429"
    with pytest.raises(core.RateLimited) as e:
        src.fetch()
    assert e.value.retry_after == 7
    MODE["kind"] = "challenge"
    with pytest.raises(core.ChallengeDetected):
        src.fetch()
    MODE["kind"] = "403"
    with pytest.raises(core.ChallengeDetected):
        src.fetch()


def test_poller_pauses_on_challenge_and_never_retries(cfg):
    MODE["kind"] = "challenge"
    msgs = []
    p = core.Poller(core.ListingSource(cfg), cfg, lambda ls: None, msgs.append)
    p.start()
    p.join(timeout=5)
    assert not p.is_alive()
    assert msgs and msgs[0].startswith("PAUSED")


def test_interval_floor(cfg):
    cfg["interval_ms"] = 10
    seen = []
    p = core.Poller(core.ListingSource(cfg), cfg, lambda ls: seen.append(time.time()), lambda s: None)
    p.start()
    time.sleep(2.3)
    p.stop()
    p.join(timeout=3)
    assert 2 <= len(seen) <= 3  # ~1 request/second at most


def test_user_agent_identifies_app(cfg):
    h = core.ListingSource(cfg)._headers()
    assert "MesoWatcher" in h["User-Agent"] and "test@example.com" in h["User-Agent"]


def test_beeper_wav_and_mute(cfg, monkeypatch):
    b = core.Beeper(cfg)
    f = b._wav(50)
    assert Path(f).exists() and Path(f).stat().st_size > 1000
    cfg["muted"] = True
    assert b.play() is True  # muted: silently "succeeds"


def test_parse_number():
    assert core.parse_number("1,200") == 1200
    assert core.parse_number("1.5m") == 1_500_000
    assert core.parse_number("abc") is None
