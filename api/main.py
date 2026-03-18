"""
Application FastAPI principale.
Sert l'API REST, les WebSockets et le dashboard statique.
"""

from pathlib import Path

from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from api.routes import bot, charts, portfolio, signals, trades
from api.routes import config_api, feedback
from api.websocket import websocket_endpoint

DASHBOARD_DIR = Path(__file__).parent.parent / "dashboard"
MOBILE_DIR = Path(__file__).parent.parent / "mobile"

app = FastAPI(
    title="Trading Bot Dashboard API",
    description="API du bot de trading crypto",
    version="1.0.0",
)

# CORS — nécessaire pour l'accès depuis tunnel et app mobile
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routes API
app.include_router(portfolio.router, prefix="/api/portfolio", tags=["Portfolio"])
app.include_router(trades.router, prefix="/api/trades", tags=["Trades"])
app.include_router(signals.router, prefix="/api/signals", tags=["Signals"])
app.include_router(bot.router, prefix="/api/bot", tags=["Bot"])
app.include_router(charts.router, prefix="/api/charts", tags=["Charts"])
app.include_router(config_api.router, prefix="/api/config", tags=["Config"])
app.include_router(feedback.router, prefix="/api/feedback", tags=["Feedback"])


# WebSocket
@app.websocket("/ws")
async def websocket_route(websocket: WebSocket):
    await websocket_endpoint(websocket, refresh_seconds=5)


# Fichiers statiques dashboard
if DASHBOARD_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(DASHBOARD_DIR)), name="static")

# Fichiers PWA (manifest.json, sw.js, icônes)
if MOBILE_DIR.exists():
    app.mount("/mobile", StaticFiles(directory=str(MOBILE_DIR)), name="mobile")


@app.get("/manifest.json")
async def serve_manifest():
    manifest = MOBILE_DIR / "manifest.json"
    if manifest.exists():
        return FileResponse(str(manifest), media_type="application/manifest+json")
    return {"error": "manifest.json not found"}


@app.get("/sw.js")
async def serve_sw():
    sw = MOBILE_DIR / "sw.js"
    if sw.exists():
        return FileResponse(str(sw), media_type="application/javascript")
    return JSONResponse({"error": "sw.js not found"}, status_code=404)


@app.get("/")
async def serve_dashboard():
    index = DASHBOARD_DIR / "index.html"
    if index.exists():
        return FileResponse(str(index))
    return {"message": "Dashboard non trouvé."}


@app.get("/health")
def health():
    return {"status": "ok"}
