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
  getPortfolioSummary:  () => apiFetch('/api/portfolio/summary'),
  getOpenPositions:     () => apiFetch('/api/portfolio/positions'),
  getPortfolioHistory:  (days=30) => apiFetch(`/api/portfolio/history?days=${days}`),
  getTradeHistory:      (limit=50) => apiFetch(`/api/trades/history?limit=${limit}`),
  getTradeStats:        () => apiFetch('/api/trades/stats'),
  getLatestSignals:     (limit=8) => apiFetch(`/api/signals/latest?limit=${limit}`),
  getRecentNews:        (hours=24) => apiFetch(`/api/signals/news?hours=${hours}`),
  getBotStatus:         () => apiFetch('/api/bot/status'),
  resetDrawdown:        () => apiFetch('/api/bot/reset-drawdown', { method: 'POST' }),
  getPortfolioChart:    (days=30) => apiFetch(`/api/charts/portfolio-value?days=${days}`),
  getOHLCV:             (symbol, tf='1h', limit=100) =>
    apiFetch(`/api/charts/ohlcv?symbol=${encodeURIComponent(symbol)}&timeframe=${tf}&limit=${limit}`),
  getPnlBySymbol:       () => apiFetch('/api/charts/pnl-by-symbol'),
};
