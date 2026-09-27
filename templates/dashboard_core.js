/* Pure data transformations shared by the dashboard and its Node checks. */
(function (scope) {
  'use strict';
  const populations = ['b_cell', 'cd8_t_cell', 'cd4_t_cell', 'nk_cell', 'monocyte'];
  function unpack(payload) {
    return payload.rows.map(row => {
      const r = Object.fromEntries(payload.columns.map((c, i) => [c, row[i]]));
      r.total_count = populations.reduce((n, p) => n + r[p], 0);
      r.values = populations.map(p => r.total_count ? 100 * r[p] / r.total_count : null);
      return r;
    });
  }
  function filterRows(rows, filters) {
    return rows.filter(r => Object.entries(filters).every(([k, v]) => v === '' || String(r[k] ?? 'unknown') === String(v)));
  }
  function isCohort(r) {
    return r.condition === 'melanoma' && r.treatment === 'miraclib' && r.sample_type === 'PBMC';
  }
  function frequencies(rows) {
    return rows.flatMap(r => populations.map((p, i) => ({sample: r.sample, total_count: r.total_count, population: p, count: r[p], percentage: r.values[i]})));
  }
  function comparisonValues(cohort, mode) {
    const days = {baseline: 0, day7: 7, day14: 14};
    const selected = cohort.filter(r => ['yes', 'no'].includes(r.response) && r.total_count > 0 && (!(mode in days) || r.time_from_treatment_start === days[mode]));
    if (mode === 'samples') return selected.map(r => ({id: r.sample, subject: r.subject, response: r.response, values: r.values, n: 1}));
    const subjects = new Map();
    for (const r of selected) {
      if (!subjects.has(r.subject)) subjects.set(r.subject, {id: r.subject, response: r.response, values: [0, 0, 0, 0, 0], n: 0});
      const s = subjects.get(r.subject);
      if (s.response !== r.response) throw new Error('A subject has conflicting response labels.');
      s.n++;
      r.values.forEach((v, i) => s.values[i] += v);
    }
    return Array.from(subjects.values(), s => ({...s, values: s.values.map(v => v / s.n)}));
  }
  function quantile(sorted, p) {
    if (!sorted.length) return null;
    const x = (sorted.length - 1) * p, lo = Math.floor(x), hi = Math.ceil(x);
    return sorted[lo] + (sorted[hi] - sorted[lo]) * (x - lo);
  }
  function boxStats(values) {
    const v = values.filter(x => Number.isFinite(x)).slice().sort((a, b) => a - b);
    if (!v.length) return null;
    const q1 = quantile(v, 0.25), q3 = quantile(v, 0.75), median = quantile(v, 0.5), iqr = q3 - q1;
    const inside = v.filter(x => x >= q1 - 1.5 * iqr && x <= q3 + 1.5 * iqr);
    return {q1, q3, median, low: inside[0], high: inside[inside.length - 1], n: v.length};
  }
  function csv(rows, columns) {
    function quote(value) {
      if (value === null || value === undefined) return '';
      let s = String(value);
      // Neutralize spreadsheet formula injection, including leading whitespace/tabs.
      if (typeof value === 'string' && /^[\t\r\n ]*[=+@\-]/.test(s)) s = "'" + s;
      return /[",\n\r]/.test(s) ? '"' + s.replaceAll('"', '""') + '"' : s;
    }
    return [columns.join(','), ...rows.map(r => columns.map(c => quote(r[c])).join(','))].join('\r\n');
  }
  scope.ImmuneCore = {populations, unpack, filterRows, isCohort, frequencies, comparisonValues, quantile, boxStats, csv};
  if (typeof module !== 'undefined' && module.exports) module.exports = scope.ImmuneCore;
})(globalThis);
