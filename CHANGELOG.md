# Changelog

## v0.5.6 - 2026-11-05
- **Item Name filter in the Live Feed heading** (replaces the Items button of v0.5.5). Click the **▾** at the
  right end of the "Item Name" heading (the rest of the heading still sorts) to open a drop-down list of items
  with check boxes: tick one or several, a Search box narrows long lists, **Select all** ticks every item in the
  list and **Deselect all (reset)** clears the ticks so every item shows again. It applies instantly and is
  remembered; the heading shows how many items are ticked.
- **Background scraping works again.** With "Show the browser window" off, the browser now runs in a normal
  window placed far off-screen (it behaves exactly like the visible window; the old headless mode is only used
  when there is no screen at all). It no longer shows on your screen or taskbar position.
- **The browser window opens by itself** when something goes wrong or a person is needed: a Cloudflare check,
  an HTTP 403, or an error that stops a scan. It opens on the site so you can look or complete a check; the
  Settings test keeps that window open (up to 5 minutes) until you close it.
- **Cloudflare / 403:** MesoWatcher never tries to get around a bot check. If the check cannot be completed
  by hand (it asks again and again), the site is rejecting automated browsers; the program stops with the message
  "HTTP 403: the site refused the request ..." and writes the details to the error log.
- **Error log** (`error_log.txt` in the program's data folder; Settings > **Open error log**). Every error,
  crash, Cloudflare stop, failed Settings test and window error adds a report with the error, versions, key
  settings, what the browser showed (URL, title, user agent) and the last ~250 actions before it (Start/Stop,
  page loads, text typed, every search result clicked, tabs opened, listings read). Upload that file to get help.
  Your contact address is never written to it.
- **Settings > Test item:** now a drop-down of the item database that still accepts any typed name (typing
  narrows the list). The default is **Gloves Crit. Rate Scroll: Intermediate** and your last choice is remembered.
- **Release notes can no longer miss changes:** the notes of each release now contain its own section plus every
  earlier CHANGELOG version that no release has described yet (`tools/release_notes.py`; tested). Versions
  v0.5.2 and v0.5.4 were never published on their own, and v0.1.0-v0.3.1 came before the first GitHub release
  (v0.4.0), so their notes (below) all appear in this release's notes.
  Releases are numbered from the latest published release (v0.5.5), so no number is skipped.
- The build now runs the program's self-test (window, Live Feed, browser driver) before packaging.

## v0.5.5 - 2026-11-05
- New **Items** button at the top of the Live Feed (next to the two checkboxes): choose one or several items
  to show; nothing ticked shows every item. The choice is remembered. The list holds the items in your
  Watchlist and every item that has listings in the feed.

## v0.5.4 - 2026-11-05
- Fixed "Likely still up" showing in the Location column. That is hidden status text the site adds to every
  row; for shops that show a channel but no map it was mistaken for the location. It (and "Seller not
  confirmed", and the price tags such as "High +18%" / "Deal -5%") is now ignored, so those listings have an
  empty Location and are hidden by "Only listings with Channel and Location".
- Settings > Test also shows what the site says about its own freshness ("updated 5m ago").

## v0.5.3 - 2026-11-05
- Scrolling stops as soon as a listing is older than **Show listings from the last** (the box in the main
  window). The site rounds hours down ("1h ago" may be 1h59m), so a row that shows exactly the limit now counts
  as over it; with "1 hour" the program no longer reads or scrolls into the "1h ago" rows.

## v0.5.2 - 2026-11-05
- **New way to find and open an item.** The program types the item name, then clicks the search results one by
  one (top to bottom) and stops at the first one whose right-hand panel shows the same item name. The icon is
  used as a second check: the picture in the panel must be the same one as on the clicked result (and the
  item's own icon when the item list knows it). A result that opens something else is skipped.
- **Settings > General > Search results to try** (default **6**, was 12): how many results are clicked before
  giving up on an item.
- After a match the program clicks the **For sale now** tab at the top right of the panel (the number next to it
  changes with the number of shops) and reads the listings there, newest first. The tab name can be changed in
  Settings > Advanced (`forsale_label`).
- That list already has every shop on the page, so the program reads them all at once and only scrolls when
  the page says it shows fewer shops than it has. When it does scroll, it hovers the list and rolls the mouse
  wheel over it, as a person would.
- Rows in the For sale now list show the price without the word "each"; they are now read correctly (exact
  price from the tooltip when there is one).
- Settings > Test now says which tab was clicked, how many shops the site reports and how many were read.

## v0.5.1 - 2026-11-04
- **Clear Live Feed** button (top right, next to Settings) deletes every listing after a confirmation. The
  same shops, still on the site, are not added again on the next pass; new listings appear as usual.
- **Settings > General > Delete Live Feed listings older than (hours)**: listings are deleted from the feed
  once they pass that age (for example 6). The clock keeps running while the program is closed. 0 = off
  (the "Show listings from the last" box decides, as before).
- **Only listings with Channel and Location** now also hides listings whose location is "Place not seen"
  (or "FM ?"), which used to slip through.
- New **Target Price** column right after Price: the max price you set for that item in the Watchlist
  ("any" if you watch it with no limit, "-" if it is not on the watchlist). Sortable and movable like the
  others; existing saved column orders get it next to Price.
- **Scrolling the Newest list** is much more persistent. It finds the box that really scrolls, moves down
  one screen at a time (you can watch the scroll bar move in a visible browser), waits up to 3 s at the
  bottom for the site to load more, then rolls the mouse wheel and presses a "Load more" button if there is
  one, and only after two such tries decides the list has ended. Before, it gave up after one short wait.
  Settings > Test now reports how many times it scrolled, in which box, and why it stopped.
- **Opening the right item**: after typing the name, search results are opened one after the other (a
  result whose text equals the name goes first) until the right-hand panel shows the item: its heading
  must read exactly like the name, and its icon must be that item's icon when the icon can be compared.
  A result that opens something else is skipped. This fixes scrolls that were no longer being opened.
  If nothing matches, the status line says what the panel showed instead.
- Added `--selftest` (headless self-check used to test the Linux build on other distributions).

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
