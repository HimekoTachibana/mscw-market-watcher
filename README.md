# MSCW Market Watcher

Watches the free-market listings for items on your list and beeps when one is at or under your max
price. For each watched item it opens the site in a browser (in the background), filters for the
item, clicks it, opens the **Newest** list and records every listing's seller, channel, location,
price and time since listing. Columns: Sold checkbox + icon, Item Name, Seller, Channel, Location,
Price, Listed, 24h AVG (the site's TYPICAL price), Discount (% below it).

## Using the window
* **Live Feed:** click a heading to sort, drag a heading to move a column, tick **Sold** (or press Space)
  after you check a shop in game (the line grays out and stops beeping). Right-click a row ->
  **Copy seller name** to paste into a whisper. **Only listings with Channel and Location** hides map-name shops.
* **Resize:** drag the bar between the Live Feed and the Watchlist up or down.
* **Watchlist:** double-click a max price to edit it; select an item and press **Delete** to remove it.
  **Show listings from the last** sets the time window (also how far the Newest list is scrolled).
* Listings are saved, so they are still there after Stop/Start or restarting; they drop off once they
  are older than the chosen window and the Listed time counts up every minute.
* **Background:** the browser runs headless (no window). It never uses your mouse, keyboard or focus,
  so you can keep playing. Only if you tick "Show the browser window" (to pass a Cloudflare check
  yourself) does a window open.

## First-time setup

1. **Item list:** builds itself on first launch from OSMS Data Explorer, cross-checked against
   MeowDB's item index (needs internet once; cached afterwards). **Settings -> Item list -> Update
   item database** pulls both sites again and adds anything new; **Cross-check report** shows what
   matched, what differs and what was added. Their data stays on your computer and is not
   redistributed. Items that exist only on MeowDB are added by name with no icon.
2. **Watchlist:** pick an item from the dropdown (or type any name), enter a max price, press **Watch**.
   Every watched item is opened on the site each pass, so keep the list to what you really want.
3. **Settings -> Listings (browser) -> Test & save page snapshot.** Uses the "Item to use for Test"
   and tells you which step worked or failed (page opened, filter box found, item clicked, Newest
   list opened, N listings read). It also saves the rendered page so labels can be adjusted without
   guessing (the file path is shown; share it if you want help).
4. Press **Start**. A pass visits each watched item with random pauses between actions and between
   passes (500-5000 ms by default, range editable in Settings, never under 0.5 s), like a person browsing.

### How it behaves
* It is a normal Edge/Chrome browser (Playwright) with its own saved profile. No stealth tricks,
  no fingerprint spoofing, no CAPTCHA solving. Only the pages you approved with the site owners.
* **Cloudflare check:** if one appears, monitoring **stops**. Tick **Show the browser window** in
  Settings, press Start and complete the check yourself; it continues when the page loads.
* Rows are recognised by their visible text (a price followed by "each", "3m ago", "CH 14", "FM5"),
  not by CSS class names, so small layout changes don't break it. If the site renames a button, change
  the text under Settings -> Advanced.
* **Exact names only:** the full name is typed in the filter and only the row with exactly that name
  is opened (case and punctuation ignored). A near match is never clicked; the status line tells you
  what the site showed instead, so fix the spelling in your watchlist.
* **Browser:** Windows uses the Edge that ships with Windows. On macOS pick `chrome`; on Linux install
  Chromium once with `python -m playwright install chromium` and pick `chromium`.
* If the site is ever blocked or slow, the pass ends with a status message and retries with backoff.

## Run from source

```
pip install -r requirements.txt
python run.py
pytest -q          # optional
```
Linux needs Tk (`sudo apt install python3-tk`) and an audio player (`paplay` or `aplay`).
On Linux/macOS without Edge, run `python -m playwright install chromium` once.

## Upload to GitHub

Easiest: install git and the GitHub CLI (https://cli.github.com), then run
`publish_github.bat` (Windows) or `./publish_github.sh` (Linux/macOS). It creates the repo in your
account and pushes the code and version tags.

* Default is a **private** repo (not searchable; only you, plus people you invite, can open it).
* `publish_github.bat public` makes it **public**: anyone with the link can open, fork and send pull
  requests. GitHub has no "unlisted" setting, so a public repo can also be found by GitHub search
  and search engines. Pick whichever of the two fits; you can change it later under the repo's
  Settings -> Danger Zone -> Change visibility.

By hand:
```
git init -b main
git add .
git commit -m "MSCW Market Watcher v0.4.0"
git remote add origin https://github.com/YOUR_NAME/mscw-market-watcher.git
git push -u origin main --tags
```

## Build Windows / Linux / macOS programs

Every build is named with the version, e.g. **MSCW Market Watcher v0.4.0** (the folder and the
program inside it). The version comes from `VERSION` in `mesowatcher/core.py`.

* **Windows:** install Python 3.12 (tick "Add to PATH"), then double-click `build_windows.bat`.
  Result: `dist\MSCW Market Watcher v0.4.0\MSCW Market Watcher v0.4.0.exe` (plus a zip in `release\`).
  It uses the Edge already on Windows.
* **Linux:** `sudo apt install python3-tk python3-venv alsa-utils`, then `./build_linux.sh`.
  Result: `dist/MSCW Market Watcher v0.4.0/` and a `.tar.gz` in `release/`. Run
  `python -m playwright install chromium` once (the script prints the exact command) and pick
  `chromium` in Settings.
* **macOS:** `./build_macos.sh`, result `dist/MSCW Market Watcher v0.4.0.app` (unsigned: right-click -> Open).
* **All three automatically:** push a tag (`git tag v0.4.0 && git push origin v0.4.0`). The GitHub
  Actions workflow builds Windows, Linux and macOS, runs the tests, and attaches the zips to the
  release (or download them from the run's Artifacts). You can also start it by hand under Actions -> Build.

## Releasing a new version

Bump `VERSION` in `mesowatcher/core.py`, add a section at the top of `CHANGELOG.md`
(Settings -> Changelog shows it), commit, then tag `vX.Y.Z` and push the tag.
