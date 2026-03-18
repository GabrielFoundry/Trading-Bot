/**
 * Fonctions d'appel à l'API REST.
 */

const API_BASE = '';  // Même origin que le serveur FastAPI

async function apiFetch(path, options = {}) {
  try {
    const res = await fetch(API_BASE + path, options);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return await res.json();
  } catch (e) {
    console.error(`API error ${path}:`, e);
    return null;
  }
}

const api = {
  // Portfolio
  getPortfolioSummary:  () => apiFetch('/api/portfolio/summary'),
  getOpenPositions:     () => apiFetch('/api/portfolio/positions'),
  getPortfolioHistory:  (days = 30) => apiFetch(`/api/portfolio/history?days=${days}`),

  // Trades
  getTradeHistory:      (limit = 50) => apiFetch(`/api/trades/history?limit=${limit}`),
  getTradeStats:        () => apiFetch('/api/trades/stats'),

  // Signals & news
  getLatestSignals:     (limit = 8) => apiFetch(`/api/signals/latest?limit=${limit}`),
  getRecentNews:        (hours = 24) => apiFetch(`/api/signals/news?hours=${hours}`),

  // Bot control
  getBotStatus:         () => apiFetch('/api/bot/status'),
  startBot:             () => apiFetch('/api/bot/start', { method: 'POST' }),
  stopBot:              () => apiFetch('/api/bot/stop',  { method: 'POST' }),
  resetDrawdown:        () => apiFetch('/api/bot/reset-drawdown', { method: 'POST' }),

  // Charts
  getPortfolioChart:    (days = 30) => apiFetch(`/api/charts/portfolio-value?days=${days}`),
  getOHLCV:             (symbol, tf = '1h', limit = 100) =>
    apiFetch(`/api/charts/ohlcv?symbol=${encodeURIComponent(symbol)}&timeframe=${tf}&limit=${limit}`),
  getPnlBySymbol:       () => apiFetch('/api/charts/pnl-by-symbol'),

  // Config
  getConfig:            () => apiFetch('/api/config'),
  updateConfig:         (data) => apiFetch('/api/config', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  }),

  // Feedback (éducation)
  getTradesWithoutFeedback: (limit = 20) => apiFetch(`/api/feedback/trades-without-feedback?limit=${limit}`),
  submitFeedback:           (tradeId, rating, comment = null) =>
    apiFetch(`/api/feedback/${tradeId}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ rating, comment }),
    }),
  getFeedbackStats:         () => apiFetch('/api/feedback/stats'),
};
