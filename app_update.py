"""Video Saver's own updates (the app itself; the downloader yt-dlp updates separately in saver.py).

New versions are published as GitHub Releases of REPO (push a tag like v2.1: the workflow builds the Mac .dmg files
and the Windows Setup .exe and attaches them). The app checks at start and twice a day. When there's a newer one the
page shows "✨ Update to 2.1"; pressing it downloads the right file for this computer, and "Restart now" swaps it in:
  Mac:     the new Video Saver.app replaces this one (same place, settings kept) and opens.
  Windows: the new Setup .exe runs by itself (no questions) and opens the new version.
Only the self-contained app updates itself; from source (installer/install.sh) it just says a new version exists.
"""
import hashlib, json, os, platform, re, ssl, subprocess, sys, threading, time, urllib.request

import saver

REPO = "aberenazir/video-saver"   # where new versions are published (GitHub Releases)
# VIDEO_SAVER_RELEASES = another address answering like GitHub's "latest release" (only for testing updates)
LATEST = os.environ.get("VIDEO_SAVER_RELEASES") or f"https://api.github.com/repos/{REPO}/releases/latest"
HERE = getattr(sys, "_MEIPASS", "") or os.path.dirname(os.path.abspath(__file__))
WORK = os.path.join(saver.DATA, "update")


def _read_version():
    for p in (os.path.join(HERE, "VERSION"), os.path.join(HERE, "installer", "VERSION")):
        try:
            return open(p).read().strip()
        except OSError:
            pass
    return "0"


VERSION = _read_version()
STATE = {"state": "idle", "current": VERSION, "latest": "", "notes": "", "detail": "", "progress": 0,
         "can_install": saver.FROZEN, "checked": 0}
_asset = {}
_lock = threading.Lock()


