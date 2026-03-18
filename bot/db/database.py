"""
Couche d'accès aux données — SQLite.
Tous les modules passent par cette classe. Aucune requête SQL en dehors de ce fichier.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Generator, Optional

from loguru import logger

DB_PATH = Path(__file__).parent.parent.parent / "data" / "trading_bot.db"
SCHEMA_PATH = Path(__file__).parent / "schema.sql"


def init_db(db_path: Path = DB_PATH) -> None:
    """Initialise la base de données en appliquant le schéma SQL."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        schema = SCHEMA_PATH.read_text(encoding="utf-8")
        conn.executescript(schema)
    logger.info(f"Base de données initialisée : {db_path}")


@contextmanager
def get_db(db_path: Path = DB_PATH) -> Generator[sqlite3.Connection, None, None]:
    """Context manager retournant une connexion SQLite configurée."""
    conn = sqlite3.connect(db_path, detect_types=sqlite3.PARSE_DECLTYPES)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Dataclasses de retour
# ---------------------------------------------------------------------------

@dataclass
class TradeRecord:
    id: str
    symbol: str
    side: str
    mode: str
    status: str
    entry_price: float
    quantity: float
    leverage: float
    stop_loss: float
    take_profit: float
    opened_at: str
    exit_price: Optional[float] = None
    liquidation_price: Optional[float] = None
    pnl_usdt: Optional[float] = None
    pnl_pct: Optional[float] = None
    fee_usdt: Optional[float] = None
    exit_reason: Optional[str] = None
    signal_id: Optional[int] = None
    strategy_version: int = 1
    closed_at: Optional[str] = None


@dataclass
class SignalRecord:
    id: Optional[int]
    symbol: str
    timestamp: str
    action: str
    confidence: float
    technical_score: float
    fundamental_score: float
    combined_score: float
    reasons: list[str] = field(default_factory=list)
    raw_indicators: dict[str, Any] = field(default_factory=dict)
    strategy_version: int = 1


@dataclass
class StrategyParams:
    version: int = 1
    rsi_period: int = 14
    rsi_oversold: float = 30.0
    rsi_overbought: float = 70.0
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9
    bb_period: int = 20
    bb_std: float = 2.0
    ema_fast: int = 9
    ema_slow: int = 21
    volume_threshold_mult: float = 1.5
    buy_threshold: float = 0.4
    sell_threshold: float = -0.4
    atr_stop_multiplier: float = 1.5
    risk_reward_ratio: float = 2.0
    sentiment_weight: float = 0.25


@dataclass
class BotState:
    is_running: bool
    mode: str
    active_strategy_version: int
    paper_balance: float
    max_drawdown_triggered: bool
    total_trades_count: int
    last_tick_at: Optional[str] = None
    last_news_update_at: Optional[str] = None
    last_optimization_at: Optional[str] = None
    last_snapshot_at: Optional[str] = None
    started_at: Optional[str] = None


# ---------------------------------------------------------------------------
# Classe principale
# ---------------------------------------------------------------------------

