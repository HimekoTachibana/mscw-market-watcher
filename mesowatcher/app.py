"""MesoWatcher UI (Tkinter)."""
from __future__ import annotations

import json
import os
import queue
import sys
import threading
import time
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import messagebox, ttk

try:
    from PIL import Image, ImageTk
except ImportError:  # icons are optional
    Image = ImageTk = None

from . import browser, core, updater

COLS = [("item", "Item Name", 230), ("seller", "Seller", 110), ("channel", "Channel", 65),
        ("location", "Location", 170), ("price", "Price", 90), ("target", "Target Price", 95),
        ("listed", "Listed", 90),
        ("avg", "24h AVG", 90), ("disc", "Discount", 75)]
DURATIONS = ("15 minutes", "30 minutes", "1 hour", "2 hours", "3 hours", "6 hours")
ICON = 26
CHK = 16


def resource_path(rel: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return base / rel


class ItemPicker(ttk.Frame):
    """Type to search or pick from a dropdown. Free text is allowed too.
    Every row shows the item's icon to the left of its name."""

    ROWS = 9
    IGNORE = {"Down", "Up", "Return", "Escape", "Tab", "Shift_L", "Shift_R", "Control_L",
              "Control_R", "Alt_L", "Alt_R", "Left", "Right", "Home", "End"}

    def __init__(self, master, app: "App", width: int = 38, on_pick=None):
        super().__init__(master)
        self.app, self.on_pick = app, on_pick
        self.pop: tk.Toplevel | None = None
        self.tv: ttk.Treeview | None = None
        self._names: dict[str, str] = {}
        self.icon = ttk.Label(self, width=4, anchor="center", image=app.blank)
        self.icon.pack(side="left")
        self.var = tk.StringVar()
        self.entry = ttk.Entry(self, textvariable=self.var, width=width)
        self.entry.pack(side="left")
        self.btn = ttk.Button(self, text="▾", width=3, command=self.toggle)
        self.btn.pack(side="left", padx=(2, 0))
        self.entry.bind("<KeyRelease>", self._key_release)
        self.entry.bind("<Down>", self._to_list)
        self.entry.bind("<Escape>", lambda e: self.close())
        self.entry.bind("<Return>", self._enter)
        app.bind("<Button-1>", self._outside, add="+")

    # ---- public
    def get(self) -> str:
        return self.var.get().strip()

    def clear(self):
        self.var.set("")
        self._update_icon()
        self.close()

    def refresh_if_open(self):
        self._update_icon()
        if self.pop is not None and self.pop.winfo_viewable():
            self._fill(keep_selection=True)

    # ---- popup
    def toggle(self):
        if self.pop is not None and self.pop.winfo_viewable():
            self.close()
        else:
            self.show()
            self.entry.focus_set()

    def _build_pop(self):
        pop = tk.Toplevel(self)
        pop.withdraw()
        pop.overrideredirect(True)
        try:
            pop.attributes("-topmost", True)
        except tk.TclError:
            pass
        frame = ttk.Frame(pop, borderwidth=1, relief="solid")
        frame.pack(fill="both", expand=True)
        tv = ttk.Treeview(frame, columns=("meta",), show="tree", height=self.ROWS, selectmode="browse")
        tv.column("#0", width=330)
        tv.column("meta", width=110, anchor="e")
        sb = ttk.Scrollbar(frame, orient="vertical", command=tv.yview)
        tv.configure(yscrollcommand=sb.set)
        tv.pack(side="left", fill="both", expand=True)
        sb.pack(side="left", fill="y")
        tv.bind("<ButtonRelease-1>", self._click)
        tv.bind("<Return>", lambda e: self._pick_selected())
        tv.bind("<Escape>", lambda e: (self.close(), self.entry.focus_set()))
        tv.bind("<Key>", self._tv_key)
        self.pop, self.tv = pop, tv

    def show(self):
        if self.pop is None:
            self._build_pop()
        self._fill()
        self.update_idletasks()
        x, y = self.winfo_rootx(), self.entry.winfo_rooty() + self.entry.winfo_height()
        self.pop.geometry(f"+{x}+{y}")
        self.pop.deiconify()
        self.pop.lift()

    def close(self):
        if self.pop is not None:
            self.pop.withdraw()

    def _fill(self, keep_selection: bool = False):
        tv = self.tv
        sel = tv.selection()
        keep = sel[0] if (keep_selection and sel) else None
        tv.delete(*tv.get_children())
        self._names.clear()
        db = self.app.items
        if not db.items:
            tv.insert("", "end", iid="none", image=self.app.blank, values=("",),
                      text="Item list not loaded yet - Settings > Update item database")
            return
        res = db.search(self.var.get(), 60)
        if not res:
            tv.insert("", "end", iid="none", image=self.app.blank, values=("",),
                      text="No match - press Enter to use what you typed")
            return
        for n, (name, id8) in enumerate(res):
            iid = f"r{n}"
            self._names[iid] = name
            tv.insert("", "end", iid=iid, text=name, image=self.app.icon_or_blank(id8),
                      values=(db.meta_text(id8),))
        if keep and tv.exists(keep):
            tv.selection_set(keep)

    # ---- events
    def _key_release(self, e):
        if e.keysym in self.IGNORE:
            return
        self._update_icon()
        self.show()

    def _enter(self, _e):
        if self.pop is not None and self.pop.winfo_viewable() and self.tv.selection():
            self._pick_selected()
        else:
            self.close()
            if self.on_pick:
                self.on_pick(self.get())
        return "break"

    def _to_list(self, _e):
        if self.pop is None or not self.pop.winfo_viewable():
            self.show()
        kids = self.tv.get_children()
        if kids and kids[0] in self._names:
            self.tv.focus_set()
            self.tv.selection_set(kids[0])
            self.tv.focus(kids[0])
        return "break"

    def _tv_key(self, e):
        if e.keysym == "BackSpace":
            self.entry.focus_set()
            self.var.set(self.var.get()[:-1])
            self._update_icon()
            self._fill()
        elif len(e.char) == 1 and e.char.isprintable():
            self.entry.focus_set()
            self.entry.insert("end", e.char)
            self._update_icon()
            self._fill()

    def _click(self, e):
        iid = self.tv.identify_row(e.y)
        if iid in self._names:
            self._pick(iid)

    def _pick_selected(self):
        sel = self.tv.selection()
        if sel and sel[0] in self._names:
            self._pick(sel[0])

    def _pick(self, iid: str):
        self.var.set(self._names[iid])
        self.close()
        self.entry.focus_set()
        self.entry.icursor("end")
        self._update_icon()
        if self.on_pick:
            self.on_pick(self.get())

    def _outside(self, e):
        if self.pop is not None and self.pop.winfo_viewable() and e.widget not in (self.entry, self.btn):
            self.close()

    def _update_icon(self):
        id8 = self.app.items.id_for_name(self.var.get())
        ph = self.app.icon_or_blank(id8) if id8 else self.app.blank
        self.icon.configure(image=ph)
        self.icon.image = ph


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"{core.FULL_NAME} v{core.VERSION}")
        self.geometry("1120x780")
        self.cfg = core.Config()
        self.source = None  # a fresh source (and browser) is made on every Start
        self._last_poller: core.Poller | None = None
        self.watch = core.Watchlist(self.cfg)
        self.items = core.ItemDB(self.cfg)
        self.beeper = core.Beeper(self.cfg)
        self.poller: core.Poller | None = None
        self.q: queue.Queue = queue.Queue()
        self.listings: list[core.Listing] = core.prune_listings(core.load_listings(),
                                                                core.feed_retention(self.cfg))
        self.watch.alerted.update(l.key for l in self.listings)  # old listings must not beep again
        self._keys: dict[str, str] = {}
        self._combo: dict = {}
        self.blank = tk.PhotoImage(width=ICON, height=ICON)  # keeps names aligned until an icon loads
        self._photos: dict[str, object] = {}
        self._icons_dirty = False
        self._refreshing = False
        self._announce = False
        self.icon_store = core.IconStore(self.cfg, on_ready=lambda i: self.q.put(("icon", i)))
        self._box_off, self._box_on = self._make_checkbox(False), self._make_checkbox(True)
        self._build()
        self._render()
        self.after(200, self._drain)
        self.after(int((60 - time.time() % 60) * 1000) + 300, self._tick_minute)
        self.protocol("WM_DELETE_WINDOW", self._close)
        self.uq: queue.Queue = queue.Queue()  # messages from the update threads
        self._update_busy = False
        self._update_cancel = threading.Event()
        self._dl: dict = {}
        self.after(400, self._poll_updates)
        if self.cfg["update_check_on_start"] and getattr(sys, "frozen", False):
            self.after(6000, lambda: self.check_updates(manual=False))
        if not self.items.items or self.items.age_days > 7:
            self.after(600, self.refresh_items)

    def _make_checkbox(self, on: bool) -> tk.PhotoImage:
        im = tk.PhotoImage(width=CHK, height=CHK)
        edge, fill, tick = "#6b6b6b", "#ffffff", "#1f9d3a"
        for y in range(CHK):
            row = []
            for x in range(CHK):
                border = x in (0, CHK - 1) or y in (0, CHK - 1)
                row.append(edge if border else fill)
            im.put("{" + " ".join(row) + "}", to=(0, y))
        if on:
            pts = [(3, 8), (4, 9), (5, 10), (6, 11), (7, 10), (8, 9), (9, 8), (10, 7), (11, 6), (12, 5)]
            for x, y in pts:
                for dx, dy in ((0, 0), (0, 1)):
                    im.put(tick, to=(x, y + dy - 1, x + 1, y + dy))
        return im

    # ------------------------------------------------------------- icons
    def get_icon(self, id8: str | None):
        if not (Image and id8):
            return None
        ph = self._photos.get(id8)
        if ph:
            return ph
        p = self.icon_store.path(id8)  # None => queued, will arrive via the "icon" message
        if not p:
            return None
        try:
            im = Image.open(p).convert("RGBA")
            im.thumbnail((ICON, ICON))
            canvas = Image.new("RGBA", (ICON, ICON), (0, 0, 0, 0))
            canvas.paste(im, ((ICON - im.width) // 2, (ICON - im.height) // 2))
            ph = ImageTk.PhotoImage(canvas)
        except Exception:
            try:
                p.unlink()
            except OSError:
                pass
            return None
        self._photos[id8] = ph
        return ph

    def icon_or_blank(self, id8: str | None):
        return self.get_icon(id8) or self.blank

    def _id_for(self, name: str, item_id: str = "") -> str | None:
        id8 = self.items.id_for_name(name)
        if id8:
            return id8
        if item_id and item_id.isdigit():
            cand = item_id.zfill(8)
            if cand in self.items.items:
                return cand
        return None

    # ------------------------------------------------------------- layout
    def _build(self):
        top = ttk.Frame(self, padding=6)
        top.pack(fill="x")
        self.btn = ttk.Button(top, text="Start", command=self.toggle)
        self.btn.pack(side="left")
        ttk.Label(top, foreground="#555", text="Pauses: random 0.5-5 s").pack(side="left", padx=(12, 2))
        self.show_all = tk.BooleanVar(value=self.cfg["show_all"])
        ttk.Checkbutton(top, text="Show all listings", variable=self.show_all,
                        command=self._render).pack(side="left", padx=12)
        self.only_loc = tk.BooleanVar(value=self.cfg["only_with_location"])
        ttk.Checkbutton(top, text="Only listings with Channel and Location", variable=self.only_loc,
                        command=self._render).pack(side="left")
        self.items_btn = ttk.Button(top, command=self.choose_feed_items)
        self.items_btn.pack(side="left", padx=12)
        self._items_label()
        ttk.Button(top, text="Settings", command=self.open_settings).pack(side="right")
        ttk.Button(top, text="Clear Live Feed", command=self.clear_feed).pack(side="right", padx=6)

        al = ttk.Frame(self, padding=(6, 0))
        al.pack(fill="x")
        self.muted = tk.BooleanVar(value=self.cfg["muted"])
        ttk.Checkbutton(al, text="Mute", variable=self.muted, command=self._save_audio).pack(side="left")
        ttk.Label(al, text="Volume").pack(side="left", padx=(12, 2))
        self.vol = tk.IntVar(value=self.cfg["volume"])
        ttk.Scale(al, from_=0, to=100, variable=self.vol, length=160,
                  command=lambda _=None: self._save_audio()).pack(side="left")
        ttk.Button(al, text="Test sound", command=self.test_sound).pack(side="left", padx=10)

        self.status = tk.StringVar(value="Stopped. Add items to the watchlist, then press Start.")
        ttk.Label(self, textvariable=self.status, relief="sunken", anchor="w").pack(fill="x", side="bottom")

        style = ttk.Style()
        style.configure("Treeview", rowheight=ICON + 4)
        # Two panes with a draggable divider: drag the bar between them up or down to resize.
        self.paned = ttk.PanedWindow(self, orient="vertical")
        self.paned.pack(fill="both", expand=True, padx=6, pady=4)
        self._build_feed(self.paned)
        self._build_watchlist(self.paned)
        self.after(300, self._restore_pane)

    def _build_feed(self, paned):
        feed = ttk.LabelFrame(paned, text="Live Feed  (click a heading to sort; drag a heading to move the "
                                          "column; right-click a row to copy the seller)", padding=4)
        paned.add(feed, weight=3)
        feed.rowconfigure(0, weight=1)
        feed.columnconfigure(0, weight=1)
        self.tree = ttk.Treeview(feed, columns=[c[0] for c in COLS], show="tree headings", selectmode="extended")
        self.tree.column("#0", width=72, minwidth=60, stretch=False, anchor="w")
        for cid, title, w in COLS:
            self.tree.column(cid, width=int(self.cfg["feed_widths"].get(cid, w)), minwidth=40,
                             anchor="e" if cid in ("price", "target", "avg", "disc", "listed") else "w")
        self.tree["displaycolumns"] = self._column_order()
        self.tree.tag_configure("deal", background="#d9f2d9")
        self.tree.tag_configure("sold", background="#e6e6e6", foreground="#9a9a9a")
        vs = ttk.Scrollbar(feed, orient="vertical", command=self.tree.yview)
        hs = ttk.Scrollbar(feed, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vs.set, xscrollcommand=hs.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vs.grid(row=0, column=1, sticky="ns")
        hs.grid(row=1, column=0, sticky="ew")
        self._update_headings()
        self.tree.bind("<ButtonPress-1>", self._feed_press, add="+")
        self.tree.bind("<B1-Motion>", self._feed_motion, add="+")
        self.tree.bind("<ButtonRelease-1>", self._feed_release, add="+")
        self.tree.bind("<Double-1>", self._feed_double, add="+")
        self.tree.bind("<Button-3>", self._feed_menu)
        self.tree.bind("<Button-2>", self._feed_menu)  # macOS
        self.tree.bind("<Control-c>", lambda e: self.copy_seller())
        self.tree.bind("<space>", lambda e: (self.toggle_sold(self.tree.selection()), "break")[1])
        self.menu = tk.Menu(self, tearoff=0)
        self.menu.add_command(label="Copy seller name", command=self.copy_seller)
        self.menu.add_command(label="Mark as sold / checked", command=lambda: self.toggle_sold(self.tree.selection()))
        self._drag = None

    def _build_watchlist(self, paned):
        wl = ttk.LabelFrame(paned, text="Watchlist  (alert at or under the max price; double-click a max price to edit it; "
                                  "select an item and press Delete to remove it)", padding=6)
        paned.add(wl, weight=1)
        row = ttk.Frame(wl)
        row.pack(fill="x")
        ttk.Label(row, text="Item:").pack(side="left")
        self.picker = ItemPicker(row, self, on_pick=lambda _n: self.w_price.focus_set())
        self.picker.pack(side="left", padx=4)
        ttk.Label(row, text="Max price:").pack(side="left", padx=(8, 0))
        self.w_price = ttk.Entry(row, width=12)
        self.w_price.pack(side="left", padx=4)
        self.w_price.bind("<Return>", lambda e: self.add_watch())
        ttk.Button(row, text="Watch", command=self.add_watch).pack(side="left")
        ttk.Button(row, text="Remove selected", command=self.remove_watch).pack(side="right")

        dur = ttk.Frame(wl)
        dur.pack(fill="x", pady=(6, 0))
        ttk.Label(dur, text="Show listings from the last:").pack(side="left")
        self.duration = tk.StringVar(value=core.fmt_duration(self.cfg["browser"]["lookback_min"]))
        self.dur_box = ttk.Combobox(dur, textvariable=self.duration, width=18, values=DURATIONS)
        self.dur_box.pack(side="left", padx=6)
        self.dur_box.bind("<<ComboboxSelected>>", lambda e: self.apply_duration())
        self.dur_box.bind("<Return>", lambda e: self.apply_duration())
        self.dur_box.bind("<FocusOut>", lambda e: self.apply_duration())
        ttk.Label(dur, foreground="#555", text="(or type your own, e.g. 45 min or 1h30)").pack(side="left")

        box = ttk.Frame(wl)
        box.pack(fill="both", expand=True, pady=(6, 0))
        box.rowconfigure(0, weight=1)
        box.columnconfigure(0, weight=1)
        self.wl_tree = ttk.Treeview(box, columns=("max",), show="tree headings", height=3, selectmode="extended")
        self.wl_tree.heading("#0", text="Item")
        self.wl_tree.heading("max", text="Max price")
        self.wl_tree.column("#0", width=420)
        self.wl_tree.column("max", width=110, anchor="e")
        sb = ttk.Scrollbar(box, orient="vertical", command=self.wl_tree.yview)
        self.wl_tree.configure(yscrollcommand=sb.set)
        self.wl_tree.grid(row=0, column=0, sticky="nsew")
        sb.grid(row=0, column=1, sticky="ns")
        self.wl_tree.bind("<Delete>", lambda e: self.remove_watch())
        self.wl_tree.bind("<Double-1>", self._wl_edit_click)
        self.wl_tree.bind("<F2>", self._wl_edit_key)
        self._edit = None
        self._render_watchlist()

    def _restore_pane(self):
        try:
            pos = int(self.cfg["feed_pane"])
            if pos > 80 and pos < self.paned.winfo_height() - 80:
                self.paned.sashpos(0, pos)
        except (tk.TclError, ValueError):
            pass

    # ---- feed columns: order, sorting, drag to reorder
    def _column_order(self) -> list[str]:
        ids = [c[0] for c in COLS]
        return core.merge_column_order(list(self.cfg["feed_columns"]), ids)

    def _display_cols(self) -> list[str]:
        dc = list(self.tree["displaycolumns"])
        return [c[0] for c in COLS] if dc == ["#all"] else dc

    def _col_at(self, x: int) -> str | None:
        """Column id under x ('#0' for the Sold column), or None."""
        ident = self.tree.identify_column(x)
        if not ident:
            return None
        n = int(ident[1:])
        if n == 0:
            return "#0"
        cols = self._display_cols()
        return cols[n - 1] if 0 < n <= len(cols) else None

    def _update_headings(self):
        sort = self.cfg["feed_sort"]
        titles = {c[0]: c[1] for c in COLS}
        titles["#0"] = "Sold"
        for cid, t in titles.items():
            arrow = (" ▼" if sort.get("desc") else " ▲") if sort.get("col") == ("sold" if cid == "#0" else cid) else ""
            self.tree.heading(cid, text=t + arrow)

    def _feed_press(self, e):
        self._drag = None
        self._chk = None
        region = self.tree.identify_region(e.x, e.y)
        if region in ("tree", "cell") and self._col_at(e.x) == "#0":
            row = self.tree.identify_row(e.y)
            if row:
                self._chk = row  # the Sold checkbox column: toggled on release
        if region == "heading":
            col = self._col_at(e.x)
            if col:
                self._drag = {"col": col, "x": e.x, "moved": False}

    def _feed_motion(self, e):
        d = self._drag
        if d and abs(e.x - d["x"]) > 6:
            d["moved"] = True
            self.tree.configure(cursor="fleur")

    def _feed_release(self, e):
        d, self._drag = self._drag, None
        self.tree.configure(cursor="")
        chk, self._chk = getattr(self, "_chk", None), None
        if chk and chk == self.tree.identify_row(e.y):
            self.toggle_sold([chk])
            return
        if not d:
            return
        if not d["moved"]:
            self.sort_by("sold" if d["col"] == "#0" else d["col"])
            return
        target = self._col_at(e.x)
        src = d["col"]
        if src == "#0" or not target or target == "#0" or target == src:
            return  # the Sold column always stays far left
        cols = self._display_cols()
        cols.remove(src)
        cols.insert(cols.index(target) + (1 if self._col_index(src) < self._col_index(target) else 0), src)
        self.tree["displaycolumns"] = cols
        self.cfg["feed_columns"] = cols
        self.cfg.save()

    def _col_index(self, cid: str) -> int:
        return self._display_cols().index(cid)

    def sort_by(self, col: str):
        s = self.cfg["feed_sort"]
        if s.get("col") == col:
            s["desc"] = not s.get("desc", False)
        else:
            s["col"], s["desc"] = col, False
        self.cfg.save()
        self._update_headings()
        self._render()

    def _sort_value(self, col: str, l: core.Listing, sold: set):
        if col == "item":
            return l.item_name.lower()
        if col == "seller":
            return (l.seller or "").lower() or None
        if col == "channel":
            return int(l.channel) if (l.channel or "").isdigit() else None
        if col == "location":
            return (l.location or "").lower() or None
        if col == "price":
            return l.price
        if col == "target":
            return self.watch.target(l.item_name)[1]  # blank (not watched, or any price) sorts last
        if col == "listed":
            return l.age_now()
        if col == "avg":
            return l.avg24h or None
        if col == "disc":
            return l.discount
        if col == "sold":
            return l.key in sold
        return 0

    def _sorted(self, rows: list[core.Listing]) -> list[core.Listing]:
        s = self.cfg["feed_sort"]
        col, desc = s.get("col", "listed"), bool(s.get("desc"))
        sold = set(self.cfg["sold"])
        have = [(self._sort_value(col, l, sold), l) for l in rows]
        known = sorted((t for t in have if t[0] is not None), key=lambda t: t[0], reverse=desc)
        missing = [t for t in have if t[0] is None]  # blanks always go to the bottom
        return [l for _, l in known + missing]

    # ---- feed actions: sold box, copy seller
    def _feed_double(self, e):
        self._feed_press(e)  # Tk runs only the most specific binding, so a quick second click lands here
        if self.tree.identify_region(e.x, e.y) == "cell" and self._col_at(e.x) == "seller":
            self.copy_seller([self.tree.identify_row(e.y)])

    def toggle_sold(self, iids):
        sold = set(self.cfg["sold"])
        for iid in iids:
            key = self._keys.get(iid)
            if key is None:
                continue
            sold.symmetric_difference_update({key})
        self.cfg["sold"] = sorted(sold)
        self.cfg.save()
        self._render()

    def _feed_menu(self, e):
        iid = self.tree.identify_row(e.y)
        if iid:
            if iid not in self.tree.selection():
                self.tree.selection_set(iid)
            self.menu.tk_popup(e.x_root, e.y_root)

    def copy_seller(self, iids=None):
        iids = list(iids if iids is not None else self.tree.selection())
        names = []
        for iid in iids:
            n = self.tree.set(iid, "seller") if iid else ""
            if n and n != "-" and n not in names:
                names.append(n)
        if not names:
            return "break"
        text = "\n".join(names) if len(names) > 1 else names[0]
        self.clipboard_clear()
        self.clipboard_append(text)
        self.update_idletasks()
        self.status.set(f"Copied seller '{text}' - paste it in game.")
        return "break"

    # ---- watchlist: duration, inline max-price edit
    def apply_duration(self):
        mins = core.parse_duration(self.duration.get())
        if mins is None:
            self.duration.set(core.fmt_duration(self.cfg["browser"]["lookback_min"]))
            return
        self.duration.set(core.fmt_duration(mins))
        if mins != self.cfg["browser"]["lookback_min"]:
            self.cfg["browser"]["lookback_min"] = mins
            self.cfg.save()
            self._render()

    def _wl_edit_click(self, e):
        if self.wl_tree.identify_region(e.x, e.y) == "cell" and self.wl_tree.identify_column(e.x) == "#1":
            self._wl_edit(self.wl_tree.identify_row(e.y))

    def _wl_edit_key(self, _e):
        sel = self.wl_tree.selection()
        if sel:
            self._wl_edit(sel[0])

    def _wl_edit(self, iid: str):
        self._wl_cancel()
        box = self.wl_tree.bbox(iid, "max") if iid else None
        if not box:
            return
        x, y, w, h = box
        cur = self.wl_tree.set(iid, "max")
        ent = ttk.Entry(self.wl_tree, justify="right")
        ent.insert(0, "" if cur == "any" else cur.replace(",", ""))
        ent.select_range(0, "end")
        ent.place(x=x, y=y, width=max(w, 90), height=h)
        ent.focus_set()
        ent.bind("<Return>", lambda e: self._wl_commit())
        ent.bind("<Escape>", lambda e: self._wl_cancel())
        ent.bind("<FocusOut>", lambda e: self._wl_commit())
        self._edit = (iid, ent)

    def _wl_cancel(self):
        if self._edit:
            _, ent = self._edit
            self._edit = None
            ent.destroy()

    def _wl_commit(self):
        if not self._edit:
            return
        iid, ent = self._edit
        txt = ent.get().strip().lower()
        if txt in ("", "any", "none"):
            val = None
        else:
            num = core.parse_number(txt)
            if num is None or num < 0:
                messagebox.showerror("Max price", "Enter a whole number such as 50000, 50k or 1.5m "
                                                  "(empty = any price).")
                ent.focus_set()
                return
            val = int(num)
        self._edit = None
        ent.destroy()
        name = self.wl_tree.item(iid, "text")
        self.watch.add(name, val)
        self.cfg.save()
        self._render_watchlist()
        self._render()

    # ------------------------------------------------------------ actions
    def _items_label(self):
        n = len(self.cfg["feed_items"])
        self.items_btn.config(text="Items: all" if not n else f"Items: {n} chosen")

    def choose_feed_items(self):
        """Pick which items the Live Feed shows (tick one or several; nothing ticked = every item)."""
        names = {l.item_name for l in self.listings} | {e["name"] for e in self.watch.entries if e.get("name")} \
            | set(self.cfg["feed_items"])
        names = sorted(names, key=str.lower)
        w = tk.Toplevel(self)
        w.title("Live Feed - choose items")
        w.transient(self)
        w.geometry("380x420")
        ttk.Label(w, padding=8, wraplength=350, text="Tick the items to show in the Live Feed. "
                  "Nothing ticked shows every item.").pack(anchor="w")
        box = ttk.Frame(w)
        box.pack(fill="both", expand=True, padx=8)
        cv = tk.Canvas(box, highlightthickness=0)
        sb = ttk.Scrollbar(box, orient="vertical", command=cv.yview)
        inner = ttk.Frame(cv)
        inner.bind("<Configure>", lambda e: cv.configure(scrollregion=cv.bbox("all")))
        cv.create_window((0, 0), window=inner, anchor="nw")
        cv.configure(yscrollcommand=sb.set)
        cv.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        chosen = {n.lower() for n in self.cfg["feed_items"]}
        vars_ = {n: tk.BooleanVar(value=n.lower() in chosen) for n in names}
        for n in names:
            ttk.Checkbutton(inner, text=n, variable=vars_[n]).pack(anchor="w")
        if not names:
            ttk.Label(inner, text="No items yet - add items to the Watchlist or wait for listings.").pack(anchor="w")
        bar = ttk.Frame(w, padding=8)
        bar.pack(fill="x")

        def setall(v):
            for b in vars_.values():
                b.set(v)

        def ok():
            self.cfg["feed_items"] = [n for n in names if vars_[n].get()]
            self.cfg.save()
            self._items_label()
            self._render()
            w.destroy()
        ttk.Button(bar, text="Tick all", command=lambda: setall(True)).pack(side="left")
        ttk.Button(bar, text="Clear ticks", command=lambda: setall(False)).pack(side="left", padx=6)
        ttk.Button(bar, text="Cancel", command=w.destroy).pack(side="right")
        ttk.Button(bar, text="OK", command=ok).pack(side="right", padx=6)

    def clear_feed(self):
        """Delete every listing from the Live Feed. The same shops, still on the site, are not added
        again on the next pass; listings that are new appear as usual."""
        if self.listings and not messagebox.askyesno(
                "Clear Live Feed", f"Delete all {len(self.listings)} listings from the Live Feed?\n\n"
                "The same shops will not be added again; new listings will appear as usual."):
            return
        self.cfg["feed_dismissed"] = core.dismiss_all(self.listings, self.cfg["feed_dismissed"])
        self.listings = []
        self.cfg["sold"] = []  # their rows are gone
        self.cfg.save()
        core.save_listings(self.listings)
        self._render()
        self.status.set("Live Feed cleared.")

    def _save_audio(self):
        self.cfg["muted"] = self.muted.get()
        self.cfg["volume"] = int(self.vol.get())
        self.cfg.save()

    def test_sound(self):
        if not self.beeper.play(force=True):
            self.bell()

    def add_watch(self):
        name = self.picker.get()
        txt = self.w_price.get().replace(",", "").strip()
        num = core.parse_number(txt) if txt else None
        if txt and num is None:
            messagebox.showerror("Max price", "Max price must be a number such as 50000 or 50k (or empty for any price).")
            return
        mp = int(num) if num is not None else None
        if not name:
            return
        self.watch.add(name, mp)
        self.cfg.save()
        self.picker.clear()
        self.w_price.delete(0, "end")
        self._render_watchlist()
        self._render()
        self.picker.entry.focus_set()

    def remove_watch(self):
        self._wl_cancel()
        sel = self.wl_tree.selection()
        for iid in sel:
            self.watch.remove(self.wl_tree.item(iid, "text"))
        if sel:
            self.cfg.save()
            self._render_watchlist()
            self._render()
        return "break"

    def _render_watchlist(self):
        self._wl_cancel()
        self.wl_tree.delete(*self.wl_tree.get_children())
        for e in self.watch.entries:
            mp = e.get("max_price")
            self.wl_tree.insert("", "end", text=e["name"], image=self.icon_or_blank(self._id_for(e["name"])),
                                values=(f"{mp:,}" if mp is not None else "any",))

    def toggle(self):
        if self.poller and self.poller.is_alive():
            self.poller.stop()
            self.poller = None
            self.btn.config(text="Start")
            self.status.set("Stopped.")
            return
        if self._last_poller and self._last_poller.is_alive():
            self.status.set("Still closing the previous browser - try again in a few seconds.")
            return
        self.source = self._make_source()
        self.cfg["show_all"] = self.show_all.get()
        self.cfg.save()
        if not self.watch.entries and self.cfg["source_mode"] == "browser":
            self.status.set("The watchlist is empty - add an item first; each watched item is opened on the site.")
            return
        self.apply_duration()
        self.poller = self._last_poller = core.Poller(self.source, self.cfg,
                                  lambda ls: self.q.put(("listings", ls)),
                                  lambda s: self.q.put(("status", s)))
        self.poller.start()
        self.btn.config(text="Stop")

    def _make_source(self):
        if self.cfg["source_mode"] == "api":
            return core.ListingSource(self.cfg)
        src = browser.BrowserSource(self.cfg)
        src.items = self.items  # lets the item icon be checked against the item database
        return src

    def _show_text(self, title: str, text: str, parent=None, size: str = "720x420"):
        r = tk.Toplevel(parent or self)
        r.title(title)
        r.geometry(size)
        t = tk.Text(r, wrap="word", padx=10, pady=10, font=("Consolas" if sys.platform == "win32" else "Courier", 10))
        t.insert("1.0", text)
        t.config(state="disabled")
        t.pack(fill="both", expand=True)

    def refresh_items(self, announce: bool = False):
        if self._refreshing:
            return
        self._refreshing, self._announce = True, announce
        self.status.set("Updating item list from OSMS Data Explorer and MeowDB...")

        def work():
            try:
                rep = self.items.update()
            except Exception as e:  # never let a thread die silently
                rep = [f"Item refresh failed: {e}"]
            self.q.put(("items", rep))
        threading.Thread(target=work, daemon=True).start()

    # ------------------------------------------------------- thread bridge
    def _drain(self):
        try:
            while True:
                kind, payload = self.q.get_nowait()
                if kind == "status":
                    self.status.set(payload)
                    if payload.startswith("PAUSED"):
                        self.btn.config(text="Start")
                        messagebox.showwarning("Polling paused", payload)
                elif kind == "icon":
                    self._icons_dirty = True
                elif kind == "test":
                    self.status.set("Test finished.")
                    self._show_text("Test result", "\n".join(payload), size="780x420")
                elif kind == "items":
                    self._refreshing = False
                    n, u = len(self.items.items), self.items.meta.get("unique", 0)
                    self.status.set(f"Item list ready: {n:,} items ({u:,} unique names)." if n
                                    else "Item list could not be built - see Settings > Cross-check report.")
                    self.picker.refresh_if_open()
                    self._render_watchlist()
                    self._render()
                    if self._announce:
                        messagebox.showinfo("Item database", "\n\n".join(payload)[:1800])
                else:
                    gone = self.cfg["feed_dismissed"]  # listings removed with "Clear Live Feed" stay gone
                    payload = [l for l in payload if not core.is_dismissed(l, gone)]
                    self.listings = core.prune_listings(core.merge_listings(self.listings, payload),
                                                        core.feed_retention(self.cfg))
                    sold = set(self.cfg["sold"])
                    fresh = [l for l in self.watch.new_matches(payload) if l.key not in sold]
                    core.save_listings(self.listings)
                    self._render()
                    if fresh and not self.cfg["muted"]:
                        if not self.beeper.play():
                            self.bell()
        except queue.Empty:
            pass
        if self._icons_dirty:  # icons arrived: redraw once per tick, not once per icon
            self._icons_dirty = False
            self._combo.clear()
            self.picker.refresh_if_open()
            self._render_watchlist()
            self._render()
        self.after(250, self._drain)

    def _tick_minute(self):
        """Keep the Listed column live: redraw (and drop listings that aged out) every minute."""
        try:
            self._render()
        finally:
            self.after(int((60 - time.time() % 60) * 1000) + 300, self._tick_minute)

    def _combo_image(self, id8: str | None, sold: bool):
        """Sold checkbox + item icon in the first column."""
        k = (id8, sold)
        im = self._combo.get(k)
        if im is None:
            im = tk.PhotoImage(width=CHK + ICON + 8, height=ICON)
            box = self._box_on if sold else self._box_off
            im.tk.call(im, "copy", box, "-to", 2, (ICON - CHK) // 2)
            im.tk.call(im, "copy", self.icon_or_blank(id8), "-to", CHK + 6, 0)
            self._combo[k] = im
        return im

    def _render(self):
        self.cfg["show_all"] = self.show_all.get()
        self.cfg["only_with_location"] = self.only_loc.get()
        keep = {self._keys.get(i) for i in self.tree.selection()}
        top = self.tree.yview()[0]
        self.tree.delete(*self.tree.get_children())
        self._keys = {}
        sold = set(self.cfg["sold"])
        self.listings = core.prune_listings(self.listings, core.feed_retention(self.cfg))
        rows = [l for l in self.listings if self.show_all.get() or self.watch.matches(l)]
        rows = core.feed_item_filter(rows, self.cfg["feed_items"])
        if self.only_loc.get():
            rows = [l for l in rows if core.has_place(l.channel, l.location)]  # "Place not seen" is not a place
        reselect = []
        for n, l in enumerate(self._sorted(rows)):
            d = l.discount
            watched, tmax = self.watch.target(l.item_name)
            target = "-" if not watched else (f"{tmax:,}" if tmax is not None else "any")
            vals = (l.item_name, l.seller or "-", l.channel or "-", l.location or "-", f"{l.price:,}", target,
                    core.fmt_age(l.age_now()) if l.age_min is not None else (l.listed or "-"),
                    f"{l.avg24h:,.0f}" if l.avg24h else "-", f"{d:.1f}%" if d is not None else "-")
            is_sold = l.key in sold
            tags = ("sold",) if is_sold else (("deal",) if self.watch.matches(l) else ())
            iid = f"r{n}"
            self._keys[iid] = l.key
            self.tree.insert("", "end", iid=iid, text="", values=vals, tags=tags,
                             image=self._combo_image(self._id_for(l.item_name, l.item_id), is_sold))
            if l.key in keep:
                reselect.append(iid)
        if reselect:
            self.tree.selection_set(reselect)
        self.tree.yview_moveto(top)

    # ------------------------------------------------------------ settings
    def open_settings(self):
        w = tk.Toplevel(self)
        w.title("Settings")
        w.geometry("720x640")
        w.minsize(680, 560)
        bar = ttk.Frame(w, padding=(10, 6))
        bar.pack(side="bottom", fill="x")  # packed first so it is never clipped
        nb = ttk.Notebook(w)
        nb.pack(fill="both", expand=True, padx=8, pady=(8, 0))

        def tab(title):
            f = ttk.Frame(nb, padding=10)
            nb.add(f, text=title)
            return f

        def field(f, label, value, height=1, width=None):
            ttk.Label(f, text=label).pack(anchor="w", pady=(6, 0))
            if height == 1:
                v = tk.StringVar(value=str(value))
                ttk.Entry(f, textvariable=v, width=width or 60).pack(anchor="w", fill="x" if not width else None)
                return lambda: v.get()
            t = tk.Text(f, height=height, wrap="word")
            t.insert("1.0", value)
            t.pack(fill="x")
            return lambda: t.get("1.0", "end").strip()

        bc = self.cfg["browser"]
        # ---- tab 1: listings (browser)
        f1 = tab("Listings (browser)")
        ttk.Label(f1, foreground="#555", wraplength=650, text=(
            "MesoWatcher opens the site in a normal browser, filters for each watched item, clicks it, "
            "opens the Newest list and reads seller, channel, location, price and time since listing. "
            "It pauses between clicks and stops if Cloudflare shows a check.")).pack(anchor="w")
        g_start = field(f1, "Start page", bc["start_url"])
        ttk.Label(f1, text="Browser").pack(anchor="w", pady=(6, 0))
        g_chan = tk.StringVar(value=bc["channel"] or "chromium")
        ttk.Combobox(f1, textvariable=g_chan, values=("msedge", "chrome", "chromium"), width=14,
                     state="readonly").pack(anchor="w")
        show_win = tk.BooleanVar(value=not bc["headless"])
        ttk.Checkbutton(f1, text="Show the browser window (turn on to complete a Cloudflare check yourself)",
                        variable=show_win).pack(anchor="w", pady=(8, 0))
        g_dmin = field(f1, "Random pause between actions - shortest (ms, minimum 500)", self.cfg["delay_min_ms"], width=10)
        g_dmax = field(f1, "Random pause between actions - longest (ms)", self.cfg["delay_max_ms"], width=10)
        ttk.Label(f1, foreground="#555", text="How far back to look is set in the main window (Watchlist > "
                                              "Show listings from the last).").pack(anchor="w", pady=(6, 0))
        g_max = field(f1, "Safety cap: most listings read per item", bc["listing_cap"], width=10)
        g_tries = field(f1, "Search results to try (clicked one by one until the right-hand panel shows the item)",
                        bc.get("max_results_tried", browser.MAX_RESULTS_TRIED), width=10)
        adv = {k: bc[k] for k in ("filter_placeholder", "item_selector", "row_selector", "newest_label",
                                  "forsale_label", "open_labels", "page_timeout_ms", "challenge_wait_s")}
        g_adv = field(f1, "Advanced: text the site shows (change only if the site changes), JSON",
                      json.dumps(adv, indent=1), 7)
        first = self.watch.entries[0]["name"] if self.watch.entries else "Selective 5-slot Coupon"
        g_test = field(f1, "Item to use for Test", first)

        # ---- tab 2: item list
        f2 = tab("Item list")
        g_osms = field(f2, "OSMS Data Explorer data folder", self.cfg["osms_base"])
        g_meow = field(f2, "MeowDB item index page", self.cfg["meowdb_url"])
        meow_on = tk.BooleanVar(value=self.cfg["meowdb_enabled"])
        ttk.Checkbutton(f2, text="Cross-reference item names with MeowDB", variable=meow_on).pack(anchor="w", pady=(8, 0))
        add_on = tk.BooleanVar(value=self.cfg["meowdb_add_missing"])
        ttk.Checkbutton(f2, text="Add items found only on MeowDB (name only, no icon)",
                        variable=add_on).pack(anchor="w")
        ttk.Label(f2, foreground="#555", wraplength=650, text=(
            "Item data: OSMS Data Explorer (MIT license) and NiaMeowDB (meowdb.com). MeowDB data stays on "
            "this computer and is not redistributed. Game names and icons belong to their rights holders."
        )).pack(anchor="w", pady=10)

        # ---- tab 3: general
        f3 = tab("General")
        g_contact = field(f3, "Contact (email/Discord), sent in the User-Agent of item-list downloads", self.cfg["contact"])
        g_keep = field(f3, "Delete Live Feed listings older than (hours; 0 = use 'Show listings from the last')",
                       f"{self.cfg['feed_max_age_hours']:g}", width=10)
        ttk.Label(f3, foreground="#555", wraplength=650, text=(
            "Example: 6 deletes a listing from the Live Feed once it is more than 6 hours old (the clock "
            "keeps running while the program is closed). The 'Show listings from the last' box in the main "
            "window still decides how far back the site is read.")).pack(anchor="w", pady=(2, 0))
        ttk.Label(f3, text=f"Installed version: v{core.VERSION}").pack(anchor="w", pady=(14, 0))
        upd_on = tk.BooleanVar(value=self.cfg["update_check_on_start"])
        ttk.Checkbutton(f3, text="Check for a new release when the program starts", variable=upd_on).pack(anchor="w")

        def apply() -> bool:
            try:
                dmin = max(int(g_dmin()), 500)
                dmax = max(int(g_dmax()), dmin)
                mx = max(int(g_max()), 1)
                tries = max(int(g_tries()), 1)
                keep_h = float(g_keep().strip() or 0)
                if keep_h < 0:
                    raise ValueError("Delete listings older than: enter hours, 0 or more")
                extra = json.loads(g_adv() or "{}")
                if not isinstance(extra, dict):
                    raise ValueError("Advanced must be a JSON object")
            except ValueError as e:
                messagebox.showerror("Invalid setting", f"Please check the numbers and the Advanced JSON.\n\n{e}", parent=w)
                return False
            bc.update(extra)
            bc.update(start_url=g_start().strip(), channel=g_chan.get(), headless=not show_win.get(),
                      listing_cap=mx, max_results_tried=tries)
            self.cfg["delay_min_ms"], self.cfg["delay_max_ms"] = dmin, dmax
            self.cfg["osms_base"] = g_osms().strip()
            self.cfg["meowdb_url"] = g_meow().strip()
            self.cfg["meowdb_enabled"] = meow_on.get()
            self.cfg["meowdb_add_missing"] = add_on.get()
            self.cfg["contact"] = g_contact().strip()
            self.cfg["feed_max_age_hours"] = keep_h
            self.cfg["update_check_on_start"] = upd_on.get()
            self.cfg.save()
            return True

        def test():
            if not apply():
                return
            if self.poller and self.poller.is_alive():
                messagebox.showinfo("Test", "Press Stop on the main window first; the test needs the browser.", parent=w)
                return
            name = g_test().strip() or "Selective 5-slot Coupon"
            snap = core.data_dir() / "page_snapshot.html"
            self.status.set(f"Testing with '{name}' - a browser opens briefly...")

            def work():
                src = browser.BrowserSource(self.cfg)
                src.items = self.items
                try:
                    log = src.diagnose(name, snapshot=snap)
                except Exception as e:
                    log = [f"FAIL {e}"]
                finally:
                    src.close()
                self.q.put(("test", log))
            threading.Thread(target=work, daemon=True).start()

        def refresh():
            if apply():
                self.refresh_items(announce=True)

        def report():
            self._show_text("Item cross-check report", "\n\n".join(self.items.report) or
                            "No report yet - click Update item database.", parent=w)

        ttk.Button(bar, text="Save", command=lambda: apply() and w.destroy()).pack(side="left")
        ttk.Button(bar, text="Test & save page snapshot", command=test).pack(side="left", padx=6)
        ttk.Button(bar, text="Update item database", command=refresh).pack(side="left")
        ttk.Button(bar, text="Cross-check report", command=report).pack(side="left", padx=6)
        ttk.Button(bar, text="Changelog", command=self.show_changelog).pack(side="right")
        ttk.Button(bar, text="Check for updates", command=lambda: self.check_updates(manual=True, parent=w)
                   ).pack(side="right", padx=6)

    # ------------------------------------------------------------ updates
    def check_updates(self, manual: bool = True, parent=None):
        """Ask GitHub for the latest release. manual=True (button) always answers; False (startup) is silent."""
        if self._update_busy:
            if manual:
                messagebox.showinfo("Update", "An update check or download is already running.",
                                    parent=self._ok_parent(parent))
            return
        self._update_busy = True
        if manual:
            self.status.set("Checking for updates...")
        repo = self.cfg["update_repo"]

        def work():
            try:
                self.uq.put(("checked", manual, parent, updater.check(repo)))
            except updater.UpdateError as e:
                self.uq.put(("check_error", manual, parent, str(e)))
            except Exception as e:  # never let a thread die silently
                self.uq.put(("check_error", manual, parent, f"The update check failed: {e}"))
        threading.Thread(target=work, daemon=True).start()

    def _ok_parent(self, parent):
        try:
            return parent if parent is not None and parent.winfo_exists() else self
        except tk.TclError:
            return self

    def _poll_updates(self):
        try:
            while True:
                msg = self.uq.get_nowait()
                kind = msg[0]
                if kind == "checked":
                    _, manual, parent, rel = msg
                    self._update_busy = False
                    if rel is None:
                        self.status.set(f"You have the latest version (v{core.VERSION}).")
                        if manual:
                            messagebox.showinfo("Check for updates", f"You are running the latest version "
                                                f"(v{core.VERSION}).", parent=self._ok_parent(parent))
                    else:
                        self.status.set(f"Update available: {rel.tag}")
                        self._offer_update(rel, parent)
                elif kind == "check_error":
                    _, manual, parent, text = msg
                    self._update_busy = False
                    self.status.set("Could not check for updates.")
                    if manual:
                        messagebox.showwarning("Check for updates", text, parent=self._ok_parent(parent))
                elif kind == "progress" and self._dl:
                    _, done, total = msg
                    if total:
                        self._dl["bar"].config(mode="determinate", maximum=total, value=done)
                        self._dl["pct"].set(f"{done / 1048576:.1f} of {total / 1048576:.1f} MB")
                elif kind == "stage" and self._dl:
                    self._dl["label"].set(msg[1])
                elif kind == "ready":
                    self._apply_update(msg[1])
                elif kind == "failed":
                    _, rel, text = msg
                    self._update_busy = False
                    self._close_dl()
                    self.status.set("Update failed.")
                    if rel is not None and messagebox.askyesno(
                            "Update failed", f"{text}\n\nOpen the release page to download it yourself?"):
                        webbrowser.open(rel.page_url)
        except queue.Empty:
            pass
        try:
            self.after(150, self._poll_updates)
        except tk.TclError:  # the window was closed (for instance by the update restart)
            pass

    def _offer_update(self, rel, parent=None):
        """The 'new version available' popup with Update and Cancel."""
        d = tk.Toplevel(self._ok_parent(parent))
        d.title("Update available")
        d.geometry("520x380")
        d.transient(self)
        f = ttk.Frame(d, padding=12)
        f.pack(fill="both", expand=True)
        ttk.Label(f, font=("TkDefaultFont", 11, "bold"),
                  text=f"A new version of {core.FULL_NAME} is available").pack(anchor="w")
        ttk.Label(f, text=f"Installed: v{core.VERSION}     New: {rel.tag}").pack(anchor="w", pady=(2, 8))
        ttk.Label(f, text="What's new:").pack(anchor="w")
        t = tk.Text(f, wrap="word", height=10, padx=8, pady=6)
        t.insert("1.0", rel.notes or "(no release notes)")
        t.config(state="disabled")
        t.pack(fill="both", expand=True, pady=(2, 8))
        ttk.Label(f, foreground="#555", wraplength=480,
                  text="Update downloads the new version, installs it, and reopens the program. "
                       "Your settings and watchlist are kept.").pack(anchor="w", pady=(0, 8))
        bar = ttk.Frame(f)
        bar.pack(fill="x")
        ttk.Button(bar, text="Cancel", command=d.destroy).pack(side="right")
        ttk.Button(bar, text="Update", command=lambda: (d.destroy(), self._start_update(rel))
                   ).pack(side="right", padx=6)
        d.protocol("WM_DELETE_WINDOW", d.destroy)
        d.lift()
        d.focus_force()

    def _start_update(self, rel):
        why = updater.problem(updater.install_target())
        if why:
            if messagebox.askyesno("Update", f"This copy cannot update itself.\n\n{why}\n\n"
                                   "Open the release page to download the new version?"):
                webbrowser.open(rel.page_url)
            return
        if self._update_busy:
            return
        self._update_busy = True
        self._update_cancel.clear()
        d = tk.Toplevel(self)
        d.title("Updating")
        d.geometry("420x140")
        d.transient(self)
        d.resizable(False, False)
        label, pct = tk.StringVar(value=f"Downloading {rel.tag} ..."), tk.StringVar(value="")
        ttk.Label(d, textvariable=label).pack(anchor="w", padx=14, pady=(14, 4))
        bar = ttk.Progressbar(d, mode="indeterminate", length=390)
        bar.pack(padx=14)
        bar.start(12)
        ttk.Label(d, textvariable=pct, foreground="#555").pack(anchor="w", padx=14, pady=(4, 0))
        cancel = ttk.Button(d, text="Cancel", command=self._update_cancel.set)
        cancel.pack(side="bottom", pady=10)
        d.protocol("WM_DELETE_WINDOW", self._update_cancel.set)
        self._dl = {"win": d, "bar": bar, "label": label, "pct": pct, "cancel": cancel}
        target = updater.install_target()

        def work():
            try:
                plan = updater.prepare(
                    rel, target, progress=lambda a, b: self.uq.put(("progress", a, b)),
                    status=lambda s: self.uq.put(("stage", s)), cancel=self._update_cancel)
                self.uq.put(("ready", plan))
            except updater.UpdateError as e:
                self.uq.put(("failed", None if self._update_cancel.is_set() else rel, str(e)))
            except Exception as e:
                self.uq.put(("failed", rel, f"The update failed: {e}"))
        threading.Thread(target=work, daemon=True).start()

    def _close_dl(self):
        try:
            if self._dl:
                self._dl["win"].destroy()
        except tk.TclError:
            pass
        self._dl = {}

    def _apply_update(self, plan):
        """Download is done: hand over to the helper script, quit, and let it install and reopen the program."""
        if self._dl:
            self._dl["label"].set("Installing - the program will close and reopen ...")
            self._dl["cancel"].state(["disabled"])
            self._dl["bar"].config(mode="indeterminate")
            self._dl["bar"].start(12)
            self.update_idletasks()
        try:
            updater.start_helper(plan)
        except Exception as e:
            import shutil
            shutil.rmtree(plan.stage, ignore_errors=True)
            self._update_busy = False
            self._close_dl()
            messagebox.showerror("Update failed", f"The update could not be started: {e}")
            return
        self._close()  # stops polling, saves everything, closes the window
        t = threading.Timer(8, os._exit, args=(0,))  # make sure the process really ends so the files can be replaced
        t.daemon = True
        t.start()

    def show_changelog(self):
        p = resource_path("CHANGELOG.md")
        text = p.read_text(encoding="utf-8") if p.exists() else "No changelog found."
        w = tk.Toplevel(self)
        w.title("Changelog")
        w.geometry("560x480")
        t = tk.Text(w, wrap="word", padx=10, pady=10)
        t.insert("1.0", text)
        t.config(state="disabled")
        t.pack(fill="both", expand=True)

    def _close(self):
        if self.poller:
            self.poller.stop()
        try:
            self.cfg["feed_pane"] = int(self.paned.sashpos(0))
            self.cfg["feed_widths"] = {c[0]: int(self.tree.column(c[0], "width")) for c in COLS}
        except tk.TclError:
            pass
        core.save_listings(self.listings)
        self.cfg.save()
        self.destroy()


def main():
    App().mainloop()


if __name__ == "__main__":
    main()
