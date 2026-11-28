"""Video Saver: the download engine (shared, unchanged, by Video Saver and Link Transcriber's "Save a video").

Paste a link from YouTube, Instagram, TikTok, X, Facebook, Reddit, Vimeo, Pinterest, Snapchat, Twitch…
(anything yt-dlp knows) and the video is saved into the Finder folder you chose, made Mac-friendly (H.264/AAC)
so it opens in QuickTime, iMovie, CapCut and ThumbStudio Video.
"""
import glob, json, logging, os, re, shutil, subprocess, sys, threading, time, uuid

MAC, WINDOWS = sys.platform == "darwin", os.name == "nt"
# FROZEN = the self-contained app (PyInstaller: Python and every package inside the app). Link Transcriber and the
# older Video Saver run from a Python setup instead, where updates are pip-installed.
FROZEN = getattr(sys, "frozen", False)
BUNDLE = getattr(sys, "_MEIPASS", "")   # the frozen app's own files

# Each app keeps its own settings and saved list: Link Transcriber sets SAVER_DATA / SAVER_FOLDER / SAVER_APP first.
DATA = os.environ.get("SAVER_DATA") or (
    os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "Video Saver") if WINDOWS
    else os.path.expanduser("~/Library/Application Support/Video Saver"))
APP_NAME = os.environ.get("SAVER_APP") or "ThumbStudio Video Saver"
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

JOBS = {}          # id -> job (this session, plus paused / unfinished ones from last time: see restore_queue)
PARTIAL = os.path.join(DATA, "partial")        # half-downloaded pieces, one folder per save (so Pause can resume)
QUEUE_FILE = os.path.join(DATA, "queue.json")  # paused and unfinished saves, kept across quitting / restarting
PAUSED_TEXT = "Paused · press Resume to carry on from here"
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
# ---------------------------------------------------------------- add the date to videos saved before
DATED = re.compile(r"^\d{4}-\d{2}-\d{2} ")
RENAME_HOOKS = []   # f(old path, new path), e.g. Link Transcriber keeps its transcripts pointing at the renamed file
DATING = {"state": "", "done": 0, "total": 0, "renamed": 0, "detail": ""}
_dating_lock = threading.Lock()


def _day_of(info):
    """The day a video was posted, as "2026-11-24", or "" if the site doesn't say."""
    day = str(info.get("upload_date") or info.get("release_date") or "")
    if not re.fullmatch(r"\d{8}", day) and info.get("timestamp"):
        day = time.strftime("%Y%m%d", time.localtime(info["timestamp"]))
    return f"{day[:4]}-{day[4:6]}-{day[6:]}" if re.fullmatch(r"\d{8}", day) else ""


class _Quiet:
    def debug(self, m): pass
    warning = error = info = debug


def _lookup_day(url, s):
    opts = {"quiet": True, "no_warnings": True, "skip_download": True, "noplaylist": True, "socket_timeout": 20,
            "js_runtimes": JS_RUNTIMES, "ffmpeg_location": FFMPEG, "logger": _Quiet()}
    if s["browser"]:
        prof = login_profile(s["browser"], site_of(url))
        opts["cookiesfrombrowser"] = (s["browser"], prof) if prof else (s["browser"],)
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False, process=False) or {}
        day = _day_of(info)
        if not day and info.get("_type") in ("url", "url_transparent"):  # a short link: follow it
            day = _day_of(ydl.extract_info(info["url"], download=False, process=False) or {})
    return day


def _undated(h):
    return [p for p in h.get("paths", []) if os.path.exists(p) and not DATED.match(os.path.basename(p))]


def dating_status():
    todo = sum(1 for h in load_history() if _undated(h))
    return dict(DATING, todo=todo)


def add_dates():
    """Starts the posting day at the front of every saved video's name that doesn't have one yet (in the background)."""
    with _dating_lock:
        if DATING["state"] == "working":
            return dating_status()
        if busy():
            DATING.update(state="error", detail="Wait until the videos saving now are done, then try again.")
            return dating_status()
        DATING.update(state="working", done=0, total=0, renamed=0, detail="Looking up the dates…")
    threading.Thread(target=_date_all, daemon=True).start()
    return dating_status()


