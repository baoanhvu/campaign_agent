const viNumberFormat = new Intl.NumberFormat('vi-VN');
const viCurrencyFormat = new Intl.NumberFormat('vi-VN', { style: 'currency', currency: 'VND', maximumFractionDigits: 0 });

function fmtVnd(v) {
  if (v === null || v === undefined || isNaN(v)) return '—';
  return viNumberFormat.format(v) + ' VND';
}

function fmtVndShort(v) {
  if (v === null || v === undefined || isNaN(v)) return '—';
  const a = Math.abs(v);
  if (a >= 1e9) return (v / 1e9).toFixed(1).replace('.', ',') + ' tỷ';
  if (a >= 1e6) return (v / 1e6).toFixed(1).replace('.', ',') + ' tr';
  return viNumberFormat.format(v);
}

function fmtVndShortJS(v) { return fmtVndShort(v); }

function fmtPct(v, d = 1) {
  if (v === null || v === undefined || isNaN(v)) return '—';
  return (v * 100).toFixed(d).replace('.', ',') + '%';
}

function fmtRatio(v, d = 2) {
  if (v === null || v === undefined || isNaN(v)) return '—';
  return v.toFixed(d).replace('.', ',');
}

function fmtInt(v) {
  if (v === null || v === undefined || isNaN(v)) return '—';
  return viNumberFormat.format(v);
}
