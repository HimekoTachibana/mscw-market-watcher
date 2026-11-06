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


def test_poller_pause_and_resume(cfg):
    class Source:
        pause_s = staticmethod(lambda: 0.05)

        def __init__(self):
            self.calls = 0
            self.first = threading.Event()

        def fetch(self):
            self.calls += 1
            self.first.set()
            return []

        def close(self):
            pass

    src = Source()
    p = core.Poller(src, cfg, lambda ls: None, lambda status: None)
    p.start()
    assert src.first.wait(2)
    p.pause()
    time.sleep(0.35)
    calls_while_paused = src.calls
    assert p.is_paused
    p.resume()
    deadline = time.time() + 2
    while src.calls == calls_while_paused and time.time() < deadline:
        time.sleep(0.02)
    p.stop()
    p.join(timeout=2)
    assert calls_while_paused >= 1
    assert src.calls > calls_while_paused


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


# ---- release notes include every version no release has described yet
def _notes_tool():
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location("release_notes", Path(__file__).resolve().parent.parent / "tools" / "release_notes.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


CHANGELOG = """# Changelog

## v0.6.0 - 2026-11-09
- six

## v0.5.9 - 2026-11-08
- five-nine

## v0.5.8 - 2026-11-07
- five-eight

## v0.5.7 - 2026-11-06
- five-seven
"""


def test_release_notes_only_current_when_everything_before_was_released():
    m = _notes_tool()
    rel = [{"tag": "v0.5.9", "body": "x"}, {"tag": "v0.5.8", "body": "x"}, {"tag": "v0.5.7", "body": "x"}]
    assert m.build_notes(CHANGELOG, "v0.6.0", rel) == "- six\n"


def test_release_notes_include_versions_that_were_never_released():
    m = _notes_tool()
    rel = [{"tag": "v0.5.9", "body": "- five-nine"}, {"tag": "v0.5.7", "body": ""}]  # 0.5.8 never had a release
    out = m.build_notes(CHANGELOG, "v0.6.0", rel)
    assert "## v0.6.0" in out and "## v0.5.8" in out and "- five-eight" in out
    assert "five-nine" not in out and "five-seven" not in out
    assert out.index("v0.6.0") < out.index("v0.5.8")


def test_release_notes_skip_versions_whose_heading_is_already_in_a_release():
    m = _notes_tool()
    rel = [{"tag": "v0.5.9", "body": "## v0.5.9 - x\n- a\n\n## v0.5.8 - y\n- b"}, {"tag": "v0.5.7", "body": ""}]
    assert m.build_notes(CHANGELOG, "v0.6.0", rel) == "- six\n"


def test_release_notes_without_release_history_and_missing_section():
    m = _notes_tool()
    assert m.build_notes(CHANGELOG, "v0.6.0", None) == "- six\n"
    assert m.build_notes(CHANGELOG, "v9.9.9", []) == "Release v9.9.9\n"


def test_release_notes_include_versions_from_before_the_first_release():
    m = _notes_tool()
    log = CHANGELOG + "\n## v0.5.6 - old\n- pre-release history\n"
    out = m.build_notes(log, "v0.6.0", [{"tag": "v0.5.9", "body": ""}, {"tag": "v0.5.8", "body": ""}, {"tag": "v0.5.7", "body": ""}])
    assert "pre-release history" in out and out.index("## v0.6.0") < out.index("## v0.5.6")
