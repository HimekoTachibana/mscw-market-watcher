"""Self-check that proves the program runs on a given machine (used by CI on each Linux distribution).

    "MSCW Market Watcher vX" --selftest              imports, window, bundled browser driver
    "MSCW Market Watcher vX" --selftest --browser    ... plus download Chromium and open a page with it
    "MSCW Market Watcher vX" --selftest --no-gui     skip the window check (no display available)

Prints one [PASS]/[FAIL]/[INFO]/[SKIP] line per check and ends with "SELFTEST RESULT: OK" or "FAILED".
The exit code is 1 when anything failed. Settings go to a temporary folder, never your real ones.
"""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def _os_release() -> str:
    try:
        for line in Path("/etc/os-release").read_text(encoding="utf-8").splitlines():
            if line.startswith("PRETTY_NAME="):
                return line.split("=", 1)[1].strip().strip('"')
    except OSError:
        pass
    return platform.platform()


def _glibc() -> str:
    try:
        return os.confstr("CS_GNU_LIBC_VERSION")  # e.g. "glibc 2.36"
    except (AttributeError, ValueError, OSError):
        return "n/a"


def _driver():
    """(node, cli.js) of the Playwright driver bundled with the program."""
    from playwright._impl._driver import compute_driver_executable
    d = compute_driver_executable()
    return (str(d[0]), str(d[1])) if isinstance(d, tuple) else (str(d), "")


def _exercise_feed(a, app, core):
    """Drive the real window: put listings in the Live Feed and use the controls on it."""
    import time
    import tkinter as tk
    from tkinter import messagebox
    cols = [c[0] for c in app.COLS]
    assert cols[cols.index("price") + 1] == "target", "Target Price must sit right after Price"
    assert "target" in a._display_cols(), "Target Price column is not displayed"
    a.watch.add("Pan Lid", 5000)
    now = time.time()

    def mk(key, item, loc, price):
        return core.Listing(key=key, item_id="", item_name=item, channel="5", location=loc, price=price,
                            avg24h=6000, seller="s" + key, listed="3m ago", age_min=3.0, observed=now)
    a.listings = [mk("1", "Pan Lid", "Place not seen", 4000), mk("2", "Pan Lid", "Henesys", 4500),
                  mk("3", "Red Potion", "Henesys", 50)]
    a.show_all.set(True)
    a.only_loc.set(False)
    a._render()
    rows = a.tree.get_children()
    assert len(rows) == 3, f"expected 3 rows, saw {len(rows)}"
    texts = {a.tree.set(r, "item"): a.tree.set(r, "target") for r in rows}
    assert texts == {"Pan Lid": "5,000", "Red Potion": "-"}, f"Target Price shows {texts}"
    a.only_loc.set(True)
    a._render()
    assert len(a.tree.get_children()) == 2, "'Place not seen' was not filtered out"
    assert "Next item every" in a.delay_lbl.cget("text"), "delay label of the rotating windows mode is missing"
    a.cfg["feed_items"] = ["Red Potion"]  # the item filter
    a._render()
    assert [a.tree.set(r, "item") for r in a.tree.get_children()] == ["Red Potion"], "item filter did not apply"
    a._update_headings()
    assert "\u25be (1)" in a.tree.heading("item", "text"), "Item Name heading does not show the filter"
    a.choose_feed_items()  # the drop-down opens
    a.update()
    a._item_filter_win.destroy()
    a.cfg["feed_items"] = []
    a._update_headings()
    a._render()
    a.only_loc.set(True)
    a._render()
    a.sort_by("target")  # sorting by the new column must not fail
    a.sort_by("target")
    a.cfg["feed_max_age_hours"] = 0.001  # 3.6 s: the 3-minute-old listings are older than that
    a._render()
    assert not a.tree.get_children(), "listings older than the retention setting were not deleted"
    a.cfg["feed_max_age_hours"] = 0
    a.listings = [mk("1", "Pan Lid", "Henesys", 4000)]
    a.only_loc.set(False)
    a._render()
    ask = messagebox.askyesno
    messagebox.askyesno = lambda *x, **k: True  # answer the confirmation question
    try:
        a.clear_feed()
    finally:
        messagebox.askyesno = ask
    assert a.listings == [] and not a.tree.get_children(), "Clear Live Feed left listings behind"
    assert core.is_dismissed(mk("1", "Pan Lid", "Henesys", 4000), a.cfg["feed_dismissed"])
    a.open_settings()  # builds every settings tab
    a.update()
    for w in a.winfo_children():
        if isinstance(w, tk.Toplevel):
            w.destroy()


