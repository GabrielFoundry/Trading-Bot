/**
 * Application principale — Dashboard Trading Bot
 * 4 onglets : Dashboard · Signaux · Contrôle · Éducation
 * WebSocket auto-reconnect + mise à jour DOM.
 */

// ─────────────────────────────────────────
// Navigation par onglets
// ─────────────────────────────────────────

let _currentTab = 'dashboard';

function switchTab(name) {
  // Panels
  document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
  const panel = document.getElementById(`panel-${name}`);
  if (panel) panel.classList.add('active');

  // Nav buttons
  document.querySelectorAll('.nav-btn').forEach(b => {
    b.classList.toggle('active', b.dataset.tab === name);
  });

  _currentTab = name;

  // Chargement lazy selon l'onglet
  if (name === 'control')   loadConfigForm();
  if (name === 'education') loadFeedbackList();
  if (name === 'signals')   loadNewsSection();
}

// ─────────────────────────────────────────
// WebSocket
// ─────────────────────────────────────────

let ws = null;
let wsRetryDelay = 2000;
const WS_PROTO = location.protocol === 'https:' ? 'wss:' : 'ws:';
const WS_URL = `${WS_PROTO}//${location.host}/ws`;

function connectWebSocket() {
  updateWsStatus('connecting');
  ws = new WebSocket(WS_URL);

  ws.onopen = () => {
    wsRetryDelay = 2000;
    updateWsStatus('connected');
  };

  ws.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);
      if (data.type === 'snapshot') renderSnapshot(data);
    } catch (e) {
      console.error('WS parse error:', e);
    }
  };

  ws.onerror = () => updateWsStatus('error');

  ws.onclose = () => {
    updateWsStatus('disconnected');
    setTimeout(() => {
      wsRetryDelay = Math.min(wsRetryDelay * 1.5, 30000);
      connectWebSocket();
    }, wsRetryDelay);
  };
}

function updateWsStatus(status) {
  const dot = document.getElementById('wsDot');
  if (!dot) return;
  dot.className = 'ws-dot';
  const states = {
    connecting:   'dot-gray',
    connected:    'dot-green',
    disconnected: 'dot-gray',
    error:        'dot-red',
  };
  dot.classList.add(states[status] || 'dot-gray');
}

// ─────────────────────────────────────────
// Rendu principal (snapshot WebSocket)
// ─────────────────────────────────────────

function renderSnapshot(data) {
  renderBotStatus(data.bot);
  renderPortfolioSummary(data.portfolio, data.performance);
  renderPositions(data.positions);
  renderSignals(data.signals);
  if (data.performance) renderPerformance(data.performance);
}

function renderBotStatus(bot) {
  if (!bot) return;
  const badge = document.getElementById('botStatusBadge');
  const alert = document.getElementById('drawdownAlert');

  if (badge) {
    if (bot.max_drawdown_triggered) {
      badge.textContent = 'DRAWDOWN';
      badge.className = 'status-pill pill-halted';
    } else if (bot.is_running) {
      badge.textContent = 'EN COURS';
      badge.className = 'status-pill pill-running';
    } else {
      badge.textContent = 'ARRÊTÉ';
      badge.className = 'status-pill pill-stopped';
    }
  }

  if (alert) alert.classList.toggle('hidden', !bot.max_drawdown_triggered);

  setText('lastTickAt', bot.last_tick_at ? fmtDatetime(bot.last_tick_at) : '—');

  const modeEl = document.getElementById('botModeLabel');
  if (modeEl) modeEl.textContent = bot.mode === 'paper' ? '🧪 Paper' : '💰 Live';

  // Statut Contrôle
  const statusEl = document.getElementById('controlStatus');
  if (statusEl) {
    if (bot.is_running) {
      statusEl.textContent = `✅ Bot en cours — dernier tick ${bot.last_tick_at ? fmtDatetime(bot.last_tick_at) : '—'}`;
    } else {
      statusEl.textContent = '⏸ Bot arrêté';
    }
  }
}

function renderPortfolioSummary(portfolio, perf) {
  if (!portfolio) return;
  setText('totalValue', fmtUsdt(portfolio.total_value));
  setText('usdtBalance', fmtUsdt(portfolio.usdt_balance));
  setText('positionsValue', fmtUsdt(portfolio.positions_value));
  setText('openPositionsCount', portfolio.open_positions_count ?? '—');

  if (perf) {
    const pnlEl = document.getElementById('totalPnl');
    if (pnlEl) {
      const pnl = perf.total_pnl_usdt || 0;
      pnlEl.textContent = (pnl >= 0 ? '+' : '') + fmtUsdt(pnl);
      pnlEl.className = 'metric-value ' + (pnl >= 0 ? 'positive' : 'negative');
    }
  }
}

