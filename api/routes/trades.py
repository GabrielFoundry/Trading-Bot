"""Routes API pour l'historique des trades."""

from typing import Optional
from fastapi import APIRouter, Depends, Query
from bot.db.database import Database, DB_PATH

router = APIRouter()


def get_db() -> Database:
    return Database(DB_PATH)


@router.get("/history")
def get_trade_history(
    limit: int = Query(50, ge=1, le=500),
    symbol: Optional[str] = None,
    db: Database = Depends(get_db),
):
    return db.get_trade_history(limit=limit, symbol=symbol)


@router.get("/stats")
def get_trade_stats(db: Database = Depends(get_db)):
    return db.get_latest_performance()
