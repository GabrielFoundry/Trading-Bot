/**
 * Éditeur de configuration in-app (onglet Contrôle).
 * Charge la config depuis /api/config, affiche un formulaire mobile,
 * envoie les modifications via POST /api/config.
 */

const AVAILABLE_PAIRS = ['BTC/USDT', 'ETH/USDT', 'BNB/USDT', 'SOL/USDT', 'XRP/USDT', 'ADA/USDT'];

let _currentConfig = null;
let _selectedPairs = new Set();

// ─────────────────────────────────────────
// Chargement initial
// ─────────────────────────────────────────

async function loadConfigForm() {
  const container = document.getElementById('configForm');
  if (!container) return;

  const cfg = await api.getConfig();
  if (!cfg) {
    container.innerHTML = '<div class="empty-state">Impossible de charger la configuration.</div>';
    return;
  }

  _currentConfig = cfg;
  _selectedPairs = new Set(cfg.trading.pairs || []);

  container.innerHTML = _buildForm(cfg);
  _bindFormEvents(container);
}

// ─────────────────────────────────────────
// Construction HTML
// ─────────────────────────────────────────

function _buildForm(cfg) {
  const t = cfg.trading;
  const r = cfg.risk;
  const lev = cfg.leverage;
  const news = cfg.news;
  const sched = cfg.schedule;
  const scheduler = cfg.scheduler;

  return `
    <!-- Paires -->
    <div class="form-group">
      <div class="form-label">Paires tradées</div>
      <div class="pairs-grid" id="pairsGrid">
        ${AVAILABLE_PAIRS.map(p => `
          <div class="pair-toggle ${_selectedPairs.has(p) ? 'selected' : ''}"
               data-pair="${p}" onclick="togglePair(this, '${p}')">
            ${p.replace('/USDT', '')}
          </div>
        `).join('')}
      </div>
    </div>

    <!-- Risque par trade -->
    <div class="form-group">
      <div class="form-label">Risque par trade : <span id="riskVal">${t.risk_per_trade_pct}</span>%</div>
      <div class="range-row">
        <span style="font-size:12px;color:var(--text-muted)">1%</span>
        <input type="range" id="riskRange" min="1" max="10" step="0.5"
               value="${t.risk_per_trade_pct}"
               oninput="document.getElementById('riskVal').textContent=this.value">
        <span style="font-size:12px;color:var(--text-muted)">10%</span>
      </div>
    </div>

    <!-- Max positions -->
    <div class="form-group">
      <div class="form-label">Positions simultanées max</div>
      <select id="maxPositions" class="form-select">
        ${[1,2,3,4,5].map(n =>
          `<option value="${n}" ${n === t.max_open_positions ? 'selected' : ''}>${n}</option>`
        ).join('')}
      </select>
    </div>

    <!-- Timeframe -->
    <div class="form-group">
      <div class="form-label">Timeframe</div>
      <select id="timeframe" class="form-select">
        ${['1m','5m','15m','1h','4h','1d'].map(tf =>
          `<option value="${tf}" ${tf === t.timeframe ? 'selected' : ''}>${tf}</option>`
        ).join('')}
      </select>
    </div>

    <!-- Levier max -->
    <div class="form-group">
      <div class="form-label">Levier maximum</div>
      <select id="maxLeverage" class="form-select">
        ${[1.0, 1.5, 2.0].map(l =>
          `<option value="${l}" ${l === lev.max_leverage ? 'selected' : ''}>x${l}</option>`
        ).join('')}
      </select>
    </div>

    <!-- Stop-loss -->
    <div class="form-group">
      <div class="form-label">Stop-loss : <span id="slVal">${r.stop_loss_pct}</span>%</div>
      <div class="range-row">
        <span style="font-size:12px;color:var(--text-muted)">0.5%</span>
        <input type="range" id="slRange" min="0.5" max="10" step="0.5"
               value="${r.stop_loss_pct}"
               oninput="document.getElementById('slVal').textContent=this.value">
        <span style="font-size:12px;color:var(--text-muted)">10%</span>
      </div>
    </div>

    <!-- Take-profit -->
    <div class="form-group">
      <div class="form-label">Take-profit : <span id="tpVal">${r.take_profit_pct}</span>%</div>
      <div class="range-row">
        <span style="font-size:12px;color:var(--text-muted)">0.5%</span>
        <input type="range" id="tpRange" min="0.5" max="20" step="0.5"
               value="${r.take_profit_pct}"
               oninput="document.getElementById('tpVal').textContent=this.value">
        <span style="font-size:12px;color:var(--text-muted)">20%</span>
      </div>
    </div>

    <!-- Drawdown max -->
    <div class="form-group">
      <div class="form-label">Drawdown max : <span id="ddVal">${r.max_drawdown_pct}</span>%</div>
      <div class="range-row">
        <span style="font-size:12px;color:var(--text-muted)">5%</span>
        <input type="range" id="ddRange" min="5" max="50" step="1"
               value="${r.max_drawdown_pct}"
               oninput="document.getElementById('ddVal').textContent=this.value">
        <span style="font-size:12px;color:var(--text-muted)">50%</span>
      </div>
    </div>

    <!-- Poids news -->
    <div class="form-group">
      <div class="form-label">Poids des news : <span id="newsVal">${Math.round((news.sentiment_weight||0)*100)}</span>%</div>
      <div class="range-row">
        <span style="font-size:12px;color:var(--text-muted)">0%</span>
        <input type="range" id="newsRange" min="0" max="50" step="5"
               value="${Math.round((news.sentiment_weight||0)*100)}"
               oninput="document.getElementById('newsVal').textContent=this.value">
        <span style="font-size:12px;color:var(--text-muted)">50%</span>
      </div>
    </div>

    <!-- Plages horaires -->
    <div class="form-group">
      <div class="form-label">Plages horaires</div>
      <label class="pair-toggle" style="grid-column:span 2; justify-content:flex-start">
        <input type="checkbox" id="schedEnabled" ${sched.enabled ? 'checked' : ''}
               style="accent-color:var(--green); width:18px; height:18px">
        Activer les plages horaires
      </label>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:8px">
        <div>
          <div class="form-label" style="margin-bottom:4px">Début</div>
          <input type="time" id="schedStart" class="form-input" value="${sched.start || '08:00'}">
        </div>
        <div>
          <div class="form-label" style="margin-bottom:4px">Fin</div>
          <input type="time" id="schedEnd" class="form-input" value="${sched.end || '22:00'}">
        </div>
      </div>
    </div>

    <!-- Bouton Sauvegarder -->
    <button class="save-btn" onclick="saveConfig()">💾 Sauvegarder</button>
    <div id="saveResult" class="save-result" style="display:none"></div>
  `;
}

