"""Video Saver: the download engine (shared, unchanged, by Video Saver and Link Transcriber's "Save a video").

Paste a link from YouTube, Instagram, TikTok, X, Facebook, Reddit, Vimeo, Pinterest, Snapchat, Twitch…
(anything yt-dlp knows) and the video is saved into the Finder folder you chose, made Mac-friendly (H.264/AAC)
so it opens in QuickTime, iMovie, CapCut and ThumbStudio Video.
"""
import glob, json, os, re, shutil, subprocess, sys, threading, time, uuid

MAC, WINDOWS = sys.platform == "darwin", os.name == "nt"
# FROZEN = the self-contained app (PyInstaller: Python and every package inside the app). Link Transcriber and the
# older Video Saver run from a Python setup instead, where updates are pip-installed.
FROZEN = getattr(sys, "frozen", False)
BUNDLE = getattr(sys, "_MEIPASS", "")   # the frozen app's own files

# Each app keeps its own settings and saved list: Link Transcriber sets SAVER_DATA / SAVER_FOLDER / SAVER_APP first.
DATA = os.environ.get("SAVER_DATA") or (
    os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "Video Saver") if WINDOWS
    else os.path.expanduser("~/Library/Application Support/Video Saver"))
APP_NAME = os.environ.get("SAVER_APP") or "Video Saver"
os.makedirs(DATA, exist_ok=True)
SETTINGS_FILE = os.path.join(DATA, "settings.json")
HISTORY_FILE = os.path.join(DATA, "history.json")
BIN = os.path.join(DATA, "bin")
os.makedirs(BIN, exist_ok=True)
PYLIB = os.path.join(DATA, "pylib")   # the newer downloader the self-contained app fetched (see update_downloader)


def _vtuple(v):
    return tuple(int(x) for x in re.findall(r"\d+", v or ""))


def _use_newer_downloader():
    """Self-contained app: if a newer yt-dlp was fetched into PYLIB, load that one instead of the built-in one.
    If it's older than the built-in one (the app itself was updated) or doesn't load, the built-in one is used."""
    try:
        with open(os.path.join(PYLIB, "yt_dlp", "version.py")) as f:
            fetched = re.search(r"__version__\s*=\s*'([^']+)'", f.read()).group(1)
    except Exception:
        return
    try:
        import importlib.metadata
        built_in = importlib.metadata.version("yt-dlp")
    except Exception:
        built_in = ""
    if _vtuple(fetched) <= _vtuple(built_in):
        return
    sys.path.insert(0, PYLIB)
    try:
        import yt_dlp, yt_dlp.postprocessor  # noqa: F401
    except Exception:
        sys.path.remove(PYLIB)
        for m in [m for m in sys.modules if m.split(".")[0] in ("yt_dlp", "yt_dlp_ejs")]:
            del sys.modules[m]


if FROZEN:
    _use_newer_downloader()

import yt_dlp  # noqa: E402
import yt_dlp.postprocessor  # noqa: E402
import imageio_ffmpeg  # noqa: E402

_ff, FFMPEG = imageio_ffmpeg.get_ffmpeg_exe(), os.path.join(BIN, "ffmpeg")
if WINDOWS:
    FFMPEG = _ff   # Windows can't make shortcuts (symlinks) without admin rights: use it where it is
elif os.path.realpath(FFMPEG) != os.path.realpath(_ff):
    try:   # (re)point bin/ffmpeg at this app's ffmpeg (the app may have moved, or the old setup was removed)
        if os.path.lexists(FFMPEG):
            os.remove(FFMPEG)
        os.symlink(_ff, FFMPEG)
    except OSError:
        FFMPEG = _ff
os.environ["PATH"] = BIN + os.pathsep + os.environ.get("PATH", "")

# YouTube needs a JavaScript runtime to unlock its full-quality formats. The self-contained app brings its own
# (Deno or Node.js, in bin/ inside the app); otherwise Deno or Node.js from this computer is used. With none, YouTube still
# saves but often only in low quality, and some videos fail.
_EXE = ".exe" if WINDOWS else ""
_OWN = {rt: os.path.join(BUNDLE, "bin", rt + _EXE) for rt in ("deno", "node")} if BUNDLE else {}
JS_RUNTIMES = {rt: {"path": _OWN[rt]} if rt in _OWN and os.path.exists(_OWN[rt]) else {} for rt in ("deno", "node")}
# Windows: no black console window for ffmpeg, and its messages read as UTF-8 (file names in any language)
_NOWIN = {"creationflags": 0x08000000, "encoding": "utf-8", "errors": "replace"} if WINDOWS else {}

DEFAULTS = {
    "folder": os.environ.get("SAVER_FOLDER") or os.path.expanduser("~/Downloads/Video Saver"),
    "quality": "best",
    "site_folders": False,      # a sub-folder per app: YouTube, Instagram, TikTok…
    "mac_friendly": True,       # convert VP9/AV1/Opus to H.264/AAC so every Mac app opens it
    "browser": "",              # use my login from this browser (private / age-limited / Instagram stories)
    "notify": True,
    "reveal_when_done": False,  # open the Finder window on the new file
    "date_in_name": False,      # start the file name with the day it was posted: "2026-11-24 Title.mp4"
    "last_update_check": 0,
}

QUALITIES = {  # key: (label, max height or 0 for audio)
    "best": ("Best quality", 100000),  # the sharpest the site has (8K, 4K, …)
    "2160": ("4K", 2160),
    "1080": ("1080p", 1080),
    "720": ("720p", 720),
    "480": ("480p (small)", 480),
    "audio": ("Audio only (MP3)", 0),
}

