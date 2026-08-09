// Charts. Global `Charts`. Thin layer over Chart.js (vendored in js/vendor).
//
// Screens never talk to Chart.js directly: colours, fonts and grid come from
// the design tokens, so a chart cannot drift away from the rest of the app when
// the Telegram theme changes. Every helper takes plain data and returns HTML for
// a <canvas>, then draws into it once the node is in the document.
//
// Rules kept here so no screen has to remember them:
//   * one measure per chart and one colour per series — length carries the value,
//     colour is spent only where it means "which one";
//   * no axis where a direct label is exact: the funnel and the ring label their
//     own marks;
//   * grid is a hairline in the token colour, never dashed, never on top;
//   * motion is off entirely for anyone who asked for that.
window.Charts = (() => {
  let seq = 0;
  const live = new Map();

  const token = (name, fallback) => {
    const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    return v || fallback;
  };
  const still = () => window.matchMedia
    && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  // Chart.js resolves CSS variables to nothing, so the values are read once per
  // draw and passed in as plain colours.
  const palette = () => ({
    accent: token('--accent', '#2563eb'),
    fg: token('--fg', '#131824'),
    muted: token('--muted', '#78828f'),
    hair: token('--hair', 'rgba(0,0,0,.12)'),
    surface: token('--surface', '#ffffff'),
    viz: [1, 2, 3, 4, 5].map((i) => token(`--viz-${i}`, '#2a78d6')),
  });

  const base = (p) => ({
    responsive: true,
    maintainAspectRatio: false,
    animation: still() ? false : { duration: 260 },
    font: { family: getComputedStyle(document.body).fontFamily },
    plugins: {
      legend: { display: false },
      tooltip: {
        backgroundColor: p.fg,
        titleColor: p.surface,
        bodyColor: p.surface,
        cornerRadius: 6,
        padding: 8,
        displayColors: false,
      },
    },
  });

  const axis = (p, opts = {}) => ({
    grid: { color: p.hair, drawTicks: false, drawBorder: false, ...opts.grid },
    border: { display: false },
    ticks: { color: p.muted, font: { size: 11 }, padding: 6, ...opts.ticks },
  });

  /** A canvas placeholder; `draw` fills it once it is in the document. */
  function slot(height) {
    const id = `chart-${++seq}`;
    return { id, html: `<div class="chart" style="height:${height}px"><canvas id="${id}"></canvas></div>` };
  }

  function draw(id, config) {
    const el = document.getElementById(id);
    if (!el || typeof Chart === 'undefined') return null;
    const old = live.get(id);
    if (old) old.destroy();
    const chart = new Chart(el.getContext('2d'), config);
    live.set(id, chart);
    return chart;
  }

  /** Trend over time: a line with a wash under it. */
  function line(points, { format, height = 150 }) {
    const s = slot(height);
    s.render = () => {
      const p = palette();
      draw(s.id, {
        type: 'line',
        data: {
          labels: points.map((x) => x.label),
          datasets: [{
            data: points.map((x) => x.value),
            borderColor: p.accent,
            backgroundColor: `color-mix(in srgb, ${p.accent} 12%, transparent)`,
            borderWidth: 2,
            fill: true,
            tension: 0.32,
            pointRadius: 4,
            pointHoverRadius: 6,
            pointBackgroundColor: p.accent,
            // A ring of surface keeps a marker legible where it sits on the line.
            pointBorderColor: p.surface,
            pointBorderWidth: 2,
          }],
        },
        options: {
          ...base(p),
          plugins: {
            ...base(p).plugins,
            tooltip: {
              ...base(p).plugins.tooltip,
              callbacks: { label: (c) => format(c.parsed.y) },
            },
          },
          scales: {
            x: axis(p, { grid: { display: false } }),
            y: axis(p, { ticks: { callback: (v) => format(v), maxTicksLimit: 4 } }),
          },
        },
      });
    };
    return s;
  }

  /** Part-to-whole: a ring, with the total in the middle. */
  function ring(rows, { centre, height = 148 }) {
    const s = slot(height);
    s.render = () => {
      const p = palette();
      const colours = rows.map((r, i) => (r.muted ? p.muted : p.viz[i % p.viz.length]));
      draw(s.id, {
        type: 'doughnut',
        data: {
          labels: rows.map((r) => r.label),
          datasets: [{
            data: rows.map((r) => r.value),
            backgroundColor: colours,
            // Segments are separated by surface, not by an outline.
            borderColor: p.surface,
            borderWidth: 3,
            hoverOffset: 0,
          }],
        },
        options: {
          ...base(p),
          cutout: '64%',
          plugins: {
            ...base(p).plugins,
            tooltip: {
              ...base(p).plugins.tooltip,
              callbacks: { label: (c) => `${c.label}: ${c.parsed}` },
            },
          },
        },
        plugins: centre ? [{
          id: 'centre',
          afterDraw(chart) {
            const { ctx, chartArea } = chart;
            const x = (chartArea.left + chartArea.right) / 2;
            const y = (chartArea.top + chartArea.bottom) / 2;
            const font = getComputedStyle(document.body).fontFamily;
            ctx.save();
            ctx.textAlign = 'center';
            ctx.fillStyle = p.fg;
            ctx.font = `800 26px ${font}`;
            ctx.fillText(centre.value, x, y);
            ctx.fillStyle = p.muted;
            ctx.font = `500 11px ${font}`;
            ctx.fillText(centre.label, x, y + 18);
            ctx.restore();
          },
        }] : [],
      });
    };
    return s;
  }

  /** Ordered magnitude: columns, value written on the cap. */
  function columns(rows, { height = 156, format }) {
    const s = slot(height);
    s.render = () => {
      const p = palette();
      draw(s.id, {
        type: 'bar',
        data: {
          labels: rows.map((r) => r.label),
          datasets: [{
            data: rows.map((r) => r.value),
            backgroundColor: p.accent,
            borderRadius: { topLeft: 4, topRight: 4, bottomLeft: 0, bottomRight: 0 },
            maxBarThickness: 26,
          }],
        },
        options: {
          ...base(p),
          layout: { padding: { top: 18 } },
          plugins: {
            ...base(p).plugins,
            tooltip: {
              ...base(p).plugins.tooltip,
              callbacks: { label: (c) => (format ? format(c.parsed.y) : String(c.parsed.y)) },
            },
          },
          scales: {
            x: axis(p, { grid: { display: false }, ticks: { color: p.muted } }),
            // A scale on the left, so the columns stand in a measured space
            // rather than floating in an empty card. The cap labels stay: they
            // are exact where a gridline is a guess.
            y: axis(p, { beginAtZero: true, ticks: { maxTicksLimit: 4, precision: 0 } }),
          },
        },
        plugins: [{
          id: 'caps',
          afterDatasetsDraw(chart) {
            const ctx = chart.ctx;
            const font = getComputedStyle(document.body).fontFamily;
            ctx.save();
            ctx.fillStyle = p.fg;
            ctx.font = `700 13px ${font}`;
            ctx.textAlign = 'center';
            chart.getDatasetMeta(0).data.forEach((bar, i) => {
              const v = rows[i].value;
              ctx.fillText(format ? format(v) : String(v), bar.x, bar.y - 8);
            });
            ctx.restore();
          },
        }],
      });
    };
    return s;
  }

  /** Compare named things: horizontal bars, one colour, value at the tip. */
  function bars(rows, { height, format, note }) {
    const s = slot(height || Math.max(84, rows.length * 32 + 14));
    s.render = () => {
      const p = palette();
      draw(s.id, {
        type: 'bar',
        data: {
          labels: rows.map((r) => r.label),
          datasets: [{
            data: rows.map((r) => r.value),
            backgroundColor: p.accent,
            borderRadius: { topRight: 4, bottomRight: 4, topLeft: 0, bottomLeft: 0 },
            maxBarThickness: 13,
          }],
        },
        options: {
          ...base(p),
          indexAxis: 'y',
          layout: { padding: { right: 56 } },
          plugins: {
            ...base(p).plugins,
            tooltip: {
              ...base(p).plugins.tooltip,
              callbacks: {
                label: (c) => {
                  const money = format ? format(c.parsed.x) : String(c.parsed.x);
                  const extra = note && note(rows[c.dataIndex]);
                  return extra ? [money, extra] : money;
                },
              },
            },
          },
          scales: {
            x: { display: false, beginAtZero: true },
            y: axis(p, { grid: { display: false }, ticks: { color: p.fg, font: { size: 13 } } }),
          },
        },
        plugins: [{
          id: 'tips',
          afterDatasetsDraw(chart) {
            const ctx = chart.ctx;
            const font = getComputedStyle(document.body).fontFamily;
            ctx.save();
            ctx.fillStyle = p.fg;
            ctx.font = `700 13px ${font}`;
            ctx.textAlign = 'left';
            ctx.textBaseline = 'middle';
            chart.getDatasetMeta(0).data.forEach((bar, i) => {
              const v = rows[i].value;
              ctx.fillText(format ? format(v) : String(v), bar.x + 8, bar.y);
            });
            ctx.restore();
          },
        }],
      });
    };
    return s;
  }

  /** Draw everything a screen just rendered, and forget charts that are gone. */
  const paint = (...slots) => {
    live.forEach((chart, id) => {
      if (!document.getElementById(id)) { chart.destroy(); live.delete(id); }
    });
    slots.filter(Boolean).forEach((s) => s.render && s.render());
  };

  return { line, ring, columns, bars, paint };
})();
