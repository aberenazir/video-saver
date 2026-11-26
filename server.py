"""Video Saver's local web server (only this computer can reach it: 127.0.0.1)."""
import os

from fastapi import FastAPI
from fastapi.responses import FileResponse

import app_update
import saver
from saver_api import router

APP = os.path.dirname(os.path.abspath(__file__))
app = FastAPI()
app.include_router(router, prefix="/api")
saver.auto_update()
app_update.auto_check()


@app.get("/")
def index():
    return FileResponse(os.path.join(APP, "index.html"), headers={"Cache-Control": "no-store"})


@app.get("/icon.png")
def icon():
    return FileResponse(os.path.join(APP, "icon.png"))


# ---- Video Saver's own updates (see app_update.py)
@app.get("/api/app-update")
def app_update_state():
    return app_update.STATE


@app.post("/api/app-update/check")
def app_update_check():
    return app_update.check()


@app.post("/api/app-update/install")
def app_update_install():
    return app_update.install()


@app.post("/api/app-update/restart")
def app_update_restart():
    return app_update.restart()
