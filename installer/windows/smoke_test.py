"""Checks the Windows-only parts of the engine on a real Windows PC (the GitHub workflow runs it).
  python installer/windows/smoke_test.py            -> the engine from source (Recycle Bin, conversion, browsers…)
  python installer/windows/smoke_test.py <exe>      -> also starts the built app and asks its server for its state
Download tests from GitHub's servers are informative only: sites often block data-centre computers.
"""
import json, os, subprocess, sys, tempfile, time, urllib.request
sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # the Windows console can't print "→" otherwise

T = tempfile.mkdtemp(prefix="vs-test-")
os.environ.update(SAVER_DATA=os.path.join(T, "data"), SAVER_FOLDER=os.path.join(T, "videos"))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
failed = []


def check(name, ok, extra=""):
    print(("PASS " if ok else "FAIL ") + name + (f"  ({extra})" if extra else ""), flush=True)
    if not ok:
        failed.append(name)


import saver  # noqa: E402

check("runs as Windows", saver.WINDOWS and not saver.MAC)
check("ffmpeg found", os.path.exists(saver.FFMPEG), saver.FFMPEG)
check("browsers listed", isinstance(saver.installed_browsers(), list), json.dumps(saver.installed_browsers()))
check("links found", saver.find_links("look youtu.be/abc and https://www.instagram.com/reel/xyz/") ==
      ["https://www.instagram.com/reel/xyz/", "https://youtu.be/abc"])
check("Chrome login message", "Firefox" in saver.test_login("chrome")["message"])

# conversion: a VP9 WebM becomes an H.264 MP4 with the software encoder
src = os.path.join(T, "test clip é.webm")
subprocess.run([saver.FFMPEG, "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=320x240:rate=25:duration=2",
                "-f", "lavfi", "-i", "sine=duration=2", "-c:v", "libvpx-vp9", "-c:a", "libopus", src], check=True)
out = saver.make_mac_friendly(src)
check("converted to H.264 MP4", out.endswith(".mp4") and saver.media_info(out)[0] == "h264", out)

# Recycle Bin
junk = os.path.join(T, "old copy.txt")
open(junk, "w").write("x")
saver.to_trash(junk)
check("moved to Recycle Bin", not os.path.exists(junk))

saver.notify("Test", "Smoke test notification")
check("notification did not crash", True)

if len(sys.argv) > 1:
    exe = sys.argv[1]
    env = dict(os.environ, VIDEO_SAVER_PORT="8799")
    p = subprocess.Popen([exe], env=env)
    state = None
    for _ in range(90):
        try:
            state = json.load(urllib.request.urlopen("http://127.0.0.1:8799/api/state", timeout=2))
            break
        except Exception:
            time.sleep(1)
    check("built app starts its server", bool(state))
    if state:
        check("built app says windows", state.get("platform") == "windows", state.get("version"))
        req = urllib.request.Request("http://127.0.0.1:8799/api/add", method="POST",
                                     data=json.dumps({"text": "https://www.youtube.com/watch?v=jNQXAC9IVRw"}).encode(),
                                     headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=10)
        for _ in range(120):
            s = json.load(urllib.request.urlopen("http://127.0.0.1:8799/api/state", timeout=5))
            j = s["jobs"][0] if s["jobs"] else {}
            if j.get("status") in ("done", "error"):
                break
            time.sleep(2)
        print("INFO YouTube download from GitHub's server:", j.get("status"), j.get("paths") or j.get("error", "")[:300])
    p.kill()

print("\nFAILED: " + ", ".join(failed) if failed else "\nALL PASSED")
sys.exit(1 if failed else 0)