def main(argv: list[str]) -> int:
    want_gui, want_browser = "--no-gui" not in argv, "--browser" in argv
    failed: list[str] = []

    def rec(status: str, name: str, detail: str = ""):
        print(f"[{status}] {name}: {detail}", flush=True)
        if status == "FAIL":
            failed.append(name)

    tmp = tempfile.mkdtemp(prefix="mscw-selftest-")
    os.environ["XDG_CONFIG_HOME"] = tmp  # keep the real settings out of this
    os.environ["APPDATA"] = tmp
    try:
        from . import browser as _browser
        from . import core
        core.data_dir = _browser.data_dir = lambda: Path(tmp)  # settings, listings and browser profile: all temporary
        rec("INFO", "program", f"{core.FULL_NAME} v{core.VERSION}, "
                               f"{'packaged' if getattr(sys, 'frozen', False) else 'source'}")
    except Exception as e:
        rec("FAIL", "program", f"cannot import the program: {e}")
        print("SELFTEST RESULT: FAILED (program)")
        return 1
    rec("INFO", "system", f"{_os_release()} | {platform.machine()} | {_glibc()} | Python {platform.python_version()}")

    # ---- libraries the program is built from
    for mod in ("tkinter", "requests", "PIL.ImageTk", "playwright.sync_api"):
        try:
            m = __import__(mod, fromlist=["x"])
            extra = f" (Tk {m.TkVersion})" if mod == "tkinter" else ""
            rec("PASS", f"import {mod}", "ok" + extra)
        except Exception as e:
            rec("FAIL", f"import {mod}", str(e))

    # ---- sound player (optional: without one the program uses the window bell)
    players = [c for c in ("paplay", "aplay", "play") if shutil.which(c)]
    rec("INFO", "sound player", ", ".join(players) if players else "none found - the window bell is used instead")

    # ---- the window itself
    if not want_gui:
        rec("SKIP", "window", "--no-gui")
    elif not os.environ.get("DISPLAY") and sys.platform.startswith("linux") and not os.environ.get("WAYLAND_DISPLAY"):
        rec("SKIP", "window", "no display available (set DISPLAY or use xvfb-run)")
    else:
        try:
            from . import app
            a = app.App()
            a.update_idletasks()
            a.update()
            rec("PASS", "window", f"'{a.title()}' opened, {a.winfo_width()}x{a.winfo_height()}")
            try:
                _exercise_feed(a, app, core)
                rec("PASS", "live feed", "Target Price column, Place-not-seen filter, Clear Live Feed and Settings work")
            except Exception as e:
                rec("FAIL", "live feed", f"{type(e).__name__}: {e}")
            a._close()
        except Exception as e:
            rec("FAIL", "window", f"{type(e).__name__}: {e}")

    # ---- bundled Playwright driver (a small Node.js program inside the download)
    node = cli = ""
    try:
        node, cli = _driver()
        out = subprocess.run([node, "--version"], capture_output=True, text=True, timeout=30)
        if out.returncode == 0:
            rec("PASS", "browser driver", f"node {out.stdout.strip()} runs")
        else:
            rec("FAIL", "browser driver", (out.stderr or out.stdout).strip()[:300])
    except Exception as e:
        rec("FAIL", "browser driver", f"{type(e).__name__}: {e}")

    # ---- a real browser, driven the same way the program drives it
    if want_browser and node:
        try:
            from playwright._impl._driver import get_driver_env
            env = {**os.environ, **get_driver_env()}
        except Exception:
            env = dict(os.environ)
        try:
            out = subprocess.run([node, cli, "install", "chromium"], env=env, capture_output=True,
                                 text=True, timeout=900)
            tail = (out.stdout + out.stderr).strip().splitlines()[-3:]
            rec("PASS" if out.returncode == 0 else "FAIL", "install chromium",
                " / ".join(t.strip() for t in tail)[:300])
        except Exception as e:
            rec("FAIL", "install chromium", f"{type(e).__name__}: {e}")
        try:
            from . import browser
            cfg = core.Config(Path(tmp) / "config.json")
            cfg["browser"].update(channel="chromium", headless=True)
            src = browser.BrowserSource(cfg)
            try:
                src._open()
                src._page.set_content("<title>selftest ok</title><p>hello</p>")
                rec("PASS", "browser", f"Chromium opened a page, title '{src._page.title()}'")
            finally:
                src.close()
        except Exception as e:
            rec("FAIL", "browser", f"{type(e).__name__}: {str(e)[:400]}")

    shutil.rmtree(tmp, ignore_errors=True)
    print("SELFTEST RESULT: " + ("OK" if not failed else "FAILED (" + ", ".join(failed) + ")"), flush=True)
    return 1 if failed else 0
