"""Routes API pour le contrôle du bot."""

from fastapi import APIRouter, Depends, HTTPException
from bot.db.database import Database, DB_PATH

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


@router.post("/reset-drawdown")
def reset_drawdown_guard(db: Database = Depends(get_db)):
    """Réinitialise la garde drawdown (à utiliser manuellement après analyse)."""
    db.update_bot_state(max_drawdown_triggered=0)
    return {"message": "Garde drawdown réinitialisée. Le bot peut reprendre."}


@router.get("/performance")
def get_performance(db: Database = Depends(get_db)):
    return db.get_latest_performance()
