"""Routes API pour les signaux."""

from fastapi import APIRouter, Depends, Query
from bot.db.database import Database, DB_PATH

router = APIRouter()


def get_db() -> Database:
    return Database(DB_PATH)


@router.get("/latest")
def get_latest_signals(limit: int = Query(20, ge=1, le=100), db: Database = Depends(get_db)):
    return db.get_latest_signals(limit=limit)


@router.get("/news")
def get_recent_news(hours: int = 24, db: Database = Depends(get_db)):
    return db.get_recent_news(hours=hours)
