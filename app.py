"""
Web - player — simple backend.

Public features: serves static index.html (drag-n-drop player).
Admin features (behind password): lists and streams files from MUSIC_DIR.
"""
import os
import secrets
from pathlib import Path
from datetime import datetime, timedelta, timezone

import aiofiles
import jwt
from fastapi import FastAPI, HTTPException, Depends, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

# ===== Config =====
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD")
if not ADMIN_PASSWORD:
    raise RuntimeError("ADMIN_PASSWORD env var is required")

JWT_SECRET = os.environ.get("JWT_SECRET") or secrets.token_hex(32)
MUSIC_DIR = Path(os.environ.get("MUSIC_DIR", "/music")).resolve()
STATIC_DIR = Path(os.environ.get("STATIC_DIR", "/app/static")).resolve()
TOKEN_HOURS = int(os.environ.get("TOKEN_HOURS", "24"))
ALLOWED_EXT = {".flac", ".mp3", ".m4a", ".mp4", ".ogg", ".opus"}

app = FastAPI(title="Web - player", docs_url=None, redoc_url=None, openapi_url=None)

security = HTTPBearer(auto_error=False)


# ===== Auth =====
def _make_token() -> str:
    exp = datetime.now(timezone.utc) + timedelta(hours=TOKEN_HOURS)
    return jwt.encode({"exp": exp, "role": "admin"}, JWT_SECRET, algorithm="HS256")


def _check_token(token: str) -> bool:
    try:
        jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        return True
    except jwt.PyJWTError:
        return False


def require_auth_header(creds: HTTPAuthorizationCredentials = Depends(security)):
    """Standard Bearer token auth — for JSON endpoints."""
    if not creds or not _check_token(creds.credentials):
        raise HTTPException(status_code=401, detail="Unauthorized")


def require_auth_query_or_header(request: Request):
    """
    Flexible auth: accepts token from ?token= query param OR Authorization header.
    Needed because <audio src="..."> cannot send custom headers.
    """
    token = None
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        token = auth[7:]
    if not token:
        token = request.query_params.get("token")
    if not token or not _check_token(token):
        raise HTTPException(status_code=401, detail="Unauthorized")


# ===== Endpoints =====
@app.post("/api/login")
async def login(request: Request):
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Bad JSON")
    password = body.get("password", "")
    if not isinstance(password, str):
        raise HTTPException(status_code=400, detail="Bad password field")
    # Constant-time compare to resist timing attacks
    if not secrets.compare_digest(password.encode("utf-8"), ADMIN_PASSWORD.encode("utf-8")):
        # Small artificial delay to discourage brute-force
        import asyncio
        await asyncio.sleep(0.3)
        raise HTTPException(status_code=401, detail="Bad password")
    return {"token": _make_token()}


@app.get("/api/tracks")
def list_tracks(_=Depends(require_auth_header)):
    """Return a flat list of tracks from MUSIC_DIR (all subfolders), sorted by name."""
    if not MUSIC_DIR.exists():
        return []
    tracks = []
    for root, _dirs, files in os.walk(MUSIC_DIR):
        for fname in files:
            if Path(fname).suffix.lower() not in ALLOWED_EXT:
                continue
            full = Path(root) / fname
            try:
                rel = full.relative_to(MUSIC_DIR)
                stat = full.stat()
                tracks.append({
                    "id": str(rel),
                    "name": fname,
                    "size": stat.st_size,
                })
            except (ValueError, OSError):
                continue
    tracks.sort(key=lambda t: t["name"].lower())
    return tracks


def _resolve_track_path(track_id: str) -> Path:
    """Resolve track id to absolute path, safely (no path traversal)."""
    # Strip any leading slash; reject absolute or traversal attempts
    if not track_id or track_id.startswith("/") or ".." in track_id.split("/"):
        raise HTTPException(status_code=400, detail="Bad track id")
    full = (MUSIC_DIR / track_id).resolve()
    # Ensure within MUSIC_DIR
    try:
        full.relative_to(MUSIC_DIR)
    except ValueError:
        raise HTTPException(status_code=403, detail="Forbidden")
    if not full.exists() or not full.is_file():
        raise HTTPException(status_code=404, detail="Not found")
    if full.suffix.lower() not in ALLOWED_EXT:
        raise HTTPException(status_code=403, detail="Forbidden extension")
    return full


_MIME = {
    ".flac": "audio/flac",
    ".mp3": "audio/mpeg",
    ".m4a": "audio/mp4",
    ".mp4": "audio/mp4",
    ".ogg": "audio/ogg",
    ".opus": "audio/ogg",
}


@app.get("/api/track/{track_id:path}")
async def get_track(track_id: str, request: Request, _=Depends(require_auth_query_or_header)):
    full = _resolve_track_path(track_id)
    file_size = full.stat().st_size
    mime = _MIME.get(full.suffix.lower(), "application/octet-stream")

    range_header = request.headers.get("range")
    if range_header and range_header.startswith("bytes="):
        byte_range = range_header[6:].split("-")
        try:
            start = int(byte_range[0]) if byte_range[0] else 0
            end = int(byte_range[1]) if len(byte_range) > 1 and byte_range[1] else file_size - 1
        except ValueError:
            raise HTTPException(status_code=416, detail="Bad range")
        end = min(end, file_size - 1)
        if start > end or start < 0:
            raise HTTPException(status_code=416, detail="Bad range")
        length = end - start + 1

        async def iter_range():
            chunk_size = 64 * 1024
            async with aiofiles.open(full, "rb") as f:
                await f.seek(start)
                remaining = length
                while remaining > 0:
                    data = await f.read(min(chunk_size, remaining))
                    if not data:
                        break
                    yield data
                    remaining -= len(data)

        headers = {
            "Content-Range": f"bytes {start}-{end}/{file_size}",
            "Accept-Ranges": "bytes",
            "Content-Length": str(length),
            "Cache-Control": "private, max-age=3600",
        }
        return StreamingResponse(iter_range(), status_code=206, headers=headers, media_type=mime)

    # Full file response with Accept-Ranges header so browser can re-request with Range
    headers = {"Accept-Ranges": "bytes", "Cache-Control": "private, max-age=3600"}
    return FileResponse(full, media_type=mime, headers=headers)


@app.get("/healthz")
def healthz():
    return {"ok": True, "music_dir_exists": MUSIC_DIR.exists()}


# ===== Static =====
# Serve index.html with no-cache to avoid stale UI after rebuilds.
# Other static assets (icons, fonts) get cached normally.

@app.get("/")
@app.get("/index.html")
async def index():
    index_path = STATIC_DIR / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=404, detail="index.html not found")
    return FileResponse(
        index_path,
        media_type="text/html; charset=utf-8",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


@app.get("/manifest.webmanifest")
async def manifest():
    """PWA manifest — short cache so install metadata can update."""
    p = STATIC_DIR / "manifest.webmanifest"
    if not p.exists():
        raise HTTPException(status_code=404)
    return FileResponse(
        p,
        media_type="application/manifest+json",
        headers={"Cache-Control": "public, max-age=300"},
    )


# All other static (icons, fonts, future css/js) — long cache, immutable
app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=False), name="static")