def _ctx():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def _open(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": "Video Saver", "Accept": "application/vnd.github+json"})
    return urllib.request.urlopen(req, timeout=timeout, context=_ctx())


def _pick(assets):
    """The installer for this computer: Setup .exe on Windows, the Apple Silicon or Intel .dmg on a Mac.
    (GitHub turns spaces in file names into dots, so names are compared without them.)"""
    key = lambda a: re.sub(r"[^a-z0-9]", "", a["name"].lower())
    if saver.WINDOWS:
        return next((a for a in assets if key(a).endswith("exe") and "setup" in key(a)), None)
    dmgs = [a for a in assets if key(a).endswith("dmg")]
    want = "intel" if platform.machine() == "x86_64" else "applesilicon"
    return next((a for a in dmgs if want in key(a)), None) or next(
        (a for a in dmgs if "intel" not in key(a) and want == "applesilicon"), None)


def check(quiet=False):
    """Asks GitHub for the newest release. No release yet / no internet = nothing to show."""
    if STATE["state"] in ("downloading", "ready"):
        return STATE
    try:
        rel = json.load(_open(LATEST))
        latest = rel.get("tag_name", "").lstrip("vV")
        asset = _pick(rel.get("assets") or [])
        STATE.update(checked=time.time(), latest=latest, notes=(rel.get("body") or "")[:1200],
                     page=rel.get("html_url", ""))
        if latest and saver._vtuple(latest) > saver._vtuple(VERSION) and asset:
            _asset.clear()
            _asset.update(asset)
            STATE.update(state="available", detail=f"Version {latest} is ready to install.")
        else:
            STATE.update(state="current", detail=f"You have the newest version ({VERSION}).")
    except Exception as e:
        no_release = "404" in str(e)
        STATE.update(state="current" if no_release else ("idle" if quiet else "error"), checked=time.time(),
                     detail=f"You have the newest version ({VERSION})." if no_release
                     else f"Couldn't check for updates (no internet?) {str(e)[:120]}")
    return STATE


def auto_check():
    def loop():
        time.sleep(8)
        while True:
            check(quiet=True)
            time.sleep(12 * 3600)
    threading.Thread(target=loop, daemon=True).start()


def install():
    """Downloads the new version (in the background); the page then shows Restart now."""
    with _lock:
        if STATE["state"] != "available" or not STATE["can_install"]:
            return STATE
        STATE.update(state="downloading", progress=0, detail="Downloading the update…")
    threading.Thread(target=_download, daemon=True).start()
    return STATE


def _download():
    a = dict(_asset)
    try:
        os.makedirs(WORK, exist_ok=True)
        dst = os.path.join(WORK, "Video Saver Setup.exe" if saver.WINDOWS else "Video Saver.dmg")
        h, got = hashlib.sha256(), 0
        with _open(a["browser_download_url"], 60) as r, open(dst + ".part", "wb") as f:
            total = int(r.headers.get("Content-Length") or a.get("size") or 0)
            while chunk := r.read(1 << 20):
                f.write(chunk)
                h.update(chunk)
                got += len(chunk)
                if total:
                    STATE.update(progress=round(got * 100 / total), detail=f"Downloading the update… {round(got * 100 / total)}%")
        want = (a.get("digest") or "").removeprefix("sha256:")
        if (want and h.hexdigest() != want) or (a.get("size") and got != a["size"]):
            raise RuntimeError("the download was damaged, try again")
        os.replace(dst + ".part", dst)
        if saver.WINDOWS:
            _asset["file"] = dst
        else:
            _unpack_mac(dst)
        STATE.update(state="ready", progress=100, detail=f"Version {STATE['latest']} is ready. Restart to use it.")
    except Exception as e:
        STATE.update(state="available", detail=f"The update didn't download: {str(e)[:160]}. Try again.")


def _this_app():
    """…/Video Saver.app that is running now (Mac)."""
    p = os.path.realpath(sys.executable)
    return p[:p.index(".app/") + 4] if ".app/" in p else ""


def _unpack_mac(dmg):
    mnt, new = os.path.join(WORK, "mnt"), os.path.join(WORK, "new")
    subprocess.run(["/bin/rm", "-rf", new])
    os.makedirs(mnt, exist_ok=True)
    subprocess.run(["hdiutil", "attach", "-nobrowse", "-readonly", "-noautoopen", "-mountpoint", mnt, dmg],
                   check=True, capture_output=True)
    try:
        app = next(os.path.join(mnt, n) for n in os.listdir(mnt) if n.endswith(".app"))
        subprocess.run(["ditto", app, os.path.join(new, "Video Saver.app")], check=True)
    finally:
        subprocess.run(["hdiutil", "detach", "-quiet", "-force", mnt], capture_output=True)
    os.remove(dmg)
    here = _this_app()
    if not here or "/AppTranslocation/" in here or not os.access(os.path.dirname(here), os.W_OK):
        # can't replace it where it is (e.g. opened straight from Downloads): show the new one in Finder instead
        _asset["manual"] = True


SWAP = """#!/bin/bash
# waits for Video Saver to quit, puts the new version where the old one was, and opens it
while kill -0 "$1" 2>/dev/null; do sleep 0.3; done
OLD="$2"; NEW="$3"; BAK="$OLD.old"
rm -rf "$BAK"
if mv "$OLD" "$BAK" && ditto "$NEW" "$OLD"; then rm -rf "$BAK" "$NEW"; else rm -rf "$OLD"; mv "$BAK" "$OLD"; fi
open "$OLD"
"""


def restart():
    """Quits, swaps in the new version and opens it."""
    if STATE["state"] != "ready":
        return STATE
    if saver.WINDOWS:
        subprocess.Popen([_asset["file"], "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS"],
                         creationflags=0x00000008 | 0x00000200, close_fds=True)  # DETACHED, NEW_PROCESS_GROUP
    else:
        new = os.path.join(WORK, "new", "Video Saver.app")
        if _asset.get("manual"):
            subprocess.run(["open", "-R", new])
            STATE.update(detail="Drag the new Video Saver (shown in Finder) into Applications, replacing the old one.")
            return STATE
        script = os.path.join(WORK, "swap.sh")
        with open(script, "w") as f:
            f.write(SWAP)
        subprocess.Popen(["/bin/bash", script, str(os.getpid()), _this_app(), new], start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    STATE.update(state="restarting", detail="Restarting…")
    threading.Timer(0.6, lambda: os._exit(0)).start()
    return STATE
