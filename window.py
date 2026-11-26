"""Video Saver as a real app: its own window (no browser), Dock / taskbar icon, ⌘Q (Mac) or the ✕ (Windows) to quit.

The window shows the page from the local server, which runs inside this same process.
Closing the window quits the app and stops the server.
Works the same from the source (python window.py) and as the self-contained app built by installer/build_mac.sh or
the Windows workflow (PyInstaller: then the files are in sys._MEIPASS).
"""
import json, os, sys, threading, time, urllib.request

FROZEN = getattr(sys, "frozen", False)
APP = getattr(sys, "_MEIPASS", "") or os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, APP)
os.chdir(APP)
PORT = int(os.environ.get("VIDEO_SAVER_PORT") or 8766)   # another port only for testing a second copy
URL = f"http://127.0.0.1:{PORT}"
MAC, WINDOWS = sys.platform == "darwin", os.name == "nt"

if FROZEN and (sys.stdout is None or sys.stderr is None or MAC):
    # the app has no Terminal: messages go to app.log in the data folder (Windows gives no stdout at all)
    _data = os.environ.get("SAVER_DATA") or (
        os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "Video Saver") if WINDOWS
        else os.path.expanduser("~/Library/Application Support/Video Saver"))
    os.makedirs(_data, exist_ok=True)
    sys.stdout = sys.stderr = open(os.path.join(_data, "app.log"), "a", buffering=1, encoding="utf-8")

import webview  # noqa: E402


def server_up():
    try:
        urllib.request.urlopen(URL + "/api/busy", timeout=1)
        return True
    except Exception:
        return False


def run_server():
    import uvicorn
    from server import app
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning", loop="asyncio", http="h11", ws="none",
                lifespan="off", log_config=None)


def mac_branding():
    """Show "Video Saver" (not "Python") in the menu bar and the app's icon in the Dock (only needed from source)."""
    if not MAC or FROZEN:
        return
    try:
        from Foundation import NSBundle
        info = NSBundle.mainBundle().localizedInfoDictionary() or NSBundle.mainBundle().infoDictionary()
        info["CFBundleName"] = "Video Saver"
        from AppKit import NSApplication, NSImage
        icon = NSImage.alloc().initWithContentsOfFile_(os.path.join(APP, "icon_large.png"))
        if icon:
            NSApplication.sharedApplication().setApplicationIconImage_(icon)
    except Exception:
        pass


def windows_clipboard():
    import ctypes
    from ctypes import wintypes
    u, k = ctypes.windll.user32, ctypes.windll.kernel32
    u.GetClipboardData.restype = k.GlobalLock.restype = wintypes.HANDLE
    u.GetClipboardData.argtypes = [wintypes.UINT]
    k.GlobalLock.argtypes = k.GlobalUnlock.argtypes = [wintypes.HANDLE]
    if not u.OpenClipboard(None):
        return ""
    try:
        h = u.GetClipboardData(13)  # CF_UNICODETEXT
        if not h:
            return ""
        p = k.GlobalLock(h)
        try:
            return ctypes.wstring_at(p) if p else ""
        finally:
            k.GlobalUnlock(h)
    finally:
        u.CloseClipboard()


class Api:
    """Things the page asks the computer to do (folder chooser, clipboard)."""

    def __init__(self):
        self.window = None

    def pick_folder(self):
        r = self.window.create_file_dialog(webview.FileDialog.FOLDER)
        return r[0] if r else ""

    def clipboard(self):
        try:
            if WINDOWS:
                return windows_clipboard()
            from AppKit import NSPasteboard, NSPasteboardTypeString
            return NSPasteboard.generalPasteboard().stringForType_(NSPasteboardTypeString) or ""
        except Exception:
            return ""


def main():
    mac_branding()
    if not server_up():
        threading.Thread(target=run_server, daemon=True).start()
        for _ in range(120):
            if server_up():
                break
            time.sleep(0.25)
    webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = True
    api = Api()
    api.window = webview.create_window("Video Saver", URL, js_api=api, width=980, height=760, min_size=(620, 520),
                                       text_select=True, background_color="#151413")

    def on_closing():
        try:
            work = json.load(urllib.request.urlopen(URL + "/api/busy", timeout=2))
        except Exception:
            work = []
        api.window.confirm_close = bool(work)
        if work:
            api.window.localization["global.quitConfirmation"] = (
                f"Video Saver is still saving {len(work)} video{'s' if len(work) > 1 else ''}.\n\nIf you quit now "
                "they stop. Press Try again later and they continue where they left off.")
        return True

    api.window.events.closing += on_closing
    webview.start(mac_branding)
    os._exit(0)


if __name__ == "__main__":
    main()
