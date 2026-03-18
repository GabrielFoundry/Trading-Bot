"""
Route API pour le feedback utilisateur sur les trades.
Permet d'éduquer le bot depuis l'app mobile.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from bot.db.database import Database, DB_PATH

router = APIRouter()


def get_db() -> Database:
    return Database(DB_PATH)


class FeedbackRequest(BaseModel):
    rating: str          # 'good', 'bad', 'neutral'
    comment: Optional[str] = None
    context: Optional[dict] = None   # {"market_context": "...", "notes": "..."}


@router.post("/{trade_id}")
def submit_feedback(
    trade_id: str,
    body: FeedbackRequest,
    db: Database = Depends(get_db),
):
    """
    Soumet un feedback sur un trade clôturé.
    Ce feedback est utilisé par l'optimiseur pour améliorer la stratégie.
    """
    if body.rating not in ("good", "bad", "neutral"):
        raise HTTPException(400, "rating doit être 'good', 'bad' ou 'neutral'")

    # Vérifier que le trade existe (requête directe par ID, sans limite)
    if not db.trade_exists(trade_id):
        raise HTTPException(404, f"Trade {trade_id} introuvable")

    feedback_id = db.save_trade_feedback(
        trade_id=trade_id,
        rating=body.rating,
        comment=body.comment,
        context=body.context,
    )

    rating_labels = {"good": "Bon trade ✅", "bad": "Mauvais trade ❌", "neutral": "Neutre 🔵"}
    return {
        "success": True,
        "feedback_id": feedback_id,
        "message": f"Feedback enregistré : {rating_labels.get(body.rating, body.rating)}",
    }


@router.get("/")
def get_all_feedback(limit: int = 50, db: Database = Depends(get_db)):
    """Retourne tous les feedbacks avec les détails des trades."""
    return db.get_all_feedback(limit=limit)


@router.get("/stats")
def get_feedback_stats(db: Database = Depends(get_db)):
    """Statistiques globales des feedbacks."""
    return db.get_feedback_stats()


@router.get("/trades-without-feedback")
def get_trades_without_feedback(limit: int = 20, db: Database = Depends(get_db)):
    """Retourne les trades clôturés qui n'ont pas encore reçu de feedback."""
    all_trades = db.get_trade_history(limit=200)
    all_feedback = db.get_all_feedback(limit=500)
    rated_ids = {f["trade_id"] for f in all_feedback}
    unrated = [t for t in all_trades if t["id"] not in rated_ids]
    return unrated[:limit]
