-- ============================================================
--  SCHÉMA DE BASE DE DONNÉES — Trading Bot
-- ============================================================

PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

-- Cache des données OHLCV (bougies)
CREATE TABLE IF NOT EXISTS ohlcv_cache (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol      TEXT NOT NULL,
    timeframe   TEXT NOT NULL,
    timestamp   INTEGER NOT NULL,  -- Unix timestamp en ms
    open        REAL NOT NULL,
    high        REAL NOT NULL,
    low         REAL NOT NULL,
    close       REAL NOT NULL,
    volume      REAL NOT NULL,
    created_at  TEXT DEFAULT (datetime('now')),
    UNIQUE(symbol, timeframe, timestamp)
);
CREATE INDEX IF NOT EXISTS idx_ohlcv_symbol_tf_ts ON ohlcv_cache(symbol, timeframe, timestamp DESC);

-- Signaux générés par le bot
CREATE TABLE IF NOT EXISTS signals (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol              TEXT NOT NULL,
    timestamp           TEXT NOT NULL,
    action              TEXT NOT NULL CHECK(action IN ('BUY', 'SELL', 'HOLD')),
    confidence          REAL NOT NULL,
    technical_score     REAL NOT NULL,
    fundamental_score   REAL NOT NULL,
    combined_score      REAL NOT NULL,
    reasons             TEXT,       -- JSON array de strings
    raw_indicators      TEXT,       -- JSON dict des valeurs brutes
    strategy_version    INTEGER NOT NULL DEFAULT 1,
    created_at          TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_signals_symbol_ts ON signals(symbol, timestamp DESC);

-- Trades (paper + réels)
CREATE TABLE IF NOT EXISTS trades (
    id                  TEXT PRIMARY KEY,  -- UUID
    symbol              TEXT NOT NULL,
    side                TEXT NOT NULL CHECK(side IN ('BUY', 'SELL')),
    mode                TEXT NOT NULL CHECK(mode IN ('paper', 'live')),
    status              TEXT NOT NULL CHECK(status IN ('open', 'closed')),
    entry_price         REAL NOT NULL,
    exit_price          REAL,
    quantity            REAL NOT NULL,
    leverage            REAL NOT NULL DEFAULT 1.0,
    liquidation_price   REAL,
    stop_loss           REAL NOT NULL,
    take_profit         REAL NOT NULL,
    pnl_usdt            REAL,           -- Réalisé après clôture
    pnl_pct             REAL,
    fee_usdt            REAL,
    exit_reason         TEXT,           -- 'stop_loss', 'take_profit', 'signal', 'manual', 'liquidation_guard'
    signal_id           INTEGER REFERENCES signals(id),
    strategy_version    INTEGER NOT NULL DEFAULT 1,
    opened_at           TEXT NOT NULL,
    closed_at           TEXT,
    created_at          TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_trades_symbol ON trades(symbol);
CREATE INDEX IF NOT EXISTS idx_trades_status ON trades(status);
CREATE INDEX IF NOT EXISTS idx_trades_opened_at ON trades(opened_at DESC);

-- Snapshots quotidiens du portfolio
CREATE TABLE IF NOT EXISTS portfolio_snapshots (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_date       TEXT NOT NULL UNIQUE,   -- YYYY-MM-DD
    usdt_balance        REAL NOT NULL,
    positions_value     REAL NOT NULL,          -- Valeur mark-to-market des positions
    total_value         REAL NOT NULL,
    unrealized_pnl      REAL NOT NULL,
    realized_pnl_today  REAL NOT NULL DEFAULT 0,
    open_positions      INTEGER NOT NULL DEFAULT 0,
    created_at          TEXT DEFAULT (datetime('now'))
);

-- Métriques de performance calculées périodiquement
CREATE TABLE IF NOT EXISTS performance_metrics (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    calculated_at       TEXT NOT NULL,
    window_trades       INTEGER NOT NULL,   -- Sur combien de trades
    total_trades        INTEGER NOT NULL,
    winning_trades      INTEGER NOT NULL,
    losing_trades       INTEGER NOT NULL,
    win_rate            REAL NOT NULL,
    avg_win_usdt        REAL NOT NULL,
    avg_loss_usdt       REAL NOT NULL,
    profit_factor       REAL NOT NULL,      -- Gross profit / Gross loss
    sharpe_ratio        REAL,
    max_drawdown_pct    REAL NOT NULL,
    total_pnl_usdt      REAL NOT NULL,
    total_pnl_pct       REAL NOT NULL,
    best_symbol         TEXT,
    worst_symbol        TEXT,
    created_at          TEXT DEFAULT (datetime('now'))
);

-- Versions des paramètres de stratégie (jamais mutées, toujours de nouvelles lignes)
CREATE TABLE IF NOT EXISTS strategy_params (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    version                 INTEGER NOT NULL UNIQUE,
    is_active               INTEGER NOT NULL DEFAULT 0,  -- 1 = version courante
    rsi_period              INTEGER NOT NULL DEFAULT 14,
    rsi_oversold            REAL NOT NULL DEFAULT 30,
    rsi_overbought          REAL NOT NULL DEFAULT 70,
    macd_fast               INTEGER NOT NULL DEFAULT 12,
    macd_slow               INTEGER NOT NULL DEFAULT 26,
    macd_signal             INTEGER NOT NULL DEFAULT 9,
    bb_period               INTEGER NOT NULL DEFAULT 20,
    bb_std                  REAL NOT NULL DEFAULT 2.0,
    ema_fast                INTEGER NOT NULL DEFAULT 9,
    ema_slow                INTEGER NOT NULL DEFAULT 21,
    volume_threshold_mult   REAL NOT NULL DEFAULT 1.5,
    buy_threshold           REAL NOT NULL DEFAULT 0.4,
    sell_threshold          REAL NOT NULL DEFAULT -0.4,
    atr_stop_multiplier     REAL NOT NULL DEFAULT 1.5,
    risk_reward_ratio       REAL NOT NULL DEFAULT 2.0,
    sentiment_weight        REAL NOT NULL DEFAULT 0.25,
    -- Métriques à la création (pour comparaison future)
    win_rate_at_creation    REAL,
    profit_factor_at_creation REAL,
    optimization_reason     TEXT,   -- Pourquoi ces params ont été adoptés
    created_at              TEXT DEFAULT (datetime('now'))
);

-- Articles de news avec scores de sentiment
CREATE TABLE IF NOT EXISTS news_items (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    title           TEXT NOT NULL,
    body            TEXT,
    source          TEXT,
    url             TEXT UNIQUE,
    published_at    TEXT NOT NULL,
    currencies      TEXT,       -- JSON array (ex: ["BTC", "ETH"])
    sentiment_score REAL,       -- -1.0 à +1.0
    sentiment_label TEXT,       -- 'bullish', 'bearish', 'neutral'
    fetched_at      TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_news_published_at ON news_items(published_at DESC);
CREATE INDEX IF NOT EXISTS idx_news_fetched_at ON news_items(fetched_at DESC);

-- État global du bot (singleton — toujours 1 seule ligne)
CREATE TABLE IF NOT EXISTS bot_state (
    id                      INTEGER PRIMARY KEY CHECK(id = 1),
    is_running              INTEGER NOT NULL DEFAULT 0,
    mode                    TEXT NOT NULL DEFAULT 'paper' CHECK(mode IN ('paper', 'live')),
    active_strategy_version INTEGER NOT NULL DEFAULT 1,
    paper_balance           REAL NOT NULL DEFAULT 300.0,
    max_drawdown_triggered  INTEGER NOT NULL DEFAULT 0,
    last_tick_at            TEXT,
    last_news_update_at     TEXT,
    last_optimization_at    TEXT,
    last_snapshot_at        TEXT,
    total_trades_count      INTEGER NOT NULL DEFAULT 0,
    started_at              TEXT,
    updated_at              TEXT DEFAULT (datetime('now'))
);

-- Insertion de l'état initial du bot
INSERT OR IGNORE INTO bot_state (id) VALUES (1);

-- Insertion de la version initiale des paramètres de stratégie
INSERT OR IGNORE INTO strategy_params (
    version, is_active, optimization_reason
) VALUES (1, 1, 'Paramètres initiaux depuis config.yaml');