SITE_NAMES = {"youtube": "YouTube", "youtubetab": "YouTube", "instagram": "Instagram", "instagramstory": "Instagram",
              "tiktok": "TikTok", "twitter": "X", "facebook": "Facebook", "reddit": "Reddit", "vimeo": "Vimeo",
              "pinterest": "Pinterest", "snapchat": "Snapchat", "twitch": "Twitch", "twitchclips": "Twitch",
              "twitchvod": "Twitch", "dailymotion": "Dailymotion", "threads": "Threads", "linkedin": "LinkedIn",
              "bilibili": "Bilibili", "soundcloud": "SoundCloud", "tumblr": "Tumblr", "weverse": "Weverse",
              "vlive": "V LIVE", "bluesky": "Bluesky", "kick": "Kick", "streamable": "Streamable"}

# H.264 + AAC first when the site has it (nothing to convert), then VP9 before AV1 (AV1 has no hardware
# decoder on M1/M2 Macs, so converting it is very slow).
FAST_SORT = "+codec:avc:m4a"
_CONVERT_LOCK = threading.Semaphore(1)   # the Mac has one hardware video encoder: one conversion at a time
_SLOTS = threading.Semaphore(3)          # up to 3 downloads at the same time

JOBS = {}          # id -> job (this session)
_lock = threading.Lock()


# ---------------------------------------------------------------- settings & history
def load_settings():
    s = dict(DEFAULTS)
    try:
        with open(SETTINGS_FILE) as f:
            s.update(json.load(f))
    except Exception:
        pass
    return s


def save_settings(changes):
    s = load_settings()
    s.update({k: v for k, v in changes.items() if k in DEFAULTS})
    with open(SETTINGS_FILE, "w") as f:
        json.dump(s, f, indent=1)
    return s


def load_history():
    try:
        with open(HISTORY_FILE) as f:
            return json.load(f)
    except Exception:
        return []


def _save_history(items):
    tmp = HISTORY_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(items[:500], f, ensure_ascii=False, indent=1)
    os.replace(tmp, HISTORY_FILE)


def add_history(entry):
    with _lock:
        same = set(entry.get("paths", []))
        items = [h for h in load_history() if h.get("id") != entry["id"] and not same & set(h.get("paths", []))]
        items.insert(0, entry)
        _save_history(items)


def remove_history(hid):
    with _lock:
        _save_history([h for h in load_history() if h.get("id") != hid])


def history_with_status():
    out = []
    for h in load_history():
        h = dict(h)
        h["files"] = [{"path": p, "name": os.path.basename(p), "exists": os.path.exists(p),
                       "size": os.path.getsize(p) if os.path.exists(p) else 0} for p in h.get("paths", [])]
        out.append(h)
    return out


def installed_browsers():
    apps = {"chrome": "Google Chrome", "safari": "Safari", "firefox": "Firefox", "edge": "Microsoft Edge",
            "brave": "Brave Browser", "opera": "Opera", "vivaldi": "Vivaldi", "chromium": "Chromium"}
    if WINDOWS:  # a browser counts when it has a profile folder (it has been used on this PC)
        from yt_dlp.cookies import _get_chromium_based_browser_settings, _firefox_browser_dirs
        found = []
        for k, n in apps.items():
            try:
                dirs = list(_firefox_browser_dirs()) if k == "firefox" else (
                    [] if k == "safari" else [_get_chromium_based_browser_settings(k)["browser_dir"]])
            except Exception:
                dirs = []
            if any(os.path.isdir(d) for d in dirs):
                found.append({"key": k, "name": n.replace(" Browser", ""),
                              "works": k == "firefox"})  # Chrome-type browsers lock their logins on Windows
        return found
    return [{"key": k, "name": n, "works": True} for k, n in apps.items()
            if os.path.exists(f"/Applications/{n}.app") or os.path.exists(os.path.expanduser(f"~/Applications/{n}.app"))]


# ---------------------------------------------------------------- links
URL_RE = re.compile(r"https?://[^\s<>\"']+", re.I)
BARE_RE = re.compile(r"(?<![\w/.])((?:www\.|m\.|vm\.|vt\.)?(?:youtube\.com|youtu\.be|instagram\.com|tiktok\.com|"
                     r"x\.com|twitter\.com|facebook\.com|fb\.watch|reddit\.com|vimeo\.com|pin\.it|pinterest\.com|"
                     r"snapchat\.com|twitch\.tv|threads\.net|threads\.com)/[^\s<>\"']+)", re.I)


def find_links(text):
    """Every link in pasted text (one per line, or mixed with other words). Links without https:// work too."""
    links = [u.rstrip(").,;!?»”'") for u in URL_RE.findall(text or "")]
    rest = URL_RE.sub(" ", text or "")
    links += ["https://" + u.rstrip(").,;!?»”'") for u in BARE_RE.findall(rest)]
    seen, out = set(), []
    for u in links:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def site_of(url, extractor=""):
    k = (extractor or "").lower().split(":")[0]
    if k in SITE_NAMES:
        return SITE_NAMES[k]
    host = re.sub(r"^(www|m|mobile|vm|vt)\.", "", (re.findall(r"https?://([^/]+)", url) or [""])[0].lower())
    for key, name in (("youtu", "YouTube"), ("instagram", "Instagram"), ("tiktok", "TikTok"), ("x.com", "X"),
                      ("twitter", "X"), ("facebook", "Facebook"), ("fb.watch", "Facebook"), ("reddit", "Reddit"),
                      ("vimeo", "Vimeo"), ("pin", "Pinterest"), ("snapchat", "Snapchat"), ("twitch", "Twitch"),
                      ("threads", "Threads")):
        if key in host:
            return name
    return host.split(":")[0] or "Other"


def safe_name(name, limit=90):
    name = re.sub(r"\s+", " ", "".join(c for c in (name or "") if c not in '/\\:*?"<>|\0')).strip(" .")
    return name[:limit].strip() or "Video"


