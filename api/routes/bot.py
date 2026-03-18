"""Routes API pour le contrôle du bot."""

from fastapi import APIRouter, Depends
from bot.db.database import Database, DB_PATH

# Référence au bot global (injectée depuis api/main.py au démarrage)
_bot_ref = None

def set_bot_ref(bot):
    global _bot_ref
    _bot_ref = bot

router = APIRouter()


def get_db() -> Database:
    return Database(DB_PATH)


@router.get("/status")
def get_bot_status(db: Database = Depends(get_db)):
    state = db.get_bot_state()
    return {
        "is_running": state.is_running,
        "mode": state.mode,
        "active_strategy_version": state.active_strategy_version,
        "max_drawdown_triggered": state.max_drawdown_triggered,
        "last_tick_at": state.last_tick_at,
        "last_optimization_at": state.last_optimization_at,
        "total_trades_count": state.total_trades_count,
        "started_at": state.started_at,
    }


@router.post("/start")
def start_bot(db: Database = Depends(get_db)):
    """Démarre le trading loop (depuis l'app mobile)."""
    state = db.get_bot_state()
    if state.max_drawdown_triggered:
        return {"success": False, "message": "Drawdown maximum déclenché. Réinitialisez d'abord."}
    db.update_bot_state(is_running=1)
    return {"success": True, "message": "Bot démarré"}


@router.post("/stop")
def stop_bot(db: Database = Depends(get_db)):
    """Arrête le trading loop sans couper le serveur."""
    db.update_bot_state(is_running=0)
    return {"success": True, "message": "Bot arrêté"}


@router.post("/reset-drawdown")
def reset_drawdown_guard(db: Database = Depends(get_db)):
    """Réinitialise la garde drawdown."""
    db.update_bot_state(max_drawdown_triggered=0)
    return {"success": True, "message": "Garde drawdown réinitialisée. Le bot peut reprendre."}


@router.get("/performance")
def get_performance(db: Database = Depends(get_db)):
    return db.get_latest_performance()
