"""Error log for troubleshooting.

Everything the program does that matters (Start/Stop, the browser opening, every search result clicked, tabs
opened, pages read ...) is remembered in a short in-memory trail. When something goes wrong the trail is written,
together with the error and system details, to one text file you can upload:

    <data folder>/error_log.txt        (Settings > "Open error log" shows it)

The file never contains your contact address or other settings, only the browser settings that matter.
"""
from __future__ import annotations

import collections
import os
import platform
import sys
import threading
import time
import traceback
from pathlib import Path
from typing import Optional

TRAIL_SIZE = 250  # actions remembered
MAX_LOG_BYTES = 1_000_000  # the file is started over (old one kept as .1) when it grows past this

_trail: collections.deque = collections.deque(maxlen=TRAIL_SIZE)
_lock = threading.Lock()
_cfg_summary = None  # callable returning a dict of settings worth showing; set by the app


def _folder() -> Path:
    from .core import data_dir
    return data_dir()


def log_path() -> Path:
    return _folder() / "error_log.txt"


def action(msg: str) -> None:
    """Remember one thing that was just done (kept in memory, written only if an error follows)."""
    with _lock:
        _trail.append((time.time(), threading.current_thread().name, str(msg)))


def trail() -> list[str]:
    with _lock:
        items = list(_trail)
    return [f"{time.strftime('%H:%M:%S', time.localtime(t))} [{th}] {m}" for t, th, m in items]


def clear() -> None:
    with _lock:
        _trail.clear()


def set_settings_summary(fn) -> None:
    global _cfg_summary
    _cfg_summary = fn


def _versions() -> str:
    from . import core
    parts = [f"{core.FULL_NAME} v{core.VERSION} ({'packaged' if getattr(sys, 'frozen', False) else 'source'})",
             f"Python {platform.python_version()}", platform.platform()]
    try:
        from importlib.metadata import version
        parts.append("playwright " + version("playwright"))
    except Exception:
        pass
    return " | ".join(parts)


def write(what: str, exc: Optional[BaseException] = None, extra: Optional[dict] = None) -> Optional[Path]:
    """Append one report to error_log.txt: what happened, the traceback, details, and the actions before it."""
    try:
        lines = ["=" * 78, f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {what}", "-" * 78, _versions()]
        if exc is not None:
            tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)).rstrip()
            lines += ["", "ERROR:", tb]
        if extra:
            lines += [""] + [f"{k}: {v}" for k, v in extra.items()]
        if _cfg_summary:
            try:
                lines += ["", "SETTINGS:"] + [f"  {k}: {v}" for k, v in _cfg_summary().items()]
            except Exception:
                pass
        lines += ["", "WHAT HAPPENED BEFORE (oldest first):"] + ["  " + t for t in trail()] + [""]
        p = log_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        try:
            if p.exists() and p.stat().st_size > MAX_LOG_BYTES:
                p.replace(p.with_suffix(".txt.1"))
        except OSError:
            pass
        with open(p, "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        return p
    except Exception:  # logging must never be the thing that crashes the program
        return None


def install_hooks() -> None:
    """Log crashes that nobody catches (main thread and worker threads)."""
    prev_exc, prev_thread = sys.excepthook, getattr(threading, "excepthook", None)

    def on_exc(t, v, tb):
        v.__traceback__ = tb
        write("The program crashed (uncaught error)", v)
        prev_exc(t, v, tb)

    sys.excepthook = on_exc
    if prev_thread:
        def on_thread(args):
            if args.exc_value is not None:
                write(f"A background task crashed (thread {getattr(args.thread, 'name', '?')})", args.exc_value)
            prev_thread(args)
        threading.excepthook = on_thread


def open_in_viewer(path: Path) -> None:
    """Open a file with the system's default program."""
    try:
        if sys.platform.startswith("win"):
            os.startfile(str(path))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            import subprocess
            subprocess.Popen(["open", str(path)])
        else:
            import subprocess
            subprocess.Popen(["xdg-open", str(path)])
    except Exception:
        pass