# ---------------------------------------------------------------- one file per video
# Several videos can have the same title (Instagram calls every video of an account "Video by <account>"), so the
# file name could already belong to ANOTHER video. Then the downloader would skip the new one ("already there")
# and the app would show the old file. Each saved file is recorded with which video it is; a different video
# with the same name gets " (2)", " (3)"…
FILES_FILE = os.path.join(DATA, "files.json")
_names_lock = threading.Lock()
_reserved = set()   # names being saved right now by other downloads


def _norm_url(u):
    return re.sub(r"^https?://(www\.|m\.)?", "", (u or "").split("?")[0].split("#")[0]).rstrip("/").lower()


def _load_files():
    try:
        with open(FILES_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def remember_files(paths, vid, url):
    with _names_lock:
        idx = _load_files()
        for p in paths:
            idx[p] = {"vid": vid, "url": _norm_url(url)}
        with open(FILES_FILE + ".tmp", "w") as f:
            json.dump(idx, f, ensure_ascii=False)
        os.replace(FILES_FILE + ".tmp", FILES_FILE)


def _owner(stem):
    """Which video a saved file with this name (any extension) is, or None if there's no such file."""
    files = [f for f in glob.glob(glob.escape(stem) + ".*") if not f.endswith((".part", ".ytdl"))
             and ".converting." not in f and not re.search(r"\.f[\w-]+\.\w+$", f)]
    if not files:
        return None
    idx = _load_files()
    for f in files:
        if f in idx:
            return idx[f]
    for h in load_history():  # saved before files.json existed
        if set(files) & set(h.get("paths", [])):
            return {"vid": "", "url": _norm_url(h.get("url"))}
    return {"vid": "?", "url": ""}  # a file the app didn't make


def _existing(stem):
    files = [f for f in glob.glob(glob.escape(stem) + ".*") if not f.endswith((".part", ".ytdl", ".json"))
             and ".converting." not in f and not re.search(r"\.f[\w-]+\.\w+$", f)]
    return files[0] if files else None


def to_trash(path):
    """Moves a file to the Trash / Recycle Bin (you can put it back from there)."""
    if WINDOWS:
        return _recycle(path)
    try:
        from Foundation import NSFileManager, NSURL
        ok, _, _ = NSFileManager.defaultManager().trashItemAtURL_resultingItemURL_error_(
            NSURL.fileURLWithPath_(path), None, None)
        if ok:
            return True
    except Exception:
        pass
    trash = os.path.expanduser("~/.Trash")
    dst = os.path.join(trash, os.path.basename(path))
    if os.path.exists(dst):
        dst = os.path.join(trash, f"{time.strftime('%H.%M.%S')} {os.path.basename(path)}")
    shutil.move(path, dst)
    return True


def _recycle(path):
    """Windows: the Recycle Bin (SHFileOperation with "allow undo"). If that fails the old file is kept, renamed."""
    import ctypes
    from ctypes import wintypes

    class SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [("hwnd", wintypes.HWND), ("wFunc", wintypes.UINT), ("pFrom", wintypes.LPCWSTR),
                    ("pTo", wintypes.LPCWSTR), ("fFlags", ctypes.c_ushort), ("fAnyOperationsAborted", wintypes.BOOL),
                    ("hNameMappings", ctypes.c_void_p), ("lpszProgressTitle", wintypes.LPCWSTR)]

    op = SHFILEOPSTRUCTW(wFunc=3, pFrom=os.path.abspath(path) + "\0",   # FO_DELETE; the list ends with two \0
                         fFlags=0x40 | 0x10 | 0x4 | 0x400)              # ALLOWUNDO, NOCONFIRMATION, SILENT, NOERRORUI
    try:
        if ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op)) == 0 and not os.path.exists(path):
            return True
    except Exception:
        pass
    stem, ext = os.path.splitext(path)
    os.replace(path, f"{stem} (old copy {time.strftime('%H.%M.%S')}){ext}")
    return True


def _vid(info):
    return f"{info.get('extractor_key', '')}:{info.get('id', '')}"


def _better_title(info):
    """Instagram titles are just "Video by <account>": use the account and the start of the caption instead."""
    title = info.get("title") or ""
    if info.get("extractor_key", "").lower().startswith("instagram") and re.match(r"(Video|Post|Reel) by ", title):
        who = info.get("channel") or info.get("uploader_id") or info.get("uploader") or title.split(" by ", 1)[-1]
        cap = next((l for l in (info.get("description") or "").splitlines() if re.sub(r"[#@]\S+", "", l).strip()), "")
        cap = re.sub(r"\s+", " ", re.sub(r"[#@]\S+", "", cap)).strip(" -–—·.")
        if len(cap) > 60:
            cap = cap[:60].rsplit(" ", 1)[0] + "…"
        return f"{who} - {cap}" if cap else f"{who} - {info.get('id', '')}"
    return title