function renderPositions(positions) {
  const el = document.getElementById('positionsList');
  if (!el) return;

  if (!positions || positions.length === 0) {
    el.innerHTML = '<div class="empty-state">Aucune position ouverte</div>';
    return;
  }

  el.innerHTML = positions.map(p => {
    const isLong = p.side === 'BUY';
    const pnl = p.unrealized_pnl_usdt;
    const pnlClass = pnl > 0 ? 'positive' : pnl < 0 ? 'negative' : '';
    const pnlText = pnl != null ? (pnl >= 0 ? '+' : '') + fmtUsdt(pnl) : '—';
    const liq = p.liquidation_price && p.liquidation_price > 0 ? fmtPrice(p.liquidation_price) : '—';

    return `
      <div class="position-card ${isLong ? 'long' : 'short'}">
        <div class="pos-top">
          <span class="pos-symbol">
            <span class="${isLong ? 'side-long' : 'side-short'}">${isLong ? '▲ LONG' : '▼ SHORT'}</span>
            <span class="lev-badge">x${p.leverage}</span>
            ${p.symbol}
          </span>
          <span class="pos-pnl ${pnlClass}">${pnlText}</span>
        </div>
        <div class="pos-details">
          <span class="pos-detail-row"><span>Entrée</span><span>${fmtPrice(p.entry_price)}</span></span>
          <span class="pos-detail-row"><span>Actuel</span><span>${fmtPrice(p.current_price || p.entry_price)}</span></span>
          <span class="pos-detail-row"><span style="color:var(--red)">Stop</span><span>${fmtPrice(p.stop_loss)}</span></span>
          <span class="pos-detail-row"><span style="color:var(--green)">TP</span><span>${fmtPrice(p.take_profit)}</span></span>
          <span class="pos-detail-row"><span>Liquidation</span><span>${liq}</span></span>
          <span class="pos-detail-row"><span>Durée</span><span>${p.time_open_hours != null ? p.time_open_hours.toFixed(1) + 'h' : '—'}</span></span>
        </div>
      </div>`;
  }).join('');
}

function renderSignals(signals) {
  const el = document.getElementById('signalsContainer');
  if (!el || !signals) return;

  if (signals.length === 0) {
    el.innerHTML = '<div class="empty-state">Aucun signal récent</div>';
    return;
  }

  el.innerHTML = signals.map(s => {
    const cls = s.action === 'BUY' ? 'sig-buy' : s.action === 'SELL' ? 'sig-sell' : 'sig-hold';
    const actionCls = s.action === 'BUY' ? 'action-buy' : s.action === 'SELL' ? 'action-sell' : 'action-hold';
    const conf = Math.round((s.confidence || 0) * 100);
    const reasons = (s.reasons || []).slice(0, 3).map(r => `<li>${escHtml(r)}</li>`).join('');

    return `
      <div class="signal-card ${cls}">
        <div class="sig-top">
          <span class="sig-symbol">${s.symbol}</span>
          <span class="sig-action ${actionCls}">${s.action}</span>
        </div>
        <div class="sig-conf">${conf}% confiance · score ${(s.combined_score || 0).toFixed(3)}</div>
        <div class="conf-bar"><div class="conf-fill" style="width:${conf}%"></div></div>
        ${reasons ? `<ul class="reasons">${reasons}</ul>` : ''}
        <div class="sig-time">${fmtDatetime(s.timestamp)}</div>
      </div>`;
  }).join('');
}

function renderPerformance(perf) {
  if (!perf) return;
  setText('winRate',     perf.win_rate     != null ? (perf.win_rate * 100).toFixed(1) + '%' : '—');
  setText('profitFactor', perf.profit_factor != null ? perf.profit_factor.toFixed(2) : '—');
  setText('sharpeRatio', perf.sharpe_ratio  != null ? perf.sharpe_ratio.toFixed(2) : '—');
  const ddEl = document.getElementById('maxDrawdown');
  if (ddEl) {
    ddEl.textContent = perf.max_drawdown_pct != null ? perf.max_drawdown_pct.toFixed(1) + '%' : '—';
    ddEl.className = 'perf-value negative';
  }
  setText('totalTrades', perf.total_trades || '—');
  setText('bestSymbol',  perf.best_symbol  || '—');
  setText('worstSymbol', perf.worst_symbol || '—');
}

// ─────────────────────────────────────────
// Historique des trades (cards)
// ─────────────────────────────────────────

