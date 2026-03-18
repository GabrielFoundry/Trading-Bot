/**
 * Application principale du dashboard.
 * WebSocket auto-reconnect + mise à jour DOM.
 */

let ws = null;
let wsRetryDelay = 2000;
const WS_URL = `ws://${location.host}/ws`;

// ─────────────────────────────────────────
// WebSocket
// ─────────────────────────────────────────

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
  const label = document.getElementById('wsLabel');
  if (!dot || !label) return;
  dot.className = 'status-dot';
  const map = {
    connecting:   ['dot-gray', 'Connexion...'],
    connected:    ['dot-green', 'En direct'],
    disconnected: ['dot-gray', 'Déconnecté'],
    error:        ['dot-red', 'Erreur'],
  };
  const [cls, text] = map[status] || ['dot-gray', status];
  dot.classList.add(cls);
  label.textContent = text;
}

// ─────────────────────────────────────────
// Rendu principal
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
  const drawdownAlert = document.getElementById('drawdownAlert');

  if (badge) {
    if (bot.max_drawdown_triggered) {
      badge.textContent = 'ARRÊTÉ (DRAWDOWN)';
      badge.className = 'badge badge-halted';
    } else if (bot.is_running) {
      badge.textContent = 'EN COURS';
      badge.className = 'badge badge-running';
    } else {
      badge.textContent = 'ARRÊTÉ';
      badge.className = 'badge badge-stopped';
    }
  }

  if (drawdownAlert) {
    drawdownAlert.classList.toggle('hidden', !bot.max_drawdown_triggered);
  }

  setText('lastTickAt', bot.last_tick_at ? formatDateTime(bot.last_tick_at) : '—');
  setText('botMode', bot.mode === 'paper' ? '🧪 Paper Trading' : '💰 Live Trading');
}

function renderPortfolioSummary(portfolio, perf) {
  if (!portfolio) return;
  setText('totalValue', formatUsdt(portfolio.total_value));
  setText('usdtBalance', formatUsdt(portfolio.usdt_balance));
  setText('positionsValue', formatUsdt(portfolio.positions_value));
  setText('openPositionsCount', portfolio.open_positions_count);

  if (perf) {
    const pnlEl = document.getElementById('totalPnl');
    if (pnlEl) {
      const pnl = perf.total_pnl_usdt || 0;
      pnlEl.textContent = (pnl >= 0 ? '+' : '') + formatUsdt(pnl);
      pnlEl.className = 'card-value ' + (pnl >= 0 ? 'positive' : 'negative');
    }
  }
}

function renderPositions(positions) {
  const tbody = document.getElementById('positionsBody');
  if (!tbody) return;

  if (!positions || positions.length === 0) {
    tbody.innerHTML = '<tr><td colspan="9" class="empty-state">Aucune position ouverte</td></tr>';
    return;
  }

  tbody.innerHTML = positions.map(p => {
    const side = p.side === 'BUY'
      ? '<span class="action-buy">LONG</span>'
      : '<span class="action-sell">SHORT</span>';
    const leverage = `<span class="leverage-badge">x${p.leverage}</span>`;
    const liq = p.liquidation_price && p.liquidation_price > 0
      ? formatPrice(p.liquidation_price)
      : '—';
    const pnl = p.unrealized_pnl_usdt !== undefined
      ? pnlCell(p.unrealized_pnl_usdt)
      : '—';

    return `<tr>
      <td><strong>${p.symbol}</strong></td>
      <td>${side} ${leverage}</td>
      <td>${formatPrice(p.entry_price)}</td>
      <td>${formatPrice(p.current_price || p.entry_price)}</td>
      <td class="pnl-neg">${formatPrice(p.stop_loss)}</td>
      <td class="pnl-pos">${formatPrice(p.take_profit)}</td>
      <td>${liq}</td>
      <td>${pnl}</td>
      <td>${p.time_open_hours !== undefined ? p.time_open_hours.toFixed(1) + 'h' : '—'}</td>
    </tr>`;
  }).join('');
}

function renderSignals(signals) {
  const container = document.getElementById('signalsContainer');
  if (!container || !signals) return;

  if (signals.length === 0) {
    container.innerHTML = '<div class="empty-state">Aucun signal récent</div>';
    return;
  }

  container.innerHTML = signals.map(s => {
    const cls = s.action === 'BUY' ? 'signal-buy' : s.action === 'SELL' ? 'signal-sell' : 'signal-hold';
    const actionCls = s.action === 'BUY' ? 'action-buy' : s.action === 'SELL' ? 'action-sell' : 'action-hold';
    const conf = Math.round((s.confidence || 0) * 100);
    const reasons = (s.reasons || []).slice(0, 3).map(r =>
      `<li>${escapeHtml(r)}</li>`
    ).join('');

    return `<div class="signal-card ${cls}">
      <div style="display:flex; justify-content:space-between; align-items:center">
        <span class="signal-symbol">${s.symbol}</span>
        <span class="signal-action ${actionCls}">${s.action}</span>
      </div>
      <div class="signal-confidence">${conf}% confiance · score ${(s.combined_score || 0).toFixed(3)}</div>
      <div class="confidence-bar"><div class="confidence-fill" style="width:${conf}%"></div></div>
      ${reasons ? `<ul class="reasons-list">${reasons}</ul>` : ''}
      <div style="font-size:11px; color:var(--text-muted); margin-top:6px">${formatDateTime(s.timestamp)}</div>
    </div>`;
  }).join('');
}