class _UniqueName(yt_dlp.postprocessor.PostProcessor):
    """Runs just before the file name is chosen: a clear title, and a name no other video uses."""

    def __init__(self, ydl, job, mine):
        super().__init__(ydl)
        self.job, self.mine = job, mine

    def run(self, info):
        info["title"] = _better_title(info)
        base = info["title"]
        # the day it was posted (sites keep only that, not the day it was filmed), when the setting is on
        day = str(info.get("upload_date") or info.get("release_date") or "")
        if not re.fullmatch(r"\d{8}", day) and info.get("timestamp"):
            day = time.strftime("%Y%m%d", time.localtime(info["timestamp"]))
        info["saver_date"] = (f"{day[:4]}-{day[4:6]}-{day[6:]} "
                              if self.job.get("date_in_name") and re.fullmatch(r"\d{8}", day) else "")
        vid, url = _vid(info), _norm_url(info.get("webpage_url") or info.get("original_url"))
        with _names_lock:
            n = 1
            while True:
                stem = os.path.splitext(self._downloader.prepare_filename(info))[0]
                owner = _owner(stem)
                if stem not in _reserved or stem in self.mine:
                    if owner is None:
                        break
                    if owner["vid"] == vid or (owner["url"] and owner["url"] in (url, _norm_url(self.job["url"]))):
                        # this same video was saved before: keep that file, unless the site now gives it sharper
                        # (e.g. Instagram after logging in): then save the better copy and the old one goes to Trash
                        old = _existing(stem)
                        new_q = min(info.get("width") or 0, info.get("height") or 0)
                        old_q = media_info(old)[1] if old else 0
                        if old and new_q and old_q and new_q > old_q + 8 and info.get("vcodec") != "none":
                            self.job["_upgrade"] = {"old": old, "stem": stem, "title": base, "from": old_q, "to": new_q}
                            info["title"] = f"{base} (better copy)"
                            continue
                        self.job["already"] = True
                        break
                if self.job.get("_upgrade") and info["title"].endswith("(better copy)") and stem.endswith("(better copy)"):
                    break
                n += 1
                info["title"] = f"{base} ({n})"
            _reserved.add(stem)
            self.mine.add(stem)
        return [], info


# ---------------------------------------------------------------- Mac-friendly conversion
def media_info(path):
    """(video codec, quality = the short side, so a vertical 1080x1920 is "1080p", audio codec, seconds)."""
    r = subprocess.run([FFMPEG, "-hide_banner", "-i", path], capture_output=True, text=True, **_NOWIN)
    v = re.search(r"Stream #.*Video: (\w+)", r.stderr)
    h = re.search(r"Stream #.*Video:.*?, (\d{2,5})x(\d{2,5})", r.stderr)
    a = re.search(r"Stream #.*Audio: (\w+)", r.stderr)
    d = re.search(r"Duration: (\d+):(\d+):([\d.]+)", r.stderr)
    dur = int(d.group(1)) * 3600 + int(d.group(2)) * 60 + float(d.group(3)) if d else 0
    return (v.group(1) if v else ""), (min(int(h.group(1)), int(h.group(2))) if h else 0), (a.group(1) if a else ""), dur


