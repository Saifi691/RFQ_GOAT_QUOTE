import { useState } from "react";
import type { Metrics } from "../api";
import { count, percent } from "../format";
import { useWidth } from "./useWidth";

const ROWS = [
  { key: "website", label: "ferguson.com", hint: "Live product page" },
  { key: "api", label: "Product service", hint: "Ferguson internal product-info API" },
  { key: "pdf", label: "Spec sheet PDF", hint: "Manufacturer document" },
  { key: "catalog", label: "Backup catalog", hint: "Fallback, 2026-09-24 snapshot" },
] as const;

const LABEL_W = 120;
const VALUE_W = 92;
const ROW_H = 44;
const BAR_H = 20;

/** Bar with a 4px rounded data-end and a square baseline. */
function bar(x: number, y: number, width: number, height: number) {
  const r = Math.min(4, width, height / 2);
  return `M${x},${y} H${x + width - r} Q${x + width},${y} ${x + width},${y + r} V${y + height - r} Q${x + width},${y + height} ${x + width - r},${y + height} H${x} Z`;
}

export function SourceChart({ sources }: { sources: Metrics["sources"] }) {
  const [ref, width] = useWidth<HTMLDivElement>(360);
  const [hover, setHover] = useState<number | null>(null);
  const [showTable, setShowTable] = useState(false);
  const total = sources.website + (sources.api ?? 0) + sources.pdf + sources.catalog;
  const max = Math.max(1, sources.website, sources.api ?? 0, sources.pdf, sources.catalog);
  const plotW = Math.max(60, width - LABEL_W - VALUE_W);
  const height = ROWS.length * ROW_H;
  const share = (value: number) => (total ? (value / total) * 100 : 0);

  return (
    <div className="card">
      <div className="card-head">
        <div>
          <h2>Where the values came from</h2>
          <p className="sub">{count(total)} filled values, in priority order</p>
        </div>
      </div>
      {total === 0 ? (
        <div className="empty">No product values recorded yet.</div>
      ) : (
        <div className="chart" ref={ref} onMouseLeave={() => setHover(null)}>
          <svg height={height} role="img"
            aria-label={ROWS.map((r) => `${r.label}: ${sources[r.key]} values`).join("; ")}>
            <line x1={LABEL_W} x2={LABEL_W} y1={0} y2={height} stroke="var(--axis)" strokeWidth={1} />
            {ROWS.map((row, i) => {
              const value = sources[row.key];
              const w = (value / max) * plotW;
              const top = i * ROW_H + (ROW_H - BAR_H) / 2;
              return (
                <g key={row.key} onMouseEnter={() => setHover(i)}>
                  <rect x={0} y={i * ROW_H} width={width} height={ROW_H}
                    fill={hover === i ? "var(--surface-2)" : "transparent"} />
                  <text x={0} y={i * ROW_H + ROW_H / 2} dy="0.32em" style={{ fill: "var(--text-secondary)", fontSize: 13 }}>
                    {row.label}
                  </text>
                  {value > 0 && <path d={bar(LABEL_W, top, Math.max(w, 2), BAR_H)} fill="var(--series-1)" />}
                  <text className="tick-label" x={LABEL_W + w + 8} y={i * ROW_H + ROW_H / 2} dy="0.32em"
                    style={{ fill: "var(--text-primary)", fontSize: 12 }}>
                    {count(value)} · {percent(share(value))}
                  </text>
                </g>
              );
            })}
          </svg>
          {hover != null && (
            <div className="tooltip" style={{ left: LABEL_W + 8, top: hover * ROW_H + ROW_H - 4 }}>
              <div className="t-title">{ROWS[hover].label}</div>
              <div className="t-row"><span>{ROWS[hover].hint}</span></div>
              <div className="t-row"><span>Values</span><b>{count(sources[ROWS[hover].key])}</b></div>
              <div className="t-row"><span>Share</span><b>{percent(share(sources[ROWS[hover].key]), 1)}</b></div>
            </div>
          )}
        </div>
      )}
      <button className="link" onClick={() => setShowTable(!showTable)}>{showTable ? "Hide table" : "Show as table"}</button>
      {showTable && (
        <table>
          <thead><tr><th>Source</th><th className="r">Values</th><th className="r">Share</th></tr></thead>
          <tbody>
            {ROWS.map((r) => (
              <tr key={r.key}><td>{r.label}</td><td className="r">{sources[r.key]}</td><td className="r">{percent(share(sources[r.key]), 1)}</td></tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