def _date_all():
    s = load_settings()
    todo = [h for h in load_history() if _undated(h)]
    DATING["total"] = len(todo)
    missing = 0
    for k, h in enumerate(todo):
        DATING["detail"] = f"Adding dates… {k + 1} of {len(todo)}"
        try:
            day = h.get("posted") or _lookup_day(h["url"], s)
        except Exception:
            day = ""
        if not day:
            missing += 1
        else:
            moved = {}
            for p in _undated(h):
                folder, name = os.path.split(p)
                new = os.path.join(folder, f"{day} {name}")
                stem, ext = os.path.splitext(new)
                n = 2
                while os.path.exists(new):
                    new = f"{stem} ({n}){ext}"
                    n += 1
                try:
                    os.rename(p, new)
                    moved[p] = new
                except OSError:
                    missing += 1
            _moved(h["id"], day, moved)
            DATING["renamed"] += len(moved)
        DATING["done"] = k + 1
    n = DATING["renamed"]
    DATING.update(state="done", detail=(f"Added the date to {n} video{'s' if n != 1 else ''}." if n else "No names to change.")
                  + (f" {missing} couldn't get a date (the post is gone, private, or the site doesn't say)." if missing else ""))


def _moved(hid, day, moved):
    """Keeps the saved list, the file index and Link Transcriber pointing at the new names."""
    with _lock:
        items = load_history()
        for h in items:
            if h.get("id") == hid:
                h["posted"] = day
            h["paths"] = [moved.get(p, p) for p in h.get("paths", [])]
        _save_history(items)
    with _names_lock:
        idx = {moved.get(k, k): v for k, v in _load_files().items()}
        with open(FILES_FILE + ".tmp", "w") as f:
            json.dump(idx, f, ensure_ascii=False)
        os.replace(FILES_FILE + ".tmp", FILES_FILE)
    for old, new in moved.items():
        for hook in RENAME_HOOKS:
            try:
                hook(old, new)
            except Exception:
                pass


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
        # the day it was posted (sites keep only that, not the day it was filmed): at the start of the name when
        # the setting is on, and kept in the saved list either way (so "Add dates" needs no lookup later)
        self.job["posted"] = _day_of(info)
        info["saver_date"] = self.job["posted"] + " " if self.job.get("date_in_name") and self.job["posted"] else ""
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
class Cancelled(yt_dlp.utils.DownloadCancelled):
    """Pause / Stop. yt-dlp passes its own "cancelled" signal straight up (no retries, no "error"), so raising it from
    the logger or a hook stops the work at its next step: while looking at the link, between retries, before merging."""


# ffmpeg runs that yt-dlp starts (merging video + sound) per save, so Pause / Stop can close them at once
_PROCS = {}   # thread id -> ffmpeg processes it started
try:
    import yt_dlp.postprocessor.ffmpeg as _ffpp

    class _TrackedPopen(_ffpp.Popen):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            _PROCS.setdefault(threading.get_ident(), set()).add(self)

    _ffpp.Popen = _TrackedPopen
except Exception:
    pass


def _kill_work(job):
    for proc in list(_PROCS.get(job.get("_tid"), ())):
        try:
            if proc.poll() is None:
                proc.kill()
        except Exception:
            pass


class _Log:
    """Keeps yt-dlp's error messages so the page can say what really went wrong, and limits stall reconnects."""

    def __init__(self, job=None):
        self.errors, self.job, self.ydl, self.reconnects = [], job, None, 0

    def debug(self, msg):
        if self.job is not None and self.job["_cancel"]:  # yt-dlp says something at almost every step
            raise Cancelled()
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


