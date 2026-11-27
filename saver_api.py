"""The web routes for saving videos (shared by Video Saver at /api and Link Transcriber at /api/saver)."""
import os

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

import saver

router = APIRouter()


@router.get("/state")
def state():
    jobs = sorted((saver.public(j) for j in saver.JOBS.values()), key=lambda j: -j["added"])
    return {"settings": saver.load_settings(), "jobs": jobs, "history": saver.history_with_status(),
            "browsers": saver.installed_browsers(), "update": saver._update,
            "qualities": [{"key": k, "label": v[0]} for k, v in saver.QUALITIES.items()],
            "dating": saver.dating_status(), "version": saver.yt_dlp.version.__version__, "platform": "windows" if saver.WINDOWS else "mac"}


@router.get("/busy")
def busy():
    return saver.busy()


@router.post("/add")
async def add(req: Request):
    body = await req.json()
    links = saver.find_links(body.get("text", ""))
    if not links:
        return JSONResponse({"error": "No link found. Copy the video's link (Share → Copy link) and paste it here."},
                            400)
    return {"added": saver.add(links, body.get("quality")), "links": links}


@router.post("/links")
async def links(req: Request):
    return {"links": saver.find_links((await req.json()).get("text", ""))}


@router.post("/cancel/{jid}")
def cancel(jid: str):
    saver.cancel(jid)
    return {"ok": True}


@router.post("/retry/{jid}")
def retry(jid: str):
    return {"added": saver.retry(jid)}


@router.post("/clear")
def clear():
    saver.clear_finished()
    return {"ok": True}


@router.post("/settings")
async def settings(req: Request):
    body = await req.json()
    if "folder" in body:
        body["folder"] = os.path.expanduser(body["folder"] or saver.DEFAULTS["folder"])
    return saver.save_settings(body)


@router.post("/reveal")
async def reveal(req: Request):
    return {"ok": saver.reveal((await req.json()).get("path"))}


@router.post("/open")
async def open_(req: Request):
    return {"ok": saver.open_path((await req.json()).get("path"))}


@router.post("/open-folder")
def open_folder():
    f = os.path.expanduser(saver.load_settings()["folder"])
    os.makedirs(f, exist_ok=True)
    return {"ok": saver.open_path(f)}


@router.post("/history/remove/{hid}")
def history_remove(hid: str):
    saver.remove_history(hid)
    return {"ok": True}


@router.post("/update-downloader")
def update_downloader():
    return saver.update_downloader()


@router.post("/test-login")
def test_login():
    return saver.test_login(saver.load_settings()["browser"])


@router.post("/add-dates")
def add_dates():
    return saver.add_dates()
