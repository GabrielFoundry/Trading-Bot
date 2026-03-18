"""
WebSocket pour le push des données en temps réel vers le dashboard.
Envoie un snapshot complet toutes les N secondes.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect
from loguru import logger

from bot.db.database import Database, DB_PATH


class ConnectionManager:
    """Gère les connexions WebSocket actives."""

    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.debug(f"WebSocket connecté ({len(self.active_connections)} clients)")

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        logger.debug(f"WebSocket déconnecté ({len(self.active_connections)} clients)")

    async def broadcast(self, data: dict):
        """Envoie les données à tous les clients connectés."""
        if not self.active_connections:
            return
        message = json.dumps(data, default=str)
        disconnected = []
        for ws in self.active_connections:
            try:
                await ws.send_text(message)
            except Exception:
                disconnected.append(ws)
        for ws in disconnected:
            self.disconnect(ws)


manager = ConnectionManager()


async def get_live_snapshot(db: Database) -> dict:
    """Construit le snapshot de données envoyé via WebSocket."""
    state = db.get_bot_state()
    open_trades = db.get_open_trades()
    perf = db.get_latest_performance()
    latest_signals = db.get_latest_signals(limit=8)

    positions_value = sum(
        t["entry_price"] * t["quantity"] / t["leverage"]
        for t in open_trades
    )

    return {
        "type": "snapshot",
        "bot": {
            "is_running": state.is_running,
            "mode": state.mode,
            "max_drawdown_triggered": state.max_drawdown_triggered,
            "last_tick_at": state.last_tick_at,
        },
        "portfolio": {
            "usdt_balance": round(state.paper_balance, 4),
            "positions_value": round(positions_value, 4),
            "total_value": round(state.paper_balance + positions_value, 4),
            "open_positions_count": len(open_trades),
        },
        "positions": [
            {
                "symbol": t["symbol"],
                "side": t["side"],
                "entry_price": t["entry_price"],
                "quantity": t["quantity"],
                "leverage": t["leverage"],
                "stop_loss": t["stop_loss"],
                "take_profit": t["take_profit"],
                "liquidation_price": t.get("liquidation_price"),
                "opened_at": t["opened_at"],
            }
            for t in open_trades
        ],
        "performance": perf,
        "signals": [
            {
                "symbol": s["symbol"],
                "action": s["action"],
                "confidence": s["confidence"],
                "combined_score": s["combined_score"],
                "reasons": s.get("reasons", []),
                "timestamp": s["timestamp"],
            }
            for s in latest_signals
        ],
    }


async def websocket_endpoint(websocket: WebSocket, refresh_seconds: int = 5):
    """Endpoint WebSocket principal."""
    db = Database(DB_PATH)
    await manager.connect(websocket)
    try:
        while True:
            snapshot = await get_live_snapshot(db)
            await websocket.send_text(json.dumps(snapshot, default=str))
            await asyncio.sleep(refresh_seconds)
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        manager.disconnect(websocket)