async function loadTradeHistory() {
  const trades = await api.getTradeHistory(30);
  const el = document.getElementById('tradesList');
  if (!el) return;

  if (!trades || trades.length === 0) {
    el.innerHTML = '<div class="empty-state">Aucun trade clôturé</div>';
    return;
  }

  el.innerHTML = trades.map(t => {
    const isLong = t.side === 'BUY';
    const pnl = t.pnl_usdt;
    const pnlClass = pnl > 0 ? 'positive' : pnl < 0 ? 'negative' : '';
    const pnlSign = pnl > 0 ? '+' : '';
    const pnlPct = t.pnl_pct != null ? `${t.pnl_pct >= 0 ? '+' : ''}${t.pnl_pct.toFixed(2)}%` : '';

    return `
      <div class="trade-card">
        <div>
          <span class="${isLong ? 'side-long' : 'side-short'}">${isLong ? '▲' : '▼'}</span>
          <span class="lev-badge">x${t.leverage}</span>
        </div>
        <div class="trade-symbol">${t.symbol}</div>
        <div class="trade-info">
          ${fmtPrice(t.entry_price)} → ${t.exit_price != null ? fmtPrice(t.exit_price) : '—'}
          <br><span style="color:var(--text-muted)">${exitLabel(t.exit_reason)}</span>
        </div>
        <div class="trade-pnl ${pnlClass}">
          ${pnl != null ? pnlSign + fmtUsdt(pnl) : '—'}
          ${pnlPct ? `<br><span style="font-size:11px">${pnlPct}</span>` : ''}
        </div>
      </div>`;
  }).join('');
}

// ─────────────────────────────────────────
// News (onglet Signaux)
// ─────────────────────────────────────────

async function loadNewsSection() {
  const el = document.getElementById('newsList');
  if (!el) return;

  const news = await api.getRecentNews(48);
  if (!news || news.length === 0) {
    el.innerHTML = '<div class="empty-state">Aucune news récente</div>';
    return;
  }

  el.innerHTML = news.map(n => {
    const s = n.sentiment_score || 0;
    const sentClass = s > 0.1 ? 'sent-pos' : s < -0.1 ? 'sent-neg' : 'sent-neu';
    const sentLabel = s > 0.1 ? '↑ Positif' : s < -0.1 ? '↓ Négatif' : '→ Neutre';

    return `
      <div class="news-item">
        <div class="news-title">${escHtml(n.title || '—')}</div>
        <div class="news-meta">
          ${n.currencies || ''} · ${fmtDatetime(n.published_at)}
          <span class="news-sentiment ${sentClass}">${sentLabel}</span>
        </div>
      </div>`;
  }).join('');
}

// ─────────────────────────────────────────
// Contrôle du bot
// ─────────────────────────────────────────

async function botAction(action) {
  const title = action === 'start' ? 'Démarrer le bot ?' : 'Arrêter le bot ?';
  const body  = action === 'start'
    ? 'Le bot va commencer à analyser les marchés et prendre des positions.'
    : 'Le bot va arrêter de prendre de nouvelles positions. Les positions ouvertes restent actives.';

  showModal(title, body, async () => {
    const result = action === 'start' ? await api.startBot() : await api.stopBot();
    const statusEl = document.getElementById('controlStatus');
    if (result && result.success) {
      if (statusEl) statusEl.textContent = result.message;
    } else {
      if (statusEl) statusEl.textContent = 'Erreur lors de l\'action.';
    }
  });
}

// ─────────────────────────────────────────
// Éducation / Feedback
// ─────────────────────────────────────────

async function loadFeedbackList() {
  const el = document.getElementById('feedbackList');
  if (!el) return;

  el.innerHTML = '<div class="empty-state"><span class="spinner"></span></div>';

  const trades = await api.getTradesWithoutFeedback(20);
  if (!trades || trades.length === 0) {
    el.innerHTML = `
      <div class="card" style="text-align:center">
        <div style="font-size:32px;margin-bottom:12px">🎉</div>
        <div style="font-size:15px;font-weight:600;margin-bottom:6px">Tous les trades sont notés !</div>
        <div class="help-text">Revenez après les prochains trades pour continuer à éduquer le bot.</div>
      </div>`;
    return;
  }

  el.innerHTML = trades.map(t => _buildFeedbackCard(t)).join('');
}

