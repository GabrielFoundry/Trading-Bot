"""
Application FastAPI principale.
Sert l'API REST, les WebSockets et le dashboard statique.
"""

from pathlib import Path

from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from api.routes import bot, charts, portfolio, signals, trades
from api.websocket import websocket_endpoint

DASHBOARD_DIR = Path(__file__).parent.parent / "dashboard"

app = FastAPI(
    title="Trading Bot Dashboard API",
    description="API du bot de trading crypto",
    version="1.0.0",
)

# CORS pour le dashboard
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


# WebSocket
@app.websocket("/ws")
async def websocket_route(websocket: WebSocket):
    await websocket_endpoint(websocket, refresh_seconds=5)


# Dashboard statique
if DASHBOARD_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(DASHBOARD_DIR)), name="static")


@app.get("/")
async def serve_dashboard():
    index = DASHBOARD_DIR / "index.html"
    if index.exists():
        return FileResponse(str(index))
    return {"message": "Dashboard non trouvé. Assurez-vous que le dossier 'dashboard/' existe."}


@app.get("/health")
def health():
    return {"status": "ok"}
