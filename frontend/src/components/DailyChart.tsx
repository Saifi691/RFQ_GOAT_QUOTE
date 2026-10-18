import { useState } from "react";
import type { DailyPoint } from "../api";
import { count, longDay, niceTicks, shortDay } from "../format";
import { useWidth } from "./useWidth";

const SERIES = [
  { key: "received", label: "Emails received", color: "var(--series-1)" },
  { key: "replied", label: "RFQs sent", color: "var(--series-2)" },
] as const;

const HEIGHT = 220;
const MARGIN = { top: 12, right: 8, bottom: 26, left: 32 };

/** Column with a 4px rounded data-end and a square baseline. */
function column(x: number, y: number, width: number, height: number) {
  const r = Math.min(4, height, width / 2);
  return `M${x},${y + height} V${y + r} Q${x},${y} ${x + r},${y} H${x + width - r} Q${x + width},${y} ${x + width},${y + r} V${y + height} Z`;
}

export function DailyChart({ data }: { data: DailyPoint[] }) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);
  const [showTable, setShowTable] = useState(false);

  const max = Math.max(1, ...data.flatMap((d) => [d.received, d.replied]));
  const ticks = niceTicks(max);
  const top = ticks[ticks.length - 1];
  const plotW = Math.max(100, width - MARGIN.left - MARGIN.right);
  const plotH = HEIGHT - MARGIN.top - MARGIN.bottom;
  const band = plotW / data.length;
  const gap = 2; // surface gap between the two touching columns
  const barW = Math.max(2, Math.min(24, (band * 0.72 - gap) / 2));
  const y = (value: number) => MARGIN.top + plotH - (value / top) * plotH;
  const labelEvery = Math.max(1, Math.ceil(data.length / Math.max(1, Math.floor(plotW / 56))));
  const total = data.reduce((sum, d) => ({ received: sum.received + d.received, replied: sum.replied + d.replied }),
    { received: 0, replied: 0 });

  const hovered = hover == null ? null : data[hover];
  // Beside the hovered day, never on top of its columns: flip to the left near the right edge.
  const TOOLTIP_W = 170;
  const rightOfBand = hover == null ? 0 : MARGIN.left + band * (hover + 1) + 8;
  const tooltipLeft = hover == null ? 0
    : rightOfBand + TOOLTIP_W <= width ? rightOfBand : Math.max(0, MARGIN.left + band * hover - TOOLTIP_W - 8);

  return (
    <div className="card">
      <div className="card-head">
        <div>
          <h2>Emails received and RFQs sent</h2>
          <p className="sub">Per day · {count(total.received)} received, {count(total.replied)} sent</p>
        </div>
        <div className="legend" aria-label="Legend">
          {SERIES.map((s) => (
            <span key={s.key}><i className="swatch" style={{ background: s.color }} />{s.label}</span>
          ))}
        </div>
      </div>
      <div className="chart" ref={ref} onMouseLeave={() => setHover(null)}>
        <svg height={HEIGHT} role="img"
          aria-label={`Daily emails received and RFQs sent over ${data.length} days: ${total.received} received, ${total.replied} sent.`}>
          {ticks.map((tick) => (
            <g key={tick}>
              <line x1={MARGIN.left} x2={MARGIN.left + plotW} y1={y(tick)} y2={y(tick)}
                stroke={tick === 0 ? "var(--axis)" : "var(--grid)"} strokeWidth={1} />
              <text className="tick-label" x={MARGIN.left - 6} y={y(tick)} dy="0.32em" textAnchor="end">{count(tick)}</text>
            </g>
          ))}
          {data.map((d, i) => {
            const center = MARGIN.left + band * i + band / 2;
            return (
              <g key={d.day}>
                {hover === i && (
                  <rect x={MARGIN.left + band * i} y={MARGIN.top} width={band} height={plotH} fill="var(--surface-2)" />
                )}
                {SERIES.map((s, k) => {
                  const value = d[s.key];
                  if (!value) return null;
                  const x = center - barW - gap / 2 + k * (barW + gap);
                  return <path key={s.key} d={column(x, y(value), barW, y(0) - y(value))} fill={s.color} />;
                })}
                {i % labelEvery === 0 && (
                  <text x={center} y={HEIGHT - 8} textAnchor="middle">{shortDay(d.day)}</text>
                )}
                {/* Hit target: the whole day band, larger than the marks. */}
                <rect x={MARGIN.left + band * i} y={MARGIN.top} width={band} height={plotH + MARGIN.bottom}
                  fill="transparent" onMouseEnter={() => setHover(i)} />
              </g>
            );
          })}
        </svg>
        {hovered && (
          <div className="tooltip" style={{ left: tooltipLeft, top: 8 }}>
            <div className="t-title">{longDay(hovered.day)}</div>
            {SERIES.map((s) => (
              <div className="t-row" key={s.key}>
                <span><i className="swatch" style={{ background: s.color }} /> {s.label}</span>
                <b>{count(hovered[s.key])}</b>
              </div>
            ))}
          </div>
        )}
      </div>
      <button className="link" onClick={() => setShowTable(!showTable)}>{showTable ? "Hide table" : "Show as table"}</button>
      {showTable && (
        <div className="table-wrap">
          <table>
            <thead><tr><th>Day</th><th className="r">Emails received</th><th className="r">RFQs sent</th></tr></thead>
            <tbody>
              {data.filter((d) => d.received || d.replied).map((d) => (
                <tr key={d.day}><td>{longDay(d.day)}</td><td className="r">{d.received}</td><td className="r">{d.replied}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
