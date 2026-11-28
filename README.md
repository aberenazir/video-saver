# ThumbStudio Video Saver (formerly Video Saver)

Paste a link from YouTube, Instagram, TikTok, X, Facebook, Threads, Reddit, Pinterest, Snapchat, Vimeo, Twitch,
Dailymotion, Bilibili, SoundCloud (and ~1,800 other sites) and the video is saved into a Finder folder you choose.

## Open it

Double-click **ThumbStudio Video Saver** in Applications (or Launchpad / Spotlight). The app file is still
`Video Saver.app` underneath, so updates, settings and the Downloads › Video Saver folder carry on. It opens in its own window with its icon in
the Dock. Close the window or press ⌘Q to quit.

## Use it

1. In any app, press **Share → Copy link** on a video.
2. Switch to Video Saver: it offers **"Link on your clipboard: Save it"**. Or paste into the box and press
   **Save video** (or Enter). Several links at once (one per line, or mixed with other text) work too.
   You can also drag a link from a browser onto the window.
3. Pick the quality: **Best quality** (up to 4K/8K when the site has it), 1080p, 720p, 480p, or **Audio only (MP3)**.
4. When it's done: **Show in Finder** or **Open**. Everything you saved stays in the **Saved** list (searchable).

Videos go to **Downloads › Video Saver** until you press **Change…** and pick another folder.

**Pause / Resume:** a save that's running has **Pause** and **Stop**. Pause keeps what came in so far (each save has
its own folder in `<data>/partial/<id>`); **Resume** carries on from there. Paused saves stay paused after quitting
or restarting the Mac, and saves that were still running when you quit carry on by themselves next time
(`<data>/queue.json`). Stop on a paused save forgets it and throws its pieces away.

## Settings

| Setting | What it does |
|---|---|
| Save videos to | The Finder folder for new videos |
| A folder per app | YouTube, Instagram, TikTok, X… sub-folders inside your save folder |
| Make every video Mac-friendly | Converts VP9/AV1/Opus to H.264/AAC MP4 so QuickTime, iMovie, CapCut and ThumbStudio Video open it (on by default) |
| Use my login from | For posts that need you logged in (Instagram stories, private / age-limited videos): reads that browser's login on this Mac. Chrome asks once for your Mac password ("Always Allow"); Safari needs Full Disk Access for Video Saver |
| Notifications / Show in Finder when saved | Optional |
| Update downloader | Sites change often; it also updates itself once a week (used from the next start) |

## Install it on any Mac or Windows PC (no Python, Terminal or Claude Code needed)

- **Mac:** `Install/Mac/Video Saver.dmg` (built by `bash installer/build_mac.sh`): a self-contained app with Python,
  yt-dlp, ffmpeg and Deno inside. Built on Apple Silicon for Apple Silicon Macs; the GitHub workflow also builds an
  Intel one.
- **Windows:** built on GitHub's computers by `.github/workflows/build.yml` (a Mac can't make a Windows .exe):
  `Video Saver Setup.exe` and a portable zip.
- The self-contained app updates its downloader (yt-dlp) by fetching the newest one from PyPI into
  `<data folder>/pylib` (it can't pip-install into itself); it's used from the next start, and a broken or older one
  is skipped automatically.
- YouTube needs a JavaScript runtime for full quality. The app brings Deno. Without any runtime (only when running
  from source with neither Deno nor Node.js installed), YouTube still saves but often only in low quality and some
  videos fail.

### Updates (the ✨ Update button)

The self-contained app checks GitHub Releases of `aberenazir/video-saver` (`REPO` in `app_update.py`) when it starts
and twice a day. A newer version shows **✨ Update to x.y** at the top; it downloads the right file for that computer
(Apple Silicon or Intel .dmg, Windows Setup .exe, checked against GitHub's sha256), then **Restart now** swaps it in
(Mac: replaces the app where it is and reopens it; Windows: runs the Setup silently and reopens). Settings and the
saved list are kept. Settings → "Video Saver version" has **Check for updates**.

To publish a new version: change the number in `installer/VERSION`, then push a tag with that number, for example
`git tag v2.1 && git push origin v2.1`. The workflow builds every installer and attaches them to a GitHub Release; every
installed copy then offers the update. (Until the repository and a first release exist, the button simply never
shows.) `VIDEO_SAVER_RELEASES=<url>` points the check at a test file instead of GitHub (only for testing).

### Signing (so macOS remembers Full Disk Access)

`build_mac.sh` signs the app with the "Video Saver Local Signing" certificate in this Mac's login Keychain (self-made,
valid to 2046, no Apple account). macOS ties Full Disk Access to that certificate, so it survives rebuilds and
updates; without it (or on GitHub's computers) the app gets an ad-hoc signature and macOS asks again after every
new build. So build Mac releases on this Mac (`bash installer/build_mac.sh`) and attach that .dmg to the GitHub
Release, rather than using the GitHub-built Mac .dmg. Back up the certificate (Keychain Access → export) if you want
to build on another Mac with the same identity.

### What differs on Windows

| Mac | Windows |
|---|---|
| Finder (`open -R`, `open`) | File Explorer (`explorer /select,`, `os.startfile`) |
| Notifications via `osascript` | Windows notification via PowerShell (built in) |
| Clipboard via NSPasteboard | Clipboard via the Windows API (ctypes) |
| Trash via NSFileManager | Recycle Bin via SHFileOperation (if that fails, the old copy is kept, renamed) |
| H.264 conversion with the hardware encoder (`h264_videotoolbox`) | Software encoder `libx264` |
| Browsers found in /Applications | Browsers found by their profile folders |
| Data in `~/Library/Application Support/Video Saver` | Data in `%APPDATA%\Video Saver` |
| "Use my login from" works with Safari, Chrome, Brave, Firefox… | **Only Firefox** works: Chrome, Edge, Brave, Opera and Vivaldi lock their logins on Windows (app-bound encryption, and the file is locked while the browser is open) |

## Files
- `saver.py`: the download engine (yt-dlp), Mac-friendly conversion, settings, saved list
- `saver_api.py`: its web routes. Both files are also used, unchanged, by Link Transcriber's "⬇ Save a video" (copy them across when one changes)
- `server.py`: the local web server (127.0.0.1:8766, only this Mac)
- `window.py`: the app window (starts the server and shows the page), folder chooser, clipboard (Mac and Windows)
- `app_update.py`: Video Saver's own updates (the ✨ Update button), from GitHub Releases
- `index.html`: the page
- `installer/build_mac.sh`: builds the self-contained app and `Install/Mac/Video Saver.dmg` (doesn't touch /Applications)
- `installer/VideoSaver.spec`: the PyInstaller recipe (Mac and Windows); `installer/requirements.txt`: what it bundles
- `installer/windows/`: the Windows installer recipe (Inno Setup), version info and a Windows self-test
- `.github/workflows/build.yml`: builds Windows (Setup .exe + portable zip) and Mac (Apple Silicon + Intel) on GitHub
- `installer/install.sh`: **not the installer any more**: the old way (an app that needs a Python setup on this Mac). It refuses to run unless given `--old-python-version`, because it would replace the self-contained app
- `installer/make_icon.py`: draws the icon

Settings and the saved list live in `~/Library/Application Support/Video Saver` (Windows: `%APPDATA%\Video Saver`), kept when you reinstall.