// ─────────────────────────────────────────
// Interactions
// ─────────────────────────────────────────

function togglePair(el, pair) {
  if (_selectedPairs.has(pair)) {
    _selectedPairs.delete(pair);
    el.classList.remove('selected');
  } else {
    _selectedPairs.add(pair);
    el.classList.add('selected');
  }
}

function _bindFormEvents(container) {
  // Les events sont déjà en inline onclick/oninput dans le HTML généré
}

async function saveConfig() {
  if (_selectedPairs.size === 0) {
    _showSaveResult('Au moins une paire requise.', false);
    return;
  }

  const payload = {
    pairs: Array.from(_selectedPairs),
    risk_per_trade_pct: parseFloat(document.getElementById('riskRange').value),
    max_open_positions: parseInt(document.getElementById('maxPositions').value),
    timeframe: document.getElementById('timeframe').value,
    max_leverage: parseFloat(document.getElementById('maxLeverage').value),
    stop_loss_pct: parseFloat(document.getElementById('slRange').value),
    take_profit_pct: parseFloat(document.getElementById('tpRange').value),
    max_drawdown_pct: parseFloat(document.getElementById('ddRange').value),
    sentiment_weight: parseInt(document.getElementById('newsRange').value) / 100,
    schedule_enabled: document.getElementById('schedEnabled').checked,
    schedule_start: document.getElementById('schedStart').value,
    schedule_end: document.getElementById('schedEnd').value,
  };

  const result = await api.updateConfig(payload);
  if (result && result.success) {
    _showSaveResult(`✓ ${result.message}`, true);
  } else {
    _showSaveResult('Erreur lors de la sauvegarde.', false);
  }
}

function _showSaveResult(msg, ok) {
  const el = document.getElementById('saveResult');
  if (!el) return;
  el.textContent = msg;
  el.className = `save-result ${ok ? 'ok' : 'err'}`;
  el.style.display = 'block';
  setTimeout(() => { el.style.display = 'none'; }, 4000);
}