class Database:
    """Interface haut niveau pour toutes les opérations de base de données."""

    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path

    @contextmanager
    def _conn(self) -> Generator[sqlite3.Connection, None, None]:
        with get_db(self.db_path) as conn:
            yield conn

    # ------------------------------------------------------------------
    # OHLCV Cache
    # ------------------------------------------------------------------

    def upsert_ohlcv(self, symbol: str, timeframe: str, candles: list[list]) -> int:
        """Insère ou met à jour des bougies OHLCV. Retourne le nombre de lignes insérées."""
        with self._conn() as conn:
            cursor = conn.executemany(
                """INSERT OR REPLACE INTO ohlcv_cache
                   (symbol, timeframe, timestamp, open, high, low, close, volume)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                [(symbol, timeframe, c[0], c[1], c[2], c[3], c[4], c[5]) for c in candles],
            )
            return cursor.rowcount

    def get_ohlcv(
        self, symbol: str, timeframe: str, limit: int = 200
    ) -> list[dict]:
        """Retourne les N dernières bougies pour un symbole/timeframe."""
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT timestamp, open, high, low, close, volume
                   FROM ohlcv_cache WHERE symbol=? AND timeframe=?
                   ORDER BY timestamp DESC LIMIT ?""",
                (symbol, timeframe, limit),
            ).fetchall()
            return [dict(r) for r in reversed(rows)]

    def get_latest_ohlcv_timestamp(self, symbol: str, timeframe: str) -> Optional[int]:
        """Retourne le timestamp de la dernière bougie en cache."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT MAX(timestamp) FROM ohlcv_cache WHERE symbol=? AND timeframe=?",
                (symbol, timeframe),
            ).fetchone()
            return row[0] if row else None

    # ------------------------------------------------------------------
    # Signaux
    # ------------------------------------------------------------------

    def save_signal(self, signal: SignalRecord) -> int:
        """Persiste un signal et retourne son ID."""
        with self._conn() as conn:
            cursor = conn.execute(
                """INSERT INTO signals
                   (symbol, timestamp, action, confidence, technical_score,
                    fundamental_score, combined_score, reasons, raw_indicators, strategy_version)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    signal.symbol,
                    signal.timestamp,
                    signal.action,
                    signal.confidence,
                    signal.technical_score,
                    signal.fundamental_score,
                    signal.combined_score,
                    json.dumps(signal.reasons),
                    json.dumps(signal.raw_indicators),
                    signal.strategy_version,
                ),
            )
            return cursor.lastrowid

    def get_latest_signals(self, limit: int = 20) -> list[dict]:
        """Retourne les N derniers signaux, tous symboles confondus."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM signals ORDER BY timestamp DESC LIMIT ?", (limit,)
            ).fetchall()
            result = []
            for r in rows:
                d = dict(r)
                d["reasons"] = json.loads(d["reasons"] or "[]")
                d["raw_indicators"] = json.loads(d["raw_indicators"] or "{}")
                result.append(d)
            return result

    # ------------------------------------------------------------------
    # Trades
    # ------------------------------------------------------------------

    def save_trade(self, trade: TradeRecord) -> None:
        """Insère un nouveau trade (status='open')."""
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO trades
                   (id, symbol, side, mode, status, entry_price, quantity,
                    leverage, liquidation_price, stop_loss, take_profit,
                    signal_id, strategy_version, opened_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    trade.id, trade.symbol, trade.side, trade.mode, "open",
                    trade.entry_price, trade.quantity, trade.leverage,
                    trade.liquidation_price, trade.stop_loss, trade.take_profit,
                    trade.signal_id, trade.strategy_version, trade.opened_at,
                ),
            )

    def close_trade(
        self,
        trade_id: str,
        exit_price: float,
        pnl_usdt: float,
        pnl_pct: float,
        fee_usdt: float,
        exit_reason: str,
        closed_at: str,
    ) -> None:
        """Clôture un trade ouvert avec son résultat."""
        with self._conn() as conn:
            conn.execute(
                """UPDATE trades SET status='closed', exit_price=?, pnl_usdt=?,
                   pnl_pct=?, fee_usdt=?, exit_reason=?, closed_at=?
                   WHERE id=?""",
                (exit_price, pnl_usdt, pnl_pct, fee_usdt, exit_reason, closed_at, trade_id),
            )
            # Incrémenter le compteur total dans bot_state
            conn.execute(
                "UPDATE bot_state SET total_trades_count = total_trades_count + 1 WHERE id=1"
            )

    def trade_exists(self, trade_id: str) -> bool:
        """Vérifie si un trade existe (ouvert ou fermé) par son ID."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT 1 FROM trades WHERE id=? LIMIT 1", (trade_id,)
            ).fetchone()
            return row is not None

    def get_open_trades(self) -> list[dict]:
        """Retourne tous les trades ouverts."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM trades WHERE status='open' ORDER BY opened_at"
            ).fetchall()
            return [dict(r) for r in rows]

    def get_trade_history(
        self, limit: int = 50, symbol: Optional[str] = None
    ) -> list[dict]:
        """Retourne l'historique des trades clôturés."""
        with self._conn() as conn:
            if symbol:
                rows = conn.execute(
                    """SELECT * FROM trades WHERE status='closed' AND symbol=?
                       ORDER BY closed_at DESC LIMIT ?""",
                    (symbol, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM trades WHERE status='closed' ORDER BY closed_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            return [dict(r) for r in rows]

    def get_closed_trades_count(self) -> int:
        """Nombre total de trades clôturés."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM trades WHERE status='closed'"
            ).fetchone()
            return row[0] if row else 0

    def get_closed_trades_for_analysis(self, limit: int = 200) -> list[dict]:
        """Retourne les trades clôturés avec leurs indicateurs pour l'optimiseur."""
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT t.*, s.raw_indicators, s.technical_score, s.fundamental_score,
                          s.confidence, s.reasons
                   FROM trades t
                   LEFT JOIN signals s ON t.signal_id = s.id
                   WHERE t.status='closed'
                   ORDER BY t.closed_at DESC LIMIT ?""",
                (limit,),
            ).fetchall()
            result = []
            for r in rows:
                d = dict(r)
                if d.get("raw_indicators"):
                    d["raw_indicators"] = json.loads(d["raw_indicators"])
                if d.get("reasons"):
                    d["reasons"] = json.loads(d["reasons"])
                result.append(d)
            return result

    # ------------------------------------------------------------------
    # Portfolio Snapshots
    # ------------------------------------------------------------------

    def save_portfolio_snapshot(
        self,
        usdt_balance: float,
        positions_value: float,
        total_value: float,
        unrealized_pnl: float,
        realized_pnl_today: float,
        open_positions: int,
        snapshot_date: Optional[str] = None,
    ) -> None:
        """Sauvegarde un snapshot quotidien du portfolio."""
        today = snapshot_date or date.today().isoformat()
        with self._conn() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO portfolio_snapshots
                   (snapshot_date, usdt_balance, positions_value, total_value,
                    unrealized_pnl, realized_pnl_today, open_positions)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (today, usdt_balance, positions_value, total_value,
                 unrealized_pnl, realized_pnl_today, open_positions),
            )

    def get_portfolio_history(self, days: int = 30) -> list[dict]:
        """Retourne l'historique des snapshots portfolio."""
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT * FROM portfolio_snapshots
                   ORDER BY snapshot_date DESC LIMIT ?""",
                (days,),
            ).fetchall()
            return [dict(r) for r in reversed(rows)]

    # ------------------------------------------------------------------
    # Performance Metrics
    # ------------------------------------------------------------------

    def save_performance_metrics(self, metrics: dict) -> None:
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO performance_metrics
                   (calculated_at, window_trades, total_trades, winning_trades, losing_trades,
                    win_rate, avg_win_usdt, avg_loss_usdt, profit_factor, sharpe_ratio,
                    max_drawdown_pct, total_pnl_usdt, total_pnl_pct, best_symbol, worst_symbol)
                   VALUES (:calculated_at, :window_trades, :total_trades, :winning_trades,
                           :losing_trades, :win_rate, :avg_win_usdt, :avg_loss_usdt,
                           :profit_factor, :sharpe_ratio, :max_drawdown_pct,
                           :total_pnl_usdt, :total_pnl_pct, :best_symbol, :worst_symbol)""",
                metrics,
            )

    def get_latest_performance(self) -> Optional[dict]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM performance_metrics ORDER BY calculated_at DESC LIMIT 1"
            ).fetchone()
            return dict(row) if row else None

    # ------------------------------------------------------------------
    # Strategy Params
    # ------------------------------------------------------------------

    def get_active_strategy_params(self) -> StrategyParams:
        """Retourne les paramètres de stratégie actifs."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM strategy_params WHERE is_active=1 ORDER BY version DESC LIMIT 1"
            ).fetchone()
            if not row:
                return StrategyParams()
            d = dict(row)
            return StrategyParams(
                version=d["version"],
                rsi_period=d["rsi_period"],
                rsi_oversold=d["rsi_oversold"],
                rsi_overbought=d["rsi_overbought"],
                macd_fast=d["macd_fast"],
                macd_slow=d["macd_slow"],
                macd_signal=d["macd_signal"],
                bb_period=d["bb_period"],
                bb_std=d["bb_std"],
                ema_fast=d["ema_fast"],
                ema_slow=d["ema_slow"],
                volume_threshold_mult=d["volume_threshold_mult"],
                buy_threshold=d["buy_threshold"],
                sell_threshold=d["sell_threshold"],
                atr_stop_multiplier=d["atr_stop_multiplier"],
                risk_reward_ratio=d["risk_reward_ratio"],
                sentiment_weight=d["sentiment_weight"],
            )

    def save_new_strategy_params(
        self,
        params: StrategyParams,
        win_rate: Optional[float] = None,
        profit_factor: Optional[float] = None,
        reason: Optional[str] = None,
    ) -> int:
        """Crée une nouvelle version des paramètres et la marque comme active."""
        with self._conn() as conn:
            # Désactiver l'ancienne version
            conn.execute("UPDATE strategy_params SET is_active=0")
            cursor = conn.execute(
                """INSERT INTO strategy_params
                   (version, is_active, rsi_period, rsi_oversold, rsi_overbought,
                    macd_fast, macd_slow, macd_signal, bb_period, bb_std,
                    ema_fast, ema_slow, volume_threshold_mult, buy_threshold, sell_threshold,
                    atr_stop_multiplier, risk_reward_ratio, sentiment_weight,
                    win_rate_at_creation, profit_factor_at_creation, optimization_reason)
                   VALUES (
                    (SELECT COALESCE(MAX(version), 0) + 1 FROM strategy_params),
                    1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    params.rsi_period, params.rsi_oversold, params.rsi_overbought,
                    params.macd_fast, params.macd_slow, params.macd_signal,
                    params.bb_period, params.bb_std, params.ema_fast, params.ema_slow,
                    params.volume_threshold_mult, params.buy_threshold, params.sell_threshold,
                    params.atr_stop_multiplier, params.risk_reward_ratio, params.sentiment_weight,
                    win_rate, profit_factor, reason,
                ),
            )
            return cursor.lastrowid

    # ------------------------------------------------------------------
    # News
    # ------------------------------------------------------------------

    def save_news_items(self, items: list[dict]) -> int:
        """Sauvegarde des articles de news. Ignore les doublons (url UNIQUE)."""
        if not items:
            return 0
        with self._conn() as conn:
            cursor = conn.executemany(
                """INSERT OR IGNORE INTO news_items
                   (title, body, source, url, published_at, currencies,
                    sentiment_score, sentiment_label)
                   VALUES (:title, :body, :source, :url, :published_at, :currencies,
                           :sentiment_score, :sentiment_label)""",
                items,
            )
            return cursor.rowcount

    def get_recent_news(self, hours: int = 24, currency: Optional[str] = None) -> list[dict]:
        """Retourne les news récentes, filtrées optionnellement par devise."""
        with self._conn() as conn:
            if currency:
                rows = conn.execute(
                    """SELECT * FROM news_items
                       WHERE fetched_at >= datetime('now', ? || ' hours')
                       AND currencies LIKE ?
                       ORDER BY published_at DESC LIMIT 50""",
                    (f"-{hours}", f"%{currency}%"),
                ).fetchall()
            else:
                rows = conn.execute(
                    """SELECT * FROM news_items
                       WHERE fetched_at >= datetime('now', ? || ' hours')
                       ORDER BY published_at DESC LIMIT 100""",
                    (f"-{hours}",),
                ).fetchall()
            return [dict(r) for r in rows]

    def get_news_last_fetched(self) -> Optional[str]:
        """Retourne le datetime de la dernière news récupérée."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT MAX(fetched_at) FROM news_items"
            ).fetchone()
            return row[0] if row else None

    # ------------------------------------------------------------------
    # Bot State
    # ------------------------------------------------------------------

    def get_bot_state(self) -> BotState:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM bot_state WHERE id=1").fetchone()
            d = dict(row)
            return BotState(
                is_running=bool(d["is_running"]),
                mode=d["mode"],
                active_strategy_version=d["active_strategy_version"],
                paper_balance=d["paper_balance"],
                max_drawdown_triggered=bool(d["max_drawdown_triggered"]),
                total_trades_count=d["total_trades_count"],
                last_tick_at=d.get("last_tick_at"),
                last_news_update_at=d.get("last_news_update_at"),
                last_optimization_at=d.get("last_optimization_at"),
                last_snapshot_at=d.get("last_snapshot_at"),
                started_at=d.get("started_at"),
            )

    def update_bot_state(self, **kwargs) -> None:
        """Met à jour des champs spécifiques de l'état du bot."""
        if not kwargs:
            return
        kwargs["updated_at"] = datetime.now(timezone.utc).isoformat()
        set_clause = ", ".join(f"{k}=:{k}" for k in kwargs)
        kwargs["id"] = 1
        with self._conn() as conn:
            conn.execute(
                f"UPDATE bot_state SET {set_clause} WHERE id=:id", kwargs
            )

    def update_paper_balance(self, new_balance: float) -> None:
        self.update_bot_state(paper_balance=new_balance)

    def set_bot_running(self, running: bool, mode: str = "paper") -> None:
        now = datetime.now(timezone.utc).isoformat()
        self.update_bot_state(
            is_running=1 if running else 0,
            mode=mode,
            started_at=now if running else None,
        )

    # ------------------------------------------------------------------
    # Trade Feedback (éducation du bot)
    # ------------------------------------------------------------------

    def save_trade_feedback(
        self,
        trade_id: str,
        rating: str,
        comment: Optional[str] = None,
        context: Optional[dict] = None,
    ) -> int:
        """Sauvegarde le feedback de l'utilisateur sur un trade."""
        with self._conn() as conn:
            cursor = conn.execute(
                """INSERT OR REPLACE INTO trade_feedback
                   (trade_id, rating, comment, context)
                   VALUES (?, ?, ?, ?)""",
                (trade_id, rating, comment, json.dumps(context) if context else None),
            )
            return cursor.lastrowid

    def get_feedback_for_trade(self, trade_id: str) -> Optional[dict]:
        """Retourne le feedback pour un trade donné."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM trade_feedback WHERE trade_id=? ORDER BY created_at DESC LIMIT 1",
                (trade_id,),
            ).fetchone()
            return dict(row) if row else None

    def get_all_feedback(self, limit: int = 100) -> list[dict]:
        """Retourne tous les feedbacks avec les détails du trade associé."""
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT f.*, t.symbol, t.side, t.entry_price, t.exit_price,
                          t.pnl_usdt, t.pnl_pct, t.leverage, t.opened_at, t.closed_at
                   FROM trade_feedback f
                   JOIN trades t ON f.trade_id = t.id
                   ORDER BY f.created_at DESC LIMIT ?""",
                (limit,),
            ).fetchall()
            result = []
            for r in rows:
                d = dict(r)
                if d.get("context"):
                    try:
                        d["context"] = json.loads(d["context"])
                    except Exception:
                        pass
                result.append(d)
            return result

    def get_feedback_stats(self) -> dict:
        """Statistiques globales sur les feedbacks."""
        with self._conn() as conn:
            row = conn.execute(
                """SELECT
                    COUNT(*) as total,
                    SUM(CASE WHEN rating='good' THEN 1 ELSE 0 END) as good_count,
                    SUM(CASE WHEN rating='bad' THEN 1 ELSE 0 END) as bad_count,
                    SUM(CASE WHEN rating='neutral' THEN 1 ELSE 0 END) as neutral_count
                   FROM trade_feedback"""
            ).fetchone()
            return dict(row) if row else {}
