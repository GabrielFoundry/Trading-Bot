/**
 * Initialisation et mise à jour des graphiques Chart.js.
 * Adapté mobile : moins de points, couleurs unifiées.
 */

let portfolioChart = null;
let pnlChart = null;

const C_GREEN  = '#00d4aa';
const C_RED    = '#ff4757';
const C_BORDER = '#2d3561';
const C_TEXT   = '#8892a4';

const BASE_OPTS = {
  responsive: true,
  maintainAspectRatio: false,
  animation: false,
  plugins: { legend: { display: false } },
  scales: {
    x: { grid: { color: C_BORDER }, ticks: { color: C_TEXT, maxTicksLimit: 6 } },
    y: { grid: { color: C_BORDER }, ticks: { color: C_TEXT } },
  },
};

// ─────────────────────────────────────────
// Portfolio
// ─────────────────────────────────────────

function initPortfolioChart() {
  const ctx = document.getElementById('portfolioChart');
  if (!ctx) return;
  portfolioChart = new Chart(ctx, {
    type: 'line',
    data: { labels: [], datasets: [{
      label: 'Portfolio (USDT)',
      data: [],
      borderColor: C_GREEN,
      backgroundColor: 'rgba(0,212,170,0.08)',
      fill: true,
      tension: 0.3,
      pointRadius: 2,
      pointHoverRadius: 5,
    }]},
    options: {
      ...BASE_OPTS,
      plugins: { legend: { display: true, labels: { color: '#e0e0e0', font: { size: 11 } } } },
      scales: {
        x: BASE_OPTS.scales.x,
        y: { ...BASE_OPTS.scales.y,
          ticks: { color: C_TEXT, callback: v => v.toFixed(0) + '$' },
        },
      },
    },
  });
}

async function updatePortfolioChart(days = 30) {
  const data = await api.getPortfolioChart(days);
  if (!data || !portfolioChart) return;
  portfolioChart.data.labels = data.map(d => d.date.slice(5));
  portfolioChart.data.datasets[0].data = data.map(d => d.total_value);
  portfolioChart.update('none');
}

// ─────────────────────────────────────────
// PnL par paire
// ─────────────────────────────────────────

function initPnlChart() {
  const ctx = document.getElementById('pnlChart');
  if (!ctx) return;
  pnlChart = new Chart(ctx, {
    type: 'bar',
    data: { labels: [], datasets: [{
      data: [],
      backgroundColor: [],
      borderRadius: 6,
    }]},
    options: {
      ...BASE_OPTS,
      scales: {
        x: BASE_OPTS.scales.x,
        y: { ...BASE_OPTS.scales.y,
          ticks: { color: C_TEXT, callback: v => v.toFixed(1) + '$' },
        },
      },
    },
  });
}

async function updatePnlChart() {
  const data = await api.getPnlBySymbol();
  if (!data || !pnlChart) return;
  pnlChart.data.labels = data.map(d => d.symbol.replace('/USDT', ''));
  pnlChart.data.datasets[0].data = data.map(d => d.total_pnl);
  pnlChart.data.datasets[0].backgroundColor = data.map(d =>
    d.total_pnl >= 0 ? 'rgba(0,212,170,0.7)' : 'rgba(255,71,87,0.7)'
  );
  pnlChart.update('none');
}

// ─────────────────────────────────────────
// Public
// ─────────────────────────────────────────

function initAllCharts() {
  initPortfolioChart();
  initPnlChart();
}

async function refreshAllCharts(days = 30) {
  await Promise.all([updatePortfolioChart(days), updatePnlChart()]);
}