def _new_job(url, quality, jid=None, **keep):
    quality = quality if quality in QUALITIES else load_settings()["quality"]
    job = {"id": jid or uuid.uuid4().hex[:10], "url": url, "site": site_of(url), "quality": quality,
           "quality_label": QUALITIES[quality][0], "status": "waiting", "detail": "Waiting…", "progress": 0, "title": "",
           "thumbnail": "", "uploader": "", "duration": 0, "count": 1, "index": 1, "paths": [], "error": "",
           "added": time.time(), "size": 0, "got": 0, "pending": [], "vids": [], "_cancel": False, "_pause": False,
           "_done": threading.Event(), "_after": None}
    job.update({k: v for k, v in keep.items() if k in job and v is not None and k not in ("id", "url", "quality")})
    return job


def _start(job):
    JOBS[job["id"]] = job
    _save_queue()
    threading.Thread(target=_run, args=(job,), daemon=True).start()


def add(links, quality=None):
    made = []
    for url in links:
        same = [j for j in JOBS.values() if j["url"] == url and j["status"] in ("waiting", "working", "paused")]
        if same:  # already saving it, or paused: pasting it again carries on
            if same[0]["status"] == "paused":
                resume(same[0]["id"])
                made.append(same[0]["id"])
            continue
        job = _new_job(url, quality)
        _start(job)
        made.append(job["id"])
    return made


def pause(jid):
    """Stops the download but keeps what came in so far; Resume carries on from there. The card says Paused at once;
    the download itself stops at its next step (Resume waits for that before it touches the same files)."""
    j = JOBS.get(jid)
    if j and j["status"] in ("waiting", "working"):
        j["_pause"] = j["_cancel"] = True
        j.update(status="paused", detail=PAUSED_TEXT)
        _kill_work(j)
        _save_queue()


def resume(jid):
    j = JOBS.get(jid)
    if not j or j["status"] != "paused":
        return False
    fresh = _new_job(j["url"], j["quality"], jid=jid, **{k: j.get(k) for k in _QUEUE_KEYS})
    fresh["_after"] = j["_done"]   # the paused download may still be winding down
    _start(fresh)
    return True


def cancel(jid):
    j = JOBS.get(jid)
    if not j:
        return
    if j["status"] == "paused":  # Stop on a paused save: forget it and its half-downloaded pieces
        JOBS.pop(jid, None)
        j["_pause"] = False
        if j["_done"].is_set():
            _drop_partial(jid)
        # else: the download is still winding down; it throws its pieces away when it ends (see _stopped)
        _save_queue()
    elif j["status"] in ("waiting", "working"):
        j["_pause"], j["_cancel"] = False, True
        j.update(status="cancelled", detail="Stopped", progress=0)
        _kill_work(j)
        _save_queue()


def retry(jid):
    """Try again on the same save (and the same temp folder), so a failed download carries on where it stopped."""
    j = JOBS.get(jid)
    if not j or j["status"] in ("waiting", "working"):
        return []
    fresh = _new_job(j["url"], j["quality"], jid=jid, title=j.get("title"), thumbnail=j.get("thumbnail"))
    fresh["_after"] = j["_done"]
    _start(fresh)
    return [jid]


def clear_finished():
    for jid in [k for k, j in JOBS.items() if j["status"] in ("done", "error", "cancelled")]:
        JOBS.pop(jid, None)


def busy():
    """Saves still running (a paused one doesn't count: it doesn't hold anything up)."""
    return [j["title"] or j["url"] for j in JOBS.values() if j["status"] in ("waiting", "working")]


# ---------------------------------------------------------------- paused / unfinished saves survive a restart
_QUEUE_KEYS = ("title", "thumbnail", "site", "uploader", "duration", "added", "size", "got", "progress", "pending",
               "vids", "count", "index")
_queue_lock = threading.Lock()
_restored = False


def _save_queue():
    with _queue_lock:
        items = [dict({k: j.get(k) for k in ("id", "url", "quality") + _QUEUE_KEYS}, paused=j["status"] == "paused")
                 for j in list(JOBS.values()) if j["status"] in ("waiting", "working", "paused")]
        try:
            with open(QUEUE_FILE + ".tmp", "w") as f:
                json.dump(items, f, ensure_ascii=False)
            os.replace(QUEUE_FILE + ".tmp", QUEUE_FILE)
        except OSError:
            pass