def make_mac_friendly(path, progress=None, cancelled=lambda: False):
    vcodec, height, acodec, total = media_info(path)
    video_ok = not vcodec or vcodec in ("h264", "hevc")
    audio_ok = not acodec or acodec in ("aac", "mp3", "alac")
    hev1 = vcodec == "hevc" and "(hev1" in subprocess.run([FFMPEG, "-hide_banner", "-i", path],
                                                           capture_output=True, text=True, **_NOWIN).stderr
    if video_ok and audio_ok and not hev1 and path.lower().endswith((".mp4", ".m4v", ".mov", ".mp3", ".m4a")):
        return path
    out = os.path.splitext(path)[0] + ".mp4"
    tmp = os.path.splitext(path)[0] + ".converting.mp4"
    rate = "45M" if height >= 2000 else "22M" if height >= 1400 else "12M" if height >= 1000 else "6M"
    software = ["-c:v", "libx264", "-crf", "18", "-preset", "fast", "-pix_fmt", "yuv420p"]
    vargs = (["-c:v", "copy"] if video_ok else  # the Mac's hardware encoder; elsewhere the software one
             ["-c:v", "h264_videotoolbox", "-b:v", rate, "-pix_fmt", "yuv420p"] if MAC else software)
    if vcodec == "hevc":
        vargs += ["-tag:v", "hvc1"]  # so QuickTime plays it
    aargs = ["-c:a", "copy"] if audio_ok else ["-c:a", "aac", "-b:a", "192k"]
    base = [FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-i", path]

    def run(cmd):
        p = subprocess.Popen(cmd[:1] + ["-progress", "pipe:1", "-nostats"] + cmd[1:], stdout=subprocess.PIPE,
                             text=True, **_NOWIN)
        for line in p.stdout:
            if cancelled():
                p.kill()
                break
            if line.startswith("out_time_us=") and total and progress:
                try:
                    progress(min(1.0, int(line.split("=", 1)[1]) / 1e6 / total))
                except ValueError:
                    pass
        return p.wait()

    if not _CONVERT_LOCK.acquire(blocking=False):
        if progress:
            progress(None)
        _CONVERT_LOCK.acquire()
    try:
        rc = run(base + vargs + aargs + ["-movflags", "+faststart", tmp])
        if rc != 0 and not video_ok and MAC and not cancelled():  # no hardware encoder: software one
            rc = run(base + software + aargs + ["-movflags", "+faststart", tmp])
        if cancelled():
            raise Cancelled()
        if rc != 0:
            raise RuntimeError("Could not convert the video to a Mac-friendly MP4")
    finally:
        _CONVERT_LOCK.release()
        if cancelled() and os.path.exists(tmp):
            os.remove(tmp)
    os.replace(tmp, out)
    if out != path and os.path.exists(path):
        os.remove(path)
    return out


# ---------------------------------------------------------------- jobs
class Cancelled(Exception):
    pass


class _Log:
    """Keeps yt-dlp's error messages so the page can say what really went wrong, and limits stall reconnects."""

    def __init__(self, job=None):
        self.errors, self.job, self.ydl, self.reconnects = [], job, None, 0

    def debug(self, msg):
        if "Re-extracting data" in msg and self.ydl:  # a stalled download was reconnected
            self.reconnects += 1
            if self.job is not None:
                self.job["detail"] = "Download stalled, reconnecting…"
            if self.reconnects >= 3:  # the line itself is this slow: stop reconnecting, just carry on
                self.ydl.params["throttledratelimit"] = None

    info = warning = debug

    def error(self, msg):
        self.errors.append(msg)


def public(job):
    return {k: v for k, v in job.items() if not k.startswith("_")}


def add(links, quality=None):
    s = load_settings()
    quality = quality if quality in QUALITIES else s["quality"]
    made = []
    for url in links:
        busy = [j for j in JOBS.values() if j["url"] == url and j["status"] in ("waiting", "working")]
        if busy:
            continue
        jid = uuid.uuid4().hex[:10]
        job = {"id": jid, "url": url, "site": site_of(url), "quality": quality, "quality_label": QUALITIES[quality][0],
               "status": "waiting", "detail": "Waiting…", "progress": 0, "title": "", "thumbnail": "", "uploader": "",
               "duration": 0, "count": 1, "index": 1, "paths": [], "error": "", "added": time.time(),
               "_cancel": False}
        JOBS[jid] = job
        threading.Thread(target=_run, args=(job,), daemon=True).start()
        made.append(jid)
    return made


def cancel(jid):
    j = JOBS.get(jid)
    if j and j["status"] in ("waiting", "working"):
        j["_cancel"] = True
        j["detail"] = "Stopping…"


def retry(jid):
    j = JOBS.pop(jid, None)
    if j:
        return add([j["url"]], j["quality"])
    return []


def clear_finished():
    for jid in [k for k, j in JOBS.items() if j["status"] in ("done", "error", "cancelled")]:
        JOBS.pop(jid, None)


def busy():
    return [j["title"] or j["url"] for j in JOBS.values() if j["status"] in ("waiting", "working")]


def _friendly_error(e, job, browser):
    msg = re.sub(r"\x1b\[[0-9;]*m", "", str(e)).replace("ERROR: ", "")
    low = msg.lower()
    login = any(w in low for w in ("login", "log in", "logged-in", "logged in", "sign in", "cookies", "private", "rate-limit", "rate limit",
                                   "authentication", "confirm you", "not a bot", "age", "inappropriate",
                                   "followers", "unavailable for certain audiences"))
    if login and not browser:
        return (f"{job['site']} wants you to be logged in for this one. Open Settings → \"Use my login from\" and "
                f"pick the browser where you're logged in to {job['site']}, then press Try again.")
    if login and browser:
        return (f"{job['site']} still refused, even with your {browser.title()} login. Make sure you're logged in "
                f"to {job['site']} in {browser.title()} and can watch it there, then Try again. ({msg[:160]})")
    if "unsupported url" in low:
        return f"This link isn't a video page {APP_NAME} knows. Copy the link of the post/video itself and try again."
    if "no video" in low or "there is no video" in low:
        return "There's no video in this post (only pictures or text)."
    if WINDOWS and browser and browser != "firefox" and ("cookie" in low or "decrypt" in low or "dpapi" in low):
        return (f"Windows doesn't let other apps read {browser.title()}'s login (Chrome, Edge, Brave, Opera and "
                "Vivaldi lock it). Log in to the site in Firefox and pick Firefox in Settings → \"Use my login from\".")
    if "failed to load cookies" in low and browser:
        return (f"Couldn't read your {browser.title()} login. Open Settings and press Test next to "
                "\"Use my login from\": it says what to do.")
    if "keyring" in low or "keychain" in low or "decrypt" in low or "operation not permitted" in low:
        return (f"Couldn't read your {browser.title() or 'browser'} login. If the Mac asked for your password for "
                f"\"Safe Storage\", choose Always Allow. For Safari, give {APP_NAME} Full Disk Access in System "
                "Settings → Privacy & Security. Or pick another browser in Settings.")
    if "requested format is not available" in low:
        return "That quality isn't available for this video. Try a lower quality or Best."
    return msg[:400] + "  (If a site stopped working, press Settings → Update downloader.)"


def _run(job):
    with _SLOTS:
        if job["_cancel"]:
            job.update(status="cancelled", detail="Stopped")
            return
        s = load_settings()
        job.update(status="working", detail="Looking at the link…" + (
            " (YouTube takes about 20 seconds)" if job["site"] == "YouTube" else ""))
        label, height = QUALITIES[job["quality"]]
        folder = os.path.expanduser(s["folder"] or DEFAULTS["folder"])
        done_paths = []
        log = _Log(job)
        mine = set()   # file names this download reserved

        def hook(d):
            if job["_cancel"]:
                raise Cancelled()
            info = d.get("info_dict") or {}
            if info and not job["title"]:
                job.update(title=info.get("title") or info.get("description", "")[:80] or job["title"],
                           thumbnail=info.get("thumbnail") or job["thumbnail"],
                           uploader=info.get("uploader") or info.get("channel") or info.get("uploader_id") or "",
                           duration=info.get("duration") or 0,
                           site=site_of(job["url"], info.get("extractor_key", "")))
            n, i = info.get("n_entries") or info.get("playlist_count"), info.get("playlist_index")
            if n and i:
                job.update(count=n, index=i)
            if d.get("status") == "downloading":
                tot = d.get("total_bytes") or d.get("total_bytes_estimate")
                part = d.get("downloaded_bytes", 0) / tot if tot else 0
                each = 100 / max(1, job["count"])
                job["progress"] = min(97, round((job["index"] - 1) * each + part * each * 0.95))
                sp, eta = d.get("speed"), d.get("eta")
                extra = (f" · {sp / 1e6:.1f} MB/s" if sp else "") + (f" · {int(eta)} s left" if eta else "")
                many = f" ({job['index']} of {job['count']})" if job["count"] > 1 else ""
                job["detail"] = f"Downloading{many}{extra}"
            elif d.get("status") == "finished":
                job["detail"] = "Putting video and sound together…" if height else "Making the MP3…"

        def post(path):  # called with each final file
            done_paths.append(path)

        try:
            os.makedirs(folder, exist_ok=True)
            opts = {
                "paths": {"home": folder, "temp": os.path.join(DATA, "partial")},
                "outtmpl": (safe_name(job["site"], 40) + "/" if s["site_folders"] else "")
                           + "%(saver_date|)s%(playlist_index&{} - |)s%(title).90B.%(ext)s",
                "windowsfilenames": True,
                "ffmpeg_location": FFMPEG, "js_runtimes": JS_RUNTIMES, "quiet": True, "no_warnings": True,
                "noplaylist": True, "playlistend": 300, "retries": 15, "fragment_retries": 15, "continuedl": True,
                "socket_timeout": 20,  # a connection that hangs is dropped and retried, not waited on
                # stall protection: below 50 KB/s the link is fetched again on a fresh connection (a stuck server
                # or a throttled one), and big files come in 10 MB pieces (YouTube slows unbroken downloads)
                "throttledratelimit": 50_000, "http_chunk_size": 10_485_760,
                "progress_hooks": [hook], "post_hooks": [post], "ignoreerrors": "only_download",
                "noprogress": True, "updatetime": False, "logger": log,  # file date = when you saved it, so it's on top in Finder
            }
            if height:
                # "res" is the SHORT side, so 1080p means 1080x1920 for a vertical Reel/Short/TikTok too (a height
                # limit would pick 608x1080). Order: sharpest, then smoothest (60fps), then the Mac-friendly codec
                # (H.264 avoids a lossy conversion), then the highest bitrate.
                opts.update(format="bv*+ba/b", merge_output_format="mp4",
                            format_sort=(["res", "fps"] if job["quality"] == "best" else [f"res:{height}", "fps"])
                            + [FAST_SORT, "br"])
            else:
                opts.update(format="ba/b", postprocessors=[{"key": "FFmpegExtractAudio", "preferredcodec": "mp3",
                                                             "preferredquality": "192"}])
            if s["browser"]:
                prof = login_profile(s["browser"], job["site"])
                opts["cookiesfrombrowser"] = (s["browser"], prof) if prof else (s["browser"],)
            with yt_dlp.YoutubeDL(opts) as ydl:
                log.ydl = ydl
                job["date_in_name"] = bool(s.get("date_in_name"))
                ydl.add_post_processor(_UniqueName(ydl, job, mine), when="video")
                info = ydl.extract_info(job["url"], download=True)
            if job["_cancel"]:
                raise Cancelled()
            if info and not job["title"]:
                job.update(title=info.get("title") or "", thumbnail=info.get("thumbnail") or "")
            if not done_paths:  # already saved before: yt-dlp skips it, so find the existing file
                for e in (info.get("entries") or [info]) if info else []:
                    for r in (e or {}).get("requested_downloads") or []:
                        if r.get("filepath") and os.path.exists(r["filepath"]):
                            done_paths.append(r["filepath"])
            if not done_paths:
                raise RuntimeError(log.errors[-1] if log.errors else
                                   "There's no video in this post, or it couldn't be downloaded.")
            final = []
            for k, p in enumerate(dict.fromkeys(done_paths)):
                if height and s["mac_friendly"]:
                    def conv(frac, k=k):
                        if frac is None:
                            job["detail"] = "Waiting for another video to finish converting…"
                        else:
                            job["detail"] = "Making it Mac-friendly (H.264)… " + f"{round(frac * 100)}%"
                            job["progress"] = 97 + min(2, int(frac * 3))
                    p = make_mac_friendly(p, conv, lambda: job["_cancel"])
                stem, ext = os.path.splitext(p)
                if stem.endswith("...") and not os.path.exists(stem[:-3].rstrip() + "…" + ext):
                    os.replace(p, stem[:-3].rstrip() + "…" + ext)
                    p = stem[:-3].rstrip() + "…" + ext
                final.append(p)
            up = job.get("_upgrade")
            if up and len(final) == 1 and os.path.exists(final[0]):
                target = up["stem"] + os.path.splitext(final[0])[1]
                to_trash(up["old"])
                os.replace(final[0], target)
                final = [target]
                job["title"] = up["title"]
                job["upgraded"] = f"Replaced your earlier {up['from']}p copy with {up['to']}p (the old one is in the Trash)"
            vids = [_vid(e) for e in ((info.get("entries") or [info]) if info else []) if e]
            remember_files(final, vids[0] if len(vids) == 1 else "", job["url"])
            job.update(status="done", progress=100, paths=final,
                       detail=job.get("upgraded") or ("Already in your folder (saved before)" if job.get("already") else ""))
            _, got, _, dur = media_info(final[0])
            job["height"] = got
            add_history({"id": job["id"], "url": job["url"], "site": job["site"], "title": job["title"] or
                         os.path.splitext(os.path.basename(final[0]))[0], "uploader": job["uploader"],
                         "thumbnail": job["thumbnail"], "quality": label, "height": got,
                         "duration": job["duration"] or dur, "paths": final, "saved": time.time()})
            if s["notify"]:
                notify(f"Saved to {os.path.basename(folder)}", job["title"] or os.path.basename(final[0]))
            if s["reveal_when_done"]:
                reveal(final[0])
        except Cancelled:
            job.update(status="cancelled", detail="Stopped", progress=0)
        except Exception as e:
            job.update(status="error", error=_friendly_error(e, job, s["browser"]), detail="")
        finally:
            with _names_lock:
                _reserved.difference_update(mine)


# ---------------------------------------------------------------- "Use my login from" test
LOGIN_COOKIES = {"Instagram": ("instagram.com", "sessionid"), "TikTok": ("tiktok.com", "sessionid"),
                 "YouTube": ("youtube.com", "SAPISID"), "X": ("x.com", "auth_token"),
                 "Facebook": ("facebook.com", "c_user"), "Threads": ("threads.com", "sessionid"),
                 "Reddit": ("reddit.com", "reddit_session"), "Pinterest": ("pinterest.com", "_auth")}


class _Bar:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def print(self, *a):
        pass


class _CookieLog:
    def __init__(self):
        self.lines = []

    def debug(self, msg, *a, **k):
        self.lines.append(str(msg))

    info = warning = error = debug

    def progress_bar(self):
        return _Bar()


def test_login(browser):
    """Reads the browser's login the same way downloads do and says plainly what worked or why not."""
    if not browser:
        return {"ok": False, "message": "Pick a browser first."}
    from yt_dlp.cookies import extract_cookies_from_browser, _get_chromium_based_browser_settings
    log, name = _CookieLog(), browser.title()
    if WINDOWS and browser != "firefox":
        return {"ok": False, "message": (
            f"On Windows, {name} locks its logins so no other app can read them (Chrome, Edge, Brave, Opera and "
            f"Vivaldi all do this now). Use Firefox instead: log in to the site in Firefox, pick Firefox here and "
            f"press Test again.")}
    if browser not in ("firefox", "safari"):  # Chrome-type browsers: can the app see the folder at all?
        root = _get_chromium_based_browser_settings(browser)["browser_dir"]
        try:
            entries = os.listdir(root)
        except FileNotFoundError:
            return {"ok": False, "message": f"{name} hasn't been used on this Mac (no {name} data). Pick another browser."}
        except PermissionError:
            return {"ok": False, "message": (
                f"macOS is blocking {APP_NAME} from reading {name}'s files. Open System Settings → Privacy & Security → "
                f"Full Disk Access, switch on {APP_NAME} (press + and pick it from Applications if it isn't listed), "
                f"then quit and reopen {APP_NAME} and press Test again.")}
        profiles = [e for e in entries if e == "Default" or e.startswith("Profile ")]
        if not profiles:
            return {"ok": False, "message": f"{name} is installed but has no profile with logins yet. Open {name}, "
                                            "log in to Instagram there, then Test again."}
    try:
        found = {}   # profile -> sites logged in there
        for prof in _profiles(browser):
            jar = extract_cookies_from_browser(browser, prof, logger=log)
            found[prof] = _sites_in(jar)
            ig = sorted({c.name for c in jar if c.domain.lstrip(".").lower().endswith("instagram.com")})
    except Exception as e:
        err = f"{type(e).__name__}: {e}"
        if isinstance(e, PermissionError) or "not permitted" in err.lower():
            msg = (f"macOS blocked {APP_NAME} from reading {name}'s files. Open System Settings → Privacy & Security → "
                   f"Full Disk Access, switch on {APP_NAME} (press + and pick it from Applications if it isn't "
                   f"listed), then quit and reopen {APP_NAME} and press Test again.")
        elif isinstance(e, FileNotFoundError):
            msg = f"{name} has no saved logins on this Mac yet. Open {name}, log in to the site, then Test again."
        else:
            msg = f"Couldn't read {name}'s login: {err[:200]}"
        return {"ok": False, "message": msg, "log": log.lines[-6:]}
    if any("find-generic-password failed" in l for l in log.lines):
        return {"ok": False, "log": log.lines[-6:], "message": (
            f"The Mac didn't give {APP_NAME} the key to {name}'s logins. Press Test again: when the Mac asks for "
            f"\"{name} Safe Storage\", type your Mac password and click Always Allow.")}
    _login_cache.clear()
    sites = [x for x in LOGIN_COOKIES if any(x in v for v in found.values())]
    return {"ok": True, "profiles": len(found), "sites": sites, "instagram_cookie_names": ig,
            "skipped": [l for l in log.lines if "decrypt" in l.lower() or "skipp" in l.lower()][-3:],
            "message": (f"Working. Logged in to: {', '.join(sites)}." if sites else
                        f"Read {name}, but you're not logged in to Instagram, TikTok, YouTube or X there. "
                        f"Log in to them in {name}, then Test again.")}


def _profiles(browser):
    """Every profile of a Chrome-type browser (Default, Profile 1…); [None] = the browser's own choice."""
    if browser in ("firefox", "safari"):
        return [None]
    from yt_dlp.cookies import _get_chromium_based_browser_settings
    root = _get_chromium_based_browser_settings(browser)["browser_dir"]
    try:
        profs = sorted(e for e in os.listdir(root) if (e == "Default" or e.startswith("Profile "))
                       and (os.path.exists(os.path.join(root, e, "Cookies"))
                            or os.path.exists(os.path.join(root, e, "Network", "Cookies"))))
    except OSError:
        return [None]
    return profs or [None]


def _sites_in(jar):
    have = {(c.domain.lstrip(".").lower(), c.name) for c in jar}
    return [site for site, (dom, key) in LOGIN_COOKIES.items()
            if any(d == dom or d.endswith("." + dom) for d, n in have if n == key)]


_login_cache = {}   # (browser, site) -> (profile, time)


def login_profile(browser, site):
    """The profile of `browser` that is logged in to `site` (several Chrome profiles = several accounts)."""
    hit = _login_cache.get((browser, site))
    if hit and time.time() - hit[1] < 600:
        return hit[0]
    best = None
    profs = _profiles(browser)
    if len(profs) > 1 and site in LOGIN_COOKIES:
        from yt_dlp.cookies import extract_cookies_from_browser
        for prof in profs:
            try:
                if site in _sites_in(extract_cookies_from_browser(browser, prof, logger=_CookieLog())):
                    best = prof
                    break
            except Exception:
                pass
    _login_cache[(browser, site)] = (best, time.time())
    return best


# ---------------------------------------------------------------- Mac helpers
def notify(title, message):
    if WINDOWS:
        return _toast(title, message)
    q = lambda t: '"' + t.replace("\\", "\\\\").replace('"', '\\"') + '"'
    subprocess.run(["osascript", "-e", f"display notification {q(message[:120])} with title {q(APP_NAME)} "
                                       f"subtitle {q(title)}"], capture_output=True)


def _toast(title, message):
    """Windows 10/11 notification (through PowerShell, which every Windows has; nothing to install)."""
    x = lambda t: (t or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("'", "''")
    ps = ("[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null;"
          "[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] > $null;"
          "$x = New-Object Windows.Data.Xml.Dom.XmlDocument;"
          f"$x.LoadXml('<toast><visual><binding template=\"ToastGeneric\"><text>{x(APP_NAME)}: {x(title)}</text>"
          f"<text>{x(message[:120])}</text></binding></visual></toast>');"
          "$id = '{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\\WindowsPowerShell\\v1.0\\powershell.exe';"
          "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($id).Show("
          "[Windows.UI.Notifications.ToastNotification]::new($x))")
    try:
        import base64   # -EncodedCommand: no quoting problems with titles that have quotes in them
        subprocess.Popen(["powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand",
                          base64.b64encode(ps.encode("utf-16-le")).decode()], **_NOWIN)
    except OSError:
        pass


def reveal(path):
    """Show the file in Finder (Mac) or File Explorer (Windows), selected."""
    if path and os.path.exists(path):
        if WINDOWS:
            subprocess.Popen(f'explorer /select,"{os.path.normpath(path)}"')
        else:
            subprocess.run(["open", "-R", path])
        return True
    return False


def open_path(path):
    if path and os.path.exists(path):
        if WINDOWS:
            os.startfile(path)
        else:
            subprocess.run(["open", path])
        return True
    return False


_update = {"state": "idle", "detail": ""}


def update_downloader(background=False):
    """Sites change often; a newer yt-dlp fixes most "it stopped working" problems. Used on the next start."""
    if _update["state"] == "working":
        return _update
    _update.update(state="working", detail="Updating the downloader…")

    def go():
        if FROZEN:
            return _update_frozen()
        uv = shutil.which("uv") or os.path.expanduser("~/.local/bin/uv")
        cmd = ([uv, "pip", "install", "-q", "--python", sys.executable, "-U", "yt-dlp[default]"] if os.path.exists(uv)
               else [sys.executable, "-m", "pip", "install", "-q", "-U", "yt-dlp[default]"])
        r = subprocess.run(cmd, capture_output=True, text=True)
        out = subprocess.run([sys.executable, "-c", "import yt_dlp;print(yt_dlp.version.__version__)"],
                             capture_output=True, text=True).stdout.strip()
        save_settings({"last_update_check": time.time()})
        if r.returncode == 0:
            now = yt_dlp.version.__version__
            _update.update(state="done", detail=(f"Updated to {out}. Quit and reopen {APP_NAME} to use it."
                                                 if out and out != now else f"Already the newest ({now})."))
        else:
            _update.update(state="error", detail="Couldn't update (no internet?) " + r.stderr[-200:])

    t = threading.Thread(target=go, daemon=True)
    t.start()
    return _update


def _update_frozen():
    """Self-contained app: pip can't install into it, so fetch the newest yt-dlp (and the YouTube helper scripts
    version it asks for) straight from PyPI into PYLIB, checking each file's fingerprint (sha256)."""
    import hashlib, io, ssl, urllib.request, zipfile
    try:
        import certifi
        ctx = ssl.create_default_context(cafile=certifi.where())
    except Exception:
        ctx = ssl.create_default_context()
    get = lambda u, t=60: urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": APP_NAME}),
                                                 timeout=t, context=ctx).read()
    now = yt_dlp.version.__version__
    try:
        meta = json.loads(get("https://pypi.org/pypi/yt-dlp/json"))
        newest = meta["info"]["version"]
        save_settings({"last_update_check": time.time()})
        if _vtuple(newest) <= _vtuple(now):
            return _update.update(state="done", detail=f"Already the newest ({now}).")
        ejs = next((re.search(r"==\s*([\w.]+)", r).group(1) for r in meta["info"].get("requires_dist") or []
                    if r.startswith("yt-dlp-ejs") and "==" in r), None)
        wanted = [("yt_dlp", meta)] + ([("yt_dlp_ejs", json.loads(get(f"https://pypi.org/pypi/yt-dlp-ejs/{ejs}/json")))]
                                       if ejs else [])
        new = PYLIB + ".new"
        shutil.rmtree(new, ignore_errors=True)
        os.makedirs(new)
        for top, m in wanted:
            whl = next(u for u in m["urls"] if u["packagetype"] == "bdist_wheel" and u["filename"].endswith("-any.whl"))
            data = get(whl["url"], 300)
            if hashlib.sha256(data).hexdigest() != whl["digests"]["sha256"]:
                raise RuntimeError("the download was damaged, try again")
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                z.extractall(new, [n for n in z.namelist() if n.startswith(top + "/")])
        old = PYLIB + ".old"
        shutil.rmtree(old, ignore_errors=True)
        if os.path.exists(PYLIB):
            os.replace(PYLIB, old)
        os.replace(new, PYLIB)
        shutil.rmtree(old, ignore_errors=True)
        _update.update(state="done", detail=f"Updated to {newest}. Quit and reopen {APP_NAME} to use it.")
    except Exception as e:
        _update.update(state="error", detail=f"Couldn't update (no internet?) {str(e)[:200]}")


def auto_update():
    """Once a week, quietly fetch the newest downloader (it's used from the next start)."""
    if time.time() - load_settings().get("last_update_check", 0) > 7 * 86400:
        update_downloader(background=True)
