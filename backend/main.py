import asyncio
import os
import secrets
from pathlib import Path
from typing import List

import httpx
from fastapi import Depends, FastAPI, File, Header, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

app = FastAPI(title="Ghammas Baladi Central Radio API")

MUSIC_DIR = Path("/music")
PLAYLIST_FILE = MUSIC_DIR / "playlist.m3u"
ICECAST_STATUS_URL = os.getenv("ICECAST_STATUS_URL", "http://icecast:8000/status-json.xsl")
LIQUIDSOAP_HOST = os.getenv("LIQUIDSOAP_HOST", "liquidsoap")
LIQUIDSOAP_PORT = int(os.getenv("LIQUIDSOAP_TELNET_PORT", "1234"))
raw_pin = os.getenv("ADMIN_PIN")
if not raw_pin or raw_pin == "CHANGE_ME":
    raise RuntimeError("ADMIN_PIN environment variable must be set in .env before starting.")
ADMIN_PIN = raw_pin.strip().upper()

app.mount("/static", StaticFiles(directory="static"), name="static")


def verify_admin(x_admin_pin: str = Header(default="")):
    if not secrets.compare_digest(x_admin_pin.strip().upper(), ADMIN_PIN):
        raise HTTPException(status_code=401, detail="Invalid HQ Admin PIN")


class ReorderRequest(BaseModel):
    tracks: List[str]


class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        await self.broadcast_state()

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        dead = []
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                dead.append(connection)
        for conn in dead:
            self.disconnect(conn)

    async def broadcast_state(self):
        await self.broadcast({
            "type": "STATE",
            "now_playing": current_track_title,
            "connected_branches": len(self.active_connections),
            "playlist": get_playlist_tracks(),
        })


manager = ConnectionManager()
current_track_title = "Initializing Live Broadcast..."


def get_playlist_tracks() -> List[str]:
    MUSIC_DIR.mkdir(parents=True, exist_ok=True)
    existing_mp3s = {f.name for f in MUSIC_DIR.glob("*.mp3")}

    ordered: List[str] = []
    if PLAYLIST_FILE.exists():
        for line in PLAYLIST_FILE.read_text(encoding="utf-8").splitlines():
            name = Path(line.strip()).name
            if name in existing_mp3s and name not in ordered:
                ordered.append(name)

    for name in sorted(existing_mp3s):
        if name not in ordered:
            ordered.append(name)

    save_playlist_tracks(ordered)
    return ordered


def save_playlist_tracks(tracks: List[str]):
    lines = [f"/music/{t}" for t in tracks if (MUSIC_DIR / t).exists()]
    PLAYLIST_FILE.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


async def send_liquidsoap_command(cmd: str) -> str:
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(LIQUIDSOAP_HOST, LIQUIDSOAP_PORT), timeout=3.0
        )
        writer.write(f"{cmd}\nquit\n".encode("utf-8"))
        await writer.drain()
        data = await asyncio.wait_for(reader.read(1024), timeout=3.0)
        writer.close()
        await writer.wait_closed()
        return data.decode("utf-8", errors="ignore").strip()
    except Exception as e:
        return f"Telnet error: {e}"


async def poll_icecast_metadata():
    global current_track_title
    async with httpx.AsyncClient(timeout=3.0) as client:
        while True:
            try:
                resp = await client.get(ICECAST_STATUS_URL)
                if resp.status_code == 200:
                    data = resp.json()
                    source = data.get("icestats", {}).get("source")
                    if isinstance(source, list):
                        source = source[0]
                    if isinstance(source, dict):
                        title = source.get("title") or source.get("yp_currently_playing") or "Ghammas Baladi Live Feed"
                        if title != current_track_title:
                            current_track_title = title
                            await manager.broadcast_state()
            except Exception:
                pass
            await asyncio.sleep(2.0)


@app.on_event("startup")
async def startup_event():
    get_playlist_tracks()
    asyncio.create_task(poll_icecast_metadata())


@app.get("/")
async def serve_ui():
    return FileResponse("static/index.html")


@app.post("/api/admin/verify", dependencies=[Depends(verify_admin)])
async def api_verify_admin():
    return {"status": "authorized"}


@app.get("/api/playlist")
async def api_get_playlist():
    return {
        "tracks": get_playlist_tracks(),
        "now_playing": current_track_title,
        "connected_branches": len(manager.active_connections),
    }


@app.post("/api/upload", dependencies=[Depends(verify_admin)])
async def api_upload_track(file: UploadFile = File(...)):
    if not file.filename.lower().endswith(".mp3"):
        raise HTTPException(status_code=400, detail="Only .mp3 files are supported.")
    safe_name = os.path.basename(file.filename).replace(" ", "_")
    dest = MUSIC_DIR / safe_name
    content = await file.read()
    dest.write_bytes(content)

    tracks = get_playlist_tracks()
    if safe_name not in tracks:
        tracks.append(safe_name)
    save_playlist_tracks(tracks)

    await send_liquidsoap_command("main_playlist.reload")
    await manager.broadcast_state()
    return {"status": "uploaded", "track": safe_name, "tracks": tracks}


@app.post("/api/playlist/reorder", dependencies=[Depends(verify_admin)])
async def api_reorder_playlist(payload: ReorderRequest):
    save_playlist_tracks(payload.tracks)
    await send_liquidsoap_command("main_playlist.reload")
    await manager.broadcast_state()
    return {"status": "reordered", "tracks": get_playlist_tracks()}


@app.delete("/api/playlist/{track_name}", dependencies=[Depends(verify_admin)])
async def api_delete_track(track_name: str):
    safe_name = os.path.basename(track_name)
    target = MUSIC_DIR / safe_name
    if target.exists():
        target.unlink()
    tracks = [t for t in get_playlist_tracks() if t != safe_name]
    save_playlist_tracks(tracks)
    await send_liquidsoap_command("main_playlist.reload")
    await manager.broadcast_state()
    return {"status": "deleted", "tracks": tracks}


@app.post("/api/control/skip", dependencies=[Depends(verify_admin)])
async def api_skip_track():
    res = await send_liquidsoap_command("broadcast.skip")
    return {"status": "skipped", "detail": res}


@app.post("/api/control/sync", dependencies=[Depends(verify_admin)])
async def api_force_sync():
    await manager.broadcast({"type": "FORCE_SYNC"})
    return {"status": "sync_triggered", "branches_notified": len(manager.active_connections)}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            msg = await websocket.receive_text()
            if msg == "PING":
                await websocket.send_json({"type": "PONG"})
    except WebSocketDisconnect:
        manager.disconnect(websocket)
        await manager.broadcast_state()