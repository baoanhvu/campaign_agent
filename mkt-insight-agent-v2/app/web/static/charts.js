function renderCharts(dashboard) {
  renderRomiChart(dashboard.campaigns);
  renderFunnelChart(dashboard.funnel);
  renderTrendChart(dashboard.trend);
}

function renderRomiChart(campaigns) {
  const el = document.getElementById('chart-romi');
  if (!el) return;
  const data = campaigns.map(c => ({ name: c.campaign_name, value: c.romi || 0 }));
  echarts.init(el).setOption({
    tooltip: { trigger: 'axis', formatter: p => `${p[0].name}<br/>ROMI: ${(p[0].value * 100).toFixed(1)}%` },
    xAxis: { type: 'value', axisLabel: { formatter: v => (v * 100).toFixed(0) + '%' } },
    yAxis: { type: 'category', data: data.map(d => d.name) },
    series: [{
      type: 'bar',
      data: data.map(d => ({
        value: d.value,
        itemStyle: { color: d.value >= 0 ? '#16a34a' : '#dc2626' },
      })),
    }],
  });
}

function renderFunnelChart(funnel) {
  const el = document.getElementById('chart-funnel');
  if (!el || !funnel.length) return;
  const stages = ['leads', 'profiles', 'approvals', 'disbursements'];
  const labels = ['Leads', 'Hồ sơ', 'Duyệt', 'Giải ngân'];
  const total = funnel.reduce((acc, c) => { stages.forEach(s => acc[s] = (acc[s] || 0) + (c[s] || 0)); return acc; }, {});
  echarts.init(el).setOption({
    tooltip: { trigger: 'item' },
    series: [{
      type: 'funnel',
      data: labels.map((l, i) => ({ name: l, value: total[stages[i]] || 0 })),
    }],
  });
}

function renderTrendChart(trend) {
  const el = document.getElementById('chart-trend');
  if (!el || !trend.length) return;
  echarts.init(el).setOption({
    tooltip: { trigger: 'axis' },
    legend: { data: ['Chi phí', 'Doanh thu', 'Lợi nhuận'] },
    xAxis: { type: 'category', data: trend.map(t => t.date) },
    yAxis: { type: 'value', axisLabel: { formatter: v => fmtVndShortJS(v) } },
    series: [
      { name: 'Chi phí', type: 'line', data: trend.map(t => t.spend), itemStyle: { color: '#f59e0b' } },
      { name: 'Doanh thu', type: 'line', data: trend.map(t => t.revenue), itemStyle: { color: '#3b82f6' } },
      { name: 'Lợi nhuận', type: 'line', data: trend.map(t => t.profit), itemStyle: { color: '#16a34a' } },
    ],
  });
}

function renderSegmentCharts(segments) {
  renderSegmentScatter(segments);
  renderRepeatRateChart(segments);
}

function renderSegmentScatter(segments) {
  const el = document.getElementById('chart-segment-scatter');
  if (!el) return;
  echarts.init(el).setOption({
    tooltip: { formatter: p => `${p.data[2]}<br/>Size: ${p.data[0]}<br/>CLV: ${fmtVndShortJS(p.data[1])}` },
    xAxis: { name: 'Kích thước', type: 'value' },
    yAxis: { name: 'CLV', type: 'value', axisLabel: { formatter: v => fmtVndShortJS(v) } },
    series: [{
      type: 'scatter',
      symbolSize: d => Math.sqrt(d[0]) / 2,
      data: segments.map(s => [s.size || 0, s.clv_mean || 0, s.segment_name]),
    }],
  });
}

function renderRepeatRateChart(segments) {
  const el = document.getElementById('chart-repeat-rate');
  if (!el) return;
  echarts.init(el).setOption({
    tooltip: { trigger: 'axis' },
    xAxis: { type: 'category', data: segments.map(s => s.segment_name) },
    yAxis: { type: 'value', axisLabel: { formatter: v => (v * 100).toFixed(0) + '%' } },
    series: [{
      type: 'bar',
      data: segments.map(s => ({
        value: s.repeat_rate || 0,
        itemStyle: { color: '#3b82f6' },
      })),
      markPoint: { data: [] },
    }],
  });
}
