import base64
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from mesowatcher import core

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")

STATE = {}


def reset_state():
    STATE.clear()
    STATE.update(
        lookups={"1002000": "Brown Skullcap", "1002001": "Green Skullcap", "2020021": "Blue Malady's Candy",
                 "4003004": "Piece of Ice", "2040000": "Hat Accuracy Scroll: Lesser"},
        meow_entries=["Brown Skullcap (Lv 5)", "Blue Malady’s Candy", "Piece of Ice", "Hat Accuracy Scroll: Lesser",
                      "Brand New Hat (Lv 10)"],
        osms_status=200, meow_status=200,
    )


def meow_html():
    entries = "".join(f"<li><a href='/x'>{e}</a></li>" for e in STATE["meow_entries"])
    return ("<html><body><nav><a>Discord</a><a>Log In</a></nav><main><h2>Equip Bottom ( 175 )</h2>"
            f"<h3>Hat</h3><ul>{entries}</ul><p>5,515 items total</p></main>"
            "<footer><a>Privacy</a><a>Ad preferences</a></footer><script>var x='Fake Script Item';</script>"
            "</body></html>")


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        p = self.path
        if p.endswith("/lookups.json"):
            if STATE["osms_status"] != 200:
                return self._send(STATE["osms_status"], b"err", "text/plain")
            return self._send(200, json.dumps({"item_names": STATE["lookups"]}).encode(), "application/json")
        if p.endswith("/items.json"):
            d = {"items": [{"id": 1002000, "name": "Brown Skullcap", "category": "Equipment", "sub_category": "Hat"}],
                 "scrolls": [{"id": 2040000, "name": "Hat Accuracy Scroll: Lesser"}]}
            return self._send(200, json.dumps(d).encode(), "application/json")
        if p.endswith("/meow/all"):
            if STATE["meow_status"] != 200:
                return self._send(STATE["meow_status"], b"blocked", "text/plain")
            return self._send(200, meow_html().encode(), "text/html")
        if "/images/items/" in p:
            if p.endswith("/01002000.png") or p.endswith("/04003004.png"):
                return self._send(200, PNG, "image/png")
            return self._send(404, b"nope", "text/plain")
        self._send(404, b"nope", "text/plain")


@pytest.fixture(scope="module")
def base():
    s = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{s.server_port}"
    s.shutdown()


@pytest.fixture()
def db(tmp_path, base, monkeypatch):
    reset_state()
    monkeypatch.setattr(core, "MEOW_MIN_ENTRIES", 5)
    cfg = core.Config(tmp_path / "c.json")
    cfg["osms_base"] = base + "/data/current"
    cfg["meowdb_url"] = base + "/meow/all"
    return core.ItemDB(cfg, tmp_path / "items.json")


def names(db):
    return {it["name"] for it in db.items.values()}


def test_first_update_builds_list_and_filters_page_text(db):
    rep = db.update()
    assert rep[0].startswith("Update complete: 6 new items added (5 from OSMS Data Explorer, 1 only on MeowDB)")
    assert "Brand New Hat" in names(db)
    for junk in ("Equip Bottom ( 175 )", "Hat", "Discord", "Log In", "Privacy", "Fake Script Item",
                 "5,515 items total", "Ad preferences"):
        assert junk not in names(db)
    assert len(db.items) == 6


def test_cross_check_flags_and_categories(db):
    db.update()
    by = {it["name"]: it for it in db.items.values()}
    assert by["Brown Skullcap"]["ok"] is True and by["Brown Skullcap"]["cat"] == "Hat"
    assert by["Blue Malady's Candy"]["ok"] is True  # curly vs straight apostrophe
    assert by["Green Skullcap"]["ok"] is False  # OSMS only
    assert by["Hat Accuracy Scroll: Lesser"]["cat"] == "Scroll"
    assert db.meta_text(db.id_for_name("Green Skullcap")) == ""
    assert "✓" in db.meta_text(db.id_for_name("Piece of Ice"))
    assert db.meta_text(db.id_for_name("Brand New Hat")) == "MeowDB only"
    assert any("Green Skullcap" in line for line in db.report)  # listed as missing from MeowDB


