"""Live Feed rules that do not need a window: clearing, retention, 'Place not seen', Target Price, column order."""
import time

import pytest

from mesowatcher import core


@pytest.fixture()
def cfg(tmp_path):
    return core.Config(tmp_path / "c.json")


def L(item="Pan Lid", seller="s", channel="5", location="FM 3", price=100, age=10.0, observed=None):
    return core.Listing(key=f"{item}|{seller}|{channel}|{location}|{price}", item_id="", item_name=item,
                        channel=channel, location=location, price=price, avg24h=None, seller=seller,
                        age_min=age, observed=observed if observed is not None else time.time())


# ---- 'Only listings with Channel and Location'
@pytest.mark.parametrize("channel,location,expected", [
    ("5", "Henesys", True), ("5", "FM 3", True),
    ("5", "Place not seen", False), ("5", "place not seen", False), ("5", "  Place Not Seen. ", False),
    ("5", "Not seen", False), ("5", "FM ?", False), ("5", "", False), ("5", "-", False),
    ("", "Henesys", False), ("", "", False), ("?", "FM 3", False),
])
def test_has_place(channel, location, expected):
    assert core.has_place(channel, location) is expected


def test_a_place_that_merely_contains_the_words_still_counts():
    assert core.has_place("1", "Seen Valley Outpost")


# ---- delete older than X hours
def test_retention_uses_hours_setting_else_the_lookback_window(cfg):
    cfg["browser"]["lookback_min"] = 180
    assert core.feed_retention(cfg) == 180  # setting is 0 = off
    cfg["feed_max_age_hours"] = 6
    assert core.feed_retention(cfg) == 360  # keeps listings longer than the look-back window
    cfg["feed_max_age_hours"] = 0.5
    assert core.feed_retention(cfg) == 30
    cfg["feed_max_age_hours"] = "nonsense"
    assert core.feed_retention(cfg) == 180


def test_old_listings_are_deleted_by_retention_and_the_clock_runs_while_closed(cfg):
    cfg["feed_max_age_hours"] = 2
    now = time.time()
    fresh = L(seller="fresh", age=30, observed=now)
    stale = L(seller="stale", age=100, observed=now - 30 * 60)  # 100 min old when read, 30 min ago: 130 min now
    kept = core.prune_listings([fresh, stale], core.feed_retention(cfg), now)
    assert [l.seller for l in kept] == ["fresh"]
    later = core.prune_listings([fresh], core.feed_retention(cfg), now + 100 * 60)  # 130 min after reading
    assert later == []


# ---- Clear Live Feed
def test_cleared_listings_stay_gone_but_new_ones_and_relists_come_back():
    now = time.time()
    old = L(seller="old", age=25, observed=now)
    other = L(seller="other", age=5, observed=now)
    dismissed = core.dismiss_all([old, other], {}, now)
    assert set(dismissed) == {old.key, other.key}
    # the same shop, read again 5 min later (so 30 min old): still the deleted listing
    assert core.is_dismissed(L(seller="old", age=30, observed=now + 300), dismissed)
    # a shop that was not in the feed when it was cleared is simply shown
    assert not core.is_dismissed(L(seller="brand-new", age=1, observed=now + 300), dismissed)
    # the same shop listed again at the same price 10 min later: younger than the time since the clear
    assert not core.is_dismissed(L(seller="old", age=2, observed=now + 700), dismissed)
    assert not core.is_dismissed(L(seller="old", age=2), {})


def test_dismissed_without_an_age_is_hidden_and_old_entries_are_forgotten():
    now = time.time()
    l = L(seller="x", age=None)
    assert core.is_dismissed(l, {l.key: now})
    kept = core.dismiss_all([L(seller="y")], {"ancient": now - 5 * 86400, "recent": now - 3600}, now)
    assert set(kept) == {"recent", L(seller="y").key}


# ---- Target Price column
def test_watchlist_target(cfg):
    w = core.Watchlist(cfg)
    w.add("Pan Lid", 50000)
    w.add("Red Potion", None)
    assert w.target("pan lid") == (True, 50000)
    assert w.target("Red Potion") == (True, None)  # watched, any price
    assert w.target("Garnet Ore") == (False, None)  # not watched


# ---- new column goes next to Price, not at the far right
def test_new_column_is_placed_after_its_default_neighbour():
    old_default = ["item", "seller", "channel", "location", "price", "listed", "avg", "disc"]
    ids = ["item", "seller", "channel", "location", "price", "target", "listed", "avg", "disc"]
    assert core.merge_column_order(old_default, ids) == ids
    assert core.merge_column_order([], ids) == ids
    moved = ["price", "item", "seller", "channel", "location", "listed", "avg", "disc"]  # the user dragged Price first
    assert core.merge_column_order(moved, ids)[:3] == ["price", "target", "item"]
    assert core.merge_column_order(["gone"] + ids, ids) == ids  # unknown ids are dropped


# ---- the headless self-check used on other Linux systems
def test_selftest_prints_a_verdict(capsys, tmp_path, monkeypatch):
    from mesowatcher import selftest
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    rc = selftest.main(["--no-gui"])
    out = capsys.readouterr().out
    assert rc in (0, 1) and "[INFO] program: MSCW Market Watcher v" in out and "SELFTEST RESULT:" in out
    assert "[SKIP] window: --no-gui" in out


def test_feed_item_filter_chooses_one_several_or_all_items():
    L = lambda n: core.Listing(key=n, item_id="", item_name=n, channel="1", location="FM 1", price=1, avg24h=None,
                               seller="s", listed="", age_min=1.0, observed=0.0)
    ls = [L("Pan Lid"), L("Red Potion"), L("Pan Lid"), L("Garnet Ore")]
    assert len(core.feed_item_filter(ls, [])) == 4 and len(core.feed_item_filter(ls, None)) == 4
    assert [l.item_name for l in core.feed_item_filter(ls, ["pan lid "])] == ["Pan Lid", "Pan Lid"]
    assert {l.item_name for l in core.feed_item_filter(ls, ["Pan Lid", "Garnet Ore"])} == {"Pan Lid", "Garnet Ore"}
    assert core.DEFAULT_CONFIG["feed_items"] == []
