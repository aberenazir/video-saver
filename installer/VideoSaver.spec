# PyInstaller recipe for the self-contained Video Saver (Python and every package inside the app).
# Used by installer/build_mac.sh on a Mac and by .github/workflows/build.yml on Windows:
#   pyinstaller --noconfirm installer/VideoSaver.spec      (run from the Source code folder)
import os, sys
from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata

HERE = os.path.dirname(os.path.abspath(SPEC))
SRC = os.path.dirname(HERE)
WIN = sys.platform == "win32"
VERSION = open(os.path.join(HERE, "VERSION")).read().strip()
# the JavaScript runtime YouTube needs: DENO or NODE = its path (the build fetches it), else installer/bin/deno[.exe]
js = [p for p in (os.environ.get("DENO"), os.environ.get("NODE"),
                  os.path.join(HERE, "bin", "deno.exe" if WIN else "deno")) if p and os.path.exists(p)][:1]

a = Analysis(
    [os.path.join(SRC, "window.py")],
    pathex=[SRC],
    binaries=[(js[0], "bin")] if js else [],
    datas=[(os.path.join(SRC, f), ".") for f in ("index.html", "icon.png", "icon_large.png")]
          + [(os.path.join(HERE, "VERSION"), ".")]
          + collect_data_files("yt_dlp_ejs") + collect_data_files("imageio_ffmpeg", include_py_files=False)
          + copy_metadata("yt-dlp"),
    # yt-dlp loads some parts by name; the whole standard library helps a newer downloader (fetched later) load
    hiddenimports=["server", "saver", "saver_api", "app_update"] + collect_submodules("yt_dlp") + collect_submodules("yt_dlp_ejs")
                  + ["sqlite3", "xml.etree.ElementTree", "http.cookiejar", "email.utils", "hmac", "secrets",
                     "uuid", "zipfile", "tarfile", "lzma", "bz2", "concurrent.futures", "unittest.mock"],
    excludes=["tkinter", "matplotlib", "numpy", "PIL", "IPython", "pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="Video Saver", console=False,
          icon=os.path.join(HERE, "AppIcon.ico" if WIN else "AppIcon.icns"),
          version=os.path.join(HERE, "windows", "version_info.txt") if WIN else None)
coll = COLLECT(exe, a.binaries, a.datas, name="Video Saver")

if not WIN:
    app = BUNDLE(
        coll, name="Video Saver.app", icon=os.path.join(HERE, "AppIcon.icns"), bundle_identifier="local.videosaver.app",
        info_plist={
            "CFBundleName": "Video Saver", "CFBundleDisplayName": "Video Saver",
            "CFBundleShortVersionString": VERSION, "CFBundleVersion": VERSION,
            "LSMinimumSystemVersion": "12.0", "LSApplicationCategoryType": "public.app-category.utilities",
            "NSHighResolutionCapable": True,
            "NSAppleEventsUsageDescription": "Video Saver uses this to show notifications.",
        })