def test_second_update_only_adds_new_and_keeps_old(db):
    db.update()
    STATE["lookups"]["2000000"] = "Red Potion"
    STATE["meow_entries"] += ["Red Potion", "Another New Thing (Lv 3)"]
    rep = db.update()
    assert rep[0].startswith("Update complete: 2 new items added (1 from OSMS Data Explorer, 1 only on MeowDB)")
    assert "New from OSMS Data Explorer: Red Potion" in rep[1]
    assert "Another New Thing" in rep[2]
    assert "Brand New Hat" in names(db) and len(db.items) == 8
    rep = db.update()
    assert rep[0].startswith("Update complete: no new items found")


def test_never_drops_items_even_if_source_shrinks(db):
    db.update()
    del STATE["lookups"]["1002001"]
    db.update()
    assert "Green Skullcap" in names(db)


def test_meow_only_item_superseded_when_osms_gets_it(db):
    db.update()
    STATE["lookups"]["1002999"] = "Brand New Hat"
    rep = db.update()
    assert "1 from OSMS Data Explorer, 0 only on MeowDB" in rep[0]
    assert sum(1 for it in db.items.values() if it["name"] == "Brand New Hat") == 1
    assert db.items[db.id_for_name("Brand New Hat")]["src"] == "osms"


def test_osms_failure_keeps_previous_list(db):
    db.update()
    before = dict(db.items)
    STATE["osms_status"] = 500
    rep = db.update()
    assert rep[0].startswith("Update failed") and db.items == before


def test_meow_blocked_does_not_break_osms_update(db):
    STATE["meow_status"] = 403
    rep = db.update()
    assert "5 from OSMS Data Explorer, 0 only on MeowDB" in rep[0]
    assert any("MeowDB: skipped" in line and "refused automated access" in line for line in rep)
    assert all(it["ok"] is None for it in db.items.values())


def test_meow_unreadable_page_is_skipped(db, monkeypatch):
    monkeypatch.setattr(core, "MEOW_MIN_ENTRIES", 500)
    rep = db.update()
    assert any("exposed only" in line for line in rep) and len(db.items) == 5


def test_add_missing_can_be_turned_off(db):
    db.cfg["meowdb_add_missing"] = False
    db.update()
    assert "Brand New Hat" not in names(db)


def test_persistence(db, tmp_path):
    db.update()
    again = core.ItemDB(db.cfg, tmp_path / "items.json")
    assert len(again.items) == 6 and again.report and again.age_days < 1


def test_search_ranking_and_tolerance(db):
    db.update()
    assert db.search("malady")[0][0] == "Blue Malady's Candy"
    assert db.search("maladys candy")[0][0] == "Blue Malady's Candy"
    assert db.search("piece ice")[0][0] == "Piece of Ice"
    assert db.search("zzzz") == []
    alpha = [n for n, _ in db.search("")]
    assert alpha == sorted(alpha, key=str.lower)
    assert db.search("skullcap")[0][0] in ("Brown Skullcap", "Green Skullcap")


def test_duplicate_names_prefer_id_with_icon(db):
    db.items = {"00000001": {"name": "Twin", "cat": "", "ok": None, "src": "osms"},
                "00000002": {"name": "Twin", "cat": "", "ok": None, "src": "osms"}}
    db._icon_hint = {"00000002"}
    db._reindex()
    assert db.id_for_name("twin") == "00000002" and len(db.search("twin")) == 1


@pytest.mark.parametrize("name,ok", [
    ("Brown Skullcap", True), ("Hat Accuracy Scroll: Lesser", True), ("Equip Bottom ( 175 )", False),
    ("Hat", False), ("Discord", False), ("5,515 items total", False), ("Sort by:", False),
    ("AB", False), ("12345", False), ("This is a long sentence. It is not an item name at all", False),
])
def test_looks_like_item(name, ok):
    assert core.looks_like_item(name) is ok


def _wait(cond, t=4.0):
    end = time.time() + t
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.05)
    return False


def test_icon_store_downloads_caches_and_skips_non_numeric(base, tmp_path):
    cfg = core.Config(tmp_path / "c.json")
    cfg["osms_base"] = base + "/data/current"
    got = []
    st = core.IconStore(cfg, on_ready=got.append, cache_dir=tmp_path / "icons")
    assert st.path("01002000") is None  # not cached yet: queued
    assert _wait(lambda: (tmp_path / "icons" / "01002000.png").exists())
    assert st.path("01002000").read_bytes() == PNG and "01002000" in got
    assert st.path("09999999") is None
    assert _wait(lambda: "09999999" in st._missing)  # 404 remembered, never retried
    assert st.path("m_brand_new_hat") is None and st.path("") is None
    assert "m_brand_new_hat" not in st._pending
