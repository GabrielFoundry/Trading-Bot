"""Routes API pour les données des graphiques."""

from fastapi import APIRouter, Depends, Query
from bot.db.database import Database, DB_PATH

router = APIRouter()


def get_db() -> Database:
    return Database(DB_PATH)


@router.get("/portfolio-value")
def get_portfolio_chart(days: int = Query(30, ge=1, le=365), db: Database = Depends(get_db)):
    """Retourne l'historique de la valeur du portfolio pour le graphique linéaire."""
    history = db.get_portfolio_history(days=days)
    return [
        {
            "date": s["snapshot_date"],
            "total_value": s["total_value"],
            "usdt_balance": s["usdt_balance"],
            "unrealized_pnl": s["unrealized_pnl"],
        }
        for s in history
    ]


@router.get("/ohlcv")
def get_ohlcv_chart(
    symbol: str = "BTC/USDT",
    timeframe: str = "1h",
    limit: int = Query(100, ge=10, le=500),
    db: Database = Depends(get_db),
):
    """Retourne les données OHLCV pour le graphique en chandeliers."""
    return db.get_ohlcv(symbol, timeframe, limit)


@router.get("/pnl-by-symbol")
def get_pnl_by_symbol(db: Database = Depends(get_db)):
    """Retourne le P&L total par symbole pour le graphique en barres."""
    trades = db.get_trade_history(limit=500)
    symbol_pnl: dict[str, float] = {}
    symbol_count: dict[str, int] = {}

    for trade in trades:
        sym = trade.get("symbol", "?")
        pnl = trade.get("pnl_usdt", 0.0) or 0.0
        symbol_pnl[sym] = symbol_pnl.get(sym, 0.0) + pnl
        symbol_count[sym] = symbol_count.get(sym, 0) + 1

    return [
        {"symbol": sym, "total_pnl": round(pnl, 4), "trade_count": symbol_count.get(sym, 0)}
        for sym, pnl in sorted(symbol_pnl.items(), key=lambda x: x[1], reverse=True)
    ]
