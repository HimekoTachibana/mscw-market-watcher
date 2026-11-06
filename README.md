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
* **Pause / Resume:** press **Pause** beside Start to let the current scan finish and then hold polling; press **Resume** to continue the same session. **Stop** ends monitoring and closes the browser.
* Listings are saved, so they are still there after Stop/Start or restarting; they drop off once they
  are older than the chosen window and the Listed time counts up every minute.
* **Background:** the browser runs headless (no window). It never uses your mouse, keyboard or focus,
  so you can keep playing. Only if you tick "Show the browser window" (to pass a Cloudflare check
  yourself) does a window open. If a Cloudflare check appears, a window opens by itself so you can
  complete it; that session then stays in the window.
* **Watch only** (Settings > General) needs **Scan mode: Rotating windows**: each item keeps its own page
  and is read only when its list changed. One page (the default) is lighter on the site.

## Download and run (nothing to install)

Download the file for your system from the latest release, unpack it anywhere (your home folder, a USB stick)
and start the program inside. No installer, no admin rights, no Python, no browser to install:

* **Windows:** unzip, run `MSCW Market Watcher vX.Y.Z.exe`. Uses the Edge that comes with Windows 10/11.
* **Linux:** `tar -xzf "MSCW Market Watcher vX.Y.Z (Linux).tar.gz"`, then run `./"MSCW Market Watcher vX.Y.Z"`
  inside the folder (or double-click it). One download for every x86-64 distribution with glibc 2.31 or
  newer: Ubuntu 20.04+, Debian 11+, Linux Mint, Pop!_OS, Fedora, RHEL/Rocky/Alma 9, openSUSE, Arch,
  Manjaro, EndeavourOS and the gaming distributions **CachyOS**, **Bazzite** and **SteamOS** (Steam Deck:
  use Desktop Mode). It carries its own Python, Tk and Chromium; if a minimal install lacks one of the
  libraries Chromium uses (NSS, CUPS, ATK, ...), the program's own copy is used for that one only. It works
  on immutable systems (Bazzite, SteamOS) because nothing is written outside the folder and your settings.
* **macOS (Apple Silicon):** unpack and right-click -> **Open** the first time (the app is unsigned). It carries
  its own Chromium. If macOS still refuses to start it, run `xattr -dr com.apple.quarantine` on the `.app` once.

Settings, the watchlist and listings are kept in your user folder (`%APPDATA%\MesoWatcher`,
`~/.config/MesoWatcher`, `~/Library/Application Support/MesoWatcher`), so a new version finds them again.
Sound uses whatever the system has (`paplay`, `pw-play`, `aplay`, `play` or `ffplay` on Linux); with none of
them the window bell is used.

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
4. Press **Start**. A pass visits each watched item with short random pauses between actions
   (500-5000 ms), then waits **3-5 minutes** before the next pass (editable in Settings, never under
   60 s). No item is read more than once every 3 minutes (never under 60 s), in either scan mode.

### How it behaves
* It is a normal Edge/Chrome browser (Playwright) with its own saved profile. It accesses only the pages
  you approved with the site owners.
* **Cloudflare check:** if one appears, monitoring **stops**. Tick **Show the browser window** in
  Settings, press Start and complete the check yourself; it continues when the page loads.
* Rows are recognised by their visible text (a price followed by "each", "3m ago", "CH 14", "FM5"),
  not by CSS class names, so small layout changes don't break it. If the site renames a button, change
  the text under Settings -> Advanced.
* **Exact names only:** the full name is typed in the filter and only the row with exactly that name
  is opened (case and punctuation ignored). A near match is never clicked; the status line tells you
  what the site showed instead, so fix the spelling in your watchlist.
* **Browser:** Windows uses the Edge that ships with Windows; the Linux and macOS downloads use the Chromium
  they carry (`chromium` in Settings). `chrome` or `msedge` can be picked instead if installed.
