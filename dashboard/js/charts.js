/**
 * Initialisation et mise à jour des graphiques Chart.js.
 */

let portfolioChart = null;
let pnlChart = null;
let winLossChart = null;

const CHART_DEFAULTS = {
  responsive: true,
  maintainAspectRatio: false,
  plugins: { legend: { display: false } },
  scales: {
    x: { grid: { color: '#30363d' }, ticks: { color: '#7d8590', maxTicksLimit: 8 } },
    y: { grid: { color: '#30363d' }, ticks: { color: '#7d8590' } },
  },
};

function initPortfolioChart() {
  const ctx = document.getElementById('portfolioChart');
  if (!ctx) return;
  portfolioChart = new Chart(ctx, {
    type: 'line',
    data: { labels: [], datasets: [{
      label: 'Valeur Portfolio (USDT)',
      data: [],
      borderColor: '#58a6ff',
      backgroundColor: 'rgba(88,166,255,0.08)',
      fill: true,
      tension: 0.3,
      pointRadius: 3,
      pointHoverRadius: 5,
    }]},
    options: {
      ...CHART_DEFAULTS,
      plugins: { legend: { display: true, labels: { color: '#e6edf3' } } },
      scales: {
        x: { ...CHART_DEFAULTS.scales.x },
        y: { ...CHART_DEFAULTS.scales.y,
          ticks: { color: '#7d8590', callback: v => v.toFixed(2) + ' $' }
        },
      },
    },
  });
}

async function updatePortfolioChart() {
  const data = await api.getPortfolioChart(30);
  if (!data || !portfolioChart) return;
  portfolioChart.data.labels = data.map(d => d.date.slice(5)); // MM-DD
  portfolioChart.data.datasets[0].data = data.map(d => d.total_value);
  portfolioChart.update('none');
}

function initPnlChart() {
  const ctx = document.getElementById('pnlChart');
  if (!ctx) return;
  pnlChart = new Chart(ctx, {
    type: 'bar',
    data: { labels: [], datasets: [{
      data: [],
      backgroundColor: [],
      borderRadius: 4,
    }]},
    options: {
      ...CHART_DEFAULTS,
      scales: {
        x: { ...CHART_DEFAULTS.scales.x },
        y: { ...CHART_DEFAULTS.scales.y,
          ticks: { color: '#7d8590', callback: v => v.toFixed(2) + ' $' }
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
    d.total_pnl >= 0 ? 'rgba(63,185,80,0.7)' : 'rgba(248,81,73,0.7)'
  );
  pnlChart.update('none');
}

function initWinLossChart() {
  const ctx = document.getElementById('winLossChart');
  if (!ctx) return;
  winLossChart = new Chart(ctx, {
    type: 'doughnut',
    data: {
      labels: ['Gagnants', 'Perdants'],
      datasets: [{ data: [0, 0], backgroundColor: ['#3fb950', '#f85149'], borderWidth: 0 }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: true, position: 'bottom', labels: { color: '#e6edf3', padding: 12 } },
      },
      cutout: '65%',
    },
  });
}

function updateWinLossChart(winning, losing) {
  if (!winLossChart) return;
  winLossChart.data.datasets[0].data = [winning, losing];
  winLossChart.update('none');
}

function initAllCharts() {
  initPortfolioChart();
  initPnlChart();
  initWinLossChart();
}

async function refreshAllCharts() {
  await Promise.all([updatePortfolioChart(), updatePnlChart()]);
}