def _drop_partial(jid):
    shutil.rmtree(os.path.join(PARTIAL, jid), ignore_errors=True)


def restore_queue():
    """At start: paused saves come back paused, unfinished ones (the app was quit mid-download) carry on by themselves.
    Half-downloaded pieces that belong to no save any more are cleaned up."""
    global _restored
    if _restored:
        return
    _restored = True
    try:
        with open(QUEUE_FILE) as f:
            items = json.load(f)
    except Exception:
        items = []
    keep = set()
    for it in items:
        if not it.get("url") or not it.get("id"):
            continue
        job = _new_job(it["url"], it.get("quality"), jid=it["id"], **{k: it.get(k) for k in _QUEUE_KEYS})
        keep.add(job["id"])
        if it.get("paused"):
            job.update(status="paused", detail=PAUSED_TEXT)
            JOBS[job["id"]] = job
        else:
            _start(job)
    os.makedirs(PARTIAL, exist_ok=True)
    for name in os.listdir(PARTIAL):
        if name not in keep:
            p = os.path.join(PARTIAL, name)
            try:
                shutil.rmtree(p) if os.path.isdir(p) else os.remove(p)
            except OSError:
                pass
    _save_queue()


def _friendly_error(e, job, browser):
    msg = re.sub(r"\x1b\[[0-9;]*m", "", str(e)).replace("ERROR: ", "")
    low = msg.lower()
    login = any(w in low for w in ("401 unauthorized", "login", "log in", "logged-in", "logged in", "sign in", "cookies", "private", "rate-limit", "rate limit",
                                   "authentication", "confirm you", "not a bot", "age", "inappropriate",
                                   "followers", "unavailable for certain audiences"))
    if login and not browser:
        return (f"{job['site']} wants you to be logged in for this one. Open Settings → \"Use my login from\" and "
                f"pick the browser where you're logged in to {job['site']}, then press Try again.")
    if login and browser:
        return (f"{job['site']} still refused, even with your {browser.title()} login. Make sure you're logged in "
                f"to {job['site']} in {browser.title()} and can watch it there, then Try again. ({msg[:160]})")
    if "unsupported url" in low:
        return f"This link isn't a video or photo page {APP_NAME} knows. Copy the link of the post itself and try again."
    if "no video" in low or "there is no video" in low or "no results" in low:
        return "There's no video or photo in this post (only text), or it was deleted."
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


def nice_size(b):
    return f"{b / 1e9:.1f} GB" if b >= 1e9 else f"{round(b / 1e6)} MB" if b >= 1e6 else f"{round(b / 1e3)} KB" if b else ""


def _count_size(job, info, d):
    """How big the whole download is (video + sound, every video of a list) and how much has come in so far.
    Before a part starts, the site's own size for it is used, so the total is known from the first second."""
    parts = job.setdefault("_parts", {})
    i = job["index"]
    tot = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
    got = d.get("downloaded_bytes") or (tot if d.get("status") == "finished" else 0)
    parts[(i, info.get("format_id") or d.get("filename") or "")] = (got, max(tot, got))
    fmts = info.get("requested_formats") or [info]
    waiting = sum((f.get("filesize") or f.get("filesize_approx") or 0) for f in fmts
                  if (i, f.get("format_id")) not in parts)  # the sound part, before it starts
    job["size"] = sum(t for _, t in parts.values()) + waiting
    job["got"] = min(job["size"], sum(g for g, _ in parts.values()))


