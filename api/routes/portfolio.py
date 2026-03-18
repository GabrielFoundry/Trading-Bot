"""Routes API pour le portfolio."""

from fastapi import APIRouter, Depends
from bot.db.database import Database, DB_PATH
from pathlib import Path

router = APIRouter()


def get_db() -> Database:
    return Database(DB_PATH)


@router.get("/summary")
def get_portfolio_summary(db: Database = Depends(get_db)):
    state = db.get_bot_state()
    perf = db.get_latest_performance()
    open_trades = db.get_open_trades()

    positions_value = sum(
        t["entry_price"] * t["quantity"] / t["leverage"]
        for t in open_trades
    )

    return {
        "usdt_balance": round(state.paper_balance, 4),
        "positions_value": round(positions_value, 4),
        "total_value": round(state.paper_balance + positions_value, 4),
        "open_positions_count": len(open_trades),
        "total_trades": state.total_trades_count,
        "mode": state.mode,
        "is_running": state.is_running,
        "max_drawdown_triggered": state.max_drawdown_triggered,
        "performance": perf,
    }


@router.get("/positions")
def get_open_positions(db: Database = Depends(get_db)):
    return db.get_open_trades()


@router.get("/history")
def get_portfolio_history(days: int = 30, db: Database = Depends(get_db)):
    return db.get_portfolio_history(days=days)
