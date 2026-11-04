import time

from mesowatcher import core


def L(seller, item="Coupon", age=5.0, observed=None, price=100):
    return core.Listing(key=f"{item}|{seller}|{price}", item_id="", item_name=item, channel="1", location="FM 1",
                        price=price, avg24h=200, seller=seller, age_min=age,
                        observed=time.time() if observed is None else observed)


def test_age_keeps_growing_while_saved():
    l = L("a", age=10, observed=time.time() - 600)
    assert 19.9 < l.age_now() < 20.2


def test_fmt_age():
    assert [core.fmt_age(x) for x in (0.2, 5.9, 60, 61, 125, None)] == \
        ["just now", "5m ago", "1h ago", "1h 1m ago", "2h 5m ago", "-"]


def test_prune_by_window():
    old, new = L("old", age=10, observed=time.time() - 3000), L("new", age=3)
    assert [l.seller for l in core.prune_listings([old, new], 30)] == ["new"]
    assert len(core.prune_listings([old, new], 0)) == 2


def test_merge_replaces_same_seller_keeps_others():
    a, b = L("a", price=100), L("b", price=100)
    a2 = L("a", price=90)
    got = core.merge_listings([a, b], [a2])
    assert sorted((l.seller, l.price) for l in got) == [("a", 90), ("b", 100)]


def test_persist_roundtrip(tmp_path):
    p = tmp_path / "l.json"
    core.save_listings([L("a"), L("b")], p)
    got = core.load_listings(p)
    assert [l.seller for l in got] == ["a", "b"] and got[0].avg24h == 200
    assert core.load_listings(tmp_path / "missing.json") == []
    p.write_text("not json")
    assert core.load_listings(p) == []


def test_window_follows_lookback_and_cap(tmp_path):
    cfg = core.Config(tmp_path / "c.json")
    cfg["browser"]["lookback_min"] = 60
    assert core.effective_window(cfg) == 60
    cfg["max_age_min"] = 30
    assert core.effective_window(cfg) == 30


def test_parse_and_format_duration():
    p = core.parse_duration
    assert [p(x) for x in ("45", "45 min", "1 hour", "1h", "1h30", "1.5h", "2 hours 15 minutes", "15m")] == \
        [45, 45, 60, 60, 90, 90, 135, 15]
    assert p("") is None and p("soon") is None and p("3 apples") is None
    assert [core.fmt_duration(x) for x in (1, 15, 60, 90, 180)] == \
        ["1 minute", "15 minutes", "1 hour", "1 hour 30 minutes", "3 hours"]
