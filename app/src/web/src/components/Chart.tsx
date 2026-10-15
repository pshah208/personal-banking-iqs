/**
 * Dependency-free SVG charts.
 *
 * Hand-rolled for the same reason `Markdown.tsx` is: the numbers in an answer are
 * the substance of it, so nothing may rewrite them. A chart library would want to
 * reformat, round and locale-ise every value. Here the parsed number drives only
 * the *geometry* — every label printed on screen is the original token exactly as
 * the agent emitted it.
 *
 * Everything is a plain <svg> with a viewBox, so charts scale with their column
 * and need no resize observer.
 */

const PALETTE = [
  "var(--brand)", "#0f766e", "#7c3aed", "#b45309",
  "#1d4ed8", "#be185d", "#4d7c0f", "#0369a1",
];

export interface Datum {
  /** Row label, printed verbatim. */
  label: string;
  /** Parsed magnitude — drives geometry only. */
  value: number;
  /** The original cell text, printed verbatim as the value badge. */
  display: string;
}

function niceMax(v: number): number {
  if (v <= 0) return 1;
  const mag = Math.pow(10, Math.floor(Math.log10(v)));
  const norm = v / mag;
  const step = norm <= 1 ? 1 : norm <= 2 ? 2 : norm <= 5 ? 5 : 10;
  return step * mag;
}

/** Truncate a long label so the axis gutter stays readable. */
function clip(s: string, n = 26): string {
  return s.length > n ? `${s.slice(0, n - 1)}…` : s;
}

/* ------------------------------------------------------------------ bars --- */

export function BarChart({ data, caption }: { data: Datum[]; caption?: string }) {
  if (!data.length) return null;

  const rowH = 30;
  const gap = 8;
  const gutter = 168;
  const padRight = 92;
  const width = 640;
  const height = data.length * (rowH + gap) + 26;
  const max = niceMax(Math.max(...data.map((d) => Math.abs(d.value))));
  const plot = width - gutter - padRight;

  return (
    <figure className="chart chart-bar">
      <svg viewBox={`0 0 ${width} ${height}`} role="img"
           aria-label={caption || "Bar chart"} preserveAspectRatio="xMinYMin meet">
        {/* Gridlines at quarter steps, behind the bars. */}
        {[0.25, 0.5, 0.75, 1].map((f) => (
          <line
            key={f}
            x1={gutter + plot * f} x2={gutter + plot * f}
            y1={0} y2={height - 22}
            className="chart-grid"
          />
        ))}

        {data.map((d, i) => {
          const y = i * (rowH + gap);
          const w = Math.max(2, (Math.abs(d.value) / max) * plot);
          return (
            <g key={`${d.label}-${i}`} className="chart-row">
              <text x={gutter - 10} y={y + rowH / 2} className="chart-label"
                    textAnchor="end" dominantBaseline="middle">
                {clip(d.label)}
              </text>
              <rect x={gutter} y={y + 4} width={plot} height={rowH - 8}
                    rx={4} className="chart-track" />
              <rect x={gutter} y={y + 4} width={w} height={rowH - 8}
                    rx={4} fill={PALETTE[i % PALETTE.length]} className="chart-fill">
                <animate attributeName="width" from="0" to={w}
                         dur="0.5s" fill="freeze" />
              </rect>
              <text x={gutter + w + 10} y={y + rowH / 2} className="chart-value"
                    dominantBaseline="middle">
                {d.display}
              </text>
            </g>
          );
        })}

        {/* Axis floor + max marker. */}
        <line x1={gutter} x2={width - padRight} y1={height - 20} y2={height - 20}
              className="chart-axis" />
        <text x={gutter} y={height - 6} className="chart-tick">0</text>
      </svg>
      {caption && <figcaption>{caption}</figcaption>}
    </figure>
  );
}

/* ----------------------------------------------------------------- donut --- */

function arc(cx: number, cy: number, r: number, from: number, to: number): string {
  const p = (a: number) => [
    cx + r * Math.cos(a - Math.PI / 2),
    cy + r * Math.sin(a - Math.PI / 2),
  ];
  const [x1, y1] = p(from);
  const [x2, y2] = p(to);
  const large = to - from > Math.PI ? 1 : 0;
  return `M ${x1} ${y1} A ${r} ${r} 0 ${large} 1 ${x2} ${y2}`;
}

export function DonutChart({ data, caption }: { data: Datum[]; caption?: string }) {
  const total = data.reduce((s, d) => s + Math.abs(d.value), 0);
  if (!data.length || total <= 0) return null;

  const size = 200;
  const cx = size / 2;
  const cy = size / 2;
  const r = 74;
  let cursor = 0;

  const slices = data.map((d, i) => {
    const frac = Math.abs(d.value) / total;
    const from = cursor * Math.PI * 2;
    cursor += frac;
    const to = cursor * Math.PI * 2;
    return { d, i, frac, from, to: Math.min(to, Math.PI * 2 - 0.0001) };
  });

  return (
    <figure className="chart chart-donut">
      <div className="donut-wrap">
        <svg viewBox={`0 0 ${size} ${size}`} role="img"
             aria-label={caption || "Donut chart"} className="donut-svg">
          {slices.map((s) => (
            <path
              key={`${s.d.label}-${s.i}`}
              d={arc(cx, cy, r, s.from, s.to)}
              stroke={PALETTE[s.i % PALETTE.length]}
              className="donut-arc"
            />
          ))}
          <text x={cx} y={cy - 6} className="donut-total" textAnchor="middle">
            {data.length}
          </text>
          <text x={cx} y={cy + 13} className="donut-total-label" textAnchor="middle">
            {data.length === 1 ? "segment" : "segments"}
          </text>
        </svg>

        <ul className="donut-legend">
          {slices.map((s) => (
            <li key={`${s.d.label}-${s.i}`}>
              <span className="legend-swatch"
                    style={{ background: PALETTE[s.i % PALETTE.length] }} />
              <span className="legend-label">{s.d.label}</span>
              <span className="legend-value">{s.d.display}</span>
              <span className="legend-pct">{Math.round(s.frac * 100)}%</span>
            </li>
          ))}
        </ul>
      </div>
      {caption && <figcaption>{caption}</figcaption>}
    </figure>
  );
}

/* --------------------------------------------------------------- sparkbar --- */

/** Inline proportion bar drawn behind a table cell. */
export function CellBar({ fraction }: { fraction: number }) {
  const pct = Math.max(0, Math.min(1, fraction)) * 100;
  return (
    <span className="cell-bar" aria-hidden>
      <span className="cell-bar-fill" style={{ width: `${pct}%` }} />
    </span>
  );
}

export { PALETTE };
