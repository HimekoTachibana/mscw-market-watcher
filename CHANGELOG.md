# Changelog

## v0.5.0 - 2026-11-04
- **Auto-update:** Settings > **Check for updates** looks at the project's GitHub releases. If a newer
  version exists, a popup shows what's new with **Update** and **Cancel**. Update downloads the build for
  your system (Windows, Linux or macOS), checks it, installs it, and reopens the program by itself.
  Your settings, watchlist and listings are kept.
- The program also checks quietly when it starts (turn this off under Settings > General). It only
  speaks up if there is a newer release.
- Copies run from the source code, or from a renamed or read-only folder, can't replace themselves; the
  popup then offers to open the release page instead.
- v0.4.0 has no updater, so install v0.5.0 once by hand; from then on updates are automatic.

## v0.4.0 - 2026-11-03
- **Live Feed and Watchlist** now have scroll bars, and a draggable divider between them: drag it up or
  down to resize. The divider position and column widths are remembered.
- **Sort** the Live Feed by clicking any column heading (click again to reverse). Default order: most
  recent listing at the top. Blank cells always sort to the bottom.
- **Move columns** by dragging a heading left or right. The order is remembered.
- **Sold** column (far left): tick it yourself when you have checked a shop in game. The line turns gray,
  stops highlighting as a deal and no longer beeps. Click the box or press Space. Remembered.
- **Copy seller:** right-click a row > Copy seller name (or Ctrl+C, or double-click the Seller cell),
  then paste it into a whisper in game.
- **Watchlist:** double-click (or F2) a max price to edit it in place; Enter saves, Esc cancels, empty or
  "any" = any price, "50k" and "1.5m" work. Select an item and press **Delete** to remove it.
- **Show listings from the last:** (15 minutes, 30 minutes, 1 hour ... or type your own, e.g. 1h30).
  Also controls how far the Newest list is scrolled.
- **Listings persist** between Stop/Start and app restarts. Older ones are removed automatically when
  they pass the chosen time. The **Listed** column counts up live every minute.
- **Random timing:** pauses between clicks and between passes are random, 500-5000 ms (editable
  range in Settings), instead of fixed intervals.
- **Exact item names:** the filter is typed with the full name and only the row with exactly that name
  is clicked (case and punctuation ignored). "Shoes Speed Scroll: Chaos" can no longer open
  "Shoes Speed Scroll: Intermediate". If nothing matches exactly, the status line says what the site showed.
- New toggle: **Only listings with Channel and Location**.
- The browser no longer starts with `--no-sandbox` (no more "unsupported command-line flag" bar).
- Packaged apps are named with the version, e.g. **MSCW Market Watcher v0.4.0** (folder and program).
  New `build_linux.sh` and `build_macos.sh`; `build_windows.bat` also makes a zip in `release/`.
- Settings > Test no longer reports FAIL when the Newest list simply has nothing inside the chosen time
  window; it says how many older listings exist and how old the newest is.
- `publish_github.bat` / `publish_github.sh` upload the project to your GitHub account.

## v0.3.1 - 2026-11-03
- Fix: "Filter box 'Filter items...' not found". The site's placeholder uses the single "…" character;
  the filter box is now matched by its words (with or without dots) or as a search box.
- Listings are read from the site's real rows (`li.buy-row`) and items are clicked inside the item table,
  so names that also appear in the scrolling megaphone ticker are never clicked by mistake.
- Exact prices: the site shows "45K" but its tooltip holds "44,999 mesos"; the exact figure is used for
  the listing price and for the typical price (24h AVG / Discount).
- Fix: a hidden non-breaking space no longer sticks to map names.
- New advanced settings: item selector and row selector (leave blank to match by visible text).

## v0.3.0 - 2026-11-02
- Listings are now read by clicking through the site in a background browser instead of an API:
  for each watched item it filters the list, clicks the item, opens **Newest** and records seller,
  channel, location, price and time since listing. New columns: Seller and Listed.
- 24h AVG and Discount use the site's TYPICAL price for the item.
- Settings is now tabbed (Listings (browser), Item list, General). **Test & save page snapshot**
  walks through each step and says exactly what failed; the rendered page is saved for troubleshooting.
- Stops on a Cloudflare check; tick **Show the browser window** to complete it yourself.
- New: ignore listings older than N minutes; pause between clicks; browser choice (Edge, Chrome, Chromium).
- Default pass interval is now 30 s (minimum 5 s) because a pass clicks through every watched item.
- Each Start launches a fresh browser; closing is automatic.

## v0.2.0 - 2026-11-02
- Item list is now built from OSMS Data Explorer (about 7,300 item ids, 5,300 unique names) and
  cross-referenced with MeowDB's item index. Names confirmed by both sites show a check mark.
- Settings -> **Update item database**: pulls both sites, adds any items you are missing and tells
  you exactly what was new. Existing items are never removed. Items that exist only on MeowDB are
  added by name (no icon). The first launch (and any list older than 7 days) updates automatically.
- Settings -> **Cross-check report**: counts, mismatches and what was added.
- Watchlist: pick an item from a searchable dropdown or just type any name.
- Item icons are shown to the left of every item name (main table, watchlist, dropdown). They
  download in the background and are cached, so the window never freezes.
- New settings: OSMS data folder URL, MeowDB index URL, MeowDB cross-check on/off, add MeowDB-only items on/off.

## v0.1.0 - 2026-11-02
- First release.
- Polite poller: editable interval (1000 ms minimum), honest User-Agent with your contact,
  exponential backoff on 429/503 (honors Retry-After).
- Pauses and tells you if the site serves a Cloudflare challenge or refuses access (401/403);
  it never tries to bypass it.
- Watchlist with per-item max price; beeps on new matching listings.
- Sound: volume slider, mute toggle, test button.
- Columns: icon, Item Name, Channel, Location, Price, 24h AVG, Discount.
- Item database built from two sources (e.g. osmsdataexplorer + MeowDB) with a cross-check report.
- Settings: source URL, JSON field mapping, custom headers (API key), item sources, Changelog button.