def _run(job):
    """One save, in its own thread: waits for an earlier run of the same save to end (after Pause), waits for a free
    slot (up to 3 at once) unless it's paused / stopped meanwhile, then does the work."""
    job["_tid"] = threading.get_ident()
    try:
        if job.get("_after"):
            job["_after"].wait()
        while not _SLOTS.acquire(timeout=0.3):
            if job["_cancel"]:
                _stopped(job)
                _save_queue()
                return
        try:
            if job["_cancel"]:  # paused / stopped just as the slot came free
                _stopped(job)
                _save_queue()
            else:
                _work(job)
        finally:
            _SLOTS.release()
    finally:
        _PROCS.pop(job["_tid"], None)
        job["_done"].set()


def _work(job):
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
        if d.get("status") in ("downloading", "finished"):
            _count_size(job, info, d)
        if d.get("status") == "downloading":
            tot = d.get("total_bytes") or d.get("total_bytes_estimate")
            part = d.get("downloaded_bytes", 0) / tot if tot else 0
            each = 100 / max(1, job["count"])
            job["progress"] = min(97, round((job["index"] - 1) * each + part * each * 0.95))
            sp, eta = d.get("speed"), d.get("eta")
            extra = (f" · {sp / 1e6:.1f} MB/s" if sp else "") + (f" · {int(eta)} s left" if eta else "")
            many = f" ({job['index']} of {job['count']})" if job["count"] > 1 else ""
            of = f" · {nice_size(job['got'])} of {nice_size(job['size'])}" if job.get("size") else ""
            job["detail"] = f"Downloading{many}{of}{extra}"
        elif d.get("status") == "finished":
            job["detail"] = "Putting video and sound together…" if height else "Making the MP3…"

    def stop_check(d):  # before and after each step that follows the download (merging, MP3, moving)
        if job["_cancel"]:
            raise Cancelled()

    def post(path):  # called with each final file
        done_paths.append(path)

    try:
        os.makedirs(folder, exist_ok=True)
        opts = {
            "paths": {"home": folder, "temp": os.path.join(PARTIAL, job["id"])},  # this save's own pieces
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
            "postprocessor_hooks": [stop_check],
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
        pending = job.get("pending") or []
        photos, video_error, vids = [], None, []
        if pending and all(os.path.exists(p) for p in pending):
            # paused while converting: the download itself was finished, so only the conversion is redone
            done_paths, vids = list(pending), job.get("vids") or []
        elif _yt_post(job["url"]):   # a YouTube post holds photos (yt-dlp doesn't read posts)
            photos = save_photos(job, s, folder)
        else:
            try:
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
                vids = [_vid(e) for e in ((info.get("entries") or [info]) if info else []) if e]
            except Cancelled:
                raise
            except Exception as e:   # no video here: it may be a photo post (or the photo downloader knows the site)
                if job["_cancel"] or not photo_link(job["url"]):
                    raise
                video_error = e
            if video_error is not None:
                try:
                    photos = save_photos(job, s, folder)
                except Cancelled:
                    raise
                except Exception as e:
                    raise (e if "no video" in str(video_error).lower() or "unsupported url" in str(video_error).lower()
                           else video_error)
                if not photos:
                    raise video_error
            elif height and MIXED.search(job["url"]):   # a carousel / post with videos AND photos: the photos too
                photos = save_photos(job, s, folder, quiet=True)
        job.update(pending=list(dict.fromkeys(done_paths)), vids=vids)
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
        videos = list(final)
        final += [p for p in photos if p not in final]
        remember_files(final, vids[0] if len(vids) == 1 else "", job["url"])
        job["size"] = sum(os.path.getsize(p) for p in final if os.path.exists(p))  # the real size on disk
        job.update(status="done", progress=100, paths=final, photos=len(photos),
                   detail=job.get("upgraded") or ("Already in your folder (saved before)" if job.get("already") else ""))
        got, dur = (media_info(videos[0])[1], media_info(videos[0])[3]) if videos else (0, 0)
        job["height"] = got
        add_history({"id": job["id"], "url": job["url"], "site": job["site"], "title": job["title"] or
                     os.path.splitext(os.path.basename(final[0]))[0], "uploader": job["uploader"],
                     "thumbnail": job["thumbnail"], "quality": label if videos else "Photos", "height": got,
                     "duration": (job["duration"] or dur) if videos else 0, "paths": final, "saved": time.time(),
                     "posted": job.get("posted", ""), "photos": len(photos)})
        if s["notify"]:
            notify(f"Saved to {os.path.basename(folder)}", job["title"] or os.path.basename(final[0]))
        if s["reveal_when_done"]:
            reveal(final[0])
    except Cancelled:
        _stopped(job)
    except Exception as e:
        if job["_cancel"]:   # stopping made the merge / a request fail: that's the Pause / Stop, not an error
            _stopped(job)
        else:
            job.update(status="error", error=_friendly_error(e, job, s["browser"]), detail="")
    finally:
        with _names_lock:
            _reserved.difference_update(mine)
        if job["status"] == "done":
            job["pending"] = []
            _drop_partial(job["id"])
        _save_queue()


def _stopped(job):
    """After Pause (keep the pieces, show Resume) or Stop (throw the pieces away)."""
    if job.get("_pause"):
        job.update(status="paused", detail=PAUSED_TEXT)
    else:
        job.update(status="cancelled", detail="Stopped", progress=0)
        _drop_partial(job["id"])


# ---------------------------------------------------------------- photos
# Photo posts (Instagram photos and carousels, X, TikTok photo posts, Facebook, Pinterest, Reddit, Tumblr, Bluesky…)
# come from gallery-dl, which asks each site for the original upload (X "orig", Instagram's biggest version). YouTube
# posts are read straight from the post's page. Videos still come from yt-dlp: photos are looked for when a link has
# no video, and also next to the videos of a post that can mix both (an Instagram carousel, an X post).
PHOTO_EXT = {"jpg", "jpeg", "png", "webp", "heic", "heif", "gif", "avif", "bmp", "tif", "tiff"}
MIXED = re.compile(r"instagram\.com/(?:[^/?#]+/)?p/|(?:x|twitter)\.com/[^/?#]+/status/|bsky\.app/profile/[^/]+/post/")
_photo_lock = threading.Lock()   # gallery-dl keeps its settings in one place, so one photo post at a time
_find_lock = threading.Lock()


def _yt_post(url):
    """The id of a YouTube post (youtube.com/post/<id>, or a channel's community tab ?lb=<id>), else ''."""
    if "youtube.com" not in (url or ""):
        return ""
    m = re.search(r"youtube\.com/post/([\w-]+)", url) or re.search(r"[?&]lb=([\w-]+)", url)
    return m.group(1) if m else ""


def photo_link(url):
    """True when the link can hold photos: a site gallery-dl knows, or a YouTube post."""
    if _yt_post(url):
        return True
    with _find_lock:   # gallery-dl loads its list of sites on first use, which isn't safe from two saves at once
        try:
            from gallery_dl import extractor
            return extractor.find(url) is not None
        except Exception:
            return False


def _walk(o, key):
    if isinstance(o, dict):
        for k, v in o.items():
            if k == key:
                yield v
            yield from _walk(v, key)
    elif isinstance(o, list):
        for v in o:
            yield from _walk(v, key)


def _text_of(t):
    return "".join(r.get("text", "") for r in (t or {}).get("runs") or []) or (t or {}).get("simpleText", "")


def _yt_post_photos(job, s, tmp):
    """The photos of a YouTube post at their original size ("=s0" asks YouTube for the uploaded picture)."""
    opts = {"quiet": True, "no_warnings": True, "socket_timeout": 20, "logger": _Quiet()}
    if s["browser"]:
        prof = login_profile(s["browser"], "YouTube")
        opts["cookiesfrombrowser"] = (s["browser"], prof) if prof else (s["browser"],)
    out = []
    with yt_dlp.YoutubeDL(opts) as ydl:
        html = ydl.urlopen(f"https://www.youtube.com/post/{_yt_post(job['url'])}").read().decode("utf-8", "replace")
        m = re.search(r"var ytInitialData\s*=\s*(\{.*?\});\s*</script>", html, re.S)
        if not m:
            return out
        data = json.loads(m.group(1))
        post = next(_walk(data, "backstagePostRenderer"), None) or {}
        meta = {"title": _text_of(post.get("contentText")), "uploader": _text_of(post.get("authorText"))}
        for n, r in enumerate(_walk(post, "backstageImageRenderer"), 1):
            if job["_cancel"]:
                raise Cancelled()
            u = r["image"]["thumbnails"][-1]["url"]
            u = re.sub(r"=[^/=]*$", "", u) + "=s0"
            job["detail"] = f"Saving photo {n}…"
            resp = ydl.urlopen(u)
            ext = {"image/png": "png", "image/webp": "webp", "image/gif": "gif"}.get(
                (resp.headers.get("Content-Type") or "").split(";")[0], "jpg")
            p = os.path.join(tmp, f"{n:03d}.{ext}")
            with open(p, "wb") as f:
                shutil.copyfileobj(resp, f)
            out.append((p, dict(meta), u))
    return out


class _PhotoLog(logging.Handler):
    """Keeps gallery-dl's error messages (from this thread only) so the page can say what went wrong."""

    def __init__(self):
        super().__init__(level=40)
        self.tid, self.errors = threading.get_ident(), []

    def emit(self, record):
        if record.thread == self.tid:
            self.errors.append(record.getMessage())


def _gallery_photos(job, s, tmp):
    """The photos of a post, as the site's original files. Videos and music in the post are skipped here."""
    from gallery_dl import config as gconf, job as gjob, exception as gexc
    found = []

    class _Job(gjob.DownloadJob):
        def handle_url(self, url, kwdict):
            if job["_cancel"]:
                raise gexc.StopExtraction()
            if (kwdict.get("extension") or "").lower() not in PHOTO_EXT:
                return
            n = len(found) + 1
            job["detail"] = f"Saving photo {n}" + (f" of {kwdict['count']}" if kwdict.get("count") else "") + "…"
            super().handle_url(url, kwdict)
            p = self.pathfmt.path
            if p and os.path.exists(p):
                found.append((p, dict(kwdict), url))
                job["got"] = job["size"] = job.get("got", 0) + os.path.getsize(p)

    while not _photo_lock.acquire(timeout=0.3):
        if job["_cancel"]:
            raise Cancelled()
    log = _PhotoLog()
    logging.getLogger().addHandler(log)
    cookies = os.path.join(tmp, "..", "cookies.txt")
    try:
        gconf.clear()
        gconf.set(("cache",), "file", os.path.join(DATA, "photos-cache.sqlite3"))
        gconf.set(("output",), "mode", "null")
        for k, v in {"base-directory": tmp, "directory": [], "videos": False, "audio": False, "timeout": 20,
                     "retries": 3, "skip": False, "image-range": "1-500"}.items():
            gconf.set(("extractor",), k, v)
        if s["browser"]:   # the same login the videos use (read the same way, so it works wherever that works)
            from yt_dlp.cookies import extract_cookies_from_browser
            prof = login_profile(s["browser"], job["site"])
            jar = extract_cookies_from_browser(s["browser"], prof, logger=_CookieLog())
            jar.filename = cookies
            jar.save(ignore_discard=True, ignore_expires=True)
            gconf.set(("extractor",), "cookies", cookies)
        for attempt in range(2):   # a site that is slowing us down sometimes answers with nothing: ask once more
            _Job(job["url"]).run()
            if found or job["_cancel"] or attempt:
                break
            job["detail"] = "Looking for photos again…"
            for _ in range(15):
                if job["_cancel"]:
                    break
                time.sleep(0.2)
    finally:
        logging.getLogger().removeHandler(log)
        gconf.clear()
        _photo_lock.release()
        if os.path.exists(cookies):
            os.remove(cookies)
    if job["_cancel"]:
        raise Cancelled()
    if not found and log.errors:
        raise RuntimeError(log.errors[-1])
    return found


def _photo_meta(kw):
    """Title, who posted it and the posted day, from what gallery-dl tells about a photo (each site names them
    differently)."""
    title = next((kw.get(k) for k in ("content", "desc", "description", "caption", "title", "text")
                  if isinstance(kw.get(k), str) and kw.get(k).strip()), "")
    who = kw.get("author") if isinstance(kw.get("author"), dict) else {}
    user = kw.get("user") if isinstance(kw.get("user"), dict) else {}
    uploader = next((v for v in (kw.get("uploader"), kw.get("username"), kw.get("fullname"), who.get("nick"),
                                 who.get("name"), who.get("uniqueId"), user.get("name"),
                                 kw.get("user") if isinstance(kw.get("user"), str) else "") if v), "")
    d = kw.get("date")
    day = d.strftime("%Y-%m-%d") if hasattr(d, "strftime") else (d[:10] if isinstance(d, str) and DATED.match(d[:10] + " ") else "")
    return title.strip().split("\n")[0], uploader, day


def _photos_saved_before(url):
    key = (_norm_url(url), _yt_post(url))
    for h in load_history():
        if h.get("photos") and (_norm_url(h.get("url")), _yt_post(h.get("url"))) == key and h.get("paths") \
                and all(os.path.exists(p) for p in h["paths"]) and not any(
                    p.lower().endswith((".mp4", ".mov", ".mkv", ".webm", ".mp3", ".m4a")) for p in h["paths"]):
            return h
    return None


def save_photos(job, s, folder, quiet=False):
    """Saves the post's photos into the folder and returns their paths ([] when the post has none). `quiet` (photos
    next to the videos of a mixed post) never fails the save: a problem only means no extra photos."""
    tmp = os.path.join(PARTIAL, job["id"], "photos")
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp, exist_ok=True)
    if not quiet:
        before = _photos_saved_before(job["url"])
        if before:
            job.update(already=True, title=job["title"] or before.get("title", ""),
                       thumbnail=job["thumbnail"] or before.get("thumbnail", ""), photo_count=len(before["paths"]))
            return list(before["paths"])
        job["detail"] = "Looking for photos…"
    try:
        got = _yt_post_photos(job, s, tmp) if _yt_post(job["url"]) else _gallery_photos(job, s, tmp)
    except Cancelled:
        raise
    except Exception:
        if quiet:
            return []
        raise
    if not got:
        return []
    title, uploader, day = _photo_meta(got[0][1])
    if quiet and job["title"]:   # photos next to a post's videos are named like the videos
        title = job["title"]
    else:
        title = title or job["title"] or (f"Photo by {uploader}" if uploader else f"{job['site']} photo")
        job["title"] = title[:120]
    job["uploader"] = job.get("uploader") or uploader
    job["thumbnail"] = job.get("thumbnail") or got[0][2]
    job["posted"] = job.get("posted") or day
    where = os.path.join(folder, safe_name(job["site"], 40)) if s["site_folders"] else folder
    os.makedirs(where, exist_ok=True)
    stem = (day + " " if s.get("date_in_name") and day else "") + safe_name(title, 90)
    final = []
    with _names_lock:
        for n, (p, _, _) in enumerate(got, 1):
            ext = os.path.splitext(p)[1].lower().replace(".jpeg", ".jpg")
            name = f"{stem} {n}" if len(got) > 1 else stem
            target, k = os.path.join(where, name + ext), 1
            while os.path.exists(target) or target in _reserved:
                k += 1
                target = os.path.join(where, f"{name} ({k}){ext}")
            shutil.move(p, target)
            final.append(target)
    shutil.rmtree(tmp, ignore_errors=True)
    job["photo_count"] = job.get("photo_count", 0) + len(final)
    return final


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
        cmd = ([uv, "pip", "install", "-q", "--python", sys.executable, "-U", "yt-dlp[default]", "gallery-dl"]
               if os.path.exists(uv) else [sys.executable, "-m", "pip", "install", "-q", "-U", "yt-dlp[default]", "gallery-dl"])
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