function renderPerformance(perf) {
  if (!perf) return;
  setText('winRate', perf.win_rate != null ? (perf.win_rate * 100).toFixed(1) + '%' : '—');
  setText('profitFactor', perf.profit_factor != null ? perf.profit_factor.toFixed(2) : '—');
  setText('sharpeRatio', perf.sharpe_ratio != null ? perf.sharpe_ratio.toFixed(2) : '—');
  setText('maxDrawdown', perf.max_drawdown_pct != null ? perf.max_drawdown_pct.toFixed(1) + '%' : '—');
  setText('totalTrades', perf.total_trades || '—');
  setText('bestSymbol', perf.best_symbol || '—');
  setText('worstSymbol', perf.worst_symbol || '—');
  updateWinLossChart(perf.winning_trades || 0, perf.losing_trades || 0);
}

// ─────────────────────────────────────────
// Trade history (chargé une fois au démarrage + rafraîchi toutes les 30s)
// ─────────────────────────────────────────

async function loadTradeHistory() {
  const trades = await api.getTradeHistory(30);
  const tbody = document.getElementById('tradesBody');
  if (!tbody) return;

  if (!trades || trades.length === 0) {
    tbody.innerHTML = '<tr><td colspan="7" class="empty-state">Aucun trade clôturé</td></tr>';
    return;
  }

  tbody.innerHTML = trades.map(t => {
    const side = t.side === 'BUY'
      ? '<span class="action-buy">LONG</span>'
      : '<span class="action-sell">SHORT</span>';
    const pnl = t.pnl_usdt != null ? pnlCell(t.pnl_usdt) : '—';
    const pnlPct = t.pnl_pct != null
      ? `<span class="${t.pnl_pct >= 0 ? 'pnl-pos' : 'pnl-neg'}">${t.pnl_pct >= 0 ? '+' : ''}${t.pnl_pct.toFixed(2)}%</span>`
      : '—';

    return `<tr>
      <td><strong>${t.symbol}</strong></td>
      <td>${side} <span class="leverage-badge">x${t.leverage}</span></td>
      <td>${formatPrice(t.entry_price)}</td>
      <td>${t.exit_price != null ? formatPrice(t.exit_price) : '—'}</td>
      <td>${pnl}</td>
      <td>${pnlPct}</td>
      <td><span style="color:var(--text-muted);font-size:12px">${exitReasonLabel(t.exit_reason)}</span></td>
    </tr>`;
  }).join('');
}

// ─────────────────────────────────────────
// Utilitaires
// ─────────────────────────────────────────

function setText(id, value) {
  const el = document.getElementById(id);
  if (el) el.textContent = value ?? '—';
}

function formatUsdt(v) {
  if (v == null) return '—';
  return Number(v).toFixed(2) + ' $';
}

function formatPrice(v) {
  if (v == null) return '—';
  const n = Number(v);
  return n > 100 ? n.toFixed(2) : n.toPrecision(5);
}

function pnlCell(pnl) {
  const cls = pnl > 0 ? 'pnl-pos' : pnl < 0 ? 'pnl-neg' : 'pnl-zero';
  const sign = pnl > 0 ? '+' : '';
  return `<span class="${cls}">${sign}${pnl.toFixed(4)} $</span>`;
}

function formatDateTime(iso) {
  if (!iso) return '—';
  try {
    return new Date(iso).toLocaleString('fr-FR', {
      day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit',
    });
  } catch { return iso; }
}

function exitReasonLabel(reason) {
  const labels = {
    stop_loss: '⛔ Stop-loss',
    take_profit: '✅ Take-profit',
    signal: '📊 Signal',
    liquidation_guard: '⚠️ Garde liq.',
    manual: '🖐 Manuel',
  };
  return labels[reason] || reason || '—';
}

function escapeHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}

// ─────────────────────────────────────────
// Initialisation
// ─────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
  initAllCharts();
  connectWebSocket();
  loadTradeHistory();
  refreshAllCharts();

  // Rafraîchir l'historique et les graphiques toutes les 30s
  setInterval(() => {
    loadTradeHistory();
    refreshAllCharts();
  }, 30000);

  // Bouton reset drawdown
  const resetBtn = document.getElementById('resetDrawdownBtn');
  if (resetBtn) {
    resetBtn.addEventListener('click', async () => {
      if (!confirm('Êtes-vous sûr de vouloir réinitialiser la garde drawdown ?')) return;
      await api.resetDrawdown();
    });
  }
});