* **Being polite to the site:** every response from meso.watch is watched, including the requests the page
  makes in the background after a click or scroll. If the site answers **429** or **503** ("slow down"),
  the scan stops at once and waits for the time the site asks (Retry-After), then backs off further on
  repeats (from 1 minute, doubling, up to 1 hour). After a Cloudflare check is completed it waits 15
  minutes before reading again. Ordinary errors are retried after a backoff without restarting the
  browser or reloading the site.
* **Scan modes:** **One page** (default) uses a single headless page for all items. **Rotating windows**
  keeps a page per item open; every open page also refreshes itself, so it loads the site more.

## Run from source

```
pip install -r requirements.txt
python run.py
pytest -q          # optional
```
From source (not the download) you need Python 3.12+ with Tk from your distribution (the package is usually
`python3-tk`, `python3-tkinter` or, on Arch-based systems, `tk`), and Chromium for Playwright once:
`python -m playwright install chromium`.

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
git commit -m "MSCW Market Watcher v0.6.0"
git remote add origin https://github.com/YOUR_NAME/mscw-market-watcher.git
git push -u origin main --tags
```

## Build Windows / Linux / macOS programs

Every build is named with the version, e.g. **MSCW Market Watcher v0.6.0** (the folder and the
program inside it). The version comes from `VERSION` in `mesowatcher/core.py`.

* **Windows:** install Python 3.12 (tick "Add to PATH"), then double-click `build_windows.bat`.
  Result: `dist\MSCW Market Watcher v0.6.0\MSCW Market Watcher v0.6.0.exe` (plus a zip in `release\`).
  It uses the Edge already on Windows.
* **Linux:** Python 3.12+ with Tk and venv, then `./build_linux.sh`. Result: `dist/MSCW Market Watcher v0.6.0/`
  and a `.tar.gz` in `release/`, with Chromium inside. A local build only runs on systems whose glibc is at least
  as new as the build machine's; the GitHub Actions build (Debian 11, glibc 2.31) is the one to publish, and it is
  started and self-tested on Ubuntu, Debian, Fedora, openSUSE, Arch, CachyOS, SteamOS and Bazzite.
* **macOS:** `./build_macos.sh`, result `dist/MSCW Market Watcher v0.6.0.app` with Chromium inside (unsigned:
  right-click -> Open).
* **All three automatically:** push a tag (`git tag v0.4.0 && git push origin v0.4.0`). The GitHub
  Actions workflow builds Windows, Linux and macOS, runs the tests, and attaches the zips to the
  release (or download them from the run's Artifacts). You can also start it by hand under Actions -> Build
  -> Run workflow: tick **Publish a release** to create the tag `v<VERSION>` and the release from the
  selected branch without using git on your computer, or leave it unticked to only get Artifacts.

### Keeping the shipped Chromium up to date

The Linux and macOS downloads carry the Chromium of the Playwright version they were built with, and it never
updates by itself (the program only ever opens meso.watch with it). `requirements.txt` asks for the newest
Playwright, so every release build picks up the current Chromium: publish a release at least once a month, and
sooner when Playwright ships a Chromium security fix. Windows uses the system's Edge, which Windows keeps updated.

## Updating the program

Settings > **Check for updates** asks GitHub for the latest release of `update_repo` (default
`HimekoTachibana/mscw-market-watcher`, editable in `config.json`). If it is newer than the running
version you get a popup with **Update** / **Cancel**. Update downloads the Windows / Linux / macOS file
for your system, verifies its size and SHA-256, unpacks it next to the installed program, then closes the
program, swaps the folders (the old one is deleted, or restored if something fails) and starts the new
version. The folder is named after the version, so the new folder is `MSCW Market Watcher vX.Y.Z` next to
the old one's location; update any shortcut once. Settings, watchlist and listings live in your user data
folder and are not touched.

Needs a packaged build in a writable folder whose name still starts with "MSCW Market Watcher"; otherwise
the popup offers to open the release page. The program also checks quietly at start-up (switch off under
Settings > General).

## Releasing a new version

Bump `VERSION` in `mesowatcher/core.py`, add a section at the top of `CHANGELOG.md`
(Settings -> Changelog shows it), commit, then tag `vX.Y.Z` and push the tag.