function _buildFeedbackCard(t) {
  const isLong = t.side === 'BUY';
  const pnl = t.pnl_usdt;
  const pnlClass = pnl > 0 ? 'positive' : pnl < 0 ? 'negative' : '';
  const pnlText = pnl != null ? (pnl >= 0 ? '+' : '') + fmtUsdt(pnl) : '—';
  const pnlPct = t.pnl_pct != null ? ` (${t.pnl_pct >= 0 ? '+' : ''}${t.pnl_pct.toFixed(2)}%)` : '';

  return `
    <div class="feedback-card" id="fc-${t.id}">
      <div class="fb-top">
        <div>
          <span class="fb-symbol">${t.symbol}</span>
          <span class="lev-badge">x${t.leverage}</span>
          <span class="${isLong ? 'side-long' : 'side-short'}" style="font-size:12px;margin-left:6px">
            ${isLong ? '▲ LONG' : '▼ SHORT'}
          </span>
        </div>
        <span class="fb-pnl ${pnlClass}">${pnlText}${pnlPct}</span>
      </div>
      <div class="fb-info">
        ${fmtPrice(t.entry_price)} → ${t.exit_price != null ? fmtPrice(t.exit_price) : '—'}
        · ${exitLabel(t.exit_reason)}
        · ${fmtDatetime(t.opened_at || t.closed_at)}
      </div>
      <div class="fb-buttons">
        <button class="fb-btn" onclick="rateTrade('${t.id}', 'good', this)">👍 Bon</button>
        <button class="fb-btn" onclick="rateTrade('${t.id}', 'neutral', this)">🔵 Neutre</button>
        <button class="fb-btn" onclick="rateTrade('${t.id}', 'bad', this)">👎 Mauvais</button>
      </div>
    </div>`;
}

async function rateTrade(tradeId, rating, btn) {
  const result = await api.submitFeedback(tradeId, rating);
  if (result && result.success) {
    const card = document.getElementById(`fc-${tradeId}`);
    if (card) {
      const labels = { good: '👍 Bon trade', neutral: '🔵 Neutre', bad: '👎 Mauvais trade' };
      card.querySelector('.fb-buttons').innerHTML = `
        <div class="fb-rated">✓ Noté : ${labels[rating]}</div>`;
    }
  }
}

// ─────────────────────────────────────────
// Modal
// ─────────────────────────────────────────

let _modalCallback = null;

function showModal(title, body, onConfirm) {
  document.getElementById('modalTitle').textContent = title;
  document.getElementById('modalBody').textContent = body;
  _modalCallback = onConfirm;
  document.getElementById('confirmModal').classList.remove('hidden');
}

function closeModal() {
  document.getElementById('confirmModal').classList.add('hidden');
  _modalCallback = null;
}

document.addEventListener('DOMContentLoaded', () => {
  document.getElementById('modalConfirm').addEventListener('click', () => {
    closeModal();
    if (_modalCallback) _modalCallback();
  });
});

// ─────────────────────────────────────────
// Utilitaires
// ─────────────────────────────────────────

function setText(id, value) {
  const el = document.getElementById(id);
  if (el) el.textContent = value ?? '—';
}

function fmtUsdt(v) {
  if (v == null) return '—';
  return Number(v).toFixed(2) + ' $';
}

function fmtPrice(v) {
  if (v == null) return '—';
  const n = Number(v);
  return n > 100 ? n.toFixed(2) : n.toPrecision(5);
}

function fmtDatetime(iso) {
  if (!iso) return '—';
  try {
    return new Date(iso).toLocaleString('fr-FR', {
      day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit',
    });
  } catch { return iso; }
}

function exitLabel(reason) {
  const m = {
    stop_loss: '⛔ Stop-loss', take_profit: '✅ TP',
    signal: '📊 Signal', liquidation_guard: '⚠️ Liq.', manual: '🖐 Manuel',
  };
  return m[reason] || reason || '—';
}

function escHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

// ─────────────────────────────────────────
// Initialisation
// ─────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
  initAllCharts();
  connectWebSocket();
  loadTradeHistory();

  // Portfolio chart range selector
  const rangeEl = document.getElementById('portfolioRange');
  if (rangeEl) {
    rangeEl.addEventListener('change', () => {
      refreshAllCharts(parseInt(rangeEl.value));
    });
  }

  refreshAllCharts(30);
  setInterval(() => {
    loadTradeHistory();
    refreshAllCharts(parseInt(document.getElementById('portfolioRange')?.value || 30));
  }, 30000);

  // Reset drawdown
  const resetBtn = document.getElementById('resetDrawdownBtn');
  if (resetBtn) {
    resetBtn.addEventListener('click', async () => {
      await api.resetDrawdown();
    });
  }

  // Shortcut depuis URL (PWA)
  const params = new URLSearchParams(location.search);
  if (params.get('action') === 'start') botAction('start');
  if (params.get('action') === 'stop')  botAction('stop');
});
